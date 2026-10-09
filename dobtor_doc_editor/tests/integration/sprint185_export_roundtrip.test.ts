/**
 * Sprint 185 整合驗證（Phase 6 docx export MVS round-trip）
 *
 * 規畫書 §6 黃金測試：`import(export(doc))` ≅ `doc`。本 MVS 切片只驗證**段落
 * 文字內容**對稱（RunProps / 樣式 / 表格 / Phase 5 子功能等留後續 sprint）。
 *
 * 完整對稱性將隨後續 export sprint 逐步擴充覆蓋。
 */

import { describe, expect, it } from 'vitest';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
} from '../../static/src/core/ooxml/ast/types';

const writer = new OoxmlWriter();
const parser = new OoxmlParser();

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

/** 從 DocumentNode 抽出純文字（按段落、run 順序、段落以 \n 分隔）。 */
function extractText(doc: DocumentNode): string {
  const lines: string[] = [];
  for (const sec of doc.sections) {
    for (const block of sec.body) {
      if (block.type !== 'paragraph') continue;
      const t = block.runs
        .filter((r): r is RunNode => r.type === 'run')
        .map((r) => r.text)
        .join('');
      lines.push(t);
    }
  }
  return lines.join('\n');
}

/** 寫出 → 再讀回 → 回傳 round-trip 後的 DocumentNode。 */
function roundTrip(doc: DocumentNode): DocumentNode {
  const bytes = writer.write(doc);
  const arr = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  return parser.parse(arr);
}

describe('Sprint 185 — Phase 6 export round-trip（純文字段落）', () => {
  it('空文件 → round-trip 不 crash、產出有效 docx', () => {
    const doc = makeDoc([makeSection([])]);
    expect(() => roundTrip(doc)).not.toThrow();
  });

  it('單段落單 run → round-trip 文字保留', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('Hello World')])])]);
    const back = roundTrip(doc);
    expect(extractText(back)).toBe('Hello World');
  });

  it('多段落 → round-trip 順序保留', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('第一段')]),
      makeParagraph([makeRun('第二段')]),
      makeParagraph([makeRun('第三段')]),
    ])]);
    expect(extractText(roundTrip(doc))).toBe('第一段\n第二段\n第三段');
  });

  it('多 run 同段落 → round-trip 拼接保留', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('Hello, '), makeRun('世界'), makeRun('!')]),
    ])]);
    expect(extractText(roundTrip(doc))).toBe('Hello, 世界!');
  });

  it('XML 特殊字元 → round-trip 文字 byte-identical', () => {
    const txt = 'a&b<c>d"e\'f';
    const doc = makeDoc([makeSection([makeParagraph([makeRun(txt)])])]);
    expect(extractText(roundTrip(doc))).toBe(txt);
  });

  it('前後空白 → round-trip 保留（xml:space="preserve"）', () => {
    const doc = makeDoc([makeSection([
      makeParagraph([makeRun('  前後皆有空白  ')]),
    ])]);
    expect(extractText(roundTrip(doc))).toBe('  前後皆有空白  ');
  });

  it('中文 / CJK / 表情符號 → round-trip 文字保留', () => {
    const txt = '繁體中文・日本語・한국어・🎯';
    const doc = makeDoc([makeSection([makeParagraph([makeRun(txt)])])]);
    expect(extractText(roundTrip(doc))).toBe(txt);
  });

  it('Sprint 191：多 section round-trip → 2 個 section、anchor paragraph 拆分還原', () => {
    const doc = makeDoc([
      makeSection([makeParagraph([makeRun('A')])]),
      makeSection([makeParagraph([makeRun('B')])]),
    ]);
    const back = roundTrip(doc);
    expect(back.sections).toHaveLength(2);
    // 兩 section 的段落都在（anchor para 可能變空段、不影響文字內容）
    const text = extractText(back);
    expect(text).toContain('A');
    expect(text).toContain('B');
  });

  it('section page / margins round-trip（pt → twips → pt 量化、A4 + 72pt）', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    const back = roundTrip(doc);
    // 595.3pt → 11906 twips → 595.3pt（× 20 / 20 整數運算可能差 0.05、容忍度）
    expect(back.sections[0].page.width).toBeCloseTo(595.3, 0);
    expect(back.sections[0].page.height).toBeCloseTo(841.9, 0);
    expect(back.sections[0].margins.top).toBeCloseTo(72, 1);
    expect(back.sections[0].margins.left).toBeCloseTo(72, 1);
  });
});

