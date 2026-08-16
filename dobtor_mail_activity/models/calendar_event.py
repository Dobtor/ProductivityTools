# -*- coding: utf-8 -*-
"""日曆事件 ↔ 會議記錄。

日曆事件 popover 上的「會議記錄」按鈕（static/src/views/calendar_popover/）
需要三樣東西：note_count 欄位、action_create_note、action_view_notes。

關聯方式刻意用 note.note 上的一個 M2O（calendar_event_id）而非新的中介模型：
會議記錄本質上就是一則筆記，只是知道自己屬於哪場會議；反向的 One2many 讓
日曆端可以直接數與列。ondelete='set null' —— 會議被刪掉，記錄本身仍有保存價值。
"""
from odoo import api, fields, models, _


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    note_ids = fields.One2many(
        'note.note',
        'calendar_event_id',
        string='Meeting Minutes',
    )
    note_count = fields.Integer(
        string='Meeting Minutes Count',
        compute='_compute_note_count',
        # 必須 store：日曆檢視的 popover 由 rawRecord 讀它，
        # 非儲存欄位不會出現在日曆模型抓取的欄位集合中。
        store=True,
    )

    @api.depends('note_ids')
    def _compute_note_count(self):
        # 批次統計，避免每個事件各一次查詢（日曆一次載入整個月）
        counts = {}
        if self.ids:
            groups = self.env['note.note'].with_context(active_test=False)._read_group(
                [('calendar_event_id', 'in', self.ids)],
                groupby=['calendar_event_id'],
                aggregates=['__count'],
            )
            counts = {event.id: count for event, count in groups}
        for event in self:
            event.note_count = counts.get(event.id, 0)

    def action_create_note(self):
        """建立一則關聯本會議的會議記錄，並直接開啟它。

        note.note 的標題（name）是由 memo 第一行計算而來，所以這裡把會議名稱
        寫進 memo 首行當標題，而不是去設 name（那是 compute 欄位）。
        """
        self.ensure_one()
        note = self.env['note.note'].create({
            'memo': '<p>%s</p><p><br/></p>' % _('Meeting Minutes: %s', self.display_name),
            'user_id': self.env.user.id,
            'calendar_event_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meeting Minutes'),
            'res_model': 'note.note',
            'res_id': note.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dobtor_mail_activity.view_note_note_form').id, 'form')],
            'target': 'current',
        }

    def action_view_notes(self):
        """檢視本會議的會議記錄：單筆直接開表單，多筆開清單。"""
        self.ensure_one()
        notes = self.note_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Meeting Minutes'),
            'res_model': 'note.note',
            'target': 'current',
            'context': {'default_calendar_event_id': self.id},
        }
        if len(notes) == 1:
            action.update({
                'res_id': notes.id,
                'view_mode': 'form',
                'views': [(self.env.ref('dobtor_mail_activity.view_note_note_form').id, 'form')],
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('calendar_event_id', '=', self.id)],
            })
        return action
