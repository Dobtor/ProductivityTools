# -*- coding: utf-8 -*-
{
    'name': 'Calendar Recurrence/Sync Fixes',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Calendar',
    'summary': 'Standalone fixes for Odoo 18 calendar recurrence (Google sync) and zh_TW template bugs',
    'description': """
Calendar Recurrence / Sync Fixes
================================
Independent bug-fix module for Odoo core ``calendar``. Extracted from
``dobtor_mail_activity`` so the fixes can be installed, upgraded or removed
on their own, without touching the productivity tooling.

Fixes:
------
* ``calendar.recurrence``: FREQ=WEEKLY without BYDAY (Google Calendar sync)
  no longer raises "You have to choose at least one day in the week".
* ``calendar.attendee``: defensive ``daymail_tz`` alias for a broken
  zh_TW translation reference (``daymail_tz`` vs ``mail_tz``).

These patches apply on Odoo <= 18.0; remove this module once Odoo fixes the
issues upstream.
    """,
    'author': 'Dobtor SI',
    'website': 'https://www.dobtor.com',
    'depends': [
        'calendar',
    ],
    'data': [],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
    'post_init_hook': '_post_init_hook',
}