describe('Sprint 186 — Phase 6 export round-trip（RunProps）', () => {
  /** 從 round-trip 後的 doc 取第一段第一個 run 的 props。 */
  function firstRunProps(doc: DocumentNode): RunNode['props'] {
    const sec = doc.sections[0];
    const para = sec.body[0];
    if (para.type !== 'paragraph') throw new Error('expected paragraph');
    const run = para.runs[0];
    if (run.type !== 'run') throw new Error('expected run');
    return run.props;
  }

  function makeRunWithProps(text: string, props: RunNode['props']): RunNode {
    return { type: 'run', text, props };
  }

  it('粗體 / 斜體 / 刪除線 round-trip', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', { bold: true, italic: true, strike: true }),
    ])])]);
    const back = firstRunProps(roundTrip(doc));
    expect(back.bold).toBe(true);
    expect(back.italic).toBe(true);
    expect(back.strike).toBe(true);
  });

  it('字級 fontSize round-trip（half-points 精度）', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', { fontSize: 14 }),
    ])])]);
    expect(firstRunProps(roundTrip(doc)).fontSize).toBe(14);
  });

  it('顏色 hex round-trip（大寫正規化由 parser 處理）', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', { color: 'FF0000' }),
    ])])]);
    const back = firstRunProps(roundTrip(doc));
    expect(back.color?.toUpperCase()).toBe('FF0000');
  });

  it('底線 underline round-trip', () => {
    for (const u of ['single', 'double', 'wave'] as const) {
      const doc = makeDoc([makeSection([makeParagraph([
        makeRunWithProps('x', { underline: u }),
      ])])]);
      expect(firstRunProps(roundTrip(doc)).underline).toBe(u);
    }
  });

  it('上下標 vertAlign round-trip', () => {
    for (const v of ['superscript', 'subscript'] as const) {
      const doc = makeDoc([makeSection([makeParagraph([
        makeRunWithProps('x', { vertAlign: v }),
      ])])]);
      expect(firstRunProps(roundTrip(doc)).vertAlign).toBe(v);
    }
  });

  it('字型 rFonts 四欄位 round-trip', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', {
        fontFamily: 'Arial',
        fontFamilyEastAsia: '微軟正黑體',
        fontFamilyHAnsi: 'Calibri',
        fontFamilyCs: 'Arial',
      }),
    ])])]);
    const back = firstRunProps(roundTrip(doc));
    expect(back.fontFamily).toBe('Arial');
    expect(back.fontFamilyEastAsia).toBe('微軟正黑體');
    expect(back.fontFamilyHAnsi).toBe('Calibri');
    expect(back.fontFamilyCs).toBe('Arial');
  });

  it('高亮 highlight round-trip（具名色）', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', { highlight: 'yellow' }),
    ])])]);
    expect(firstRunProps(roundTrip(doc)).highlight).toBe('yellow');
  });

  it('語言 lang round-trip', () => {
    const doc = makeDoc([makeSection([makeParagraph([
      makeRunWithProps('x', { lang: 'zh-TW' }),
    ])])]);
    expect(firstRunProps(roundTrip(doc)).lang).toBe('zh-TW');
  });

  it('多 props 組合 round-trip', () => {
    const props = {
      bold: true, italic: true, fontSize: 16, color: 'FF0000',
      underline: 'single' as const, fontFamily: 'Arial', vertAlign: 'superscript' as const,
    };
    const doc = makeDoc([makeSection([makeParagraph([makeRunWithProps('x', props)])])]);
    const back = firstRunProps(roundTrip(doc));
    expect(back.bold).toBe(true);
    expect(back.italic).toBe(true);
    expect(back.fontSize).toBe(16);
    expect(back.color?.toUpperCase()).toBe('FF0000');
    expect(back.underline).toBe('single');
    expect(back.fontFamily).toBe('Arial');
    expect(back.vertAlign).toBe('superscript');
  });
});

describe('Sprint 187 — Phase 6 export round-trip（ParagraphProps）', () => {
  function firstParaProps(doc: DocumentNode): ParagraphNode['props'] {
    const block = doc.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    return block.props;
  }
  function firstParaStyleId(doc: DocumentNode): string | undefined {
    const block = doc.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    return block.styleId;
  }
  function paraWith(props: ParagraphNode['props'], styleId?: string): ParagraphNode {
    const p: ParagraphNode = { type: 'paragraph', runs: [makeRun('x')], props };
    if (styleId) p.styleId = styleId;
    return p;
  }

  it('alignment round-trip（left / center / right / justify）', () => {
    for (const a of ['left', 'center', 'right', 'justify'] as const) {
      const doc = makeDoc([makeSection([paraWith({ alignment: a })])]);
      expect(firstParaProps(roundTrip(doc)).alignment).toBe(a);
    }
  });

  it('styleId round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({}, 'Heading1')])]);
    expect(firstParaStyleId(roundTrip(doc))).toBe('Heading1');
  });

  it('numId + ilvl round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({ numId: 5, ilvl: 2 })])]);
    const back = firstParaProps(roundTrip(doc));
    expect(back.numId).toBe(5);
    expect(back.ilvl).toBe(2);
  });

  it('indent 四欄位 round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      indent: { left: 36, right: 24, firstLine: 18, hanging: 12 },
    })])]);
    const back = firstParaProps(roundTrip(doc)).indent;
    expect(back?.left).toBeCloseTo(36, 1);
    expect(back?.right).toBeCloseTo(24, 1);
    expect(back?.firstLine).toBeCloseTo(18, 1);
    expect(back?.hanging).toBeCloseTo(12, 1);
  });

  it('spacing before/after/line auto round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      spacing: { before: 6, after: 12, line: { rule: 'auto', value: 1.5 } },
    })])]);
    const back = firstParaProps(roundTrip(doc)).spacing;
    expect(back?.before).toBeCloseTo(6, 1);
    expect(back?.after).toBeCloseTo(12, 1);
    expect(back?.line?.rule).toBe('auto');
    expect(back?.line?.value).toBeCloseTo(1.5, 2);
  });

  it('spacing line exact round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      spacing: { line: { rule: 'exact', value: 14 } },
    })])]);
    const back = firstParaProps(roundTrip(doc)).spacing;
    expect(back?.line?.rule).toBe('exact');
    expect(back?.line?.value).toBeCloseTo(14, 1);
  });

  it('keepNext / keepLines / pageBreakBefore toggle round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      keepNext: true, keepLines: true, pageBreakBefore: true,
    })])]);
    const back = firstParaProps(roundTrip(doc));
    expect(back.keepNext).toBe(true);
    expect(back.keepLines).toBe(true);
    expect(back.pageBreakBefore).toBe(true);
  });

  it('tabs round-trip（多 tab + leader）', () => {
    const doc = makeDoc([makeSection([paraWith({
      tabs: [
        { pos: 100, align: 'left' },
        { pos: 200, align: 'right', leader: 'dot' },
      ],
    })])]);
    const back = firstParaProps(roundTrip(doc)).tabs;
    expect(back).toHaveLength(2);
    expect(back?.[0].pos).toBeCloseTo(100, 1);
    expect(back?.[0].align).toBe('left');
    expect(back?.[1].pos).toBeCloseTo(200, 1);
    expect(back?.[1].align).toBe('right');
    expect(back?.[1].leader).toBe('dot');
  });

  it('textAlignment round-trip', () => {
    for (const v of ['auto', 'top', 'center', 'baseline', 'bottom'] as const) {
      const doc = makeDoc([makeSection([paraWith({ textAlignment: v })])]);
      expect(firstParaProps(roundTrip(doc)).textAlignment).toBe(v);
    }
  });

  it('多 ParagraphProps 組合 round-trip', () => {
    const props = {
      alignment: 'center' as const,
      indent: { left: 24, firstLine: 12 },
      spacing: { before: 6, after: 6, line: { rule: 'auto' as const, value: 1.0 } },
      keepNext: true,
      numId: 1, ilvl: 0,
    };
    const doc = makeDoc([makeSection([paraWith(props, 'Body')])]);
    const back = roundTrip(doc);
    const props2 = firstParaProps(back);
    expect(firstParaStyleId(back)).toBe('Body');
    expect(props2.alignment).toBe('center');
    expect(props2.indent?.left).toBeCloseTo(24, 1);
    expect(props2.spacing?.before).toBeCloseTo(6, 1);
    expect(props2.keepNext).toBe(true);
    expect(props2.numId).toBe(1);
    expect(props2.ilvl).toBe(0);
  });
});

