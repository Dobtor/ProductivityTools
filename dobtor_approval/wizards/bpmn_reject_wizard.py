# -*- coding: utf-8 -*-
"""駁回精靈 — DESIGN_APPROVAL_EVENT.md §5/§6.6。

可選駁回去向：退回申請人 / 退回上一關 / 退回指定關卡。
"""
from odoo import fields, models, _
from odoo.exceptions import UserError


class BpmnRejectWizard(models.TransientModel):
    _name = 'bpmn.reject.wizard'
    _description = '駁回簽核事件'

    link_id = fields.Many2one('bpmn.activity.link', string='來源事件',
                              required=True, ondelete='cascade')
    destination = fields.Selection([
        ('applicant', '退回申請人'),
        ('previous', '退回上一關'),
        ('node', '退回指定關卡'),
    ], string='駁回去向', default='applicant', required=True)
    target_element = fields.Char(string='指定關卡 (element id)')
    reason = fields.Text(string='駁回理由', required=True)

    def action_reject(self):
        self.ensure_one()
        link = self.link_id
        if self.destination == 'node':
            if not self.target_element:
                raise UserError(_('請填入要退回的關卡 element id。'))
            link.reject_to_element = self.target_element
        link.action_bpmn_reject(feedback=self.reason)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
