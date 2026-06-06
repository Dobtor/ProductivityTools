# -*- coding: utf-8 -*-
"""上呈加簽 wizard — DESIGN.md §7.1。

在不改流程定義的前提下，於 token 上插入臨時 user_task：
- return_after=True：上級簽完後退回原簽核人續簽（token 暫停、嵌入子簽核）。
- return_after=False：直接上呈，原活動關閉，由上級接手該節點。
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 加簽鏈最大深度（防無限上呈）
_MAX_ESCALATION_DEPTH = 5


class BpmnEscalateWizard(models.TransientModel):
    _name = 'bpmn.escalate.wizard'
    _description = '上呈加簽精靈'

    link_id = fields.Many2one('bpmn.activity.link', string='來源簽核',
                              required=True)
    target_type = fields.Selection([
        ('direct_manager', '送我的直屬主管'),
        ('specific_user', '指定人員'),
        ('role', '指定角色'),
    ], string='加簽對象', default='direct_manager', required=True)
    target_user_id = fields.Many2one('res.users', string='指定人員')
    target_role_id = fields.Many2one('bpmn.role', string='指定角色')
    return_after = fields.Boolean(string='加簽後退回我續簽', default=True)
    reason = fields.Text(string='加簽理由', required=True)

    def _resolve_target(self):
        self.ensure_one()
        if self.target_type == 'direct_manager':
            emp = self.env.user.employee_id
            user = emp.parent_id.user_id
            if not user:
                raise UserError(_('找不到您的直屬主管對應的使用者。'))
            return user[:1]
        elif self.target_type == 'specific_user':
            if not self.target_user_id:
                raise UserError(_('請指定加簽人員。'))
            return self.target_user_id
        elif self.target_type == 'role':
            if not self.target_role_id:
                raise UserError(_('請指定加簽角色。'))
            users = self.target_role_id.resolve(self.link_id.instance_id)
            if not users:
                raise UserError(_('指定角色解析不到簽核人。'))
            return users[:1]
        return self.env['res.users']

    def _check_depth(self):
        depth = 0
        link = self.link_id
        while link.parent_link_id:
            depth += 1
            link = link.parent_link_id
            if depth > _MAX_ESCALATION_DEPTH:
                raise UserError(_(
                    '加簽鏈已達上限 %s 層，不可再上呈。', _MAX_ESCALATION_DEPTH))

    def action_escalate(self):
        self.ensure_one()
        self._check_depth()
        source = self.link_id
        instance = source.instance_id
        target_user = self._resolve_target()

        # 關閉原簽核活動（暫停）
        if source.activity_id and source.activity_id.active:
            source.activity_id.action_cancel()

        # 建立加簽子活動
        new_activity = instance._create_approval_activity(
            source.bpmn_element_id, target_user,
            summary_suffix=_('（加簽）'))
        child_link = self.env['bpmn.activity.link'].create({
            'instance_id': instance.id,
            'token_id': source.token_id.id,
            'bpmn_element_id': source.bpmn_element_id,
            'activity_id': new_activity.id,
            'approver_user_id': target_user.id,
            'decision': 'pending',
            'parent_link_id': source.id,
            'return_after_escalate': self.return_after,
        })

        # 標記原 link 為已上呈
        source.write({
            'decision': 'escalated',
            'feedback': self.reason,
        })

        instance.message_post(body=_(
            '%(user)s 將節點「%(node)s」上呈加簽給 %(target)s。理由：%(reason)s',
            user=self.env.user.name,
            node=source.bpmn_element_id,
            target=target_user.name,
            reason=self.reason))

        return {'type': 'ir.actions.client', 'tag': 'reload'}
