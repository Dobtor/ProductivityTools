# -*- coding: utf-8 -*-
"""併入 dobtor_mail_activity_timesheet 的 pre-migration。

背景：橋接模組 dobtor_mail_activity_timesheet 曾以「自己模組」的身分建立
crm.lead.project_id、account.analytic.line.activity_id、project.project.lead_ids
等**持久欄位（有資料）**。本版把這些程式併入核心 dobtor_mail_activity 並將刪除
橋接模組。若直接讓 Odoo 卸載橋接，會 CASCADE 掉這些欄位與其資料。

策略（pre-migration 於本模組升級、載入新程式碼之前執行）：
1. 把橋接對「持久欄位（ir.model.fields）」的 ir_model_data 歸屬改到核心，
   使卸載橋接時不再連帶刪除欄位/資料（核心稍後載入會沿用同一列）。
2. 刪除橋接自身的 view/action/rule/access 之 ir_model_data（核心已重新定義
   等價物件），讓卸載時無殘留可 CASCADE。
3. 把橋接模組標記為 uninstalled，避免之後 registry 載入時尋找已刪除的檔案。

※ 需在實機（有既有橋接安裝）驗證資料保存；全新安裝環境無橋接時本檔為 no-op。
"""
import logging

_logger = logging.getLogger(__name__)

BRIDGE = 'dobtor_mail_activity_timesheet'
CORE = 'dobtor_mail_activity'


def migrate(cr, version):
    _migrate_requirement_7(cr)
    _merge_timesheet_bridge(cr)


def _migrate_requirement_7(cr):
    """需求七：移除「預設筆記本」設計。

    1) DROP 官方 CHECK(res_id NOT NULL) 約束，否則後續把 res_id 設 NULL 會違反。
       （Odoo 載入時會依本模組中和後的 _sql_constraints 重建為 CHECK(1=1)。）
    2) 解除既有「指向使用者預設筆記」的待辦關聯（res 與 note_id 皆清空）。
       default_activity_note_id 欄位於本升級移除，故於 pre 階段（欄位仍在）擷取。
    """
    cr.execute(
        "ALTER TABLE mail_activity "
        "DROP CONSTRAINT IF EXISTS mail_activity_check_res_id_is_set"
    )

    # 官方 res_id / res_model_id 於 base 為 required=True → DB 欄位帶 NOT NULL。
    # 本模組覆寫為 required=False，但移除 NOT NULL 的 schema 同步發生在「載入模型」
    # 階段，晚於本 pre-migration。若此處先把 res 設 NULL 會違反尚未移除的 NOT NULL，
    # 故先手動移除（ALTER ... DROP NOT NULL 對已可空欄位為 no-op，安全冪等）。
    cr.execute("ALTER TABLE mail_activity ALTER COLUMN res_model_id DROP NOT NULL")
    cr.execute("ALTER TABLE mail_activity ALTER COLUMN res_id DROP NOT NULL")

    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_users' AND column_name = 'default_activity_note_id'
    """)
    if not cr.fetchone():
        return

    cr.execute(
        "SELECT default_activity_note_id FROM res_users "
        "WHERE default_activity_note_id IS NOT NULL"
    )
    note_ids = tuple({r[0] for r in cr.fetchall()})
    if not note_ids:
        return

    cr.execute("""
        UPDATE mail_activity
        SET res_model_id = NULL, res_model = NULL, res_id = NULL, note_id = NULL
        WHERE note_id IN %(nids)s
           OR (res_model = 'note.note' AND res_id IN %(nids)s)
    """, {'nids': note_ids})
    _logger.info('需求七：解除 %s 筆待辦與預設筆記的關聯（改為獨立待辦）。', cr.rowcount)


def _merge_timesheet_bridge(cr):
    # 橋接未安裝（全新環境）→ 無事可做
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (BRIDGE,))
    if not cr.fetchone():
        _logger.info('%s not present; merge pre-migration is a no-op.', BRIDGE)
        return

    # 1) 把「持久欄位」的資產歸屬由橋接轉核心（避免卸載時 CASCADE 掉欄位資料）。
    #    僅轉移核心尚未擁有同名 xmlid 者，避免 (module,name) 唯一鍵衝突。
    cr.execute("""
        UPDATE ir_model_data d
        SET module = %(core)s
        WHERE d.module = %(bridge)s
          AND d.model = 'ir.model.fields'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data c
              WHERE c.module = %(core)s
                AND c.model = 'ir.model.fields'
                AND c.name = d.name
          )
    """, {'core': CORE, 'bridge': BRIDGE})
    reassigned = cr.rowcount
    _logger.info('Merge: reassigned %s field xmlids %s -> %s', reassigned, BRIDGE, CORE)

    # 2) 移除橋接自身的 view/action/rule/access xmlid（核心已重新定義等價物件），
    #    使卸載時不會 CASCADE 到已改歸核心的共用欄位。
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = %(bridge)s
          AND model IN (
              'ir.ui.view', 'ir.actions.act_window', 'ir.actions.server',
              'ir.rule', 'ir.model.access', 'ir.ui.menu'
          )
    """, {'bridge': BRIDGE})

    # 3) 標記橋接為 uninstalled（其檔案將被刪除）。
    cr.execute("""
        UPDATE ir_module_module SET state = 'uninstalled'
        WHERE name = %s AND state IN ('installed', 'to upgrade', 'to remove')
    """, (BRIDGE,))
    _logger.info('Merge: marked %s as uninstalled.', BRIDGE)
