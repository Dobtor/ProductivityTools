# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class CalendarEvent(models.Model):
    """日曆事件 - 擴展會議記錄功能

    提供日曆事件與筆記本的關聯功能，讓用戶可以：
    - 為會議建立會議記錄筆記
    - 從日曆視圖快速新增筆記
    - 查看會議關聯的所有筆記
    """
    _inherit = 'calendar.event'

    # ===== 筆記關聯欄位 =====
    note_ids = fields.Many2many(
        'note.note',
        'calendar_event_note_rel',
        'event_id',
        'note_id',
        string='Meeting Minutes',
        help='Meeting minutes linked to this calendar event',
    )
    note_count = fields.Integer(
        string='Minutes Count',
        compute='_compute_note_count',
    )

    # ===== 計算方法 =====
    @api.depends('note_ids')
    def _compute_note_count(self):
        """計算關聯筆記數量"""
        for event in self:
            event.note_count = len(event.note_ids)

    # ===== 動作方法 =====
    def action_view_notes(self):
        """查看關聯筆記"""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Meeting Minutes'),
            'res_model': 'note.note',
            'view_mode': 'kanban,list,form',
            'views': [(False, 'kanban'), (False, 'list'), (False, 'form')],
            'domain': [('id', 'in', self.note_ids.ids)],
            'context': {
                'default_note_type': 'meeting',
                'default_calendar_event_ids': [(4, self.id)],
                'search_default_open_true': 1,
            },
        }
        if len(self.note_ids) == 1:
            action['view_mode'] = 'form'
            action['views'] = [(False, 'form')]
            action['res_id'] = self.note_ids.id
        return action

    def action_create_note(self):
        """建立會議記錄"""
        self.ensure_one()
        # 準備筆記內容模板
        memo_template = self._prepare_meeting_note_template()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Meeting Minutes'),
            'res_model': 'note.note',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_note_type': 'meeting',
                'default_memo': memo_template,
                'default_calendar_event_ids': [(4, self.id)],
            },
        }

    def _prepare_meeting_note_template(self):
        """準備會議記錄模板

        第一行嵌入會議名稱（作為標題），其餘為章節結構。
        Portal 和 PDF 報表已從關聯的行事曆事件自動顯示時間/地點/與會者。

        Returns:
            str: HTML 格式的會議記錄模板
        """
        from markupsafe import Markup, escape
        title = escape(self.name or '')
        base_template = self.env['note.note']._default_meeting_memo_template()
        return Markup('<p>%s</p>') % title + Markup(base_template)
