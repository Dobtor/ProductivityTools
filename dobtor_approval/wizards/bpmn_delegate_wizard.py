# -*- coding: utf-8 -*-
"""委派代簽精靈 — DESIGN_APPROVAL_EVENT.md §6.3。

把本事件交給代理人簽（重指派 mail.activity 與 link）。
"""
from odoo import fields, models, _


class BpmnDelegateWizard(models.TransientModel):
    _name = 'bpmn.delegate.wizard'
    _description = '委派代簽'

    link_id = fields.Many2one('bpmn.activity.link', string='來源事件',
                              required=True, ondelete='cascade')
    delegate_user_id = fields.Many2one('res.users', string='代理人', required=True)
    reason = fields.Text(string='委派理由')

    def action_delegate(self):
        self.ensure_one()
        link = self.link_id
        if link.activity_id and link.activity_id.active:
            link.activity_id.user_id = self.delegate_user_id.id
        link.write({
            'approver_user_id': self.delegate_user_id.id,
            'kind': 'delegate',
        })
        link.instance_id.message_post(body=_(
            '%(user)s 將「%(node)s」委派給 %(to)s 代簽。',
            user=self.env.user.name, node=link.node_name or '',
            to=self.delegate_user_id.name))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
