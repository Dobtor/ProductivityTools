/**
 * Paginator — 分頁引擎測試
 */

import { describe, expect, it } from 'vitest';
import { paginate, layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  TableNode,
  RowNode,
  CellNode,
  RunNode,
} from '../../../static/src/core/ooxml/ast/types';

const A4_PORTRAIT = {
  width: 595,
  height: 842,
  orientation: 'portrait' as const,
};

const STD_MARGINS = {
  top: 72, bottom: 72, left: 72, right: 72,
  header: 36, footer: 36,
};

function makeSection(body: SectionNode['body'] = []): SectionNode {
  return {
    type: 'section',
    page: A4_PORTRAIT,
    margins: STD_MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function paraNode(text: string, fontSize = 12, props: ParagraphNode['props'] = {}): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props, runs: [run] };
}

function tableNode(rows: number, cols: number): TableNode {
  const row: RowNode = {
    type: 'row',
    cells: Array.from({ length: cols }, (_, i): CellNode => ({
      type: 'cell',
      gridCol: i,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraNode('x')],
      props: {},
    })),
    props: { isHeader: false, cantSplit: false },
  };
  return {
    type: 'table',
    grid: Array.from({ length: cols }, () => 50),
    rows: Array.from({ length: rows }, () => row),
    props: {},
  };
}

describe('Paginator — 單頁基本', () => {
  it('空 section → 1 頁無 entry', () => {
    const r = paginate(makeSection([]), 0, 1);
    expect(r.pages.length).toBe(1);
    expect(r.pages[0].entries.length).toBe(0);
    expect(r.pages[0].pageNumber).toBe(1);
    expect(r.nextPageNumber).toBe(2);
  });

  it('短段落塞得進一頁 → 1 頁', () => {
    const r = paginate(makeSection([paraNode('hello world')]), 0, 1);
    expect(r.pages.length).toBe(1);
    const linesOnPage = r.pages[0].entries.filter((e) => e.kind === 'line');
    expect(linesOnPage.length).toBe(1);
  });

  it('輸出 page 尺寸與 margins 正確帶入', () => {
    const r = paginate(makeSection([paraNode('x')]), 0, 1);
    expect(r.pages[0].width).toBe(595);
    expect(r.pages[0].height).toBe(842);
    expect(r.pages[0].margins.top).toBe(72);
  });
});

describe('Paginator — 多頁', () => {
  it('100 個短段落 → 多頁', () => {
    const paras = Array.from({ length: 100 }, (_, i) => paraNode(`段${i}`));
    const r = paginate(makeSection(paras), 0, 1);
    expect(r.pages.length).toBeGreaterThan(1);
    // 頁碼遞增
    for (let i = 0; i < r.pages.length; i++) {
      expect(r.pages[i].pageNumber).toBe(i + 1);
    }
  });

  it('pageBreakBefore 強制換頁', () => {
    const paras: ParagraphNode[] = [
      paraNode('first'),
      paraNode('second', 12, { pageBreakBefore: true }),
    ];
    const r = paginate(makeSection(paras), 0, 1);
    expect(r.pages.length).toBe(2);
  });
});

describe('Paginator — Sprint 3 表格 cell-level layout', () => {
  it('小表格 → 一頁、kind="table"（不再是 placeholder）', () => {
    const r = paginate(makeSection([tableNode(3, 4)]), 0, 1);
    expect(r.pages.length).toBe(1);
    const tEntries = r.pages[0].entries.filter((e) => e.kind === 'table');
    expect(tEntries.length).toBe(1);
    if (tEntries[0].kind === 'table') {
      expect(tEntries[0].rows.length).toBe(3);
      expect(tEntries[0].grid.length).toBe(4);
      expect(tEntries[0].isContinuation).toBe(false);
      expect(tEntries[0].hasMore).toBe(false);
    }
  });

  it('超大表格跨頁：第一段 hasMore=true、後續 isContinuation=true', () => {
    // 50 行 × ~14pt → ~700pt，會超過 contentHeight (698pt) 觸發跨頁
    const r = paginate(makeSection([tableNode(50, 4)]), 0, 1);
    expect(r.pages.length).toBeGreaterThan(1);
    // 收集所有 table entry
    const allTableEntries: Array<{ isContinuation: boolean; hasMore: boolean }> = [];
    for (const p of r.pages) {
      for (const e of p.entries) {
        if (e.kind === 'table') {
          allTableEntries.push({ isContinuation: e.isContinuation, hasMore: e.hasMore });
        }
      }
    }
    expect(allTableEntries.length).toBeGreaterThan(1);
    expect(allTableEntries[0].isContinuation).toBe(false);
    expect(allTableEntries[0].hasMore).toBe(true);
    expect(allTableEntries[allTableEntries.length - 1].hasMore).toBe(false);
  });
});

