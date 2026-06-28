"""Tests for security setup (W9-10 P2-1, W2-3 P0-1)。

驗證 portal user 的權限模型：
    - 只能看自己被加為 collaborator 的文件
    - 不能 create / unlink
    - 沒被加為 collaborator 時不能讀別人的文件
"""

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPortalSecurity(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Doc = self.env['doc.document']

        # 內部 user A 建立兩份文件
        self.user_internal = new_test_user(
            self.env,
            login='dobtor_internal_test',
            groups='dobtor_doc_editor.group_doc_editor,base.group_user',
        )
        self.doc_a = self.Doc.with_user(self.user_internal).create({
            'name': '文件 A（受邀）',
            'content_html': '<p>A</p>',
        })
        self.doc_b = self.Doc.with_user(self.user_internal).create({
            'name': '文件 B（未受邀）',
            'content_html': '<p>B</p>',
        })

        # Portal user
        self.user_portal = new_test_user(
            self.env,
            login='dobtor_portal_test',
            groups='dobtor_doc_editor.group_doc_portal,base.group_portal',
        )

        # 把 portal user 加為 doc_a 的協作者
        self.doc_a.collaborator_ids = [(4, self.user_portal.id)]

    def test_portal_can_read_invited_doc(self):
        """portal user 可以讀被邀請的文件。"""
        doc = self.Doc.with_user(self.user_portal).browse(self.doc_a.id)
        self.assertEqual(doc.exists().id, self.doc_a.id)
        # 觸發實際讀取
        _ = doc.name

    def test_portal_cannot_read_uninvited_doc(self):
        """portal user 不能讀未受邀的文件（ir.rule 過濾）。"""
        # search 應該空集合
        docs = self.Doc.with_user(self.user_portal).search([
            ('id', '=', self.doc_b.id)
        ])
        self.assertEqual(len(docs), 0,
                         "portal user 不該看到未受邀的文件")

    def test_portal_cannot_create_doc(self):
        """portal user 不能建立新文件（ACL perm_create=0）。"""
        with self.assertRaises(AccessError):
            self.Doc.with_user(self.user_portal).create({
                'name': '惡意建立的文件',
            })

    def test_portal_cannot_unlink_doc(self):
        """portal user 不能刪除文件（ACL perm_unlink=0）。"""
        doc = self.Doc.with_user(self.user_portal).browse(self.doc_a.id)
        with self.assertRaises(AccessError):
            doc.unlink()

    def test_portal_can_write_invited_doc(self):
        """portal user 可以編輯被邀請的文件（ACL perm_write=1）。"""
        doc = self.Doc.with_user(self.user_portal).browse(self.doc_a.id)
        doc.write({'content_html': '<p>portal user 改的</p>'})
        self.assertIn('portal user 改的', doc.content_html)

    def test_portal_search_only_returns_invited(self):
        """search 不帶任何 domain 時，portal user 只看到被邀請的。"""
        all_visible = self.Doc.with_user(self.user_portal).search([])
        ids = set(all_visible.ids)
        self.assertIn(self.doc_a.id, ids)
        self.assertNotIn(self.doc_b.id, ids)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPortalCrossCompanyCollaboration(TransactionCase):
    """Sprint 117 — Sprint 78 Finding B 收口

    Lock-in test：rule_doc_document_portal 刻意不加 company_id 過濾、
    使 portal user 能以 collaborator 身份跨公司讀寫被邀請的文件。
    這是 ChienYi 承包商 / 業主代表跨公司協作的核心設計。

    若未來有人加 company filter 進 rule_doc_document_portal、本測試會 fail、
    強迫先讀 docs/sprint117_portal_company_rule_closure.md 理解 trade-off。
    """

    def setUp(self):
        super().setUp()
        self.Doc = self.env['doc.document']
        self.Company = self.env['res.company']

        # 兩家公司：監造公司 + 承包商公司
        self.company_supervisor = self.Company.create({'name': 'Sprint117 監造公司'})
        self.company_contractor = self.Company.create({'name': 'Sprint117 承包商'})

        # 監造公司的內部 user 建立文件（doc.company_id = 監造公司）
        self.user_supervisor = new_test_user(
            self.env,
            login='sprint117_supervisor',
            groups='dobtor_doc_editor.group_doc_editor,base.group_user',
            company_id=self.company_supervisor.id,
            company_ids=[(6, 0, [self.company_supervisor.id])],
        )
        self.doc_invited = self.Doc.with_user(self.user_supervisor).create({
            'name': 'Sprint117 跨公司邀請文件',
            'content_html': '<p>cross-company invited</p>',
            'company_id': self.company_supervisor.id,
        })
        self.doc_not_invited = self.Doc.with_user(self.user_supervisor).create({
            'name': 'Sprint117 跨公司未邀請文件',
            'content_html': '<p>cross-company not invited</p>',
            'company_id': self.company_supervisor.id,
        })

        # Portal user 屬於承包商公司（不同於文件 company_id）
        self.user_portal_contractor = new_test_user(
            self.env,
            login='sprint117_portal_contractor',
            groups='dobtor_doc_editor.group_doc_portal,base.group_portal',
            company_id=self.company_contractor.id,
            company_ids=[(6, 0, [self.company_contractor.id])],
        )

        # 監造公司管理員把承包商 portal user 加為 doc_invited 的協作者
        self.doc_invited.collaborator_ids = [(4, self.user_portal_contractor.id)]

    def test_portal_can_read_cross_company_invited_doc(self):
        """Lock-in：portal user（承包商）能讀被邀請的跨公司文件。

        Sprint 78 Finding B 評估後決議：collaborator_ids 是 explicit access grant、
        足以承擔授權邊界；強行加 company filter 會 break ChienYi 跨公司協作流程。
        """
        doc = self.Doc.with_user(self.user_portal_contractor).browse(self.doc_invited.id)
        existing = doc.exists()
        self.assertEqual(
            existing.id, self.doc_invited.id,
            'portal user（承包商）應該能讀被邀請的監造公司文件 — '
            '若 fail、表示有人加了 company filter 到 rule_doc_document_portal、'
            '請先讀 docs/sprint117_portal_company_rule_closure.md',
        )
        _ = existing.name  # 觸發實際讀

    def test_portal_can_write_cross_company_invited_doc(self):
        """Lock-in：portal user（承包商）能寫被邀請的跨公司文件。"""
        doc = self.Doc.with_user(self.user_portal_contractor).browse(self.doc_invited.id)
        doc.write({'content_html': '<p>承包商跨公司編輯</p>'})
        self.assertIn('承包商跨公司編輯', doc.content_html)

    def test_portal_cannot_read_uninvited_cross_company_doc(self):
        """Sanity：portal user 沒被邀請就讀不到、即使是同樣 cross-company 文件。

        確認 collaborator_ids 仍是必要邊界、不是「跨公司全開」。
        """
        docs = self.Doc.with_user(self.user_portal_contractor).search([
            ('id', '=', self.doc_not_invited.id)
        ])
        self.assertEqual(
            len(docs), 0,
            'portal user 不能讀未受邀的跨公司文件 — collaborator_ids 仍須是必要邊界',
        )

    def test_portal_search_includes_cross_company_invited(self):
        """search 不帶 domain 時、cross-company 受邀文件也應出現。"""
        all_visible = self.Doc.with_user(self.user_portal_contractor).search([])
        ids = set(all_visible.ids)
        self.assertIn(self.doc_invited.id, ids)
        self.assertNotIn(self.doc_not_invited.id, ids)
