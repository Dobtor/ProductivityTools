"""舊系統 `+++INS+++` 語法 → docxtpl Jinja2 語法的轉換。

為什麼單獨一支：這是 `doc_convert.py` 十支函式中**唯一服務核心**的一支
（`/dobtor_doc/upload_template` 上傳 DOCX 範本時把舊語法轉成 `{{ }}`）。
其餘九支都只服務「檔案匯入」（DOCX/ODT → doc.document），會隨
`dobtor_doc_import` 模組搬走。先把這支抽出來，搬的時候才能整檔搬、不必在
一個要搬走的檔案裡留一支留下來的函式。

放在 `models/` 而不是 `controllers/`：它是純函式、不碰 ORM 也不碰 request，
與同樣形狀的 `doc_zip_guard.py` 一致（controller 匯入它們來用）。
"""
import io
import logging
import re

_logger = logging.getLogger(__name__)


def _convert_ins_to_jinja(raw_bytes):
    """
    把舊系統 +++...+++ 語法全面轉換為 docxtpl Jinja2 語法。
    在段落層級操作（para.text 已拼接所有 <w:r>），安全處理 Word 的 run 切割問題。

    語法對照表：
      +++INS name+++           → {{ name }}
      +++INS $item.field+++    → {{ item.field }}
      +++FOR v IN col++++      → {% for v in col %}      （段落層級，表格外）
      +++FOR v IN $col++++     → {% tr for v in col %}   （表格列層級，表格內）
      +++END-FOR v++++         → {% endfor %}            （段落層級，表格外）
      +++END-FOR v++++         → {% tr endfor %}         （表格列層級，表格內）

    缺 python-docx 時原樣回傳 raw_bytes：上傳仍然成功，只是舊語法不轉換。
    擋掉整個上傳比較糟——使用者的檔案裡可能本來就寫 {{ }}，根本不需要轉換。
    呼叫端會回報偵測到的變數數量，數量為 0 就是使用者看得到的訊號。
    """
    try:
        import docx as python_docx
    except ImportError:
        _logger.warning(
            'python-docx 未安裝，略過 +++INS+++ 舊語法轉換（pip install python-docx）'
        )
        return raw_bytes

    # +++INS $item.field+++ 或 +++INS $item. field+++（允許點號前後有空格，轉換時移除）
    _INS    = re.compile(r'\+{3}INS\s+\$?\s*([A-Za-z_][\w]*(?:\s*\.\s*[A-Za-z_][\w]*)*)\s*\+{3,4}')
    # +++FOR loopVar IN $collection+++ 或 +++FOR loopVar IN collection+++
    _FOR    = re.compile(r'\+{3}FOR\s+([A-Za-z_]\w*)\s+IN\s+\$?([A-Za-z_][A-Za-z0-9_.]*)\s*\+{3,4}')
    # +++END-FOR varName+++（3 或 4 個 +）
    _ENDFOR = re.compile(r'\+{3}END-FOR\s+[A-Za-z_]\w*\s*\+{3,4}')
    # 任何 +++ 標記
    _ANY    = re.compile(r'\+{3}(?:INS|FOR|END-FOR)\s')

    doc = python_docx.Document(io.BytesIO(raw_bytes))

    def _apply(text, in_table):
        # docxtpl 識別 {%tr for %} 的 regex 是 ({%|{{)tr，無空格後才接 tr
        for_tpl    = '{%%tr for %s in %s %%}' if in_table else '{%% for %s in %s %%}'
        endfor_tpl = '{%tr endfor %}'          if in_table else '{% endfor %}'
        text = _INS.sub(lambda m: '{{ %s }}' % re.sub(r'\s', '', m.group(1)), text)
        text = _FOR.sub(lambda m: for_tpl % (m.group(1), m.group(2)), text)
        text = _ENDFOR.sub(endfor_tpl, text)
        return text

    def _process_para(para, in_table):
        if not _ANY.search(para.text):
            return
        new_text = _apply(para.text, in_table)
        if para.runs:
            para.runs[0].text = new_text
            for run in para.runs[1:]:
                run.text = ''

    for para in doc.paragraphs:
        _process_para(para, in_table=False)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _process_para(para, in_table=True)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
