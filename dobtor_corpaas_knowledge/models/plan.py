# -*- coding: utf-8 -*-
"""說明書製作計畫（新架構規格第 8 節）：一份計畫版本是唯一的人工控制點。

來源（產品／建議書）→ 知識底稿（K1～K6）→ AI 設計計畫（D1～D6）→ 審閱、核准 → 展開 → 流程編排 → 驗收。
初版、分期、修訂都是「下一個版本」，各自和前一版比對差異。

本檔只放資料模型與畫面用的計算欄位；行為分在：
  plan_ledger.py（知識底稿）、plan_check.py（檢查引擎）、plan_design.py（AI 設計）、plan_exec.py（展開與流程編排）。
"""
import html as html_mod
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

PLAN_STATES = [
    ('ledger', '底稿建立中'),
    ('readiness', '就緒檢查'),
    ('blocked', '受阻'),
    ('draft', '草稿'),
    ('review', '審閱'),
    ('approved', '已核准'),
    ('expanding', '展開中'),
    ('canary', '前哨批'),
    ('running', '執行中'),
    ('done', '已完成'),
    ('stopped', '已停止'),
    ('superseded', '已取代'),
]
#: 計畫已經生效（說明書依它產出）的狀態
LIVE_STATES = ('approved', 'expanding', 'canary', 'running', 'done', 'stopped')
#: 還在準備、可以修改的狀態
OPEN_STATES = ('ledger', 'readiness', 'blocked', 'draft', 'review')

ITEM_KINDS = [
    ('story', '故事'),
    ('chapter', '章節'),
    ('flow', '流程'),
    ('role', '角色'),
    ('data', '資料需求'),
    ('exclusion', '排除'),
    ('question', '待決事項'),
    ('instruction', '內容指示'),
]
ASSIGNMENTS = [('chapter', '章節'), ('exclude', '排除'), ('next', '下期'), ('unassigned', '未歸屬')]
CONFIDENCE = [('high', '高'), ('medium', '中'), ('low', '低')]
CHANGES = [('same', '沿用'), ('new', '新增'), ('modify', '修改'), ('remove', '移除')]
AUTOMATION = [('conservative', '保守：計畫與文章都要人核准'),
              ('standard', '標準：初版計畫人核准，輕微變更與自審通過的文章自動生效'),
              ('full', '全自動：產品來源檢查全綠時初版計畫也自動核准')]


def _j(text, default=None):
    try:
        val = json.loads(text or '')
    except (TypeError, ValueError):
        return default
    return val if val is not None else default


