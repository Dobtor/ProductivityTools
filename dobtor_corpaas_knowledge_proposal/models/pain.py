# -*- coding: utf-8 -*-
"""痛點、痛點對應能力、估算明細、主資料（資料移轉檢核表）。

★ 這些都是建議書的一部分：建議書送出後一律唯讀（寫、建、刪都擋）。
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.models.catalog import COLORS

from .effort import ACTIVITIES
from .proposal import is_internal


class ProposalChildMixin(models.AbstractModel):
    _name = 'corpaas.knowledge.proposal.child'
    _description = '建議書子記錄（送出後唯讀）'

    def _proposal_of(self):
        return self.mapped('proposal_id')

    def _check_proposal_editable(self, proposals):
        if is_internal(self.env):
            return
        frozen = proposals.filtered(lambda p: p.state != 'draft')
        if frozen:
            raise UserError(_('建議書「%s」已送出，內容不可再修改；請複製一份新版。')
                            % frozen[0].display_name)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self._check_proposal_editable(recs._proposal_of())
        return recs

    def write(self, vals):
        self._check_proposal_editable(self._proposal_of())
        res = super().write(vals)
        self._check_proposal_editable(self._proposal_of())
        return res

    def unlink(self):
        self._check_proposal_editable(self._proposal_of())
        return super().unlink()


class ProposalPain(models.Model):
    _name = 'corpaas.knowledge.pain'
    _description = '客戶痛點'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, id'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    department = fields.Char(string='部門')
    description = fields.Text(string='客戶提問／痛點', required=True)
    current_state = fields.Text(string='現況說明／客戶補充')
    proposed_solution = fields.Text(string='解決方案（售前）')
    color_hint = fields.Selection(COLORS, string='售前四色')
    module_hint = fields.Char(string='對應原生功能／模組')
    quote_note = fields.Text(string='報價重點／待確認')
    source = fields.Selection([('manual', '手動'), ('import', '匯入'), ('ai_source', 'AI 自筆記萃取')],
                              default='manual', required=True)
    mapping_ids = fields.One2many('corpaas.knowledge.mapping', 'pain_id', string='對應能力',
                                  copy=True)

    @api.depends('department', 'description')
    def _compute_display_name(self):
        for rec in self:
            text = (rec.description or '').splitlines()[0][:40] if rec.description else ''
            rec.display_name = '[%s] %s' % (rec.department, text) if rec.department else text


class ProposalMapping(models.Model):
    _name = 'corpaas.knowledge.mapping'
    _description = '痛點對應能力'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, pain_id, id'

    pain_id = fields.Many2one('corpaas.knowledge.pain', required=True, ondelete='cascade',
                              index=True)
    proposal_id = fields.Many2one(related='pain_id.proposal_id', store=True, index=True)
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='能力',
                                    ondelete='restrict',
                                    help='留空＝方案沒有對應能力（客製或沿用現況）。')
    color = fields.Selection(COLORS, string='四色', required=True, default='native')
    # ★ 能力缺幾個模組就要報幾個：只帶第一個，客戶買了還是開不起來。
    addon_product_ids = fields.Many2many(
        'product.product', 'corpaas_knowledge_mapping_addon_rel', 'mapping_id', 'product_id',
        string='加購模組產品')
    custom_days_low = fields.Float(string='客製人天（低）')
    custom_days_high = fields.Float(string='客製人天（高）')
    note = fields.Text(string='說明')
    confirmed = fields.Boolean(string='已確認', help='只有確認的對應會進估算與報價。')
    source = fields.Selection([('manual', '手動'), ('ai', 'AI')], default='manual')

    def action_confirm(self):
        self.write({'confirmed': True})
        return True

    def action_unconfirm(self):
        self.write({'confirmed': False})
        return True


class ProposalEstimateLine(models.Model):
    _name = 'corpaas.knowledge.estimate_line'
    _description = '估算明細'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, is_custom, capability_id, activity'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    mapping_id = fields.Many2one('corpaas.knowledge.mapping', ondelete='set null')
    template_id = fields.Many2one('corpaas.knowledge.effort_template', string='工時範本',
                                  ondelete='set null')
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='能力',
                                    ondelete='set null')
    activity = fields.Selection(ACTIVITIES + [('tuning', '設定微調'), ('custom', '客製開發')],
                                string='工項',
                                required=True)
    driver_qty = fields.Float(string='驅動量')
    days = fields.Float(string='人天')
    day_rate = fields.Float(string='日費率')
    internal_day_cost = fields.Float(string='內部人天成本')
    amount = fields.Float(string='金額', compute='_compute_amounts', store=True)
    internal_cost = fields.Float(string='內部成本', compute='_compute_amounts', store=True)
    is_custom = fields.Boolean(string='客製')
    note = fields.Char(string='說明')
    currency_id = fields.Many2one(related='proposal_id.currency_id')

    @api.depends('days', 'day_rate', 'internal_day_cost')
    def _compute_amounts(self):
        for rec in self:
            rec.amount = rec.days * rec.day_rate
            rec.internal_cost = rec.days * rec.internal_day_cost

    @api.depends('capability_id', 'activity')
    def _compute_display_name(self):
        labels = dict(self._fields['activity'].selection)
        for rec in self:
            rec.display_name = '%s／%s' % (rec.capability_id.name or _('通用'),
                                          labels.get(rec.activity, rec.activity))


class ProposalMasterData(models.Model):
    """資料移轉檢核表：情境示範資料用到的模型＝客戶要提供的主資料。"""
    _name = 'corpaas.knowledge.proposal.master_data'
    _description = '主資料（資料移轉檢核表）'
    _inherit = ['corpaas.knowledge.proposal.child']
    _order = 'proposal_id, sequence, model'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    model = fields.Char(string='模型', required=True)
    model_label = fields.Char(string='資料', compute='_compute_model_label')
    record_count = fields.Integer(string='預估筆數')
    provided = fields.Boolean(string='客戶已提供')
    note = fields.Char(string='備註')

    _sql_constraints = [('model_uniq', 'unique(proposal_id, model)', '主資料模型重複')]

    @api.depends('model')
    def _compute_model_label(self):
        IrModel = self.env['ir.model'].sudo()
        for rec in self:
            m = IrModel._get(rec.model) if rec.model else IrModel
            rec.model_label = m.name if m else rec.model
