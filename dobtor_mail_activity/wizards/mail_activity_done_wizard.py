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
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Complete Activity Wizard'

    # 待辦資訊（activity_id / summary / activity_type_name / date_deadline /
    # planned_date / estimated_hours / urgency / importance / assignee_id /
    # res_display / note_id）由 mail.activity.action.wizard.mixin 提供。

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

    # ===== 刪除權限 =====
    can_delete = fields.Boolean(
        string='Can Delete',
        compute='_compute_can_delete',
        help='Only the activity creator or a system administrator may delete it.',
    )

    # ===== 計算方法 =====

    @api.depends('activity_id', 'activity_id.actual_hours')
    def _compute_accumulated_hours(self):
        """計算已累計工時（activity.actual_hours）"""
        for wizard in self:
            wizard.accumulated_hours = wizard.activity_id.actual_hours or 0.0

    @api.depends('activity_id')
    def _compute_can_delete(self):
        """建立者或最高管理者（base.group_system）才可刪除該待辦。"""
        is_admin = self.env.user.has_group('base.group_system')
        for wizard in self:
            activity = wizard.activity_id
            wizard.can_delete = bool(activity) and (
                is_admin or activity.create_uid.id == self.env.uid
            )

    @api.model
    def default_get(self, fields_list):
        """預設值處理：取得 activity_id（mixin）後預填執行工時"""
        res = super().default_get(fields_list)

        # 預填執行工時：預估工時減去已累計工時
        if res.get('activity_id'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists() and activity.estimated_hours:
                remaining = activity.estimated_hours - activity.actual_hours
                res['actual_hours'] = max(remaining, 0)

        return res

    # ===== 驗證方法 =====

    def _validate_actual_hours(self):
        """驗證執行工時"""
        self.ensure_one()
        if self.actual_hours < 0:
            raise UserError(_('Hours cannot be negative.'))

    # ===== 工時記錄方法 =====

    def _log_hours(self):
        """記錄本次執行工時（核心 hook）。

        本模組硬相依 hr_timesheet：登錄工時 = 建立 account.analytic.line
        工時表記錄，actual_hours 由工時表加總自動更新（見 mail.activity
        _compute_actual_hours）。

        受「啟用工時記錄」開關（res.company.dobtor_activity_timesheet_enabled）
        控制：關閉時不建立工時表記錄（等同不追蹤工時）。
        """
        self.ensure_one()
        if self.actual_hours <= 0:
            return
        if not self.env.company.dobtor_activity_timesheet_enabled:
            # 工時記錄功能關閉 → 不建立工時表記錄
            return
        self._create_timesheet_entry()

    # ===== 工時表建立方法（原 dobtor_mail_activity_timesheet 併入）=====

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

        # 優先級 3: 待辦本身的 project_id（需求二/三帶入）
        if activity.project_id:
            return activity.project_id

        # 優先級 4: 公司預設專案
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
            'date': activity.planned_date or fields.Date.context_today(self),
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

        # 記錄本次工時
        self._log_hours()

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

        # 先記錄本次工時（如果有填寫且大於 0）
        if self.actual_hours > 0:
            self._log_hours()

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
        """完成當前待辦，並鏈式開啟「建立待辦」精靈安排下一個。

        依需求：先把當前待辦設為完成（記錄工時），再開啟
        mail.activity.create.wizard，帶入上一筆待辦的標題（summary）、
        類型與關聯（res 文件 / 客戶 / 專案 / 來源參考）作為新待辦預設值，
        使用者於新精靈編輯後儲存。
        """
        self.ensure_one()
        self._validate_actual_hours()

        activity = self.activity_id

        # 記錄本次工時（如有）並完成當前待辦
        if self.actual_hours > 0:
            self._log_hours()
        activity._action_done(
            feedback=self.feedback,
            attachment_ids=self._get_attachment_ids(),
        )

        # 帶入本待辦的標題/類型/關聯，鏈式開啟建立待辦精靈
        # （完成後欄位仍在，與已完成待辦的「延續新增待辦」共用同一路徑）
        return activity._continue_todo_action()

    def action_postpone(self):
        """延至下週（開啟延期 wizard）"""
        self.ensure_one()
        return self.activity_id.action_postpone_wizard()

    def action_delete_activity(self):
        """刪除該待辦（建立者或最高管理者限定）。

        回傳 act_window_close 並帶回 deleted_activity_id，供編輯器同步移除
        對應的內嵌膠囊；其他開啟情境（清單/看板）則由父視圖自動刷新。
        """
        self.ensure_one()
        activity = self.activity_id
        if not activity:
            return {'type': 'ir.actions.act_window_close'}
        if not (self.env.user.has_group('base.group_system')
                or activity.create_uid.id == self.env.uid):
            raise UserError(_('Only the activity creator or an administrator can delete this to-do.'))
        activity_id = activity.id
        # 權限已於上方依「建立者/最高管理者」把關；用 sudo 執行 unlink，
        # 避免建立者非指派人時被預設記錄規則擋下。
        activity.sudo().unlink()
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'deleted_activity_id': activity_id},
        }
