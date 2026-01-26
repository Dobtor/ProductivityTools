# -*- coding: utf-8 -*-

import uuid
from odoo import api, fields, models, _


class NoteSignature(models.Model):
    """會議記錄簽名記錄

    每位指定簽名者會有一筆簽名記錄，包含：
    - 簽名者資訊
    - 簽名圖片
    - 獨立的 access_token 供 Portal 驗證
    """
    _name = 'note.signature'
    _description = 'Meeting Minutes Signature'
    _order = 'create_date asc'

    # ===== 關聯欄位 =====
    note_id = fields.Many2one(
        'note.note',
        string='Meeting Minutes',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Signer',
        required=True,
        index=True,
    )

    # ===== 簽名欄位 =====
    signature = fields.Image(
        string='Signature',
        max_width=1024,
        max_height=1024,
        copy=False,
    )
    signed_by = fields.Char(
        string='Signed By',
        help='Name entered by the signer during signing',
    )
    signed_on = fields.Datetime(
        string='Signed On',
        readonly=True,
    )

    # ===== 存取控制 =====
    access_token = fields.Char(
        string='Access Token',
        copy=False,
        index=True,
        help='Unique token for portal access without login',
    )

    # ===== 計算欄位 =====
    is_signed = fields.Boolean(
        string='Is Signed',
        compute='_compute_is_signed',
        store=True,
    )

    # ===== 計算方法 =====
    @api.depends('signature')
    def _compute_is_signed(self):
        """判斷是否已簽名"""
        for record in self:
            record.is_signed = bool(record.signature)

    # ===== CRUD 方法 =====
    @api.model_create_multi
    def create(self, vals_list):
        """建立簽名記錄時自動產生 access_token"""
        for vals in vals_list:
            if not vals.get('access_token'):
                vals['access_token'] = str(uuid.uuid4())
        return super().create(vals_list)

    # ===== 業務方法 =====
    def action_sign(self, name, signature):
        """執行簽名

        Args:
            name: 簽名者輸入的姓名
            signature: Base64 編碼的簽名圖片

        Returns:
            bool: 簽名是否成功
        """
        self.ensure_one()
        if self.is_signed:
            return False

        self.write({
            'signed_by': name,
            'signature': signature,
            'signed_on': fields.Datetime.now(),
        })

        # 更新會議記錄狀態
        self.note_id._check_all_signed()
        return True

    def _get_portal_url(self):
        """取得 Portal 簽名連結"""
        self.ensure_one()
        return f'{self.note_id.access_url}?access_token={self.note_id.access_token}&signature_id={self.id}&signature_token={self.access_token}'
