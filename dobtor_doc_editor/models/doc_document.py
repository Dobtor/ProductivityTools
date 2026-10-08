import base64
import io
import json
import re
import subprocess
import tempfile
import os
import zipfile
from odoo import models, fields, api, _
from odoo.exceptions import UserError


# ─── python-docx HTML 轉換輔助函式 ────────────────────────────────────────────
#
# 這組函式把 _content_json_to_html() 產生的 HTML 轉成 DOCX。它是 LibreOffice
# 不可用時的 fallback（minimal container 常見），所以保真度直接決定那些環境的
# 匯出品質。
#
# 2026-10-07 實測基準：改寫前 6/17 項格式存活、LibreOffice 13/17。
# 差距不是 python-docx 的能力問題——舊版只看 `'bold' in style_str`，
# 字色/字級/字體/對齊完全不讀，表格用 `cell.text = ...` 把整格打成純文字，
# 圖片與跨欄沒有分支。以下補齊這些。

_CSS_DECL_RE = re.compile(r'([\w-]+)\s*:\s*([^;]+)')
_HEX_RE = re.compile(r'^#?([0-9a-fA-F]{6})$')
_RGB_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)')
_LEN_RE = re.compile(r'^([\d.]+)\s*(px|pt|em|rem)?$')

# 行內樣式可繼承的屬性：巢狀 <span> 時外層設定要傳進內層
def _css_color_to_hex(value):
    """CSS 顏色 → 六位 hex（不帶 #）；無法解析回 None。

    同時吃 #rrggbb 與 rgb(r,g,b)——前者來自本模組的 _element_style，
    後者來自 LibreOffice 匯入的 HTML。
    """
    value = (value or '').strip()
    m = _HEX_RE.match(value)
    if m:
        return m.group(1).upper()
    m = _RGB_RE.match(value)
    if m:
        return '%02X%02X%02X' % tuple(min(255, int(g)) for g in m.groups())
    return None


def _css_length_to_pt(value):
    """CSS 長度 → Word 的 pt。

    canvas-editor 的 element.size 單位是 px，_element_style 也輸出 px；
    Word 用 pt。96dpi 下 1px = 0.75pt——這個換算錯掉的話字級會差 33%
    （就是先前 _content_json_to_html 寫成 pt 的那個缺陷的鏡像）。
    """
    m = _LEN_RE.match((value or '').strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or 'px'
    if unit == 'px':
        return num * 0.75
    if unit == 'pt':
        return num
    if unit in ('em', 'rem'):
        return num * 12.0          # 以 16px 基準字換算
    return None


def _parse_inline_style(style_str, inherited=None):
    """行內 style 屬性 → run 樣式 dict（含繼承）。"""
    props = dict(inherited or {})
    for name, value in _CSS_DECL_RE.findall(style_str or ''):
        name = name.strip().lower()
        value = value.strip()
        if name == 'font-weight':
            props['bold'] = value in ('bold', 'bolder') or (
                value.isdigit() and int(value) >= 600)
        elif name == 'font-style':
            props['italic'] = value in ('italic', 'oblique')
        elif name == 'text-decoration' or name == 'text-decoration-line':
            if 'underline' in value:
                props['underline'] = True
            if 'line-through' in value:
                props['strike'] = True
        elif name == 'color':
            hexv = _css_color_to_hex(value)
            if hexv:
                props['color'] = hexv
        elif name == 'background-color':
            hexv = _css_color_to_hex(value)
            if hexv:
                props['highlight'] = hexv
        elif name == 'font-size':
            pt = _css_length_to_pt(value)
            if pt:
                props['size_pt'] = pt
        elif name == 'font-family':
            first = value.split(',')[0].strip().strip('\'"')
            if first:
                props['font_name'] = first
    return props


def _style_from_tag(tag, props):
    """標籤本身帶的語意格式（<b>/<strong>/<em>/<u>/<s>…）。"""
    props = dict(props)
    if tag in ('b', 'strong'):
        props['bold'] = True
    elif tag in ('i', 'em'):
        props['italic'] = True
    elif tag == 'u':
        props['underline'] = True
    elif tag in ('s', 'strike', 'del'):
        props['strike'] = True
    return props


def _apply_run_style(run, props):
    """把樣式 dict 套到 python-docx 的 run 上。"""
    from docx.shared import Pt, RGBColor
    if props.get('bold'):
        run.bold = True
    if props.get('italic'):
        run.italic = True
    if props.get('underline'):
        run.underline = True
    if props.get('strike'):
        run.font.strike = True
    if props.get('color'):
        try:
            run.font.color.rgb = RGBColor.from_string(props['color'])
        except Exception:
            pass
    if props.get('size_pt'):
        try:
            run.font.size = Pt(props['size_pt'])
        except Exception:
            pass
    if props.get('font_name'):
        run.font.name = props['font_name']
        # 中日韓字型要同時設 eastAsia，否則 Word 只對拉丁字母生效
        try:
            from docx.oxml.ns import qn
            rpr = run._element.get_or_add_rPr()
            rfonts = rpr.find(qn('w:rFonts'))
            if rfonts is None:
                from docx.oxml import OxmlElement
                rfonts = OxmlElement('w:rFonts')
                rpr.append(rfonts)
            rfonts.set(qn('w:eastAsia'), props['font_name'])
        except Exception:
            pass
    if props.get('highlight'):
        # 用 w:shd 而非 font.highlight_color：後者只吃 WD_COLOR_INDEX 那十幾種
        # 預設色，任意 hex 會失真。
        try:
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), props['highlight'])
            run._element.get_or_add_rPr().append(shd)
        except Exception:
            pass


def _is_page_break(node):
    cls = (node.get('class') or '')
    return 'doc-page-break' in cls


def _emit_image(para, node):
    """<img src="data:image/...;base64,..."> → 嵌進 DOCX。回傳是否成功。

    只處理 data: URI。外部 URL 刻意不抓——匯出不該在使用者按下載時去連外，
    那會讓匯出時間取決於第三方網站，在無外網的容器還會直接卡住。
    """
    from docx.shared import Emu
    src = node.get('src') or ''
    if not src.startswith('data:'):
        return False
    try:
        header, _, b64 = src.partition(',')
        if 'base64' not in header or not b64:
            return False
        raw = base64.b64decode(b64)
        run = para.add_run()
        width = node.get('width')
        kwargs = {}
        if width and str(width).isdigit():
            # HTML width 是 px；96dpi → 1px = 9525 EMU
            kwargs['width'] = Emu(int(width) * 9525)
        run.add_picture(io.BytesIO(raw), **kwargs)
        return True
    except Exception:
        return False


def _add_page_field(para, kind):
    """插入 Word 的頁碼 field code。

    DOCX 的頁碼不是文字而是 field（PAGE / NUMPAGES），開檔時由 Word 計算。
    不做這件事的話，PDF 有頁碼、DOCX 靜默沒有——正是這個模組最想避免的
    那種不對稱（同一份文件兩種格式印出來不一樣，而且沒有任何訊息）。

    fldSimple 內放一個佔位 run：部分檢視器在重新計算之前會顯示空白。
    """
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), ' NUMPAGES ' if kind == 'count' else ' PAGE ')
    holder = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = '1'
    holder.append(text)
    fld.append(holder)
    para._p.append(fld)


