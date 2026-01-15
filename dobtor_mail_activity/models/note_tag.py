# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NoteTag(models.Model):
    """筆記標籤 - 支援階層式分類

    提供階層式的標籤管理，支援父子關係，用於筆記的分類與篩選。
    使用 _parent_store 實現高效的階層查詢。
    """
    _name = 'note.tag'
    _description = '筆記標籤'
    _parent_store = True
    _order = 'parent_path, name'

    # ===== 基本欄位 =====
    name = fields.Char(
        string='標籤名稱',
        required=True,
        translate=True,
    )
    color = fields.Integer(
        string='顏色索引',
        default=0,
    )
    active = fields.Boolean(
        string='啟用',
        default=True,
        help="設為非啟用可隱藏此標籤，而不需刪除它。",
    )

    # ===== 階層欄位 =====
    parent_id = fields.Many2one(
        'note.tag',
        string='父類別',
        index=True,
        ondelete='cascade',
    )
    child_ids = fields.One2many(
        'note.tag',
        'parent_id',
        string='子類別',
    )
    parent_path = fields.Char(
        index=True,
        unaccent=False,
    )

    # ===== SQL 約束 =====
    _sql_constraints = [
        (
            'name_parent_uniq',
            'unique (name, parent_id)',
            "同一類別下標籤名稱不可重複！"
        ),
    ]

    # ===== 約束方法 =====
    @api.constrains('parent_id')
    def _check_parent_id(self):
        """檢查父標籤是否造成循環"""
        if not self._check_recursion():
            raise ValidationError(_('不可建立循環的標籤層級。'))

    # ===== 顯示方法 =====
    def _compute_display_name(self):
        """計算顯示名稱，包含完整的標籤路徑

        例如：父類別 / 子類別
        可透過 context 中的 note_tag_display='short' 顯示短名稱
        """
        if self._context.get('note_tag_display') == 'short':
            return super()._compute_display_name()

        for tag in self:
            names = []
            current = tag
            while current:
                names.append(current.name)
                current = current.parent_id
            tag.display_name = ' / '.join(reversed(names))

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        """支援搜尋完整路徑或單一名稱"""
        domain = domain or []
        if name:
            # 取得路徑中的最後一個名稱進行搜尋
            name = name.split(' / ')[-1]
            domain = [('name', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)
