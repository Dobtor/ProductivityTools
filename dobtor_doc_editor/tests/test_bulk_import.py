"""Tests for bulk import wizard (P3-1)。"""

import io
import base64
import zipfile

from odoo.tests.common import TransactionCase, tagged


def _make_minimal_docx_bytes():
    """產一個最小的 docx zip（只有必要 parts）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>''')
        zf.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''')
        zf.writestr('word/_rels/document.xml.rels', '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>''')
        zf.writestr('word/document.xml', '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Hello World</w:t></w:r></w:p></w:body>
</w:document>''')
    return buf.getvalue()


def _make_archive(entries):
    """打包多個 (name, bytes) → 一個外層 zip。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestBulkImport(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Wizard = self.env['doc.bulk.import.wizard']
        self.Doc = self.env['doc.document']

    def test_wizard_creates_documents(self):
        """匯入含 2 個 docx 的 zip → 建立 2 筆文件。"""
        docx = _make_minimal_docx_bytes()
        archive = _make_archive([
            ('meeting1.docx', docx),
            ('meeting2.docx', docx),
        ])
        before = self.Doc.search_count([])

        wiz = self.Wizard.create({
            'archive_file': base64.b64encode(archive),
            'archive_filename': 'batch.zip',
            'target_company_id': self.env.company.id,
            'skip_failures': True,
        })
        wiz.action_run_import()

        self.assertEqual(wiz.state, 'done')
        self.assertEqual(wiz.created_count, 2)
        self.assertEqual(wiz.failed_count, 0)
        after = self.Doc.search_count([])
        self.assertEqual(after - before, 2)

    def test_wizard_skips_non_docx(self):
        """zip 內非 .docx 檔案應被略過，不影響 .docx 處理。"""
        archive = _make_archive([
            ('meeting.docx', _make_minimal_docx_bytes()),
            ('readme.txt', b'this should be skipped'),
            ('image.png', b'\x89PNG\r\n\x1a\n'),
        ])
        wiz = self.Wizard.create({
            'archive_file': base64.b64encode(archive),
            'archive_filename': 'mixed.zip',
            'target_company_id': self.env.company.id,
        })
        wiz.action_run_import()
        self.assertEqual(wiz.created_count, 1)
        self.assertIn('SKIP', wiz.log_text)

    def test_wizard_rejects_zip_bomb_attempt(self):
        """超過 5000 entry 的 archive 應被 zip_guard 擋。"""
        # 用最小 entry size 製造 5001 個假檔（會觸發 zip_guard 的 max_entries）
        entries = [(f'f{i}.txt', b'') for i in range(5001)]
        archive = _make_archive(entries)
        wiz = self.Wizard.create({
            'archive_file': base64.b64encode(archive),
            'archive_filename': 'too_many.zip',
            'target_company_id': self.env.company.id,
        })
        wiz.action_run_import()
        self.assertEqual(wiz.state, 'failed')
        self.assertIn('entry', (wiz.log_text or '').lower())

    def test_wizard_rejects_malformed_archive(self):
        wiz = self.Wizard.create({
            'archive_file': base64.b64encode(b'not a zip at all'),
            'archive_filename': 'broken.zip',
            'target_company_id': self.env.company.id,
        })
        wiz.action_run_import()
        self.assertEqual(wiz.state, 'failed')

    def test_wizard_assigns_target_company(self):
        """新建文件的 company_id 應 = wizard 設定的 target_company_id。"""
        before_ids = self.Doc.search([]).ids
        archive = _make_archive([('x.docx', _make_minimal_docx_bytes())])
        wiz = self.Wizard.create({
            'archive_file': base64.b64encode(archive),
            'archive_filename': 'one.zip',
            'target_company_id': self.env.company.id,
        })
        wiz.action_run_import()
        new_docs = self.Doc.search([('id', 'not in', before_ids)])
        self.assertEqual(len(new_docs), 1)
        self.assertEqual(new_docs.company_id, self.env.company)
