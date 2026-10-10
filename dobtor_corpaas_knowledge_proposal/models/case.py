# -*- coding: utf-8 -*-
"""報價案件：一個客戶機會底下的一串「版本」（建議書）。

★ 為什麼要有案件：以前「複製新版」只是複製成一張新的草稿、領新的流水號，版本之間
  互不相識 —— 沒有版號、沒有前版指標、不知道哪一版是客戶現在手上那一份。報價規格書
  （以賽亞 v2.0、預建 v6.0、SKF 7.4 …）每一份都是「某個案件的第 N 版」，所以版本是一等公民：
  案件管「這個客戶這件事」，版本（`corpaas.knowledge.proposal`）管「某一次送出的內容」。
★ 一個商機可以有多個案件（追加報價、分階段各一案），所以 `opportunity_id` 不是唯一的；
  追加案用 `parent_case_id` 指向原案（極電 BYOD 的「與原合約之對照」）。
★ 提案模組直接依賴 `sale_crm`：商機不是可選的橋接，而是案件的來源與去處。
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CASE_STATES = [('open', '進行中'), ('won', '成交'), ('lost', '未成交')]


class KnowledgeCase(models.Model):
    _name = 'corpaas.knowledge.case'
    _description = '報價案件'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='案件編號', required=True, copy=False, readonly=True,
                       default='/')
    title = fields.Char(string='案件名稱', tracking=True,
                        help='例如「營運治理導入」「BYOD 追加開發」；留空時以客戶名稱顯示。')
    partner_id = fields.Many2one('res.partner', string='客戶', required=True, tracking=True)
    opportunity_id = fields.Many2one(
        'crm.lead', string='商機', tracking=True, index=True, ondelete='set null',
        domain="[('type', '=', 'opportunity')]",
        help='一個商機可以有多個案件（追加報價、分階段各一案）。')
    parent_case_id = fields.Many2one(
        'corpaas.knowledge.case', string='原案件', index=True, ondelete='set null',
        help='追加報價：這個案件是在哪個既有案件之上追加的。')
    child_case_ids = fields.One2many('corpaas.knowledge.case', 'parent_case_id',
                                     string='追加案件')
    user_id = fields.Many2one('res.users', string='業務', default=lambda s: s.env.user)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda s: s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    version_ids = fields.One2many('corpaas.knowledge.proposal', 'case_id', string='版本')
    version_count = fields.Integer(compute='_compute_versions')
    current_version_id = fields.Many2one(
        'corpaas.knowledge.proposal', string='最新版本', compute='_compute_versions',
        store=True)
    quoted_version_id = fields.Many2one(
        'corpaas.knowledge.proposal', string='客戶手上的版本', compute='_compute_versions',
        store=True, help='最新一份已送出（或成交）的版本；草稿不算。')
    quoted_total = fields.Monetary(string='報價金額', compute='_compute_versions',
                                   store=True, help='客戶手上那一版的首年總額。')
    state = fields.Selection(CASE_STATES, string='狀態', compute='_compute_versions',
                             store=True, index=True, tracking=True)

    @api.depends('version_ids', 'version_ids.state', 'version_ids.version_major',
                 'version_ids.version_minor', 'version_ids.total')
    def _compute_versions(self):
        for case in self:
            versions = case.version_ids.sorted(
                lambda v: (v.version_major, v.version_minor, v.id), reverse=True)
            case.version_count = len(versions)
            case.current_version_id = versions[:1]
            quoted = versions.filtered(lambda v: v.state in ('sent', 'won'))[:1]
            case.quoted_version_id = quoted
            case.quoted_total = quoted.total if quoted else 0.0
            if versions.filtered(lambda v: v.state == 'won'):
                case.state = 'won'
            elif versions and all(v.state == 'lost' for v in versions):
                case.state = 'lost'
            else:
                case.state = 'open'

    @api.depends('name', 'title', 'partner_id')
    def _compute_display_name(self):
        for case in self:
            label = case.title or case.partner_id.display_name or ''
            case.display_name = '%s %s' % (case.name, label) if label else case.name

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = seq.next_by_code('corpaas.knowledge.case') or '/'
        return super().create(vals_list)

    @api.onchange('opportunity_id')
    def _onchange_opportunity_id(self):
        lead = self.opportunity_id
        if lead:
            self.partner_id = lead.partner_id or self.partner_id
            self.title = self.title or lead.name

    # ------------------------------------------------------------------
    # 版本號
    # ------------------------------------------------------------------
    def _next_version(self, major=False):
        """下一個版號 `(主版, 次版)`。

        次版 +1 是一般的「複製新版」（7.4 → 7.5）；`major=True` 是重大改版（6.x → 7.0）。
        ★ 以案件裡**已有的最大版號**為準，不是以被複製的那一版 —— 從 v1.0 複製、
          而 v1.1 已經存在時，新版是 v1.2，不是又一個 v1.1。
        """
        self.ensure_one()
        versions = self.version_ids
        if not versions:
            return 1, 0
        top = max((v.version_major, v.version_minor) for v in versions)
        return (top[0] + 1, 0) if major else (top[0], top[1] + 1)

    # ------------------------------------------------------------------
    # 動作
    # ------------------------------------------------------------------
    def action_open_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('版本'),
            'res_model': 'corpaas.knowledge.proposal', 'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id,
                        'default_partner_id': self.partner_id.id},
        }

    def action_new_version(self):
        """在這個案件底下開一份新版本（沒有任何版本時開 v1.0）。"""
        self.ensure_one()
        if self.current_version_id:
            return self.current_version_id.action_copy_new_version()
        proposal = self.env['corpaas.knowledge.proposal'].create({
            'case_id': self.id, 'partner_id': self.partner_id.id,
            'user_id': self.user_id.id, 'company_id': self.company_id.id})
        return {'type': 'ir.actions.act_window', 'res_model': proposal._name,
                'res_id': proposal.id, 'view_mode': 'form', 'target': 'current'}

    def action_open_opportunity(self):
        self.ensure_one()
        if not self.opportunity_id:
            raise UserError(_('這個案件沒有商機。'))
        return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead',
                'res_id': self.opportunity_id.id, 'view_mode': 'form', 'target': 'current'}

    # ------------------------------------------------------------------
    # 舊資料遷移
    # ------------------------------------------------------------------
    @api.model
    def _migrate_legacy_proposals(self):
        """沒有案件的建議書各自升為一個案件的 v1.0。回遷移筆數。

        ☠️ 不嘗試把舊的「複製新版」合併成同一案件：那時沒有記錄版本關係，
           用「同客戶」猜會把不同案件併在一起，而拆開比併錯容易修。
        ★ 建議書送出後被擋寫，遷移要經內部旗標才能寫（與送出按鈕同一條路）。
        """
        from .proposal import INTERNAL_CTX, INTERNAL_TOKEN
        Proposal = self.env['corpaas.knowledge.proposal'].sudo().with_context(
            **{INTERNAL_CTX: INTERNAL_TOKEN})
        legacy = Proposal.search([('case_id', '=', False)], order='id')
        for proposal in legacy:
            case = self.sudo().create({
                'partner_id': proposal.partner_id.id,
                'user_id': proposal.user_id.id,
                'company_id': proposal.company_id.id,
                'opportunity_id': proposal.sale_order_id.opportunity_id.id or False,
            })
            proposal.write({
                'case_id': case.id, 'version_major': 1, 'version_minor': 0,
                'version_date': (proposal.create_date or fields.Datetime.now()).date(),
            })
        return len(legacy)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    knowledge_case_ids = fields.One2many('corpaas.knowledge.case', 'opportunity_id',
                                         string='報價案件')
    knowledge_case_count = fields.Integer(compute='_compute_knowledge_case_count')

    @api.depends('knowledge_case_ids')
    def _compute_knowledge_case_count(self):
        data = self.env['corpaas.knowledge.case']._read_group(
            [('opportunity_id', 'in', self.ids)], ['opportunity_id'], ['__count'])
        counts = {lead.id: count for lead, count in data}
        for lead in self:
            lead.knowledge_case_count = counts.get(lead.id, 0)

    def action_view_knowledge_cases(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window', 'name': _('報價案件'),
            'res_model': 'corpaas.knowledge.case', 'view_mode': 'list,form',
            'domain': [('opportunity_id', '=', self.id)],
            'context': {'default_opportunity_id': self.id,
                        'default_partner_id': self.partner_id.id,
                        'default_title': self.name},
        }
        if self.knowledge_case_count == 1:
            action.update(view_mode='form', res_id=self.knowledge_case_ids.id)
        return action

    def action_create_knowledge_case(self):
        """從商機開一個報價案件（一個商機可以開很多個）。"""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('請先在商機上指定客戶，才能開報價案件。'))
        case = self.env['corpaas.knowledge.case'].create({
            'partner_id': self.partner_id.id, 'opportunity_id': self.id,
            'title': self.name, 'user_id': self.user_id.id or self.env.uid,
            'company_id': (self.company_id or self.env.company).id})
        return {'type': 'ir.actions.act_window', 'res_model': case._name,
                'res_id': case.id, 'view_mode': 'form', 'target': 'current'}

    def _knowledge_revenue_from_cases(self):
        """這個商機底下所有未失敗案件、客戶手上那一版的報價合計。"""
        self.ensure_one()
        cases = self.knowledge_case_ids.filtered(lambda c: c.state != 'lost')
        return sum(cases.mapped('quoted_total'))
