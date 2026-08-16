# -*- coding: utf-8 -*-

from . import note_stage
from . import note_tag
from . import note_note
from . import mail_activity
# 以下六檔自 mail_activity.py 拆出，皆為 _inherit = 'mail.activity' 的同一模型。
# 必須排在 mail_activity 之後：欄位定義與 create/write/_search 等核心覆寫仍在
# 該檔（它同時以 _name + _inherit 清單掛上 mail.thread），拆出檔只放方法。
from . import mail_activity_editor
from . import mail_activity_message
from . import mail_activity_merge
from . import mail_activity_relation_diagram
from . import mail_activity_source
from . import mail_activity_week
from . import calendar_event
from . import mail_activity_type
from . import mail_activity_assignment_history
from . import mail_activity_postpone_history
from . import mail_activity_transfer_config
from . import mail_message
from . import res_company
from . import res_users
# 併入自 dobtor_mail_activity_timesheet（crm/專案/銷售/工時整合）
from . import account_analytic_line
from . import crm_lead
from . import project_project
from . import sale_order
from . import weekly_report
from . import activity_efficiency_metrics
from . import weekly_schedule_config