describe('Sprint 188 — Phase 6 export round-trip（ParagraphProps 進階）', () => {
  function firstParaProps(doc: DocumentNode): ParagraphNode['props'] {
    const block = doc.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    return block.props;
  }
  function paraWith(props: ParagraphNode['props']): ParagraphNode {
    return { type: 'paragraph', runs: [makeRun('x')], props };
  }

  // ── pBdr ──────────────────────────────────────────────────────────────────

  it('borders 全四邊 round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      borders: {
        top:    { style: 'single', width: 0.5, color: '000000' },
        bottom: { style: 'single', width: 0.5, color: '000000' },
        left:   { style: 'double', width: 1, color: 'FF0000' },
        right:  { style: 'double', width: 1, color: 'FF0000' },
      },
    })])]);
    const back = firstParaProps(roundTrip(doc)).borders;
    expect(back?.top?.style).toBe('single');
    expect(back?.top?.width).toBeCloseTo(0.5, 2);
    expect(back?.top?.color?.toUpperCase()).toBe('000000');
    expect(back?.left?.style).toBe('double');
    expect(back?.left?.width).toBeCloseTo(1, 2);
    expect(back?.left?.color?.toUpperCase()).toBe('FF0000');
  });

  it('borders space round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      borders: { bottom: { style: 'single', width: 0.5, color: '000000', space: 4 } },
    })])]);
    expect(firstParaProps(roundTrip(doc)).borders?.bottom?.space).toBeCloseTo(4, 0);
  });

  // ── shd ──────────────────────────────────────────────────────────────────

  it('shading fill/pattern round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      shading: { fill: 'DEEAF6', pattern: 'clear', color: 'auto' },
    })])]);
    const back = firstParaProps(roundTrip(doc)).shading;
    expect(back?.fill?.toUpperCase()).toBe('DEEAF6');
    expect(back?.pattern).toBe('clear');
    expect(back?.color).toBe('auto');
  });

  // ── framePr ──────────────────────────────────────────────────────────────

  it('framePr 完整 round-trip', () => {
    const fp = {
      width: 100, height: 50, hRule: 'exact' as const,
      hSpace: 4, vSpace: 4,
      wrap: 'around' as const,
      hAnchor: 'page' as const, vAnchor: 'margin' as const,
      xAlign: 'center' as const, yAlign: 'top' as const,
      x: 10, y: 20,
    };
    const doc = makeDoc([makeSection([paraWith({ framePr: fp })])]);
    const back = firstParaProps(roundTrip(doc)).framePr;
    expect(back?.width).toBeCloseTo(100, 1);
    expect(back?.height).toBeCloseTo(50, 1);
    expect(back?.hRule).toBe('exact');
    expect(back?.hSpace).toBeCloseTo(4, 1);
    expect(back?.vSpace).toBeCloseTo(4, 1);
    expect(back?.wrap).toBe('around');
    expect(back?.hAnchor).toBe('page');
    expect(back?.vAnchor).toBe('margin');
    expect(back?.xAlign).toBe('center');
    expect(back?.yAlign).toBe('top');
    expect(back?.x).toBeCloseTo(10, 1);
    expect(back?.y).toBeCloseTo(20, 1);
  });

  it('framePr 部分欄位 round-trip（無值欄位不掛 key）', () => {
    const doc = makeDoc([makeSection([paraWith({
      framePr: { wrap: 'around', hAnchor: 'page' },
    })])]);
    const back = firstParaProps(roundTrip(doc)).framePr;
    expect(back?.wrap).toBe('around');
    expect(back?.hAnchor).toBe('page');
    expect(back?.width).toBeUndefined();
    expect(back?.height).toBeUndefined();
  });

  // ── 複合 round-trip ───────────────────────────────────────────────────────

  it('pBdr + shd + framePr 同段落 round-trip', () => {
    const doc = makeDoc([makeSection([paraWith({
      framePr: { wrap: 'around', hAnchor: 'page' },
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
      shading: { fill: 'FFFF00' },
    })])]);
    const back = firstParaProps(roundTrip(doc));
    expect(back.framePr?.wrap).toBe('around');
    expect(back.borders?.top?.style).toBe('single');
    expect(back.shading?.fill?.toUpperCase()).toBe('FFFF00');
  });
});

