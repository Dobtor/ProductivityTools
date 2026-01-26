# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityFromMessageWizard(models.TransientModel):
    """從訊息建立待辦精靈

    功能說明:
    - 從 mail.message 建立新的待辦
    - 自動預填訊息內容摘要
    - 支援選擇目標文件（依 transfer.config 配置）
    - 記錄來源訊息以供追蹤
    - 若指派給用戶，自動將其加入訊息所在頻道
    """
    _name = 'mail.activity.from.message.wizard'
    _description = 'Create Activity from Message Wizard'

    # ===== 訊息資訊 =====
    message_id = fields.Many2one(
        'mail.message',
        string='Source Message',
        readonly=True,
    )
    message_body_preview = fields.Html(
        string='Message Preview',
        compute='_compute_message_preview',
    )
    message_author = fields.Char(
        string='Message Author',
        compute='_compute_message_preview',
    )
    message_date = fields.Datetime(
        string='Message Time',
        related='message_id.date',
        readonly=True,
    )

    # ===== 目標選擇 =====
    target_ref = fields.Reference(
        string='Target Record',
        selection='_selection_target_model',
        required=True,
    )

    # ===== 待辦設定 =====
    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Activity Type',
        required=True,
        default=lambda self: self._default_activity_type(),
    )
    summary = fields.Char(
        string='Summary',
    )
    note = fields.Html(
        string='Note',
    )
    date_deadline = fields.Date(
        string='Deadline',
        required=True,
        default=fields.Date.context_today,
    )
    estimated_hours = fields.Float(
        string='Estimated Hours',
        default=1.0,
    )
    urgency = fields.Selection([
        ('urgent', 'Urgent'),
        ('standard', 'Standard'),
        ('flexible', 'Flexible'),
    ], string='Urgency', default='standard', required=True)
    importance = fields.Selection([
        ('important', 'Important'),
        ('normal', 'Normal'),
    ], string='Importance', default='normal', required=True)
    user_id = fields.Many2one(
        'res.users',
        string='Assign To',
        help='If not assigned, activity will wait to be claimed',
    )

    @api.model
    def _default_activity_type(self):
        """預設待辦類型：待辦事項"""
        return self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

    @api.model
    def _selection_target_model(self):
        """取得允許的目標模型選項（使用共用方法）"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.model
    def default_get(self, fields_list):
        """預設值處理：從 context 取得訊息資訊"""
        res = super().default_get(fields_list)

        # 從 context 取得 message_id
        if 'message_id' not in res and self.env.context.get('default_message_id'):
            res['message_id'] = self.env.context.get('default_message_id')

        return res

    @api.depends('message_id')
    def _compute_message_preview(self):
        """計算訊息預覽和作者"""
        for wizard in self:
            if wizard.message_id:
                body = wizard.message_id.body or ''
                # 截取前 500 字元作為預覽
                wizard.message_body_preview = body[:500] if len(body) > 500 else body
                # 作者名稱
                wizard.message_author = wizard.message_id.author_id.name if wizard.message_id.author_id else _('Unknown')
            else:
                wizard.message_body_preview = False
                wizard.message_author = False

    @api.onchange('message_id')
    def _onchange_message_id(self):
        """從訊息內容預填待辦摘要"""
        if self.message_id:
            body = self.message_id.body or ''
            plain_text = self._strip_html_tags(body, max_length=100)
            self.summary = plain_text or _('From Message')

            # 預填備註為完整訊息內容
            if not self.note:
                self.note = self.message_id.body

    def _strip_html_tags(self, html_content, max_length=None):
        """清理 HTML 標籤，提取純文字"""
        if not html_content:
            return ''
        plain_text = re.sub(r'<[^>]+>', '', html_content)
        plain_text = plain_text.strip()
        if max_length and len(plain_text) > max_length:
            return plain_text[:max_length] + '...'
        return plain_text

    def _validate_create(self):
        """驗證建立操作"""
        self.ensure_one()

        if not self.target_ref:
            raise UserError(_('Please select a target record.'))

        # 驗證目標記錄存在
        if not self.target_ref.exists():
            raise UserError(_('Target record does not exist.'))

        if not self.activity_type_id:
            raise UserError(_('Please select an activity type.'))

        if not self.date_deadline:
            raise UserError(_('Please select a deadline.'))

    def _prepare_activity_values(self):
        """準備建立待辦的值"""
        self.ensure_one()

        target_model = self.target_ref._name
        target_id = self.target_ref.id
        target_model_id = self.env['ir.model']._get(target_model)

        vals = {
            'activity_type_id': self.activity_type_id.id,
            'summary': self.summary,
            'note': self.note or (self.message_id.body if self.message_id else False),
            'date_deadline': self.date_deadline,
            'estimated_hours': self.estimated_hours,
            'urgency': self.urgency,
            'importance': self.importance,
            'res_model_id': target_model_id.id,
            'res_id': target_id,
        }

        # 記錄來源訊息
        if self.message_id:
            vals['source_message_id'] = self.message_id.id

        # 只有指定了用戶才設定 user_id
        if self.user_id:
            vals['user_id'] = self.user_id.id

        return vals

    def _add_user_to_channel(self):
        """將被指派者加入來源訊息所在的頻道"""
        if self.user_id and self.message_id:
            self.env['mail.activity']._add_user_to_channel_from_message(
                self.message_id, self.user_id
            )

    @api.model
    def action_open_wizard(self, message_id):
        """從訊息 ID 開啟 wizard（供外部調用）"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Activity from Message'),
            'res_model': 'mail.activity.from.message.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_message_id': message_id,
            }
        }

    def action_create_activity(self):
        """建立待辦"""
        self.ensure_one()
        self._validate_create()

        # 建立待辦
        activity = self.env['mail.activity'].create(self._prepare_activity_values())

        # 將被指派者加入來源訊息所在的頻道
        self._add_user_to_channel()

        # 關閉視窗
        return {'type': 'ir.actions.act_window_close'}
