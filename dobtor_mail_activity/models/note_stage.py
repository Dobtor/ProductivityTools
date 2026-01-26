# -*- coding: utf-8 -*-

from odoo import fields, models


class NoteStage(models.Model):
    """筆記階段 - 用於看板視圖的階段管理

    每個用戶可以有自己的階段設定，支援個人化的筆記管理流程。
    """
    _name = 'note.stage'
    _description = 'Note Stage'
    _order = 'sequence, id'

    # ===== 基本欄位 =====
    name = fields.Char(
        string='Stage Name',
        required=True,
        translate=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=1,
        help="Used to sort the stages.",
    )
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env.uid,
        help="Owner of the stage, each user can have their own stage settings.",
    )
    fold = fields.Boolean(
        string='Folded by Default',
        default=False,
        help="When checked, this stage will be folded by default in kanban view.",
    )
