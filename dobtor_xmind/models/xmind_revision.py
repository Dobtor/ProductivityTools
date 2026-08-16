# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api


class XMindRevision(models.Model):
    _name = 'xmind.revision'
    _description = 'Mind Map Workbook Revision'
    _order = 'create_date desc'

    workbook_id = fields.Many2one(
        'xmind.workbook', string='Workbook',
        ondelete='cascade', required=True, index=True,
    )
    # 快照存的是「當時編輯的那一張分頁」的樹，不是整本工作簿 —— 還原時必須寫回
    # 同一張，否則會用某張分頁的內容覆蓋第一張（與 save_mindmap_data 少了
    # sheet_id 時同一類的資料遺失）。舊資料沒有這個值，還原時退回第一張，
    # 與加上本欄位之前的行為一致。
    sheet_id = fields.Many2one(
        'xmind.sheet', string='Sheet',
        ondelete='cascade', index=True,
    )
    name = fields.Char('Label', compute='_compute_name', store=True)
    snapshot = fields.Text('Snapshot (JSON)', required=True)
    user_id = fields.Many2one(
        'res.users', string='Saved By',
        default=lambda self: self.env.user,
    )
    topic_count = fields.Integer('Topics')
    is_auto = fields.Boolean('Auto-save', default=False)

    @api.depends('create_date', 'is_auto', 'sheet_id')
    def _compute_name(self):
        for rec in self:
            prefix = 'Auto' if rec.is_auto else 'Manual'
            ts = rec.create_date.strftime('%Y-%m-%d %H:%M') if rec.create_date else ''
            # 多分頁時標上分頁名，否則版本清單裡的項目彼此無法分辨
            sheet = f' · {rec.sheet_id.name}' if rec.sheet_id else ''
            rec.name = f'{prefix} — {ts}{sheet}'

    def action_restore(self):
        """Restore the snapshot back into the sheet it was taken from."""
        self.ensure_one()
        data = json.loads(self.snapshot)
        # sheet_id 為空 = 加上該欄位之前建立的舊版本 → 沿用舊行為（第一張）
        self.workbook_id.save_mindmap_data(data, sheet_id=self.sheet_id.id or None)
        return True
