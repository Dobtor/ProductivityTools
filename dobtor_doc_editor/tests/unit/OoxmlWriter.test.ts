/**
 * OoxmlWriter 單元測試（Sprint 185、Phase 6 docx export MVS）
 *
 * 驗證 DocumentNode → .docx package 的最小可行切片：純文字段落、單 section
 * pgSz/pgMar、5 個必要 part。其他 RunProps/表格/圖片/Phase 5 子功能等留後續 sprint。
 */

import { describe, expect, it } from 'vitest';
import { unzipSync, strFromU8 } from 'fflate';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  BlockNode,
  CellNode,
  DocumentNode,
  ParagraphNode,
  RowNode,
  RunNode,
  SectionNode,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const writer = new OoxmlWriter();

function makeRun(text: string): RunNode {
  return { type: 'run', text, props: {} };
}

function makeParagraph(runs: ParagraphNode['runs']): ParagraphNode {
  return { type: 'paragraph', runs, props: {} };
}

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section',
    page: { width: 595.3, height: 841.9, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function makeDoc(sections: SectionNode[]): DocumentNode {
  return {
    type: 'document',
    sections,
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    comments: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering: new Map(),
    media: new Map(),
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  };
}

/** 把 OoxmlWriter 輸出解 zip 為 path → 字串 map（測試方便）。 */
function unzipToText(bytes: Uint8Array): Record<string, string> {
  const entries = unzipSync(bytes);
  const out: Record<string, string> = {};
  for (const [path, u8] of Object.entries(entries)) {
    out[path] = strFromU8(u8);
  }
  return out;
}

describe('OoxmlWriter — 5 必要 part', () => {
  it('空文件 → zip 含 7 必要 part（Sprint 194：含 comments.xml）', () => {
    const bytes = writer.write(makeDoc([makeSection([])]));
    const files = unzipToText(bytes);
    expect(Object.keys(files).sort()).toEqual([
      '[Content_Types].xml',
      '_rels/.rels',
      'word/_rels/document.xml.rels',
      'word/comments.xml',
      'word/document.xml',
      'word/numbering.xml',
      'word/styles.xml',
    ]);
  });

  it('Content Types 宣告 document.xml 與 styles.xml 兩個 override', () => {
    const files = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(files['[Content_Types].xml']).toContain('PartName="/word/document.xml"');
    expect(files['[Content_Types].xml']).toContain('PartName="/word/styles.xml"');
    expect(files['[Content_Types].xml']).toContain('wordprocessingml.document.main+xml');
  });

  it('root rels 指向 word/document.xml（officeDocument 關係型別）', () => {
    const files = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(files['_rels/.rels']).toContain('Target="word/document.xml"');
    expect(files['_rels/.rels']).toContain('officeDocument');
  });

  it('document rels 指向 styles.xml', () => {
    const files = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(files['word/_rels/document.xml.rels']).toContain('Target="styles.xml"');
    expect(files['word/_rels/document.xml.rels']).toContain('relationships/styles');
  });
});

describe('OoxmlWriter — 段落與 Run 輸出', () => {
  it('單一段落單一 run → <w:p><w:r><w:t>text</w:t></w:r></w:p>', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('Hello')])])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:p>');
    expect(xml).toContain('<w:r>');
    expect(xml).toContain('<w:t xml:space="preserve">Hello</w:t>');
  });

  it('多 run → 同段落內依序輸出', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('A'), makeRun('B'), makeRun('C')]),
    ])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    const aIdx = xml.indexOf('>A<');
    const bIdx = xml.indexOf('>B<');
    const cIdx = xml.indexOf('>C<');
    expect(aIdx).toBeGreaterThan(-1);
    expect(aIdx).toBeLessThan(bIdx);
    expect(bIdx).toBeLessThan(cIdx);
  });

  it('多段落 → 依序輸出 <w:p>', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('一')]),
      makeParagraph([makeRun('二')]),
    ])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect((xml.match(/<w:p>/g) ?? []).length).toBe(2);
  });

  it('XML 特殊字元跳脫：& < > " \'', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('a&b<c>d"e\'f')]),
    ])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('a&amp;b&lt;c&gt;d&quot;e&apos;f');
  });

  it('xml:space="preserve" 保留前後空白', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('  leading')])])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('xml:space="preserve"');
  });

  it('Sprint 192：image 升級為輸出 <w:drawing>，break/field 仍跳過', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([
        makeRun('前'),
        { type: 'inlineImage', rId: 'rIdImg1', width: 100, height: 50 },
        { type: 'break', breakType: 'line' },
        makeRun('後'),
      ]),
    ])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('>前<');
    expect(xml).toContain('>後<');
    // Sprint 192：image 現在會輸出 <w:drawing>
    expect(xml).toContain('<w:drawing>');
    // break 仍未實作
    expect(xml).not.toContain('<w:br');
  });

  it('Sprint 190：表格 BlockNode → 與段落並存輸出（Sprint 185 「跳過」已升級）', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('段落')]),
      { type: 'table', grid: [], rows: [], props: {} },
    ])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('>段落<');
    expect(xml).toContain('<w:tbl>');
    expect(xml).toContain('<w:tblGrid>');
  });
});

