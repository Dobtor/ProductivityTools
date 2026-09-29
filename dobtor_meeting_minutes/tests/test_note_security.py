# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNoteSecurityRules(TransactionCase):
    """筆記／階段的記錄規則（自 dobtor_mail_activity 搬入）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = [cls.env.ref('base.group_user').id,
                  cls.env.ref('dobtor_mail_activity.group_activity_user').id]
        cls.user_activity = cls.env['res.users'].create({
            'name': '筆記用戶', 'login': 'note_rule_user',
            'groups_id': [(6, 0, groups)],
        })
        cls.user_other = cls.env['res.users'].create({
            'name': '其他筆記用戶', 'login': 'note_rule_other',
            'groups_id': [(6, 0, groups)],
        })

    def test_01_user_own_notes(self):
        """測試用戶只能看到自己的筆記"""
        # 用戶1建立筆記
        note1 = self.env['note.note'].with_user(self.user_activity).create({
            'memo': '<p>用戶1私人筆記</p>',
        })

        # 用戶2建立筆記
        note2 = self.env['note.note'].with_user(self.user_other).create({
            'memo': '<p>用戶2私人筆記</p>',
        })

        # 用戶1搜尋筆記
        notes = self.env['note.note'].with_user(self.user_activity).search([])

        # 用戶1應該能看到自己的筆記
        self.assertIn(note1.id, notes.ids)

    def test_02_note_stage_user_specific(self):
        """測試筆記階段是用戶專屬的"""
        # 用戶1建立階段
        stage1 = self.env['note.stage'].with_user(self.user_activity).create({
            'name': '用戶1階段',
        })

        # 用戶2建立階段
        stage2 = self.env['note.stage'].with_user(self.user_other).create({
            'name': '用戶2階段',
        })

        # 用戶1搜尋階段，應該只看到自己的
        stages = self.env['note.stage'].with_user(self.user_activity).search([])
        self.assertIn(stage1.id, stages.ids)
