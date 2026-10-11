# -*- coding: utf-8 -*-
"""AI 設計計畫（新架構規格第 9 節）：在知識底稿上取捨，判斷只做一次。

D1 章節與端到端流程 → D2 底稿列歸屬（依模組分批）→ D3 故事、角色、資料需求、待決事項
→ D4 排除（依規則彙整，不問 AI）→ D5 成本與品質（依單價計算）→ D6 自我檢查（A1～A3，未歸屬的重問）
→ 試寫（文字）與自審。

★ 審閱者鎖定或確認過的項目、鎖定的底稿列，AI 修訂時一律保留。
★ 修訂與分期版本：沿用前一版的項目，只對新增的底稿列與意見做判斷。
"""
import hashlib
import html as html_mod
import json
import logging
import re

from odoo import _, api, fields, models

from ..services import hub_client, txn

_logger = logging.getLogger(__name__)

BATCH = 150
MAX_D2_RETRY = 2


def _slug(text, prefix):
    s = re.sub(r'[^a-z0-9_]+', '_', str(text or '').lower()).strip('_')
    return s[:40] or prefix


class KnowledgePlanDesign(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def _plan_enqueue_design(self):
        self.ensure_one()
        if txn.in_tests(self.env) and not self.env.context.get('knowledge_plan_design_inline'):
            return False
        if self.env.context.get('knowledge_plan_design_inline'):
            return self._plan_design_run()
        return self.env['corpaas.knowledge.ai'].enqueue(self, '_plan_design_run', self.package_id,
                                                        note=_('AI 設計說明書製作計畫'))

    def action_ai_revise(self):
        """依「審閱意見」修訂：保留鎖定與確認過的項目，其餘重新設計。"""
        for rec in self:
            rec._check_editable()
            rec.with_context(knowledge_plan_system=True).write({'state': 'draft'})
            rec._plan_enqueue_design()
        return True

    def _plan_design_run(self):
        """AI 工作：D1～D6＋試寫，完成後進入審閱（或依自動化等級自動核准）。"""
        self.ensure_one()
        plan = self.sudo().with_context(knowledge_plan_system=True)
        pack = plan._design_pack()
        plan.design_pack = json.dumps(pack, ensure_ascii=False)
        # ★ 只有內容指示的修訂（沒有審閱意見、沒有新的未歸屬功能點）：沿用前一版的設計，不重新問 AI
        light = bool(plan.parent_id) and not (plan.review_notes or '').strip() and not plan.lines_unassigned
        if not light:
            plan._d1_chapters(pack)
            plan._d2_assign(pack)
            plan._d3_story_roles_data(pack)
        plan._d4_exclusions()
        plan._d5_cost_quality()
        for _i in range(MAX_D2_RETRY):
            if not plan.lines_unassigned:
                break
            plan._d2_assign(pack, only_unassigned=True)
        plan._mark_changes()
        if not light:
            try:
                plan._plan_trial(pack)
            except hub_client.HubError as e:
                _logger.warning('[knowledge] 試寫略過：%s', e)
        plan.write({'state': 'review'})
        plan.message_post(body=_('AI 已設計計畫：%(c)s 章、入選 %(a)s 個功能點，預估 $%(e).2f',
                                 c=len(plan.live_items('chapter')), a=plan.lines_chapter,
                                 e=plan.cost_estimate or 0))
        plan._plan_try_auto_approve()
        return True

    # ------------------------------------------------------------------
    # 計畫設計輸入包
    # ------------------------------------------------------------------
    def _source_brief(self):
        """來源簡述（產品來源）。建議書模組覆寫，依建議書版本快照產生。"""
        self.ensure_one()
        pkg = self.package_id
        tmpl = pkg.product_tmpl_id
        brief = (pkg.knowledge_target_brief or '').strip() or \
            (tmpl.description_sale or tmpl.description or '').strip()
        return {'type': 'product', 'package': pkg.display_name, 'brief': brief[:3000]}

    def _design_pack(self):
        self.ensure_one()
        pkg = self.package_id
        groups = {}
        for line in self.line_ids.filtered(lambda l: l.assignment != 'exclude' or not l.by_rule):
            key = (line.module, line.flow_id.id or 0)
            g = groups.setdefault(key, {'module': line.module,
                                        'flow': line.flow_id.name if line.flow_id else None,
                                        'count': 0, 'usage': 0.0, 'examples': []})
            g['count'] += 1
            g['usage'] += line.usage or 0
            g['examples'].append((line.usage or 0, line.feature_id.name))
        group_rows = []
        for g in sorted(groups.values(), key=lambda x: -x['usage']):
            g['examples'] = [n for _u, n in sorted(g['examples'], reverse=True)[:6]]
            g['usage'] = round(g['usage'], 1)
            group_rows.append(g)
        flows = {f.model: f.name for f in self.env['corpaas.knowledge.flow'].sudo().search(
            [('package_ids', 'in', pkg.id)])}
        paths = [[flows.get(m, m) for m in p] for p in self._ledger_paths()]
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        library = [{'code': c.code, 'name': c.name, 'pain': c.pain, 'outcome': c.outcome}
                   for c in Cap.search([('code', '!=', False)])][:80]
        base = [('package_ids', 'in', pkg.id), ('missing', '=', False)]
        try:
            avail = pkg._knowledge_role_groups(base)
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge] 讀可用群組失敗：%s', e)
            avail = []
        packs = []
        for p in self.env['corpaas.knowledge.seed_pack'].sudo().search([]):
            try:
                ms = sorted({r.get('model') for r in json.loads(p.seed_json or '[]') if isinstance(r, dict)})
            except ValueError:
                ms = []
            packs.append({'code': p.code, 'name': p.name, 'models': ms[:30]})
        roles = [{'code': r.code, 'name': r.name, 'groups': (r.group_xmlids or '').split()}
                 for r in self.env['corpaas.knowledge.role'].sudo().search([])]
        profile = pkg._knowledge_profile()
        prev = {}
        if self.parent_id:
            prev = {'chapters': [{'key': i.key, 'name': i.name, **i.content()}
                                 for i in self.parent_id.live_items('chapter')],
                    'story': self.parent_id.story()}
        return {
            'source': self._source_brief(),
            'modules': [{'module': m.module, 'category': m.category, 'origin': m.origin,
                         'features': m.feature_count, 'summarized': m.summarized}
                        for m in self.module_ids if m.category != 'tech'],
            'groups_summary': group_rows[:120],
            'paths': paths,
            'module_briefs': pkg._knowledge_module_brief(),
            'library': library,
            'groups': avail,
            'role_templates': roles,
            'packs': packs,
            'limits': {'max_scenarios': profile.get('max_scenarios'), 'reader': self.reader,
                       'budget': self.budget},
            'warnings': [r for r in (self.t1_check_id.results() if self.t1_check_id else [])
                         if r.get('state') != 'pass'],
            'previous': prev,
            'notes': self.review_notes or '',
            'instructions': [{'key': i.key, 'name': i.name, **i.content()}
                             for i in self.live_items('instruction')],
        }

    def _ask(self, prompt, check):
        data, errors = self.env['corpaas.knowledge.ai'].ask_checked(
            'plan_design', prompt, check, package=self.package_id, record=self)
        if errors:
            _logger.info('[knowledge] 計畫設計回覆仍有問題：%s', errors[:5])
        return data or {}

    def _keep(self, kind):
        """這一類裡人鎖定／確認過的項目（AI 修訂不能動）。"""
        return self.item_ids.filtered(lambda i: i.kind == kind and (i.locked or i.confirmed))

    def _upsert_items(self, kind, rows):
        """以 key 合併 AI 的輸出：鎖定／確認的不動；這一類沒出現在輸出裡、也沒鎖定的刪掉。"""
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        keep = self._keep(kind)
        seen = set(keep.mapped('key'))
        for seq, row in enumerate(rows, 1):
            key = row['key']
            if key in seen:
                continue
            seen.add(key)
            vals = {'name': row['name'][:200], 'summary': row.get('summary') or False,
                    'evidence': row.get('evidence') or False,
                    'confidence': row.get('confidence') if row.get('confidence') in ('high', 'medium', 'low')
                    else 'medium',
                    'content_json': json.dumps(row.get('content') or {}, ensure_ascii=False),
                    'sequence': seq}
            item = self.item_ids.filtered(lambda i: i.kind == kind and i.key == key)[:1]
            if item:
                item.write(vals)
            else:
                Item.create(dict(vals, plan_id=self.id, kind=kind, key=key))
        stale = self.item_ids.filtered(lambda i: i.kind == kind and i.key not in seen
                                       and not (i.locked or i.confirmed))
        stale.unlink()

    # ------------------------------------------------------------------
    # D1 章節與流程
    # ------------------------------------------------------------------
    def _d1_chapters(self, pack):
        lib = {c['code'] for c in pack['library']}
        keep = [{'key': i.key, 'name': i.name, **i.content()} for i in self._keep('chapter')]

        def check(data):
            errs = []
            chs = (data or {}).get('chapters')
            if not isinstance(chs, list) or not (1 <= len(chs) <= 20):
                return ['chapters 要 1～20 章']
            keys = set()
            for c in chs:
                if not isinstance(c, dict) or not c.get('key') or not c.get('name'):
                    errs.append('每章都要有 key 與 name')
                    continue
                if c['key'] in keys:
                    errs.append('章節 key 重複：%s' % c['key'])
                keys.add(c['key'])
                if c.get('library_code') and c['library_code'] not in lib:
                    errs.append('範本庫沒有能力 %s' % c['library_code'])
            return errs
        prompt = (
            "你在設計一本 Odoo 操作說明書的「製作計畫」。依下面整理好的知識底稿，定出章節（能力）與端到端流程。\n"
            "規則：\n"
            "1. 章節是使用者要完成的業務能力（例如「報價與接單」），不是選單名稱；依模組摘要的商業邏輯與流程交接劃分。\n"
            "2. 範本庫裡有合適的能力就沿用（library_code 填它的 code、名稱可沿用），不要另取近似名稱。\n"
            "3. 每章寫痛點（pain）與成果（outcome），標必寫 must 或選寫 optional；列出涵蓋的模組與流程。\n"
            "4. 端到端流程從「候選路徑」挑 3～6 條，寫起點→終點與關鍵前提，指到所屬章節。\n"
            "5. 依據（evidence）寫你用了哪個模組摘要、哪條路徑；把握不高的 confidence 給 low。\n"
            "6. 已鎖定的章節原樣保留（不要改它們的 key）：%s\n"
            "7. 有前一版時以前一版章節為基礎，只在理由充分時增刪；審閱意見要照辦：%s\n"
            "格式：{\"chapters\":[{\"key\":英數,\"name\":…,\"pain\":…,\"outcome\":…,\"priority\":\"must\"|\"optional\","
            "\"library_code\":…|null,\"modules\":[…],\"evidence\":…,\"confidence\":\"high\"|\"medium\"|\"low\"}],"
            "\"flows\":[{\"key\":英數,\"name\":…,\"path\":[…],\"chapter\":章節key,\"premise\":…,\"evidence\":…}]}\n\n"
            "來源：%s\n\n關聯模組：%s\n\n底稿分組（模組×流程，數量與代表功能點）：%s\n\n候選路徑：%s\n\n"
            "模組摘要：%s\n\n範本庫能力：%s\n\n前一版：%s"
        ) % (json.dumps(keep, ensure_ascii=False), pack['notes'] or '（無）',
             json.dumps(pack['source'], ensure_ascii=False),
             json.dumps(pack['modules'], ensure_ascii=False)[:6000],
             json.dumps(pack['groups_summary'], ensure_ascii=False)[:20000],
             json.dumps(pack['paths'], ensure_ascii=False)[:3000],
             json.dumps(pack['module_briefs'], ensure_ascii=False)[:12000],
             json.dumps(pack['library'], ensure_ascii=False)[:6000],
             json.dumps(pack['previous'], ensure_ascii=False)[:6000])
        data = self._ask(prompt, check)
        rows = []
        for c in data.get('chapters') or []:
            if not isinstance(c, dict) or not c.get('key') or not c.get('name'):
                continue
            rows.append({'key': _slug(c['key'], 'ch'), 'name': c['name'],
                         'summary': '%s → %s' % (c.get('pain') or '', c.get('outcome') or ''),
                         'evidence': c.get('evidence'), 'confidence': c.get('confidence'),
                         'content': {k: c.get(k) for k in ('pain', 'outcome', 'priority', 'library_code', 'modules')}})
        self._upsert_items('chapter', rows)
        chapter_keys = set(self.live_items('chapter').mapped('key'))
        frows = []
        for f in data.get('flows') or []:
            if not isinstance(f, dict) or not f.get('key') or not f.get('name'):
                continue
            ch = _slug(f.get('chapter'), '')
            frows.append({'key': _slug(f['key'], 'fl'), 'name': f['name'],
                          'summary': ' → '.join(str(x) for x in f.get('path') or []),
                          'evidence': f.get('evidence'), 'confidence': 'medium' if ch in chapter_keys else 'low',
                          'content': {'path': f.get('path') or [], 'chapter': ch if ch in chapter_keys else None,
                                      'premise': f.get('premise')}})
        self._upsert_items('flow', frows)

    # ------------------------------------------------------------------
    # D2 歸屬
    # ------------------------------------------------------------------
    def _d2_assign(self, pack, only_unassigned=False):
        chapters = self.live_items('chapter')
        if not chapters:
            return
        by_key = {c.key: c for c in chapters}
        lines = self.line_ids.filtered(lambda l: not l.locked and not l.by_rule)
        if only_unassigned or self.parent_id:
            lines = lines.filtered(lambda l: l.assignment == 'unassigned')
        lines = lines.sorted(lambda l: (l.module or '', l.flow_id.id or 0, -(l.usage or 0)))
        Line = self.env['corpaas.knowledge.scope_line'].sudo().with_context(knowledge_plan_system=True)
        ch_info = [{'key': c.key, 'name': c.name, 'modules': c.content().get('modules') or []} for c in chapters]
        for i in range(0, len(lines), BATCH):
            batch = lines[i:i + BATCH]
            ids = set(batch.ids)

            def check(data, ids=ids):
                rows = (data or {}).get('rows')
                if not isinstance(rows, list):
                    return ['rows 要是陣列']
                got = {r.get('id') for r in rows if isinstance(r, dict)}
                errs = []
                miss = ids - got
                if miss:
                    errs.append('還有 %s 列沒有回覆（id：%s）' % (len(miss), sorted(miss)[:20]))
                bad = [r.get('a') for r in rows if isinstance(r, dict)
                       and r.get('a') not in by_key and r.get('a') not in ('exclude', 'next')]
                if bad:
                    errs.append('歸屬只能是章節 key、exclude 或 next：%s' % bad[:10])
                return errs
            prompt = (
                "把下面每個功能點歸到一個章節（填章節 key），或 exclude（不寫，附原因），或 next（下期再寫，附原因）。\n"
                "規則：每一列都要回覆；畫面屬於哪個業務能力就歸哪章；純技術、重複、讀者用不到的才 exclude；"
                "把握不高 c 給 low。\n"
                "格式：{\"rows\":[{\"id\":…,\"a\":章節key|\"exclude\"|\"next\",\"reason\":…,\"c\":\"high\"|\"medium\"|\"low\"}]}\n\n"
                "章節：%s\n\n功能點：%s"
            ) % (json.dumps(ch_info, ensure_ascii=False),
                 json.dumps([{'id': l.id, 'name': l.feature_id.name, 'kind': l.kind, 'module': l.module,
                              'flow': l.flow_id.name if l.flow_id else None,
                              'menu': l.feature_id.menu_path, 'usage': round(l.usage or 0, 1)}
                             for l in batch], ensure_ascii=False))
            data = self._ask(prompt, check)
            for r in data.get('rows') or []:
                if not isinstance(r, dict) or r.get('id') not in ids:
                    continue
                line = Line.browse(r['id'])
                a = r.get('a')
                conf = r.get('c') if r.get('c') in ('high', 'medium', 'low') else 'medium'
                if a in by_key:
                    line.write({'assignment': 'chapter', 'item_id': by_key[a].id,
                                'reason': (r.get('reason') or '')[:200], 'confidence': conf})
                elif a in ('exclude', 'next'):
                    line.write({'assignment': a, 'item_id': False,
                                'reason': (r.get('reason') or '')[:200], 'confidence': conf})

    # ------------------------------------------------------------------
    # D3 故事、角色、資料需求、待決事項
    # ------------------------------------------------------------------
    def _d3_story_roles_data(self, pack):
        allowed = {g.split('｜')[0] for g in pack['groups']}
        chapter_keys = set(self.live_items('chapter').mapped('key'))
        in_scope = self.line_ids.filtered(lambda l: l.assignment == 'chapter')
        models_needed = sorted({l.feature_id.model for l in in_scope if l.feature_id.model})

        def check(data):
            errs = []
            st = (data or {}).get('story')
            if not isinstance(st, dict) or not st.get('company') or not st.get('narrative'):
                errs.append('story 要有 company 與 narrative')
            for r in (data or {}).get('roles') or []:
                for g in (r or {}).get('groups') or []:
                    if allowed and g not in allowed and g != 'base.group_system':
                        errs.append('角色 %s 的群組 %s 不在可用群組裡' % (r.get('key'), g))
            if not (data or {}).get('roles'):
                errs.append('roles 不能是空的')
            if not (data or {}).get('data'):
                errs.append('data（資料需求）不能是空的')
            if len((data or {}).get('questions') or []) > 5:
                errs.append('questions 最多 5 題')
            return errs
        keep_story = self._keep('story')
        prompt = (
            "為這本說明書定出：(1) 公司故事：一家虛構公司（不得與真實公司或品牌同名）貫穿所有章節，"
            "寫公司名、規模、一句話營運模式、150–300 字敘事、用語對照（系統原詞→這個行業的說法，最多 10 條）、"
            "寫作規則（最多 5 條）；(2) 拍畫面用的角色：每個角色 key（英數）、中文名稱、groups 只能從「可用群組」挑"
            "（「｜」前那段）、負責哪些章節；讀者是%s，挑使用者等級群組，不要多公司、多幣別這類會改變畫面的群組；"
            "admin 角色固定用 base.group_system；(3) 資料需求：拍這些章節需要哪些單據、準備到什麼狀態、大約幾筆，"
            "優先用示範資料包涵蓋的模型；(4) 待決事項：你不確定、需要人回答的問題，最多 5 題，沒有就空陣列。\n"
            "已鎖定的故事原樣保留：%s\n審閱意見：%s\n內容指示（上線後意見）：%s\n"
            "格式：{\"story\":{\"company\":…,\"scale\":…,\"model\":…,\"narrative\":…,\"glossary\":{原詞:說法},"
            "\"rules\":[…],\"confidence\":\"high\"|\"medium\"|\"low\"},"
            "\"roles\":[{\"key\":…,\"name\":…,\"groups\":[…],\"chapters\":[章節key]}],"
            "\"data\":[{\"key\":…,\"model\":…,\"state\":…,\"count\":數字,\"chapter\":章節key,\"note\":…}],"
            "\"questions\":[{\"key\":…,\"question\":…,\"why\":…}]}\n\n"
            "來源：%s\n\n章節：%s\n\n入選畫面用到的模型：%s\n\n可用群組：%s\n\n既有角色範本：%s\n\n"
            "示範資料包：%s\n\n前一版故事：%s"
        ) % (dict(self._fields['reader'].selection).get(self.reader),
             json.dumps([i.content() for i in keep_story], ensure_ascii=False),
             pack['notes'] or '（無）', json.dumps(pack['instructions'], ensure_ascii=False)[:3000],
             json.dumps(pack['source'], ensure_ascii=False),
             json.dumps([{'key': c.key, 'name': c.name, 'summary': c.summary}
                         for c in self.live_items('chapter')], ensure_ascii=False),
             json.dumps(models_needed, ensure_ascii=False)[:4000],
             json.dumps(pack['groups'], ensure_ascii=False)[:12000],
             json.dumps(pack['role_templates'], ensure_ascii=False)[:4000],
             json.dumps(pack['packs'], ensure_ascii=False)[:8000],
             json.dumps((pack['previous'] or {}).get('story') or {}, ensure_ascii=False)[:3000])
        data = self._ask(prompt, check)
        st = data.get('story') if isinstance(data.get('story'), dict) else {}
        if st:
            self._upsert_items('story', [{
                'key': 'story', 'name': st.get('company') or _('公司故事'),
                'summary': st.get('narrative'), 'confidence': st.get('confidence'),
                'content': {k: st.get(k) for k in ('company', 'scale', 'model', 'narrative', 'glossary', 'rules')}}])
        roles = []
        has_admin = False
        for r in data.get('roles') or []:
            if not isinstance(r, dict) or not r.get('key'):
                continue
            key = _slug(r['key'], 'role')
            has_admin = has_admin or key == 'admin'
            groups = [g for g in r.get('groups') or [] if isinstance(g, str) and (not allowed or g in allowed
                                                                                or g == 'base.group_system')]
            roles.append({'key': key, 'name': r.get('name') or key, 'summary': '、'.join(groups),
                          'content': {'groups': groups or (['base.group_system'] if key == 'admin' else []),
                                      'chapters': [c for c in r.get('chapters') or [] if c in chapter_keys]}})
        if not has_admin:
            roles.append({'key': 'admin', 'name': _('系統管理員'), 'summary': 'base.group_system',
                          'confidence': 'high', 'content': {'groups': ['base.group_system'], 'chapters': []}})
        self._upsert_items('role', roles)
        drows = []
        for d in data.get('data') or []:
            if not isinstance(d, dict) or not d.get('model'):
                continue
            drows.append({'key': _slug(d.get('key') or d['model'], 'data'),
                          'name': '%s（%s）' % (d['model'], d.get('state') or _('任何狀態')),
                          'summary': d.get('note'),
                          'content': {k: d.get(k) for k in ('model', 'state', 'count', 'chapter', 'note')}})
        self._upsert_items('data', drows)
        qrows = []
        for q in (data.get('questions') or [])[:5]:
            if isinstance(q, dict) and q.get('question'):
                qrows.append({'key': _slug(q.get('key') or q['question'][:20], 'q'), 'name': q['question'][:200],
                              'summary': q.get('why'), 'confidence': 'low', 'content': {}})
        self._upsert_items('question', qrows)

    # ------------------------------------------------------------------
    # D4 排除（依原因彙整，不問 AI）
    # ------------------------------------------------------------------
    def _d4_exclusions(self):
        groups = {}
        for line in self.line_ids.filtered(lambda l: l.assignment in ('exclude', 'next')):
            reason = (line.reason or _('未說明')).strip()
            groups.setdefault((line.assignment, reason), []).append(line)
        rows = []
        for (a, reason), lines in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            rows.append({'key': 'ex_%s_%s' % (a, hashlib.md5(reason.encode('utf-8')).hexdigest()[:8]),
                         'name': '%s：%s（%s 個）' % (_('下期') if a == 'next' else _('排除'), reason[:80], len(lines)),
                         'confidence': 'high',
                         'content': {'assignment': a, 'reason': reason, 'count': len(lines),
                                     'examples': [l.feature_id.name for l in lines[:8]]}})
        self._upsert_items('exclusion', rows)

    # ------------------------------------------------------------------
    # D5 成本與品質
    # ------------------------------------------------------------------
    def _d5_cost_quality(self):
        Ai = self.env['corpaas.knowledge.ai']
        icp = self.env['ir.config_parameter'].sudo()
        n = self.lines_chapter
        explore_ratio = float(icp.get_param('corpaas_knowledge.plan_explore_ratio') or 0.4)
        repair_ratio = float(icp.get_param('corpaas_knowledge.plan_repair_ratio') or 0.3)
        per_article = Ai.unit_cost('manual_step_block') + Ai.unit_cost('manual_scenario') + \
            Ai.unit_cost('manual_review') * 1.5
        est = n * per_article + n * explore_ratio * Ai.unit_cost('manual_explore') + \
            n * repair_ratio * Ai.unit_cost('manual_repair') + Ai.unit_cost('scenario_seed') * 2 + \
            self._design_cost_estimate()
        vals = {'cost_estimate': round(est, 2)}
        for f, key, default in (('target_shot_rate', 'plan_target_shot_rate', 95.0),
                                ('target_review_rate', 'plan_target_review_rate', 85.0),
                                ('target_blank_max', 'plan_target_blank_max', 10.0),
                                ('max_rounds', 'plan_max_rounds', 3)):
            if not self.parent_id:
                raw = icp.get_param('corpaas_knowledge.%s' % key)
                if raw:
                    vals[f] = int(raw) if f == 'max_rounds' else float(raw)
        self.write(vals)

    # ------------------------------------------------------------------
    # 和前一版比對
    # ------------------------------------------------------------------
    def _mark_changes(self):
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        if not self.parent_id:
            self.item_ids.filtered(lambda i: i.change != 'new').write({'change': 'new'})
            return
        old = {(i.kind, i.key): i for i in self.parent_id.live_items()}
        seen = set()
        for item in self.item_ids.filtered(lambda i: i.change != 'remove'):
            prev = old.get((item.kind, item.key))
            seen.add((item.kind, item.key))
            if not prev:
                item.write({'change': 'new'})
            elif prev.content_json == item.content_json and prev.name == item.name:
                item.write({'change': 'same'})
            else:
                item.write({'change': 'modify'})
        for key, prev in old.items():
            if key in seen or prev.kind in ('question', 'instruction'):
                continue
            exists = self.item_ids.filtered(lambda i: (i.kind, i.key) == key)
            if not exists:
                Item.create({'plan_id': self.id, 'kind': prev.kind, 'key': prev.key, 'name': prev.name,
                             'content_json': prev.content_json, 'change': 'remove', 'confidence': 'high'})

    # ------------------------------------------------------------------
    # 試寫（文字）與自審
    # ------------------------------------------------------------------
    def _plan_trial(self, pack):
        """挑兩個章節使用量最高的功能點，依故事試寫情境說明，再用同一套審稿標準自審。"""
        story = self.story()
        picks = []
        for ch in self.live_items('chapter')[:6]:
            line = self.line_ids.filtered(lambda l: l.item_id == ch and l.assignment == 'chapter').sorted(
                lambda l: -(l.usage or 0))[:1]
            if line:
                picks.append((ch, line))
            if len(picks) >= 2:
                break
        if not picks or not story:
            return
        esc = html_mod.escape
        Ai = self.env['corpaas.knowledge.ai']
        parts, ok_all = [], True
        for ch, line in picks:
            f = line.feature_id
            text = Ai.ask('plan_trial', (
                "依公司故事，為功能「%s」寫一段 100–200 字的情境說明（為什麼、什麼時機要做這件事、做完的結果）。"
                "只寫這個功能做得到的事；故事裡別的功能不要硬套。繁體中文、台灣用語。只回純文字。\n\n"
                "公司故事：%s\n章節：%s（%s）\n功能：%s；選單：%s；模型：%s") % (
                f.name, json.dumps(story, ensure_ascii=False)[:2000], ch.name, ch.summary or '',
                f.name, f.menu_path or '', f.model or ''), package=self.package_id, record=self,
                expect_json=False) or ''
            review = Ai.ask('plan_trial', (
                "你是說明書審稿人。判斷這段情境說明能不能上線：有沒有編造功能做不到的事、讀者身分對不對、"
                "公司背景照故事寫不算編造。只列會讓讀者誤解的問題。"
                "只回 JSON：{\"ok\": true|false, \"problems\": [\"…\"]}\n\n"
                "故事：%s\n功能：%s（%s）\n文字：%s") % (
                json.dumps(story, ensure_ascii=False)[:1500], f.name, f.menu_path or '', text[:1500]),
                package=self.package_id, record=self) or {}
            ok = bool(isinstance(review, dict) and review.get('ok') and not review.get('problems'))
            ok_all = ok_all and ok
            probs = review.get('problems') if isinstance(review, dict) else []
            parts.append('<h4>%s／%s</h4><p>%s</p><p class="text-%s">%s</p>' % (
                esc(ch.name), esc(f.name), esc(str(text)).replace('\n', '<br/>'),
                'success' if ok else 'danger',
                esc(_('自審通過') if ok else _('自審意見：%s') % '；'.join(str(p) for p in probs or []))))
        self.trial_html = '<div data-trial-ok="%s">%s</div>' % ('1' if ok_all else '0', ''.join(parts))

    def _plan_try_auto_approve(self):
        """依自動化等級自動核准（規格第 10 節）；實作在 plan_exec.py。"""
        return False
