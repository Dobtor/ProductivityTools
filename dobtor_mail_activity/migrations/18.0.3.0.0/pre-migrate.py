# -*- coding: utf-8 -*-
"""筆記（note.note / note.stage / note.tag）與待辦↔筆記整合搬到 dobtor_meeting_minutes。

dobtor_meeting_minutes 相依本模組，同一次升級中一定在本模組之後載入：
- 已安裝會議記錄：升級本模組時 Odoo 會連帶升級它（相依者）
- 未安裝：本檔把它標為 'to install'，於同一次升級的第二段安裝

本檔在本模組載入前執行，負責：
1. XML ID 歸屬轉給 dobtor_meeting_minutes（清單由新舊兩版實裝後比對產生，
   共 136 筆）。否則升級結束的孤兒清理會把 note_note 等資料表連同資料刪掉。
2. 關聯表（ir_model_relation）與約束（ir_model_constraint）歸屬一併轉移。
3. 舊的 note.calendar_event_id（多對一）資料補進 calendar_event_note_rel
   （多對多，會議記錄模組的做法）；該欄位隨後由 Odoo 移除。
4. 刪除本模組舊的日曆視圖（引用的 calendar.event.note_count 在本模組載入時已
   不存在 → 視圖驗證 ParseError；會議記錄模組有自己的同功能視圖）。

冪等：重跑不會重複搬移或插入。
"""
import logging

_logger = logging.getLogger(__name__)

CORE = 'dobtor_mail_activity'
MEETING = 'dobtor_meeting_minutes'

TRANSFER_XMLIDS = [
    # ir.actions.act_window
    'action_note_note',
    'action_note_only',
    'action_note_stage',
    'action_note_tag',
    # ir.actions.act_window.view
    'action_note_note_form',
    'action_note_note_kanban',
    'action_note_note_list',
    'action_note_only_form',
    'action_note_only_kanban',
    'action_note_only_list',
    'action_note_stage_form',
    'action_note_stage_list',
    'action_note_tag_form',
    'action_note_tag_list',
    # ir.model
    'model_calendar_event',
    'model_note_note',
    'model_note_stage',
    'model_note_tag',
    # ir.model.access
    'access_note_note',
    'access_note_stage',
    'access_note_tag_admin',
    'access_note_tag_user',
    # ir.model.constraint
    'constraint_note_tag_name_parent_uniq',
    # ir.model.fields
    'field_calendar_event__note_count',
    'field_calendar_event__note_ids',
    'field_mail_activity__note_count',
    'field_mail_activity__note_id',
    'field_mail_activity__note_ids',
    'field_mail_activity_action_wizard_mixin__note_id',
    'field_mail_activity_cancel_wizard__note_id',
    'field_mail_activity_create_wizard__note_id',
    'field_mail_activity_done_wizard__note_id',
    'field_mail_activity_merge_wizard__merged_note_count',
    'field_mail_activity_postpone_wizard__note_id',
    'field_mail_activity_reassign_wizard__note_id',
    'field_mail_activity_transfer_wizard__note_id',
    'field_note_note__access_token',
    'field_note_note__access_url',
    'field_note_note__access_warning',
    'field_note_note__active',
    'field_note_note__activity_calendar_event_id',
    'field_note_note__activity_date_deadline',
    'field_note_note__activity_exception_decoration',
    'field_note_note__activity_exception_icon',
    'field_note_note__activity_ids',
    'field_note_note__activity_state',
    'field_note_note__activity_summary',
    'field_note_note__activity_type_icon',
    'field_note_note__activity_type_id',
    'field_note_note__activity_user_id',
    'field_note_note__color',
    'field_note_note__create_date',
    'field_note_note__create_uid',
    'field_note_note__date_done',
    'field_note_note__display_name',
    'field_note_note__has_message',
    'field_note_note__id',
    'field_note_note__main_tag_id',
    'field_note_note__memo',
    'field_note_note__message_attachment_count',
    'field_note_note__message_follower_ids',
    'field_note_note__message_has_error',
    'field_note_note__message_has_error_counter',
    'field_note_note__message_has_sms_error',
    'field_note_note__message_ids',
    'field_note_note__message_is_follower',
    'field_note_note__message_needaction',
    'field_note_note__message_needaction_counter',
    'field_note_note__message_partner_ids',
    'field_note_note__my_activity_date_deadline',
    'field_note_note__name',
    'field_note_note__note_active_activity_count',
    'field_note_note__note_activity_count',
    'field_note_note__note_activity_ids',
    'field_note_note__note_type',
    'field_note_note__open',
    'field_note_note__sequence',
    'field_note_note__stage_id',
    'field_note_note__stage_ids',
    'field_note_note__tag_ids',
    'field_note_note__user_id',
    'field_note_note__website_message_ids',
    'field_note_note__write_date',
    'field_note_note__write_uid',
    'field_note_stage__create_date',
    'field_note_stage__create_uid',
    'field_note_stage__display_name',
    'field_note_stage__fold',
    'field_note_stage__id',
    'field_note_stage__name',
    'field_note_stage__sequence',
    'field_note_stage__user_id',
    'field_note_stage__write_date',
    'field_note_stage__write_uid',
    'field_note_tag__active',
    'field_note_tag__child_ids',
    'field_note_tag__color',
    'field_note_tag__create_date',
    'field_note_tag__create_uid',
    'field_note_tag__display_name',
    'field_note_tag__id',
    'field_note_tag__name',
    'field_note_tag__parent_id',
    'field_note_tag__parent_path',
    'field_note_tag__write_date',
    'field_note_tag__write_uid',
    'field_weekly_schedule_config__auto_create_note',
    'field_weekly_schedule_config__note_id',
    # ir.model.fields.selection
    'selection__note_note__note_type__note',
    'selection__weekly_schedule_config__target_model__note_note',
    # ir.model.inherit
    'model_inherit__note_note__mail_activity_mixin',
    'model_inherit__note_note__mail_thread',
    'model_inherit__note_note__portal_mixin',
    # ir.rule
    'note_note_rule_manager',
    'note_note_rule_user',
    'note_stage_rule_manager',
    'note_stage_rule_user',
    # ir.ui.menu
    'menu_note_notes',
    'menu_note_stage',
    'menu_note_tag',
    'menu_notebook_configuration',
    'menu_notebook_root',
    # ir.ui.view
    'view_note_note_form',
    'view_note_note_kanban',
    'view_note_note_list',
    'view_note_note_quick_create',
    'view_note_note_search',
    'view_note_stage_form',
    'view_note_stage_list',
    'view_note_tag_form',
    'view_note_tag_list',
    'view_note_tag_search',
    # mail.activity.transfer.config
    'transfer_config_note',
    # note.stage
    'note_stage_draft',
    'note_stage_planning',
    'note_stage_published',
]