describe('OoxmlWriter — sectPr', () => {
  it('pgSz / pgMar 由 section page/margins 換算為 twips（×20）', () => {
    const doc = makeDoc([makeSection([])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    // A4 = 595.3 × 20 = 11906；841.9 × 20 = 16838
    expect(xml).toContain('w:w="11906"');
    expect(xml).toContain('w:h="16838"');
    // 邊距 72pt × 20 = 1440 twips
    expect(xml).toContain('w:top="1440"');
    expect(xml).toContain('w:left="1440"');
  });

  it('Sprint 191：多 section → 中間 section anchor paragraph 內嵌 sectPr、末 section body 尾', () => {
    const secA = makeSection([makeParagraph([makeRun('A')])]);
    const secB = {
      ...makeSection([makeParagraph([makeRun('B')])]),
      page: { width: 841.9, height: 595.3, orientation: 'landscape' as const },
    };
    const doc = makeDoc([secA, secB]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    // 兩個 sectPr：A 在 anchor para 內、B 在 body 尾
    expect((xml.match(/<w:sectPr>/g) ?? []).length).toBe(2);
    // section A: 直式 11906；section B: 橫式 16838
    expect(xml).toContain('w:w="11906"');
    expect(xml).toContain('w:w="16838"');
    // 兩 section 的段落都有
    expect(xml).toContain('>A<');
    expect(xml).toContain('>B<');
    // anchor paragraph 結構驗證：<w:p><w:pPr><w:sectPr>
    expect(xml).toContain('<w:p><w:pPr><w:sectPr>');
  });

  it('無 section 時用 A4 + Word 預設邊距 fallback', () => {
    const doc = makeDoc([]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('w:w="11906"');  // A4 width
    expect(xml).toContain('w:top="1440"'); // 72pt 邊距
  });
});

describe('OoxmlWriter — 輸出格式', () => {
  it('所有 part 開頭含 XML 宣告（UTF-8 / standalone="yes"）', () => {
    const files = unzipToText(writer.write(makeDoc([makeSection([])])));
    for (const path of Object.keys(files)) {
      expect(files[path]).toMatch(/^<\?xml version="1\.0" encoding="UTF-8" standalone="yes"\?>/);
    }
  });

  it('輸出為 Uint8Array、可直接 unzipSync 解析（fflate 對稱）', () => {
    const bytes = writer.write(makeDoc([makeSection([])]));
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(() => unzipSync(bytes)).not.toThrow();
  });
});

describe('OoxmlWriter — Sprint 186 RunProps 序列化', () => {
  function runWithProps(text: string, props: RunNode['props']): RunNode {
    return { type: 'run', text, props };
  }

  function getDocXml(runs: RunNode[]): string {
    const doc = makeDoc([makeSection([makeParagraph(runs)])]);
    return unzipToText(writer.write(doc))['word/document.xml'];
  }

  it('無 props → 不輸出 <w:rPr>（紀律 #21）', () => {
    const xml = getDocXml([runWithProps('x', {})]);
    expect(xml).not.toContain('<w:rPr>');
  });

  it('粗體 true → <w:b/>', () => {
    const xml = getDocXml([runWithProps('x', { bold: true })]);
    expect(xml).toContain('<w:rPr><w:b/></w:rPr>');
  });

  it('粗體 false → <w:b w:val="0"/>（顯式關閉、覆蓋 style）', () => {
    const xml = getDocXml([runWithProps('x', { bold: false })]);
    expect(xml).toContain('<w:b w:val="0"/>');
  });

  it('斜體 / 刪除線 / 雙刪除線', () => {
    const xml = getDocXml([runWithProps('x', { italic: true, strike: true, dstrike: true })]);
    expect(xml).toContain('<w:i/>');
    expect(xml).toContain('<w:strike/>');
    expect(xml).toContain('<w:dstrike/>');
  });

  it('字級 fontSize → <w:sz w:val=>（half-points、12pt = 24）', () => {
    const xml = getDocXml([runWithProps('x', { fontSize: 12 })]);
    expect(xml).toContain('<w:sz w:val="24"/>');
  });

  it('顏色 → <w:color w:val="RRGGBB"/>', () => {
    const xml = getDocXml([runWithProps('x', { color: 'FF0000' })]);
    expect(xml).toContain('<w:color w:val="FF0000"/>');
  });

  it('高亮 → <w:highlight w:val>', () => {
    const xml = getDocXml([runWithProps('x', { highlight: 'yellow' })]);
    expect(xml).toContain('<w:highlight w:val="yellow"/>');
  });

  it('底線 → <w:u w:val>（含複雜列舉值）', () => {
    for (const u of ['single', 'double', 'wave']) {
      const xml = getDocXml([runWithProps('x', { underline: u as 'single' })]);
      expect(xml).toContain(`<w:u w:val="${u}"/>`);
    }
  });

  it('上下標 vertAlign → <w:vertAlign w:val>', () => {
    expect(getDocXml([runWithProps('x', { vertAlign: 'superscript' })]))
      .toContain('<w:vertAlign w:val="superscript"/>');
    expect(getDocXml([runWithProps('x', { vertAlign: 'subscript' })]))
      .toContain('<w:vertAlign w:val="subscript"/>');
  });

  it('字型 rFonts → ascii / eastAsia / hAnsi / cs 屬性', () => {
    const xml = getDocXml([runWithProps('x', {
      fontFamily: 'Arial', fontFamilyEastAsia: '微軟正黑體',
      fontFamilyHAnsi: 'Arial', fontFamilyCs: 'Arial',
    })]);
    expect(xml).toContain('w:ascii="Arial"');
    expect(xml).toContain('w:eastAsia="微軟正黑體"');
    expect(xml).toContain('w:hAnsi="Arial"');
    expect(xml).toContain('w:cs="Arial"');
  });

  it('部分字型欄位 → 只輸出有值的 attribute', () => {
    const xml = getDocXml([runWithProps('x', { fontFamily: 'Arial' })]);
    expect(xml).toContain('<w:rFonts w:ascii="Arial"/>');
    expect(xml).not.toContain('w:eastAsia');
    expect(xml).not.toContain('w:hAnsi');
  });

  it('字距 spacing → <w:spacing w:val=>（twips、pt × 20）', () => {
    const xml = getDocXml([runWithProps('x', { spacing: 1 })]);
    expect(xml).toContain('<w:spacing w:val="20"/>');
  });

  it('語言 lang → <w:lang w:val>', () => {
    const xml = getDocXml([runWithProps('x', { lang: 'zh-TW' })]);
    expect(xml).toContain('<w:lang w:val="zh-TW"/>');
  });

  it('多 prop 組合 → 依 schema 大致順序輸出（rFonts → b → color → sz → u）', () => {
    const xml = getDocXml([runWithProps('x', {
      bold: true, color: 'FF0000', fontSize: 14, underline: 'single', fontFamily: 'Arial',
    })]);
    // 驗證順序
    const rFontsIdx = xml.indexOf('<w:rFonts');
    const bIdx = xml.indexOf('<w:b/>');
    const colorIdx = xml.indexOf('<w:color');
    const szIdx = xml.indexOf('<w:sz');
    const uIdx = xml.indexOf('<w:u ');
    expect(rFontsIdx).toBeLessThan(bIdx);
    expect(bIdx).toBeLessThan(colorIdx);
    expect(colorIdx).toBeLessThan(szIdx);
    expect(szIdx).toBeLessThan(uIdx);
  });
});

describe('OoxmlWriter — Sprint 187 ParagraphProps 序列化', () => {
  function paraWith(props: ParagraphNode['props'], styleId?: string): ParagraphNode {
    const para: ParagraphNode = { type: 'paragraph', runs: [makeRun('x')], props };
    if (styleId) para.styleId = styleId;
    return para;
  }
  function getDocXml(para: ParagraphNode): string {
    return unzipToText(writer.write(makeDoc([makeSection([para])])))['word/document.xml'];
  }

  it('無 props 與 styleId → 不輸出 <w:pPr>（紀律 #21）', () => {
    const xml = getDocXml(paraWith({}));
    expect(xml).not.toContain('<w:pPr>');
  });

  it('styleId → <w:pStyle w:val>（pPr 第一個子元素）', () => {
    const xml = getDocXml(paraWith({}, 'Heading1'));
    expect(xml).toContain('<w:pStyle w:val="Heading1"/>');
    expect(xml.indexOf('<w:pStyle')).toBeLessThan(xml.indexOf('<w:r>'));
  });

  it('keepNext / keepLines / pageBreakBefore toggle properties', () => {
    const xml = getDocXml(paraWith({
      keepNext: true, keepLines: true, pageBreakBefore: true,
    }));
    expect(xml).toContain('<w:keepNext/>');
    expect(xml).toContain('<w:keepLines/>');
    expect(xml).toContain('<w:pageBreakBefore/>');
  });

  it('keepNext false → 顯式 w:val="0"', () => {
    const xml = getDocXml(paraWith({ keepNext: false }));
    expect(xml).toContain('<w:keepNext w:val="0"/>');
  });

  it('numId + ilvl → <w:numPr><w:ilvl/><w:numId/></w:numPr>', () => {
    const xml = getDocXml(paraWith({ numId: 5, ilvl: 2 }));
    expect(xml).toContain('<w:numPr>');
    expect(xml).toContain('<w:ilvl w:val="2"/>');
    expect(xml).toContain('<w:numId w:val="5"/>');
    // ilvl 在 numId 之前
    expect(xml.indexOf('<w:ilvl')).toBeLessThan(xml.indexOf('<w:numId'));
  });

  it('alignment → <w:jc w:val>', () => {
    for (const a of ['left', 'center', 'right', 'justify'] as const) {
      const xml = getDocXml(paraWith({ alignment: a }));
      expect(xml).toContain(`<w:jc w:val="${a}"/>`);
    }
  });

  it('indent 四欄位 → <w:ind w:left w:right w:firstLine w:hanging>（pt→twips）', () => {
    const xml = getDocXml(paraWith({
      indent: { left: 36, right: 36, firstLine: 18, hanging: 12 },
    }));
    // 36pt × 20 = 720 twips, 18pt × 20 = 360, 12pt × 20 = 240
    expect(xml).toContain('w:left="720"');
    expect(xml).toContain('w:right="720"');
    expect(xml).toContain('w:firstLine="360"');
    expect(xml).toContain('w:hanging="240"');
  });

  it('spacing before/after/line（auto rule、240 分母）', () => {
    const xml = getDocXml(paraWith({
      spacing: { before: 6, after: 6, line: { rule: 'auto', value: 1.5 } },
    }));
    // 6pt × 20 = 120 twips
    expect(xml).toContain('w:before="120"');
    expect(xml).toContain('w:after="120"');
    // 1.5 × 240 = 360
    expect(xml).toContain('w:line="360"');
    expect(xml).toContain('w:lineRule="auto"');
  });

  it('spacing line exact rule → twips 換算', () => {
    const xml = getDocXml(paraWith({
      spacing: { line: { rule: 'exact', value: 14 } },
    }));
    // 14pt × 20 = 280 twips
    expect(xml).toContain('w:line="280"');
    expect(xml).toContain('w:lineRule="exact"');
  });

  it('tabs → <w:tabs><w:tab w:val w:pos w:leader/></w:tabs>', () => {
    const xml = getDocXml(paraWith({
      tabs: [
        { pos: 100, align: 'left' },
        { pos: 200, align: 'right', leader: 'dot' },
      ],
    }));
    expect(xml).toContain('<w:tabs>');
    expect(xml).toContain('<w:tab w:val="left" w:pos="2000"/>');
    expect(xml).toContain('<w:tab w:val="right" w:pos="4000" w:leader="dot"/>');
  });

  it('textAlignment → <w:textAlignment w:val>', () => {
    const xml = getDocXml(paraWith({ textAlignment: 'center' }));
    expect(xml).toContain('<w:textAlignment w:val="center"/>');
  });

  it('snapToGrid toggle', () => {
    expect(getDocXml(paraWith({ snapToGrid: true }))).toContain('<w:snapToGrid/>');
    expect(getDocXml(paraWith({ snapToGrid: false }))).toContain('<w:snapToGrid w:val="0"/>');
  });

  it('子元素順序：pStyle → keepNext → numPr → spacing → ind → jc → textAlignment', () => {
    const xml = getDocXml(paraWith({
      keepNext: true, numId: 1, ilvl: 0,
      spacing: { before: 6 }, indent: { left: 10 },
      alignment: 'left', textAlignment: 'auto',
    }, 'MyStyle'));
    const indices = [
      ['<w:pStyle', xml.indexOf('<w:pStyle')],
      ['<w:keepNext', xml.indexOf('<w:keepNext')],
      ['<w:numPr', xml.indexOf('<w:numPr')],
      ['<w:spacing', xml.indexOf('<w:spacing')],
      ['<w:ind ', xml.indexOf('<w:ind ')],
      ['<w:jc ', xml.indexOf('<w:jc ')],
      ['<w:textAlignment', xml.indexOf('<w:textAlignment')],
    ] as const;
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i][1]).toBeGreaterThan(indices[i - 1][1]);
    }
  });
});

describe('OoxmlWriter — Sprint 188 ParagraphProps 進階（pBdr / shd / framePr）', () => {
  function paraWith(props: ParagraphNode['props']): ParagraphNode {
    return { type: 'paragraph', runs: [makeRun('x')], props };
  }
  function getDocXml(para: ParagraphNode): string {
    return unzipToText(writer.write(makeDoc([makeSection([para])])))['word/document.xml'];
  }

  // ── pBdr ────────────────────────────────────────────────────────────────────

  it('borders 全四邊 → <w:pBdr> 含 top/bottom/left/right', () => {
    const xml = getDocXml(paraWith({
      borders: {
        top:    { style: 'single', width: 0.5, color: '000000' },
        bottom: { style: 'single', width: 0.5, color: '000000' },
        left:   { style: 'double', width: 1, color: 'FF0000' },
        right:  { style: 'double', width: 1, color: 'FF0000' },
      },
    }));
    expect(xml).toContain('<w:pBdr>');
    expect(xml).toContain('<w:top ');
    expect(xml).toContain('<w:bottom ');
    expect(xml).toContain('<w:left ');
    expect(xml).toContain('<w:right ');
  });

  it('borders w:sz 單位為 1/8 pt（width 0.5pt → sz=4、width 1pt → sz=8）', () => {
    const xml = getDocXml(paraWith({
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
    }));
    expect(xml).toContain('w:sz="4"');
    const xml2 = getDocXml(paraWith({
      borders: { top: { style: 'single', width: 1, color: '000000' } },
    }));
    expect(xml2).toContain('w:sz="8"');
  });

  it('borders space → w:space 屬性（缺漏跳過）', () => {
    const xml = getDocXml(paraWith({
      borders: { top: { style: 'single', width: 0.5, color: '000000', space: 4 } },
    }));
    expect(xml).toContain('w:space="4"');
    const xml2 = getDocXml(paraWith({
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
    }));
    expect(xml2).not.toContain('w:space=');
  });

  it('borders 僅單邊 → 只輸出該邊', () => {
    const xml = getDocXml(paraWith({
      borders: { bottom: { style: 'single', width: 0.5, color: '000000' } },
    }));
    expect(xml).toContain('<w:bottom ');
    expect(xml).not.toContain('<w:top ');
    expect(xml).not.toContain('<w:left ');
    expect(xml).not.toContain('<w:right ');
  });

  // ── shd ─────────────────────────────────────────────────────────────────────

  it('shading fill/color/pattern → <w:shd>', () => {
    const xml = getDocXml(paraWith({
      shading: { fill: 'DEEAF6', color: 'auto', pattern: 'clear' },
    }));
    expect(xml).toContain('<w:shd ');
    expect(xml).toContain('w:val="clear"');
    expect(xml).toContain('w:fill="DEEAF6"');
    expect(xml).toContain('w:color="auto"');
  });

  it('shading 部分欄位 → 缺漏屬性跳過', () => {
    const xml = getDocXml(paraWith({ shading: { fill: 'FFFF00' } }));
    expect(xml).toContain('w:fill="FFFF00"');
    expect(xml).not.toContain('w:val=');
    expect(xml).not.toContain('w:color=');
  });

  // ── framePr ─────────────────────────────────────────────────────────────────

  it('framePr 完整屬性 → <w:framePr/>（w/h/hSpace/vSpace 為 twips）', () => {
    const xml = getDocXml(paraWith({
      framePr: {
        width: 100, height: 50, hRule: 'exact', hSpace: 4, vSpace: 4,
        wrap: 'around', hAnchor: 'page', vAnchor: 'margin',
        xAlign: 'center', yAlign: 'top', x: 10, y: 20,
      },
    }));
    expect(xml).toContain('w:w="2000"');         // 100pt × 20
    expect(xml).toContain('w:h="1000"');         // 50pt × 20
    expect(xml).toContain('w:hRule="exact"');
    expect(xml).toContain('w:hSpace="80"');      // 4pt × 20
    expect(xml).toContain('w:vSpace="80"');
    expect(xml).toContain('w:wrap="around"');
    expect(xml).toContain('w:hAnchor="page"');
    expect(xml).toContain('w:vAnchor="margin"');
    expect(xml).toContain('w:xAlign="center"');
    expect(xml).toContain('w:yAlign="top"');
    expect(xml).toContain('w:x="200"');
    expect(xml).toContain('w:y="400"');
  });

  it('framePr 部分欄位 → 缺漏屬性跳過', () => {
    const xml = getDocXml(paraWith({ framePr: { wrap: 'around', hAnchor: 'page' } }));
    // 取出 <w:framePr ... /> 區段（避開 sectPr 的 pgSz w:w）
    const m = xml.match(/<w:framePr[^/]*\/>/);
    expect(m).not.toBeNull();
    const frameXml = m![0];
    expect(frameXml).toContain('w:wrap="around"');
    expect(frameXml).toContain('w:hAnchor="page"');
    // framePr 自身不應含 width/height 屬性
    expect(frameXml).not.toMatch(/\bw:w="/);
    expect(frameXml).not.toMatch(/\bw:h="/);
  });

  // ── schema 順序 ─────────────────────────────────────────────────────────────

  it('schema 順序：framePr → numPr → pBdr → shd → tabs', () => {
    const xml = getDocXml(paraWith({
      framePr: { wrap: 'around' },
      numId: 1, ilvl: 0,
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
      shading: { fill: 'FFFF00' },
      tabs: [{ pos: 100, align: 'left' }],
    }));
    const indices = [
      ['framePr', xml.indexOf('<w:framePr')],
      ['numPr', xml.indexOf('<w:numPr')],
      ['pBdr', xml.indexOf('<w:pBdr')],
      ['shd', xml.indexOf('<w:shd ')],
      ['tabs', xml.indexOf('<w:tabs')],
    ] as const;
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i][1]).toBeGreaterThan(indices[i - 1][1]);
    }
  });
});