class KnowledgePlan(models.Model):
    _name = 'corpaas.knowledge.plan'
    _description = '說明書製作計畫'
    _inherit = ['mail.thread']
    _order = 'package_id, version desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    package_id = fields.Many2one('infrastructure.solution.package', string='方案', required=True,
                                 ondelete='cascade', index=True)
    source_type = fields.Selection([('product', '產品')], string='來源', required=True,
                                   default='product', tracking=True)
    source_note = fields.Text(string='來源簡述', help='起草時整理好給 AI 看的來源背景（快照）')
    version = fields.Integer(string='版本', default=1, readonly=True)
    version_type = fields.Selection([('initial', '初版'), ('phase', '分期'), ('revision', '修訂')],
                                    string='版本類型', default='initial', required=True, readonly=True)
    parent_id = fields.Many2one('corpaas.knowledge.plan', string='前一版', readonly=True,
                                ondelete='set null', index=True)
    child_ids = fields.One2many('corpaas.knowledge.plan', 'parent_id', string='後續版本')
    state = fields.Selection(PLAN_STATES, string='狀態', default='ledger', required=True,
                             tracking=True, index=True, copy=False)
    reader = fields.Selection([('backend', '後台職務'), ('admin', '租戶管理員'), ('portal', '前台會員')],
                              string='讀者', default='backend', required=True)
    budget = fields.Float(string='AI 預算（USD）', default=20.0)
    target_shot_rate = fields.Float(string='截圖成功率目標（%）', default=95.0)
    target_review_rate = fields.Float(string='自審通過率目標（%）', default=85.0)
    target_blank_max = fields.Float(string='空白率上限（%）', default=10.0)
    max_rounds = fields.Integer(string='修正輪上限', default=3)

    item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id', string='計畫項目')
    story_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                     domain=[('kind', '=', 'story')], string='故事')
    chapter_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                       domain=[('kind', '=', 'chapter')], string='章節')
    flow_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                    domain=[('kind', '=', 'flow')], string='流程')
    role_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                    domain=[('kind', '=', 'role')], string='角色')
    data_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                    domain=[('kind', '=', 'data')], string='資料需求')
    exclusion_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                         domain=[('kind', '=', 'exclusion')], string='排除')
    question_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                        domain=[('kind', '=', 'question')], string='待決事項')
    instruction_item_ids = fields.One2many('corpaas.knowledge.plan.item', 'plan_id',
                                           domain=[('kind', '=', 'instruction')], string='內容指示')
    line_ids = fields.One2many('corpaas.knowledge.scope_line', 'plan_id', string='範圍底稿')
    module_ids = fields.One2many('corpaas.knowledge.source_module', 'plan_id', string='關聯模組')
    relation_ids = fields.One2many('corpaas.knowledge.module_relation', 'plan_id', string='模組關係')
    check_ids = fields.One2many('corpaas.knowledge.check', 'plan_id', string='檢查紀錄')
    run_ids = fields.One2many('corpaas.knowledge.run', 'plan_id', string='執行紀錄')

    lines_total = fields.Integer(string='底稿列', compute='_compute_coverage', store=True)
    lines_chapter = fields.Integer(string='入選列', compute='_compute_coverage', store=True)
    lines_excluded = fields.Integer(string='排除列', compute='_compute_coverage', store=True)
    lines_next = fields.Integer(string='下期列', compute='_compute_coverage', store=True)
    lines_unassigned = fields.Integer(string='未歸屬', compute='_compute_coverage', store=True)

    cost_estimate = fields.Float(string='預估 AI 成本（USD）', readonly=True, digits=(10, 2))
    cost_actual = fields.Float(string='實際 AI 成本（USD）', compute='_compute_cost', digits=(10, 2))
    rounds = fields.Integer(string='已跑修正輪', readonly=True, copy=False)
    stop_reason = fields.Char(string='停止原因', readonly=True, copy=False)
    last_metrics_json = fields.Text(readonly=True, copy=False)

    approve_mode = fields.Selection([('manual', '人工'), ('auto', '自動')], string='核准方式',
                                    readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='核准人', readonly=True, copy=False)
    approved_at = fields.Datetime(string='核准時間', readonly=True, copy=False)
    t1_check_id = fields.Many2one('corpaas.knowledge.check', string='起草前檢查', readonly=True,
                                  copy=False)
    t2_check_id = fields.Many2one('corpaas.knowledge.check', string='核准前檢查', readonly=True,
                                  copy=False)
    design_pack = fields.Text(string='計畫設計輸入包', readonly=True, copy=False,
                              help='起草時的輸入快照，讓計畫可以重現')
    review_notes = fields.Text(string='審閱意見', help='寫下意見後按「AI 修訂」')
    trial_html = fields.Html(string='試寫', readonly=True, sanitize=False, copy=False)
    report_html = fields.Html(string='驗收報告', readonly=True, sanitize=False, copy=False)
    decisions_html = fields.Html(string='需要你決定', compute='_compute_decisions', sanitize=False)
    summary_html = fields.Html(string='計畫摘要', compute='_compute_summary_html', sanitize=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('package_version_uniq', 'unique(package_id, source_type, version)',
         '同一方案、同一來源的計畫版本不能重複。'),
    ]

    @api.depends('package_id', 'version', 'version_type')
    def _compute_name(self):
        types = dict(self._fields['version_type'].selection)
        for rec in self:
            rec.name = _('%(p)s 說明書製作計畫 v%(v)s（%(t)s）',
                         p=rec.package_id.display_name or '', v=rec.version,
                         t=types.get(rec.version_type, ''))

    @api.depends('line_ids.assignment')
    def _compute_coverage(self):
        for rec in self:
            counts = {k: 0 for k, _l in ASSIGNMENTS}
            for line in rec.line_ids:
                counts[line.assignment] = counts.get(line.assignment, 0) + 1
            rec.lines_total = len(rec.line_ids)
            rec.lines_chapter = counts['chapter']
            rec.lines_excluded = counts['exclude']
            rec.lines_next = counts['next']
            rec.lines_unassigned = counts['unassigned']

    def _compute_cost(self):
        Call = self.env['corpaas.knowledge.ai.call'].sudo()
        for rec in self:
            tokens = [t for t in rec.run_ids.mapped('token') if t]
            dom = ['|', '&', ('res_model', '=', rec._name), ('res_id', '=', rec.id)]
            dom += [('refresh_token', 'in', tokens)] if tokens else [('id', '=', 0)]
            rows = Call.read_group(dom, ['cost_usd:sum'], [])
            rec.cost_actual = rows[0]['cost_usd'] if rows and rows[0].get('cost_usd') else 0.0

    def _compute_decisions(self):
        esc = html_mod.escape
        for rec in self:
            parts = []
            questions = rec.question_item_ids.filtered(lambda i: not i.answer and i.change != 'remove')
            if questions:
                parts.append('<p><b>%s</b></p><ul>%s</ul>' % (
                    esc(_('待決事項（請在「待決事項」分頁回答）')),
                    ''.join('<li>%s</li>' % esc(q.name) for q in questions)))
            low = rec.item_ids.filtered(lambda i: i.confidence == 'low' and not i.confirmed
                                        and i.kind not in ('question', 'instruction')
                                        and i.change != 'remove')
            if low:
                parts.append('<p><b>%s</b></p><ul>%s</ul>' % (
                    esc(_('低信心項目（請確認或修改）')),
                    ''.join('<li>[%s] %s</li>' % (esc(dict(ITEM_KINDS).get(i.kind, '')), esc(i.name))
                            for i in low[:20])))
            if rec.lines_unassigned:
                parts.append('<p>%s</p>' % esc(_('有 %s 個功能點還沒有歸屬') % rec.lines_unassigned))
            if rec.cost_estimate and rec.budget and rec.cost_estimate > rec.budget:
                parts.append('<p>%s</p>' % esc(_('預估成本 $%(c).2f 超過預算 $%(b).2f：請縮小範圍或提高預算',
                                                 c=rec.cost_estimate, b=rec.budget)))
            changed = rec.item_ids.filtered(lambda i: i.change in ('new', 'modify', 'remove'))
            if rec.parent_id and changed:
                parts.append('<p><b>%s</b></p><ul>%s</ul>' % (
                    esc(_('和上一版不同')),
                    ''.join('<li>%s：%s</li>' % (esc(dict(CHANGES).get(i.change, '')), esc(i.name))
                            for i in changed[:30])))
            blocks = rec.t1_check_id.blocking_text() if rec.t1_check_id else ''
            if blocks:
                parts.append('<p><b>%s</b></p><p>%s</p>' % (esc(_('檢查未通過')), esc(blocks)))
            rec.decisions_html = ''.join(parts) or '<p class="text-muted">%s</p>' % esc(
                _('沒有需要你決定的事項'))

    def _compute_summary_html(self):
        esc = html_mod.escape
        for rec in self:
            story = rec.story_item_ids[:1]
            data = story.content() if story else {}
            rows = [
                (_('公司故事'), data.get('company') and '%s：%s' % (data.get('company'), data.get('model') or '')),
                (_('章節'), _('%s 章') % len(rec.chapter_item_ids.filtered(lambda i: i.change != 'remove'))),
                (_('流程'), _('%s 條') % len(rec.flow_item_ids.filtered(lambda i: i.change != 'remove'))),
                (_('角色'), '、'.join(rec.role_item_ids.filtered(lambda i: i.change != 'remove').mapped('name'))),
                (_('範圍'), _('入選 %(a)s／排除 %(b)s／下期 %(c)s（共 %(t)s）', a=rec.lines_chapter,
                              b=rec.lines_excluded, c=rec.lines_next, t=rec.lines_total)),
                (_('預估成本'), '$%.2f／預算 $%.2f' % (rec.cost_estimate or 0, rec.budget or 0)),
            ]
            rec.summary_html = '<table class="table table-sm">%s</table>' % ''.join(
                '<tr><th style="width:8em">%s</th><td>%s</td></tr>' % (esc(k), esc(str(v or '—')))
                for k, v in rows)

    # ------------------------------------------------------------------
    def _check_editable(self):
        for rec in self:
            if rec.state not in OPEN_STATES:
                raise UserError(_('計畫「%s」已經核准，請建立下一個版本再修改。') % rec.display_name)

    def story(self):
        """故事項目的內容 dict（沒有就空 dict）。"""
        self.ensure_one()
        item = self.story_item_ids.filtered(lambda i: i.change != 'remove')[:1]
        return item.content() if item else {}

    def live_items(self, kind=None):
        self.ensure_one()
        items = self.item_ids.filtered(lambda i: i.change != 'remove')
        return items.filtered(lambda i: i.kind == kind) if kind else items

    def action_open_lines(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('範圍底稿'),
                'res_model': 'corpaas.knowledge.scope_line', 'view_mode': 'list,form',
                'domain': [('plan_id', '=', self.id)], 'context': {'default_plan_id': self.id}}


