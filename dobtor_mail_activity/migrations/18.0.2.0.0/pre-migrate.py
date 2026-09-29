# -*- coding: utf-8 -*-
"""核心不再相依 project / hr_timesheet / project_todo / crm / sale_crm。

專案／工時整合搬到 dobtor_mail_activity_project，CRM／銷售搬到
dobtor_mail_activity_crm（兩者 auto_install）。既有資料庫升級時：

1. 把兩個橋接標記為 'to install'（若其相依已安裝）——同一次升級的第二段
   （Odoo loading STEP 3 的 ['to install']）即會安裝它們。
   鐵律：核心升級＋橋接安裝必須同一 run，否則搬走的持久欄位會被 DROP。
   （STEP 2 的 update_list 早於本檔執行，新模組此時已在 ir_module_module。）
2. 把搬走的「持久欄位」ir_model_data 歸屬改到橋接，欄位與資料原地保留
   （反向於 18.0.1.6.0 的併入 migration）。
3. 刪除搬走的核心視圖：核心載入時會驗證本模組全部視圖，而這些舊視圖引用
   的欄位（timesheet_ids、crm.lead.project_id…）在核心載入當下已不存在
   → ParseError。橋接以自己的 xmlid 重建。
4. project_todo 的「待辦事項」選單：舊版被本模組改指向我們的動作；還原為
   project_todo 原動作（專案橋接改以群組隱藏它）。

冪等：重跑不會重複移動或刪除（條件式 UPDATE/DELETE）。
"""
import logging

_logger = logging.getLogger(__name__)

CORE = 'dobtor_mail_activity'
PROJECT = 'dobtor_mail_activity_project'
CRM = 'dobtor_mail_activity_crm'

# (橋接, 相依模組)
BRIDGES = [
    (PROJECT, ('project', 'project_todo', 'hr_timesheet')),
    (CRM, ('project', 'project_todo', 'hr_timesheet', 'crm', 'sale_crm')),
]

# 橋接 → 搬過去的欄位 (model, field)
MOVED_FIELDS = {
    PROJECT: [
        ('mail.activity', 'project_id'),
        ('mail.activity', 'timesheet_ids'),
        ('mail.activity', 'timesheet_feature_enabled'),
        ('mail.activity', 'can_log_timesheet'),
        ('account.analytic.line', 'activity_id'),
        ('res.company', 'dobtor_activity_timesheet_enabled'),
        ('res.company', 'default_timesheet_project_id'),
        ('res.config.settings', 'dobtor_activity_timesheet_enabled'),
        ('res.config.settings', 'timesheet_project_id'),
        ('mail.activity.create.wizard', 'project_id'),
        ('mail.activity.done.wizard', 'accumulated_hours'),
        ('mail.activity.done.wizard', 'actual_hours'),
        ('mail.activity.done.wizard', 'log_only'),
        ('mail.activity.done.wizard', 'timesheet_skipped'),
    ],
    CRM: [
        ('crm.lead', 'project_id'),
        ('crm.lead', 'task_count'),
        ('project.project', 'lead_ids'),
        ('project.project', 'lead_count'),
    ],
}

MOVED_VIEWS = [
    'mail_activity_view_form_schedule_timesheet',
    'res_company_view_form_inherit_productivity',
    'crm_lead_view_form_inherit_productivity',
    'project_project_view_form_inherit_productivity',
]


def migrate(cr, version):
    if not version:
        return
    installing = _mark_bridges_to_install(cr)
    for bridge in installing:
        _move_field_xmlids(cr, bridge)
    _drop_moved_views(cr)
    _restore_project_todo_menu(cr)


def _installed(cr, names):
    cr.execute(
        "SELECT count(*) FROM ir_module_module WHERE name IN %s AND state IN ('installed', 'to upgrade')",
        (tuple(names),))
    return cr.fetchone()[0] == len(names)


def _mark_bridges_to_install(cr):
    installing = []
    for bridge, deps in BRIDGES:
        cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (bridge,))
        row = cr.fetchone()
        if not row:
            _logger.warning('%s not found in module list; cannot auto-install it.', bridge)
            continue
        if row[0] in ('installed', 'to upgrade', 'to install'):
            installing.append(bridge)
            continue
        if not _installed(cr, deps):
            continue
        cr.execute("UPDATE ir_module_module SET state = 'to install' WHERE name = %s", (bridge,))
        installing.append(bridge)
        _logger.info('Marked %s to install (dependencies already installed).', bridge)
    return installing


def _move_field_xmlids(cr, bridge):
    for model, field in MOVED_FIELDS[bridge]:
        name = 'field_%s__%s' % (model.replace('.', '_'), field)
        cr.execute("""
            UPDATE ir_model_data d SET module = %(bridge)s
             WHERE d.module = %(core)s AND d.model = 'ir.model.fields' AND d.name = %(name)s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data b
                    WHERE b.module = %(bridge)s AND b.name = %(name)s)
        """, {'bridge': bridge, 'core': CORE, 'name': name})
        if cr.rowcount:
            _logger.info('Moved field xmlid %s -> %s', name, bridge)


def _drop_moved_views(cr):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND model = 'ir.ui.view' AND name IN %s
    """, (CORE, tuple(MOVED_VIEWS)))
    view_ids = tuple(r[0] for r in cr.fetchall())
    if not view_ids:
        return
    # 先刪子視圖（若有人繼承它們），再刪本身
    cr.execute("DELETE FROM ir_ui_view WHERE inherit_id IN %s", (view_ids,))
    cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id IN %s", (view_ids,))
    cr.execute("DELETE FROM ir_ui_view WHERE id IN %s", (view_ids,))
    _logger.info('Dropped %d moved views (recreated by bridges).', len(view_ids))


def _restore_project_todo_menu(cr):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'project_todo' AND name = 'menu_todo_todos' AND model = 'ir.ui.menu'
    """)
    menu = cr.fetchone()
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'project_todo' AND name = 'project_task_preload_action_todo'
    """)
    action = cr.fetchone()
    if not menu or not action:
        return
    cr.execute("UPDATE ir_ui_menu SET action = %s WHERE id = %s",
               ('ir.actions.server,%s' % action[0], menu[0]))
