# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityPostponeWizard(models.TransientModel):
    """延期待辦精靈

    功能說明:
    - 將待辦從週計畫中移至等待排程
    - 記錄延期歷史（原計畫日期、原因）
    - 標記待辦來源為「延期」
    """
    _name = 'mail.activity.postpone.wizard'
    _description = '延期待辦精靈'

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
        string='原計畫日期',
        related='activity_id.planned_date',
        readonly=True,
    )
    date_deadline = fields.Date(
        string='截止日期',
        related='activity_id.date_deadline',
        readonly=True,
    )
    postpone_count = fields.Integer(
        string='已延期次數',
        related='activity_id.postpone_count',
        readonly=True,
    )

    # ===== 延期資訊 =====
    reason = fields.Text(
        string='延期原因',
        required=True,
        help='請說明延期的原因',
    )

    @api.model
    def default_get(self, fields_list):
        """預設值處理：從 context 取得 activity_id"""
        res = super().default_get(fields_list)

        # 從 context 取得 activity_id
        if 'activity_id' not in res and self.env.context.get('default_activity_id'):
            res['activity_id'] = self.env.context.get('default_activity_id')

        return res

    def _validate_postpone(self):
        """驗證是否可以延期"""
        self.ensure_one()

        activity = self.activity_id

        # 檢查待辦是否存在
        if not activity.exists():
            raise UserError(_('待辦記錄不存在。'))

        # 檢查待辦是否已完成或取消
        if not activity.active:
            raise UserError(_('此待辦已封存，無法延期。'))

        # 檢查是否有計畫日期
        if not activity.planned_date:
            raise UserError(_('此待辦尚未排程，無需延期。'))

    def _get_original_week(self):
        """取得原始週次字串（格式：2026-W02）"""
        self.ensure_one()
        if self.planned_date:
            iso_year, iso_week, _ = self.planned_date.isocalendar()
            return f'{iso_year}-W{iso_week:02d}'
        return False

    def _create_postpone_history(self):
        """建立延期歷史記錄"""
        self.ensure_one()
        return self.env['mail.activity.postpone.history'].create({
            'activity_id': self.activity_id.id,
            'original_planned_date': self.activity_id.planned_date,
            'original_week': self._get_original_week(),
            'reason': self.reason,
        })

    def _prepare_postpone_values(self):
        """準備延期更新值"""
        self.ensure_one()
        return {
            'schedule_status': 'waiting',
            'planned_date': False,
            'schedule_origin': 'postponed',  # 標記為延期來源
        }

    def action_postpone(self):
        """延至下週"""
        self.ensure_one()
        self._validate_postpone()

        # 建立延期歷史記錄
        self._create_postpone_history()

        # 更新待辦狀態（使用 context 標記跳過權限檢查）
        self.activity_id.with_context(skip_schedule_check=True).write(
            self._prepare_postpone_values()
        )

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
