# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import UserError
from dateutil import rrule


# 從 calendar 模組複製的常量
RRULE_WEEKDAYS = {
    'mon': 'MO',
    'tue': 'TU',
    'wed': 'WE',
    'thu': 'TH',
    'fri': 'FR',
    'sat': 'SA',
    'sun': 'SU',
}


class CalendarRecurrence(models.Model):
    """修補 Google Calendar 同步的 rrule 解析 bug

    問題：當 Google Calendar 傳入 FREQ=WEEKLY 但沒有 BYDAY 參數時，
    Odoo 的 _rrule_parse 方法不會設置任何星期幾欄位，導致後續
    _get_rrule 方法拋出 "You have to choose at least one day in the week" 錯誤。

    解決方案：
    1. 覆寫 _rrule_parse 方法，在 FREQ=WEEKLY 沒有 BYDAY 時自動設置默認星期幾
    2. 覆寫 _get_rrule 方法，在沒有設置星期幾時自動使用 dtstart 的星期幾
    """
    _inherit = 'calendar.recurrence'

    @api.model
    def _rrule_parse(self, rule_str, date_start):
        """覆寫 rrule 解析方法，修補 FREQ=WEEKLY 沒有 BYDAY 的情況"""
        data = super()._rrule_parse(rule_str, date_start)

        day_list = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

        if data.get('rrule_type') == 'weekly' and date_start:
            has_weekday = any(data.get(day) for day in day_list)

            if not has_weekday:
                # RFC 5545: 如果沒有 BYDAY，使用 DTSTART 的星期幾
                weekday_index = date_start.weekday()
                for day in day_list:
                    data[day] = False
                data[day_list[weekday_index]] = True

        return data

    def _get_week_days(self):
        """覆寫以處理沒有設置星期幾的情況"""
        day_fields = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

        # 檢查是否有設置任何星期幾
        weekdays = tuple(
            rrule.weekday(weekday_index)
            for weekday_index, weekday in {
                rrule.MO.weekday: self.mon,
                rrule.TU.weekday: self.tue,
                rrule.WE.weekday: self.wed,
                rrule.TH.weekday: self.thu,
                rrule.FR.weekday: self.fri,
                rrule.SA.weekday: self.sat,
                rrule.SU.weekday: self.sun,
            }.items() if weekday
        )

        # 如果沒有設置任何星期幾，使用 base_event 的開始日期的星期幾
        if not weekdays:
            base_event = self.base_event_id or self._get_first_event()
            if base_event and base_event.start:
                weekday_index = base_event.start.weekday()
                weekdays = (rrule.weekday(weekday_index),)
                # 同時更新記錄
                self.write({day_fields[weekday_index]: True})

        return weekdays

    def _get_rrule(self, dtstart=None):
        """覆寫 _get_rrule 方法，在沒有設置星期幾時不拋出錯誤"""
        from odoo.addons.calendar.models.calendar_recurrence import (
            freq_to_rrule, MAX_RECURRENT_EVENT
        )
        from datetime import time, datetime

        self.ensure_one()
        freq = self.rrule_type

        rrule_params = dict(
            dtstart=dtstart,
            interval=self.interval,
        )

        if freq == 'monthly' and self.month_by == 'date':
            rrule_params['bymonthday'] = self.day
        elif freq == 'monthly' and self.month_by == 'day':
            rrule_params['byweekday'] = getattr(rrule, RRULE_WEEKDAYS[self.weekday])(int(self.byday))
        elif freq == 'weekly':
            weekdays = self._get_week_days()
            if not weekdays:
                # 最後的防線：使用 dtstart 的星期幾
                if dtstart:
                    weekday_index = dtstart.weekday()
                    weekdays = (rrule.weekday(weekday_index),)
                else:
                    raise UserError(_("You have to choose at least one day in the week"))
            rrule_params['byweekday'] = weekdays
            rrule_params['wkst'] = self._get_lang_week_start()

        if self.end_type == 'count':
            rrule_params['count'] = min(self.count, MAX_RECURRENT_EVENT)
        elif self.end_type == 'forever':
            rrule_params['count'] = MAX_RECURRENT_EVENT
        elif self.end_type == 'end_date':
            rrule_params['until'] = datetime.combine(self.until, time.max)

        return rrule.rrule(freq_to_rrule(freq), **rrule_params)
