# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    """CRM 商機擴展

    新增專案關聯功能：
    - 商機可關聯到專案，用於工時記錄歸屬
    - 建立商機（opportunity）時自動填入公司預設工時表專案
    - 專案變更時自動遷移相關工時記錄
    """
    _inherit = 'crm.lead'

    project_id = fields.Many2one(
        'project.project',
        string='Project',
        tracking=True,
        help='Project associated with this lead for timesheet tracking.',
    )
    task_count = fields.Integer(
        string='Task Count',
        compute='_compute_task_count',
    )

    # ========== 計算方法 ==========

    @api.depends('project_id')
    def _compute_task_count(self):
        """批次計算關聯專案的任務數量"""
        # 收集有專案的 lead，批次查詢
        project_ids = [lead.project_id.id for lead in self if lead.project_id]
        if project_ids:
            task_data = self.env['project.task']._read_group(
                [('project_id', 'in', project_ids)],
                ['project_id'],
                ['__count'],
            )
            mapped_count = {project.id: count for project, count in task_data}
        else:
            mapped_count = {}
        for lead in self:
            lead.task_count = mapped_count.get(lead.project_id.id, 0)

    # ========== CRUD 覆寫 ==========

    @api.model_create_multi
    def create(self, vals_list):
        """覆寫 create：商機（opportunity）未指定專案時自動填入公司預設工時表專案

        潛在客戶（lead）不填入預設專案，因為 lead 階段通常不需要工時追蹤。
        """
        for vals in vals_list:
            if not vals.get('project_id') and vals.get('type', 'lead') == 'opportunity':
                default_project = self.env.company.default_timesheet_project_id
                if default_project:
                    vals['project_id'] = default_project.id
        return super().create(vals_list)

    def write(self, vals):
        """覆寫 write：

        1. Lead 轉 Opportunity 時自動補填預設專案
        2. 專案變更時遷移相關工時記錄
        """
        # Lead → Opportunity 轉換：補填預設專案（僅對需要的記錄）
        if vals.get('type') == 'opportunity' and 'project_id' not in vals:
            leads_need_project = self.filtered(
                lambda l: l.type != 'opportunity' and not l.project_id
            )
            if leads_need_project:
                default_project = self.env.company.default_timesheet_project_id
                if default_project:
                    leads_need_project.write({'project_id': default_project.id})

        if 'project_id' not in vals:
            return super().write(vals)

        # 捕獲變更前的專案（僅記錄實際有變更的 lead）
        old_projects = {}
        new_project_id = vals['project_id']
        for lead in self:
            if lead.project_id.id != new_project_id:
                old_projects[lead.id] = lead.project_id

        result = super().write(vals)

        if not old_projects:
            return result

        new_project = self.env['project.project'].browse(new_project_id) if new_project_id else False
        for lead in self:
            old_project = old_projects.get(lead.id)
            if not old_project:
                continue
            if new_project:
                # 有新專案 → 遷移工時
                self._migrate_lead_timesheets(lead, old_project, new_project)
            else:
                # 清空專案 → 警告孤兒工時
                self._warn_orphan_timesheets(lead, old_project)

        return result

    # ========== 工時遷移 ==========

    def _get_lead_timesheets(self, lead, project):
        """取得商機在指定專案下的工時記錄

        先查 activity_id 再查 timesheet，避免跨 FK 的 JOIN。
        """
        activity_ids = self.env['mail.activity'].with_context(active_test=False).sudo().search([
            ('res_model', '=', 'crm.lead'),
            ('res_id', '=', lead.id),
        ]).ids
        if not activity_ids:
            return self.env['account.analytic.line']
        return self.env['account.analytic.line'].sudo().search([
            ('activity_id', 'in', activity_ids),
            ('project_id', '=', project.id),
        ])

    def _migrate_lead_timesheets(self, lead, old_project, new_project):
        """遷移商機相關工時記錄到新專案

        驗證失敗時在商機 chatter 發布警告，不阻止專案變更。
        """
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

        timesheets = self._get_lead_timesheets(lead, old_project)
        if not timesheets:
            return

        timesheets.sudo().write({
            'project_id': new_project.id,
            'account_id': new_project.account_id.id,
        })

        lead.message_post(
            body=_('Migrated %(count)s timesheet entries from project "%(old)s" to "%(new)s".',
                   count=len(timesheets),
                   old=old_project.name,
                   new=new_project.name),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

    def _warn_orphan_timesheets(self, lead, old_project):
        """專案被清空時，警告使用者仍有工時記錄留在舊專案"""
        timesheets = self._get_lead_timesheets(lead, old_project)
        if not timesheets:
            return

        lead.message_post(
            body=_('Project removed. %(count)s timesheet entries remain in project "%(project)s".',
                   count=len(timesheets),
                   project=old_project.name),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

    # ========== Smart Button 動作 ==========

    def action_view_tasks(self):
        """開啟關聯專案的任務列表"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tasks'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.project_id.id)],
            'context': {
                'default_project_id': self.project_id.id,
            },
        }
