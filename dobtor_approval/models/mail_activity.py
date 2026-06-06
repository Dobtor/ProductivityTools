# -*- coding: utf-8 -*-
"""mail.activity 簽核橋接 — DESIGN_APPROVAL_EVENT.md。

以 Odoo **原生** mail.activity 為事件基礎（不依賴 dobtor_mail_activity）。
原生 _action_done(feedback, attachment_ids) 回傳 (messages, next_activities)；
此處 override：先 super()，再以 hook 推進 BPMN token。簽核/駁回/加簽等動作於
「簽核事件」inbox 進行。
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    # 是否為簽核活動（用於前端按鈕顯隱）
    is_bpmn_approval = fields.Boolean(
        string='是否簽核活動', compute='_compute_is_bpmn_approval')
    bpmn_link_id = fields.Many2one('bpmn.activity.link',
                                   string='BPMN 簽核連結',
                                   compute='_compute_bpmn_link', store=False)
    bpmn_allow_escalation = fields.Boolean(
        string='允許上呈加簽', compute='_compute_bpmn_link')

    @api.depends('activity_type_id')
    def _compute_is_bpmn_approval(self):
        approval_type = self.env.ref(
            'dobtor_approval.activity_type_approval', raise_if_not_found=False)
        for act in self:
            act.is_bpmn_approval = bool(
                approval_type and act.activity_type_id == approval_type)

    @api.depends('activity_type_id')
    def _compute_bpmn_link(self):
        Link = self.env['bpmn.activity.link']
        links = Link.search([('activity_id', 'in', self.ids),
                             ('decision', '=', 'pending')])
        link_by_act = {l.activity_id.id: l for l in links}
        for act in self:
            link = link_by_act.get(act.id)
            act.bpmn_link_id = link.id if link else False
            if link:
                cfg = link.instance_id.process_id._config_for(link.bpmn_element_id)
                act.bpmn_allow_escalation = bool(
                    cfg and cfg.allow_escalation
                    and act.env.company._bpmn_feature_enabled('escalation'))
            else:
                act.bpmn_allow_escalation = False

    # ------------------------------------------------------------------
    # 完成 hook：super() 後推進 token
    # ------------------------------------------------------------------
    def _action_done(self, feedback=False, attachment_ids=None):
        res = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
        # 找出對應的待簽 link 並推進
        links = self.env['bpmn.activity.link'].search([
            ('activity_id', 'in', self.ids),
            ('decision', '=', 'pending'),
        ])
        if links:
            links._on_activity_done(feedback)
        return res

    # ------------------------------------------------------------------
    # 駁回
    # ------------------------------------------------------------------
    def action_bpmn_reject(self):
        """簽核活動的駁回按鈕。"""
        self.ensure_one()
        link = self.env['bpmn.activity.link'].search([
            ('activity_id', '=', self.id),
            ('decision', '=', 'pending'),
        ], limit=1)
        if not link:
            raise UserError(_('此活動不是待簽核的 BPMN 活動。'))
        link.action_bpmn_reject(feedback=self.feedback)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ------------------------------------------------------------------
    # 上呈加簽
    # ------------------------------------------------------------------
    def action_bpmn_escalate(self):
        """開啟上呈加簽 wizard。"""
        self.ensure_one()
        if not self.env.company._bpmn_feature_enabled('escalation'):
            raise UserError(_('「主管自主加簽」能力尚未啟用。'))
        link = self.env['bpmn.activity.link'].search([
            ('activity_id', '=', self.id),
            ('decision', '=', 'pending'),
        ], limit=1)
        if not link:
            raise UserError(_('此活動不是待簽核的 BPMN 活動。'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('上呈加簽'),
            'res_model': 'bpmn.escalate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_link_id': link.id},
        }
