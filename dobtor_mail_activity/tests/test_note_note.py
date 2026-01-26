# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNoteNote(TransactionCase):
    """測試 note.note 模型"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

        # 建立測試階段
        cls.stage = cls.env['note.stage'].create({
            'name': '測試階段',
            'user_id': cls.user.id,
            'sequence': 1,
        })

        # 建立測試標籤
        cls.tag = cls.env['note.tag'].create({
            'name': '測試標籤',
        })

    def test_01_create_note(self):
        """測試建立筆記"""
        note = self.env['note.note'].create({
            'memo': '<p>這是測試筆記內容</p>',
            'user_id': self.user.id,
        })

        self.assertTrue(note.id)
        self.assertTrue(note.active)

    def test_02_note_name_compute(self):
        """測試筆記名稱計算"""
        note = self.env['note.note'].create({
            'memo': '<p>第一行是標題</p><p>第二行是內容</p>',
            'user_id': self.user.id,
        })

        self.assertEqual(note.name, '第一行是標題')

    def test_03_note_stage(self):
        """測試筆記階段"""
        note = self.env['note.note'].with_user(self.user).create({
            'memo': '<p>階段測試筆記</p>',
            'stage_id': self.stage.id,
        })

        self.assertEqual(note.stage_id.id, self.stage.id)

    def test_04_note_tags(self):
        """測試筆記標籤"""
        tag2 = self.env['note.tag'].create({'name': '標籤2'})

        note = self.env['note.note'].create({
            'memo': '<p>標籤測試</p>',
            'user_id': self.user.id,
            'tag_ids': [(6, 0, [self.tag.id, tag2.id])],
        })

        self.assertEqual(len(note.tag_ids), 2)
        self.assertEqual(note.main_tag_id.id, self.tag.id)

    def test_05_note_archive(self):
        """測試筆記封存"""
        note = self.env['note.note'].create({
            'memo': '<p>待封存筆記</p>',
            'user_id': self.user.id,
        })

        note.write({'active': False})
        self.assertFalse(note.active)

    def test_06_note_close_open(self):
        """測試筆記開啟/關閉"""
        note = self.env['note.note'].create({
            'memo': '<p>開關測試</p>',
            'user_id': self.user.id,
            'open': True,
        })

        # 關閉筆記
        note.action_close()
        self.assertFalse(note.open)
        self.assertTrue(note.date_done)

        # 重新開啟
        note.action_open()
        self.assertTrue(note.open)
        self.assertFalse(note.date_done)

    def test_07_note_activity_relation(self):
        """測試筆記與待辦的關聯"""
        note = self.env['note.note'].create({
            'memo': '<p>關聯測試</p>',
            'user_id': self.user.id,
        })

        activity_type = self.env['mail.activity.type'].search([], limit=1)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].create({
                'name': '測試類型',
                'category': 'default',
            })

        # 建立關聯待辦
        activity = self.env['mail.activity'].create({
            'summary': '筆記關聯待辦',
            'activity_type_id': activity_type.id,
            'res_model_id': self.env['ir.model']._get('note.note').id,
            'res_id': note.id,
            'date_deadline': '2026-01-15',
            'note_id': note.id,
        })

        self.assertGreaterEqual(note.note_activity_count, 1)


@tagged('post_install', '-at_install')
class TestNoteStage(TransactionCase):
    """測試 note.stage 模型"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.ref('base.user_demo')

    def test_01_create_stage(self):
        """測試建立階段"""
        stage = self.env['note.stage'].create({
            'name': '新階段',
            'user_id': self.user.id,
            'sequence': 10,
        })

        self.assertTrue(stage.id)
        self.assertEqual(stage.name, '新階段')

    def test_02_stage_fold(self):
        """測試階段摺疊設定"""
        stage = self.env['note.stage'].create({
            'name': '摺疊階段',
            'user_id': self.user.id,
            'fold': True,
        })

        self.assertTrue(stage.fold)


@tagged('post_install', '-at_install')
class TestNoteTag(TransactionCase):
    """測試 note.tag 模型（階層式）"""

    def test_01_create_tag(self):
        """測試建立標籤"""
        tag = self.env['note.tag'].create({
            'name': '父標籤',
        })

        self.assertTrue(tag.id)

    def test_02_tag_hierarchy(self):
        """測試標籤階層"""
        parent_tag = self.env['note.tag'].create({
            'name': '父標籤',
        })

        child_tag = self.env['note.tag'].create({
            'name': '子標籤',
            'parent_id': parent_tag.id,
        })

        self.assertEqual(child_tag.parent_id.id, parent_tag.id)