describe('OoxmlWriter — Sprint 189 Styles.xml 輸出', () => {
  function getStylesXml(styles: DocumentNode['styles']): string {
    const doc = makeDoc([makeSection([])]);
    doc.styles = styles;
    return unzipToText(writer.write(doc))['word/styles.xml'];
  }

  it('空 styles map → 空 <w:styles/> 骨架（與 MVS 相容）', () => {
    const xml = getStylesXml(new Map());
    expect(xml).toContain('<w:styles xmlns:w=');
    expect(xml).toMatch(/<w:styles[^>]*\/>/);
    expect(xml).not.toContain('<w:style ');
  });

  it('單一空 entry → <w:style w:type="paragraph" w:styleId="X"/>（self-closing）', () => {
    const xml = getStylesXml(new Map([['Heading1', {}]]));
    expect(xml).toContain('<w:style w:type="paragraph" w:styleId="Heading1"/>');
  });

  it('entry 含 pProps → <w:style ...><w:pPr>...</w:pPr></w:style>', () => {
    const xml = getStylesXml(new Map([
      ['Heading1', { pProps: { alignment: 'center', keepNext: true } }],
    ]));
    expect(xml).toContain('<w:style w:type="paragraph" w:styleId="Heading1">');
    expect(xml).toContain('<w:pPr>');
    expect(xml).toContain('<w:jc w:val="center"/>');
    expect(xml).toContain('<w:keepNext/>');
    expect(xml).toContain('</w:style>');
  });

  it('entry 含 rProps → <w:style ...><w:rPr>...</w:rPr></w:style>', () => {
    const xml = getStylesXml(new Map([
      ['Strong', { rProps: { bold: true, fontSize: 14 } }],
    ]));
    expect(xml).toContain('<w:rPr>');
    expect(xml).toContain('<w:b/>');
    expect(xml).toContain('<w:sz w:val="28"/>');  // 14pt × 2 half-points
  });

  it('entry 同時含 pProps 與 rProps → 兩者皆輸出', () => {
    const xml = getStylesXml(new Map([
      ['Title', { pProps: { alignment: 'center' }, rProps: { bold: true } }],
    ]));
    expect(xml).toContain('<w:pPr>');
    expect(xml).toContain('<w:rPr>');
    expect(xml.indexOf('<w:pPr>')).toBeLessThan(xml.indexOf('<w:rPr>'));
  });

  it('多 entry → 依 Map 順序輸出', () => {
    const xml = getStylesXml(new Map([
      ['A', { rProps: { bold: true } }],
      ['B', { rProps: { italic: true } }],
      ['C', { pProps: { alignment: 'right' } }],
    ]));
    const aIdx = xml.indexOf('w:styleId="A"');
    const bIdx = xml.indexOf('w:styleId="B"');
    const cIdx = xml.indexOf('w:styleId="C"');
    expect(aIdx).toBeLessThan(bIdx);
    expect(bIdx).toBeLessThan(cIdx);
  });

  it('styleId 內含 XML 特殊字元 → 跳脫', () => {
    const xml = getStylesXml(new Map([['A&B<C', {}]]));
    expect(xml).toContain('w:styleId="A&amp;B&lt;C"');
  });

  it('不輸出 docDefaults / basedOn（parser 已 flatten）', () => {
    const xml = getStylesXml(new Map([
      ['X', { pProps: { alignment: 'left' }, rProps: { bold: true } }],
    ]));
    expect(xml).not.toContain('<w:docDefaults');
    expect(xml).not.toContain('<w:basedOn');
  });
});