def _page_field_kind(node):
    """<span class="page"> / <span class="topage"> → 'number' / 'count'。"""
    if not isinstance(node.tag, str) or node.tag.lower() != 'span':
        return None
    cls = (node.get('class') or '').strip()
    if cls == 'page':
        return 'number'
    if cls == 'topage':
        return 'count'
    return None


def _add_runs_from_node(para, node, inherited=None):
    """把節點的行內內容（含巢狀格式、圖片、換行）加入 docx paragraph。

    遞迴並累積樣式——舊版只看第一層 <span> 且只認 bold/italic，
    `<span style="color:red"><b>x</b></span>` 這種巢狀會整組掉格式。
    """
    base = _parse_inline_style(node.get('style'), inherited)

    if node.text:
        run = para.add_run(node.text)
        _apply_run_style(run, base)

    for child in node:
        ctag = (child.tag or '').lower() if isinstance(child.tag, str) else ''
        page_kind = _page_field_kind(child)
        if page_kind:
            _add_page_field(para, page_kind)
        elif ctag == 'br':
            para.add_run().add_break()
        elif ctag == 'img':
            _emit_image(para, child)
        elif ctag in ('script', 'style'):
            pass
        else:
            child_props = _parse_inline_style(
                child.get('style'), _style_from_tag(ctag, base),
            )
            if len(child) == 0:
                text = child.text or ''
                if text:
                    run = para.add_run(text)
                    _apply_run_style(run, child_props)
            else:
                _add_runs_from_node(para, child, inherited=child_props)
        if child.tail:
            run = para.add_run(child.tail)
            _apply_run_style(run, base)


