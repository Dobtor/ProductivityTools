# -*- coding: utf-8 -*-
"""知識底稿（新架構規格第 6 節）：計畫前完成所有分析，AI 設計計畫只在整理好的事實上取捨。

K1 模組解析 → K2 模組事實（沿用盤點、指紋、流程）→ K3 程式知識（模組摘要、繼承鏈、程式結論，
由圈選與拍照階段提前到這裡）→ K4 流程補強（程式結論補進流程、流程命名不送審、官方文件）
→ K5 範圍底稿與模組關係 → K6 就緒檢查（檢查引擎 T1）。

★ 走知識更新的佇列（reason='plan_ledger'），跟一般更新共用心跳、提交與失敗處理；
  只跑準備階段的盤點部分，不建說明庫、不拍照、不產生任何提案。
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import txn

_logger = logging.getLogger(__name__)

LEDGER_REASON = 'plan_ledger'
#: 沒有畫面、不寫說明的功能點種類
NO_SCREEN_KINDS = ('report', 'wizard_hidden')


class KnowledgePlanLedger(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def action_build_ledger(self):
        """（重新）建立知識底稿：排一張知識更新（只做盤點部分），完成後自動跑就緒檢查。"""
        for rec in self:
            rec._check_editable()
            rec.package_id._knowledge_master()
            rec.with_context(knowledge_plan_system=True).write({'state': 'ledger'})
            rec.package_id.sudo().write({'knowledge_enabled': True})
            rec.package_id.knowledge_enqueue_refresh(full=False, reason=LEDGER_REASON)
        return True

    @api.model
    def _plan_building(self, package):
        """這個方案正在建底稿的計畫（最新一份）。"""
        return self.sudo().search([('package_id', '=', package.id), ('state', '=', 'ledger')],
                                  order='version desc, id desc', limit=1)

    # ------------------------------------------------------------------
    # K5：範圍底稿、關聯模組、模組關係
    # ------------------------------------------------------------------
    def _ledger_build(self):
        """依目前的事實層重建這份計畫的關聯模組、範圍底稿、模組關係。

        ★ 審閱者鎖定過的底稿列保留原歸屬；有前一版時，沒變的功能點沿用前一版的歸屬。"""
        self.ensure_one()
        pkg = self.package_id
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        feats = Feature.search([('package_ids', 'in', pkg.id), ('missing', '=', False)])
        feats = feats.filtered(lambda f: f.is_present_in(pkg))
        self._ledger_modules(feats)
        self._ledger_lines(feats)
        self._ledger_relations()
        return True

    def _ledger_module_category(self, module, code_addons, tech):
        if module in tech:
            return 'tech'
        if module in code_addons:
            return 'own'
        return 'odoo'

    def _ledger_modules(self, feats):
        self.ensure_one()
        pkg = self.package_id
        SM = self.env['corpaas.knowledge.source_module'].sudo()
        code = pkg.knowledge_profile().get('code') or {}
        addons = code.get('addons') or {}
        master = pkg._knowledge_master(raise_if_missing=False)
        golden = master._corpaas_golden_db() if master else None
        bom = set(pkg._provision_module_names())
        installed = pkg._knowledge_golden_installed(golden) if golden else set()
        scope = set(pkg._knowledge_scope_names() or []) or (bom | installed)
        counts = {}
        for f in feats:
            counts[f.module] = counts.get(f.module, 0) + 1
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        mods = sorted((scope | set(counts)) - {False, None, ''})
        tech = {m for m in mods if not counts.get(m)}
        keep = SM
        for m in mods:
            hashv = (addons.get(m) or {}).get('hash')
            vals = {
                'origin': 'package' if m in bom else 'depends',
                'category': self._ledger_module_category(m, addons, tech),
                'version_ref': hashv or False,
                'feature_count': counts.get(m, 0),
                'installed': m in installed or m in bom,
                'summarized': bool(hashv and Summary.search_count([('module', '=', m), ('dir_hash', '=', hashv),
                                                                   ('source', '=', 'ai')])),
            }
            rec = SM.search([('plan_id', '=', self.id), ('module', '=', m)], limit=1)
            if rec:
                if rec.origin in ('addon', 'dev', 'customer', 'tier'):
                    vals.pop('origin')   # 來源轉接器標的來源不要被覆蓋
                rec.write(vals)
            else:
                rec = SM.create(dict(vals, plan_id=self.id, module=m))
            keep |= rec
        (self.module_ids - keep).filtered(lambda r: r.origin in ('package', 'depends')).unlink()

    def _ledger_pack_models(self):
        models_ = set()
        for pack in self.env['corpaas.knowledge.seed_pack'].sudo().search([]):
            try:
                for row in json.loads(pack.seed_json or '[]'):
                    if isinstance(row, dict) and row.get('model'):
                        models_.add(row['model'])
            except ValueError:
                continue
        return models_

    def _ledger_rule(self, feature):
        """規則直接判定的歸屬：(assignment, reason) 或 None（交給 AI）。"""
        pkg = self.package_id
        if not feature.model and feature.kind != 'route':
            return 'exclude', _('沒有畫面（不寫操作說明）')
        if not pkg._knowledge_documents_feature(feature):
            return 'exclude', _('未客製的官方畫面：連結 Odoo 官方文件')
        return None

    def _ledger_lines(self, feats):
        self.ensure_one()
        pkg = self.package_id
        Line = self.env['corpaas.knowledge.scope_line'].sudo().with_context(knowledge_plan_system=True)
        cats = {m.module: m.category for m in self.module_ids}
        packs = self._ledger_pack_models()
        flows = self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', pkg.id)])
        flow_of = {}
        for fl in flows:
            for f in fl.feature_ids:
                flow_of.setdefault(f.id, fl.id)
        prev = {}
        if self.parent_id:
            for line in self.parent_id.line_ids:
                prev[line.feature_id.id] = line
        existing = {line.feature_id.id: line for line in self.line_ids}
        seen = set()
        for f in feats:
            seen.add(f.id)
            cls = f.class_for(pkg)
            vals = {
                'module': f.module, 'module_category': cats.get(f.module) or 'odoo',
                'kind': f.kind, 'flow_id': flow_of.get(f.id) or False,
                'usage': f.attr_for(pkg, 'usage_score') or 0.0,
                'classification': (cls.as_payload().get('classification_label') if cls else False) or False,
                'has_pack': bool(f.model and f.model in packs),
            }
            line = existing.get(f.id)
            rule = self._ledger_rule(f)
            if line and line.locked:
                line.write(vals)
                continue
            if rule:
                vals.update({'assignment': rule[0], 'reason': rule[1], 'item_id': False,
                             'by_rule': True, 'confidence': 'high'})
            elif line and line.assignment != 'unassigned' and not line.by_rule:
                pass   # 已由 AI 或人歸屬：重建底稿不覆蓋
            elif f.id in prev and prev[f.id].assignment != 'unassigned':
                old = prev[f.id]
                item = self.chapter_item_ids.filtered(lambda i: i.key == old.item_id.key)[:1] \
                    if old.item_id else False
                vals.update({'assignment': old.assignment if (item or old.assignment != 'chapter')
                             else 'unassigned',
                             'item_id': item.id if item else False, 'reason': old.reason,
                             'confidence': old.confidence, 'by_rule': False})
            else:
                vals.update({'assignment': 'unassigned', 'by_rule': False})
            if line:
                line.write(vals)
            else:
                Line.create(dict(vals, plan_id=self.id, feature_id=f.id))
        self.line_ids.filtered(lambda l: l.feature_id.id not in seen).unlink()

    def _ledger_relations(self):
        """相依（模組摘要記的 depends）、繼承（程式結論的定義鏈跨模組）、流程交接（按鈕開出別的流程）。"""
        self.ensure_one()
        pkg = self.package_id
        Rel = self.env['corpaas.knowledge.module_relation'].sudo()
        self.relation_ids.unlink()
        rows = set()
        code = pkg.knowledge_profile().get('code') or {}
        addons = code.get('addons') or {}
        mods = set(self.module_ids.mapped('module'))
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        for m in sorted(mods & set(addons)):
            rec = Summary.search([('module', '=', m), ('dir_hash', '=', (addons.get(m) or {}).get('hash'))],
                                 order='source, id desc', limit=1)
            try:
                facts = json.loads(rec.facts_json or '{}') if rec else {}
            except ValueError:
                facts = {}
            for dep in facts.get('depends') or []:
                rows.add(('depends', m, dep, ''))
        Fact = self.env['corpaas.knowledge.code_fact'].sudo()
        subjects = ['%s.%s' % t for t in pkg._knowledge_button_targets()]
        for fact in Fact.search([('subject', 'in', subjects)]):
            chain = [d.module for d in fact.def_ids if d.module]
            for upper, lower in zip(chain, chain[1:]):
                if upper != lower:
                    rows.add(('inherits', upper, lower, fact.subject))
        flows = self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', pkg.id)])
        for t in flows.mapped('transition_ids').filtered('opens_flow_id'):
            rows.add(('handoff', t.flow_id.model, t.opens_flow_id.model,
                      t.button_label or t.button_name or ''))
        for kind, src, dst, note in sorted(rows):
            Rel.create({'plan_id': self.id, 'kind': kind, 'src': src, 'dst': dst, 'note': note[:200]})

    def _ledger_paths(self, limit=12):
        """候選端到端流程：沿流程交接邊串起來的路徑（例如訂單 → 出貨 → 發票）。"""
        self.ensure_one()
        edges = {}
        for r in self.relation_ids.filtered(lambda r: r.kind == 'handoff'):
            edges.setdefault(r.src, set()).add(r.dst)
        targets = {d for ds in edges.values() for d in ds}
        starts = [s for s in edges if s not in targets] or list(edges)
        paths = []

        def walk(node, path):
            nxt = [n for n in sorted(edges.get(node, ())) if n not in path]
            if not nxt or len(path) >= 6:
                paths.append(path)
                return
            for n in nxt:
                walk(n, path + [n])
        for s in sorted(starts):
            walk(s, [s])
        paths.sort(key=lambda p: -len(p))
        return paths[:limit]


class SolutionPackageLedger(models.Model):
    _inherit = 'infrastructure.solution.package'

    def solution_package_knowledge_refresh(self, package_id=None, full=False, reason='', after=None):
        """知識更新的派工目標：reason＝plan_ledger 時只建知識底稿（計畫前），不往下拍照。"""
        self.ensure_one()
        pending = reason or self.knowledge_pending_reason or ''
        if pending != LEDGER_REASON:
            return super().solution_package_knowledge_refresh(package_id=package_id, full=full,
                                                              reason=reason, after=after)
        return self._knowledge_run_ledger()

    def _knowledge_run_ledger(self):
        self.ensure_one()
        self = self.with_context(knowledge_fresh_cursor=True, knowledge_ledger=True)
        Plan = self.env['corpaas.knowledge.plan']
        plan = Plan._plan_building(self)
        if self.knowledge_pending_reason:
            self._knowledge_bookkeep({'knowledge_pending_reason': False})
        if not plan:
            _logger.info('[knowledge] %s 沒有建底稿中的計畫，略過', self.display_name)
            return True
        import uuid
        run = self.env['corpaas.knowledge.run'].sudo().create({
            'package_id': self.id, 'token': uuid.uuid4().hex, 'full': False,
            'reason': LEDGER_REASON, 'plan_id': plan.id})
        self._knowledge_commit()
        try:
            run.begin_stage('prepare')
            self._knowledge_commit()
            self._knowledge_stage_ledger(run, plan)
            run.end_stage()
            run.mark_done()
            self._knowledge_commit()
        except Exception as e:
            self._knowledge_stage_failed(run, e)
            plan.with_context(knowledge_plan_system=True).write({'state': 'blocked'})
            plan.message_post(body=_('建立知識底稿失敗：%s') % str(e)[:500])
            if not txn.in_tests(self.env):
                self.env.cr.commit()
            raise
        plan._plan_after_ledger()
        return True

    def _knowledge_stage_ledger(self, run, plan):
        """K1～K5：重用準備階段的盤點，加上提前的程式知識；不產生任何提案。"""
        token = run.token
        Event = self.env['corpaas.knowledge.event'].sudo()
        with self._op_step('kb_check'):
            master = self._knowledge_master()
            golden = master._corpaas_golden_db()
            if not golden or golden.golden_state != 'verified':
                raise UserError(_('母體「%s」沒有已驗證的黃金庫。') % master.display_name)
        with self._op_step('kb_golden_sync'):
            with golden._corpaas_golden_lock():
                changed = golden.with_context(
                    knowledge_skip_modules_trigger=True,
                    golden_refresh_state=True)._corpaas_golden_sync_code()
            if changed:
                Event.create({'type': 'code_changed', 'package_id': self.id, 'refresh_token': token,
                              'payload': json.dumps({'modules': changed})})
        with self._op_step('kb_inventory'):
            analysis = self._knowledge_analyze(golden)
            self._knowledge_update_profile(analysis.get('profile') or {})
            added, removed = self._knowledge_inventory(golden, token, analysis)
        with self._op_step('kb_fingerprint'):
            self._knowledge_fingerprint(golden, token, full=False)
            self._knowledge_detect_renames(added, removed, token)
        with self._op_step('kb_flows'):
            try:
                self._knowledge_flows(golden, token, analysis.get('flows'))
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] %s 流程推導失敗：%s', self.display_name, e)
        self._knowledge_commit()
        # K3：程式知識（提前到計畫前；依模組目錄雜湊與映像版本沿用，不重讀）
        with self._op_step('kb_ai_catalog'):
            try:
                with self.env.cr.savepoint():
                    self._knowledge_module_summaries(token=token)
            except Exception as e:  # noqa: BLE001 — 讀不到程式由就緒檢查標出
                _logger.warning('[knowledge] %s 模組摘要失敗：%s', self.display_name, e)
            self._knowledge_commit()
            try:
                with self.env.cr.savepoint():
                    self._knowledge_ledger_code_facts(golden, token)
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] %s 程式結論失敗：%s', self.display_name, e)
            self._knowledge_commit()
            # K4：流程補強
            try:
                with self.env.cr.savepoint():
                    cstats = self._knowledge_apply_code_facts()
                run.add_stats(**{'flows_code_%s' % k: v for k, v in (cstats or {}).items() if v})
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge] %s 程式結論補進流程失敗：%s', self.display_name, e)
            for step in (lambda: self._knowledge_flow_names(token),
                         lambda: self._knowledge_official_docs(token)):
                try:
                    with self.env.cr.savepoint():
                        step()
                except Exception as e:  # noqa: BLE001
                    _logger.warning('[knowledge] %s 流程補強略過：%s', self.display_name, e)
            self._knowledge_commit()
        # K5
        plan._ledger_build()
        run.add_stats(ledger_lines=len(plan.line_ids), ledger_modules=len(plan.module_ids))

    def _knowledge_ledger_code_facts(self, golden, token):
        """方案所有按鈕方法的繼承鏈與結論（在黃金庫解析，不必等說明庫）。"""
        targets = self._knowledge_button_targets()
        if not targets:
            return 0
        facts = self._knowledge_code_chains(golden.instance_id, golden.name, targets)
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('corpaas_knowledge.code_semantic') not in ('1', 'True', 'true'):
            return 0
        limit = int(icp.get_param('corpaas_knowledge.ledger_semantic_limit') or 40)
        todo = [f for f in (facts or {}).values() if f.state != 'current'][:limit]
        return self._knowledge_code_semantic(golden.instance_id, todo, token=token) if todo else 0

    def _knowledge_flow_names(self, token, batch=10):
        """建底稿時或依計畫產出時：流程命名直接生效、不送審、不建議能力（歸屬由計畫決定）。"""
        self.ensure_one()
        if not (self.env.context.get('knowledge_ledger') or self.knowledge_plan_mode):
            return super()._knowledge_flow_names(token, batch=batch)
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        todo = Flow.search([('package_ids', 'in', self.id), ('structure_hash', '!=', False)]).filtered(
            lambda f: f.structure_hash != f.named_hash)[:batch]
        if not todo:
            return self.env['corpaas.knowledge.selection']
        subjects = {'%s.%s' % (f.model, t.button_name) for f in todo for t in f.transition_ids if t.button_name}
        code = self._knowledge_code_facts_for(subjects) if subjects else {}
        modules = self._knowledge_module_brief()
        prompt = (
            "以下是方案「%s」裡的任務流程（狀態步驟與觸發按鈕）。請為每個流程取一個使用者看得懂的業務名稱"
            "（4–12 字），並用 1–2 句寫出這個流程在做什麼（寫出關鍵前提）。\n"
            "格式：{\"items\":[{\"model\":…,\"name\":…,\"summary\":…}]}\n\n"
            "方案自訂模組摘要（讀過程式）：%s\n\n轉換按鈕在程式裡做什麼：%s\n\n流程：%s"
        ) % (self.display_name,
             json.dumps([{k: b.get(k) for k in ('module', 'purpose', 'rules')} for b in modules],
                        ensure_ascii=False)[:8000],
             json.dumps(code, ensure_ascii=False)[:6000],
             json.dumps([f.as_outline() for f in todo], ensure_ascii=False))
        from ..services import hub_client
        try:
            data = self.env['corpaas.knowledge.ai'].ask('flow_name', prompt, package=self,
                                                        refresh_token=token)
        except hub_client.HubError as e:
            _logger.warning('[knowledge] 流程命名略過：%s', e)
            return self.env['corpaas.knowledge.selection']
        by_model = {f.model: f for f in todo}
        for item in (data or {}).get('items') or []:
            flow = by_model.get((item or {}).get('model'))
            if not flow:
                continue
            vals = {'named_hash': flow.structure_hash}
            if item.get('name'):
                vals['ai_name'] = str(item['name'])[:60]
            if item.get('summary'):
                vals['summary'] = str(item['summary'])[:1000]
            flow.write(vals)
        return self.env['corpaas.knowledge.selection']