describe('OoxmlWriter — Sprint 190 表格 export', () => {
  function makeCell(content: BlockNode[], props: CellNode['props'] = {}, opts: Partial<CellNode> = {}): CellNode {
    return {
      type: 'cell', gridCol: opts.gridCol ?? 0, gridSpan: opts.gridSpan ?? 1,
      rowSpan: opts.rowSpan ?? 1, isContinuation: opts.isContinuation ?? false,
      content, props,
    };
  }
  function makeRow(cells: CellNode[], props: Partial<RowNode['props']> = {}): RowNode {
    return { type: 'row', cells, props: { isHeader: false, cantSplit: false, ...props } };
  }
  function makeTable(grid: number[], rows: RowNode[], props: TableNode['props'] = {}, styleId?: string): TableNode {
    const t: TableNode = { type: 'table', grid, rows, props };
    if (styleId) t.styleId = styleId;
    return t;
  }
  function getDocXml(blocks: BlockNode[]): string {
    return unzipToText(writer.write(makeDoc([makeSection(blocks)])))['word/document.xml'];
  }

  // ── 基本結構 ────────────────────────────────────────────────────────────────

  it('空表格 → <w:tbl><w:tblPr>...</w:tblPr><w:tblGrid/></w:tbl>', () => {
    const xml = getDocXml([makeTable([], [])]);
    expect(xml).toContain('<w:tbl>');
    expect(xml).toContain('<w:tblPr>');
    expect(xml).toContain('<w:tblGrid>');
    expect(xml).toContain('</w:tbl>');
  });

  it('tblGrid 由 grid array 寫出 gridCol（pt → twips）', () => {
    const xml = getDocXml([makeTable([100, 200, 300], [])]);
    expect(xml).toContain('<w:gridCol w:w="2000"/>');
    expect(xml).toContain('<w:gridCol w:w="4000"/>');
    expect(xml).toContain('<w:gridCol w:w="6000"/>');
  });

  // ── 單一儲存格 ─────────────────────────────────────────────────────────────

  it('單列單格含段落 → <w:tr><w:tc>...<w:p>...</w:p></w:tc></w:tr>', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [makeRun('A')], props: {} }]);
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).toContain('<w:tr>');
    expect(xml).toContain('<w:tc>');
    expect(xml).toContain('>A<');
    expect(xml).toContain('</w:tc>');
    expect(xml).toContain('</w:tr>');
  });

  it('空 cell content → 自動補 <w:p/>（OOXML 規範每個 tc 必含至少一 block）', () => {
    const cell = makeCell([]);
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).toContain('<w:tc><w:p/></w:tc>');
  });

  // ── 表格層級屬性 ─────────────────────────────────────────────────────────

  it('tblPr：tblStyle / tblW / jc / tblInd / tblLook', () => {
    const table = makeTable([100], [], {
      width: 500, widthType: 'dxa',
      alignment: 'center', indent: 36,
      look: '04A0',
    }, 'TableGrid');
    const xml = getDocXml([table]);
    expect(xml).toContain('<w:tblStyle w:val="TableGrid"/>');
    expect(xml).toContain('<w:tblW w:w="10000" w:type="dxa"/>');
    expect(xml).toContain('<w:jc w:val="center"/>');
    expect(xml).toContain('<w:tblInd w:w="720" w:type="dxa"/>');
    expect(xml).toContain('<w:tblLook w:val="04A0"/>');
  });

  it('tblW 非 dxa 型別（pct/auto/nil）→ w:w="0"（與 parser 對稱）', () => {
    for (const t of ['pct', 'auto', 'nil'] as const) {
      const xml = getDocXml([makeTable([], [], { widthType: t })]);
      expect(xml).toContain(`<w:tblW w:w="0" w:type="${t}"/>`);
    }
  });

  it('tblBorders / tblCellMar', () => {
    const table = makeTable([], [], {
      borders: {
        top: { style: 'single', width: 0.5, color: '000000' },
        insideH: { style: 'single', width: 0.5, color: '808080' },
      },
      cellMargins: { top: 4, left: 8, bottom: 4, right: 8 },
    });
    const xml = getDocXml([table]);
    expect(xml).toContain('<w:tblBorders>');
    expect(xml).toContain('<w:top w:val="single" w:sz="4" w:color="000000"/>');
    expect(xml).toContain('<w:insideH ');
    expect(xml).toContain('<w:tblCellMar>');
    expect(xml).toContain('<w:left w:w="160" w:type="dxa"/>');
  });

  // ── trPr ───────────────────────────────────────────────────────────────────

  it('trPr：trHeight + heightRule / tblHeader / cantSplit', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }]);
    const row = makeRow([cell], { height: 20, heightRule: 'exact', isHeader: true, cantSplit: true });
    const xml = getDocXml([makeTable([100], [row])]);
    expect(xml).toContain('<w:trHeight w:val="400" w:hRule="exact"/>');
    expect(xml).toContain('<w:tblHeader/>');
    expect(xml).toContain('<w:cantSplit/>');
  });

  // ── tcPr ───────────────────────────────────────────────────────────────────

  it('tcPr：tcW / vAlign / noWrap / textDirection', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }], {
      width: 80, vAlign: 'center', noWrap: true, textDirection: 'tbRlV',
    });
    const xml = getDocXml([makeTable([80], [makeRow([cell])])]);
    expect(xml).toContain('<w:tcW w:w="1600" w:type="dxa"/>');
    expect(xml).toContain('<w:vAlign w:val="center"/>');
    expect(xml).toContain('<w:noWrap/>');
    expect(xml).toContain('<w:textDirection w:val="tbRlV"/>');
  });

  it('tcPr：tcBorders + shading + margins', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }], {
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
      shading: { fill: 'DEEAF6', pattern: 'clear' },
      margins: { top: 4, left: 8 },
    });
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).toContain('<w:tcBorders>');
    expect(xml).toContain('<w:shd ');
    expect(xml).toContain('w:fill="DEEAF6"');
    expect(xml).toContain('<w:tcMar>');
  });

  // ── gridSpan / vMerge ───────────────────────────────────────────────────

  it('gridSpan > 1 → <w:gridSpan w:val>', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }], {}, { gridSpan: 3 });
    const xml = getDocXml([makeTable([100, 100, 100], [makeRow([cell])])]);
    expect(xml).toContain('<w:gridSpan w:val="3"/>');
  });

  it('gridSpan = 1 → 不輸出 gridSpan（紀律 #21）', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }]);
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).not.toContain('<w:gridSpan');
  });

  it('vMerge restart（rowSpan>1 且非延續）→ <w:vMerge w:val="restart"/>', () => {
    const cell = makeCell([{ type: 'paragraph', runs: [], props: {} }], {}, { rowSpan: 2 });
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).toContain('<w:vMerge w:val="restart"/>');
  });

  it('vMerge continue（isContinuation=true）→ <w:vMerge/>（無 val、預設 continue）', () => {
    const cell = makeCell([], {}, { isContinuation: true });
    const xml = getDocXml([makeTable([100], [makeRow([cell])])]);
    expect(xml).toContain('<w:vMerge/>');
    // 自動補空段落
    expect(xml).toContain('<w:p/>');
  });

  // ── 巢狀表格 ───────────────────────────────────────────────────────────

  it('巢狀表格：cell 內含 inner TableNode → 遞迴輸出', () => {
    const inner = makeTable([50], [makeRow([
      makeCell([{ type: 'paragraph', runs: [makeRun('inner')], props: {} }]),
    ])]);
    const outerCell = makeCell([inner]);
    const xml = getDocXml([makeTable([100], [makeRow([outerCell])])]);
    // 兩層 <w:tbl>
    expect((xml.match(/<w:tbl>/g) ?? []).length).toBe(2);
    expect(xml).toContain('>inner<');
  });

  // ── 多列多格 ───────────────────────────────────────────────────────────

  it('2 列 × 2 格 → <w:tr> × 2、每列 <w:tc> × 2', () => {
    const c = (text: string) => makeCell([{ type: 'paragraph', runs: [makeRun(text)], props: {} }]);
    const xml = getDocXml([makeTable([100, 100], [
      makeRow([c('A'), c('B')]),
      makeRow([c('C'), c('D')]),
    ])]);
    expect((xml.match(/<w:tr>/g) ?? []).length).toBe(2);
    expect((xml.match(/<w:tc>/g) ?? []).length).toBe(4);
    expect(xml).toContain('>A<');
    expect(xml).toContain('>D<');
  });
});

