# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成待辦精靈

    功能說明:
    - 記錄實際執行工時（支援多次登錄）
    - 添加完成回饋和附件
    - 可選擇安排下一次待辦
    - 「登錄後繼續」不完成待辦，只登錄工時
    - 觸發工時表記錄建立
    """
    _name = 'mail.activity.done.wizard'
    _description = 'Complete Activity Wizard'

    # ===== 待辦資訊（唯讀）=====
    activity_id = fields.Many2one(
        'mail.activity',
        string='Activity',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    summary = fields.Char(
        string='Activity Summary',
        related='activity_id.summary',
        readonly=True,
    )
    planned_date = fields.Date(
        string='Planned Date',
        related='activity_id.planned_date',
        readonly=True,
    )
    estimated_hours = fields.Float(
        string='Estimated Hours',
        related='activity_id.estimated_hours',
        readonly=True,
    )
    activity_type_name = fields.Char(
        string='Activity Type',
        related='activity_id.activity_type_id.name',
        readonly=True,
    )

    # ===== 工時資訊 =====
    accumulated_hours = fields.Float(
        string='Accumulated Hours',
        compute='_compute_accumulated_hours',
        readonly=True,
    )
    actual_hours = fields.Float(
        string='Hours to Log',
        required=True,
        help='Time spent on this activity (hours)',
    )

    # ===== 完成資訊 =====
    feedback = fields.Text(
        string='Feedback/Notes',
        help='Feedback or notes upon activity completion',
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'mail_activity_done_wizard_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments',
    )

    # ===== 下一個待辦相關 =====
    schedule_next = fields.Boolean(
        string='Schedule Next Activity',
        default=False,
    )
    next_activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Next Activity Type',
    )
    next_date_deadline = fields.Date(
        string='Next Deadline',
    )
    next_summary = fields.Char(
        string='Next Summary',
    )
    next_user_id = fields.Many2one(
        'res.users',
        string='Next Assignee',
        default=lambda self: self.env.user,
    )

    # ===== 計算方法 =====

    @api.depends('activity_id', 'activity_id.actual_hours')
    def _compute_accumulated_hours(self):
        """計算已累計工時（來自 timesheet_ids）"""
        for wizard in self:
            wizard.accumulated_hours = wizard.activity_id.actual_hours or 0.0

    @api.model
    def default_get(self, fields_list):
        """預設值處理：從 context 取得 activity_id 並預填執行工時"""
        res = super().default_get(fields_list)

        # 從 context 取得 activity_id
        if 'activity_id' not in res and self.env.context.get('default_activity_id'):
            res['activity_id'] = self.env.context.get('default_activity_id')

        # 預填執行工時：預估工時減去已累計工時
        if res.get('activity_id'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists() and activity.estimated_hours:
                remaining = activity.estimated_hours - activity.actual_hours
                res['actual_hours'] = max(remaining, 0)

        return res

    @api.onchange('schedule_next')
    def _onchange_schedule_next(self):
        """當選擇安排下一次時，預填類型和摘要"""
        if self.schedule_next and self.activity_id:
            if not self.next_activity_type_id:
                self.next_activity_type_id = self.activity_id.activity_type_id
            if not self.next_summary:
                self.next_summary = self.activity_id.summary

    # ===== 驗證方法 =====

    def _validate_actual_hours(self):
        """驗證執行工時"""
        self.ensure_one()
        if self.actual_hours < 0:
            raise UserError(_('Hours cannot be negative.'))

    # ===== 工時表建立方法 =====

    def _get_timesheet_project(self):
        """取得工時表專案（優先級邏輯）"""
        activity = self.activity_id

        # 優先級 1: 關聯 task 的專案
        if activity.res_model == 'project.task':
            task = self.env['project.task'].browse(activity.res_id)
            if task.exists() and task.project_id:
                return task.project_id

        # 優先級 2: 關聯 lead 的專案
        if activity.res_model == 'crm.lead':
            lead = self.env['crm.lead'].browse(activity.res_id)
            if hasattr(lead, 'project_id') and lead.project_id:
                return lead.project_id

        # 優先級 3: 公司預設專案
        return self.env.company.default_timesheet_project_id

    def _get_timesheet_task(self):
        """取得工時表任務"""
        activity = self.activity_id
        if activity.res_model == 'project.task':
            return activity.res_id
        return False

    def _create_timesheet_entry(self):
        """建立工時表記錄"""
        activity = self.activity_id
        employee = self.env.user.employee_id

        if not employee:
            raise UserError(_('You do not have an employee record and cannot log time.'))

        if not employee.active:
            raise UserError(_('Your employee record is inactive and cannot log time.'))

        # 決定專案
        project = self._get_timesheet_project()
        if not project:
            raise UserError(_(
                'Cannot find a project to log time.\n'
                'Please ensure the activity is linked to a project task/lead, or the company has a default timesheet project configured.'
            ))

        if not project.allow_timesheets:
            raise UserError(_('Project "%s" does not have timesheets enabled.') % project.name)

        # Odoo 18: analytic_account_id 已改為 account_id
        analytic_account = project.account_id
        if not analytic_account or not analytic_account.active:
            raise UserError(_('Project "%s" is missing a valid analytic account. Please configure it in project settings.') % project.name)

        # 建立工時記錄
        timesheet_vals = {
            'date': activity.planned_date or fields.Date.today(),
            'name': self.feedback or activity.summary or _('Activity Execution'),
            'unit_amount': self.actual_hours,
            'employee_id': employee.id,
            'user_id': self.env.user.id,
            'project_id': project.id,
            'task_id': self._get_timesheet_task(),
            'account_id': analytic_account.id,
            'activity_id': activity.id,  # 關聯待辦
            'company_id': analytic_account.company_id.id or project.company_id.id,
        }

        return self.env['account.analytic.line'].sudo().create(timesheet_vals)

    def _get_attachment_ids(self):
        """取得附件 ID 列表"""
        return self.attachment_ids.ids if self.attachment_ids else None

    # ===== Action 方法 =====

    def action_log_and_continue(self):
        """登錄工時後繼續（不完成待辦）"""
        self.ensure_one()

        if self.actual_hours <= 0:
            raise UserError(_('Please enter valid hours (must be greater than 0)'))

        # 建立工時表記錄
        self._create_timesheet_entry()

        # 關閉精靈並刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'soft_reload',
        }

    def action_done(self):
        """完成待辦"""
        self.ensure_one()
        self._validate_actual_hours()

        activity = self.activity_id

        # 先登錄本次工時（如果有填寫且大於 0）
        if self.actual_hours > 0:
            self._create_timesheet_entry()

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
            raise UserError(_('Please select next activity type.'))
        if not self.next_date_deadline:
            raise UserError(_('Please select next deadline.'))

        activity = self.activity_id

        # 先登錄本次工時（如果有填寫且大於 0）
        if self.actual_hours > 0:
            self._create_timesheet_entry()

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
