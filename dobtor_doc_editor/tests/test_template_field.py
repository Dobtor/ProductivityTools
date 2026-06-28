"""Tests for Phase 8 Template UI Builder（ADR-022）— doc.template.signer / field。

涵蓋：
- signer / field 基本 CRUD 與關聯
- @api.constrains：signer 必須屬於同一範本
- _compute_field_count 計數
- ACL：editor read-only / manager full / 跨群組行為
- ondelete='cascade'：signer 刪除時對應 field 一併消失
"""

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTemplateField(TransactionCase):
    """Phase 8 範本欄位 / 簽約人 model 測試。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['doc.template']
        cls.Signer = cls.env['doc.template.signer']
        cls.Field = cls.env['doc.template.field']

        # 兩個範本（用於 cross-template constrains 驗證）
        cls.tpl_a = cls.Template.create({'name': 'Phase8 範本 A'})
        cls.tpl_b = cls.Template.create({'name': 'Phase8 範本 B'})

        # 三個 user：editor（read-only）、manager（full）、portal（read-only）
        cls.user_editor = new_test_user(
            cls.env,
            login='phase8_editor',
            groups='dobtor_doc_editor.group_doc_editor,base.group_user',
        )
        cls.user_manager = new_test_user(
            cls.env,
            login='phase8_manager',
            groups='dobtor_doc_editor.group_doc_manager,base.group_user',
        )

    # ─── 基本 CRUD + 計算欄位 ──────────────────────────────────────────

    def test_signer_create_links_to_template(self):
        """建立 signer 後可以從 template.signer_ids 反查、且 field_count = 0。"""
        signer = self.Signer.create({
            'template_id': self.tpl_a.id,
            'name': '房東',
            'sequence': 10,
        })
        self.assertIn(signer, self.tpl_a.signer_ids)
        self.assertEqual(signer.field_count, 0)
        self.assertEqual(self.tpl_a.signer_count, 1)

    def test_field_count_compute_on_template_and_signer(self):
        """新增 fields 後 template.field_count 與 signer.field_count 都跟著更新。"""
        signer = self.Signer.create({
            'template_id': self.tpl_a.id,
            'name': '業務',
        })
        self.Field.create({
            'template_id': self.tpl_a.id,
            'signer_id': signer.id,
            'field_type': 'text',
            'placeholder_text': '備註',
        })
        self.Field.create({
            'template_id': self.tpl_a.id,
            'signer_id': signer.id,
            'field_type': 'signature',
        })
        # 重新查欄位（compute 是 non-stored，要重新存取觸發）
        self.assertEqual(self.tpl_a.field_count, 2)
        self.assertEqual(signer.field_count, 2)

    # ─── @api.constrains ─────────────────────────────────────────────

    def test_field_constrains_signer_belongs_to_same_template(self):
        """field.signer_id 屬於不同 template 的 signer 時，constrains 擋下。"""
        signer_a = self.Signer.create({
            'template_id': self.tpl_a.id,
            'name': '房東 A',
        })
        # 嘗試在 tpl_b 上建立 field、但 signer 屬於 tpl_a → 應該被 constrains 擋下
        with self.assertRaises(ValidationError):
            self.Field.create({
                'template_id': self.tpl_b.id,
                'signer_id': signer_a.id,
                'field_type': 'name',
            })

    # ─── ACL ─────────────────────────────────────────────────────────

    def test_editor_cannot_create_template_field(self):
        """editor 群組對 doc.template.field 只有 read，create 應該 AccessError。"""
        signer = self.Signer.create({
            'template_id': self.tpl_a.id,
            'name': '業務',
        })
        with self.assertRaises(AccessError):
            self.Field.with_user(self.user_editor).create({
                'template_id': self.tpl_a.id,
                'signer_id': signer.id,
                'field_type': 'text',
            })

    def test_manager_can_full_crud_template_field(self):
        """manager 群組可以 create / write / unlink doc.template.field。"""
        Signer = self.Signer.with_user(self.user_manager)
        Field = self.Field.with_user(self.user_manager)
        signer = Signer.create({
            'template_id': self.tpl_a.id,
            'name': '見證人',
        })
        field = Field.create({
            'template_id': self.tpl_a.id,
            'signer_id': signer.id,
            'field_type': 'date',
        })
        field.write({'placeholder_text': '簽署日期', 'required': True})
        self.assertTrue(field.required)
        field.unlink()
        self.assertFalse(field.exists())

    # ─── ondelete cascade ───────────────────────────────────────────

    def test_signer_unlink_cascades_to_fields(self):
        """刪掉 signer 時，所有指向他的 field 也一併消失（ondelete='cascade'）。"""
        signer = self.Signer.create({
            'template_id': self.tpl_a.id,
            'name': '臨時角色',
        })
        f1 = self.Field.create({
            'template_id': self.tpl_a.id,
            'signer_id': signer.id,
            'field_type': 'text',
        })
        f2 = self.Field.create({
            'template_id': self.tpl_a.id,
            'signer_id': signer.id,
            'field_type': 'email',
        })
        signer.unlink()
        self.assertFalse(f1.exists())
        self.assertFalse(f2.exists())
