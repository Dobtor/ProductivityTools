# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class MailActivityDoneWizard(models.TransientModel):
    """完成待辦精靈 - 工時表整合（橋接）。

    覆寫核心的 ``_log_hours`` hook：核心模式直接累加 activity.actual_hours，
    本橋接改為建立 account.analytic.line 工時表記錄（actual_hours 由工時表加總）。
    """
    _inherit = 'mail.activity.done.wizard'

    def _log_hours(self):
        """覆寫核心 hook：改為建立工時表記錄。"""
        self.ensure_one()
        if self.actual_hours <= 0:
            return
        self._create_timesheet_entry()

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
            raise UserError(_('Project "%(project)s" does not have timesheets enabled.', project=project.name))

        # Odoo 18: analytic_account_id 已改為 account_id
        analytic_account = project.account_id
        if not analytic_account or not analytic_account.active:
            raise UserError(_('Project "%(project)s" is missing a valid analytic account. Please configure it in project settings.', project=project.name))

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