describe('Sprint 189 — Phase 6 export round-trip（Styles.xml）', () => {
  function roundTripStyles(styles: DocumentNode['styles']): DocumentNode['styles'] {
    const doc = makeDoc([makeSection([])]);
    doc.styles = styles;
    return roundTrip(doc).styles;
  }

  it('空 styles map → round-trip 仍空', () => {
    const back = roundTripStyles(new Map());
    expect(back.size).toBe(0);
  });

  it('單一空 entry → round-trip 保留 styleId（Map 大小 1）', () => {
    const back = roundTripStyles(new Map([['Heading1', {}]]));
    expect(back.has('Heading1')).toBe(true);
  });

  it('entry pProps round-trip', () => {
    const back = roundTripStyles(new Map([
      ['Body', { pProps: { alignment: 'center', keepNext: true } }],
    ]));
    expect(back.get('Body')?.pProps?.alignment).toBe('center');
    expect(back.get('Body')?.pProps?.keepNext).toBe(true);
  });

  it('entry rProps round-trip', () => {
    const back = roundTripStyles(new Map([
      ['Emphasis', { rProps: { bold: true, italic: true, fontSize: 14 } }],
    ]));
    expect(back.get('Emphasis')?.rProps?.bold).toBe(true);
    expect(back.get('Emphasis')?.rProps?.italic).toBe(true);
    expect(back.get('Emphasis')?.rProps?.fontSize).toBe(14);
  });

  it('entry pProps + rProps 同時 round-trip', () => {
    const back = roundTripStyles(new Map([
      ['Title', { pProps: { alignment: 'center' }, rProps: { bold: true, fontSize: 24 } }],
    ]));
    const entry = back.get('Title');
    expect(entry?.pProps?.alignment).toBe('center');
    expect(entry?.rProps?.bold).toBe(true);
    expect(entry?.rProps?.fontSize).toBe(24);
  });

  it('多 entry round-trip（Map 大小 + 各鍵內容）', () => {
    const back = roundTripStyles(new Map([
      ['A', { rProps: { bold: true } }],
      ['B', { rProps: { italic: true } }],
      ['C', { pProps: { alignment: 'right' } }],
    ]));
    expect(back.size).toBe(3);
    expect(back.get('A')?.rProps?.bold).toBe(true);
    expect(back.get('B')?.rProps?.italic).toBe(true);
    expect(back.get('C')?.pProps?.alignment).toBe('right');
  });

  it('paragraph 引用 styleId → 連同 styles 一起 round-trip', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [makeRun('Title')], props: {}, styleId: 'Heading1' },
    ])]);
    doc.styles = new Map([['Heading1', { rProps: { bold: true, fontSize: 18 } }]]);
    const back = roundTrip(doc);
    const block = back.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    expect(block.styleId).toBe('Heading1');
    expect(back.styles.get('Heading1')?.rProps?.bold).toBe(true);
    expect(back.styles.get('Heading1')?.rProps?.fontSize).toBe(18);
  });
});

describe('Sprint 190 — Phase 6 export round-trip（表格）', () => {
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

  function firstTable(doc: DocumentNode): TableNode {
    const block = doc.sections[0].body[0];
    if (block.type !== 'table') throw new Error('expected table');
    return block;
  }

  it('空表格 round-trip', () => {
    const doc = makeDoc([makeSection([makeTable([], [])])]);
    const back = roundTrip(doc);
    const t = back.sections[0].body[0];
    expect(t.type).toBe('table');
  });

  it('grid 寬度 round-trip', () => {
    const doc = makeDoc([makeSection([makeTable([100, 200, 300], [])])]);
    const t = firstTable(roundTrip(doc));
    expect(t.grid).toHaveLength(3);
    expect(t.grid[0]).toBeCloseTo(100, 1);
    expect(t.grid[1]).toBeCloseTo(200, 1);
    expect(t.grid[2]).toBeCloseTo(300, 1);
  });

  it('單列單格 + cell 內文字 round-trip', () => {
    const c = makeCell([{ type: 'paragraph', runs: [makeRun('Hello')], props: {} }]);
    const doc = makeDoc([makeSection([makeTable([100], [makeRow([c])])])]);
    const t = firstTable(roundTrip(doc));
    const cell = t.rows[0].cells[0];
    const para = cell.content[0];
    if (para.type !== 'paragraph') throw new Error('expected paragraph');
    const run = para.runs[0];
    expect(run.type === 'run' && run.text).toBe('Hello');
  });

  it('tblPr：styleId / alignment / indent round-trip', () => {
    const doc = makeDoc([makeSection([
      makeTable([100], [], { alignment: 'center', indent: 36 }, 'TableGrid'),
    ])]);
    const t = firstTable(roundTrip(doc));
    expect(t.styleId).toBe('TableGrid');
    expect(t.props.alignment).toBe('center');
    expect(t.props.indent).toBeCloseTo(36, 1);
  });

  it('tblW dxa round-trip', () => {
    const doc = makeDoc([makeSection([
      makeTable([], [], { width: 500, widthType: 'dxa' }),
    ])]);
    const t = firstTable(roundTrip(doc));
    expect(t.props.widthType).toBe('dxa');
    expect(t.props.width).toBeCloseTo(500, 1);
  });

  it('tblBorders + tblCellMar round-trip', () => {
    const doc = makeDoc([makeSection([makeTable([100], [], {
      borders: { top: { style: 'single', width: 0.5, color: '000000' } },
      cellMargins: { top: 4, left: 8 },
    })])]);
    const t = firstTable(roundTrip(doc));
    expect(t.props.borders?.top?.style).toBe('single');
    expect(t.props.cellMargins?.top).toBeCloseTo(4, 1);
    expect(t.props.cellMargins?.left).toBeCloseTo(8, 1);
  });

  it('trPr：trHeight / heightRule / isHeader / cantSplit round-trip', () => {
    const c = makeCell([{ type: 'paragraph', runs: [], props: {} }]);
    const row = makeRow([c], { height: 20, heightRule: 'exact', isHeader: true, cantSplit: true });
    const doc = makeDoc([makeSection([makeTable([100], [row])])]);
    const t = firstTable(roundTrip(doc));
    const r = t.rows[0];
    expect(r.props.height).toBeCloseTo(20, 1);
    expect(r.props.heightRule).toBe('exact');
    expect(r.props.isHeader).toBe(true);
    expect(r.props.cantSplit).toBe(true);
  });

  it('tcPr：width / vAlign / textDirection round-trip', () => {
    const c = makeCell([{ type: 'paragraph', runs: [], props: {} }], {
      width: 80, vAlign: 'center', textDirection: 'tbRlV',
    });
    const doc = makeDoc([makeSection([makeTable([80], [makeRow([c])])])]);
    const t = firstTable(roundTrip(doc));
    const cell = t.rows[0].cells[0];
    expect(cell.props.width).toBeCloseTo(80, 1);
    expect(cell.props.vAlign).toBe('center');
    expect(cell.props.textDirection).toBe('tbRlV');
  });

  it('tcPr：tcBorders + shading round-trip', () => {
    const c = makeCell([{ type: 'paragraph', runs: [], props: {} }], {
      borders: { top: { style: 'single', width: 0.5, color: 'FF0000' } },
      shading: { fill: 'DEEAF6' },
    });
    const doc = makeDoc([makeSection([makeTable([100], [makeRow([c])])])]);
    const t = firstTable(roundTrip(doc));
    const cell = t.rows[0].cells[0];
    expect(cell.props.borders?.top?.style).toBe('single');
    expect(cell.props.borders?.top?.color?.toUpperCase()).toBe('FF0000');
    expect(cell.props.shading?.fill?.toUpperCase()).toBe('DEEAF6');
  });

  it('gridSpan round-trip', () => {
    const c = makeCell([{ type: 'paragraph', runs: [], props: {} }], {}, { gridSpan: 3 });
    const doc = makeDoc([makeSection([makeTable([50, 50, 50], [makeRow([c])])])]);
    const t = firstTable(roundTrip(doc));
    expect(t.rows[0].cells[0].gridSpan).toBe(3);
  });

  it('2×2 表格 round-trip（4 cells、文字內容）', () => {
    const c = (text: string) => makeCell([{ type: 'paragraph', runs: [makeRun(text)], props: {} }]);
    const doc = makeDoc([makeSection([makeTable([100, 100], [
      makeRow([c('A'), c('B')]),
      makeRow([c('C'), c('D')]),
    ])])]);
    const t = firstTable(roundTrip(doc));
    expect(t.rows).toHaveLength(2);
    expect(t.rows[0].cells).toHaveLength(2);
    const getText = (cell: CellNode) => {
      const p = cell.content[0];
      if (p.type !== 'paragraph') return '';
      const r = p.runs[0];
      return r.type === 'run' ? r.text : '';
    };
    expect(getText(t.rows[0].cells[0])).toBe('A');
    expect(getText(t.rows[0].cells[1])).toBe('B');
    expect(getText(t.rows[1].cells[0])).toBe('C');
    expect(getText(t.rows[1].cells[1])).toBe('D');
  });

  it('巢狀表格 round-trip（cell 內含 inner table、含文字）', () => {
    const inner = makeTable([50], [makeRow([
      makeCell([{ type: 'paragraph', runs: [makeRun('inner')], props: {} }]),
    ])]);
    const outerCell = makeCell([inner]);
    const doc = makeDoc([makeSection([makeTable([100], [makeRow([outerCell])])])]);
    const t = firstTable(roundTrip(doc));
    const innerBlock = t.rows[0].cells[0].content[0];
    expect(innerBlock.type).toBe('table');
    if (innerBlock.type === 'table') {
      const innerCell = innerBlock.rows[0].cells[0];
      const innerPara = innerCell.content[0];
      expect(innerPara.type === 'paragraph' && (innerPara.runs[0].type === 'run' && innerPara.runs[0].text)).toBe('inner');
    }
  });
});

