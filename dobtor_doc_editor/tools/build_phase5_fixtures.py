#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 5 測試 fixture 產生器 — dobtor_doc_editor。

從工程資料的 xlsx / pptx 抽出真實的 Chart / SmartArt OOXML part，
重新打包成合法的 .docx fixture；OMML 數學公式無真實來源，以 synthetic 補齊。

輸出：
    tests/fixtures/07_chart/     — 真實圖表（來源 xlsx）
    tests/fixtures/08_smartart/  — 真實 SmartArt（來源 pptx）
    tests/fixtures/09_omml/      — synthetic 數學公式
    tests/fixtures/phase5_fixture_manifest.json — 來源/類型/狀態紀錄

原理：OOXML 三格式共用 DrawingML schema，xlsx 的 xl/charts/chartN.xml 與
docx 的 word/charts/chartN.xml 是同一套 schema；pptx 與 docx 的 diagrams/
part 亦通用。因此可「抽 part 重新打包」做格式移植。

用法：
    python3 tools/build_phase5_fixtures.py \\
        --source-root /mnt/d/work --out tests/fixtures [--verify]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ── 命名常數（遵守 CLAUDE.md：禁止 magic number / magic string）─────────────
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MS_2011_REL = "http://schemas.microsoft.com/office/2011/relationships"
MS_2007_REL = "http://schemas.microsoft.com/office/2007/relationships"

CT_DOCUMENT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CT_STYLES = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
CT_CHART = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
CT_CHARTSTYLE = "application/vnd.ms-office.chartstyle+xml"
CT_CHARTCOLOR = "application/vnd.ms-office.chartcolorstyle+xml"
CT_DGM_DATA = "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml"
CT_DGM_LAYOUT = "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml"
CT_DGM_STYLE = "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml"
CT_DGM_COLORS = "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml"
CT_DGM_DRAWING = "application/vnd.ms-office.drawingml.diagramDrawing+xml"

# 圖表策展：每種圖表類型最多取的份數、圖表 fixture 總數上限
MAX_PER_CHART_TYPE = 4
MAX_CHART_FIXTURES = 10
# 內嵌物件尺寸（EMU；6 吋 x 3.5 吋）
EMU_W = 5486400
EMU_H = 3200400
# LibreOffice headless 轉檔逾時（秒）；冷啟動建 profile 較慢，故放寬
LIBREOFFICE_TIMEOUT = 180

# ── 共用 XML 片段 ──────────────────────────────────────────────────────────
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

ROOT_RELS = (
    XML_DECL
    + f'<Relationships xmlns="{REL_NS}">'
    + f'<Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" '
    + 'Target="word/document.xml"/></Relationships>'
)

STYLES_XML = (
    XML_DECL
    + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    + '<w:docDefaults><w:rPrDefault><w:rPr/></w:rPrDefault>'
    + '<w:pPrDefault><w:pPr/></w:pPrDefault></w:docDefaults>'
    + '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    + '<w:name w:val="Normal"/></w:style></w:styles>'
)