describe('Paginator — section 串接', () => {
  it('layoutDocument 對 2 個 section 累計頁碼', () => {
    const s1 = makeSection([paraNode('a')]);
    const s2 = makeSection([paraNode('b')]);
    const layout = layoutDocument([s1, s2]);
    expect(layout.pages.length).toBe(2);
    expect(layout.pages[0].pageNumber).toBe(1);
    expect(layout.pages[1].pageNumber).toBe(2);
    expect(layout.pages[0].sectionIndex).toBe(0);
    expect(layout.pages[1].sectionIndex).toBe(1);
  });
});

describe('Paginator — entry 座標', () => {
  it('Line entry y 從 marginTop 起算且不為負', () => {
    const r = paginate(makeSection([paraNode('hello')]), 0, 1);
    const lineEntry = r.pages[0].entries[0];
    expect(lineEntry.y).toBeGreaterThanOrEqual(72); // marginTop = 72
    expect(lineEntry.x).toBeGreaterThanOrEqual(72); // marginLeft = 72
  });
});

// ── Sprint 17：image-row break heuristic（規則 R1）──────────────────────────────

describe('Sprint 17 — image-row break heuristic', () => {
  /** 建一個含大型 inline image 的 row（高度由 trHeight 控制）。 */
  function imageRow(rId: string, imgW: number, imgH: number, trHeight?: number): RowNode {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [{
        type: 'paragraph',
        props: {},
        runs: [{ type: 'inlineImage', rId, width: imgW, height: imgH }],
      }],
      props: {},
    };
    const props: RowNode['props'] = { isHeader: false, cantSplit: true };
    if (trHeight !== undefined) {
      props.height = trHeight;
      props.heightRule = 'atLeast';
    }
    return { type: 'row', cells: [cell], props };
  }

  /** 建一個短文字 row。 */
  function textRow(text: string): RowNode {
    return {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [paraNode(text)],
        props: {},
      }],
      props: { isHeader: false, cantSplit: true },
    };
  }

  it('Sprint 18 預設 ratio=0.34 + transition 變體：std→image 觸發（且 overflow）', () => {
    // Sprint 31：R1 條件加上 overflow — 此 fixture 用 600pt image row
    // 確保 std(header) + image(600) = 614+ > 698pt（contentHeight）才觸發
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), imageRow('rId7', 700, 700, 700)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    expect(r.pages.length).toBe(2);
  });

  it('Sprint 18 預設 ratio=0.34：opt-in 改 ratio=0 可保留 Sprint 16 行為（非 overflow 場景）', () => {
    // 改用 300pt image row（不 overflow），R1=0 + R1=0.34 都應該 fit 1 頁
    // 600pt image row 會被自然 overflow split，無論 R1 設定如何
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), imageRow('rId7b', 300, 300, 300)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1, { imageRowBreakRatio: 0 });
    expect(r.pages.length).toBe(1);
  });

  it('opt-in（ratio=0.3）+ cantSplit + 大型 image + overflow：強制換頁', () => {
    // Sprint 31：image row 高 600pt，header + image > contentHeight → 觸發 R1
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), imageRow('rId7', 700, 700, 700)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1, { imageRowBreakRatio: 0.3 });
    expect(r.pages.length).toBe(2);
    const page2Tables = r.pages[1].entries.filter((e) => e.kind === 'table');
    expect(page2Tables.length).toBe(1);
    if (page2Tables[0].kind === 'table') {
      expect(page2Tables[0].isContinuation).toBe(true);
    }
  });

  it('Sprint 31：transition + 不 overflow → 不觸發 R1（04_with_image 場景）', () => {
    // header + image 共 ~314pt < contentHeight 698pt → fit 1 頁、R1 不觸發
    // 此 case 在 Sprint 30 之前會被 R1 強制 split 成 2 頁，視覺對齊失準
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), imageRow('rId7c', 300, 300, 300)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    expect(r.pages.length).toBe(1);
  });

  it('opt-in（ratio=0.3）+ 小型 image row（< 30% contentHeight）：不觸發 R1', () => {
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), imageRow('rId8', 60, 60, 60)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1, { imageRowBreakRatio: 0.3 });
    expect(r.pages.length).toBe(1);
  });

  it('opt-in（ratio=0.3）+ cantSplit=false 的 image row：不觸發 R1', () => {
    const splittableImageRow: RowNode = {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [{
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'rIdX', width: 300, height: 300 }],
        }],
        props: {},
      }],
      props: { isHeader: false, cantSplit: false, height: 300, heightRule: 'atLeast' },
    };
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [textRow('header'), splittableImageRow],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1, { imageRowBreakRatio: 0.3 });
    const firstPageTable = r.pages[0].entries.find((e) => e.kind === 'table');
    expect(firstPageTable).toBeDefined();
    if (firstPageTable && firstPageTable.kind === 'table') {
      expect(firstPageTable.isContinuation).toBe(false);
    }
  });

  it('opt-in + 空頁時不觸發 R1（避免空轉）', () => {
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [imageRow('rIdA', 300, 300, 300)],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1, { imageRowBreakRatio: 0.3 });
    expect(r.pages.length).toBe(1);
  });

  it('layoutDocument 預設啟用 R1 transition 變體（ratio=0.34）— overflow 場景', () => {
    // Sprint 31：用 600pt image row + paragraph 確保 overflow
    const sec: SectionNode = makeSection([
      paraNode('paragraph 1'),
      {
        type: 'table',
        grid: [400],
        rows: [textRow('std row'), imageRow('rIdB', 700, 700, 700)],
        props: {},
      },
    ]);
    const layout = layoutDocument([sec]);
    // 預設啟用 → std→image transition + overflow 觸發 → 至少 2 頁
    expect(layout.pages.length).toBeGreaterThanOrEqual(2);
  });

  it('Sprint 18 + 31：連續 image row 不觸發 R1（image→image 不換頁），overflow 場景', () => {
    // 兩個 600pt image row → 1200pt > contentHeight 698pt → 必須拆頁
    // P1: std header + 第一個 image row(部分)；P2: 第一個 image row(剩) + 第二個 image row
    // 重點：image→image 不觸發 R1，連續 image rows 不額外拆頁
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [
        textRow('std header'),
        imageRow('rIdC1', 600, 600, 600), // std→image + overflow → break, page 2
        imageRow('rIdC2', 600, 600, 600), // image→image：無 R1 觸發
      ],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    // page count 至少 2（image rows 太大，多於 1 頁）
    expect(r.pages.length).toBeGreaterThanOrEqual(2);
  });

  it('Sprint 18 + 31：image→std transition + overflow 也觸發 R1（離開 image block）', () => {
    // Sprint 31：image row 設 600pt 強制 overflow，image→std 才觸發
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [
        textRow('std A'),
        imageRow('rIdD', 700, 700, 700), // std→image + overflow：page 2
        textRow('std B'),                  // image→std + overflow（page 2 已塞 image 600pt 接 std 必 overflow）：page 3
      ],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    expect(r.pages.length).toBe(3);
  });
});