describe('OoxmlWriter — Sprint 191 多 section + numbering.xml', () => {
  // ── 多 section ───────────────────────────────────────────────────────────

  it('多 section anchor paragraph 結構 + sectPr 順序', () => {
    const doc = makeDoc([
      makeSection([makeParagraph([makeRun('一')])]),
      makeSection([makeParagraph([makeRun('二')])]),
      makeSection([makeParagraph([makeRun('三')])]),
    ]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    // 3 sections → 2 個 anchor + 1 個 body 尾 = 3 個 sectPr
    expect((xml.match(/<w:sectPr>/g) ?? []).length).toBe(3);
    // 2 個 anchor paragraph 結構
    expect((xml.match(/<w:p><w:pPr><w:sectPr>/g) ?? []).length).toBe(2);
    // 三段文字皆存在
    expect(xml).toContain('>一<');
    expect(xml).toContain('>二<');
    expect(xml).toContain('>三<');
  });

  it('單一 section → 仍只有 body 尾的 sectPr、無 anchor paragraph', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('only')])])]);
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect((xml.match(/<w:sectPr>/g) ?? []).length).toBe(1);
    expect(xml).not.toContain('<w:p><w:pPr><w:sectPr>');
  });

  // ── numbering.xml ───────────────────────────────────────────────────────

  function getNumberingXml(numbering: DocumentNode['numbering']): string {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = numbering;
    return unzipToText(writer.write(doc))['word/numbering.xml'];
  }

  it('空 numbering map → 空 <w:numbering/> 骨架', () => {
    const xml = getNumberingXml(new Map());
    expect(xml).toMatch(/<w:numbering[^>]*\/>/);
    expect(xml).not.toContain('<w:abstractNum');
  });

  it('Content Types 含 numbering override + document rels 含 numbering 關係', () => {
    const bytes = writer.write(makeDoc([makeSection([])]));
    const files = unzipToText(bytes);
    expect(files['[Content_Types].xml']).toContain('PartName="/word/numbering.xml"');
    expect(files['[Content_Types].xml']).toContain('wordprocessingml.numbering+xml');
    expect(files['word/_rels/document.xml.rels']).toContain('Target="numbering.xml"');
    expect(files['word/_rels/document.xml.rels']).toContain('relationships/numbering');
  });

  it('單一 numId/entry → <w:abstractNum> + <w:num>', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, {
        abstractNumId: 5,
        levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }],
      }],
    ]);
    const xml = getNumberingXml(numbering);
    // 用 numId 當 abstractNumId（=1、不是原 5）保證唯一
    expect(xml).toContain('<w:abstractNum w:abstractNumId="1">');
    expect(xml).toContain('<w:lvl w:ilvl="0">');
    expect(xml).toContain('<w:start w:val="1"/>');
    expect(xml).toContain('<w:numFmt w:val="decimal"/>');
    expect(xml).toContain('<w:lvlText w:val="%1."/>');
    expect(xml).toContain('<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>');
  });

  it('多層 levels（ilvl 0/1/2）→ 依序輸出', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, {
        abstractNumId: 0,
        levels: [
          { ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 },
          { ilvl: 1, numFmt: 'lowerLetter', text: '%2)', start: 1 },
          { ilvl: 2, numFmt: 'lowerRoman', text: '%3.', start: 1 },
        ],
      }],
    ]);
    const xml = getNumberingXml(numbering);
    expect((xml.match(/<w:lvl /g) ?? []).length).toBe(3);
    expect(xml).toContain('w:ilvl="0"');
    expect(xml).toContain('w:ilvl="1"');
    expect(xml).toContain('w:ilvl="2"');
    expect(xml).toContain('w:val="lowerLetter"');
    expect(xml).toContain('w:val="lowerRoman"');
  });

  it('lvlRestart / isLegal toggle 輸出', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, {
        abstractNumId: 0,
        levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1, lvlRestart: 0, isLegal: true }],
      }],
    ]);
    const xml = getNumberingXml(numbering);
    expect(xml).toContain('<w:lvlRestart w:val="0"/>');
    expect(xml).toContain('<w:isLgl/>');
  });

  it('indent 合併進 pPr（parser 分離 indent 與 pProps）', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, {
        abstractNumId: 0,
        levels: [{
          ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1,
          indent: { left: 36, hanging: 18 },
        }],
      }],
    ]);
    const xml = getNumberingXml(numbering);
    expect(xml).toContain('<w:pPr>');
    expect(xml).toContain('w:left="720"');   // 36pt × 20
    expect(xml).toContain('w:hanging="360"'); // 18pt × 20
  });

  it('level runProps → <w:rPr>', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, {
        abstractNumId: 0,
        levels: [{
          ilvl: 0, numFmt: 'bullet', text: '•', start: 1,
          runProps: { bold: true, fontFamily: 'Symbol' },
        }],
      }],
    ]);
    const xml = getNumberingXml(numbering);
    expect(xml).toContain('<w:rPr>');
    expect(xml).toContain('<w:b/>');
    expect(xml).toContain('w:ascii="Symbol"');
  });

  it('多 entry → 各自 abstractNum + num', () => {
    const numbering: DocumentNode['numbering'] = new Map([
      [1, { abstractNumId: 0, levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }] }],
      [2, { abstractNumId: 1, levels: [{ ilvl: 0, numFmt: 'bullet', text: '•', start: 1 }] }],
    ]);
    const xml = getNumberingXml(numbering);
    expect((xml.match(/<w:abstractNum /g) ?? []).length).toBe(2);
    expect((xml.match(/<w:num /g) ?? []).length).toBe(2);
    expect(xml).toContain('w:numId="1"');
    expect(xml).toContain('w:numId="2"');
  });
});

describe('OoxmlWriter — Sprint 192 圖片 / media export', () => {
  // 1x1 透明 PNG（已知有效、用於測試）
  const PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=';
  const PNG_DATA_URL = `data:image/png;base64,${PNG_B64}`;
  // 最小 JPEG（白色 1x1，僅供測試 mime 多樣性）
  const JPG_DATA_URL = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAASABIAAD/2wBDAP//';

  function imageRun(rId: string, width = 50, height = 50, altText?: string) {
    const n: { type: 'inlineImage'; rId: string; width: number; height: number; altText?: string } =
      { type: 'inlineImage', rId, width, height };
    if (altText) n.altText = altText;
    return n;
  }

  function getDocXml(media: Map<string, string>, runs: ReturnType<typeof imageRun>[] = []): string {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [makeRun('text'), ...runs], props: {} },
    ])]);
    doc.media = media;
    return unzipToText(writer.write(doc))['word/document.xml'];
  }

  function getAllParts(media: Map<string, string>) {
    const doc = makeDoc([makeSection([])]);
    doc.media = media;
    return unzipToText(writer.write(doc));
  }

  // ── zip 結構 ────────────────────────────────────────────────────────────

  it('無 media → 仍是 6 part（無 media 檔加入）', () => {
    const parts = getAllParts(new Map());
    expect(Object.keys(parts).filter((p) => p.startsWith('word/media/'))).toHaveLength(0);
  });

  it('單張 PNG → word/media/image1.png 寫入 zip', () => {
    const parts = getAllParts(new Map([['rId10', PNG_DATA_URL]]));
    expect(parts['word/media/image1.png']).toBeDefined();
    // PNG 簽名：89 50 4E 47
    const bin = unzipSync(writer.write(((): DocumentNode => {
      const d = makeDoc([makeSection([])]); d.media = new Map([['rId10', PNG_DATA_URL]]); return d;
    })()));
    const png = bin['word/media/image1.png'];
    expect(png[0]).toBe(0x89);
    expect(png[1]).toBe(0x50);
    expect(png[2]).toBe(0x4E);
    expect(png[3]).toBe(0x47);
  });

  it('Content Types 含 image 副檔名 Default（png）', () => {
    const parts = getAllParts(new Map([['rId1', PNG_DATA_URL]]));
    expect(parts['[Content_Types].xml']).toContain('<Default Extension="png" ContentType="image/png"/>');
  });

  it('多種 mime → 各自 Default + 各自檔名（image1.png / image2.jpeg）', () => {
    const parts = getAllParts(new Map([
      ['rIdA', PNG_DATA_URL],
      ['rIdB', JPG_DATA_URL],
    ]));
    expect(parts['[Content_Types].xml']).toContain('Extension="png"');
    expect(parts['[Content_Types].xml']).toContain('Extension="jpeg"');
    expect(parts['word/media/image1.png']).toBeDefined();
    expect(parts['word/media/image2.jpeg']).toBeDefined();
  });

  it('document.xml.rels 含 image relationship + styles/numbering 改用具名 Id', () => {
    const parts = getAllParts(new Map([['rIdImg', PNG_DATA_URL]]));
    const rels = parts['word/_rels/document.xml.rels'];
    expect(rels).toContain('Id="rIdStyles"');
    expect(rels).toContain('Id="rIdNumbering"');
    expect(rels).toContain('Id="rIdImg"');
    expect(rels).toContain('Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"');
    expect(rels).toContain('Target="media/image1.png"');
  });

  it('非 image/* 的 data URL → 跳過（不寫入 zip、不影響其他 part）', () => {
    const parts = getAllParts(new Map([
      ['rIdTxt', 'data:text/plain;base64,SGVsbG8='],
      ['rIdImg', PNG_DATA_URL],
    ]));
    // 只有 image 那筆會輸出
    expect(parts['word/media/image1.png']).toBeDefined();
    // text/plain 不在
    const rels = parts['word/_rels/document.xml.rels'];
    expect(rels).toContain('rIdImg');
    expect(rels).not.toContain('rIdTxt');
  });

  // ── document.xml 內 <w:drawing> ────────────────────────────────────────

  it('InlineImageNode → <w:r><w:drawing><wp:inline>...<a:blip r:embed=...>', () => {
    const media = new Map([['rId7', PNG_DATA_URL]]);
    const xml = getDocXml(media, [imageRun('rId7', 100, 50)]);
    expect(xml).toContain('<w:drawing>');
    expect(xml).toContain('<wp:inline ');
    expect(xml).toContain('r:embed="rId7"');
    expect(xml).toContain('<pic:pic ');
    expect(xml).toContain('<a:prstGeom prst="rect"');
  });

  it('extent cx/cy 換 EMU（100pt × 12700 = 1270000）', () => {
    const media = new Map([['rId1', PNG_DATA_URL]]);
    const xml = getDocXml(media, [imageRun('rId1', 100, 50)]);
    expect(xml).toContain('cx="1270000"');
    expect(xml).toContain('cy="635000"');
  });

  it('altText → wp:docPr descr 屬性', () => {
    const media = new Map([['rId1', PNG_DATA_URL]]);
    const xml = getDocXml(media, [imageRun('rId1', 50, 50, '示意圖')]);
    expect(xml).toContain('descr="示意圖"');
  });

  it('多張圖片 → docPr id 遞增', () => {
    const media = new Map([['rIdA', PNG_DATA_URL], ['rIdB', PNG_DATA_URL]]);
    const xml = getDocXml(media, [imageRun('rIdA'), imageRun('rIdB')]);
    expect(xml).toContain('id="1"');
    expect(xml).toContain('id="2"');
  });

  it('FloatImageNode → 降級為 inline（同樣輸出 <wp:inline>、posH/posV 不輸出）', () => {
    const media = new Map([['rIdF', PNG_DATA_URL]]);
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [{
        type: 'floatImage', rId: 'rIdF', width: 80, height: 60,
        posH: { relativeFrom: 'column' }, posV: { relativeFrom: 'paragraph' },
        wrapType: 'square',
      }], props: {} },
    ])]);
    doc.media = media;
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<wp:inline ');
    expect(xml).not.toContain('<wp:anchor');
    expect(xml).toContain('r:embed="rIdF"');
  });

  // ── 計數器重置 ────────────────────────────────────────────────────────

  it('多次 write → docPr 計數器重置（不會累加）', () => {
    const media = new Map([['rIdX', PNG_DATA_URL]]);
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [imageRun('rIdX')], props: {} },
    ])]);
    doc.media = media;
    const xml1 = unzipToText(writer.write(doc))['word/document.xml'];
    const xml2 = unzipToText(writer.write(doc))['word/document.xml'];
    // 兩次都從 id="1" 開始
    expect(xml1).toContain('id="1"');
    expect(xml2).toContain('id="1"');
  });
});

