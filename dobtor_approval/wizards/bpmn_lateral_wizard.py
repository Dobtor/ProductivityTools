# -*- coding: utf-8 -*-
"""橫向送簽精靈（會辦/徵詢）— DESIGN_APPROVAL_EVENT.md §6.2。

同一精靈處理兩種情境：
- 送出：從一般簽核事件，把案子橫向送給同事（會辦=等待回覆才可續、徵詢=不等待）。
- 回覆：被會辦/徵詢者於其事件回覆意見。
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BpmnLateralWizard(models.TransientModel):
    _name = 'bpmn.lateral.wizard'
    _description = '橫向送簽（會辦/徵詢）'

    link_id = fields.Many2one('bpmn.activity.link', string='來源事件',
                              required=True, ondelete='cascade')
    is_reply = fields.Boolean(compute='_compute_is_reply')
    mode = fields.Selection([
        ('consult', '會辦（需回覆，本關等待）'),
        ('info', '徵詢（不等待，僅參考）'),
    ], string='送簽方式', default='consult', required=True)
    user_ids = fields.Many2many('res.users', string='送簽對象')
    reason = fields.Text(string='說明')
    reply = fields.Text(string='回覆意見')

    @api.depends('link_id')
    def _compute_is_reply(self):
        for wiz in self:
            wiz.is_reply = wiz.link_id.kind in ('lateral_consult', 'lateral_info')

    def action_send(self):
        self.ensure_one()
        link = self.link_id
        # ---- 回覆會辦/徵詢 ----
        if link.kind in ('lateral_consult', 'lateral_info'):
            link.write({
                'consult_reply': self.reply or self.reason,
                'decision': 'approved',
                'decided_by': self.env.user.id,
            })
            if link.activity_id and link.activity_id.active:
                link.activity_id.action_cancel()
            link.instance_id.message_post(body=_(
                '%(user)s 已回覆會辦/徵詢：%(reply)s',
                user=self.env.user.name, reply=self.reply or self.reason or ''))
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # ---- 送出會辦/徵詢 ----
        if not self.user_ids:
            raise UserError(_('請選擇送簽對象。'))
        instance = link.instance_id
        kind = 'lateral_consult' if self.mode == 'consult' else 'lateral_info'
        suffix = _('（會辦）') if self.mode == 'consult' else _('（徵詢）')
        Link = self.env['bpmn.activity.link']
        for user in self.user_ids:
            activity = instance._create_approval_activity(
                link.bpmn_element_id, user, summary_suffix=suffix)
            Link.create({
                'instance_id': instance.id,
                'token_id': link.token_id.id,
                'bpmn_element_id': link.bpmn_element_id,
                'activity_id': activity.id,
                'approver_user_id': user.id,
                'parent_link_id': link.id,
                'kind': kind,
                'decision': 'pending',
                'feedback': self.reason,
            })
        instance.message_post(body=_(
            '%(user)s 將「%(node)s」%(mode)s 給：%(to)s',
            user=self.env.user.name, node=link.node_name or '',
            mode=suffix, to='、'.join(self.user_ids.mapped('name'))))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
