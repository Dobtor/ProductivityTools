# -*- coding: utf-8 -*-
"""從屬：對主體的鏡像紀錄送修改意見（第四期「主體修改意見通道」）。"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import protocol


class KnowledgeExchangeFeedbackWizard(models.TransientModel):
    _name = 'corpaas.knowledge.exchange.feedback.wizard'
    _description = '送修改意見給主體'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    record_name = fields.Char(string='項目', readonly=True)
    text = fields.Text(string='修改意見', required=True,
                       help='只寫對這份共用知識的意見；不要放客戶名稱、客戶資料')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        model = self.env.context.get('active_model')
        rid = self.env.context.get('active_id')
        if model and rid:
            rec = self.env[model].browse(rid)
            res.update({'res_model': model, 'res_id': rid, 'record_name': rec.display_name})
        return res

    def action_send(self):
        self.ensure_one()
        if self.res_model not in protocol.MODEL_KIND:
            raise UserError(_('這種紀錄不能送修改意見。'))
        rec = self.env[self.res_model].browse(self.res_id).exists()
        if not rec or rec.kb_sync_state != 'mirror':
            raise UserError(_('只有主體的鏡像紀錄需要送修改意見；本地紀錄直接修改即可。'))
        ok = self.env['corpaas.knowledge.exchange']._send_feedback(rec, self.text.strip())
        if not ok:
            raise UserError(_('主體沒有收下這則意見（可能主體已沒有這筆紀錄）。'))
        rec.message_post(body=_('已送修改意見給主體：%s') % self.text.strip()) if hasattr(rec, 'message_post') else None
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'message': _('已送給主體。'), 'next': {'type': 'ir.actions.act_window_close'}}}