describe('OoxmlWriter — Sprint 193 頁首頁尾 export', () => {
  function makeHF(content: BlockNode[]): { rId: string; content: BlockNode[] } {
    return { rId: '', content };  // rId 由 Map key 提供、欄位不重要
  }
  function getParts(headers: Map<string, ReturnType<typeof makeHF>>, footers: Map<string, ReturnType<typeof makeHF>>, secRefs?: Partial<SectionNode>): Record<string, string> {
    const sec = makeSection([makeParagraph([makeRun('body')])]);
    if (secRefs) Object.assign(sec, secRefs);
    const doc = makeDoc([sec]);
    doc.headers = headers as DocumentNode['headers'];
    doc.footers = footers as DocumentNode['footers'];
    return unzipToText(writer.write(doc));
  }

  // ── 部件寫入 ────────────────────────────────────────────────────────────

  it('單一 header → word/header1.xml 寫入 + <w:hdr> 結構', () => {
    const headers = new Map([['rIdH1', makeHF([makeParagraph([makeRun('頁首文字')])])]]);
    const parts = getParts(headers, new Map());
    expect(parts['word/header1.xml']).toBeDefined();
    expect(parts['word/header1.xml']).toContain('<w:hdr ');
    expect(parts['word/header1.xml']).toContain('xmlns:w=');
    expect(parts['word/header1.xml']).toContain('xmlns:r=');
    expect(parts['word/header1.xml']).toContain('>頁首文字<');
    expect(parts['word/header1.xml']).toContain('</w:hdr>');
  });

  it('單一 footer → word/footer1.xml 寫入 + <w:ftr> 結構', () => {
    const footers = new Map([['rIdF1', makeHF([makeParagraph([makeRun('頁尾文字')])])]]);
    const parts = getParts(new Map(), footers);
    expect(parts['word/footer1.xml']).toBeDefined();
    expect(parts['word/footer1.xml']).toContain('<w:ftr ');
    expect(parts['word/footer1.xml']).toContain('>頁尾文字<');
  });

  it('多 header/footer → 流水號 headerN/footerN', () => {
    const headers = new Map([
      ['rIdH1', makeHF([makeParagraph([makeRun('一')])])],
      ['rIdH2', makeHF([makeParagraph([makeRun('二')])])],
    ]);
    const footers = new Map([
      ['rIdF1', makeHF([makeParagraph([makeRun('甲')])])],
    ]);
    const parts = getParts(headers, footers);
    expect(parts['word/header1.xml']).toBeDefined();
    expect(parts['word/header2.xml']).toBeDefined();
    expect(parts['word/footer1.xml']).toBeDefined();
    expect(parts['word/header1.xml']).toContain('>一<');
    expect(parts['word/header2.xml']).toContain('>二<');
  });

  it('header 內含表格 → BlockNode 遞迴 dispatcher 正確輸出', () => {
    const headers = new Map([['rIdH1', makeHF([
      makeParagraph([makeRun('文字')]),
      { type: 'table', grid: [100], rows: [], props: {} },
    ])]]);
    const parts = getParts(headers, new Map());
    expect(parts['word/header1.xml']).toContain('<w:p>');
    expect(parts['word/header1.xml']).toContain('<w:tbl>');
  });

  // ── Content_Types / rels ─────────────────────────────────────────────────

  it('Content_Types 含 header/footer override', () => {
    const headers = new Map([['rIdH1', makeHF([makeParagraph([])])]]);
    const footers = new Map([['rIdF1', makeHF([makeParagraph([])])]]);
    const ct = getParts(headers, footers)['[Content_Types].xml'];
    expect(ct).toContain('PartName="/word/header1.xml"');
    expect(ct).toContain('PartName="/word/footer1.xml"');
    expect(ct).toContain('wordprocessingml.header+xml');
    expect(ct).toContain('wordprocessingml.footer+xml');
  });

  it('document rels 含 header/footer relationship（rId 保留）', () => {
    const headers = new Map([['rIdH1', makeHF([])]]);
    const footers = new Map([['rIdF1', makeHF([])]]);
    const rels = getParts(headers, footers)['word/_rels/document.xml.rels'];
    expect(rels).toContain('Id="rIdH1"');
    expect(rels).toContain('Target="header1.xml"');
    expect(rels).toContain('relationships/header');
    expect(rels).toContain('Id="rIdF1"');
    expect(rels).toContain('Target="footer1.xml"');
    expect(rels).toContain('relationships/footer');
  });

  // ── sectPr references ─────────────────────────────────────────────────

  it('sectPr 含 <w:headerReference> + <w:footerReference>（依 default/first/even）', () => {
    const headers = new Map([['rIdHdef', makeHF([])]]);
    const footers = new Map([
      ['rIdFdef', makeHF([])],
      ['rIdFfirst', makeHF([])],
    ]);
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    doc.headers = headers as DocumentNode['headers'];
    doc.footers = footers as DocumentNode['footers'];
    // 手動設置 refs
    doc.sections[0].headerRefs = { default: 'rIdHdef' };
    doc.sections[0].footerRefs = { default: 'rIdFdef', first: 'rIdFfirst' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:headerReference w:type="default" r:id="rIdHdef"/>');
    expect(xml).toContain('<w:footerReference w:type="default" r:id="rIdFdef"/>');
    expect(xml).toContain('<w:footerReference w:type="first" r:id="rIdFfirst"/>');
  });

  it('section.titlePage = true → sectPr 內 <w:titlePg/>', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    doc.sections[0].titlePage = true;
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:titlePg/>');
  });

  it('document.xml root 含 xmlns:r 宣告（給 headerReference r:id 用）', () => {
    const xml = unzipToText(writer.write(makeDoc([makeSection([])])))['word/document.xml'];
    expect(xml).toMatch(/<w:document[^>]*xmlns:r=/);
  });

  it('schema 順序：headerReference / footerReference 在 pgSz 之前', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    doc.headers = new Map([['rIdH', makeHF([])]]) as DocumentNode['headers'];
    doc.sections[0].headerRefs = { default: 'rIdH' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml.indexOf('<w:headerReference')).toBeLessThan(xml.indexOf('<w:pgSz'));
  });

  // ── 無 header/footer → 不寫入 ──────────────────────────────────────────

  it('無 header/footer → 不輸出對應部件、Content_Types/rels 無條目', () => {
    const parts = getParts(new Map(), new Map());
    expect(parts['word/header1.xml']).toBeUndefined();
    expect(parts['word/footer1.xml']).toBeUndefined();
    expect(parts['[Content_Types].xml']).not.toContain('header+xml');
    expect(parts['[Content_Types].xml']).not.toContain('footer+xml');
    expect(parts['word/_rels/document.xml.rels']).not.toContain('relationships/header');
  });
});

