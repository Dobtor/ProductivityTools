# -*- coding: utf-8 -*-
"""訊息來源與通知：從 mail.message 建立的待辦、其來源預覽與上下文，
以及覆寫官方通知以套用自訂郵件範本。

「從訊息建立待辦」會把 source_message_id 記在待辦上；本檔負責由它衍生的
預覽、上下文訊息串、開啟原訊息，以及把新負責人加進來源頻道。
"""

import logging

from odoo import api, models, Command, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class MailActivityMessage(models.Model):
    """自 mail_activity.py 拆出，同一個 mail.activity 模型。"""
    _inherit = 'mail.activity'

    @api.depends('source_message_id')
    def _compute_source_message_preview(self):
        """計算來源訊息預覽"""
        for activity in self:
            if activity.source_message_id:
                msg = activity.source_message_id
                body = msg.body or ''
                # 截取前 200 字元作為預覽
                preview = self._html_to_text(body, max_length=200)
                activity.source_message_preview = preview
            else:
                activity.source_message_preview = False

    @api.depends('source_message_id')
    def _compute_source_message_context(self):
        """計算來源訊息的類型和上下文訊息"""
        for activity in self:
            if activity.source_message_id:
                msg = activity.source_message_id

                # 判斷訊息來源類型
                if msg.model == 'discuss.channel':
                    activity.source_message_type = 'channel'
                elif msg.model and msg.res_id:
                    activity.source_message_type = 'document'
                else:
                    activity.source_message_type = False

                # 用兩次有限查詢取代無限全表搜尋：
                # 查詢來源訊息之後（含）的較舊訊息（desc → id <= msg.id）
                Message = self.env['mail.message']
                base_domain = [
                    ('model', '=', msg.model),
                    ('res_id', '=', msg.res_id),
                    ('message_type', 'in', ['comment', 'email']),
                ]
                older = Message.search(
                    base_domain + [('id', '<=', msg.id)],
                    order='date desc, id desc', limit=3,
                )
                newer = Message.search(
                    base_domain + [('id', '>', msg.id)],
                    order='date asc, id asc', limit=2,
                )
                context_msgs = newer | older
                if context_msgs:
                    activity.context_message_ids = context_msgs
                else:
                    activity.context_message_ids = msg
            else:
                activity.source_message_type = False
                activity.context_message_ids = False

    @api.depends('context_message_ids', 'source_message_id')
    def _compute_context_messages_html(self):
        """使用 QWeb 渲染訊息 HTML，採用官方樣式"""
        for activity in self:
            if activity.context_message_ids:
                activity.context_messages_html = self.env['ir.qweb']._render(
                    'dobtor_mail_activity.message_context_preview',
                    {
                        'messages': activity.context_message_ids,
                        'source_message_id': activity.source_message_id.id if activity.source_message_id else False,
                    }
                )
            else:
                activity.context_messages_html = False

    def action_open_source_message(self):
        """開啟來源訊息所在的頁面

        根據訊息來源類型，導航至不同位置：
        - discuss.channel: 開啟 Discuss 介面的對應頻道
        - 其他模型: 開啟文件表單（會自動捲動到 chatter）
        """
        self.ensure_one()
        if not self.source_message_id:
            raise UserError(_('This activity has no source message.'))

        msg = self.source_message_id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        # 處理 Discuss 頻道訊息
        if msg.model == 'discuss.channel' and msg.res_id:
            channel = self.env['discuss.channel'].browse(msg.res_id)
            if not channel.exists():
                raise UserError(_('Source channel no longer exists.'))

            # 確保當前用戶已加入頻道
            partner = self.env.user.partner_id
            if partner:
                member_partners = channel.channel_member_ids.mapped('partner_id')
                if partner not in member_partners:
                    try:
                        channel.add_members(partner_ids=[partner.id])
                    except AccessError:
                        raise UserError(_('Cannot join this channel, you may not have access rights.'))

            # 使用正確的 Odoo 18 Discuss URL 格式
            # /odoo/discuss?active_id=discuss.channel_{channel_id}
            return {
                'type': 'ir.actions.act_url',
                'url': f'{base_url}/odoo/discuss?active_id=discuss.channel_{msg.res_id}',
                'target': 'self',
            }

        # 處理文件 Chatter 訊息
        elif msg.model and msg.res_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': msg.model,
                'res_id': msg.res_id,
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'message_id': msg.id,  # 可用於前端定位訊息
                }
            }

        else:
            raise UserError(_('Cannot locate source message, message information is incomplete.'))

    # ===== 覆寫通知方法：支援自定義郵件模板 =====
    def action_notify(self):
        """覆寫：支援使用 Activity Type 設定的自定義郵件模板發送通知

        若 Activity Type 設定了 use_custom_notify=True 且有 notify_template_id，
        則使用該模板發送郵件；否則使用原始的系統預設通知。
        """
        if not self:
            return

        # 分離使用自定義模板和預設通知的待辦
        custom_notify_activities = self.env['mail.activity']
        default_notify_activities = self.env['mail.activity']

        for activity in self:
            activity_type = activity.activity_type_id
            if (activity_type and
                    hasattr(activity_type, 'use_custom_notify') and
                    activity_type.use_custom_notify and
                    activity_type.notify_template_id):
                custom_notify_activities |= activity
            else:
                default_notify_activities |= activity

        # 自訂模板無法寄送時，退回預設通知（避免完全不通知）
        fallback_notify_activities = self.env['mail.activity']

        # 處理自定義模板通知
        for activity in custom_notify_activities:
            if not activity.user_id:
                continue
            template = activity.activity_type_id.notify_template_id
            # 獨立待辦（res 為空）或模板 model 與 res_model 不符 → 跳過自訂模板寄送，
            # 避免 template.send_mail(False) 對不存在文件寄信（需求七防禦），
            # 改由預設通知路徑處理，確保被指派者仍收到通知
            if not activity.res_model or not activity.res_id or \
                    (template.model and template.model != activity.res_model):
                _logger.debug(
                    'Activity %s: custom notify skipped (no matching res document), '
                    'falling back to default notify', activity.id)
                fallback_notify_activities |= activity
                continue
            # 使用被指派者的語言
            if activity.user_id.lang:
                template = template.with_context(lang=activity.user_id.lang)

            # 發送郵件給被指派者
            template.send_mail(
                activity.res_id,
                force_send=False,
                email_values={
                    'email_to': activity.user_id.email,
                    'recipient_ids': [Command.link(activity.user_id.partner_id.id)],
                },
            )
            _logger.info(
                'Activity %s: sent custom notification using template %s to %s',
                activity.id, template.name, activity.user_id.name
            )

        # 處理預設通知（調用原始方法）；併入自訂模板無法寄送而退回的待辦
        default_notify_activities |= fallback_notify_activities
        # 需求七：獨立待辦（res 為空）無關聯文件，核心 action_notify 會
        # self.env['ir.model']._get(False) / self.env[False].browse(...) → KeyError。
        # 其 systray 計數已於 create 覆寫發送；此處略過「文件式」郵件/inbox 通知
        # （無文件可據以發送），避免崩潰。
        # 同時濾掉「無指派人」的未指派待辦：官方 create 會把它們一併送進
        # action_notify，官方在寄送前雖有 `if activity.user_id` 守衛不會出錯，
        # 但在那之前已白白算過 model_description 與整段 qweb 樣板。
        notifiable = default_notify_activities.filtered(
            lambda a: a.res_model and a.res_id and a.user_id)
        skipped = default_notify_activities - notifiable
        if skipped:
            _logger.debug(
                'action_notify: skip document-based notify for %s activities '
                '(standalone or unassigned); systray count is handled by core create.',
                len(skipped))
        if notifiable:
            super(MailActivityMessage, notifiable).action_notify()

    @api.model
    def _add_user_to_channel_from_message(self, message, user):
        """將用戶加入訊息所在的 Discuss 頻道（共用方法）

        Args:
            message: mail.message 記錄或 False
            user: res.users 記錄

        注意：Odoo 18 使用 discuss.channel 取代 mail.channel
        """
        if not message or not user:
            return

        # 檢查訊息是否來自 discuss 頻道
        if message.model == 'discuss.channel' and message.res_id:
            channel = self.env['discuss.channel'].browse(message.res_id)
            if channel.exists():
                partner = user.partner_id
                if partner:
                    # 檢查用戶是否已在頻道中
                    member_partners = channel.channel_member_ids.mapped('partner_id')
                    if partner not in member_partners:
                        try:
                            channel.add_members(partner_ids=[partner.id])
                        except Exception as e:
                            _logger.debug(
                                'Could not add user %s to channel %s: %s',
                                user.id, channel.id, str(e)
                            )

    def _add_user_to_source_channel(self, user):
        """將用戶加入來源訊息所在的 Discuss 頻道"""
        self.ensure_one()
        self._add_user_to_channel_from_message(self.source_message_id, user)
