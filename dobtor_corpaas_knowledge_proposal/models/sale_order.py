# -*- coding: utf-8 -*-
"""建議書產生的報價單：確認時不自動開通。

★ dobtor_corpaas_sale 的 `action_confirm` 對每張單都呼叫 `_maybe_provision_by_tier()`，
  只要有自計費方案行、訂單沒掛平台（instance_id），就會開一座**新平台**——跟
  `is_to_create_paas` 無關。建議書的客戶常常已經有平台（該疊加或換層級），
  所以這裡對建議書來的單一律先擋下（回 True＝已處理，連同疊加／換層級分支一起跳過），
  等業務按「確認開通」選好模式（與後檯「建立 CorPaaS 訂閱單」精靈同一組模式）才放行。
☠️ 合約重建草稿（`corpaas_rebuild_draft`）也會走 `_maybe_provision_by_tier`：
  沒放行的單一樣擋，只是不重複留言。
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

PROVISION_STATES = [('hold', '待確認開通'), ('released', '已確認開通')]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    knowledge_proposal_id = fields.Many2one(
        'corpaas.knowledge.proposal', string='服務建議書', copy=False, readonly=True,
        index='btree_not_null')
    knowledge_provision_state = fields.Selection(
        PROVISION_STATES, string='建議書開通', copy=False, readonly=True,
        help='建議書來的報價單確認後不會自動開通；按「確認開通」選擇模式後才放行。')

    def _knowledge_provision_held(self):
        self.ensure_one()
        return bool(self.knowledge_proposal_id) and self.knowledge_provision_state != 'released'

    def _maybe_provision_by_tier(self):
        self.ensure_one()
        if self._knowledge_provision_held():
            if not self.env.context.get('corpaas_rebuild_draft'):
                self.message_post(body=_(
                    '這張報價單來自服務建議書 %s：確認後不會自動開通任何平台。'
                    '請按「確認開通」選擇新平台、疊加至既有平台或換層級。')
                    % self.knowledge_proposal_id.display_name)
            return True
        return super()._maybe_provision_by_tier()

    def _knowledge_package_line(self):
        """訂閱方案那一行：自計費方案行優先，其次建議書報的那個變體。"""
        self.ensure_one()
        billed = self.order_line.filtered(lambda l: l._is_corpaas_billed_package())
        if billed:
            return billed[:1]
        variant = self.knowledge_proposal_id._package_variant() \
            if self.knowledge_proposal_id.product_tmpl_id else self.env['product.product']
        return self.order_line.filtered(lambda l: variant and l.product_id == variant)[:1]

    def action_knowledge_confirm_provision(self):
        self.ensure_one()
        if not self._knowledge_provision_held():
            raise UserError(_('這張報價單不需要（或已經）確認開通。'))
        if self.state == 'cancel':
            raise UserError(_('報價單已取消。'))
        return {
            'type': 'ir.actions.act_window', 'name': _('確認開通'),
            'res_model': 'corpaas.knowledge.provision.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_order_id': self.id},
        }
