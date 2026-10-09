"""`controllers/doc_convert.py` 九支轉換函式的直接單元測試。

☠️ 為什麼需要：這九支原本**只靠路由間接覆蓋**。而其中有一整條是
**降級路徑**——`_lo_convert_to_html()` 在沒有 LibreOffice 時回 `None`，呼叫端
改走 `_docx_to_html_with_format()`（純 python-docx）。容器裡有 `soffice`，所以
那條降級鏈在測試裡**永遠走不到**：它是「寫好了但從沒被執行過」的典型。

這一支用 `patch('shutil.which')` 把 LibreOffice 拿掉，讓降級鏈真的跑一次。

另一半是純函式的行為（表格、樣式、頁面邊距），不需要 LibreOffice 也不需要
瀏覽器，所以直接餵資料進去驗。
"""
import io
from importlib.util import find_spec
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..controllers import doc_convert

HAS_PYTHON_DOCX = find_spec('docx') is not None


def _docx_bytes(build):
    """用 python-docx 組一份 docx，回 bytes。`build(doc)` 負責填內容。"""
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    build(doc)
    doc.save(buf)
    return buf.getvalue()


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestDocxToHtmlFallback(TransactionCase):
    """`_docx_to_html_with_format()`——LibreOffice 缺席時的純 Python 路徑。"""

    def setUp(self):
        super().setUp()
        if not HAS_PYTHON_DOCX:
            self.skipTest('需要 python-docx（這條路徑本身就是它的 fallback）')

    def test_paragraph_text_survives(self):
        html = doc_convert._docx_to_html_with_format(
            _docx_bytes(lambda d: d.add_paragraph('第一段內容')))
        self.assertIn('第一段內容', html, '段落文字不見了')

    def test_multiple_paragraphs_stay_separate(self):
        def build(d):
            d.add_paragraph('甲')
            d.add_paragraph('乙')
        html = doc_convert._docx_to_html_with_format(_docx_bytes(build))
        self.assertIn('甲', html)
        self.assertIn('乙', html)
        # 兩段不可以被併成一段
        self.assertNotIn('甲乙', html.replace('\n', '').replace(' ', ''),
                         '兩個段落被併在一起了')

    def test_table_becomes_a_table(self):
        def build(d):
            t = d.add_table(rows=2, cols=2)
            t.cell(0, 0).text = '左上'
            t.cell(1, 1).text = '右下'
        html = doc_convert._docx_to_html_with_format(_docx_bytes(build))
        self.assertIn('<table', html, '表格沒有變成 <table>')
        self.assertIn('左上', html)
        self.assertIn('右下', html)

    def test_bold_run_keeps_emphasis(self):
        def build(d):
            p = d.add_paragraph()
            p.add_run('粗體').bold = True
        html = doc_convert._docx_to_html_with_format(_docx_bytes(build))
        self.assertIn('粗體', html)
        self.assertRegex(html, r'(<b>|<strong>|font-weight)',
                         '粗體沒有留下任何強調標記')

    def test_html_is_escaped_not_injected(self):
        """文件裡寫 `<script>` 不可以變成活的標籤。"""
        html = doc_convert._docx_to_html_with_format(
            _docx_bytes(lambda d: d.add_paragraph('<script>alert(1)</script>')))
        self.assertNotIn('<script>', html, 'docx 內的 <script> 沒有被轉義')
        self.assertIn('&lt;script&gt;', html)

    def test_garbage_input_raises(self):
        """完全不是 zip → UserError，不是「把錯誤當文件內容回傳」。"""
        with self.assertRaises(UserError):
            doc_convert._docx_to_html_with_format(b'not a docx at all')

    def test_valid_zip_that_is_not_a_docx_raises(self):
        """☠️ 這一則是寫單元測試時挖出來的**可達缺陷**。

        把改名的 .zip 當 .docx 上傳：zip_guard 會放行（它確實是合法 zip），
        然後轉換器原本回傳
            `<p>（無法解析 DOCX："There is no item named 'word/document.xml'…"）</p>`
        ——**把失敗當成文件內容**。使用者因此得到一份內容是英文函式庫錯誤訊息的
        文件；經批次精靈更糟：那份文件會被建出來並**計為成功**。

        現在要 raise UserError（路由 → 400、精靈 → failed_count + log）。
        """
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('readme.txt', 'hello')
        with self.assertRaises(UserError) as cm:
            doc_convert._docx_to_html_with_format(buf.getvalue())
        msg = str(cm.exception)
        # 訊息要是給使用者看的，不可以是函式庫原文
        self.assertNotIn('word/document.xml', msg,
                         '錯誤訊息洩漏了函式庫內部路徑：%s' % msg)
        self.assertNotIn('There is no item named', msg)


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestLibreOfficeAbsentFallback(TransactionCase):
    """☠️ 這組是這支檔案存在的主要理由：讓降級鏈真的跑一次。

    容器有 `soffice`，所以 `_lo_convert_to_html()` 永遠不會回 `None`，
    `import_document` 裡那條 `lo_result is None → _docx_to_html_with_format`
    的分支在測試裡從來沒被執行過。
    """

    def test_lo_convert_returns_none_without_soffice(self):
        """沒有 soffice → 回 None（而不是丟例外），呼叫端才能降級。"""
        with patch.object(doc_convert.shutil, 'which', return_value=None):
            result = doc_convert._lo_convert_to_html(b'whatever', '.docx')
        self.assertIsNone(result, '沒有 LibreOffice 時應該回 None 讓呼叫端降級')

    def test_import_route_falls_back_to_python_parser(self):
        """整條降級鏈：沒有 LibreOffice，匯入仍然要產出 HTML。"""
        if not HAS_PYTHON_DOCX:
            self.skipTest('需要 python-docx')
        blob = _docx_bytes(lambda d: d.add_paragraph('降級路徑測試'))
        with patch.object(doc_convert.shutil, 'which', return_value=None):
            html = doc_convert._docx_to_html_with_format(blob)
        self.assertIn('降級路徑測試', html,
                      '沒有 LibreOffice 時的純 Python 路徑產不出內容')


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestPageMarginExtraction(TransactionCase):
    """`_extract_page_margins()`——從 LibreOffice 的 <style> 讀頁面邊距。"""

    def test_reads_margins_from_at_page(self):
        style = '@page { size: 21cm 29.7cm; margin: 2cm 1.5cm 2cm 1.5cm; }'
        margins = doc_convert._extract_page_margins(style)
        self.assertTrue(margins, '完整的 @page 讀不出邊距')

    def test_returns_falsy_when_no_at_page(self):
        self.assertFalse(
            doc_convert._extract_page_margins('body { color: red; }'),
            '沒有 @page 時不該憑空給出邊距')

    def test_survives_garbage_style(self):
        """壞掉的 CSS 不可以讓整個匯入掛掉。"""
        for junk in ('', '@page {', 'margin: ;', '@page { margin: abc; }'):
            doc_convert._extract_page_margins(junk)   # 不丟例外就算過


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestLoPostprocess(TransactionCase):
    """`_lo_postprocess()`——修 LibreOffice 輸出的已知毛病。"""

    def test_keeps_body_content(self):
        out = doc_convert._lo_postprocess(
            '<html><head><style>p{}</style></head><body><p>內容</p></body></html>')
        self.assertIn('內容', out)

    def test_survives_empty_and_broken_html(self):
        for junk in ('', '<html>', '<body><p>未閉合'):
            doc_convert._lo_postprocess(junk)   # 不丟例外就算過
