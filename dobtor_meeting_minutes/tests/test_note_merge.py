# -*- coding: utf-8 -*-

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestActivityNoteMerge(TransactionCase):
    """待辦 ↔ 筆記：不變式、合併時筆記聯集、筆記膠囊改寫（自 dobtor_mail_activity 搬入）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Activity = cls.env['mail.activity']
        cls.activity_type = cls.env['mail.activity.type'].create({
            'name': 'Note Merge Test Type',
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
