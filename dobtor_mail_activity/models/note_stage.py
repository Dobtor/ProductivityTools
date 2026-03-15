# -*- coding: utf-8 -*-

from odoo import api, fields, models


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

    # ===== 預設階段定義 =====
    DEFAULT_STAGES = [
        {'name': '暫記', 'sequence': 1, 'fold': False},
        {'name': '規劃中', 'sequence': 5, 'fold': False},
        {'name': '定稿發佈', 'sequence': 10, 'fold': False},
    ]

    @api.model
    def _ensure_user_stages(self, user_id=None):
        """確保使用者有預設階段，若無則自動建立"""
        uid = user_id or self.env.uid
        existing = self.search([('user_id', '=', uid)], limit=1)
        if existing:
            return
        self.sudo().create([
            {**stage, 'user_id': uid}
            for stage in self.DEFAULT_STAGES
        ])
