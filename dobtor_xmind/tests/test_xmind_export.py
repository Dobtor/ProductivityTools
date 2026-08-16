# -*- coding: utf-8 -*-
"""``.xmind`` 匯出的往返測試。

``_generate_xmind_content()`` 在補上 ``action_export_xmind`` 之前是零呼叫的死碼，
所以它的輸出從來沒被驗證過 —— 這裡的重點不是「有沒有產生檔案」，而是：

1. 產出的結構真的可以 JSON 序列化（樹裡若混進 date/記錄集會直接炸）；
2. 產出的 zip 可以被本模組自己的 ``import_xmind_file()`` 讀回來（同一份
   ``content.json`` 契約，匯出端與匯入端不會各說各話）；
3. 往返之後主題的層級與名稱還在。
"""
import base64
import io
import json
import zipfile

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestXmindExport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workbook = cls.env['xmind.workbook'].create({'name': 'Export Book'})
        cls.sheet = cls.env['xmind.sheet'].create({
            'name': 'Sheet A',
            'workbook_id': cls.workbook.id,
        })
        cls.root = cls.env['xmind.topic'].create({
            'title': 'Root',
            'sheet_id': cls.sheet.id,
        })
        cls.child = cls.env['xmind.topic'].create({
            'title': 'Child',
            'sheet_id': cls.sheet.id,
            'parent_id': cls.root.id,
        })

    def _archive(self):
        content = self.workbook._generate_xmind_content()
        return content, self.workbook._generate_xmind_archive(content)

    def test_content_is_json_serialisable(self):
        """整棵樹（含日期、標記、關聯）必須能過 json.dumps。"""
        content, _blob = self._archive()
        # 不吞例外：序列化失敗代表匯出實際上是壞的
        dumped = json.dumps(content, ensure_ascii=False)
        self.assertIn('Root', dumped)
        self.assertIn('Child', dumped)

    def test_archive_members(self):
        """zip 至少要有匯入端讀的 content.json，且是合法 JSON。"""
        _content, blob = self._archive()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
            self.assertIn('content.json', names)
            self.assertIn('metadata.json', names)
            self.assertIn('manifest.json', names)
            parsed = json.loads(zf.read('content.json'))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['title'], 'Sheet A')
        self.assertEqual(parsed[0]['rootTopic']['title'], 'Root')

    def test_round_trip_through_importer(self):
        """匯出 → 用本模組的匯入端讀回 → 層級與名稱不變。"""
        _content, blob = self._archive()
        target = self.env['xmind.workbook'].create({
            'name': 'Round Trip',
            'xmind_file': base64.b64encode(blob),
            'xmind_filename': 'rt.xmind',
        })
        target.import_xmind_file()

        self.assertEqual(len(target.sheet_ids), 1)
        imported = target.sheet_ids[0]
        self.assertEqual(imported.name, 'Sheet A')
        roots = imported.topic_ids.filtered(lambda t: not t.parent_id)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots.name, 'Root')
        self.assertEqual(roots.child_ids.mapped('name'), ['Child'])

    def test_export_action_creates_attachment_without_touching_source(self):
        """匯出寫進獨立 attachment，不可覆蓋 xmind_file（匯入來源）。"""
        source = base64.b64encode(b'original-upload')
        self.workbook.write({'xmind_file': source, 'xmind_filename': 'src.xmind'})

        action = self.workbook.action_export_xmind()
        self.assertEqual(action['type'], 'ir.actions.act_url')

        self.assertEqual(self.workbook.xmind_file, source)
        self.assertEqual(self.workbook.xmind_filename, 'src.xmind')

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'xmind.workbook'),
            ('res_id', '=', self.workbook.id),
            ('name', '=', 'Export Book.xmind'),
        ], limit=1)
        self.assertTrue(attachment)
        self.assertIn(str(attachment.id), action['url'])

    def test_export_twice_reuses_one_attachment(self):
        """重複匯出只留一份 —— 附件掛在工作簿上，每次新建會塞滿附件區。"""
        def count():
            return self.env['ir.attachment'].search_count([
                ('res_model', '=', 'xmind.workbook'),
                ('res_id', '=', self.workbook.id),
                ('name', '=', 'Export Book.xmind'),
            ])

        self.workbook.action_export_xmind()
        self.assertEqual(count(), 1)

        # 改動內容後再匯出：仍是一份，且內容是最新的
        self.child.title = 'Child Renamed'
        action = self.workbook.action_export_xmind()
        self.assertEqual(count(), 1)

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'xmind.workbook'),
            ('res_id', '=', self.workbook.id),
            ('name', '=', 'Export Book.xmind'),
        ])
        self.assertIn(str(attachment.id), action['url'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(attachment.datas))) as zf:
            self.assertIn('Child Renamed', zf.read('content.json').decode('utf-8'))

    def test_export_empty_workbook_raises(self):
        """沒有根主題就沒有東西可匯出，要明確報錯而不是給一個空 zip。"""
        empty = self.env['xmind.workbook'].create({'name': 'Empty'})
        empty.sheet_ids.unlink()
        with self.assertRaises(UserError):
            empty.action_export_xmind()
