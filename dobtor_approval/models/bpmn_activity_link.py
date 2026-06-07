# -*- coding: utf-8 -*-
"""BPMN ↔ mail.activity 橋接 — DESIGN.md §3.6 / §6。

每個簽核人對應一張 mail.activity 與一筆 link。活動完成（_action_done hook）
→ link._on_activity_done() → 依 approval_mode 決定是否推進 token。
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

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
    phase = fields.Integer(default=0,
                           help='核決權限表分階：同 phase＝會簽，跨 phase＝依序（0＝非分階）')

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

    # 例外路由（DESIGN_APPROVAL_EVENT.md §6/§7）
    kind = fields.Selection([
        ('normal', '一般簽核'),
        ('escalate', '向上加簽'),
        ('lateral_consult', '會辦(等待)'),
        ('lateral_info', '徵詢(不等待)'),
        ('delegate', '委派代簽'),
    ], string='事件類型', default='normal', index=True)
    reject_to_element = fields.Char(string='駁回去向節點')
    consult_reply = fields.Text(string='會辦/徵詢回覆')

    # ---- 簽核事件 inbox 顯示用（related / computed）----
    process_id = fields.Many2one(related='instance_id.process_id', store=True,
                                 string='簽核流程')
    applicant_user_id = fields.Many2one(related='instance_id.applicant_user_id',
                                        store=True, string='申請人')
    res_name = fields.Char(related='instance_id.res_name', string='單據')
    summary = fields.Char(related='activity_id.summary', string='事件摘要')
    date_deadline = fields.Date(related='activity_id.date_deadline', string='期限')
    node_name = fields.Char(string='關卡', compute='_compute_node_name')
    has_open_consult = fields.Boolean(string='會辦中', store=True,
                                      compute='_compute_has_open_consult')

    @api.depends('bpmn_element_id', 'instance_id')
    def _compute_node_name(self):
        for link in self:
            cfg = link.instance_id.process_id._config_for(link.bpmn_element_id) \
                if link.instance_id and link.bpmn_element_id else False
            link.node_name = (cfg.name if cfg else link.bpmn_element_id) or ''

    @api.depends('child_link_ids.kind', 'child_link_ids.decision')
    def _compute_has_open_consult(self):
        for link in self:
            link.has_open_consult = any(
                c.kind == 'lateral_consult' and c.decision == 'pending'
                for c in link.child_link_ids)

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

    # ==================================================================
    # 簽核事件 inbox 動作（DESIGN_APPROVAL_EVENT.md §5/§6）
    # ==================================================================
    def _ensure_can_act(self):
        """僅待簽事件可操作。"""
        for link in self:
            if link.decision != 'pending':
                raise UserError(_('此事件已處理（%s），無法再操作。',
                                  dict(self._fields['decision'].selection).get(
                                      link.decision, link.decision)))

    def action_event_approve(self):
        """核准（單筆或批次）。會辦未回覆者擋下。"""
        self._ensure_can_act()
        for link in self:
            if link.has_open_consult:
                raise UserError(_('事件「%s」仍有會辦未回覆，需待回覆後才能核准。',
                                  link.node_name or link.summary or ''))
            link.action_bpmn_approve(feedback=link.feedback)
        return True

    def action_batch_approve(self):
        """list 多選批次核准（server action 綁定）。"""
        todo = self.filtered(lambda l: l.decision == 'pending'
                             and not l.has_open_consult)
        todo.action_event_approve()
        return True

    def action_batch_reject(self):
        todo = self.filtered(lambda l: l.decision == 'pending')
        for link in todo:
            link.action_bpmn_reject(feedback=link.feedback)
        return True

    def action_event_reject(self):
        self.ensure_one()
        self._ensure_can_act()
        return self._open_wizard('bpmn.reject.wizard', _('駁回'))

    def action_event_escalate(self):
        self.ensure_one()
        self._ensure_can_act()
        if not self.env.company._bpmn_feature_enabled('escalation'):
            raise UserError(_('「向上加簽」能力尚未啟用（T3）。'))
        return self._open_wizard('bpmn.escalate.wizard', _('向上加簽'))

    def action_event_lateral(self):
        self.ensure_one()
        self._ensure_can_act()
        return self._open_wizard('bpmn.lateral.wizard', _('橫向送簽'))

    def action_event_delegate(self):
        self.ensure_one()
        self._ensure_can_act()
        return self._open_wizard('bpmn.delegate.wizard', _('委派代簽'))

    def _open_wizard(self, model, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_link_id': self.id},
        }

    def action_event_retrieve(self):
        """收回/抽單：申請人或前一關簽核人，於下一關尚未動作前可收回。"""
        self.ensure_one()
        if self.decision != 'pending':
            raise UserError(_('僅待簽事件可收回。'))
        user = self.env.user
        is_applicant = self.instance_id.applicant_user_id == user
        if not (is_applicant or user == self.approver_user_id
                or user.has_group('dobtor_approval.group_bpmn_approval_manager')):
            raise UserError(_('只有申請人、該關簽核人或管理者可收回此事件。'))
        if self.activity_id and self.activity_id.active:
            self.activity_id.action_cancel()
        self.write({'decision': 'rejected', 'feedback': _('（已由 %s 收回）', user.name)})
        self.instance_id.message_post(body=_('事件「%s」已被收回。',
                                             self.node_name or ''))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ---- 會辦/徵詢回覆（被會辦人於其事件回覆）----
    def action_event_consult_reply(self):
        self.ensure_one()
        return self._open_wizard('bpmn.lateral.wizard', _('回覆會辦/徵詢'))

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