def content_types(overrides):
    """產生 [Content_Types].xml；overrides = [(partname, contenttype), ...]。"""
    parts = [
        XML_DECL,
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    for partname, ctype in overrides:
        parts.append(f'<Override PartName="{partname}" ContentType="{ctype}"/>')
    parts.append("</Types>")
    return "".join(parts)


def document_xml(body_inner):
    """包出完整 word/document.xml；body_inner 為 <w:body> 內容（不含 sectPr）。"""
    return (
        XML_DECL
        + '<w:document '
        + 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        + 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        + 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        + 'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        + 'xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        + 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        + "<w:body>"
        + body_inner
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        + '<w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/>'
        + "</w:sectPr></w:body></w:document>"
    )


def drawing_paragraph(graphic_data_inner, name):
    """產生一段含 <w:drawing> 內嵌物件的 <w:p>。"""
    return (
        "<w:p><w:r><w:drawing>"
        + '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        + f'<wp:extent cx="{EMU_W}" cy="{EMU_H}"/>'
        + f'<wp:docPr id="1" name="{name}"/>'
        + "<a:graphic>"
        + graphic_data_inner
        + "</a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def heading_paragraph(text):
    """產生一段純文字標題 <w:p>（XML escape）。"""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r>".join(
        ["<w:p>", "</w:p>"]
    )


# ── ZIP 工具 ───────────────────────────────────────────────────────────────
def zip_read(zip_path, member):
    """讀取 zip 內某 member，回傳 bytes；不存在回 None。"""
    with zipfile.ZipFile(zip_path) as zf:
        try:
            return zf.read(member)
        except KeyError:
            return None


def zip_namelist(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def write_docx(out_path, parts):
    """parts = {內部路徑: bytes|str}，打包成 docx。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in parts.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            zf.writestr(arcname, data)


def verify_docx_integrity(out_path):
    """確認 docx 是合法 zip、且 document.xml 引用的 rels 目標都存在。回傳錯誤字串或 ''。"""
    try:
        with zipfile.ZipFile(out_path) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                return "缺少 word/document.xml"
            rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
            for target in re.findall(r'Target="([^"]+)"', rels):
                if target.startswith("http"):
                    continue
                resolved = "word/" + target.lstrip("/")
                if resolved not in names:
                    return f"rels 目標遺失：{target}"
    except zipfile.BadZipFile:
        return "非合法 zip"
    except KeyError as exc:
        return f"缺少 part：{exc}"
    return ""


def verify_docx_renders(out_path, soffice, profile_dir):
    """用 LibreOffice headless 轉 PDF 驗證可開啟。回傳錯誤字串或 ''。

    profile_dir 為整批共用的 LibreOffice user profile，避免每份檔案都冷啟動。
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            soffice, "--headless", "--norestore",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to", "pdf", "--outdir", tmp, str(out_path),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=LIBREOFFICE_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return "LibreOffice 轉檔逾時"
        except FileNotFoundError:
            return "找不到 libreoffice 執行檔"
        pdf = Path(tmp) / (out_path.stem + ".pdf")
        if proc.returncode != 0 or not pdf.exists() or pdf.stat().st_size == 0:
            return f"LibreOffice 轉檔失敗 (rc={proc.returncode})"
    return ""


# ── Part A：Chart fixture（xlsx → docx）────────────────────────────────────
def detect_chart_type(chart_xml_bytes):
    """從 chartN.xml 偵測圖表類型。"""
    text = chart_xml_bytes.decode("utf-8", "ignore")
    for kind in ("bar3DChart", "barChart", "line3DChart", "lineChart",
                 "pie3DChart", "pieChart", "doughnutChart", "areaChart",
                 "area3DChart", "scatterChart", "radarChart", "bubbleChart",
                 "stockChart", "surfaceChart"):
        if f"<c:{kind}" in text:
            return kind
    return "unknownChart"


def find_chart_xlsx(source_root):
    """掃出含圖表的 xlsx，回傳 [(path, 第一個 chart 內部路徑), ...]。"""
    results = []
    for xlsx in sorted(source_root.rglob("*.xlsx")):
        if xlsx.name.startswith("~$"):
            continue
        try:
            names = zip_namelist(xlsx)
        except (zipfile.BadZipFile, OSError):
            continue
        charts = sorted(n for n in names
                        if re.fullmatch(r"xl/charts/chart\d+\.xml", n))
        if charts:
            results.append((xlsx, charts[0]))
    return results


def curate_charts(chart_files):
    """依圖表類型去重策展：每型最多 MAX_PER_CHART_TYPE，總數 MAX_CHART_FIXTURES。"""
    by_type = {}
    selected = []
    for xlsx, chart_member in chart_files:
        chart_xml = zip_read(xlsx, chart_member)
        if chart_xml is None:
            continue
        kind = detect_chart_type(chart_xml)
        if by_type.get(kind, 0) >= MAX_PER_CHART_TYPE:
            continue
        by_type[kind] = by_type.get(kind, 0) + 1
        selected.append((xlsx, chart_member, kind))
        if len(selected) >= MAX_CHART_FIXTURES:
            break
    return selected


def build_chart_docx(xlsx, chart_member, out_path):
    """把 xlsx 的圖表 part 移植成 docx。回傳 dropped_rels 清單。"""
    chart_dir = chart_member.rsplit("/", 1)[0]            # xl/charts
    chart_name = chart_member.rsplit("/", 1)[1]           # chartN.xml
    chart_xml = zip_read(xlsx, chart_member)
    rels_member = f"{chart_dir}/_rels/{chart_name}.rels"
    rels_xml = zip_read(xlsx, rels_member)

    # 解析圖表 rels，只留 chartStyle / chartColorStyle，其餘丟棄
    keep_rels = []          # [(新 Id, rel type, 來源檔, 目標檔, content type)]
    dropped = []
    if rels_xml:
        rels_text = rels_xml.decode("utf-8", "ignore")
        for m in re.finditer(
            r'<Relationship\b[^>]*Id="([^"]+)"[^>]*'
            r'Type="([^"]+)"[^>]*Target="([^"]+)"[^>]*/?>',
            rels_text,
        ):
            rel_id, rel_type, target = m.group(1), m.group(2), m.group(3)
            tgt_name = target.lstrip("./").rsplit("/", 1)[-1]
            src_member = f"{chart_dir}/{tgt_name}"
            if rel_type.endswith("/chartStyle"):
                keep_rels.append((rel_id, rel_type, src_member,
                                  "style1.xml", CT_CHARTSTYLE))
            elif rel_type.endswith("/chartColorStyle"):
                keep_rels.append((rel_id, rel_type, src_member,
                                  "colors1.xml", CT_CHARTCOLOR))
            else:
                dropped.append(f"{rel_type} -> {target}")

    overrides = [
        ("/word/document.xml", CT_DOCUMENT),
        ("/word/styles.xml", CT_STYLES),
        ("/word/charts/chart1.xml", CT_CHART),
    ]
    parts = {}
    chart_rel_entries = []
    for rel_id, rel_type, src_member, dst_name, ctype in keep_rels:
        src = zip_read(xlsx, src_member)
        if src is None:
            dropped.append(f"{rel_type} 來源遺失 {src_member}")
            continue
        parts[f"word/charts/{dst_name}"] = src
        overrides.append((f"/word/charts/{dst_name}", ctype))
        chart_rel_entries.append(
            f'<Relationship Id="{rel_id}" Type="{rel_type}" '
            f'Target="{dst_name}"/>'
        )

    parts["[Content_Types].xml"] = content_types(overrides)
    parts["_rels/.rels"] = ROOT_RELS
    parts["word/styles.xml"] = STYLES_XML
    parts["word/charts/chart1.xml"] = chart_xml
    if chart_rel_entries:
        parts["word/charts/_rels/chart1.xml.rels"] = (
            XML_DECL + f'<Relationships xmlns="{REL_NS}">'
            + "".join(chart_rel_entries) + "</Relationships>"
        )

    parts["word/_rels/document.xml.rels"] = (
        XML_DECL + f'<Relationships xmlns="{REL_NS}">'
        + f'<Relationship Id="rIdChart" Type="{OFFICE_REL}/chart" '
        + 'Target="charts/chart1.xml"/>'
        + f'<Relationship Id="rIdStyles" Type="{OFFICE_REL}/styles" '
        + 'Target="styles.xml"/></Relationships>'
    )
    graphic = (
        '<a:graphicData uri="http://schemas.openxmlformats.org/'
        'drawingml/2006/chart"><c:chart r:id="rIdChart"/></a:graphicData>'
    )
    body = (
        heading_paragraph(f"Chart fixture — 來源 {xlsx.name}")
        + drawing_paragraph(graphic, "Chart 1")
    )
    parts["word/document.xml"] = document_xml(body)
    write_docx(out_path, parts)
    return dropped


# ── Part B：SmartArt fixture（pptx → docx）─────────────────────────────────
def parse_rels(rels_bytes):
    """解析 .rels，回傳 {Id: Target}。"""
    out = {}
    if not rels_bytes:
        return out
    text = rels_bytes.decode("utf-8", "ignore")
    for m in re.finditer(
        r'<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', text
    ):
        out[m.group(1)] = m.group(2)
    # 屬性順序可能相反，再補一輪
    for m in re.finditer(
        r'<Relationship\b[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', text
    ):
        out.setdefault(m.group(2), m.group(1))
    return out


def resolve(base_dir, target):
    """把 rels 的相對 Target 解析成 zip 內絕對路徑。"""
    parts = (base_dir + "/" + target).split("/")
    stack = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if stack:
                stack.pop()
        else:
            stack.append(p)
    return "/".join(stack)


def find_smartart_sets(pptx):
    """掃 pptx 找 SmartArt，回傳 [{data,layout,quickStyle,colors,drawing,
    drawing_relid}]，路徑為 zip 內絕對路徑。"""
    names = set(zip_namelist(pptx))
    sets = []
    for slide in sorted(n for n in names
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
        slide_xml = zip_read(pptx, slide).decode("utf-8", "ignore")
        if "relIds" not in slide_xml:
            continue
        slide_dir = slide.rsplit("/", 1)[0]
        rels = parse_rels(
            zip_read(pptx, f"{slide_dir}/_rels/{slide.rsplit('/', 1)[1]}.rels")
        )
        for m in re.finditer(r"<[\w]*:?relIds\b([^>]*)/?>", slide_xml):
            attrs = m.group(1)

            def attr(name):
                am = re.search(rf'\w*:?{name}="([^"]+)"', attrs)
                return am.group(1) if am else None

            dm, lo, qs, cs = (attr("dm"), attr("lo"),
                              attr("qs"), attr("cs"))
            if not all((dm, lo, qs, cs)):
                continue
            try:
                data_path = resolve(slide_dir, rels[dm])
                layout_path = resolve(slide_dir, rels[lo])
                qs_path = resolve(slide_dir, rels[qs])
                colors_path = resolve(slide_dir, rels[cs])
            except KeyError:
                continue
            # 由 data part 的 dsp:dataModelExt relId 找 drawing
            data_xml = zip_read(pptx, data_path)
            drawing_path, drawing_relid = None, None
            if data_xml:
                dm_ext = re.search(
                    r"dataModelExt\b[^>]*relId=\"([^\"]+)\"",
                    data_xml.decode("utf-8", "ignore"),
                )
                if dm_ext and dm_ext.group(1) in rels:
                    drawing_relid = dm_ext.group(1)
                    drawing_path = resolve(slide_dir, rels[drawing_relid])
            sets.append({
                "data": data_path, "layout": layout_path,
                "quickStyle": qs_path, "colors": colors_path,
                "drawing": drawing_path, "drawing_relid": drawing_relid,
            })
    return sets


def build_smartart_docx(pptx, sa_set, out_path):
    """把 pptx 的一組 SmartArt part 移植成 docx。"""
    data_xml = zip_read(pptx, sa_set["data"])
    layout_xml = zip_read(pptx, sa_set["layout"])
    qs_xml = zip_read(pptx, sa_set["quickStyle"])
    colors_xml = zip_read(pptx, sa_set["colors"])
    drawing_xml = (zip_read(pptx, sa_set["drawing"])
                   if sa_set["drawing"] else None)

    # data part 內的 dataModelExt relId 改寫成 docx 端的 rId5
    if data_xml and sa_set["drawing_relid"]:
        data_xml = data_xml.replace(
            f'relId="{sa_set["drawing_relid"]}"'.encode(),
            b'relId="rId5"',
        )

    overrides = [
        ("/word/document.xml", CT_DOCUMENT),
        ("/word/styles.xml", CT_STYLES),
        ("/word/diagrams/data1.xml", CT_DGM_DATA),
        ("/word/diagrams/layout1.xml", CT_DGM_LAYOUT),
        ("/word/diagrams/quickStyle1.xml", CT_DGM_STYLE),
        ("/word/diagrams/colors1.xml", CT_DGM_COLORS),
    ]
    parts = {
        "word/diagrams/data1.xml": data_xml,
        "word/diagrams/layout1.xml": layout_xml,
        "word/diagrams/quickStyle1.xml": qs_xml,
        "word/diagrams/colors1.xml": colors_xml,
        "_rels/.rels": ROOT_RELS,
        "word/styles.xml": STYLES_XML,
    }
    rel_entries = [
        f'<Relationship Id="rId1" Type="{OFFICE_REL}/diagramData" '
        'Target="diagrams/data1.xml"/>',
        f'<Relationship Id="rId2" Type="{OFFICE_REL}/diagramLayout" '
        'Target="diagrams/layout1.xml"/>',
        f'<Relationship Id="rId3" Type="{OFFICE_REL}/diagramQuickStyle" '
        'Target="diagrams/quickStyle1.xml"/>',
        f'<Relationship Id="rId4" Type="{OFFICE_REL}/diagramColors" '
        'Target="diagrams/colors1.xml"/>',
        f'<Relationship Id="rIdStyles" Type="{OFFICE_REL}/styles" '
        'Target="styles.xml"/>',
    ]
    if drawing_xml is not None:
        parts["word/diagrams/drawing1.xml"] = drawing_xml
        overrides.append(("/word/diagrams/drawing1.xml", CT_DGM_DRAWING))
        rel_entries.append(
            f'<Relationship Id="rId5" '
            f'Type="{MS_2007_REL}/diagramDrawing" '
            'Target="diagrams/drawing1.xml"/>'
        )
    parts["[Content_Types].xml"] = content_types(overrides)
    parts["word/_rels/document.xml.rels"] = (
        XML_DECL + f'<Relationships xmlns="{REL_NS}">'
        + "".join(rel_entries) + "</Relationships>"
    )
    graphic = (
        '<a:graphicData uri="http://schemas.openxmlformats.org/'
        'drawingml/2006/diagram">'
        '<dgm:relIds xmlns:dgm="http://schemas.openxmlformats.org/'
        'drawingml/2006/diagram" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships" '
        'r:dm="rId1" r:lo="rId2" r:qs="rId3" r:cs="rId4"/>'
        "</a:graphicData>"
    )
    body = (
        heading_paragraph(f"SmartArt fixture — 來源 {pptx.name}")
        + drawing_paragraph(graphic, "Diagram 1")
    )
    parts["word/document.xml"] = document_xml(body)
    write_docx(out_path, parts)


# ── Part C：OMML synthetic fixture ─────────────────────────────────────────
# 每個 OMML 片段都是合法的 <m:oMath> 內容
OMML_FRACTION = (
    "<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>"
    "<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>"
)
OMML_RADICAL = (
    '<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>'
    "<m:e><m:r><m:t>x</m:t></m:r></m:e></m:rad>"
)
OMML_NARY_SUM = (
    '<m:nary><m:naryPr><m:chr m:val="∑"/>'
    '<m:limLoc m:val="undOvr"/></m:naryPr>'
    "<m:sub><m:r><m:t>i=1</m:t></m:r></m:sub>"
    "<m:sup><m:r><m:t>n</m:t></m:r></m:sup>"
    "<m:e><m:r><m:t>i</m:t></m:r></m:e></m:nary>"
)
OMML_SUPSCRIPT = (
    "<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e>"
    "<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>"
)
OMML_SUBSCRIPT = (
    "<m:sSub><m:e><m:r><m:t>x</m:t></m:r></m:e>"
    "<m:sub><m:r><m:t>n</m:t></m:r></m:sub></m:sSub>"
)
OMML_MATRIX = (
    "<m:m>"
    "<m:mr><m:e><m:r><m:t>1</m:t></m:r></m:e>"
    "<m:e><m:r><m:t>0</m:t></m:r></m:e></m:mr>"
    "<m:mr><m:e><m:r><m:t>0</m:t></m:r></m:e>"
    "<m:e><m:r><m:t>1</m:t></m:r></m:e></m:mr></m:m>"
)


def omml_display(inner):
    """display 數學（獨立成段）：<m:oMathPara>。"""
    return (
        "<w:p><m:oMathPara><m:oMath>" + inner
        + "</m:oMath></m:oMathPara></w:p>"
    )


def omml_inline(prefix, inner, suffix):
    """inline 數學：<m:oMath> 夾在文字 run 之間。"""
    return (
        "<w:p>"
        + f'<w:r><w:t xml:space="preserve">{prefix}</w:t></w:r>'
        + "<m:oMath>" + inner + "</m:oMath>"
        + f'<w:r><w:t xml:space="preserve">{suffix}</w:t></w:r>'
        + "</w:p>"
    )


# (檔名, 標題, body) — body 為 <w:body> 內段落
OMML_FIXTURES = [
    ("omml_01_inline_fraction",
     "Inline 分數",
     omml_inline("分數 ", OMML_FRACTION, " 出現在句子中。")),
    ("omml_02_display_fraction",
     "Display 分數",
     omml_display(OMML_FRACTION)),
    ("omml_03_radical",
     "根號",
     omml_display(OMML_RADICAL)),
    ("omml_04_nary_sum",
     "求和（含上下限）",
     omml_display(OMML_NARY_SUM)),
    ("omml_05_sub_sup",
     "上下標",
     omml_inline("上標 ", OMML_SUPSCRIPT, " 與下標 ")
     + omml_inline("", OMML_SUBSCRIPT, " 同段。")),
    ("omml_06_matrix",
     "矩陣",
     omml_display(OMML_MATRIX)),
]


def build_omml_docx(title, body_inner, out_path):
    """產生 synthetic OMML fixture。"""
    parts = {
        "[Content_Types].xml": content_types([
            ("/word/document.xml", CT_DOCUMENT),
            ("/word/styles.xml", CT_STYLES),
        ]),
        "_rels/.rels": ROOT_RELS,
        "word/styles.xml": STYLES_XML,
        "word/_rels/document.xml.rels": (
            XML_DECL + f'<Relationships xmlns="{REL_NS}">'
            + f'<Relationship Id="rIdStyles" Type="{OFFICE_REL}/styles" '
            + 'Target="styles.xml"/></Relationships>'
        ),
    }
    body = heading_paragraph(f"OMML fixture — {title}") + body_inner
    parts["word/document.xml"] = document_xml(body)
    write_docx(out_path, parts)


# ── 主流程 ────────────────────────────────────────────────────────────────
def sanitise(stem):
    """清掉檔名中對檔案系統不友善的字元。"""
    return re.sub(r'[\\/:*?"<>|]+', "_", stem).strip()


def unique_path(directory, stem, suffix=".docx"):
    """避免檔名碰撞。"""
    candidate = directory / f"{stem}{suffix}"
    idx = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{idx}{suffix}"
        idx += 1
    return candidate


def main():
    parser = argparse.ArgumentParser(description="Phase 5 fixture 產生器")
    parser.add_argument("--source-root", default="/mnt/d/work",
                        help="掃描 xlsx/pptx 的根目錄")
    parser.add_argument("--out", required=True,
                        help="fixture 輸出根目錄（通常是 tests/fixtures）")
    parser.add_argument("--verify", action="store_true",
                        help="用 LibreOffice headless 轉 PDF 驗證每份 fixture")
    parser.add_argument("--soffice", default="libreoffice",
                        help="LibreOffice 執行檔（預設 libreoffice）")
    args = parser.parse_args()

    source_root = Path(args.source_root)
    out_root = Path(args.out)
    if not source_root.is_dir():
        print(f"來源根目錄不存在：{source_root}", file=sys.stderr)
        return 1

    manifest = {"chart": [], "smartart": [], "omml": [], "failed": []}
    # 整批共用一個 LibreOffice profile，首份慢、其餘走熱啟動
    lo_profile = tempfile.mkdtemp(prefix="phase5_lo_")

    def record(category, out_path, source, extra=None, fail=None):
        entry = {
            "fixture": str(out_path.relative_to(out_root)),
            "source": source,
        }
        if extra:
            entry.update(extra)
        if fail:
            entry["error"] = fail
            manifest["failed"].append(entry)
        else:
            manifest[category].append(entry)

    def run_verify(out_path):
        """整合性 + 渲染驗證，回傳錯誤字串或 ''。"""
        err = verify_docx_integrity(out_path)
        if err:
            return err
        if args.verify:
            return verify_docx_renders(out_path, args.soffice, lo_profile)
        return ""

    # ── Part A：Chart ──────────────────────────────────────────────────
    print("[A] 掃描含圖表的 xlsx ...")
    chart_files = find_chart_xlsx(source_root)
    selected = curate_charts(chart_files)
    print(f"    找到 {len(chart_files)} 個含圖表 xlsx，策展取用 {len(selected)} 份")
    chart_dir = out_root / "07_chart"
    for xlsx, chart_member, kind in selected:
        out_path = unique_path(chart_dir, sanitise(xlsx.stem))
        try:
            dropped = build_chart_docx(xlsx, chart_member, out_path)
        except Exception as exc:                       # noqa: BLE001
            record("chart", out_path, str(xlsx), fail=f"打包失敗：{exc}")
            print(f"    ✗ {out_path.name}：{exc}")
            continue
        err = run_verify(out_path)
        if err:
            out_path.unlink(missing_ok=True)
            record("chart", out_path, str(xlsx),
                   {"chart_type": kind}, fail=err)
            print(f"    ✗ {out_path.name}：{err}")
        else:
            record("chart", out_path, str(xlsx),
                   {"chart_type": kind, "dropped_rels": dropped})
            print(f"    ✓ {out_path.name}  [{kind}]")

    # ── Part B：SmartArt ───────────────────────────────────────────────
    print("[B] 掃描含 SmartArt 的 pptx ...")
    smartart_dir = out_root / "08_smartart"
    pptx_count = 0
    for pptx in sorted(source_root.rglob("*.pptx")):
        if pptx.name.startswith("~$"):
            continue
        try:
            sets = find_smartart_sets(pptx)
        except (zipfile.BadZipFile, OSError):
            continue
        if not sets:
            continue
        pptx_count += 1
        sa_set = sets[0]                               # 每個 pptx 取第一組
        out_path = unique_path(smartart_dir, sanitise(pptx.stem))
        try:
            build_smartart_docx(pptx, sa_set, out_path)
        except Exception as exc:                       # noqa: BLE001
            record("smartart", out_path, str(pptx), fail=f"打包失敗：{exc}")
            print(f"    ✗ {out_path.name}：{exc}")
            continue
        err = run_verify(out_path)
        if err:
            out_path.unlink(missing_ok=True)
            record("smartart", out_path, str(pptx), fail=err)
            print(f"    ✗ {out_path.name}：{err}")
        else:
            record("smartart", out_path, str(pptx),
                   {"smartart_sets_in_source": len(sets)})
            print(f"    ✓ {out_path.name}")
    print(f"    含 SmartArt 的 pptx 共 {pptx_count} 個")

    # ── Part C：OMML synthetic ─────────────────────────────────────────
    print("[C] 產生 synthetic OMML fixture ...")
    omml_dir = out_root / "09_omml"
    for stem, title, body_inner in OMML_FIXTURES:
        out_path = unique_path(omml_dir, stem)
        try:
            build_omml_docx(title, body_inner, out_path)
        except Exception as exc:                       # noqa: BLE001
            record("omml", out_path, "synthetic", fail=f"打包失敗：{exc}")
            print(f"    ✗ {out_path.name}：{exc}")
            continue
        err = run_verify(out_path)
        if err:
            out_path.unlink(missing_ok=True)
            record("omml", out_path, "synthetic", fail=err)
            print(f"    ✗ {out_path.name}：{err}")
        else:
            record("omml", out_path, "synthetic", {"title": title})
            print(f"    ✓ {out_path.name}  [{title}]")

    # ── manifest + 摘要 ────────────────────────────────────────────────
    manifest_path = out_root / "phase5_fixture_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("─" * 60)
    print(f"Chart   ：{len(manifest['chart'])} 份")
    print(f"SmartArt：{len(manifest['smartart'])} 份")
    print(f"OMML    ：{len(manifest['omml'])} 份")
    print(f"失敗    ：{len(manifest['failed'])} 份")
    print(f"manifest：{manifest_path}")
    shutil.rmtree(lo_profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