RELATION_TABLES = ('note_note_stage_rel', 'note_note_tag_rel', 'mail_activity_note_rel')


def migrate(cr, version):
    if not version:
        return
    _ensure_meeting_minutes(cr)
    _transfer_xmlids(cr)
    _transfer_relations_and_constraints(cr)
    _copy_calendar_links(cr)
    _drop_core_calendar_view(cr)


def _ensure_meeting_minutes(cr):
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (MEETING,))
    row = cr.fetchone()
    if not row:
        raise RuntimeError(
            '%s is not in the module list; it must be present on the addons path '
            'to keep existing notes (note.note now lives there).' % MEETING)
    if row[0] == 'uninstalled':
        cr.execute("UPDATE ir_module_module SET state = 'to install' WHERE name = %s", (MEETING,))
        _logger.info('Marked %s to install (notes moved there).', MEETING)
    elif row[0] not in ('installed', 'to upgrade', 'to install'):
        # uninstallable / to remove：搬過去的 XML ID 會掛在不會載入的模組上
        raise RuntimeError(
            '%s is in state %r; it must be installable to keep existing notes.' % (MEETING, row[0]))


def _transfer_xmlids(cr):
    cr.execute("""
        UPDATE ir_model_data d SET module = %(meeting)s
         WHERE d.module = %(core)s AND d.name IN %(names)s
           AND NOT EXISTS (SELECT 1 FROM ir_model_data m
                            WHERE m.module = %(meeting)s AND m.name = d.name)
    """, {'meeting': MEETING, 'core': CORE, 'names': tuple(TRANSFER_XMLIDS)})
    _logger.info('Transferred %d xmlids %s -> %s', cr.rowcount, CORE, MEETING)


def _transfer_relations_and_constraints(cr):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (CORE,))
    core_id = cr.fetchone()[0]
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (MEETING,))
    meeting_id = cr.fetchone()[0]
    cr.execute("""
        UPDATE ir_model_relation SET module = %s
         WHERE module = %s AND name IN %s
    """, (meeting_id, core_id, RELATION_TABLES))
    cr.execute(r"""
        UPDATE ir_model_constraint SET module = %s
         WHERE module = %s
           AND name <> 'note_note_calendar_event_id_fkey'
           AND (name LIKE 'note\_%%'
                OR name LIKE 'mail\_activity\_note\_%%'
                OR name IN ('mail_activity_note_id_fkey',
                            'weekly_schedule_config_note_id_fkey',
                            'mail_activity_create_wizard_note_id_fkey'))
    """, (meeting_id, core_id))


def _copy_calendar_links(cr):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'note_note' AND column_name = 'calendar_event_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("SELECT to_regclass('calendar_event_note_rel')")
    if cr.fetchone()[0] is None:
        # 會議記錄模組從沒裝過 → 表還不存在，先照 Odoo 的建法建起來（含反向索引；
        # Odoo 之後看到表已存在就不會再補索引）
        cr.execute("""
            CREATE TABLE calendar_event_note_rel (
                note_id integer NOT NULL REFERENCES note_note(id) ON DELETE CASCADE,
                event_id integer NOT NULL REFERENCES calendar_event(id) ON DELETE CASCADE,
                PRIMARY KEY (note_id, event_id)
            );
            CREATE INDEX ON calendar_event_note_rel (event_id, note_id);
        """)
    cr.execute("""
        INSERT INTO calendar_event_note_rel (note_id, event_id)
        SELECT id, calendar_event_id FROM note_note
         WHERE calendar_event_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    _logger.info('Copied %d note.calendar_event_id links into calendar_event_note_rel', cr.rowcount)


def _drop_core_calendar_view(cr):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND model = 'ir.ui.view'
           AND name = 'calendar_event_view_calendar_inherit_productivity'
    """, (CORE,))
    row = cr.fetchone()
    if not row:
        return
    cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id = %s", (row[0],))
    cr.execute("DELETE FROM ir_ui_view WHERE id = %s", (row[0],))