describe('Sprint 191 — Phase 6 export round-trip（多 section + numbering）', () => {
  // ── 多 section round-trip ────────────────────────────────────────────────

  it('3 個 section round-trip → 3 個 section、各自段落保留', () => {
    const doc = makeDoc([
      makeSection([makeParagraph([makeRun('一')])]),
      makeSection([makeParagraph([makeRun('二')])]),
      makeSection([makeParagraph([makeRun('三')])]),
    ]);
    const back = roundTrip(doc);
    expect(back.sections).toHaveLength(3);
    expect(extractText(back)).toContain('一');
    expect(extractText(back)).toContain('二');
    expect(extractText(back)).toContain('三');
  });

  it('多 section 各自 page 屬性 round-trip', () => {
    const portrait = makeSection([makeParagraph([makeRun('P')])]);
    const landscape = {
      ...makeSection([makeParagraph([makeRun('L')])]),
      page: { width: 841.9, height: 595.3, orientation: 'landscape' as const },
    };
    const doc = makeDoc([portrait, landscape]);
    const back = roundTrip(doc);
    expect(back.sections).toHaveLength(2);
    expect(back.sections[0].page.width).toBeCloseTo(595.3, 0);
    expect(back.sections[1].page.width).toBeCloseTo(841.9, 0);
  });

  // ── numbering round-trip ─────────────────────────────────────────────────

  it('空 numbering map round-trip', () => {
    const doc = makeDoc([makeSection([])]);
    expect(roundTrip(doc).numbering.size).toBe(0);
  });

  it('單一 numbering entry round-trip（含 level start/numFmt/lvlText）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 5,
      levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }],
    }]]);
    const back = roundTrip(doc).numbering;
    expect(back.size).toBe(1);
    const entry = back.get(1);
    expect(entry).toBeDefined();
    expect(entry?.levels).toHaveLength(1);
    expect(entry?.levels[0].ilvl).toBe(0);
    expect(entry?.levels[0].numFmt).toBe('decimal');
    expect(entry?.levels[0].text).toBe('%1.');
    expect(entry?.levels[0].start).toBe(1);
    // abstractNumId 用 numId（lossy 設計、其他欄位保留）
    expect(entry?.abstractNumId).toBe(1);
  });

  it('多 levels round-trip（ilvl 0/1/2、不同 numFmt）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 0,
      levels: [
        { ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 },
        { ilvl: 1, numFmt: 'lowerLetter', text: '%2)', start: 2 },
        { ilvl: 2, numFmt: 'lowerRoman', text: '%3.', start: 3 },
      ],
    }]]);
    const entry = roundTrip(doc).numbering.get(1)!;
    expect(entry.levels).toHaveLength(3);
    expect(entry.levels[1].numFmt).toBe('lowerLetter');
    expect(entry.levels[1].start).toBe(2);
    expect(entry.levels[2].numFmt).toBe('lowerRoman');
  });

  it('level lvlRestart / isLegal round-trip', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 0,
      levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1, lvlRestart: 0, isLegal: true }],
    }]]);
    const lvl = roundTrip(doc).numbering.get(1)!.levels[0];
    expect(lvl.lvlRestart).toBe(0);
    expect(lvl.isLegal).toBe(true);
  });

  it('level indent round-trip（parser 分離欄位）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 0,
      levels: [{
        ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1,
        indent: { left: 36, hanging: 18 },
      }],
    }]]);
    const lvl = roundTrip(doc).numbering.get(1)!.levels[0];
    expect(lvl.indent?.left).toBeCloseTo(36, 1);
    expect(lvl.indent?.hanging).toBeCloseTo(18, 1);
  });

  it('level runProps round-trip', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 0,
      levels: [{
        ilvl: 0, numFmt: 'bullet', text: '•', start: 1,
        runProps: { bold: true, fontFamily: 'Symbol' },
      }],
    }]]);
    const lvl = roundTrip(doc).numbering.get(1)!.levels[0];
    expect(lvl.runProps?.bold).toBe(true);
    expect(lvl.runProps?.fontFamily).toBe('Symbol');
  });

  it('多 numId entry round-trip（Map 各 key 獨立）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.numbering = new Map([
      [1, { abstractNumId: 0, levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }] }],
      [2, { abstractNumId: 1, levels: [{ ilvl: 0, numFmt: 'bullet', text: '•', start: 1 }] }],
    ]);
    const back = roundTrip(doc).numbering;
    expect(back.size).toBe(2);
    expect(back.get(1)?.levels[0].numFmt).toBe('decimal');
    expect(back.get(2)?.levels[0].numFmt).toBe('bullet');
  });

  it('paragraph 引用 numId+ilvl + 對應 numbering round-trip 端到端', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [makeRun('item')],
      props: { numId: 1, ilvl: 0 },
    };
    const doc = makeDoc([makeSection([para])]);
    doc.numbering = new Map([[1, {
      abstractNumId: 0,
      levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }],
    }]]);
    const back = roundTrip(doc);
    const backPara = back.sections[0].body[0];
    if (backPara.type !== 'paragraph') throw new Error('expected paragraph');
    expect(backPara.props.numId).toBe(1);
    expect(backPara.props.ilvl).toBe(0);
    expect(back.numbering.get(1)?.levels[0].text).toBe('%1.');
  });
});

