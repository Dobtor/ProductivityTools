# -*- coding: utf-8 -*-
"""note.note.stage_id 改為依「擁有者」計算後，重算既有筆記。

舊版以建立者（env.uid）計算並 store：cron（OdooBot）替使用者建立的週筆記、
或他人代建的筆記，存的是建立者的階段 → 擁有者打開「個人筆記」Access Error。
depends 新增 user_id 不會觸發既有列重算，這裡手動排入並 flush。冪等。
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    # 18.0.3.0.0 起 note.note 由 dobtor_meeting_minutes 定義；跨版升級時本模組
    # 載入當下 registry 沒有它 → 由 dobtor_meeting_minutes 的 18.0.3.0.0 migration
    # 與 post-init hook（note.note._recompute_owner_stages）補做。
    if 'note.note' not in env:
        return
    Note = env['note.note']
    cr.execute("""
        SELECT n.id
          FROM note_note n
          LEFT JOIN note_stage s ON s.id = n.stage_id
         WHERE n.user_id IS NOT NULL
           AND (s.id IS NULL OR s.user_id IS DISTINCT FROM n.user_id)
    """)
    notes = Note.browse([r[0] for r in cr.fetchall()])
    if not notes:
        return
    env.add_to_compute(Note._fields['stage_id'], notes)
    notes.flush_recordset(['stage_id'])
    _logger.info('note.note: recomputed owner stage for %d notes', len(notes))
