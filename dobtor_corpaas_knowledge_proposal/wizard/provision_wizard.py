# -*- coding: utf-8 -*-
"""「確認開通」：建議書報價單選擇開通模式後放行。

★ 沿用後檯「建立 CorPaaS 訂閱單」精靈（corpaas.order.wizard）的欄位與三種模式
  （new／stack／change_tier），只是對**既有的這張報價單**套用，而不是另建一張：
  價格已經在報價單上，另建一張會重複收費。
★ 客戶已經有平台時，模式不給預設值（必須明確選）——既有客戶預設開新平台是錯的。
★ 疊加／換層級的計價跟新平台不同（取高·增額、首期比例），所以只能在**確認報價單前**選；
  已確認的單只能放行為新平台，要改模式請取消後設回草稿。
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KnowledgeProvisionWizard(models.TransientModel):
    _name = 'corpaas.knowledge.provision.wizard'
    _inherit = 'corpaas.order.wizard'
    _description = '建議書報價單：確認開通'

    order_id = fields.Many2one('sale.order', string='報價單', required=True,
                               ondelete='cascade')
    order_state = fields.Selection(related='order_id.state')
    existing_instance_ids = fields.Many2many(
        'infrastructure.instance', string='客戶既有平台',
        compute='_compute_existing_instance_ids')

    @api.model
    def _knowledge_existing_instances(self, partner):
        partner = partner.commercial_partner_id
        return self.env['dobtor.contract'].sudo().search([
            ('partner_id', 'child_of', partner.id), ('instance_id', '!=', False),
        ]).mapped('instance_id')

    @api.depends('partner_id')
    def _compute_existing_instance_ids(self):
        for w in self:
            w.existing_instance_ids = w._knowledge_existing_instances(w.partner_id) \
                if w.partner_id else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['sale.order'].browse(
            res.get('order_id') or self.env.context.get('default_order_id')).exists()
        if not order:
            return res
        line = order._knowledge_package_line()
        res.update({'order_id': order.id, 'partner_id': order.partner_id.id})
        if line:
            res.update({
                'product_id': line.product_id.id,
                'package_tier': line.package_tier or res.get('package_tier'),
                'concurrent_users': line.concurrent_users,
                'storage_gb': line.storage_gb,
                'committed_qty': line.committed_qty,
                'committed_usage': line.committed_usage,
                'staging': line.staging,
            })
        if self._knowledge_existing_instances(order.partner_id):
            res['mode'] = False
        return res

    def action_create_order(self):
        raise UserError(_('請用「確認開通」。'))

    def _knowledge_apply_mode(self, order, line):
        """把模式旗標寫到報價單上（與 corpaas.order.wizard.action_create_order 同一套）。"""
        self.ensure_one()
        if self.mode == 'new':
            order.is_to_create_paas = True
            if self.env_name:
                order.is_default_instance_d_name = self.env_name
            return
        order.instance_id = self.instance_id.id
        if self.mode == 'change_tier':
            order.paas_change_type = 'change_tier'
            line.package_tier = self.package_tier
            return
        # stack：只能疊在企業層；非企業層先在同一張單加升級行（升級行要先於疊加行）
        contract = self.env['dobtor.contract'].sudo().search([
            ('instance_id', '=', self.instance_id.id),
            ('partner_id', '=', order.partner_id.id)], limit=1)
        if contract:
            if line.product_id in contract._corpaas_active_billed_lines().mapped('product_id'):
                raise UserError(_('平台「%s」已經在用這個方案，不能疊加；請改用「換層級」。')
                                % self.instance_id.display_name)
            order.corpaas_stack_contract_id = contract.id
        if self.instance_id.env_service_tier != 'custom':
            if not (contract and order._corpaas_add_upgrade_line(contract, 'custom')):
                raise UserError(_('平台「%s」不是企業層，且找不到可升級的基準方案，無法疊加。')
                                % self.instance_id.display_name)
        line.write({'is_stack_line': True, 'package_tier': 'custom'})

    def action_apply(self):
        self.ensure_one()
        order = self.order_id
        if not order._knowledge_provision_held():
            raise UserError(_('這張報價單不需要（或已經）確認開通。'))
        if not self.mode:
            raise UserError(_('請選擇開通方式。'))
        if self.mode in ('stack', 'change_tier') and not self.instance_id:
            raise UserError(_('疊加／換層級需選擇既有平台。'))
        line = order._knowledge_package_line()
        if not line:
            raise UserError(_('報價單上沒有訂閱方案行，無法開通。'))
        labels = dict(self._fields['mode']._description_selection(self.env))
        if order.state in ('draft', 'sent'):
            self._knowledge_apply_mode(order, line)
            order.knowledge_provision_state = 'released'
            order.message_post(body=_('確認開通：%s。確認報價單時會依此開通。') % labels[self.mode])
        elif order.state == 'sale':
            if self.mode != 'new':
                raise UserError(_(
                    '報價單已確認，價格是以新平台計算；疊加或換層級的計價不同。'
                    '請先取消報價單並設回草稿，再按「確認開通」選擇模式後重新確認。'))
            self._knowledge_apply_mode(order, line)
            order.knowledge_provision_state = 'released'
            order.message_post(body=_('確認開通：%s，開始開通。') % labels[self.mode])
            order._maybe_provision_by_tier()
        else:
            raise UserError(_('報價單已取消。'))
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order',
                'res_id': order.id, 'view_mode': 'form', 'target': 'current'}
