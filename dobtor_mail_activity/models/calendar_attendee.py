# -*- coding: utf-8 -*-

from odoo import fields, models


class CalendarAttendee(models.Model):
    _inherit = 'calendar.attendee'

    # Defensive alias: zh_TW translation of calendar email templates
    # incorrectly references 'daymail_tz' instead of 'mail_tz'.
    daymail_tz = fields.Selection(related='mail_tz', store=False)