describe('OoxmlWriter — Sprint 194 Phase 5 子功能 export', () => {
  // ── OMML ───────────────────────────────────────────────────────────────

  function paraMath(math: ParagraphNode['math']): ParagraphNode {
    const p: ParagraphNode = { type: 'paragraph', runs: [makeRun('x')], props: {} };
    if (math) p.math = math;
    return p;
  }
  function getDocXmlFromBlocks(blocks: BlockNode[]): string {
    return unzipToText(writer.write(makeDoc([makeSection(blocks)])))['word/document.xml'];
  }

  it('OMML inline 公式 → 段落內 <m:oMath>（無 oMathPara 包裹）', () => {
    const math = [{
      display: false,
      omml: [{ tag: 'r', children: [{ tag: 't', text: 'x+1' }] }],
    }];
    const xml = getDocXmlFromBlocks([paraMath(math)]);
    expect(xml).toContain('<m:oMath ');
    expect(xml).not.toContain('<m:oMathPara');
    expect(xml).toContain('<m:r>');
    expect(xml).toContain('<m:t>x+1</m:t>');
  });

  it('OMML display 公式 → <m:oMathPara><m:oMath>', () => {
    const math = [{
      display: true,
      omml: [{ tag: 'r', children: [{ tag: 't', text: 'y' }] }],
    }];
    const xml = getDocXmlFromBlocks([paraMath(math)]);
    expect(xml).toContain('<m:oMathPara ');
    expect(xml).toContain('<m:oMath ');
  });

  it('OMML 結構元素（分數）+ attrs 寫回', () => {
    const math = [{
      display: false,
      omml: [{
        tag: 'f',
        children: [
          { tag: 'num', children: [{ tag: 'r', children: [{ tag: 't', text: 'a' }] }] },
          { tag: 'den', children: [{ tag: 'r', children: [{ tag: 't', text: 'b' }] }] },
        ],
      }],
    }];
    const xml = getDocXmlFromBlocks([paraMath(math)]);
    expect(xml).toContain('<m:f>');
    expect(xml).toContain('<m:num>');
    expect(xml).toContain('<m:den>');
  });

  it('OMML attrs（n 元運算子 chr）寫回', () => {
    const math = [{
      display: false,
      omml: [{
        tag: 'nary',
        children: [{
          tag: 'naryPr',
          children: [{ tag: 'chr', attrs: { val: '∑' } }],
        }],
      }],
    }];
    const xml = getDocXmlFromBlocks([paraMath(math)]);
    expect(xml).toContain('<m:chr m:val="∑"/>');
  });

  it('OMML 無 children 無 text → self-closing', () => {
    const math = [{
      display: false,
      omml: [{ tag: 'r' }],
    }];
    const xml = getDocXmlFromBlocks([paraMath(math)]);
    expect(xml).toContain('<m:r/>');
  });

  // ── 追蹤修訂 ─────────────────────────────────────────────────────────────

  function runWithRev(text: string, type: 'ins' | 'del', meta?: { id?: number; author?: string; date?: string }): RunNode {
    return {
      type: 'run', text, props: {},
      revision: { type, ...meta } as RunNode['revision'],
    };
  }

  it('追蹤修訂 ins → <w:ins> 包裹 <w:r><w:t>', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [runWithRev('插入內容', 'ins', { id: 5, author: 'Alice', date: '2024-01-01T00:00:00Z' })],
      props: {},
    };
    const xml = getDocXmlFromBlocks([para]);
    expect(xml).toContain('<w:ins ');
    expect(xml).toContain('w:id="5"');
    expect(xml).toContain('w:author="Alice"');
    expect(xml).toContain('w:date="2024-01-01T00:00:00Z"');
    expect(xml).toContain('<w:t xml:space="preserve">插入內容</w:t>');
    expect(xml).toContain('</w:ins>');
  });

  it('追蹤修訂 del → <w:del> + 內部 <w:delText>（不是 <w:t>）', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [runWithRev('要刪的字', 'del', { id: 7, author: 'Bob' })],
      props: {},
    };
    const xml = getDocXmlFromBlocks([para]);
    expect(xml).toContain('<w:del ');
    expect(xml).toContain('w:author="Bob"');
    expect(xml).toContain('<w:delText xml:space="preserve">要刪的字</w:delText>');
    expect(xml).not.toContain('<w:t xml:space="preserve">要刪的字</w:t>');
  });

  it('追蹤修訂 id / author / date 缺漏屬性 → 不掛 attribute（id 用 0 fallback）', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [runWithRev('x', 'ins')],
      props: {},
    };
    const xml = getDocXmlFromBlocks([para]);
    expect(xml).toContain('w:id="0"');
    expect(xml).not.toContain('w:author=');
    expect(xml).not.toContain('w:date=');
  });

  // ── 註解錨點 ─────────────────────────────────────────────────────────────

  it('para.commentRefs → <w:commentRangeStart> + <w:commentReference> + <w:commentRangeEnd>', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [makeRun('被註解的句子')],
      props: {},
      commentRefs: [0, 1],
    };
    const xml = getDocXmlFromBlocks([para]);
    expect(xml).toContain('<w:commentRangeStart w:id="0"/>');
    expect(xml).toContain('<w:commentRangeStart w:id="1"/>');
    expect(xml).toContain('<w:commentRangeEnd w:id="0"/>');
    expect(xml).toContain('<w:commentRangeEnd w:id="1"/>');
    expect(xml).toContain('<w:r><w:commentReference w:id="0"/></w:r>');
    expect(xml).toContain('<w:r><w:commentReference w:id="1"/></w:r>');
    // 順序：rangeStart 在 runs 之前、rangeEnd 在 runs 之後
    expect(xml.indexOf('<w:commentRangeStart')).toBeLessThan(xml.indexOf('被註解的句子'));
    expect(xml.indexOf('被註解的句子')).toBeLessThan(xml.indexOf('<w:commentRangeEnd'));
  });

  it('comments.xml 含 <w:comments>（即使空 Map）', () => {
    const parts = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(parts['word/comments.xml']).toContain('<w:comments');
  });

  it('comments.xml 寫出 doc.comments entries', () => {
    const doc = makeDoc([makeSection([])]);
    doc.comments = new Map([[0, {
      id: 0, author: 'Alice', date: '2024-01-01T00:00:00Z', initials: 'A',
      content: [{ type: 'paragraph', props: {}, runs: [makeRun('註解內容')] }],
    }]]);
    const xml = unzipToText(writer.write(doc))['word/comments.xml'];
    expect(xml).toContain('<w:comment ');
    expect(xml).toContain('w:id="0"');
    expect(xml).toContain('w:author="Alice"');
    expect(xml).toContain('w:date="2024-01-01T00:00:00Z"');
    expect(xml).toContain('w:initials="A"');
    expect(xml).toContain('>註解內容<');
  });

  it('Content_Types 含 comments override + rels 含 comments 關係', () => {
    const parts = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(parts['[Content_Types].xml']).toContain('PartName="/word/comments.xml"');
    expect(parts['[Content_Types].xml']).toContain('wordprocessingml.comments+xml');
    expect(parts['word/_rels/document.xml.rels']).toContain('Target="comments.xml"');
    expect(parts['word/_rels/document.xml.rels']).toContain('relationships/comments');
  });

  // ── background ───────────────────────────────────────────────────────────

  it('background → <w:background w:color> 在 <w:body> 之前', () => {
    const doc = makeDoc([makeSection([])]);
    doc.background = { color: 'FFFF00' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:background w:color="FFFF00"/>');
    expect(xml.indexOf('<w:background')).toBeLessThan(xml.indexOf('<w:body>'));
  });

  it('無 background → 不輸出 <w:background>', () => {
    const xml = unzipToText(writer.write(makeDoc([makeSection([])])))['word/document.xml'];
    expect(xml).not.toContain('<w:background');
  });
});