class KnowledgePlanItem(models.Model):
    _name = 'corpaas.knowledge.plan.item'
    _description = '計畫項目'
    _order = 'plan_id, kind, sequence, id'

    plan_id = fields.Many2one('corpaas.knowledge.plan', required=True, ondelete='cascade', index=True)
    package_id = fields.Many2one(related='plan_id.package_id', store=True)
    kind = fields.Selection(ITEM_KINDS, string='類型', required=True, index=True)
    key = fields.Char(string='代碼', required=True, index=True,
                      help='穩定代碼：計畫改版時用來對應已展開的紀錄')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='標題', required=True)
    content_json = fields.Text(string='內容', default='{}')
    summary = fields.Text(string='說明')
    evidence = fields.Text(string='依據')
    confidence = fields.Selection(CONFIDENCE, string='信心', default='medium')
    confirmed = fields.Boolean(string='已確認', help='審閱者確認過；AI 修訂不會改動')
    locked = fields.Boolean(string='已鎖定', help='審閱者改過；AI 修訂不會改動')
    change = fields.Selection(CHANGES, string='相對前一版', default='new')
    answer = fields.Text(string='回答', help='待決事項的回答')
    res_model = fields.Char(string='展開模型', readonly=True)
    res_id = fields.Integer(string='展開紀錄', readonly=True)
    line_count = fields.Integer(string='功能點', compute='_compute_line_count')

    _sql_constraints = [('plan_kind_key_uniq', 'unique(plan_id, kind, key)', '同一計畫的項目代碼不能重複。')]

    def _compute_line_count(self):
        Line = self.env['corpaas.knowledge.scope_line']
        groups = Line.read_group([('item_id', 'in', self.ids)], ['item_id'], ['item_id'])
        counts = {g['item_id'][0]: g['item_id_count'] for g in groups if g['item_id']}
        for rec in self:
            rec.line_count = counts.get(rec.id, 0)

    def content(self):
        self.ensure_one()
        return _j(self.content_json, {}) or {}

    def set_content(self, data):
        self.ensure_one()
        self.content_json = json.dumps(data or {}, ensure_ascii=False)

    def record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return None
        rec = self.env[self.res_model].sudo().browse(self.res_id).exists()
        return rec or None

    def write(self, vals):
        # 審閱者在介面上改內容 → 自動鎖定（系統寫入帶 knowledge_plan_system 不鎖）
        human = not self.env.context.get('knowledge_plan_system')
        if human and set(vals) & {'name', 'content_json', 'summary'}:
            self.mapped('plan_id')._check_editable()
            vals = dict(vals, locked=True)
        if human and 'answer' in vals:
            self.mapped('plan_id')._check_editable()
        return super().write(vals)

    def action_confirm(self):
        self.mapped('plan_id')._check_editable()
        self.with_context(knowledge_plan_system=True).write({'confirmed': True})
        return True


