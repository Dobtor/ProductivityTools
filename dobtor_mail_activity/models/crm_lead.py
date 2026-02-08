# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    """CRM 商機擴展

    新增專案關聯功能：
    - 商機可關聯到專案，用於工時記錄歸屬
    - 建立時自動填入公司預設工時表專案
    - 專案變更時自動遷移相關工時記錄
    """
    _inherit = 'crm.lead'

    project_id = fields.Many2one(
        'project.project',
        string='Project',
        tracking=True,
        help='Project associated with this lead for timesheet tracking.',
    )
    activity_count = fields.Integer(
        string='Activity Count',
        compute='_compute_activity_count',
    )

    # ========== 計算方法 ==========

    @api.depends('project_id')
    def _compute_activity_count(self):
        """計算關聯專案的任務數量"""
        for lead in self:
            if lead.project_id:
                lead.activity_count = self.env['project.task'].search_count([
                    ('project_id', '=', lead.project_id.id),
                ])
            else:
                lead.activity_count = 0

    # ========== CRUD 覆寫 ==========

    @api.model_create_multi
    def create(self, vals_list):
        """覆寫 create：未指定專案時自動填入公司預設工時表專案"""
        for vals in vals_list:
            if not vals.get('project_id'):
                default_project = self.env.company.default_timesheet_project_id
                if default_project:
                    vals['project_id'] = default_project.id
        return super().create(vals_list)

    def write(self, vals):
        """覆寫 write：專案變更時遷移相關工時記錄

        在 super().write() 前捕獲每筆商機的舊專案，
        寫入完成後逐一執行工時遷移。
        """
        if 'project_id' not in vals:
            return super().write(vals)

        # 捕獲變更前的專案（per lead）
        old_projects = {}
        new_project_id = vals.get('project_id')
        for lead in self:
            if lead.project_id.id != new_project_id:
                old_projects[lead.id] = lead.project_id

        result = super().write(vals)

        # 遷移工時記錄
        new_project = self.env['project.project'].browse(new_project_id) if new_project_id else False
        for lead in self:
            old_project = old_projects.get(lead.id)
            if old_project and new_project:
                self._migrate_lead_timesheets(lead, old_project, new_project)

        return result

    # ========== 工時遷移 ==========

    def _migrate_lead_timesheets(self, lead, old_project, new_project):
        """遷移商機相關工時記錄到新專案

        Args:
            lead: crm.lead 單筆記錄
            old_project: 變更前的 project.project 記錄
            new_project: 變更後的 project.project 記錄

        驗證失敗時在商機 chatter 發布警告，不阻止專案變更。
        """
        # 驗證新專案
        if not new_project.allow_timesheets:
            lead.message_post(
                body=_('Timesheet migration skipped: project "%(project)s" does not have timesheets enabled.',
                       project=new_project.name),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            return

        if not new_project.account_id or not new_project.account_id.active:
            lead.message_post(
                body=_('Timesheet migration skipped: project "%(project)s" is missing a valid analytic account.',
                       project=new_project.name),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            return

        # 搜尋該商機在舊專案下的工時記錄
        timesheets = self.env['account.analytic.line'].sudo().search([
            ('activity_id.res_model', '=', 'crm.lead'),
            ('activity_id.res_id', '=', lead.id),
            ('project_id', '=', old_project.id),
        ])

        if not timesheets:
            return

        # 更新工時記錄
        timesheets.sudo().write({
            'project_id': new_project.id,
            'account_id': new_project.account_id.id,
        })

        # 發布遷移摘要
        lead.message_post(
            body=_('Migrated %(count)s timesheet entries from project "%(old)s" to "%(new)s".',
                   count=len(timesheets),
                   old=old_project.name,
                   new=new_project.name),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

    # ========== Smart Button 動作 ==========

    def action_view_activities(self):
        """開啟關聯專案的任務列表"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Activities'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.project_id.id)],
            'context': {
                'default_project_id': self.project_id.id,
            },
        }