describe('Sprint 192 — Phase 6 export round-trip（圖片 / media）', () => {
  const PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=';
  const PNG_DATA_URL = `data:image/png;base64,${PNG_B64}`;

  function firstParagraph(doc: DocumentNode): ParagraphNode {
    const block = doc.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    return block;
  }

  it('單張內嵌圖片 round-trip → 段落中 inlineImage 還原（width/height/rId）', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [
        makeRun('前'),
        { type: 'inlineImage', rId: 'rIdImg1', width: 100, height: 50 },
        makeRun('後'),
      ], props: {} },
    ])]);
    doc.media = new Map([['rIdImg1', PNG_DATA_URL]]);
    const back = roundTrip(doc);
    const para = firstParagraph(back);
    const imgNode = para.runs.find((r) => r.type === 'inlineImage');
    expect(imgNode).toBeDefined();
    if (imgNode && imgNode.type === 'inlineImage') {
      expect(imgNode.rId).toBe('rIdImg1');
      expect(imgNode.width).toBeCloseTo(100, 0);
      expect(imgNode.height).toBeCloseTo(50, 0);
    }
    // media map 保留該 rId
    expect(back.media.has('rIdImg1')).toBe(true);
  });

  it('圖片 bytes 在 round-trip 後保留（PNG 簽名）', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [
        { type: 'inlineImage', rId: 'rIdImg1', width: 50, height: 50 },
      ], props: {} },
    ])]);
    doc.media = new Map([['rIdImg1', PNG_DATA_URL]]);
    const back = roundTrip(doc);
    const dataUrl = back.media.get('rIdImg1');
    expect(dataUrl).toBeDefined();
    expect(dataUrl).toMatch(/^data:image\/png;base64,/);
    // base64 部分相同
    expect(dataUrl).toContain(PNG_B64);
  });

  it('altText round-trip', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [
        { type: 'inlineImage', rId: 'rIdImg1', width: 50, height: 50, altText: '監造照片' },
      ], props: {} },
    ])]);
    doc.media = new Map([['rIdImg1', PNG_DATA_URL]]);
    const back = roundTrip(doc);
    const img = firstParagraph(back).runs.find((r) => r.type === 'inlineImage');
    if (img && img.type === 'inlineImage') {
      expect(img.altText).toBe('監造照片');
    }
  });

  it('多張圖片 round-trip（rId 各自還原）', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [
        { type: 'inlineImage', rId: 'rIdA', width: 30, height: 30 },
        { type: 'inlineImage', rId: 'rIdB', width: 40, height: 40 },
        { type: 'inlineImage', rId: 'rIdC', width: 50, height: 50 },
      ], props: {} },
    ])]);
    doc.media = new Map([
      ['rIdA', PNG_DATA_URL],
      ['rIdB', PNG_DATA_URL],
      ['rIdC', PNG_DATA_URL],
    ]);
    const back = roundTrip(doc);
    const para = firstParagraph(back);
    const images = para.runs.filter((r) => r.type === 'inlineImage');
    expect(images).toHaveLength(3);
    expect(images.map((i) => i.type === 'inlineImage' && i.rId).sort())
      .toEqual(['rIdA', 'rIdB', 'rIdC']);
    expect(back.media.size).toBe(3);
  });

  it('FloatImageNode 降級為 inline 後 round-trip → 還原為 inlineImage', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', runs: [{
        type: 'floatImage', rId: 'rIdF', width: 80, height: 60,
        posH: { relativeFrom: 'column' },
        posV: { relativeFrom: 'paragraph' },
        wrapType: 'square',
      }], props: {} },
    ])]);
    doc.media = new Map([['rIdF', PNG_DATA_URL]]);
    const back = roundTrip(doc);
    const img = firstParagraph(back).runs.find((r) =>
      r.type === 'inlineImage' || r.type === 'floatImage',
    );
    // 降級為 inline
    expect(img?.type).toBe('inlineImage');
    if (img && img.type === 'inlineImage') {
      expect(img.rId).toBe('rIdF');
      expect(img.width).toBeCloseTo(80, 0);
    }
  });
});

