# -*- coding: utf-8 -*-

from . import models


def _fix_calendar_template_translation(env):
    """Fix zh_TW translation bugs in calendar email templates.

    The official zh_TW.po for the calendar module contains two errors:
    - 'format_datetime' mistranslated as 'strformat_datetime' (non-existent function)
    - 'object.mail_tz' mistranslated as 'object.daymail_tz' (non-existent attribute)

    A defensive field alias (daymail_tz) is also added on calendar.attendee,
    but fixing the template text is the proper solution.
    """
    env.cr.execute("""
        UPDATE mail_template
        SET body_html = REPLACE(
            REPLACE(body_html::text, 'daymail_tz', 'mail_tz'),
            'strformat_datetime', 'format_datetime'
        )::jsonb
        WHERE body_html::text LIKE '%%daymail_tz%%'
           OR body_html::text LIKE '%%strformat_datetime%%'
    """)


def _post_init_hook(env):
    """Post-init hook."""
    _fix_calendar_template_translation(env)