class KnowledgeScopeLine(models.Model):
    _name = 'corpaas.knowledge.scope_line'
    _description = '範圍底稿列'
    _order = 'plan_id, module, kind, id'

    plan_id = fields.Many2one('corpaas.knowledge.plan', required=True, ondelete='cascade', index=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', string='功能點', required=True,
                                 ondelete='cascade', index=True)
    module = fields.Char(string='模組', index=True)
    module_category = fields.Selection([('own', '方案自有'), ('odoo', 'Odoo 官方'),
                                        ('third', '第三方'), ('tech', '技術模組')], string='模組分類')
    kind = fields.Char(string='種類')
    flow_id = fields.Many2one('corpaas.knowledge.flow', string='所在流程', ondelete='set null')
    usage = fields.Float(string='使用量')
    classification = fields.Char(string='分類')
    has_pack = fields.Boolean(string='有資料包', help='畫面用到的模型有示範資料包可以涵蓋')
    assignment = fields.Selection(ASSIGNMENTS, string='歸屬', default='unassigned', required=True,
                                  index=True)
    item_id = fields.Many2one('corpaas.knowledge.plan.item', string='章節', ondelete='set null',
                              domain="[('plan_id', '=', plan_id), ('kind', '=', 'chapter')]")
    reason = fields.Char(string='原因')
    confidence = fields.Selection(CONFIDENCE, string='信心', default='medium')
    by_rule = fields.Boolean(string='規則判定', help='依規則（技術模組、未改的官方畫面…）直接判定，沒問 AI')
    locked = fields.Boolean(string='已鎖定')

    _sql_constraints = [('plan_feature_uniq', 'unique(plan_id, feature_id)', '同一計畫的功能點只能有一列。')]

    def write(self, vals):
        if not self.env.context.get('knowledge_plan_system') and \
                set(vals) & {'assignment', 'item_id', 'reason'}:
            self.mapped('plan_id')._check_editable()
            vals = dict(vals, locked=True)
        return super().write(vals)


