# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestActivityMerge(TransactionCase):
    """待辦合併：欄位合併規則、膠囊轉向、解除合併、權限、刪除主待辦。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Activity = cls.env['mail.activity']
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': 'Merge Test Type',
            'category': 'default',
        })
        cls.note_a = cls.env['note.note'].create({'memo': '<p>Note A</p>'})
        cls.note_b = cls.env['note.note'].create({'memo': '<p>Note B</p>'})
        cls.note_model_id = cls.env['ir.model']._get('note.note').id

    def _make(self, summary, **vals):
        base = {
            'summary': summary,
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.note_model_id,
            'res_id': self.note_a.id,
            'date_deadline': date.today(),
            'user_id': self.env.user.id,
        }
        base.update(vals)
        return self.Activity.create(base)

    # ===== 不變式：note_id 必為 note_ids 成員 =====

    def test_01_note_id_joins_note_ids_on_create(self):
        act = self._make('with source note', note_id=self.note_a.id)
        self.assertIn(self.note_a, act.note_ids,
                      'create 應自動把 note_id 併入 note_ids')

    def test_02_note_id_joins_note_ids_on_write(self):
        act = self._make('no note yet')
        act.write({'note_id': self.note_b.id})
        self.assertIn(self.note_b, act.note_ids,
                      'write 應自動把 note_id 併入 note_ids')

    def test_03_constraint_rejects_broken_invariant(self):
        act = self._make('constrained', note_id=self.note_a.id)
        with self.assertRaises(ValidationError):
            # 直接清空 note_ids 會讓 note_id 落單
            act.write({'note_ids': [(5, 0, 0)]})

    # ===== 合併規則 =====

    def test_04_merge_unions_notes(self):
        master = self._make('master', note_id=self.note_a.id)
        source = self._make('source', note_id=self.note_b.id)
        (master | source).action_merge(master)

        self.assertIn(self.note_a, master.note_ids)
        self.assertIn(self.note_b, master.note_ids,
                      '被併入者的筆記應併進主待辦')
        self.assertEqual(source.note_ids, self.note_b,
                         '來源自己的 note_ids 保留不動，解除合併才回得去')

    def test_05_merge_archives_source_and_sets_pointer(self):
        master = self._make('master')
        source = self._make('source')
        (master | source).action_merge(master)

        self.assertFalse(source.active)
        self.assertEqual(source.merged_into_id, master)
        self.assertEqual(source.activity_status, 'merged')
        self.assertTrue(master.active)
        self.assertEqual(master.activity_status, 'active')
        self.assertEqual(master.merged_count, 1)

    def test_06_estimated_hours_keeps_master(self):
        """已定案：預估工時取主待辦，不加總。"""
        master = self._make('master', estimated_hours=3.0)
        source = self._make('source', estimated_hours=5.0)
        (master | source).action_merge(master)
        self.assertEqual(master.estimated_hours, 3.0)

    def test_07_deadline_urgency_importance_take_worst(self):
        """已定案：截止日/緊急/重要取最嚴重。"""
        later = date.today() + timedelta(days=10)
        earlier = date.today() + timedelta(days=2)
        master = self._make('master', date_deadline=later,
                            urgency='flexible', importance='normal')
        source = self._make('source', date_deadline=earlier,
                            urgency='urgent', importance='important')
        (master | source).action_merge(master)

        self.assertEqual(master.date_deadline, earlier, '應取最早的截止日')
        self.assertEqual(master.urgency, 'urgent', '應取最嚴重的緊急程度')
        self.assertEqual(master.importance, 'important', '應取最嚴重的重要性')

    def test_08_master_worse_values_are_kept(self):
        """主待辦本身已是最嚴重時不應被調鬆。"""
        master = self._make('master', urgency='urgent', importance='important',
                            date_deadline=date.today())
        source = self._make('source', urgency='flexible', importance='normal',
                            date_deadline=date.today() + timedelta(days=5))
        (master | source).action_merge(master)
        self.assertEqual(master.urgency, 'urgent')
        self.assertEqual(master.importance, 'important')
        self.assertEqual(master.date_deadline, date.today())

    def test_09_notes_and_feedback_are_appended(self):
        master = self._make('master', note='<p>master note</p>')
        source = self._make('source', note='<p>source note</p>')
        source.feedback = 'source feedback'
        (master | source).action_merge(master)

        self.assertIn('master note', master.note)
        self.assertIn('source note', master.note, '待辦註記應附加而非覆蓋')
        self.assertIn('source feedback', master.feedback or '')

    # ===== 膠囊轉向 =====

    def test_10_chip_data_redirects_to_master(self):
        master = self._make('master')
        source = self._make('source')
        (master | source).action_merge(master)

        data = self.Activity.get_chip_data([source.id])
        entry = data.get(str(source.id))
        self.assertTrue(entry, '被併入者仍應取得膠囊資料（不是消失）')
        self.assertEqual(entry['id'], master.id, '膠囊應解析到主待辦')
        self.assertEqual(entry['redirected_from'], source.id)
        self.assertEqual(entry['summary'], 'master')

    def test_11_chip_data_follows_merge_chain(self):
        """A→B→C：膠囊應一路解析到最終主待辦。"""
        a = self._make('A')
        b = self._make('B')
        c = self._make('C')
        (a | b).action_merge(b)     # A 併入 B
        (b | c).action_merge(c)     # B 併入 C

        data = self.Activity.get_chip_data([a.id])
        self.assertEqual(data[str(a.id)]['id'], c.id)

    def test_12_chip_data_untouched_for_normal_activity(self):
        act = self._make('plain')
        entry = self.Activity.get_chip_data([act.id])[str(act.id)]
        self.assertEqual(entry['id'], act.id)
        self.assertFalse(entry['redirected_from'])

    def test_13_chips_in_note_memo_are_rewritten(self):
        master = self._make('master')
        source = self._make('source', note_id=self.note_b.id)
        self.note_b.memo = (
            '<p>before<span data-embedded-props=\'{"activityId": %d}\' '
            'data-embedded="activityChip"></span>after</p>' % source.id
        )
        (master | source).action_merge(master)

        self.assertIn('"activityId": %d' % master.id, self.note_b.memo,
                      '筆記內的膠囊應就地改寫成主待辦')
        self.assertIn('before', self.note_b.memo)
        self.assertIn('after', self.note_b.memo, '其餘內容應保留')

    # ===== 解除合併 =====

    def test_14_unmerge_restores(self):
        master = self._make('master')
        source = self._make('source')
        (master | source).action_merge(master)
        source.action_unmerge()

        self.assertTrue(source.active)
        self.assertFalse(source.merged_into_id)
        self.assertEqual(source.activity_status, 'active')
        # 膠囊指回自己
        entry = self.Activity.get_chip_data([source.id])[str(source.id)]
        self.assertEqual(entry['id'], source.id)

    def test_15_restore_is_blocked_for_merged(self):
        master = self._make('master')
        source = self._make('source')
        (master | source).action_merge(master)
        with self.assertRaises(UserError):
            source.action_restore()

    # ===== 刪除主待辦 =====

    def test_16_deleting_master_unmerges_children(self):
        """merged_into_id 是 ondelete='set null'，直接刪會讓空殼卡在
        active=False + 無指標的矛盾狀態（狀態算成 active 卻在封存區）。"""
        master = self._make('master')
        source = self._make('source')
        (master | source).action_merge(master)

        master.unlink()

        self.assertTrue(source.exists())
        self.assertTrue(source.active, '主待辦被刪後，空殼應回到可用狀態')
        self.assertFalse(source.merged_into_id)
        self.assertEqual(source.activity_status, 'active')

    def test_17_archived_without_reason_is_not_active(self):
        """防禦分支：已封存但無 done/cancel/merge 來由 → 不可算成 active。"""
        act = self._make('weird')
        act.write({'active': False})
        self.assertEqual(act.activity_status, 'cancelled')

    # ===== 前置條件 =====

    def test_18_cannot_merge_single(self):
        master = self._make('lonely')
        with self.assertRaises(UserError):
            master.action_merge(master)

    def test_19_cannot_merge_archived_source(self):
        master = self._make('master')
        source = self._make('source')
        source.write({'active': False})
        with self.assertRaises(UserError):
            (master | source).action_merge(master)

    def test_20_cannot_merge_into_archived_master(self):
        master = self._make('master')
        source = self._make('source')
        master.write({'active': False})
        with self.assertRaises(UserError):
            (master | source).action_merge(master)


@tagged('post_install', '-at_install')
class TestActivityMergeAccess(TransactionCase):
    """合併權限：對被併入者必須是建立者或被指派者（任一）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': 'Access Test Type', 'category': 'default',
        })
        cls.note = cls.env['note.note'].create({'memo': '<p>n</p>'})
        cls.note_model_id = cls.env['ir.model']._get('note.note').id
        cls.alice = cls.env['res.users'].create({
            'name': 'Alice', 'login': 'merge_alice',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.bob = cls.env['res.users'].create({
            'name': 'Bob', 'login': 'merge_bob',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _make_as(self, user, summary, assignee=None):
        return self.env['mail.activity'].with_user(user).create({
            'summary': summary,
            'activity_type_id': self.activity_type.id,
            'res_model_id': self.note_model_id,
            'res_id': self.note.id,
            'date_deadline': date.today(),
            'user_id': (assignee or user).id,
        })

    def test_01_creator_can_merge(self):
        master = self._make_as(self.alice, 'a1')
        source = self._make_as(self.alice, 'a2')
        (master | source).with_user(self.alice).action_merge(master)
        self.assertEqual(source.merged_into_id, master)

    def test_02_assignee_can_merge(self):
        """Bob 建立、指派給 Alice → Alice 是被指派者，應可合併。"""
        master = self._make_as(self.alice, 'a1')
        source = self._make_as(self.bob, 'b1', assignee=self.alice)
        (master | source).with_user(self.alice).action_merge(master)
        self.assertEqual(source.merged_into_id, master)

    def test_03_stranger_cannot_merge(self):
        """Bob 建立且指派給 Bob → Alice 兩者皆非，應被擋。"""
        master = self._make_as(self.alice, 'a1')
        source = self._make_as(self.bob, 'b1')
        with self.assertRaises(UserError):
            (master | source).with_user(self.alice).action_merge(master)
