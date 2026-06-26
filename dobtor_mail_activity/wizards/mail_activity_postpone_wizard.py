# -*- coding: utf-8 -*-

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class MailActivityPostponeWizard(models.TransientModel):
    """延期待辦精靈

    功能說明:
    - 將待辦從週計畫中移至等待排程
    - 記錄延期歷史（原計畫日期、原因）
    - 標記待辦來源為「延期」
    - 支援單筆與批次（多選）延期，共用同一張表單與原因
    """
    _name = 'mail.activity.postpone.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Postpone Activity Wizard'

    # 單筆顯示用待辦資訊（含 planned_date / date_deadline）由
    # mail.activity.action.wizard.mixin 提供（activity_id = 批次中的第一筆）。

    # ===== 批次 =====
    activity_ids = fields.Many2many(
        'mail.activity',
        string='Activities',
        help='All activities to postpone (single or batch).',
    )
    activity_count = fields.Integer(
        string='Activity Count',
        compute='_compute_activity_count',
    )
    is_batch = fields.Boolean(
        string='Batch Mode',
        compute='_compute_activity_count',
    )

    # ===== 延期資訊 =====
    postpone_count = fields.Integer(
        string='Postpone Count',
        related='activity_id.postpone_count',
        readonly=True,
    )
    reason = fields.Text(
        string='Postponement Reason',
        required=True,
        help='Please explain the reason for postponement',
    )

    @api.depends('activity_ids')
    def _compute_activity_count(self):
        for wizard in self:
            wizard.activity_count = len(wizard.activity_ids)
            wizard.is_batch = len(wizard.activity_ids) > 1

    @api.model
    def default_get(self, fields_list):
        """預設值處理：彙整單筆/批次待辦。

        - 單筆入口（表單 cog、完成 wizard）傳 default_activity_id → mixin 設好。
        - 批次入口（清單多選）傳 default_activity_ids 或 active_ids。
        統一收斂到 activity_ids，並以第一筆作為 activity_id（mixin 必填＋單筆顯示）。
        """
        res = super().default_get(fields_list)

        ids = list(self.env.context.get('default_activity_ids') or [])
        if not ids and self.env.context.get('active_model') == 'mail.activity':
            ids = list(self.env.context.get('active_ids') or [])
        if not ids and res.get('activity_id'):
            ids = [res['activity_id']]

        if ids:
            res['activity_ids'] = [Command.set(ids)]
            if not res.get('activity_id'):
                res['activity_id'] = ids[0]

        return res

    # ===== 內部工具 =====

    @api.model
    def _week_string(self, planned_date):
        """原始週次字串（格式：2026-W02）"""
        if not planned_date:
            return False
        iso = planned_date.isocalendar()
        return f'{iso[0]}-W{iso[1]:02d}'

    def _postpone_one(self, activity):
        """對單一待辦執行延期：建立歷史並更新狀態。"""
        self.env['mail.activity.postpone.history'].create({
            'activity_id': activity.id,
            'original_planned_date': activity.planned_date,
            'original_week': self._week_string(activity.planned_date),
            'reason': self.reason,
        })
        activity.with_context(skip_schedule_check=True).write({
            'schedule_status': 'waiting',
            'planned_date': False,
            'schedule_origin': 'postponed',  # 標記為延期來源
        })

    def _validate_postpone(self, activity):
        """單筆嚴格驗證（提供明確錯誤訊息）。"""
        if not activity.exists():
            raise UserError(_('Activity record does not exist.'))
        if not activity.active:
            raise UserError(_('This activity is archived and cannot be postponed.'))
        if not activity.planned_date:
            raise UserError(_('This activity is not scheduled yet, no need to postpone.'))

    def action_postpone(self):
        """延至下週（單筆或批次）。"""
        self.ensure_one()
        activities = self.activity_ids if self.activity_ids else self.activity_id

        if len(activities) <= 1:
            # 單筆：沿用嚴格驗證，給出明確錯誤訊息
            self._validate_postpone(activities)
            self._postpone_one(activities)
        else:
            # 批次：略過不可延期者（已完成/取消/未排程），全部不符才報錯
            postponed = self.env['mail.activity']
            for activity in activities:
                if activity.exists() and activity.active and activity.planned_date:
                    self._postpone_one(activity)
                    postponed |= activity
            if not postponed:
                raise UserError(_(
                    'None of the selected activities can be postponed '
                    '(already done, cancelled, or not scheduled).'
                ))

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