// ── Sprint 18：cell-internal page break（splitRowAtPageBreak 整合）─────────────

describe('Sprint 18 — cell-internal page break 觸發', () => {
  /** Build a row whose single cell contains a paragraph with `<w:br type="page"/>`. */
  function rowWithCellPageBreak(): RowNode {
    return {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [{
          type: 'paragraph',
          props: {},
          runs: [
            { type: 'run', text: 'before', props: { fontSize: 12 } },
            { type: 'break', breakType: 'page' },
            { type: 'run', text: 'after', props: { fontSize: 12 } },
          ],
        }],
        props: {},
      }],
      props: { isHeader: false, cantSplit: false },
    };
  }
  function plainTextRow(text: string): RowNode {
    return {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [paraNode(text)],
        props: {},
      }],
      props: { isHeader: false, cantSplit: false },
    };
  }
  function tableRowImage(rId: string): RowNode {
    return {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [{
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId, width: 300, height: 300 }],
        }],
        props: {},
      }],
      props: { isHeader: false, cantSplit: true, height: 300, heightRule: 'atLeast' },
    };
  }

  it('row 內 page break 會被 split：分成兩頁', () => {
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [rowWithCellPageBreak()],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    expect(r.pages.length).toBe(2);
  });

  it('row 內無 page break：保持單頁', () => {
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [plainTextRow('all in one page')],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    expect(r.pages.length).toBe(1);
  });

  it('整張表含大型 image row 時：cell-internal break 不觸發（fall through 到 R1 + overflow）', () => {
    // Sprint 31：R1 條件加上 overflow，所以 image row 設成 600pt 確保 overflow
    // 一張表內既有 page break row 又有大型 image row → tableHasImageRow 旗標啟用 →
    // cell-break split 跳過，由 R1 transition + overflow 處理 → 2 頁
    const largeImageRow: RowNode = {
      type: 'row',
      cells: [{
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        rowSpan: 1,
        isContinuation: false,
        content: [{
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'rIdImgLarge', width: 700, height: 700 }],
        }],
        props: {},
      }],
      props: { isHeader: false, cantSplit: true, height: 700, heightRule: 'atLeast' },
    };
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [
        plainTextRow('std A'),
        largeImageRow,
      ],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    // R1 ratio=0.34 預設啟用 + overflow（std + 600pt image > 698pt contentHeight）→ 2 頁
    expect(r.pages.length).toBe(2);
  });

  it('多個 cell-internal page break：逐一 split（連鎖）', () => {
    const table: TableNode = {
      type: 'table',
      grid: [400],
      rows: [
        rowWithCellPageBreak(), // 第 1 個 break
        rowWithCellPageBreak(), // 第 2 個 break
      ],
      props: {},
    };
    const r = paginate(makeSection([table]), 0, 1);
    // 兩個 break = 至少 3 頁
    expect(r.pages.length).toBeGreaterThanOrEqual(3);
  });
});

