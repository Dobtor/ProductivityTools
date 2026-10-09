# -*- coding: utf-8 -*-
r"""多公司隔離——逐 model 量，不靠推論。

☠️ 為什麼需要這一支：2026-10-09 的稽核（02897ec）替
`doc.editor.export.log` 補了公司隔離 rule，但**沒有回頭檢查其他 model**。
把 ACL 與 record rule 攤開之後有兩個嫌疑：

1. `rule_doc_document_manager_all` 的 domain 是 `[(1,'=',1)]`。Odoo 的
   **非 global rule 之間是 OR**，所以同時是 manager 的人會 OR 掉
   `rule_doc_document_company` 的公司範圍。而 `doc.output` 與
   `doc.editor.export.log` 的 manager rule **都有**公司範圍——不一致。
2. `doc.template.field` / `.option` / `.signer` 有 ACL（editor / portal 可讀）
   但**完全沒有 record rule**，而它們的母體 `doc.template` 有公司隔離。
   在 Odoo 裡「子記錄」不會自動繼承母體的 rule。

這一支不猜哪一個是真的，**兩個都建資料去讀**。
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestCompanyIsolation(TransactionCase):
    """A 公司的使用者不可以讀到 B 公司的資料。"""

    def setUp(self):
        super().setUp()
        Company = self.env['res.company'].sudo()
        self.company_a = Company.create({'name': '隔離測試 A 公司'})
        self.company_b = Company.create({'name': '隔離測試 B 公司'})
        self.grp_editor = self.env.ref('dobtor_doc_editor.group_doc_editor')
        self.grp_manager = self.env.ref('dobtor_doc_editor.group_doc_manager')

    def _user(self, login, company, groups):
        """建一個只屬於 company 的使用者。"""
        return self.env['res.users'].sudo().create({
            'name': login,
            'login': login,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id]
                           + [g.id for g in groups])],
        })

    def _b_template(self):
        return self.env['doc.template'].sudo().create({
            'name': 'B 公司的範本',
            'role': 'content',
            'company_id': self.company_b.id,
            'model_id': self.env['ir.model']._get('res.partner').id,
        })

    # ── 嫌疑 1：manager 會不會繞過公司隔離 ────────────────────────────

    def test_manager_cannot_read_other_company_documents(self):
        """A 公司的 manager 不可以讀到 B 公司的文件。

        `rule_doc_document_manager_all` 的 domain 是 `[(1,'=',1)]`，
        而非 global rule 之間是 OR——若沒有一條 global 的公司 rule，
        這條就會把 `rule_doc_document_company` 整個 OR 掉。
        """
        doc_b = self.env['doc.document'].sudo().create({
            'name': 'B 公司的文件',
            'content_html': '<p>B 公司的機密內容</p>',
            'company_id': self.company_b.id,
        })
        mgr_a = self._user('isolation_mgr_a', self.company_a, [self.grp_manager])
        visible = self.env['doc.document'].with_user(mgr_a).search(
            [('id', '=', doc_b.id)])
        self.assertFalse(
            visible,
            'A 公司的 doc manager 讀到了 B 公司的文件（id=%d）。\n'
            'rule_doc_document_manager_all 的 domain 是 [(1,=,1)] 且不是 '
            'global rule，所以它把 rule_doc_document_company 的公司範圍 OR 掉了。\n'
            '對照：doc.output 與 doc.editor.export.log 的 manager rule 都有'
            '公司範圍——doc.document 是這三者裡唯一沒有的，而它是裝內容的那個。'
            % doc_b.id)

    # ── 嫌疑 2：範本的子記錄有沒有隔離 ────────────────────────────────

    def test_editor_cannot_read_other_company_template_fields(self):
        """A 公司的 editor 不可以讀到 B 公司範本的欄位定義。"""
        tpl_b = self._b_template()
        signer_b = self.env['doc.template.signer'].sudo().create({
            'template_id': tpl_b.id,
            'name': 'B 公司的簽核人',
        })
        field_b = self.env['doc.template.field'].sudo().create({
            'template_id': tpl_b.id,
            'signer_id': signer_b.id,
            'field_type': 'text',
            'layout_mode': 'inline',
        })
        ed_a = self._user('isolation_ed_a', self.company_a, [self.grp_editor])
        visible = self.env['doc.template.field'].with_user(ed_a).search(
            [('id', '=', field_b.id)])
        self.assertFalse(
            visible,
            'A 公司的 editor 讀到了 B 公司範本的欄位定義（id=%d）。\n'
            'doc.template 有公司隔離 rule，但 doc.template.field 沒有任何 '
            'record rule——Odoo 不會讓子記錄自動繼承母體的 rule。'
            % field_b.id)

    def test_editor_cannot_read_other_company_template_signers(self):
        """A 公司的 editor 不可以讀到 B 公司範本的簽核人設定。"""
        signer_b = self.env['doc.template.signer'].sudo().create({
            'template_id': self._b_template().id,
            'name': 'B 公司的簽核人',
        })
        ed_a = self._user('isolation_sgn_a', self.company_a, [self.grp_editor])
        visible = self.env['doc.template.signer'].with_user(ed_a).search(
            [('id', '=', signer_b.id)])
        self.assertFalse(
            visible,
            'A 公司的 editor 讀到了 B 公司範本的簽核人（id=%d）——'
            'doc.template.signer 沒有 record rule。' % signer_b.id)

    def test_editor_cannot_read_other_company_field_options(self):
        """A 公司的 editor 不可以讀到 B 公司範本欄位的選項內容。"""
        tpl_b = self._b_template()
        signer_b = self.env['doc.template.signer'].sudo().create({
            'template_id': tpl_b.id, 'name': 'B 簽核人',
        })
        field_b = self.env['doc.template.field'].sudo().create({
            'template_id': tpl_b.id, 'signer_id': signer_b.id,
            'field_type': 'select',
            'layout_mode': 'inline',
        })
        opt_b = self.env['doc.template.field.option'].sudo().create({
            'field_id': field_b.id, 'value': 'B 公司的選項值',
        })
        ed_a = self._user('isolation_opt_a', self.company_a, [self.grp_editor])
        visible = self.env['doc.template.field.option'].with_user(ed_a).search(
            [('id', '=', opt_b.id)])
        self.assertFalse(
            visible,
            'A 公司的 editor 讀到了 B 公司範本欄位的選項（id=%d）——'
            'doc.template.field.option 沒有 record rule。' % opt_b.id)
