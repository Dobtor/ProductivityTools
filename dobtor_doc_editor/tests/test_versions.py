"""Tests for document versioning (W9-10 P2-1, W7-8 P1-1)."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestVersions(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Doc = self.env['doc.document']
        self.doc = self.Doc.create({
            'name': '測試文件',
            'content_html': '<h1>初版</h1><p>原始內容。</p>',
        })

    def test_save_version_increments_number(self):
        """每次 action_save_version 應遞增 version_number。"""
        self.assertEqual(self.doc.version_number, 0)
        r1 = self.doc.action_save_version(label='第一版')
        self.assertEqual(self.doc.version_number, 1)
        self.assertEqual(r1['version_number'], 1)

        r2 = self.doc.action_save_version(label='第二版')
        self.assertEqual(self.doc.version_number, 2)
        self.assertEqual(r2['version_number'], 2)

    def test_get_version_list_returns_descending(self):
        """get_version_list 應依日期降序回傳。"""
        for i in range(3):
            self.doc.action_save_version(label=f'v{i}')

        versions = self.doc.get_version_list()
        self.assertEqual(len(versions), 3)
        # 降序：最新在前
        nos = [v['version_number'] for v in versions]
        self.assertEqual(nos, [3, 2, 1])

    def test_get_version_content_roundtrip(self):
        """寫入 → 讀回 → content 應一致。"""
        self.doc.write({
            'content_html': '<h1>定稿</h1><p>會議結論。</p>',
            'content_json': '{"main":[{"value":"foo"}]}',
        })
        result = self.doc.action_save_version(label='定稿版')
        version_no = result['version_number']

        content = self.doc.get_version_content(version_no)
        self.assertIsNotNone(content)
        self.assertEqual(content['version_number'], 1)
        self.assertIn('定稿', content['content_html'])
        self.assertIn('foo', content['content_json'])

    def test_restore_version_creates_pre_restore_snapshot(self):
        """還原時應自動先建立「還原前」快照。"""
        # v1
        self.doc.write({'content_html': '<p>第一版內容</p>'})
        r1 = self.doc.action_save_version(label='v1')

        # 修改內容
        self.doc.write({'content_html': '<p>當前最新</p>'})

        # 還原 v1（用 version_number 當 id）
        self.doc.restore_version(r1['version_number'])

        # 內容回到 v1
        self.assertIn('第一版', self.doc.content_html)
        # 應有 3 個版本：v1（手動）、還原前快照（自動）、目前 number 已 +1
        versions = self.doc.get_version_list()
        self.assertGreaterEqual(len(versions), 2)
        # 還原前快照的 label 應提及「還原前」
        labels = [v['label'] for v in versions]
        self.assertTrue(
            any('還原前' in (lab or '') for lab in labels),
            f"還原前快照未建立，labels = {labels}",
        )

    def test_diff_versions_detects_changes(self):
        """diff_versions 對段落異動應產生 opcodes。"""
        self.doc.write({'content_html': '<h1>標題</h1><p>段落1</p><p>段落2</p>'})
        r1 = self.doc.action_save_version()

        self.doc.write({'content_html': '<h1>標題</h1><p>段落1 修改</p><p>段落2</p><p>新增段落3</p>'})
        r2 = self.doc.action_save_version()

        diff = self.doc.diff_versions(r1['version_number'], r2['version_number'])
        self.assertIsNotNone(diff)
        self.assertEqual(diff['a_version'], 1)
        self.assertEqual(diff['b_version'], 2)
        ops = [op['op'] for op in diff['opcodes']]
        # 應包含 equal（標題未變）+ replace（段落1修改）+ insert（新增段落3）
        self.assertIn('equal', ops)
        self.assertTrue('replace' in ops or 'insert' in ops)

    def test_diff_versions_returns_none_for_invalid_ids(self):
        """diff 不存在的 version_id 應回 None（呼叫方處理 404）。"""
        result = self.doc.diff_versions(99999, 99998)
        self.assertIsNone(result)

    def test_restore_invalid_message_raises(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.doc.restore_version(99999)
