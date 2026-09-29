# -*- coding: utf-8 -*-

from . import models
from . import controllers
from . import wizards


def _create_default_note_stages_for_existing_users(env):
    """Post-init hook: Create default note stages for existing users

    This ensures all existing users get default note stages when the module
    is installed or upgraded. Uses batch creation for efficiency.
    """
    # Get all internal users
    users = env['res.users'].search([
        ('share', '=', False),  # Only internal users
    ])

    NoteStage = env['note.stage']
    # 與 data/note_stage_data.xml（admin 預設階段）一致：暫記 / 規劃中 / 定稿發佈
    default_stages = [
        {'name': '暫記', 'sequence': 1, 'fold': False},
        {'name': '規劃中', 'sequence': 5, 'fold': False},
        {'name': '定稿發佈', 'sequence': 10, 'fold': False},
    ]

    # Batch query users who already have stages
    env.cr.execute(
        "SELECT DISTINCT user_id FROM note_stage WHERE user_id IN %s",
        [tuple(users.ids)] if users.ids else [(0,)]
    )
    users_with_stages = {row[0] for row in env.cr.fetchall()}

    # Batch collect all vals
    vals_list = []
    for user in users:
        if user.id in users_with_stages:
            continue
        for stage_vals in default_stages:
            vals_list.append({
                **stage_vals,
                'user_id': user.id,
            })

    if vals_list:
        NoteStage.create(vals_list)


def _post_init_hook(env):
    """Post-init hook."""
    _create_default_note_stages_for_existing_users(env)
    # 自 dobtor_mail_activity 升級而首次安裝本模組時，既有筆記的階段也要修正
    env['note.note']._recompute_owner_stages()
    env['note.note']._recompute_calendar_note_counts()


# 既有資料庫（筆記原本在 dobtor_mail_activity）安裝本模組時，資料檔裡的
# noupdate 記錄在 init 模式下「一律建立」。若該筆資料已存在卻沒有 XML ID
# （例：管理者刪過再由舊版 create_default_configs 重建、或 XML ID 遺失），
# 就會重建一筆 → mail.activity.transfer.config 的 unique(model_id) 直接讓
# 安裝失敗（test-flyingway 2026-09-29 實際發生）。安裝前先把既有記錄認領
# 到本模組的 XML ID 上。此時本模組的模型尚未載入，只能用 SQL。
_ADOPT_STAGES = [
    # (xmlid, sequence, name)：data/note_stage_data.xml 的 admin 預設階段
    ('note_stage_draft', 1, '暫記'),
    ('note_stage_planning', 5, '規劃中'),
    ('note_stage_published', 10, '定稿發佈'),
]


def _adopt_xmlid(cr, name, model, res_id):
    """讓 dobtor_meeting_minutes.<name> 指向 res_id（不存在就建立、指錯就改正）。"""
    cr.execute("""
        SELECT id, res_id FROM ir_model_data
         WHERE module = 'dobtor_meeting_minutes' AND name = %s
    """, (name,))
    row = cr.fetchone()
    if not row:
        cr.execute("""
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
            VALUES ('dobtor_meeting_minutes', %s, %s, %s, true)
        """, (name, model, res_id))
    elif row[1] != res_id:
        cr.execute(f"SELECT 1 FROM {model.replace('.', '_')} WHERE id = %s", (row[1],))
        if not cr.fetchone():  # 指向已刪除的記錄 → 改指既有的那筆
            cr.execute("UPDATE ir_model_data SET res_id = %s, model = %s WHERE id = %s",
                       (res_id, model, row[0]))


def _pre_init_hook(env):
    cr = env.cr
    cr.execute("SELECT to_regclass('mail_activity_transfer_config'), to_regclass('note_stage')")
    has_config, has_stage = cr.fetchone()
    if has_config:
        cr.execute("""
            SELECT c.id FROM mail_activity_transfer_config c
              JOIN ir_model m ON m.id = c.model_id
             WHERE m.model = 'note.note'
             ORDER BY c.id LIMIT 1
        """)
        row = cr.fetchone()
        if row:
            _adopt_xmlid(cr, 'transfer_config_note', 'mail.activity.transfer.config', row[0])
    if has_stage:
        cr.execute("SELECT res_id FROM ir_model_data WHERE module = 'base' AND name = 'user_admin'")
        admin = cr.fetchone()
        if admin:
            for xmlid, sequence, name in _ADOPT_STAGES:
                cr.execute("""
                    SELECT id FROM note_stage
                     WHERE user_id = %s AND sequence = %s AND name->>'en_US' = %s
                     ORDER BY id LIMIT 1
                """, (admin[0], sequence, name))
                row = cr.fetchone()
                if row:
                    _adopt_xmlid(cr, xmlid, 'note.stage', row[0])
