# -*- coding: utf-8 -*-

from odoo import api, models, _


class ResUsers(models.Model):
    """新使用者自動建立預設筆記階段（自 dobtor_mail_activity 搬入）。"""
    _inherit = 'res.users'

    # ========== CRUD Methods ==========

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-create default note stages for new users"""
        users = super().create(vals_list)
        users._create_default_note_stages()
        return users

    def _create_default_note_stages(self):
        """Create default note stages for users

        Creates 4 default stages for each user:
        - Notes (筆記)
        - Meeting Minutes (會議記錄)
        - Manuals (說明書)
        - References (參考資料)
        """
        NoteStage = self.env['note.stage'].sudo()

        default_stages = [
            {'name': _('Notes'), 'sequence': 1, 'fold': False},
            {'name': _('Meeting Minutes'), 'sequence': 5, 'fold': False},
            {'name': _('Manuals'), 'sequence': 10, 'fold': False},
            {'name': _('References'), 'sequence': 50, 'fold': True},
        ]

        # 批次查詢已有 stage 的用戶
        existing_data = NoteStage._read_group(
            [('user_id', 'in', self.ids)],
            ['user_id'],
            ['__count'],
        )
        users_with_stages = {user.id for user, _count in existing_data}

        # 批次建立所有缺少 stage 的用戶的預設 stages
        vals_list = []
        for user in self:
            if user.id in users_with_stages:
                continue
            for stage_vals in default_stages:
                vals_list.append({
                    **stage_vals,
                    'user_id': user.id,
                })

        if vals_list:
            NoteStage.create(vals_list)
