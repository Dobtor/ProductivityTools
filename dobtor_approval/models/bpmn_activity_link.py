# -*- coding: utf-8 -*-
"""BPMN ↔ mail.activity 橋接 — DESIGN.md §3.6 / §6。

每個簽核人對應一張 mail.activity 與一筆 link。活動完成（_action_done hook）
→ link._on_activity_done() → 依 approval_mode 決定是否推進 token。
"""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class BpmnActivityLink(models.Model):
    _name = 'bpmn.activity.link'
    _description = 'BPMN 簽核活動連結'
    _order = 'id'

    instance_id = fields.Many2one('bpmn.process.instance', string='流程實例',
                                  ondelete='cascade', required=True, index=True)
    token_id = fields.Many2one('bpmn.token', string='Token', ondelete='cascade')
    bpmn_element_id = fields.Char(string='節點 (element id)')
    activity_id = fields.Many2one('mail.activity', string='簽核活動',
                                  ondelete='set null', index=True)
    approver_user_id = fields.Many2one('res.users', string='指派簽核人')
    sequence = fields.Integer(default=10, help='sequential 模式的簽核順序')

    decision = fields.Selection([
        ('pending', '待簽'),
        ('approved', '核准'),
        ('rejected', '駁回'),
        ('escalated', '上呈加簽'),
        ('delegated', '已代簽'),
    ], string='簽核結果', default='pending', index=True)
    decided_by = fields.Many2one('res.users', string='實際簽核人')
    feedback = fields.Text(string='簽核意見')

    # 加簽鏈（DESIGN.md §7.1）
    parent_link_id = fields.Many2one('bpmn.activity.link', string='上層加簽來源',
                                     ondelete='cascade')
    child_link_ids = fields.One2many('bpmn.activity.link', 'parent_link_id',
                                     string='加簽子節點')
    return_after_escalate = fields.Boolean(string='加簽後退回續簽', default=False)

    # ------------------------------------------------------------------
    # 完成 hook（由 mail.activity._action_done 觸發）
    # ------------------------------------------------------------------
    def _on_activity_done(self, feedback=False):
        """活動完成 → 記核准 → 推進 token。

        若 link 為「加簽 return_after」鏈，需先回到原簽核人續簽。
        """
        for link in self:
            if link.decision not in ('pending',):
                continue
            link.write({
                'decision': 'approved',
                'decided_by': self.env.user.id,
                'feedback': feedback or link.feedback,
            })
            link._post_decision_advance()

    def _post_decision_advance(self):
        """單筆 link 完成核准後的推進邏輯。"""
        self.ensure_one()
        # 加簽 return_after：上級簽完 → 重新產生原簽核人的活動
        if self.parent_link_id and self.return_after_escalate:
            self.parent_link_id._resume_after_escalation()
            return
        # 一般：交給實例依 approval_mode 判斷該節點是否完成
        self.instance_id._on_link_approved(self)

    def action_bpmn_approve(self, feedback=False):
        """主動核准（活動表單按鈕）。直接走活動完成 hook。"""
        for link in self:
            if link.activity_id and link.activity_id.active:
                # 走 mail.activity 既有完成流程（會回呼 _on_activity_done）
                link.activity_id.with_context(
                    mail_activity_quick_update=True)._action_done(feedback=feedback)
            else:
                link._on_activity_done(feedback=feedback)
        return True

    def action_bpmn_reject(self, feedback=False):
        """駁回：標記 + 觸發實例駁回路徑。"""
        for link in self:
            link.write({
                'decision': 'rejected',
                'decided_by': self.env.user.id,
                'feedback': feedback or link.feedback,
            })
            # 關閉活動（不走核准 hook）
            if link.activity_id and link.activity_id.active:
                link.activity_id.action_cancel()
            link.instance_id._on_link_rejected(link)
        return True

    def _resume_after_escalation(self):
        """加簽鏈：上級簽完後，重新喚起原簽核人的活動續簽。"""
        self.ensure_one()
        instance = self.instance_id
        activity = instance._create_approval_activity(
            self.bpmn_element_id, self.approver_user_id,
            summary_suffix=_('（加簽後續簽）'))
        self.write({
            'decision': 'pending',
            'activity_id': activity.id,
        })