class KnowledgeCheck(models.Model):
    _name = 'corpaas.knowledge.check'
    _description = '計畫檢查紀錄'
    _order = 'id desc'

    plan_id = fields.Many2one('corpaas.knowledge.plan', ondelete='cascade', index=True)
    package_id = fields.Many2one('infrastructure.solution.package', ondelete='cascade', index=True)
    moment = fields.Selection([('t1', 'T1 起草前'), ('t2', 'T2 核准前'), ('t3', 'T3 前哨批'),
                               ('t4', 'T4 關卡')], string='時點', required=True)
    state = fields.Selection([('pass', '通過'), ('warn', '警告'), ('block', '擋下')], string='結果',
                             required=True, default='pass')
    result_json = fields.Text(string='結果明細', default='[]')
    result_html = fields.Html(string='檢查結果', compute='_compute_html', sanitize=False)

    def results(self):
        self.ensure_one()
        return _j(self.result_json, []) or []

    def blocking_text(self):
        self.ensure_one()
        return '；'.join('%s %s' % (r.get('code'), r.get('reason') or r.get('name'))
                        for r in self.results() if r.get('state') == 'block')

    def _compute_html(self):
        esc = html_mod.escape
        badge = {'pass': ('success', _('通過')), 'warn': ('warning', _('警告')),
                 'block': ('danger', _('擋下'))}
        for rec in self:
            rows = []
            for r in rec.results():
                cls, label = badge.get(r.get('state'), ('secondary', r.get('state')))
                rows.append('<tr><td><code>%s</code></td><td>%s</td><td><span class="badge text-bg-%s">%s</span>'
                            '</td><td>%s</td></tr>' % (esc(r.get('code') or ''), esc(r.get('name') or ''),
                                                       cls, esc(label), esc(r.get('reason') or '')))
            rec.result_html = '<table class="table table-sm">%s</table>' % ''.join(rows)


class KnowledgeSourceModule(models.Model):
    _name = 'corpaas.knowledge.source_module'
    _description = '計畫的關聯模組'
    _order = 'plan_id, origin, module'

    plan_id = fields.Many2one('corpaas.knowledge.plan', required=True, ondelete='cascade', index=True)
    module = fields.Char(string='模組', required=True, index=True)
    origin = fields.Selection([('package', '方案本體'), ('tier', '服務層級'), ('addon', '加購'),
                               ('dev', '開發模組'), ('customer', '客戶實例'), ('depends', '相依')],
                              string='來源', required=True, default='package')
    category = fields.Selection([('own', '方案自有'), ('odoo', 'Odoo 官方'), ('third', '第三方'),
                                 ('tech', '技術模組')], string='分類')
    version_ref = fields.Char(string='版本', help='版本雜湊或發行標籤')
    feature_count = fields.Integer(string='功能點')
    installed = fields.Boolean(string='已安裝於分析環境')
    summarized = fields.Boolean(string='已有模組摘要')
    note = fields.Char(string='備註')

    _sql_constraints = [('plan_module_uniq', 'unique(plan_id, module)', '同一計畫的模組只能有一列。')]


class KnowledgeModuleRelation(models.Model):
    _name = 'corpaas.knowledge.module_relation'
    _description = '模組關係'
    _order = 'plan_id, kind, id'

    plan_id = fields.Many2one('corpaas.knowledge.plan', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('depends', '相依'), ('inherits', '繼承'), ('handoff', '流程交接')],
                            string='種類', required=True)
    src = fields.Char(string='起點', required=True)
    dst = fields.Char(string='終點', required=True)
    note = fields.Char(string='說明')


