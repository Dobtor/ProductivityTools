# -*- coding: utf-8 -*-
"""說明書的規則產生頁：開始之前（本說明怎麼用、開始前必設定）、章末（狀態速查、訊息與狀況對照）。

★ 資料來源：說明庫實機探測（拍攝後順手跑，簽章沒變就不重跑）＋流程結構＋截圖角色。
  AI 只補兩種短文（狀態的意思、訊息的原因與處理），系統訊息保留原文。
★ 這些頁跟旅程篇一樣由重新編號時產生，不經文章的送審流程；內容沒變不重寫（「新」標記不跳）。
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client, remote

from ..services import guide_lib, manual_lib
from .hooks import AI_ERRORS, ai_dict, ai_html_steps, ai_text

_logger = logging.getLogger(__name__)

FRONT_SECTION = '開始之前'
GUIDE_KINDS = [('howto', '本說明怎麼用'), ('setup', '開始前必設定'),
               ('concept', '先懂這幾個觀念'), ('tutorial', '情境教學'),
               ('status', '狀態速查'), ('messages', '訊息與狀況對照')]
GUIDE_TITLES = dict(GUIDE_KINDS)
#: 一次問 AI 補幾則（狀態意思以流程為單位、訊息以則為單位）
MEANING_BATCH = 15
MESSAGE_BATCH = 40


class KnowledgeFlowStep(models.Model):
    _inherit = 'corpaas.knowledge.flow.step'

    meaning = fields.Char(string='意思', help='狀態速查用：這個狀態代表什麼（AI 補寫，可人工改）')


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    manual_setup_json = fields.Text(string='開始前必設定（探測）', readonly=True, copy=False)
    manual_messages_json = fields.Text(string='系統訊息（探測）', readonly=True, copy=False)
    manual_guide_sig = fields.Char(readonly=True, copy=False,
                                   help='上次探測時的說明庫簽章：沒變就不重跑')
    manual_guide_at = fields.Datetime(string='說明書探測時間', readonly=True, copy=False)

    def action_manual_redraft_review(self):
        """待審的文章用新寫法重寫（排進 AI 佇列）。"""
        self.ensure_one()
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以重寫待審說明。'))
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_manual_redraft_review_run', self, note=_('待審說明依新寫法重寫'))

    def _manual_redraft_review_run(self):
        self.ensure_one()
        return self.env['corpaas.knowledge.hooks'].sudo()._manual_redraft_review(self)

    def action_manual_redraft_handoff(self):
        """只重寫提到錯誤交接（查看上游單據的智慧按鈕、只有編號的按鈕名稱）的待審說明。"""
        self.ensure_one()
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以重寫待審說明。'))
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_manual_redraft_handoff_run', self, note=_('重寫提到錯誤交接的待審說明'))

    def action_manual_redraft_lint(self):
        """重寫文字檢查新規則抓到的文章（標題含示範名稱、「開始前要先有」寫錯）：含已上線的。

        已上線的文章重寫後送審，前台照舊顯示上線版，核准後才換。"""
        self.ensure_one()
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
            raise AccessError(_('只有知識管理者可以重寫說明。'))
        return self.env['corpaas.knowledge.ai'].enqueue(
            self, '_manual_redraft_lint_run', self, note=_('重寫文字檢查抓到的說明'))

    def _manual_redraft_lint_run(self):
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks'].sudo()
        return hooks._manual_redraft_review(self, features=hooks._manual_lint_features(self),
                                            states=('review', 'published'))

    def _manual_redraft_handoff_run(self):
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks'].sudo()
        return hooks._manual_redraft_review(self, features=hooks._manual_wrong_handoff_features(self))

    def _manual_guide_data(self, field):
        self.ensure_one()
        try:
            return json.loads(self[field] or 'null')
        except ValueError:
            return None


class KnowledgeGuideSlide(models.Model):
    _name = 'corpaas.knowledge.guide_slide'
    _description = '操作說明：規則產生頁'
    _order = 'section_id, id'

    section_id = fields.Many2one('corpaas.knowledge.channel_section', required=True,
                                 ondelete='cascade', index=True)
    kind = fields.Selection(GUIDE_KINDS, required=True)
    slide_id = fields.Many2one('slide.slide', ondelete='set null', readonly=True)
    text_hash = fields.Char(readonly=True)

    _sql_constraints = [('section_kind_unique', 'unique(section_id, kind)', '同一章節同一種頁只能一張')]


class KnowledgeChannelSection(models.Model):
    _inherit = 'corpaas.knowledge.channel_section'

    kind = fields.Selection([('chapter', '章節'), ('front', '開始之前')], default='chapter',
                            required=True)
    guide_slide_ids = fields.One2many('corpaas.knowledge.guide_slide', 'section_id')

    @api.depends('capability_id.name', 'kind')
    def _compute_name(self):
        super()._compute_name()
        for rec in self.filtered(lambda r: r.kind == 'front'):
            rec.name = FRONT_SECTION

    def _manual_upsert_guide(self, kind, html, publisher, show):
        """建立／更新規則產生頁；不需要（show 為假或沒有內容）就取消發佈（不刪）。回傳 slide。"""
        from ..services import manual_lib
        self.ensure_one()
        Guide = self.env['corpaas.knowledge.guide_slide'].sudo()
        rec = self.guide_slide_ids.filtered(lambda g: g.kind == kind)[:1]
        slide = rec.slide_id.exists()
        if not show or not html:
            if slide and slide.is_published:
                slide.with_env(publisher.env).is_published = False
            return slide
        name = GUIDE_TITLES[kind]
        if self.kind == 'chapter' and self.capability_id:
            name = '%s：%s' % (self.name, name)
        text_hash = manual_lib.text_signature(name + html)
        vals = {'name': name, 'slide_category': 'article', 'is_preview': True,
                'html_content': html}
        if not slide:
            slide = publisher.env['slide.slide'].create(
                dict(vals, channel_id=self.channel_id.id, sequence=0, is_published=True))
        else:
            slide = slide.with_env(publisher.env)
            if not slide.is_published:
                vals['is_published'] = True
            elif rec.text_hash == text_hash:
                vals = {}
            else:
                vals['date_published'] = fields.Datetime.now()
            if vals:
                slide.write(vals)
        if rec:
            rec.write({'slide_id': slide.id, 'text_hash': text_hash})
        else:
            Guide.create({'section_id': self.id, 'kind': kind, 'slide_id': slide.id,
                          'text_hash': text_hash})
        return slide

    # ------------------------------------------------------------------
    # 章末：狀態速查、訊息與狀況對照
    # ------------------------------------------------------------------
    @api.model
    def _manual_role_names(self, package):
        out = {}
        for sc in package.knowledge_scenario_ids:
            for r in sc.all_roles():
                out.setdefault(r.code, r.name)
        return out

    @api.model
    def _manual_feature_role(self, feature, role_names):
        """這個功能以哪個角色拍攝（＝誰能操作）：取拍成功的繫結。"""
        if not feature:
            return ''
        b = self.env['corpaas.knowledge.shot_binding'].sudo().search(
            [('feature_id', '=', feature.id), ('state', '=', 'ok')], limit=1)
        code = b.login_role() if b else ''
        return role_names.get(code, '')

    @api.model
    def _manual_status_data(self, flows, package):
        """狀態速查：每個狀態「往下一步」與「取消／退回」分開列。

        ☠️ 實機：靜態分析把「列印」推成「→ 已取消」（同一顆按鈕的另一條路徑）、按鈕名稱只剩
          方法名稱 → 列印／寄送類按鈕一律不列，沒有給人看的名稱也不列。"""
        import re
        from odoo.addons.dobtor_corpaas_knowledge.models.flow_diagram import MODEL_ROLE
        deny = re.compile(guide_lib.STATUS_DENY)
        view_btn = re.compile(r'(?i)^action_(view|see|show|open)_|cancel|lock|draft|unlock')
        role_names = self._manual_role_names(package) if package else {}
        out = []
        for flow in flows.sorted(lambda f: (-(f.usage_score or 0), f.id)):
            steps = flow.step_ids.sorted('sequence').filtered('on_statusbar')
            if len(steps) < 2:
                continue
            bar = steps.mapped('value')
            default_role = role_names.get(MODEL_ROLE.get(flow.model) or '', '')
            rows = []
            for s in steps:
                nxt, back, roles = [], [], []
                for t in flow.effective_transitions().sorted('id'):
                    label = t.display_label()
                    if (t.from_value or '') not in (s.value, '') or not label \
                            or deny.search(t.button_name or ''):
                        continue
                    forward = t.to_value in bar and bar.index(t.to_value) > bar.index(s.value)
                    if t.to_value and t.to_value != s.value:
                        line = _('按「%(b)s」→ %(to)s', b=label, to=flow.step_label(t.to_value))
                    elif t.opens_flow_id and t.is_handoff():
                        line, forward = _('按「%(b)s」開出「%(f)s」', b=label,
                                          f=t.opens_flow_id.name), True
                    elif t.from_value == s.value and not t.to_value \
                            and not view_btn.search(t.button_name or '') \
                            and s.value != bar[-1] and not t.button_name.isdigit():
                        # 終點推不出來的按鈕（如「通過信件發送」）：照樣列，讀者知道要按它
                        line, forward = _('按「%s」') % label, True
                    else:
                        continue
                    bucket = nxt if forward else back
                    if line not in bucket:
                        bucket.append(line)
                    if forward:
                        who = self._manual_feature_role(t.button_feature_id, role_names) \
                            or default_role
                        if who and who not in roles:
                            roles.append(who)
                rows.append({'label': s.label or s.value, 'meaning': s.meaning or '',
                             'next': nxt, 'back': back, 'roles': roles})
            if any(r['next'] for r in rows):
                out.append({'name': flow.name, 'steps': rows})
        return out

    @api.model
    def _manual_messages_data(self, flows, package):
        items = (package._manual_guide_data('manual_messages_json') or []) if package else []
        by_flow = {}
        for it in items:
            # 使用者照正常步驟不會遇到的（AI 判斷）不列：對照表只放讀者真的會看到的訊息
            if it.get('flow') in flows.ids and it.get('message') and it.get('realistic', True):
                by_flow.setdefault(it['flow'], []).append(it)
        out = []
        for flow in flows.sorted(lambda f: (-(f.usage_score or 0), f.id)):
            if by_flow.get(flow.id):
                out.append({'name': flow.name, 'items': by_flow[flow.id]})
        return out

    def _manual_sync_chapter_guides(self, flows, package, publisher, shown):
        """回傳 [slide]：依序排在章節的參考篇之後。"""
        self.ensure_one()
        status = self._manual_status_data(flows, package) if flows else []
        msgs = self._manual_messages_data(flows, package) if flows else []
        out = []
        for kind, html in (('status', guide_lib.render_status(status) if status else ''),
                           ('messages', guide_lib.render_messages(msgs) if msgs else '')):
            slide = self._manual_upsert_guide(kind, html, publisher, shown)
            if slide:
                out.append(slide)
        return out


class SlideChannel(models.Model):
    _inherit = 'slide.channel'

    # ★ 章節清單只含能力章節與共通操作：「開始之前」不參與章節的增刪對帳
    knowledge_section_ids = fields.One2many('corpaas.knowledge.channel_section', 'channel_id',
                                            domain=[('kind', '=', 'chapter')])

    def _manual_package(self):
        self.ensure_one()
        pkg = self.knowledge_placement_ids.mapped('package_id')[:1]
        if not pkg and self.knowledge_product_tmpl_id:
            pkg = self.env['infrastructure.solution.package'].sudo().search(
                [('product_tmpl_id', '=', self.knowledge_product_tmpl_id.id)], limit=1)
        return pkg

    def _manual_front_section(self):
        self.ensure_one()
        Section = self.env['corpaas.knowledge.channel_section'].sudo()
        section = Section.search([('channel_id', '=', self.id), ('kind', '=', 'front')], limit=1)
        publisher = self._knowledge_publisher()
        slide = section.slide_id.exists()
        if not slide:
            slide = publisher.env['slide.slide'].create({
                'name': FRONT_SECTION, 'channel_id': self.id, 'is_category': True, 'sequence': 0})
        if not section:
            section = Section.create({'channel_id': self.id, 'kind': 'front', 'slide_id': slide.id})
        elif section.slide_id != slide:
            section.slide_id = slide
        return section

    def _manual_setup_html(self, package):
        data = package._manual_guide_data('manual_setup_json') if package else None
        return guide_lib.render_setup(data) if data and (data.get('items') or data.get('roles')) \
            else ''

    def _manual_howto_html(self, package, chapters, setup_slide):
        """chapters: [(section, first_slide, placements)]（依章節順序，只含上線的章節）。"""
        self.ensure_one()
        from odoo.addons.dobtor_corpaas_knowledge.models.flow_diagram import MODULE_ROLE
        role_names = self.env['corpaas.knowledge.channel_section']._manual_role_names(package) \
            if package else {}
        # ★ 誰負責哪一章：看章節（能力）的主要模組歸哪個角色，不看截圖用哪個帳號拍——
        #   拍攝角色常常只是「看得到這個畫面的任一角色」（實機：業務被列到應收付、採購）
        roles, shared, chapter_rows, stamps, kinds = {}, [], [], [], set()
        for section, first, placements in chapters:
            chapter_rows.append({'name': section.name, 'url': first.website_url if first else ''})
            kinds |= {g.kind for g in section.guide_slide_ids
                      if g.slide_id and g.slide_id.is_published}
            stamps += [pl.synced_at for pl in placements if pl.synced_at]
            cap = section.capability_id
            code = MODULE_ROLE.get(cap._knowledge_main_module()) if cap else None
            name = role_names.get(code or '')
            if name:
                roles.setdefault(name, []).append(section.name)
            else:
                shared.append(section.name)
        others = [n for n in role_names.values() if n not in roles]
        rows = [{'name': n, 'chapters': c} for n, c in roles.items()]
        if others:
            rows.append({'name': '、'.join(others), 'chapters': [_('開始之前')] + [
                _('各章最後的設定畫面')]})
        if shared:
            rows.append({'name': _('所有角色'), 'chapters': shared})
        updated = ''
        if stamps:
            updated = fields.Date.to_string(fields.Datetime.context_timestamp(
                self.with_context(tz='Asia/Taipei'), max(stamps)).date())
        order = list(role_names.values())
        return guide_lib.render_howto({
            'product': self.knowledge_product_tmpl_id.name or self.name,
            'chapters': chapter_rows, 'kinds': sorted(kinds),
            'setup_url': setup_slide.website_url if setup_slide and setup_slide.is_published else '',
            'roles': sorted(rows, key=lambda r: order.index(r['name']) if r['name'] in order
                            else 99),
            'updated': updated,
        })


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    # ------------------------------------------------------------------
    # 探測（拍攝後，在說明庫）
    # ☠️ 不為了探測另外準備說明庫：壞繫結不重建說明庫是既有原則，探測搭下一次拍攝的便車
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_shoot(self, package, sandbox, events, ctx):
        res = super()._knowledge_shoot(package, sandbox, events, ctx)
        if sandbox.scenario_id == package.knowledge_scenario_ids[:1]:
            try:
                if self._manual_guide_probe(package, sandbox):
                    ctx.setdefault('stats', {})['guide_probed'] = 1
            except Exception as e:  # noqa: BLE001 — 探測失敗不影響拍攝
                _logger.warning('[knowledge.manual] 說明書探測失敗：%s', e)
            self._manual_commit()
        return res

    @api.model
    def _manual_guide_sig(self, sandbox):
        return '%s|%s' % (getattr(sandbox, 'base_sig', '') or '',
                          getattr(sandbox, 'seed_applied', '') or '')

    @api.model
    def _manual_message_spec(self, package):
        flows = self.env['corpaas.knowledge.flow'].sudo().search(
            [('package_ids', 'in', package.id), ('field_type', '=', 'selection')])
        spec = []
        for f in flows:
            seen, buttons = set(), []
            for t in f.transition_ids.sorted('id'):
                key = (t.button_name, t.from_value or '')
                if not t.button_name or key in seen:
                    continue
                seen.add(key)
                buttons.append({'name': t.button_name, 'label': t.display_label(),
                                'from': t.from_value or ''})
            if buttons:
                bar = f.step_ids.sorted('sequence').filtered('on_statusbar')
                spec.append({'flow': f.id, 'model': f.model, 'field': f.state_field,
                             'first': bar[:1].value or '', 'buttons': buttons})
        return spec

    @api.model
    def _manual_toggles(self, package):
        """進階功能開關：候選功能裡要先到設定頁打開的（方案預設已開）。"""
        out = {}
        for feature, _cap in self._manual_sorted_candidates(package):
            cls = feature.class_for(package)
            payload = cls.as_payload() if cls else {}
            if payload.get('tier') != 'advanced':
                continue
            for path in payload.get('toggle_paths') or []:
                names = out.setdefault(path, [])
                if feature.name not in names:
                    names.append(feature.name)
        return [{'path': p, 'features': n[:6]} for p, n in out.items()]

    @api.model
    def _manual_guide_probe(self, package, sandbox, force=False):
        """開始前必設定＋系統訊息：說明庫簽章沒變就不重跑。回傳是否有跑。"""
        sig = self._manual_guide_sig(sandbox)
        if not force and package.manual_guide_sig == sig:
            return False
        roles = []
        for sc in package.knowledge_scenario_ids:
            for r in sc.all_roles():
                if r.code not in [x['code'] for x in roles]:
                    roles.append({'code': r.code, 'name': r.name,
                                  'groups': [g.strip() for g in (r.group_xmlids or '').splitlines()
                                             if g.strip()]})
        groups = sorted({g for r in roles for g in r['groups']})
        try:
            got = sandbox._shell(guide_lib.setup_probe_script(guide_lib.SETUP_ITEMS, groups))
        except remote.RemoteError as e:
            _logger.warning('[knowledge.manual] 開始前必設定探測失敗：%s', e)
            got = None
        if got is not None:
            found = got.get('items') or {}
            gnames = got.get('groups') or {}
            items = []
            for it in guide_lib.SETUP_ITEMS:
                res = found.get(it['key'])
                if res is None:
                    continue
                items.append(dict(it, count=res.get('count') or 0, names=res.get('names') or [],
                                  menu=(res.get('menu') or '').replace('/', ' › '),
                                  ok=(res.get('count') or 0) >= it.get('count_min', 1)))
            items.sort(key=lambda x: (not x['required'], 0))
            package.manual_setup_json = json.dumps({
                'items': items,
                'roles': [{'name': r['name'], 'groups': [gnames[g] for g in r['groups'] if g in gnames]}
                          for r in roles],
                'toggles': self._manual_toggles(package)}, ensure_ascii=False)
        spec = self._manual_message_spec(package)
        msgs = None
        if spec:
            try:
                msgs = sandbox._shell(guide_lib.message_probe_script(spec))
            except remote.RemoteError as e:
                _logger.warning('[knowledge.manual] 系統訊息探測失敗：%s', e)
        if isinstance(msgs, dict):
            # 實測到的狀態轉換寫回流程（截圖證據）：狀態速查與情境教學都改用實測的終點
            Flow = self.env['corpaas.knowledge.flow'].sudo()
            by_model = {}
            for o in msgs.get('observed') or []:
                by_model.setdefault(o['model'], []).append(o)
            for model, obs in by_model.items():
                Flow._knowledge_record_observations(model, obs)
            msgs = msgs.get('messages') or []
        if msgs is not None:
            old = {(m.get('flow'), m.get('message')): m
                   for m in package._manual_guide_data('manual_messages_json') or []}
            Flow = self.env['corpaas.knowledge.flow'].sudo()
            for m in msgs:
                prev = old.get((m['flow'], m['message'])) or {}
                m['cause'], m['fix'] = prev.get('cause') or '', prev.get('fix') or ''
                flow = Flow.browse(m['flow']).exists()
                state = flow.step_label(m['from']) if flow and m.get('from') else ''
                when = _('在「%(s)s」狀態按「%(b)s」', s=state, b=m.get('label') or m['button']) \
                    if state else _('按「%s」') % (m.get('label') or m['button'])
                if m.get('variant') == 'empty':
                    when += _('（單據沒有明細時）')
                m['when'] = when
            package.manual_messages_json = json.dumps(msgs, ensure_ascii=False)
        if got is not None or msgs is not None:
            package.write({'manual_guide_sig': sig, 'manual_guide_at': fields.Datetime.now()})
        return True

    @api.model
    def _manual_wrong_handoff_features(self, package):
        """待審文字提到「不是交接的交接」或只有編號的按鈕名稱的功能。"""
        import re
        Article = self.env['corpaas.knowledge.article'].sudo()
        flows = self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', package.id)])
        wrong = {}   # model → 誤當成下一步的流程名稱
        for t in flows.mapped('transition_ids'):
            if t.opens_flow_id and not t.is_handoff():
                wrong.setdefault(t.flow_id.model, set()).add(t.opens_flow_id.name)
        out = self.env['corpaas.knowledge.feature']
        for art in Article.search([('state', '=', 'review'),
                                   ('scenario_id', 'in', package.knowledge_scenario_ids.ids)]):
            text = ' '.join([art.scenario_html or ''] + [b.html or '' for b in art.step_block_ids])
            names = wrong.get(art.feature_id.model) or set()
            if any(n and n in text for n in names) or re.search(r'「\d+」', text):
                out |= art.feature_id
        return out

    @api.model
    def _manual_lint_features(self, package):
        """文字檢查新規則抓到的功能（待審與已上線的文章都看）。"""
        Article = self.env['corpaas.knowledge.article'].sudo()
        out = self.env['corpaas.knowledge.feature']
        keys = ('標題含示範資料名稱', '「開始前要先有」', '句子太長')
        for art in Article.search([('state', 'in', ('review', 'published')),
                                   ('scenario_id', 'in', package.knowledge_scenario_ids.ids)]):
            if any(p.startswith(keys) for p in art._manual_text_problems()):
                out |= art.feature_id
        return out

    @api.model
    def _manual_redraft_review(self, package, token=None, features=None, states=('review',)):
        """待審（還沒上線過）的步驟區塊與文章，用目前的提示重寫一次，再送審。

        先平行預取步驟區塊，寫回後再平行預取情境說明（情境說明要帶入新的步驟）。
        回傳 (區塊數, 文章數)。"""
        Ai = self.env['corpaas.knowledge.ai']
        Article = self.env['corpaas.knowledge.article'].sudo()
        cands = self._manual_candidates(package)
        arts = Article.search([('state', 'in', list(states)),
                               ('scenario_id', 'in', package.knowledge_scenario_ids.ids),
                               ('feature_id', 'in', [f.id for f in cands])])
        if features is not None:
            arts = arts.filtered(lambda a: a.feature_id in features)
        workers = int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.draft_parallel', 3) or 3)
        blocks = {}
        for art in arts:
            tmpl = art.shot_binding_id.template_id
            if not tmpl:
                continue
            for blk in art.step_block_ids.filtered(
                    lambda b: (not b.published_rev_no or 'published' in states)
                    and b.feature_id == art.feature_id):
                blocks.setdefault(blk.id, (blk, tmpl))
        prompts_ = {bid: self._manual_step_prompt(package, blk.feature_id, tmpl)
                    for bid, (blk, tmpl) in blocks.items()}
        Ai.prefetch([('manual_step_block', p) for p in prompts_.values()], package=package,
                    refresh_token=token, workers=workers)
        nb = 0
        for bid, (blk, tmpl) in blocks.items():
            try:
                data = ai_dict(Ai.ask('manual_step_block', prompts_[bid], package=package,
                                      refresh_token=token, record=tmpl), 'manual_step_block')
                steps = ai_html_steps(data.get('steps'), 'manual_step_block')
            except hub_client.BudgetExceeded:
                break
            except AI_ERRORS as e:
                _logger.warning('[knowledge.manual] 重寫步驟區塊失敗 %s：%s', blk.id, e)
                continue
            blk.write({'name': ai_text(data.get('title')) or blk.name,
                       'html': manual_lib.steps_to_html(steps, blk.anchor)})
            if blk.state == 'published':
                blk.knowledge_propose('text', note=_('依新寫法重寫'))
            nb += 1
        items = [('manual_scenario', self._manual_scenario_prompt(
            package, a.scenario_id, a.feature_id, a.capability_id, a.step_block_ids)) for a in arts]
        Ai.prefetch(items, package=package, refresh_token=token, workers=workers)
        na = 0
        for art in arts:
            try:
                title, html = self._manual_write_scenario(
                    package, art.scenario_id, art.feature_id, art.capability_id,
                    art.step_block_ids, token)
            except hub_client.BudgetExceeded:
                break
            except AI_ERRORS as e:
                _logger.warning('[knowledge.manual] 重寫情境說明失敗 %s：%s', art.id, e)
                continue
            art.write({'scenario_html': html,
                       'name': manual_lib.clean_title(title or art.name, art.scenario_id.name)})
            art.knowledge_propose('text', note=_('依新寫法重寫'))
            na += 1
        return nb, na

    # ------------------------------------------------------------------
    # AI 補短文（分派階段，推送前）
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_dispatch_events(self, package, events, ctx):
        stop = ctx.setdefault('manual_ai_stopped', {'ai': False})
        try:
            self._manual_guide_ai(package, ctx.get('token'), stop)
        except Exception as e:  # noqa: BLE001 — 短文補不了，頁面照樣產生（欄位留「—」）
            _logger.warning('[knowledge.manual] 說明書短文失敗：%s', e)
        try:
            n = self._manual_draft_concepts(package, ctx.get('token'), stop)
            if n:
                ctx.setdefault('stats', {})['concepts_drafted'] = n
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge.manual] 觀念頁起草失敗：%s', e)
        # ☠️ 實機：上面寫了方案記錄（訊息說明），不提交就一直鎖著；之後對帳迴圈的心跳另開連線
        #   更新同一筆方案 → 互等，發佈階段卡死（資料庫偵測不到跨連線的自我死結）
        self._manual_commit()
        res = super()._knowledge_dispatch_events(package, events, ctx)
        # 文章沒有變動時不會觸發重新編號：規則頁（探測結果、短文）可能變了，主動同步一次
        tmpl = package.product_tmpl_id
        channel = self.env['slide.channel'].sudo().search(
            [('knowledge_product_tmpl_id', '=', tmpl.id)], limit=1) if tmpl else None
        if channel:
            try:
                n = self._manual_realign_chapters(package)
                if n:
                    ctx.setdefault('stats', {})['chapters_realigned'] = n
                channel._knowledge_request_sync()
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge.manual] 規則頁同步失敗：%s', e)
        return res

    @api.model
    def _manual_realign_chapters(self, package):
        """已上線的文章也跟著目前的歸屬換章節。

        ☠️ 實機：歸屬規則改了，但發佈位置的章節只在文章重推時才更新 → 沒變動的
          銷售訂單文章一直留在採購章。"""
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        Cap = self.env['corpaas.knowledge.capability']
        cands = self._manual_candidates(package)
        n = 0
        for pl in Placement.search([('package_id', '=', package.id), ('manual_retired', '=', False)]):
            cap = cands.get(pl.article_id.feature_id)
            if cap is None:
                continue
            cap = cap if cap in package.knowledge_capability_ids else Cap
            if pl.capability_id != cap:
                pl.capability_id = cap.id
                n += 1
        return n

    @api.model
    def _manual_guide_ai(self, package, token, stop):
        if stop.get('ai'):
            return 0
        Ai = self.env['corpaas.knowledge.ai']
        n = 0
        flows = self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', package.id)])
        todo = flows.filtered(lambda f: len(f.step_ids.filtered('on_statusbar')) >= 2 and any(
            not s.meaning for s in f.step_ids.filtered('on_statusbar')))[:MEANING_BATCH]
        if todo:
            prompt = (
                "以下是方案「%s」裡的任務流程與狀態。請為每個狀態用一句話（20 字以內）寫出它的意思："
                "單據停在這個狀態代表什麼、還差什麼。用使用者看得懂的業務說法，繁體中文（台灣用語），"
                "不要寫技術欄位名。\n"
                "格式：{\"flows\":[{\"model\":…,\"steps\":[{\"value\":…,\"meaning\":…}]}]}\n\n流程：%s"
            ) % (package.display_name, json.dumps([f.as_outline() for f in todo], ensure_ascii=False))
            try:
                data = Ai.ask('manual_flow_meaning', prompt, package=package, refresh_token=token)
            except hub_client.BudgetExceeded:
                stop['ai'] = True
                return n
            by_model = {f.model: f for f in todo}
            for item in (data or {}).get('flows') or [] if isinstance(data, dict) else []:
                flow = by_model.get(item.get('model')) if isinstance(item, dict) else None
                if not flow:
                    continue
                for st in item.get('steps') or []:
                    if not isinstance(st, dict):
                        continue
                    step = flow.step_ids.filtered(lambda s: s.value == str(st.get('value')))[:1]
                    text = guide_lib.clean_short(st.get('meaning'), 60)
                    if step and text and not step.meaning:
                        step.meaning = text
                        n += 1
        msgs = package._manual_guide_data('manual_messages_json') or []
        need = [i for i, m in enumerate(msgs)
                if not m.get('cause') or 'realistic' not in m][:MESSAGE_BATCH]
        if need:
            Flow = self.env['corpaas.knowledge.flow'].sudo()
            payload = [{'id': i, 'flow': Flow.browse(msgs[i]['flow']).exists().name or '',
                        'when': msgs[i].get('when') or '', 'message': msgs[i]['message']}
                       for i in need]
            prompt = (
                "以下是使用者在系統操作時會看到的訊息（系統原文）與出現時機。請為每則寫："
                "cause＝為什麼會出現（一句話）；fix＝怎麼處理（一兩句，說清楚要去哪個畫面補什麼或按什麼）；"
                "realistic＝一般使用者照正常步驟操作時會不會遇到（true／false：只有刻意刪光資料、"
                "或系統內部狀況才會出現的填 false）。"
                "繁體中文（台灣用語），不要改寫或翻譯訊息原文，不要寫技術欄位名，不確定就寫最常見的原因。\n"
                "格式：{\"items\":[{\"id\":…,\"cause\":…,\"fix\":…,\"realistic\":true}]}\n\n訊息：%s"
            ) % json.dumps(payload, ensure_ascii=False)
            try:
                data = Ai.ask('manual_message_help', prompt, package=package, refresh_token=token)
            except hub_client.BudgetExceeded:
                stop['ai'] = True
                data = None
            for item in (data or {}).get('items') or [] if isinstance(data, dict) else []:
                if not isinstance(item, dict) or item.get('id') not in need:
                    continue
                cause = guide_lib.clean_short(item.get('cause'))
                fix = guide_lib.clean_short(item.get('fix'), 160)
                if cause and fix:
                    msgs[item['id']].update(cause=cause, fix=fix,
                                            realistic=item.get('realistic') is not False)
                    n += 1
            package.manual_messages_json = json.dumps(msgs, ensure_ascii=False)
        return n