def _apply_paragraph_align(para, node):
    """text-align → Word 段落對齊。舊版完全沒讀，所有置中/右對齊都會丟失。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    align = None
    for name, value in _CSS_DECL_RE.findall(node.get('style') or ''):
        if name.strip().lower() == 'text-align':
            align = value.strip().lower()
    mapping = {
        'center': WD_ALIGN_PARAGRAPH.CENTER,
        'right': WD_ALIGN_PARAGRAPH.RIGHT,
        'left': WD_ALIGN_PARAGRAPH.LEFT,
        'justify': WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    if align in mapping:
        para.alignment = mapping[align]


def _add_table_to_docx(doc, node):
    """HTML table → python-docx 表格（保留儲存格內格式與跨欄）。

    舊版用 `cell.text = cell.text_content()`，那會把整格打成單一無格式 run
    ——表格裡的粗體、顏色、對齊全部消失。這裡改成對每格跑完整的 run 轉換。
    """
    rows = node.xpath('./tr | ./tbody/tr | ./thead/tr | ./tfoot/tr')
    if not rows:
        rows = node.xpath('.//tr')
    if not rows:
        return
    max_cols = max(
        sum(int(td.get('colspan') or 1) for td in row.xpath('./td | ./th'))
        for row in rows
    ) or 1

    table = doc.add_table(rows=len(rows), cols=max_cols)
    # 區塊容器（class="doc-block"）是條件區塊／稅額彙總的邊界，不是真表格，
    # 不可套有框線的樣式。'Table Normal' 是 Word 內建的無框線樣式。
    is_block = 'doc-block' in (node.get('class') or '')
    try:
        table.style = 'Table Normal' if is_block else 'Table Grid'
    except Exception:
        pass

    for r_idx, row in enumerate(rows):
        cells = row.xpath('./td | ./th')
        c_idx = 0
        for cell_node in cells:
            if c_idx >= max_cols:
                break
            span = int(cell_node.get('colspan') or 1)
            span = max(1, min(span, max_cols - c_idx))
            target = table.cell(r_idx, c_idx)
            if span > 1:
                try:
                    target = target.merge(table.cell(r_idx, c_idx + span - 1))
                except Exception:
                    pass
            # 清掉預設空段落，改用轉換出來的內容
            para = target.paragraphs[0]
            blocks = cell_node.xpath('./p | ./div')
            if blocks:
                for i, blk in enumerate(blocks):
                    tgt = para if i == 0 else target.add_paragraph()
                    _apply_paragraph_align(tgt, blk)
                    _add_runs_from_node(tgt, blk)
            else:
                _add_runs_from_node(para, cell_node)
            # <th> 預設粗體（HTML 語意），除非儲存格內已自行指定
            if (cell_node.tag or '').lower() == 'th':
                for r in para.runs:
                    if r.bold is None:
                        r.bold = True
            c_idx += span


def _html_node_to_docx(doc, node):
    """遞迴將 lxml HTML 節點轉換為 python-docx 結構。"""
    from docx.enum.text import WD_BREAK

    tag = (node.tag or '').lower() if isinstance(node.tag, str) else ''

    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        para = doc.add_heading(level=int(tag[1]))
        _apply_paragraph_align(para, node)
        _add_runs_from_node(para, node)

    elif tag == 'table':
        _add_table_to_docx(doc, node)

    elif tag == 'hr':
        doc.add_paragraph('─' * 40)

    elif tag == 'img':
        para = doc.add_paragraph()
        _emit_image(para, node)

    elif tag in ('ul', 'ol'):
        style = 'List Number' if tag == 'ol' else 'List Bullet'
        for child in node:
            if (child.tag or '').lower() == 'li':
                try:
                    para = doc.add_paragraph(style=style)
                except Exception:
                    para = doc.add_paragraph()
                _add_runs_from_node(para, child)

    elif tag in ('p', 'li', 'blockquote', 'pre'):
        # 空段落也要保留——多個空行是刻意的版面，吃掉會讓間距走樣。
        # 但只有 <br> 的段落（<p><br/></p>）視為空行即可。
        para = doc.add_paragraph()
        _apply_paragraph_align(para, node)
        _add_runs_from_node(para, node)

    elif _is_page_break(node):
        # 手動分頁。舊版落到 div 分支、沒有塊級子節點又沒有文字 → 整個被吃掉，
        # 使用者在編輯器插的分頁在 DOCX 裡完全消失（且無錯誤訊息）。
        para = doc.add_paragraph()
        para.add_run().add_break(WD_BREAK.PAGE)

    elif tag in ('div', 'section', 'article', 'main', 'aside',
                 'header', 'footer', 'body', 'span'):
        block_tags = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                      'table', 'ul', 'ol', 'hr', 'div', 'blockquote', 'pre'}
        has_block_children = any(
            (c.tag or '').lower() in block_tags for c in node
        )
        if not has_block_children:
            text = (node.text_content() or '').strip()
            has_img = len(node.xpath('.//img')) > 0
            if text or has_img:
                para = doc.add_paragraph()
                _apply_paragraph_align(para, node)
                _add_runs_from_node(para, node)
        else:
            for child in node:
                _html_node_to_docx(doc, child)

    # script/style/meta 等略過


# 超過此大小（bytes）自動存入 ir.attachment
CONTENT_SIZE_THRESHOLD = 500 * 1024  # 500 KB

import logging
_logger = logging.getLogger(__name__)


def _fix_docx_table_widths(docx_bytes, usable_w_mm):
    """修正 LibreOffice 生成的 DOCX 中所有表格寬度（含巢狀），使其符合頁面可用寬度。

    LO 24.2 以內建預設邊距（~5mm）計算表格寬，導致表格寬 200mm 而版心只有 170mm。
    CSS / inline style / !important 全部無效；唯一可靠解法是在 OOXML 層直接修正。

    修改範圍（三層同步）：
    1. <w:tblGrid> / <w:gridCol> — 欄寬網格（等比縮放）
    2. <w:tblW>                  — 表格總寬（設為 target_twips, type=dxa）
    3. <w:tcW>                   — 儲存格寬度（type=dxa 者等比縮放）

    失敗保護：任何異常回傳原始 bytes（優雅降級，確保使用者至少能下載檔案）。
    """
    try:
        from lxml import etree
        import zipfile

        WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

        def W(tag):
            return f'{{{WNS}}}{tag}'

        # mm → twips（1 inch = 1440 twips；1 inch = 25.4 mm）
        target_twips = round(usable_w_mm * 1440 / 25.4)

        # 只讀取 document.xml，其餘 DOCX 內容不解析（省記憶體）
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin:
            doc_xml_bytes = zin.read('word/document.xml')

        root = etree.fromstring(doc_xml_bytes)

        # 找出所有 w:tbl（含巢狀），lxml 的 findall 以文件順序回傳（前序）
        all_tbls = root.findall(f'.//{W("tbl")}')

        for tbl in all_tbls:
            # ── Step 1: 讀取並等比縮放 <w:tblGrid> ──────────────────────────
            tbl_grid = tbl.find(W('tblGrid'))
            grid_cols = tbl_grid.findall(W('gridCol')) if tbl_grid is not None else []

            current_total = (
                sum(int(c.get(W('w'), 0)) for c in grid_cols)
                if grid_cols else 0
            )

            # current_total 為 0（空表格）或已在合理範圍（±2%）則跳過
            if current_total <= 0:
                continue
            if abs(current_total - target_twips) / target_twips < 0.02:
                continue

            scale = target_twips / current_total

            # 等比縮放 gridCol，最後一欄補足捨入誤差
            total_assigned = 0
            for i, col in enumerate(grid_cols):
                if i < len(grid_cols) - 1:
                    new_w = max(1, round(int(col.get(W('w'), 0)) * scale))
                else:
                    new_w = max(1, target_twips - total_assigned)
                col.set(W('w'), str(new_w))
                total_assigned += new_w

            # ── Step 2: 修正 <w:tblW> ────────────────────────────────────────
            tbl_pr = tbl.find(W('tblPr'))
            if tbl_pr is not None:
                tbl_w = tbl_pr.find(W('tblW'))
                if tbl_w is None:
                    tbl_w = etree.SubElement(tbl_pr, W('tblW'))
                tbl_w.set(W('w'), str(target_twips))
                tbl_w.set(W('type'), 'dxa')

            # ── Step 3: 等比縮放所有 <w:tcW>（type=dxa）──────────────────────
            for tc in tbl.iter(W('tc')):
                tc_pr = tc.find(W('tcPr'))
                if tc_pr is None:
                    continue
                tc_w = tc_pr.find(W('tcW'))
                if tc_w is None or tc_w.get(W('type')) != 'dxa':
                    continue
                old_w = int(tc_w.get(W('w'), 0))
                if old_w <= 0:
                    continue
                tc_w.set(W('w'), str(max(1, round(old_w * scale))))

        # ── 重新打包 DOCX（只替換 document.xml，其餘保持原樣）────────────────
        modified_xml = etree.tostring(
            root, xml_declaration=True, encoding='UTF-8', standalone=True
        )
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin:
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = (
                        modified_xml
                        if item.filename == 'word/document.xml'
                        else zin.read(item.filename)
                    )
                    zout.writestr(item, data)
        output.seek(0)
        return output.read()

    except Exception as e:
        _logger.warning('[DocEditor] _fix_docx_table_widths 失敗，回傳原始 DOCX: %s', e)
        return docx_bytes  # 優雅降級：確保使用者至少可下載（邊距可能有誤但檔案可開啟）


class DocDocument(models.Model):
    _name = 'doc.document'
    _description = '文件'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'doc.render.mixin']
    _order = 'write_date desc'

    name = fields.Char(string='文件名稱', required=True, default='未命名文件', tracking=True)

    # 內容欄位（sanitize=False，由 Server-Side Sanitizer 在 create/write 中處理）
    content_html = fields.Html(
        string='內容 (HTML 備份)',
        sanitize=False,
        sanitize_attributes=False,
    )
    # Canvas 引擎結構化資料（主要儲存與讀取來源）
    content_json = fields.Text(
        string='Canvas 結構化內容 (JSON)',
        help='Canvas 編輯器的結構化文件資料，為主要儲存與讀取來源',
    )

    # DOCX 模板引擎欄位（後端 docxtpl 填充路線）
    template_docx = fields.Binary(
        string='DOCX 模板原始檔',
        attachment=True,
        help='上傳的 DOCX 模板（+++INS+++語法已自動轉換為 Jinja2），由後端 docxtpl 填充',
    )
    template_filename = fields.Char(string='模板檔名')
    template_variables = fields.Text(
        string='模板變數清單 (JSON)',
        help='上傳時自動偵測的 {{ variable }} 名稱 JSON 陣列',
    )

    header_html = fields.Html(
        string='頁首',
        sanitize=False,
        sanitize_attributes=False,
    )
    footer_html = fields.Html(
        string='頁尾',
        sanitize=False,
        sanitize_attributes=False,
    )

    # 文件設定
    model_id = fields.Many2one(
        'ir.model',
        string='關聯模型',
        ondelete='set null',
        help='用於欄位變數渲染的目標模型',
    )
    # Many2oneReference 的 model_field 必須指向「存模型技術名稱字串」的 Char 欄位
    # （如 'res.partner'），不能直接指向 model_id（Many2one→ir.model），否則
    # web_read 會執行 self.env[ir.model(id,)] 而拋 KeyError，導致後台清單/表單 500
    model_name = fields.Char(
        string='關聯模型技術名稱',
        related='model_id.model',
        store=True,
        index=True,
        help='由 model_id 自動帶入的技術名稱，供 res_id (Many2oneReference) 使用',
    )
    res_id = fields.Many2oneReference(
        model_field='model_name',
        string='關聯記錄 ID',
        index=True,
        help='與本文件雙向關聯的目標記錄 ID（搭配 doc.linked.mixin 使用）',
    )
    field_aliases = fields.Json(
        string='欄位別名對映',
        default=dict,
        help=(
            '中文 token 到 Jinja2 表達式的對映，例如 '
            '{"工程名稱": "object.project_id.name"}。'
            '渲染時 _render_template 會先把文件內 《token》 包裝展開成 '
            '{{ expression }} 再交給 Jinja2。'
        ),
    )
    # ─── 版本管理（W7-8 P1-1）─────────────────────────────────────
    # 設計（修正版）：把版本快照陣列直接存在 doc.document.versions_data (fields.Json)
    #       原本想透過 mail.thread message body 內嵌 base64 JSON，但 body 是 HTML
    #       field 會被 sanitizer 處理（剝除自訂 data-* 屬性），無法 round-trip。
    #       現在把實際 snapshot 內容存在 versions_data，message_post 只記摘要。
    version_number = fields.Integer(
        string='版本號',
        default=0,
        copy=False,
        help='文件版本流水號，每次儲存版本快照時 +1',
    )
    versions_data = fields.Json(
        string='版本快照陣列',
        default=list,
        copy=False,
        help='儲存所有版本快照的 JSON 陣列。每筆含 version_no/created_at/'
             'author_id/author_name/label/content_html/content_json。',
    )
    template_id = fields.Many2one(
        'doc.template',
        string='使用範本',
        ondelete='set null',
    )
    # ─── Phase 3（藥丸改版）：建立時快照 ─────────────────────────────
    # 決策一：值在建立文件時凍結一次，之後改來源記錄不會動到文件。
    # 已簽的合約不該因為有人改了客戶地址就跟著變；代價是需要這兩個欄位
    # 記錄「何時、對哪筆記錄」凍結，並提供「重新帶值」與過期偵測。
    snapshot_date = fields.Datetime(
        string='值凍結時間',
        copy=False,
        readonly=True,
        help='最後一次把模型變數求值寫入文件內容的時間。空值表示尚未帶入過值。',
    )
    snapshot_res_id = fields.Integer(
        string='凍結來源記錄 ID',
        copy=False,
        readonly=True,
        help='上次快照是對哪一筆記錄取值；與目前的 res_id 不同時代表文件已被改綁。',
    )
    source_output_id = fields.Many2one(
        'doc.output',
        string='來源輸出紀錄',
        copy=False,
        readonly=True,
        ondelete='set null',
        help='本文件由某筆輸出紀錄「建立可編輯副本」而來。'
             '輸出本身唯讀（稽核要求），副本可編輯；此欄位保留追溯關係。',
    )
    snapshot_is_stale = fields.Boolean(
        string='來源已變更',
        compute='_compute_snapshot_is_stale',
        help='來源記錄在快照之後又被修改過，文件內的值可能已過期。',
    )
    page_format = fields.Selection([
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('A5', 'A5'),
        ('letter', 'Letter'),
        ('legal', 'Legal'),
    ], string='頁面格式', default='A4')
    margin_top = fields.Integer(string='上邊距 (px)', default=96)
    margin_bottom = fields.Integer(string='下邊距 (px)', default=96)
    margin_left = fields.Integer(string='左邊距 (px)', default=96)
    margin_right = fields.Integer(string='右邊距 (px)', default=96)
    has_different_first_page = fields.Boolean(string='首頁不同頁首/頁尾', default=False)
    first_header_html = fields.Html(string='首頁頁首', sanitize=False)
    first_footer_html = fields.Html(string='首頁頁尾', sanitize=False)

    # 協作者
    collaborator_ids = fields.Many2many(
        'res.users',
        'doc_document_collaborator_rel',
        'document_id', 'user_id',
        string='協作者',
    )

    # 多公司隔離
    company_id = fields.Many2one(
        'res.company',
        string='公司',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    # 大文件 attachment 策略（>500KB 自動存入 ir.attachment）
    content_attachment_id = fields.Many2one(
        'ir.attachment',
        string='內容附件（大文件）',
        ondelete='set null',
    )
    is_large_document = fields.Boolean(string='大文件', default=False)

    # 多欄排版預設值
    default_column_count = fields.Selection([
        ('1', '1 欄'), ('2', '2 欄'), ('3', '3 欄'),
    ], string='預設欄數', default='1')
    default_column_gap = fields.Integer(string='欄間距 (px)', default=24)
    column_rule_style = fields.Selection([
        ('none', '無'), ('solid', '實線'), ('dashed', '虛線'), ('dotted', '點線'),
    ], string='欄分隔線', default='none')

    # 需要 sanitize 的 HTML 欄位清單
    _HTML_FIELDS = ('content_html', 'header_html', 'footer_html',
                    'first_header_html', 'first_footer_html')

    # ─── CRUD Hooks ─────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """建立文件時：1) sanitize HTML 欄位 2) 若指定 template_id 但 content_html
        為空，自動把 template.content_html / page_format 複製過來。

        為何在 create() 而非 onchange：onchange 只在後台 Form view 觸發，
        Portal Modal / API / 程式內部 .create() 都不會走 onchange；放在 create()
        裡可以涵蓋所有建立路徑（後台、Portal、ChienYi mixin、單元測試）。
        """
        sanitizer = self.env['doc.sanitizer']
        Template = self.env['doc.template']
        for vals in vals_list:
            # 範本自動填充：template_id 有給但內容沒給（或空）
            # Phase 3：判斷條件必須同時看 content_json——範本改用 Canvas JSON 為
            # 權威格式後，可能有 content_json 卻沒有 content_html，舊條件會整段跳過。
            if vals.get('template_id') and not (
                vals.get('content_html') or vals.get('content_json')
            ):
                template = Template.browse(vals['template_id'])
                if template.exists():
                    if template.content_html:
                        vals['content_html'] = template.content_html
                    # content_json 是權威格式，必須一起複製。只複製 HTML 的話，
                    # 新文件的藥丸（extension.dobtorField）會整組遺失，
                    # 後續 _apply_value_snapshot 找不到任何可求值的東西。
                    if template.content_json:
                        vals['content_json'] = template.content_json
                    if template.page_format and not vals.get('page_format'):
                        vals['page_format'] = template.page_format
            for field in self._HTML_FIELDS:
                if vals.get(field):
                    vals[field] = sanitizer.sanitize_html(vals[field])
        return super().create(vals_list)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """後台 Form view 選 / 切換範本時，直接覆寫 content_html / page_format。

        為何不保護「已有內容」：在 Form view 顯式切換 template_id 是使用者
        刻意動作，意圖就是要新範本內容。若怕誤覆寫已編輯文件，使用者應該
        先儲存版本快照（Ctrl+Shift+S）或不要切 template。

        實際情境（Sprint 16 bug）：使用者建文件 → 選範本 A → 切到範本 B →
        舊邏輯因 content_html 已有 A 的內容而拒絕覆寫 → 編輯器顯示 A 而非 B
        → 使用者誤以為「範本沒套用」。

        例外：當前 content_html 看起來是「使用者編輯過」（不等於任何 template
        的 content_html），仍直接覆寫；保護機制留給「儲存版本快照」工作流。
        """
        for rec in self:
            if not rec.template_id:
                continue
            tpl = rec.template_id
            if tpl.content_html:
                rec.content_html = tpl.content_html
            # Phase 3：content_json 是權威格式，必須一併帶過來。
            # 只複製 content_html 的話，新文件會從 HTML 重建元素樹，
            # 藥丸的 extension.dobtorField 會在轉換中整組遺失——
            # 使用者看到的是「範本有變數、文件沒有」。
            if tpl.content_json:
                rec.content_json = tpl.content_json
            if tpl.page_format:
                rec.page_format = tpl.page_format

    def write(self, vals):
        sanitizer = self.env['doc.sanitizer']
        for field in self._HTML_FIELDS:
            if vals.get(field):
                vals[field] = sanitizer.sanitize_html(vals[field])

        # 大文件自動存入 attachment
        if 'content_html' in vals and vals['content_html']:
            html = vals['content_html']
            if len(html.encode('utf-8')) > CONTENT_SIZE_THRESHOLD:
                # 各筆記錄分別建立/更新 attachment，不共用 vals
                base_vals = dict(vals)
                base_vals.pop('content_html', None)
                base_vals['is_large_document'] = True
                base_vals['content_html'] = ''
                for rec in self:
                    att = rec._store_content_as_attachment(html)
                    super(DocDocument, rec).write(
                        dict(base_vals, content_attachment_id=att.id)
                    )
                return True
            else:
                # 文件縮小：清除舊 attachment
                vals['is_large_document'] = False
                vals['content_attachment_id'] = False

        return super().write(vals)

    def _store_content_as_attachment(self, html):
        """將大文件內容存入 ir.attachment。"""
        self.ensure_one()
        data = base64.b64encode(html.encode('utf-8'))
        if self.content_attachment_id:
            self.content_attachment_id.write({'datas': data})
            return self.content_attachment_id
        return self.env['ir.attachment'].create({
            'name': f'doc_content_{self.id}.html',
            'type': 'binary',
            'datas': data,
            'res_model': 'doc.document',
            'res_id': self.id,
        })

    def get_content_html(self):
        """統一取得 HTML 內容（自動判斷來源）。"""
        self.ensure_one()
        if self.is_large_document and self.content_attachment_id:
            return base64.b64decode(self.content_attachment_id.datas).decode('utf-8')
        return self.content_html or ''

    # ─── L2-v2 工具方法：alias 自動生成 + 掃描轉換 ─────────────────────
    def init_aliases_from_model(self, overwrite=False):
        """根據 doc.model_id 自動生成 field_aliases 對映。

        參數：
          overwrite=False 時，既有 token 保留不動；新欄位才加入。
          overwrite=True 時，整批以 model 欄位重建（會清掉使用者自訂的 token）。

        生成規則：
          - 一般欄位：「中文 description」→ `object.field_name`
          - date / datetime：用 format_date(object.x)
          - selection：用 selection_label('x')
          - many2one：「中文 description」→ `object.field_name.display_name`
        """
        self.ensure_one()
        if not self.model_id:
            return {'success': False, 'error': '此文件未設定 model_id'}
        model_name = self.model_id.model
        if model_name not in self.env:
            return {'success': False, 'error': f"模型 '{model_name}' 不存在"}

        existing = dict(self.field_aliases or {})
        added = []
        skipped = []
        IrModelFields = self.env['ir.model.fields']
        ttypes = ('char', 'text', 'integer', 'float', 'monetary',
                  'date', 'datetime', 'boolean', 'selection', 'many2one')
        fields = IrModelFields.search([
            ('model', '=', model_name),
            ('store', '=', True),
            ('ttype', 'in', list(ttypes)),
        ], order='field_description asc')

        for f in fields:
            label = (f.field_description or '').strip()
            if not label:
                continue
            # 計算 expression
            if f.ttype == 'date' or f.ttype == 'datetime':
                expr = f'format_date(object.{f.name})'
            elif f.ttype == 'selection':
                expr = f"selection_label('{f.name}')"
            elif f.ttype == 'many2one':
                expr = f'object.{f.name}.display_name'
            else:
                expr = f'object.{f.name}'

            if label in existing and not overwrite:
                skipped.append(label)
                continue
            existing[label] = expr
            added.append(label)

        self.write({'field_aliases': existing})
        return {
            'success': True,
            'aliases': existing,
            'added': added,
            'skipped': skipped,
        }

    def scan_and_convert_to_alias(self):
        """掃 content_html / content_json 內所有 `{{ ... }}` 文字，根據 field_aliases
        反查對應的中文 token，把找得到的整段替換成 《token》。

        反查邏輯：
          - 抓 {{ EXPRESSION }} 內的 EXPRESSION 字串（去前後空白）
          - 在 field_aliases value 中找完全相等的 expression → 取對應 key (token)
          - 沒找到 → 保留原文（不動）

        回傳 {converted: int, skipped: int}
        """
        self.ensure_one()
        import re as _re
        import json as _json
        # 合併 template + 自身 alias map（用 mixin 的合併邏輯）
        aliases = self._collect_field_aliases()
        if not aliases:
            return {'success': False, 'error': '尚無 alias 對映可供反查（請先按「自動生成」或設定範本）'}

        # 拆出 token alias（中文 key）與 varname alias（純識別符 key）
        # 反查策略：
        #   - 直接命中：{{ inner }} 內 inner 是某 alias value（expression）→ 找 token key
        #   - 兩步命中：inner 是 varname_alias key → 取對應 expression → 再從 token_alias 反查
        token_alias = {}  # key=中文 token, value=expression
        varname_alias = {}  # key=純變數名, value=expression
        expr_to_token = {}
        for k, v in aliases.items():
            ks = str(k).strip()
            vs = str(v).strip()
            if not ks or not vs:
                continue
            if _re.match(r'^[A-Za-z_][\w]*$', ks):
                varname_alias[ks] = vs
            else:
                token_alias[ks] = vs
                expr_to_token[vs] = ks

        pat = _re.compile(r'\{\{\s*(.+?)\s*\}\}')
        converted_total = [0]
        skipped_total = [0]

        def _replace_text(text):
            if not text:
                return text
            def _r(m):
                inner = m.group(1).strip()
                # 1) 直接用 expression 反查 token
                token = expr_to_token.get(inner)
                if token:
                    converted_total[0] += 1
                    return f'《{token}》'
                # 2) 變數名兩步反查
                if inner in varname_alias:
                    expr = varname_alias[inner]
                    token = expr_to_token.get(expr)
                    if token:
                        converted_total[0] += 1
                        return f'《{token}》'
                skipped_total[0] += 1
                return m.group(0)
            return pat.sub(_r, text)

        # content_html
        new_html = _replace_text(self.content_html or '')

        # content_json 遞迴
        cj = self.content_json
        if isinstance(cj, str):
            try:
                cj = _json.loads(cj)
            except Exception:
                cj = None

        def _walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == 'value' and isinstance(v, str):
                        node[k] = _replace_text(v)
                    else:
                        _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        if cj:
            _walk(cj)

        vals = {'content_html': new_html}
        if cj:
            vals['content_json'] = cj
        self.write(vals)
        return {
            'success': True,
            'converted': converted_total[0],
            'skipped': skipped_total[0],
        }

    # ─── Actions ─────────────────────────────────────────────────────

    @api.depends('snapshot_date', 'res_id', 'model_id')
    def _compute_snapshot_is_stale(self):
        """比對快照時間與來源記錄的 write_date。

        快照語意最容易造成的誤解是「我改了客戶名稱怎麼文件沒變」。
        把過期狀態算出來攤在畫面上，比任何說明文件有效。
        """
        for rec in self:
            rec.snapshot_is_stale = False
            if not rec.snapshot_date:
                continue
            source = rec._resolve_bound_record()
            if not source:
                continue
            write_date = getattr(source, 'write_date', False)
            if write_date and write_date > rec.snapshot_date:
                rec.snapshot_is_stale = True

    def _apply_value_snapshot(self, record=None):
        """對 content_json 內的模型變數藥丸求值並凍結，同步更新 content_html。

        伺服器端快照必須一併更新 content_html——前端沒有跑，攤平後的 HTML
        不會自己更新，匯出鏈與全文檢索都會讀到舊值。
        """
        self.ensure_one()
        source = record or self._resolve_bound_record()
        if not source:
            return False
        tree = self._parse_content_json(self.content_json)
        if tree is None:
            return False
        tree = self._snapshot_content_json(tree, source)
        import copy as _copy
        flat = self._flatten_content_json(_copy.deepcopy(tree))
        self.write({
            'content_json': json.dumps(tree, ensure_ascii=False),
            'content_html': self._content_json_to_html(flat),
            'snapshot_date': fields.Datetime.now(),
            'snapshot_res_id': source.id,
        })
        return True

    def action_refresh_values(self):
        """重新帶值：對目前綁定的記錄重跑一次快照。

        會覆蓋使用者在藥丸上做過的人工修改，故 view 上帶 confirm。
        """
        self.ensure_one()
        if not self._apply_value_snapshot():
            raise UserError(
                '無法重新帶值：此文件未綁定記錄，或內容尚未以編輯器儲存過。'
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已重新帶值',
                'message': '模型變數已依來源記錄的最新內容更新。',
                'type': 'success',
                'sticky': False,
            },
        }

    def _export_body_html(self, record=None):
        """匯出用的 body HTML。

        優先走 content_json（Phase 3 起的權威格式）：攤平藥丸 → 轉 HTML。
        沒有 content_json 的舊文件退回 content_html + alias 正則路徑（退場期）。

        record 只在「這份文件從未快照過」時才用來即時補值——已快照的文件
        不重新求值，否則就違背了決策一的凍結語意。
        """
        self.ensure_one()
        tree = self._parse_content_json(self.content_json)
        if tree is not None:
            # only_pending：只補「還沒凍結過」的藥丸。
            # 舊寫法用文件級的 snapshot_date 當開關，會漏掉「快照之後才新增的藥丸」
            # ——它們會以標籤文字（如「客戶名稱」）原樣印進 PDF，且無任何錯誤訊息。
            if record is not None:
                tree = self._snapshot_content_json(tree, record, only_pending=True)
            return self._content_json_to_html(self._flatten_content_json(tree))
        # 舊文件：沒有 content_json，退回 content_html + alias 正則（退場期路徑）
        body = self.get_content_html()
        if record:
            body = self._render_template(body, record)
        return body

    def action_open_editor(self):
        """開啟全螢幕文件編輯器。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'dobtor_doc_editor.action_doc_editor',
            'context': {
                'doc_id': self.id,
                'doc_name': self.name,
            },
            'target': 'fullscreen',
        }

    @api.model
    def action_new_and_open_editor(self):
        """建一份空白文件後直接進編輯器（跳過表單）。

        清單的「新增」與點開一筆都走編輯器——建立與開啟兩個入口要一致，
        否則「新增」給表單、「點開」給編輯器，使用者會以為那是兩種東西。

        範本取「空白文件」那一張（模組 data 帶的）。找不到就不帶範本，
        編輯器會開一份真的空白的——比拋例外好。
        """
        template = self.env.ref(
            'dobtor_doc_editor.doc_template_blank', raise_if_not_found=False)
        values = {'name': _('未命名文件')}
        if template:
            values['template_id'] = template.id
        doc = self.create(values)
        return doc.action_open_editor()

    def action_open_settings_form(self):
        """開這份文件的表單（清單點開一筆會直接進編輯器，表單要有另一個入口）。

        表單上才有的東西：關聯模型與記錄、協作者、版本、保留政策。那些是
        設定而不是內容，所以不搬進編輯器，但一定要留得到的路。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('文件設定'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_quick_preview(self):
        """從 form view 一鍵預覽——開新分頁顯示渲染後 HTML（含 chip 樣式）。

        需要 doc 同時設好 model_id 與 res_id；否則回提示 message。
        """
        self.ensure_one()
        if not self.model_id or not self.res_id:
            from odoo.exceptions import UserError
            raise UserError(
                "此文件未綁定模型或記錄，無法預覽。\n"
                "請先設定「關聯模型」與「關聯記錄 ID」。"
            )
        return {
            'type': 'ir.actions.act_url',
            'url': f'/dobtor_doc/preview/{self.id}',
            'target': 'new',
        }

    def action_export_pdf(self):
        """匯出 PDF 並下載。

        若此文件已綁定 model_id + res_id，自動帶入對應 record，
        讓 alias（《token》/ {{ varname }}）走完整渲染，
        匯出的 PDF 直接呈現實際欄位值，而非 token 原文。
        """
        self.ensure_one()
        record = self._resolve_bound_record()
        pdf_bytes = self._generate_pdf(record=record)
        self.env['doc.editor.export.log'].record_export(
            self, 'pdf', with_alias=record is not None,
            file_size=len(pdf_bytes), source='form_button',
        )
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'res_model': 'doc.document',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_export_docx(self):
        """匯出 DOCX 並下載。

        若此文件已綁定 model_id + res_id，自動帶入對應 record，
        讓 alias 完整渲染，匯出的 DOCX 直接呈現實際欄位值。
        """
        self.ensure_one()
        record = self._resolve_bound_record()
        docx_bytes = self._generate_docx_via_libreoffice(record=record)
        self.env['doc.editor.export.log'].record_export(
            self, 'docx', with_alias=record is not None,
            file_size=len(docx_bytes), source='form_button',
        )
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.docx',
            'type': 'binary',
            'datas': base64.b64encode(docx_bytes),
            'res_model': 'doc.document',
            'res_id': self.id,
            'mimetype': ('application/vnd.openxmlformats-officedocument'
                         '.wordprocessingml.document'),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _resolve_bound_record(self):
        """取出此文件綁定的 record（model_id + res_id）；取不到回 None。

        供匯出流程共用：有綁定就讓 alias 走完整渲染輸出實際值，
        沒綁定（或 model/record 已不存在）就回 None，輸出 token 原文。
        """
        self.ensure_one()
        if not (self.model_id and self.res_id):
            return None
        try:
            rec = self.env[self.model_id.model].browse(self.res_id)
            return rec if rec.exists() else None
        except Exception:
            return None

    def action_batch_export_pdf_zip(self):
        """批次匯出：把選取的多份文件各自渲染成 PDF，打包為單一 zip 下載。

        從 list view 的「動作」選單觸發（self 為多筆 recordset）。
        每份文件各自帶入其綁定 record，alias 渲染成實際值。
        單份失敗不中斷整批：以 _ERROR.txt 留下錯誤訊息一併打包。
        """
        if not self:
            raise UserError("請先勾選要匯出的文件。")

        zip_buffer = io.BytesIO()
        used_names = {}
        ok_count = 0
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for doc in self:
                # 檔名去重（同名文件加序號），並清掉路徑分隔字元
                safe_name = (doc.name or f'document_{doc.id}').replace('/', '_').replace('\\', '_')
                count = used_names.get(safe_name, 0)
                used_names[safe_name] = count + 1
                if count:
                    safe_name = f'{safe_name}_{count + 1}'
                try:
                    record = doc._resolve_bound_record()
                    pdf_bytes = doc._generate_pdf(record=record)
                    zf.writestr(f'{safe_name}.pdf', pdf_bytes)
                    self.env['doc.editor.export.log'].record_export(
                        doc, 'pdf', with_alias=record is not None,
                        file_size=len(pdf_bytes), source='batch',
                    )
                    ok_count += 1
                except Exception as exc:
                    zf.writestr(f'{safe_name}_ERROR.txt',
                                f'匯出失敗：{exc}'.encode('utf-8'))

        if not ok_count:
            raise UserError("批次匯出失敗：沒有任何文件成功產生 PDF。")

        zip_bytes = zip_buffer.getvalue()
        filename = (f'documents_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}'
                    f'_{ok_count}docs.zip')
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(zip_bytes),
            'mimetype': 'application/zip',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    # ─── 後端匯出邏輯 ─────────────────────────────────────────────────

    def _build_full_html(self, rendered_body=None):
        """組合完整的 HTML 文件（頁首＋內文＋頁尾），含 CSS 設定。"""
        self.ensure_one()
        body = rendered_body or self.get_content_html()
        header = self.header_html or ''
        footer = self.footer_html or ''

        page_sizes = {
            'A4': ('210mm', '297mm'),
            'A3': ('297mm', '420mm'),
            'A5': ('148mm', '210mm'),
            'letter': ('215.9mm', '279.4mm'),
            'legal': ('215.9mm', '355.6mm'),
        }
        w, h = page_sizes.get(self.page_format, ('210mm', '297mm'))

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@page {{
    size: {w} {h};
}}
body {{
    font-family: 'Microsoft JhengHei', 'Noto Sans TC', 'Arial', sans-serif;
    font-size: 12pt;
    line-height: 1.6;
    color: #333;
    margin: 0;
    padding: 0;
}}
.doc-header {{ margin-bottom: 12px; border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
.doc-footer {{ margin-top: 12px; border-top: 1px solid #ddd; padding-top: 8px; font-size: 10pt; }}
.doc-page-break {{ page-break-after: always; }}
.doc-field-token {{
    background: #e3f2fd;
    border: 1px solid #90caf9;
    border-radius: 3px;
    padding: 1px 4px;
    font-family: monospace;
    font-size: 0.875em;
    color: #1565c0;
}}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 6px; }}
/* 區塊容器：條件區塊／稅額彙總用單格表格當可靠邊界，但輸出時不是表格 */
.doc-block, .doc-block td {{ border: none; padding: 0; }}
</style>
</head>
<body>
{'<div class="doc-header">' + header + '</div>' if header else ''}
<div class="doc-body">{body}</div>
{'<div class="doc-footer">' + footer + '</div>' if footer else ''}
</body>
</html>"""

    def _generate_pdf(self, record=None):
        """使用 Odoo 內建 wkhtmltopdf 產生 PDF。"""
        self.ensure_one()
        body = self._export_body_html(record)

        full_html = self._build_full_html(rendered_body=body)
        Report = self.env['ir.actions.report']
        # px → mm（96dpi：1px = 25.4/96 mm）
        px_to_mm = 25.4 / 96
        pdf_bytes = Report._run_wkhtmltopdf(
            [full_html],          # str，不預先 encode（_run_wkhtmltopdf 內部自行 encode）
            landscape=False,
            specific_paperformat_args={
                # 傳入實際 mm 值，由 wkhtmltopdf CLI 套用正確邊距。
                # @page CSS 只保留 size，避免 CSS margin 與 CLI margin 疊加。
                # left/right 需依賴本模組 report_overrides.py 覆寫的支援。
                'data-report-margin-top':    round(self.margin_top    * px_to_mm, 1),
                'data-report-margin-bottom': round(self.margin_bottom * px_to_mm, 1),
                'data-report-margin-left':   round(self.margin_left   * px_to_mm, 1),
                'data-report-margin-right':  round(self.margin_right  * px_to_mm, 1),
            },
        )
        return pdf_bytes

    def _wrap_html_for_libreoffice(self, body_html):
        """為 LibreOffice 建立最小化的標準 HTML 封裝。

        包含 @page CSS 以確保 DOCX 邊距與螢幕上的 doc-page-sheet 一致。
        注意：此 HTML 僅供 LibreOffice 中介轉換，不會存入 DB 或顯示給使用者。
        """
        # px → cm（96dpi：1px = 2.54/96 cm）
        px_to_cm = 2.54 / 96
        page_sizes_cm = {
            'A4':     (21.0,   29.7),
            'A3':     (29.7,   42.0),
            'A5':     (14.8,   21.0),
            'letter': (21.59,  27.94),
            'Letter': (21.59,  27.94),
            'legal':  (21.59,  35.56),
            'Legal':  (21.59,  35.56),
        }
        w_cm, h_cm = page_sizes_cm.get(self.page_format, (21.0, 29.7))
        mt = round(self.margin_top    * px_to_cm, 2)
        mr = round(self.margin_right  * px_to_cm, 2)
        mb = round(self.margin_bottom * px_to_cm, 2)
        ml = round(self.margin_left   * px_to_cm, 2)
        usable_w_cm = round(w_cm - ml - mr, 2)
        return f"""<html xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:w="urn:schemas-microsoft-com:office:word"
  xmlns="http://www.w3.org/TR/REC-html40">
<head>
<meta charset="utf-8">
<style>
@page {{ size: {w_cm}cm {h_cm}cm; margin: {mt}cm {mr}cm {mb}cm {ml}cm; }}
body {{ font-family: sans-serif; max-width: {usable_w_cm}cm; margin: 0 auto; }}
table {{ border-collapse: collapse; }}
td, th {{ border: 1px solid black; padding: 4px; word-break: break-word; }}
/* 區塊容器：同 _build_full_html，兩條路徑要一致否則 PDF 與 DOCX 版面不同 */
.doc-block, .doc-block td {{ border: none; padding: 0; }}
img {{ max-width: 100%; height: auto; }}
/* 手動分頁：_build_full_html（PDF 用）有這條，這裡原本漏了，
   導致同一份文件匯出 PDF 有分頁、匯出 DOCX 卻靜默少了分頁。 */
.doc-page-break {{ page-break-after: always; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    def _generate_docx_via_libreoffice(self, record=None):
        """使用 LibreOffice headless 將 HTML 轉換為 DOCX。
        LibreOffice 不可用時自動 fallback 至 python-docx。
        """
        self.ensure_one()
        import shutil
        if not shutil.which('soffice'):
            # Fallback：使用 python-docx（已 pip install）
            return self._generate_docx_via_python(record)

        body = self._export_body_html(record)

        # 使用專為 LibreOffice 設計的最小化 HTML 封裝
        # （不用 _build_full_html，避免 @page CSS 觸發 LO MIME 誤判）
        lo_html = self._wrap_html_for_libreoffice(body)

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, 'input.html')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(lo_html)

            result = subprocess.run(
                [
                    'soffice', '--headless', '--norestore',
                    # .html 副檔名已足夠讓 LO 識別輸入格式（不需 --infilter）
                    # 'MS Word 2007 XML' 是 LO 的 DOCX export filter 正式名稱，
                    # 明確指定可防止 LO 找不到 export filter 而失敗
                    '--convert-to', 'docx:MS Word 2007 XML',
                    '--outdir', tmpdir,
                    html_path,
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise UserError(
                    f'LibreOffice 轉換失敗：{result.stderr.decode("utf-8", errors="replace")}'
                )

            docx_path = os.path.join(tmpdir, 'input.docx')
            if not os.path.exists(docx_path):
                # LO 有時以原始檔名為基礎產生輸出，嘗試搜尋
                candidates = [
                    f for f in os.listdir(tmpdir)
                    if f.endswith('.docx')
                ]
                if candidates:
                    docx_path = os.path.join(tmpdir, candidates[0])
                else:
                    raise UserError(
                        'LibreOffice 轉換後找不到輸出檔案。'
                        f'（stderr: {result.stderr.decode("utf-8", errors="replace")[:500]}）'
                    )

            with open(docx_path, 'rb') as f:
                raw_bytes = f.read()

        # 後處理：修正 LO 以內建預設邊距計算的表格寬度（200mm → 實際版心寬度）
        px_to_mm = 25.4 / 96
        page_w_map = {
            'A4': 210, 'A3': 297, 'A5': 148,
            'letter': 215.9, 'Letter': 215.9,
            'legal': 215.9, 'Legal': 215.9,
        }
        w_mm = page_w_map.get(self.page_format, 210)
        usable_mm = w_mm - (self.margin_left * px_to_mm) - (self.margin_right * px_to_mm)
        return _fix_docx_table_widths(raw_bytes, usable_mm)

    def _generate_docx_via_python(self, record=None):
        """使用 python-docx 將 HTML 轉換為 DOCX（LibreOffice 不可用時的 fallback）。

        實作已抽到 doc.render.mixin._docx_bytes_from_html()——報表引擎的
        doc.output 也要能匯出 DOCX，邏輯綁在 doc.document 的欄位上就沒法共用。
        本方法保留為對外介面（既有呼叫端與測試不受影響）。
        """
        self.ensure_one()
        return self._docx_bytes_from_html(
            self._export_body_html(record),
            page_format=self.page_format,
            margins={
                'top': self.margin_top,
                'bottom': self.margin_bottom,
                'left': self.margin_left,
                'right': self.margin_right,
            },
            # 直接給 HTML：壓成純文字會讓頁碼變成字面的「頁碼」兩字
            header_text=self.header_html or '',
            footer_text=self.footer_html or '',
        )

    # ─── 版本快照（W7-8 P1-1 重構版）─────────────────────────────────
    # 把實際 snapshot 內容存在 versions_data (fields.Json)，避開 mail.thread
    # body sanitizer 對自訂 data-* 屬性的清洗。mail.thread 仍接收摘要訊息，
    # 提供 audit trail 與 chatter UI 友善體驗。
    #
    # 對外 ID = version_number（自然遞增整數），不再用 message_id 當 key。

    def action_save_version(self, label=None):
        """儲存版本快照。

        Args:
            label: 使用者可自填的版本說明（如「會議結論定稿」）。

        Returns:
            dict: {'version_number': N, 'message_id': msg.id}
        """
        self.ensure_one()
        self.version_number = (self.version_number or 0) + 1
        version_no = self.version_number

        # 寫進 versions_data 陣列（避開 sanitizer）
        # JSON field 會自動序列化；用 list 而非 set 因為要保留順序
        versions = list(self.versions_data or [])
        versions.append({
            'version_no': version_no,
            'created_at': fields.Datetime.now().isoformat(),
            'author_id': self.env.user.id,
            'author_name': self.env.user.name or '匿名',
            'label': label or '',
            'content_html': self.get_content_html() or '',
            'content_json': self.content_json or '',
        })
        self.versions_data = versions

        # 摘要訊息送 chatter（不含 content，只當 audit trail）
        summary = (
            f'<p><strong>版本 v{version_no}</strong>'
            + (f' — {label}' if label else '')
            + '</p>'
        )
        msg = self.message_post(
            body=summary,
            subtype_xmlid='mail.mt_note',
            message_type='comment',
        )
        return {
            'version_number': version_no,
            'message_id': msg.id,
        }

    def get_version_list(self):
        """取得版本快照清單（不含 content，輕量）。"""
        self.ensure_one()
        versions = list(self.versions_data or [])
        # 降序：最新版在前
        versions_sorted = sorted(
            versions,
            key=lambda v: v.get('version_no', 0),
            reverse=True,
        )
        return [
            {
                'version_id': v.get('version_no'),
                'version_number': v.get('version_no'),
                'date': v.get('created_at'),
                'author_id': v.get('author_id'),
                'author_name': v.get('author_name', '匿名'),
                'label': v.get('label', ''),
            }
            for v in versions_sorted
        ]

    def _find_version_entry(self, version_id):
        """內部用：依 version_id 找出對應的 entry（or None）。"""
        for v in (self.versions_data or []):
            if v.get('version_no') == version_id:
                return v
        return None

    def get_version_content(self, version_id):
        """取得單一版本的完整內容（HTML + JSON）。

        Args:
            version_id: 版本號（int）。為向後相容 W7-8 早期 API 也接受傳入字串。
        """
        self.ensure_one()
        try:
            version_id = int(version_id)
        except (TypeError, ValueError):
            return None
        entry = self._find_version_entry(version_id)
        if not entry:
            return None
        return {
            'version_id': entry.get('version_no'),
            'version_number': entry.get('version_no'),
            'date': entry.get('created_at'),
            'author_name': entry.get('author_name', '匿名'),
            'content_html': entry.get('content_html', ''),
            'content_json': entry.get('content_json', ''),
        }

    def restore_version(self, version_id):
        """把指定版本的內容還原到當前文件（會自動先存「還原前」版本）。"""
        self.ensure_one()
        from odoo.exceptions import UserError
        try:
            version_id = int(version_id)
        except (TypeError, ValueError):
            raise UserError("無效的版本識別碼。")
        entry = self._find_version_entry(version_id)
        if not entry:
            raise UserError("找不到指定的版本快照。")

        target_version = entry.get('version_no')
        # 先存「還原前」快照
        self.action_save_version(
            label=f'還原前快照（即將回退到 v{target_version}）'
        )

        # 套用快照內容
        update_vals = {
            'content_html': entry.get('content_html') or '',
            'content_json': entry.get('content_json') or '',
        }
        self.write(update_vals)
        return {
            'restored_version': target_version,
            'new_current_version': self.version_number,
        }

    def diff_versions(self, version_id_a, version_id_b):
        """段落層級 diff。

        Returns:
            dict: {'a_version', 'b_version', 'a_date', 'b_date', 'opcodes': [...]}
                  或 None 若任一 version_id 不存在
        """
        self.ensure_one()
        import difflib
        import re as _re
        from html import unescape

        def _to_lines(html):
            t = _re.sub(
                r'<br\s*/?>|</(p|div|h\d|li|tr)>',
                '\n', html or '', flags=_re.I,
            )
            t = _re.sub(r'<[^>]+>', '', t)
            t = unescape(t)
            return [ln.strip() for ln in t.split('\n') if ln.strip()]

        a = self.get_version_content(version_id_a)
        b = self.get_version_content(version_id_b)
        if not a or not b:
            return None

        lines_a = _to_lines(a.get('content_html'))
        lines_b = _to_lines(b.get('content_html'))

        sm = difflib.SequenceMatcher(None, lines_a, lines_b)
        ops = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            ops.append({
                'op': tag,
                'a_lines': lines_a[i1:i2],
                'b_lines': lines_b[j1:j2],
            })
        return {
            'a_version': a.get('version_number'),
            'b_version': b.get('version_number'),
            'a_date': a.get('date'),
            'b_date': b.get('date'),
            'opcodes': ops,
        }

    # ─── DB 索引 ─────────────────────────────────────────────────────

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS doc_document_company_write_date_idx
            ON doc_document (company_id, write_date DESC);
            CREATE INDEX IF NOT EXISTS doc_document_company_model_idx
            ON doc_document (company_id, model_id) WHERE model_id IS NOT NULL;
        """)