class KnowledgeRunPlan(models.Model):
    _inherit = 'corpaas.knowledge.run'

    plan_id = fields.Many2one('corpaas.knowledge.plan', string='說明書製作計畫', index=True,
                              ondelete='set null', readonly=True)


class KnowledgeScenarioPrivate(models.Model):
    _inherit = 'corpaas.knowledge.scenario'

    knowledge_private_partner_id = fields.Many2one(
        'res.partner', string='客戶專屬', index=True, ondelete='set null',
        help='建議書來源的客戶專屬情境：只發佈到該客戶的私人課程，不進範本庫')
    knowledge_scope_capability_ids = fields.Many2many(
        'corpaas.knowledge.capability', 'corpaas_knowledge_scenario_scope_cap_rel', 'scenario_id',
        'capability_id', string='適用章節', help='客戶專屬情境只說明這些章節（建議書計畫的章節）')


class SolutionPackagePlan(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_target_brief = fields.Text(
        string='目標客群說明',
        help='說明書製作計畫的背景：目標客戶的產業、規模、現況與痛點。只給說明書使用，不出現在報價單。')
    knowledge_automation = fields.Selection(AUTOMATION, string='自動化等級', default='standard',
                                            required=True)
    knowledge_plan_ids = fields.One2many('corpaas.knowledge.plan', 'package_id', string='說明書製作計畫')
    knowledge_plan_id = fields.Many2one('corpaas.knowledge.plan', string='生效中的計畫',
                                        compute='_compute_knowledge_plan')
    knowledge_plan_mode = fields.Boolean(string='依計畫產出', compute='_compute_knowledge_plan',
                                         help='有生效中的計畫：範圍、章節、故事都以計畫為準，不再產生圈選提案')

    def _compute_knowledge_plan(self):
        """生效中的計畫：產品來源優先（方案本身的說明書）；建議書來源的計畫各自管客戶專屬情境。"""
        Plan = self.env['corpaas.knowledge.plan'].sudo()
        for rec in self:
            plan = Plan.search([('package_id', '=', rec.id), ('state', 'in', LIVE_STATES),
                                ('source_type', '=', 'product')],
                               order='version desc, id desc', limit=1) if rec.id else Plan
            rec.knowledge_plan_id = plan
            rec.knowledge_plan_mode = bool(plan)

    def action_knowledge_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('說明書製作計畫'),
                'res_model': 'corpaas.knowledge.plan', 'view_mode': 'list,form',
                'domain': [('package_id', '=', self.id)], 'context': {'default_package_id': self.id}}


#: 新架構的可調參數與預設值（規格第 21 節）：畫面上調整即生效，不必佈署
PLAN_PARAM_DEFAULTS = {
    'corpaas_knowledge.plan_target_shot_rate': '95',
    'corpaas_knowledge.plan_target_review_rate': '85',
    'corpaas_knowledge.plan_target_blank_max': '10',
    'corpaas_knowledge.plan_max_rounds': '3',
    'corpaas_knowledge.plan_canary_shot_rate': '80',
    'corpaas_knowledge.plan_no_progress_rounds': '2',
    'corpaas_knowledge.plan_minor_budget_ratio': '0.1',
    'corpaas_knowledge.plan_require_summary': '1',
    'corpaas_knowledge.plan_explore_ratio': '0.4',
    'corpaas_knowledge.plan_repair_ratio': '0.3',
    'corpaas_knowledge.ledger_semantic_limit': '40',
    'corpaas_knowledge.rename_auto_threshold': '0.95',
    'corpaas_knowledge.feedback_batch_min': '1',
    'corpaas_knowledge.feedback_hourly_limit': '10',
}


class KnowledgePlanParams(models.AbstractModel):
    _name = 'corpaas.knowledge.plan.params'
    _description = '說明書製作計畫參數'

    @api.model
    def _seed_defaults(self):
        """缺少的參數才補預設值（已存在的不動；用 XML record 種參數會撞唯一鍵）。"""
        icp = self.env['ir.config_parameter'].sudo()
        for key, value in PLAN_PARAM_DEFAULTS.items():
            if icp.get_param(key) is False:
                icp.set_param(key, value)
        return True