describe('Sprint 193 — Phase 6 export round-trip（頁首頁尾）', () => {
  function makeHF(content: BlockNode[]): { rId: string; content: BlockNode[] } {
    return { rId: '', content };
  }

  it('單一 header round-trip → doc.headers 保留', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('body')])])]);
    doc.headers = new Map([['rIdH1', makeHF([makeParagraph([makeRun('頁首')])])]]);
    doc.sections[0].headerRefs = { default: 'rIdH1' };
    const back = roundTrip(doc);
    expect(back.headers.size).toBe(1);
    const hKey = Array.from(back.headers.keys())[0];
    const hf = back.headers.get(hKey)!;
    const para = hf.content[0];
    expect(para.type).toBe('paragraph');
    if (para.type === 'paragraph') {
      const run = para.runs[0];
      expect(run.type === 'run' && run.text).toBe('頁首');
    }
  });

  it('單一 footer round-trip → doc.footers 保留', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('body')])])]);
    doc.footers = new Map([['rIdF1', makeHF([makeParagraph([makeRun('頁尾')])])]]);
    doc.sections[0].footerRefs = { default: 'rIdF1' };
    const back = roundTrip(doc);
    expect(back.footers.size).toBe(1);
    const fKey = Array.from(back.footers.keys())[0];
    const hf = back.footers.get(fKey)!;
    const para = hf.content[0];
    if (para.type === 'paragraph') {
      const run = para.runs[0];
      expect(run.type === 'run' && run.text).toBe('頁尾');
    }
  });

  it('headerRefs default round-trip → section 引用保留', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('body')])])]);
    doc.headers = new Map([['rIdH1', makeHF([makeParagraph([makeRun('h')])])]]);
    doc.sections[0].headerRefs = { default: 'rIdH1' };
    const back = roundTrip(doc);
    expect(back.sections[0].headerRefs.default).toBeDefined();
  });

  it('multi-type refs round-trip（default + first）', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    doc.headers = new Map([
      ['rIdHd', makeHF([makeParagraph([makeRun('預設頁首')])])],
      ['rIdHf', makeHF([makeParagraph([makeRun('首頁頁首')])])],
    ]);
    doc.sections[0].headerRefs = { default: 'rIdHd', first: 'rIdHf' };
    const back = roundTrip(doc);
    expect(back.headers.size).toBe(2);
    expect(back.sections[0].headerRefs.default).toBeDefined();
    expect(back.sections[0].headerRefs.first).toBeDefined();
  });

  it('titlePage round-trip', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('x')])])]);
    doc.sections[0].titlePage = true;
    const back = roundTrip(doc);
    expect(back.sections[0].titlePage).toBe(true);
  });

  it('header + footer 同時 round-trip', () => {
    const doc = makeDoc([makeSection([makeParagraph([makeRun('body')])])]);
    doc.headers = new Map([['rIdH', makeHF([makeParagraph([makeRun('H')])])]]);
    doc.footers = new Map([['rIdF', makeHF([makeParagraph([makeRun('F')])])]]);
    doc.sections[0].headerRefs = { default: 'rIdH' };
    doc.sections[0].footerRefs = { default: 'rIdF' };
    const back = roundTrip(doc);
    expect(back.headers.size).toBe(1);
    expect(back.footers.size).toBe(1);
  });
});

describe('Sprint 194 — Phase 6 export round-trip（Phase 5 子功能）', () => {
  function firstParagraph(doc: DocumentNode): ParagraphNode {
    const block = doc.sections[0].body[0];
    if (block.type !== 'paragraph') throw new Error('expected paragraph');
    return block;
  }

  // ── OMML round-trip ───────────────────────────────────────────────────

  it('OMML 行內公式 round-trip → para.math 保留', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [makeRun('x')],
      props: {},
      math: [{
        display: false,
        omml: [{ tag: 'r', children: [{ tag: 't', text: 'x+1' }] }],
      }],
    };
    const doc = makeDoc([makeSection([para])]);
    const back = firstParagraph(roundTrip(doc));
    expect(back.math).toBeDefined();
    expect(back.math).toHaveLength(1);
    expect(back.math![0].display).toBe(false);
    expect(back.math![0].omml[0].tag).toBe('r');
  });

  it('OMML display 公式 round-trip → display=true 保留', () => {
    const para: ParagraphNode = {
      type: 'paragraph', runs: [], props: {},
      math: [{
        display: true,
        omml: [{ tag: 'r', children: [{ tag: 't', text: 'y' }] }],
      }],
    };
    const doc = makeDoc([makeSection([para])]);
    const back = firstParagraph(roundTrip(doc));
    expect(back.math![0].display).toBe(true);
  });

  it('OMML 分數結構 round-trip', () => {
    const para: ParagraphNode = {
      type: 'paragraph', runs: [], props: {},
      math: [{
        display: false,
        omml: [{
          tag: 'f',
          children: [
            { tag: 'num', children: [{ tag: 'r', children: [{ tag: 't', text: 'a' }] }] },
            { tag: 'den', children: [{ tag: 'r', children: [{ tag: 't', text: 'b' }] }] },
          ],
        }],
      }],
    };
    const doc = makeDoc([makeSection([para])]);
    const back = firstParagraph(roundTrip(doc));
    const f = back.math![0].omml[0];
    expect(f.tag).toBe('f');
    expect(f.children?.map((c) => c.tag)).toEqual(['num', 'den']);
  });

  // ── 追蹤修訂 round-trip ───────────────────────────────────────────────

  it('追蹤修訂 ins round-trip → run.revision 保留', () => {
    const para: ParagraphNode = {
      type: 'paragraph', props: {},
      runs: [{
        type: 'run', text: '插入', props: {},
        revision: { type: 'ins', id: 5, author: 'Alice', date: '2024-01-01T00:00:00Z' },
      }],
    };
    const doc = makeDoc([makeSection([para])]);
    const back = firstParagraph(roundTrip(doc));
    const run = back.runs.find((r) => r.type === 'run');
    if (run && run.type === 'run') {
      expect(run.revision?.type).toBe('ins');
      expect(run.revision?.author).toBe('Alice');
      expect(run.revision?.date).toBe('2024-01-01T00:00:00Z');
      expect(run.text).toBe('插入');
    }
  });

  it('追蹤修訂 del round-trip → revision.type=del + 文字保留', () => {
    const para: ParagraphNode = {
      type: 'paragraph', props: {},
      runs: [{
        type: 'run', text: '刪除', props: {},
        revision: { type: 'del', id: 7, author: 'Bob' },
      }],
    };
    const doc = makeDoc([makeSection([para])]);
    const back = firstParagraph(roundTrip(doc));
    const run = back.runs.find((r) => r.type === 'run');
    if (run && run.type === 'run') {
      expect(run.revision?.type).toBe('del');
      expect(run.text).toBe('刪除');
    }
  });

  // ── 註解錨點 + comments.xml round-trip ──────────────────────────────

  it('comments + commentRefs 端到端 round-trip', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      runs: [makeRun('被註解')],
      props: {},
      commentRefs: [0],
    };
    const doc = makeDoc([makeSection([para])]);
    doc.comments = new Map([[0, {
      id: 0, author: 'Alice',
      content: [{ type: 'paragraph', props: {}, runs: [makeRun('註解內容')] }],
    }]]);
    const back = roundTrip(doc);
    // commentRefs 在段落
    const backPara = firstParagraph(back);
    expect(backPara.commentRefs).toContain(0);
    // comments.xml 保留
    expect(back.comments.has(0)).toBe(true);
    const cmt = back.comments.get(0)!;
    expect(cmt.author).toBe('Alice');
  });

  // ── background round-trip ───────────────────────────────────────────

  it('background round-trip → 顏色保留', () => {
    const doc = makeDoc([makeSection([])]);
    doc.background = { color: 'FFFF00' };
    const back = roundTrip(doc);
    expect(back.background?.color?.toUpperCase()).toBe('FFFF00');
  });
});