describe('OoxmlWriter — Sprint 195 SmartArt + Chart export', () => {
  // ── SmartArt ────────────────────────────────────────────────────────

  it('SmartArt → word/diagrams/data1.xml + Content_Types Override + rels', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdSA1', width: 200, height: 100,
        graphic: { kind: 'diagram', relId: 'rIdSA1' },
      }] },
    ])]);
    doc.smartArts = [{
      rId: 'rIdSA1',
      layoutType: 'urn:test:layout',
      texts: ['Step 1', 'Step 2', 'Step 3'],
    }];
    const parts = unzipToText(writer.write(doc));
    expect(parts['word/diagrams/data1.xml']).toBeDefined();
    expect(parts['word/diagrams/data1.xml']).toContain('<dgm:dataModel ');
    expect(parts['word/diagrams/data1.xml']).toContain('loTypeId="urn:test:layout"');
    expect(parts['word/diagrams/data1.xml']).toContain('>Step 1<');
    expect(parts['word/diagrams/data1.xml']).toContain('>Step 3<');
    expect(parts['[Content_Types].xml']).toContain('PartName="/word/diagrams/data1.xml"');
    expect(parts['[Content_Types].xml']).toContain('drawingml.diagramData+xml');
    expect(parts['word/_rels/document.xml.rels']).toContain('Id="rIdSA1"');
    expect(parts['word/_rels/document.xml.rels']).toContain('Target="diagrams/data1.xml"');
    expect(parts['word/_rels/document.xml.rels']).toContain('relationships/diagramData');
  });

  it('SmartArt graphicData → <dgm:relIds r:dm>（非 pic:pic）', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdSA1', width: 100, height: 50,
        graphic: { kind: 'diagram', relId: 'rIdSA1' },
      }] },
    ])]);
    doc.smartArts = [{ rId: 'rIdSA1', texts: ['x'] }];
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<dgm:relIds ');
    expect(xml).toContain('r:dm="rIdSA1"');
    expect(xml).not.toContain('<pic:pic');
  });

  // ── Chart ─────────────────────────────────────────────────────────

  it('Chart → word/charts/chart1.xml + Content_Types + rels', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdCh1', width: 200, height: 150,
        graphic: { kind: 'chart', relId: 'rIdCh1' },
      }] },
    ])]);
    doc.charts = [{
      rId: 'rIdCh1', chartType: 'barChart', title: '銷售額',
      series: [{ name: 'Q1', categories: ['A', 'B'], values: [10, 20] }],
    }];
    const parts = unzipToText(writer.write(doc));
    expect(parts['word/charts/chart1.xml']).toBeDefined();
    expect(parts['word/charts/chart1.xml']).toContain('<c:chartSpace ');
    expect(parts['word/charts/chart1.xml']).toContain('<c:barChart>');
    expect(parts['word/charts/chart1.xml']).toContain('>銷售額<');
    expect(parts['word/charts/chart1.xml']).toContain('>Q1<');
    expect(parts['word/charts/chart1.xml']).toContain('>10<');
    expect(parts['[Content_Types].xml']).toContain('PartName="/word/charts/chart1.xml"');
    expect(parts['[Content_Types].xml']).toContain('drawingml.chart+xml');
    expect(parts['word/_rels/document.xml.rels']).toContain('Id="rIdCh1"');
    expect(parts['word/_rels/document.xml.rels']).toContain('Target="charts/chart1.xml"');
  });

  it('Chart graphicData → <c:chart r:id>（非 pic:pic）', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdCh1', width: 100, height: 100,
        graphic: { kind: 'chart', relId: 'rIdCh1' },
      }] },
    ])]);
    doc.charts = [{ rId: 'rIdCh1', chartType: 'barChart', series: [] }];
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<c:chart ');
    expect(xml).toContain('r:id="rIdCh1"');
    expect(xml).not.toContain('<pic:pic');
  });

  it('Chart 數列 cat/val 對位（含稀疏 null 跳過）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.charts = [{
      rId: 'rId1', chartType: 'lineChart',
      series: [{
        name: 'S',
        categories: ['a', 'b', 'c', 'd'],
        values: [1, null, 3, null],
      }],
    }];
    const xml = unzipToText(writer.write(doc))['word/charts/chart1.xml'];
    expect(xml).toContain('<c:lineChart>');
    expect(xml).toContain('<c:ptCount val="4"/>');
    // null 點不 emit
    expect(xml).toContain('>1<');
    expect(xml).toContain('>3<');
    // 不應為 2 或 4（null 對應位置）
  });

  it('多個 SmartArt + Chart → 各自編號', () => {
    const doc = makeDoc([makeSection([])]);
    doc.smartArts = [
      { rId: 'rIdSA1', texts: ['A'] },
      { rId: 'rIdSA2', texts: ['B'] },
    ];
    doc.charts = [
      { rId: 'rIdCh1', chartType: 'barChart', series: [] },
      { rId: 'rIdCh2', chartType: 'pieChart', series: [] },
    ];
    const parts = unzipToText(writer.write(doc));
    expect(parts['word/diagrams/data1.xml']).toBeDefined();
    expect(parts['word/diagrams/data2.xml']).toBeDefined();
    expect(parts['word/charts/chart1.xml']).toBeDefined();
    expect(parts['word/charts/chart2.xml']).toBeDefined();
  });

  it('無 SmartArt/Chart → 不輸出對應部件、Content_Types/rels 無條目', () => {
    const parts = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(parts['word/diagrams/data1.xml']).toBeUndefined();
    expect(parts['word/charts/chart1.xml']).toBeUndefined();
    expect(parts['[Content_Types].xml']).not.toContain('diagramData');
    expect(parts['[Content_Types].xml']).not.toContain('drawingml.chart+xml');
  });
});

describe('OoxmlWriter — Sprint 196 watermark export', () => {
  const writer = new OoxmlWriter();

  it('文字浮水印 → word/watermarkHeader.xml 含 v:textpath + Content_Types Override + rels', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'text', text: '機密', font: '標楷體', rotation: 315 };
    const parts = unzipToText(writer.write(doc));
    expect(parts['word/watermarkHeader.xml']).toBeDefined();
    expect(parts['word/watermarkHeader.xml']).toContain('<v:shape ');
    expect(parts['word/watermarkHeader.xml']).toContain('type="#_x0000_t136"');
    expect(parts['word/watermarkHeader.xml']).toContain('rotation:315');
    expect(parts['word/watermarkHeader.xml']).toContain('<v:textpath ');
    expect(parts['word/watermarkHeader.xml']).toContain('string="機密"');
    expect(parts['word/watermarkHeader.xml']).toContain('標楷體');
    expect(parts['[Content_Types].xml']).toContain('PartName="/word/watermarkHeader.xml"');
    expect(parts['[Content_Types].xml']).toContain('wordprocessingml.header+xml');
    expect(parts['word/_rels/document.xml.rels']).toContain('Id="rIdWatermarkHdr"');
    expect(parts['word/_rels/document.xml.rels']).toContain('Target="watermarkHeader.xml"');
    expect(parts['word/_rels/document.xml.rels']).toContain('relationships/header');
  });

  it('無 default header 的 section → 注入 watermark rId 為 default headerReference', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'text', text: 'DRAFT' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:headerReference w:type="default" r:id="rIdWatermarkHdr"/>');
  });

  it('已有 default header 的 section → 保留原 default、不覆寫（honest sub-gap）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.sections[0].headerRefs = { default: 'rIdExistingH' };
    doc.watermark = { kind: 'text', text: 'X' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('<w:headerReference w:type="default" r:id="rIdExistingH"/>');
    expect(xml).not.toContain('r:id="rIdWatermarkHdr"');
  });

  it('multi-section：有 default 的不覆寫、無 default 的注入', () => {
    const sec1 = makeSection([]);
    sec1.headerRefs = { default: 'rIdH1' };
    const sec2 = makeSection([]);
    sec2.headerRefs = {};
    const doc = makeDoc([sec1, sec2]);
    doc.watermark = { kind: 'text', text: 'W' };
    const xml = unzipToText(writer.write(doc))['word/document.xml'];
    expect(xml).toContain('r:id="rIdH1"');
    expect(xml).toContain('r:id="rIdWatermarkHdr"');
  });

  it('圖片浮水印 → emit v:imagedata r:id（kind=image）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'image', imageRId: 'rIdImg1' };
    const partXml = unzipToText(writer.write(doc))['word/watermarkHeader.xml'];
    expect(partXml).toContain('<v:imagedata ');
    expect(partXml).toContain('r:id="rIdImg1"');
    expect(partXml).not.toContain('<v:textpath');
  });

  it('文字浮水印 rotation 缺漏 → fallback 315 度（Word 預設對角）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'text', text: 'X' };
    const partXml = unzipToText(writer.write(doc))['word/watermarkHeader.xml'];
    expect(partXml).toContain('rotation:315');
  });

  it('無 watermark → 不輸出 watermarkHeader.xml、Content_Types/rels 無條目、section 無注入', () => {
    const parts = unzipToText(writer.write(makeDoc([makeSection([])])));
    expect(parts['word/watermarkHeader.xml']).toBeUndefined();
    expect(parts['[Content_Types].xml']).not.toContain('watermarkHeader.xml');
    expect(parts['word/_rels/document.xml.rels']).not.toContain('rIdWatermarkHdr');
    expect(parts['word/document.xml']).not.toContain('rIdWatermarkHdr');
  });
});
