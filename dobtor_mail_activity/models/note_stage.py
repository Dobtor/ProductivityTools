# -*- coding: utf-8 -*-

from odoo import fields, models


class NoteStage(models.Model):
    """筆記階段 - 用於看板視圖的階段管理

    每個用戶可以有自己的階段設定，支援個人化的筆記管理流程。
    """
    _name = 'note.stage'
    _description = '筆記階段'
    _order = 'sequence, id'

    # ===== 基本欄位 =====
    name = fields.Char(
        string='階段名稱',
        required=True,
        translate=True,
    )
    sequence = fields.Integer(
        string='順序',
        default=1,
        help="用於排序階段的順序。",
    )
    user_id = fields.Many2one(
        'res.users',
        string='擁有者',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env.uid,
        help="階段的擁有者，每個用戶可以有自己的階段設定。",
    )
    fold = fields.Boolean(
        string='預設收合',
        default=False,
        help="勾選後，此階段在看板視圖中預設會收合。",
    )
