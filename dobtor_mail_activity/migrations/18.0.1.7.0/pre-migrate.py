# -*- coding: utf-8 -*-
"""待辦合併功能的 pre-migration。

背景：`mail.activity.note_id`（來源參考，M2O）維持不變，但新增
`note_ids`（引用筆記，M2M）—— 合併待辦時要把被併入者的筆記併進主待辦，
單一 M2O 放不下。

不變式：note_id 若有值，必定是 note_ids 的成員（由 create/write 維護）。
既有資料需要在這裡補上這層對應，否則升級後所有筆記的待辦計數、
「Related Activities」分頁與編輯器內嵌清單都會突然變成 0。

放在 pre 階段的原因：此時新欄位尚未建立，我們自己建 rel table 並灌資料，
Odoo 隨後載入 note_ids 欄位時會沿用同一張表（表名／欄名完全一致）。
若放到 post，Odoo 會先建空表，仍可灌 —— 但期間任何 compute 都會讀到 0。

本檔冪等：重跑不會產生重複列（rel table 有唯一鍵，且用 ON CONFLICT）。
"""
import logging

_logger = logging.getLogger(__name__)

REL_TABLE = 'mail_activity_note_rel'


def migrate(cr, version):
    if not version:
        # 全新安裝不會走 migration；保險起見仍為 no-op
        return
    _create_note_rel(cr)
    _seed_note_rel_from_note_id(cr)


def _create_note_rel(cr):
    """先建出與 note_ids 欄位定義完全一致的 rel table。

    欄名必須與 fields.Many2many('note.note', 'mail_activity_note_rel',
    'activity_id', 'note_id') 相符，Odoo 載入時才會沿用而非另建。
    """
    cr.execute("SELECT to_regclass(%s)", (REL_TABLE,))
    if cr.fetchone()[0]:
        return
    cr.execute(f"""
        CREATE TABLE "{REL_TABLE}" (
            "activity_id" INTEGER NOT NULL
                REFERENCES "mail_activity"(id) ON DELETE CASCADE,
            "note_id" INTEGER NOT NULL
                REFERENCES "note_note"(id) ON DELETE CASCADE,
            PRIMARY KEY("activity_id", "note_id")
        )
    """)
    cr.execute(f'CREATE INDEX "{REL_TABLE}_note_id_idx" ON "{REL_TABLE}" ("note_id")')
    _logger.info('待辦合併：已建立 %s。', REL_TABLE)


def _seed_note_rel_from_note_id(cr):
    """把既有的 note_id 灌進 rel table，維持「來源必為引用成員」的不變式。"""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'mail_activity' AND column_name = 'note_id'
    """)
    if not cr.fetchone():
        _logger.info('待辦合併：mail_activity.note_id 不存在，略過灌資料。')
        return

    cr.execute(f"""
        INSERT INTO "{REL_TABLE}" ("activity_id", "note_id")
        SELECT id, note_id FROM "mail_activity" WHERE note_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    _logger.info('待辦合併：已由 note_id 灌入 %s 筆筆記引用。', cr.rowcount)
