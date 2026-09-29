# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivity(models.Model):
    """待辦 × 專案／工時表整合。

    - project_id：待辦所屬專案（關聯圖、客戶後備、分組報告）
    - 工時：完成精靈登錄工時 = 建立工時表記錄；actual_hours 改為工時表加總
    - 找不到工時專案時，完成照常、跳過工時；之後掛上專案可「登錄工時」補登
    """
    _inherit = 'mail.activity'

    # ===== 專案關聯（需求二/三/五/六共用；設定驅動 FK）=====
    # 可空、可手填。與 res 雙向 onchange：選 project 後可用邏輯圖挑 res；
    # 直接選 res 亦反推 project。
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        index=True,
        help='Related project. Used for the relation diagram, customer '
             'fallback and grouped report.',
    )

    # ===== 工時表 =====
    timesheet_ids = fields.One2many(
        'account.analytic.line',
        'activity_id',
        string='Timesheet Entries',
    )
    # 覆寫核心的純欄位：改為工時表加總
    actual_hours = fields.Float(
        compute='_compute_actual_hours',
        store=True,
    )
    # 非儲存：供表單 Timesheet 分頁 invisible 綁定（公司層功能開關）。
    timesheet_feature_enabled = fields.Boolean(
        string='Timesheet Feature Enabled',
        compute='_compute_timesheet_feature_enabled',
    )
    # 找得到工時專案才可登錄工時（完成時找不到會跳過工時，之後掛上專案可補登）
    can_log_timesheet = fields.Boolean(
        string='Can Log Timesheet',
        compute='_compute_can_log_timesheet',
    )

    @api.depends('timesheet_ids', 'timesheet_ids.unit_amount')
    def _compute_actual_hours(self):
        """執行工時 = 所有登錄工時的總合。"""
        for activity in self:
            activity.actual_hours = sum(activity.timesheet_ids.mapped('unit_amount'))

    def _compute_timesheet_feature_enabled(self):
        enabled = self.env.company.dobtor_activity_timesheet_enabled
        for activity in self:
            activity.timesheet_feature_enabled = enabled

    def _compute_can_log_timesheet(self):
        enabled = self.env.company.dobtor_activity_timesheet_enabled
        for activity in self:
            activity.can_log_timesheet = bool(
                enabled and activity._get_timesheet_project())

    def _get_timesheet_project(self):
        """工時表專案（優先級）：關聯任務的專案 > 待辦本身的專案 >
        公司預設工時專案（dobtor_mail_activity_crm 另插入「關聯商機的專案」）。
        找不到回傳空 recordset。"""
        self.ensure_one()
        if self.res_model == 'project.task' and self.res_id:
            task = self.env['project.task'].browse(self.res_id).exists()
            if task.project_id:
                return task.project_id
        if self.project_id:
            return self.project_id
        return self.env.company.default_timesheet_project_id or self.env['project.project']

    def action_log_timesheet(self):
        """事後登錄工時（含已完成待辦）：以「只登錄」模式開啟完成精靈。"""
        self.ensure_one()
        if not self.can_log_timesheet:
            raise UserError(_(
                'Cannot find a project to log time.\n'
                'Link this activity to a project (or a task/lead with a project), '
                'or configure a default timesheet project for the company.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Log Time'),
            'res_model': 'mail.activity.done.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'default_log_only': True,
            },
        }

    # ===== 來源推導：專案 =====

    def _fallback_partner_id(self):
        """res 推不出客戶時，以待辦專案的客戶帶入（需求五）。"""
        return self.project_id.partner_id.id or super()._fallback_partner_id()

    @api.onchange('res_model_id', 'res_id')
    def _onchange_res_fill_project_partner(self):
        """選定 res 後：project_id 空時由 res 反推帶入，再派生客戶。"""
        for activity in self:
            if activity.res_model and activity.res_id and not activity.project_id:
                project = activity._project_from_res(activity.res_model, activity.res_id)
                if project:
                    activity.project_id = project.id
        return super()._onchange_res_fill_project_partner()

    @api.onchange('project_id')
    def _onchange_project_fill_partner(self):
        """選定/變更專案後，若客戶尚未設定則以專案客戶帶入。"""
        for activity in self:
            if activity.project_id and not activity.partner_id:
                activity._derive_partner_from_source(force=False)

    def _continue_todo_action(self):
        action = super()._continue_todo_action()
        if self.project_id:
            action['context']['default_project_id'] = self.project_id.id
        return action