// ── Sprint 139：layout 路徑 numbering wire-up 整合測試 ──────────────────────

import type { AbstractNumbering, NumberingLevel, NumberingMap } from '../../../static/src/core/ooxml/ast/types';

function numLevel(ilvl: number, opts: Partial<NumberingLevel> = {}): NumberingLevel {
  return { ilvl, numFmt: 'decimal', text: `%${ilvl + 1}.`, start: 1, ...opts };
}

describe('Paginator — Sprint 139 numbering wire-up', () => {
  it('LayoutOptions.numbering 未傳 → 段落不 emit 前綴（VR baseline backward compat）', () => {
    const para = paraNode('hello', 12, { numId: 1, ilvl: 0 });
    const r = paginate(makeSection([para]), 0, 1);
    // 不傳 numbering 時 first line 第一個 box 文字應 = 'hello'（無 '1.' 前綴）
    const firstLine = r.pages[0].entries[0];
    expect(firstLine.kind).toBe('line');
    if (firstLine.kind === 'line') {
      const firstBox = firstLine.line.items.find((it) => it.kind === 'box');
      expect(firstBox && (firstBox as { text: string }).text).toBe('hello');
    }
  });

  it('LayoutOptions.numbering 有傳 + paragraph 有 numId → emit「1.」前綴', () => {
    const para = paraNode('hello', 12, { numId: 1, ilvl: 0 });
    const numbering: NumberingMap = new Map([
      [1, { abstractNumId: 0, levels: [numLevel(0)] } as AbstractNumbering],
    ]);
    const r = paginate(makeSection([para]), 0, 1, { numbering });
    const firstLine = r.pages[0].entries[0];
    expect(firstLine.kind).toBe('line');
    if (firstLine.kind === 'line') {
      const boxes = firstLine.line.items.filter((it) => it.kind === 'box') as Array<{ text: string }>;
      // 西文 'hello' 是單一 token 一個 Box；'1.' 因為都是西文字也是單一 token
      // 第一個 box = '1.'、第二個 box = 'hello'
      expect(boxes[0].text).toBe('1.');
      expect(boxes[1].text).toBe('hello');
    }
  });

  it('連續同 numId 段落 → counter +1', () => {
    const numbering: NumberingMap = new Map([
      [1, { abstractNumId: 0, levels: [numLevel(0)] } as AbstractNumbering],
    ]);
    const r = paginate(
      makeSection([
        paraNode('A', 12, { numId: 1, ilvl: 0 }),
        paraNode('B', 12, { numId: 1, ilvl: 0 }),
        paraNode('C', 12, { numId: 1, ilvl: 0 }),
      ]),
      0, 1, { numbering },
    );
    const prefixes: string[] = [];
    for (const entry of r.pages[0].entries) {
      if (entry.kind === 'line') {
        const firstBox = entry.line.items.find((it) => it.kind === 'box') as { text: string } | undefined;
        if (firstBox) prefixes.push(firstBox.text);
      }
    }
    expect(prefixes).toEqual(['1.', '2.', '3.']);
  });

  it('body + table cell 共用 counter state（cell 內 numId 接續 body）', () => {
    const numbering: NumberingMap = new Map([
      [1, { abstractNumId: 0, levels: [numLevel(0)] } as AbstractNumbering],
    ]);
    const cellPara = paraNode('cell', 12, { numId: 1, ilvl: 0 });
    const bodyPara = paraNode('body', 12, { numId: 1, ilvl: 0 });
    const table: TableNode = {
      type: 'table',
      grid: [200],
      rows: [
        {
          type: 'row',
          cells: [{
            type: 'cell',
            gridCol: 0,
            gridSpan: 1,
            rowSpan: 1,
            isContinuation: false,
            content: [cellPara],
            props: {},
          }],
          props: { isHeader: false, cantSplit: false },
        },
      ],
      props: {},
    };
    const r = paginate(makeSection([bodyPara, table]), 0, 1, { numbering });
    // body 段落為 '1.\tbody'；table cell 內 paragraph 為 '2.\tcell'（共用 counter）
    const bodyLine = r.pages[0].entries.find((e) => e.kind === 'line');
    expect(bodyLine?.kind).toBe('line');
    if (bodyLine?.kind === 'line') {
      const bodyFirstBox = bodyLine.line.items.find((it) => it.kind === 'box') as { text: string };
      expect(bodyFirstBox.text).toBe('1.');
    }
    // table entry
    const tableEntry = r.pages[0].entries.find((e) => e.kind === 'table');
    expect(tableEntry?.kind).toBe('table');
    if (tableEntry?.kind === 'table') {
      const cell = tableEntry.rows[0].cells[0];
      const cellFirstLine = cell.lines?.[0];
      expect(cellFirstLine).toBeDefined();
      const cellFirstBox = cellFirstLine!.items.find((it) => it.kind === 'box') as { text: string };
      expect(cellFirstBox.text).toBe('2.');
    }
  });

  it('layoutDocument 透傳 numbering → counter 跨 section 共用', () => {
    const numbering: NumberingMap = new Map([
      [1, { abstractNumId: 0, levels: [numLevel(0)] } as AbstractNumbering],
    ]);
    const s1 = makeSection([paraNode('A', 12, { numId: 1, ilvl: 0 })]);
    const s2 = makeSection([paraNode('B', 12, { numId: 1, ilvl: 0 })]);
    const layout = layoutDocument([s1, s2], { numbering });
    // s1 first paragraph 應 '1.'、s2 first paragraph 應 '2.'（共用 counter 跨 section）
    const s1FirstLine = layout.pages[0].entries.find((e) => e.kind === 'line');
    const lastPage = layout.pages[layout.pages.length - 1];
    const s2FirstLine = lastPage.entries.find((e) => e.kind === 'line');
    if (s1FirstLine?.kind === 'line' && s2FirstLine?.kind === 'line') {
      const p1 = s1FirstLine.line.items.find((it) => it.kind === 'box') as { text: string };
      const p2 = s2FirstLine.line.items.find((it) => it.kind === 'box') as { text: string };
      expect(p1.text).toBe('1.');
      expect(p2.text).toBe('2.');
    }
  });
});