describe('Sprint 195 — Phase 6 export round-trip（SmartArt + Chart）', () => {
  it('SmartArt round-trip → doc.smartArts 文字 + layoutType 保留', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdSA1', width: 200, height: 100,
        graphic: { kind: 'diagram', relId: 'rIdSA1' },
      }] },
    ])]);
    doc.smartArts = [{
      rId: 'rIdSA1',
      layoutType: 'urn:test:circleList',
      texts: ['前置作業', '施工檢核', '驗收交付'],
    }];
    const back = roundTrip(doc);
    expect(back.smartArts).toBeDefined();
    expect(back.smartArts).toHaveLength(1);
    const sa = back.smartArts![0];
    expect(sa.texts).toContain('前置作業');
    expect(sa.texts).toContain('施工檢核');
    expect(sa.texts).toContain('驗收交付');
    expect(sa.layoutType).toBe('urn:test:circleList');
  });

  it('Chart round-trip → doc.charts 型別+series 保留', () => {
    const doc = makeDoc([makeSection([
      { type: 'paragraph', props: {}, runs: [{
        type: 'inlineImage', rId: 'rIdCh1', width: 200, height: 150,
        graphic: { kind: 'chart', relId: 'rIdCh1' },
      }] },
    ])]);
    doc.charts = [{
      rId: 'rIdCh1', chartType: 'barChart', title: '進度統計',
      series: [{ name: '完成', categories: ['Q1', 'Q2'], values: [10, 20] }],
    }];
    const back = roundTrip(doc);
    expect(back.charts).toBeDefined();
    expect(back.charts).toHaveLength(1);
    const ch = back.charts![0];
    expect(ch.chartType).toBe('barChart');
    expect(ch.title).toBe('進度統計');
    expect(ch.series).toHaveLength(1);
    expect(ch.series[0].name).toBe('完成');
    expect(ch.series[0].categories).toEqual(['Q1', 'Q2']);
    expect(ch.series[0].values).toEqual([10, 20]);
  });

  it('Chart 多 series round-trip', () => {
    const doc = makeDoc([makeSection([])]);
    doc.charts = [{
      rId: 'rId1', chartType: 'lineChart',
      series: [
        { name: 'A', categories: ['x'], values: [1] },
        { name: 'B', categories: ['x'], values: [2] },
        { name: 'C', categories: ['x'], values: [3] },
      ],
    }];
    const back = roundTrip(doc);
    expect(back.charts![0].series).toHaveLength(3);
    expect(back.charts![0].series.map((s) => s.name)).toEqual(['A', 'B', 'C']);
  });

  it('Chart null 值（稀疏）round-trip', () => {
    const doc = makeDoc([makeSection([])]);
    doc.charts = [{
      rId: 'rId1', chartType: 'barChart',
      series: [{
        name: 'X',
        categories: ['a', 'b', 'c', 'd'],
        values: [1, null, 3, null],
      }],
    }];
    const back = roundTrip(doc);
    const vals = back.charts![0].series[0].values;
    expect(vals[0]).toBe(1);
    expect(vals[1]).toBeNull();
    expect(vals[2]).toBe(3);
    expect(vals[3]).toBeNull();
  });
});

describe('Sprint 196 — Phase 6 export round-trip（watermark）', () => {
  it('文字浮水印 round-trip → kind/text/font/rotation 全保留', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'text', text: '機密', font: '標楷體', rotation: 315 };
    const back = roundTrip(doc);
    expect(back.watermark).toBeDefined();
    expect(back.watermark!.kind).toBe('text');
    expect(back.watermark!.text).toBe('機密');
    expect(back.watermark!.font).toBe('標楷體');
    expect(back.watermark!.rotation).toBe(315);
  });

  it('文字浮水印 round-trip → 不同 text 內容（DRAFT）', () => {
    const doc = makeDoc([makeSection([])]);
    doc.watermark = { kind: 'text', text: 'DRAFT' };
    const back = roundTrip(doc);
    expect(back.watermark!.kind).toBe('text');
    expect(back.watermark!.text).toBe('DRAFT');
  });

  it('無 watermark round-trip → back.watermark undefined（紀律 #21）', () => {
    const doc = makeDoc([makeSection([])]);
    const back = roundTrip(doc);
    expect(back.watermark).toBeUndefined();
  });
});
