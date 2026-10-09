#!/usr/bin/env python3
"""
scan_ooxml_elements.py — 掃 fixture DOCX 統計實際使用的 OOXML 元素

目的：
    OOXML 規格 5000+ 頁，元素無數。但 ChienYi 真實工程文件只用 Word 功能子集。
    本工具掃所有 fixture，產出「白名單」：Parser 只實作此清單即可，
    避免做出無底洞。

使用：
    python3 tools/scan_ooxml_elements.py tests/fixtures/
    python3 tools/scan_ooxml_elements.py tests/fixtures/03_complex_table/
    python3 tools/scan_ooxml_elements.py tests/fixtures/ -o docs/ooxml_whitelist.md

輸出：
    依命名空間分組的元素清單，含每個元素的出現次數與來源檔案範圍。
"""

import argparse
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


# OOXML 主要命名空間（縮寫對照）
NS_PREFIX = {
    'http://schemas.openxmlformats.org/wordprocessingml/2006/main': 'w',
    'http://schemas.openxmlformats.org/drawingml/2006/main': 'a',
    'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing': 'wp',
    'http://schemas.openxmlformats.org/drawingml/2006/picture': 'pic',
    'http://schemas.openxmlformats.org/officeDocument/2006/relationships': 'r',
    'http://schemas.openxmlformats.org/officeDocument/2006/math': 'm',
    'urn:schemas-microsoft-com:vml': 'v',
    'urn:schemas-microsoft-com:office:office': 'o',
    'urn:schemas-microsoft-com:office:word': 'w10',
    'http://schemas.microsoft.com/office/word/2010/wordml': 'w14',
    'http://schemas.microsoft.com/office/word/2012/wordml': 'w15',
    'http://schemas.openxmlformats.org/markup-compatibility/2006': 'mc',
}

# 重要 part（其他 part 也會掃，但這幾個必須出現在報告中）
KEY_PARTS = (
    'word/document.xml',
    'word/styles.xml',
    'word/numbering.xml',
    'word/theme/theme1.xml',
)


def shorten(qname: str) -> str:
    """把 {namespace}local 縮短成 ns:local。未知 namespace 留長名稱。"""
    if not qname.startswith('{'):
        return qname
    end = qname.index('}')
    ns = qname[1:end]
    local = qname[end + 1:]
    prefix = NS_PREFIX.get(ns)
    return f'{prefix}:{local}' if prefix else f'{{{ns}}}{local}'


def scan_docx(docx_path: Path, counts: dict, sources: dict) -> None:
    """掃單一 .docx，把所有 XML element 名加進 counts/sources。"""
    try:
        with zipfile.ZipFile(docx_path) as zf:
            for entry in zf.namelist():
                if not entry.endswith('.xml'):
                    continue
                try:
                    data = zf.read(entry)
                    root = ET.fromstring(data)
                except (ET.ParseError, KeyError):
                    continue
                for elem in root.iter():
                    name = shorten(elem.tag)
                    counts[name] += 1
                    sources[name].add(docx_path.name)
    except zipfile.BadZipFile:
        print(f'⚠️  Skipped (bad zip): {docx_path}', file=sys.stderr)


def render_markdown(counts: dict, sources: dict, total_files: int) -> str:
    """把統計結果產成 markdown 白名單。"""
    # 依 namespace prefix 分組
    by_ns: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for name, count in counts.items():
        if ':' in name:
            ns_prefix, local = name.split(':', 1)
        else:
            ns_prefix, local = '_unknown', name
        by_ns[ns_prefix].append((name, count, len(sources[name])))

    lines = [
        '# OOXML 元素白名單',
        '',
        '> 本檔由 `tools/scan_ooxml_elements.py` 自動產生，依 fixture 實際出現的元素統計。',
        '> Parser 僅需實作此清單；超出範圍的元素先做 fallback 不擋上線。',
        '',
        f'**Fixture 總數**：{total_files} 份 DOCX',
        f'**唯一元素數**：{len(counts)}',
        '',
    ]

    # 命名空間順序：w 優先、其餘按字母
    order = ['w', 'r', 'a', 'wp', 'pic', 'm', 'v', 'o', 'w10', 'w14', 'w15', 'mc']
    sorted_ns = [ns for ns in order if ns in by_ns] + sorted(
        ns for ns in by_ns if ns not in order
    )

    for ns in sorted_ns:
        items = sorted(by_ns[ns], key=lambda x: -x[1])  # 依出現次數遞減
        ns_label = {
            'w': 'WordprocessingML（核心）',
            'r': 'Relationships',
            'a': 'DrawingML 主',
            'wp': 'DrawingML Word 內嵌',
            'pic': 'DrawingML Picture',
            'm': 'Math (OMML)',
            'v': 'VML（舊式向量圖）',
            'o': 'Office VML 擴展',
            'w10': 'Word 10 VML',
            'w14': 'Word 2010 擴展',
            'w15': 'Word 2012 擴展',
            'mc': 'Markup Compatibility',
            '_unknown': '未知命名空間',
        }.get(ns, ns)

        lines.extend([
            f'## {ns}: {ns_label}（{len(items)} 個元素）',
            '',
            '| 元素 | 總出現次數 | 出現於檔數 |',
            '|------|-----------|------------|',
        ])
        for name, total, file_count in items:
            lines.append(f'| `{name}` | {total} | {file_count}/{total_files} |')
        lines.append('')

    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('fixture_dir', type=Path, help='fixture 根目錄（會遞迴掃 .docx）')
    ap.add_argument('-o', '--output', type=Path, default=None,
                    help='輸出 markdown 檔（預設輸出到 stdout）')
    args = ap.parse_args()

    if not args.fixture_dir.is_dir():
        print(f'✗ Not a directory: {args.fixture_dir}', file=sys.stderr)
        return 1

    docx_files = sorted(args.fixture_dir.rglob('*.docx'))
    if not docx_files:
        print(f'✗ No .docx files under {args.fixture_dir}', file=sys.stderr)
        return 1

    print(f'→ Scanning {len(docx_files)} fixture files…', file=sys.stderr)

    counts: dict[str, int] = defaultdict(int)
    sources: dict[str, set] = defaultdict(set)
    for path in docx_files:
        scan_docx(path, counts, sources)

    md = render_markdown(counts, sources, len(docx_files))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding='utf-8')
        print(f'✓ Wrote {len(counts)} unique elements → {args.output}', file=sys.stderr)
    else:
        print(md)

    return 0


if __name__ == '__main__':
    sys.exit(main())
