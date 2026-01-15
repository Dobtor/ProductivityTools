# -*- coding: utf-8 -*-

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成待辦精靈

    功能說明:
    - 記錄實際執行工時
    - 添加完成回饋和附件
    - 可選擇安排下一次待辦
    - 觸發工時表記錄建立
    """
    _name = 'mail.activity.done.wizard'
    _description = '完成待辦精靈'

    # ===== 待辦資訊（唯讀）=====
    activity_id = fields.Many2one(
        'mail.activity',
        string='待辦',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    summary = fields.Char(
        string='待辦摘要',
        related='activity_id.summary',
        readonly=True,
    )
    planned_date = fields.Date(
        string='計畫日期',
        related='activity_id.planned_date',
        readonly=True,
    )
    estimated_hours = fields.Float(
        string='預估工時',
        related='activity_id.estimated_hours',
        readonly=True,
    )
    activity_type_name = fields.Char(
        string='待辦類型',
        related='activity_id.activity_type_id.name',
        readonly=True,
    )

    # ===== 完成資訊 =====
    actual_hours = fields.Float(
        string='執行工時',
        required=True,
        help='實際執行所花費的時間（小時）',
    )
    feedback = fields.Text(
        string='回饋/說明',
        help='待辦完成的回饋或說明',
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'mail_activity_done_wizard_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='附件',
    )

    # ===== 下一個待辦相關 =====
    schedule_next = fields.Boolean(
        string='安排下一次待辦',
        default=False,
    )
    next_activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='下一次待辦類型',
    )
    next_date_deadline = fields.Date(
        string='下一次到期日',
    )
    next_summary = fields.Char(
        string='下一次摘要',
    )
    next_user_id = fields.Many2one(
        'res.users',
        string='下一次負責人',
        default=lambda self: self.env.user,
    )

    @api.model
    def default_get(self, fields_list):
        """預設值處理：從 context 取得 activity_id 並預填執行工時"""
        res = super().default_get(fields_list)

        # 從 context 取得 activity_id
        if 'activity_id' not in res and self.env.context.get('default_activity_id'):
            res['activity_id'] = self.env.context.get('default_activity_id')

        # 預填執行工時為預估工時
        if res.get('activity_id'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists() and activity.estimated_hours:
                res['actual_hours'] = activity.estimated_hours

        return res

    @api.onchange('schedule_next')
    def _onchange_schedule_next(self):
        """當選擇安排下一次時，預填類型和摘要"""
        if self.schedule_next and self.activity_id:
            if not self.next_activity_type_id:
                self.next_activity_type_id = self.activity_id.activity_type_id
            if not self.next_summary:
                self.next_summary = self.activity_id.summary

    def _validate_actual_hours(self):
        """驗證執行工時"""
        self.ensure_one()
        if self.actual_hours < 0:
            raise UserError(_('執行工時不能為負數。'))

    def _prepare_done_values(self):
        """準備完成待辦的更新值"""
        self.ensure_one()
        return {
            'actual_hours': self.actual_hours,
        }

    def _get_attachment_ids(self):
        """取得附件 ID 列表"""
        return self.attachment_ids.ids if self.attachment_ids else None

    def action_done(self):
        """完成待辦"""
        self.ensure_one()
        self._validate_actual_hours()

        activity = self.activity_id

        # 更新待辦的執行工時
        activity.write(self._prepare_done_values())

        # 執行完成動作
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_done_and_schedule_next(self):
        """完成並安排下一次待辦"""
        self.ensure_one()
        self._validate_actual_hours()

        # 驗證下一次待辦資訊
        if not self.next_activity_type_id:
            raise UserError(_('請選擇下一次待辦類型。'))
        if not self.next_date_deadline:
            raise UserError(_('請選擇下一次到期日。'))

        activity = self.activity_id

        # 更新待辦的執行工時
        activity.write(self._prepare_done_values())

        # 執行完成動作
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 建立下一個待辦
        next_activity_vals = {
            'activity_type_id': self.next_activity_type_id.id,
            'date_deadline': self.next_date_deadline,
            'summary': self.next_summary or activity.summary,
            'user_id': self.next_user_id.id if self.next_user_id else False,
            'res_model_id': activity.res_model_id.id,
            'res_id': activity.res_id,
        }

        # 保留筆記關聯
        if activity.note_id:
            next_activity_vals['note_id'] = activity.note_id.id

        self.env['mail.activity'].create(next_activity_vals)

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_postpone(self):
        """延至下週（開啟延期 wizard）"""
        self.ensure_one()
        return self.activity_id.action_postpone_wizard()
