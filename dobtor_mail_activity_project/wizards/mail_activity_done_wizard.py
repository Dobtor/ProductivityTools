# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成精靈 × 工時表：登錄工時、「登錄後繼續」、事後補登（log_only）。

    找不到工時專案時，完成照常、跳過工時（chatter 留痕），之後掛上專案可補登。
    """
    _inherit = 'mail.activity.done.wizard'

    # ===== 工時資訊 =====
    accumulated_hours = fields.Float(
        string='Accumulated Hours',
        compute='_compute_accumulated_hours',
        readonly=True,
    )
    actual_hours = fields.Float(
        string='Hours to Log',
        required=True,
        # 待辦無預估工時時 default_get 不預填 → 給 0，避免必填欄位寫入 NULL
        default=0.0,
        help='Time spent on this activity (hours)',
    )

    # ===== 工時表專案 / 模式 =====
    log_only = fields.Boolean(
        string='Log Only',
        help='Opened from "Log Time": only log hours, do not complete the activity.',
    )
    timesheet_skipped = fields.Boolean(
        string='Timesheet Will Be Skipped',
        compute='_compute_timesheet_skipped',
        help='Timesheet logging is enabled but no project can be found for this '
             'activity: completing it will not log hours.',
    )

    @api.depends('activity_id', 'activity_id.actual_hours')
    def _compute_accumulated_hours(self):
        for wizard in self:
            wizard.accumulated_hours = wizard.activity_id.actual_hours or 0.0

    @api.depends('activity_id')
    def _compute_timesheet_skipped(self):
        enabled = self.env.company.dobtor_activity_timesheet_enabled
        for wizard in self:
            wizard.timesheet_skipped = bool(
                enabled and wizard.activity_id
                and not wizard.activity_id._get_timesheet_project())

    @api.model
    def default_get(self, fields_list):
        """預填執行工時：預估工時減去已累計工時"""
        res = super().default_get(fields_list)
        if res.get('activity_id'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists() and activity.estimated_hours:
                remaining = activity.estimated_hours - activity.actual_hours
                res['actual_hours'] = max(remaining, 0)
        return res

    # ===== 工時記錄 =====

    def _log_hours(self):
        """登錄工時 = 建立工時表記錄（受「啟用工時記錄」開關控制）。"""
        self.ensure_one()
        if self.actual_hours < 0:
            raise UserError(_('Hours cannot be negative.'))
        if self.actual_hours == 0:
            return
        if not self.env.company.dobtor_activity_timesheet_enabled:
            return
        if not self._get_timesheet_project():
            # 找不到專案 → 跳過工時（待辦照常完成）。留痕以便日後掛上專案後，
            # 於待辦「工時表」分頁「登錄工時」補登。
            self.activity_id._message_log(body=_(
                'Hours not logged: %(hours)s h (no project linked). '
                'Link a project and use "Log Time" to log them later.',
                hours=round(self.actual_hours, 2)))
            return
        self._create_timesheet_entry()

    def _get_timesheet_project(self):
        """取得工時表專案（邏輯在 mail.activity，與「登錄工時」按鈕共用）"""
        return self.activity_id._get_timesheet_project()

    def _get_timesheet_task(self):
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

        project = self._get_timesheet_project()
        if not project:
            raise UserError(_(
                'Cannot find a project to log time.\n'
                'Please ensure the activity is linked to a project task/lead, or the company has a default timesheet project configured.'
            ))
        if not project.allow_timesheets:
            raise UserError(_('Project "%(project)s" does not have timesheets enabled.', project=project.name))

        # Odoo 18: analytic_account_id 已改為 account_id
        analytic_account = project.account_id
        if not analytic_account or not analytic_account.active:
            raise UserError(_('Project "%(project)s" is missing a valid analytic account. Please configure it in project settings.', project=project.name))

        timesheet_vals = {
            'date': activity.planned_date or fields.Date.context_today(self),
            'name': self.feedback or activity.summary or _('Activity Execution'),
            'unit_amount': self.actual_hours,
            'employee_id': employee.id,
            'user_id': self.env.user.id,
            'project_id': project.id,
            'task_id': self._get_timesheet_task(),
            'account_id': analytic_account.id,
            'activity_id': activity.id,
            'company_id': analytic_account.company_id.id or project.company_id.id,
        }
        return self.env['account.analytic.line'].sudo().create(timesheet_vals)

    def action_log_and_continue(self):
        """登錄工時後繼續（不完成待辦）；亦為「登錄工時」補登模式的按鈕。"""
        self.ensure_one()
        if self.actual_hours <= 0:
            raise UserError(_('Please enter valid hours (must be greater than 0)'))
        # 明確要求登錄：功能關閉或找不到專案時不可靜默跳過
        if not self.env.company.dobtor_activity_timesheet_enabled:
            raise UserError(_('Timesheet logging is disabled for this company.'))
        # 找不到專案時 _create_timesheet_entry 會提示原因
        self._create_timesheet_entry()
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
