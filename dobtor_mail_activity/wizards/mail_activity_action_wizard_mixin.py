# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class MailActivityActionWizardMixin(models.AbstractModel):
    """動作型待辦精靈共用資訊 Mixin

    完成 / 延期 / 轉移 / 改派 等 wizard 皆針對「既有的一筆 mail.activity」操作。
    為了讓每個 wizard 的顯示資訊完整且一致，這裡集中定義整套「待辦資訊」唯讀
    欄位（同一組欄位名），各 wizard 只需 `_inherit` 即可取得相同的 context 區塊，
    再各自加上其專屬的動作欄位。
    """
    _name = 'mail.activity.action.wizard.mixin'
    _description = 'Activity Action Wizard Common Info'

    # ===== 目標待辦 =====
    activity_id = fields.Many2one(
        'mail.activity',
        string='Activity',
        required=True,
        readonly=True,
        ondelete='cascade',
    )

    # ===== 待辦資訊（唯讀，統一欄位名）=====
    summary = fields.Char(
        string='Activity Summary',
        related='activity_id.summary',
        readonly=True,
    )
    activity_type_name = fields.Char(
        string='Activity Type',
        related='activity_id.activity_type_id.name',
        readonly=True,
    )
    date_deadline = fields.Date(
        string='Due Date',
        related='activity_id.date_deadline',
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
    urgency = fields.Selection(
        related='activity_id.urgency',
        string='Urgency',
        readonly=True,
    )
    importance = fields.Selection(
        related='activity_id.importance',
        string='Importance',
        readonly=True,
    )
    assignee_id = fields.Many2one(
        'res.users',
        string='Current Assignee',
        related='activity_id.user_id',
        readonly=True,
    )
    res_display = fields.Char(
        string='Related Document',
        compute='_compute_res_display',
    )
    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        related='activity_id.note_id',
        readonly=True,
    )

    @api.depends('activity_id')
    def _compute_res_display(self):
        """顯示待辦關聯文件名稱（格式：名稱 (模型)）。"""
        for wizard in self:
            activity = wizard.activity_id
            if activity.res_model and activity.res_id:
                try:
                    record = self.env[activity.res_model].browse(activity.res_id)
                    if record.exists():
                        model_name = self.env['ir.model']._get(activity.res_model).name
                        wizard.res_display = f'{record.display_name} ({model_name})'
                    else:
                        wizard.res_display = _('(Record deleted)')
                except Exception as e:
                    _logger.debug('Failed to compute res_display: %s', str(e))
                    wizard.res_display = f'{activity.res_model},{activity.res_id}'
            else:
                wizard.res_display = False

    @api.model
    def default_get(self, fields_list):
        """共用預設值：從 context 取得 activity_id。"""
        res = super().default_get(fields_list)
        if 'activity_id' not in res and self.env.context.get('default_activity_id'):
            res['activity_id'] = self.env.context.get('default_activity_id')
        return res
