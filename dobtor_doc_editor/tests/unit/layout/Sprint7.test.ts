/**
 * Sprint 7 — Column break + 巢狀表格樣式繼承 + Cell mid-row break
 */

import { describe, expect, it } from 'vitest';
import {
  layoutDocument,
} from '../../../static/src/core/layout/Paginator';
import { splitRowAtHeight, layoutTable } from '../../../static/src/core/layout/TableLayout';
import { applyTableStyle, DEFAULT_TBL_LOOK } from '../../../static/src/core/ooxml/styles/TableStyleApplicator';
import type {
  SectionNode,
  ParagraphNode,
  TableNode,
  CellNode,
  RowNode,
  RunNode,
  StyleEntry,
  BreakNode,
} from '../../../static/src/core/ooxml/ast/types';

const A4_PORTRAIT = { width: 595, height: 842, orientation: 'portrait' as const };
const STD_MARGINS = {
  top: 72, bottom: 72, left: 72, right: 72,
  header: 36, footer: 36,
};

function makeSection(
  body: SectionNode['body'] = [],
  columns?: SectionNode['columns'],
): SectionNode {
  return {
    type: 'section',
    page: A4_PORTRAIT,
    margins: STD_MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
    ...(columns ? { columns } : {}),
  };
}

function paraNode(text: string, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function paraWithBreak(text: string, breakType: 'page' | 'column'): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  const br: BreakNode = { type: 'break', breakType };
  return { type: 'paragraph', props: {}, runs: [run, br] };
}

function cellNode(content: CellNode['content'], opts: Partial<CellNode> = {}): CellNode {
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content,
    props: {},
    ...opts,
  };
}

function rowNode(cells: CellNode[], opts: Partial<RowNode['props']> = {}): RowNode {
  return {
    type: 'row',
    cells,
    props: { isHeader: false, cantSplit: false, ...opts },
  };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return { type: 'table', grid, rows, props: {} };
}

// ── Column break ────────────────────────────────────────────────────────

describe('Sprint 7 — Column break', () => {
  it('column break 在多欄 section 觸發 nextColumnOrPage', () => {
    // 雙欄；先放短段落、column break、再放短段落 → 第二段在第二欄
    const sec = makeSection([
      paraWithBreak('first', 'column'),
      paraNode('second'),
    ], { count: 2, space: 18 });
    const layout = layoutDocument([sec]);
    const lineEntries = layout.pages
      .flatMap((p) => p.entries.filter((e) => e.kind === 'line'));
    // 兩個 line entry，X 不同（在不同欄）
    expect(lineEntries.length).toBe(2);
    const xs = [...new Set(lineEntries.map((e) => Math.round(e.x)))];
    expect(xs.length).toBe(2);
  });

  it('column break 在單欄 section 等同於 page break', () => {
    const sec = makeSection([
      paraWithBreak('first', 'column'),
      paraNode('second'),
    ]);
    const layout = layoutDocument([sec]);
    expect(layout.pages.length).toBe(2);
  });

  it('page break 仍正常觸發 flushPage', () => {
    const sec = makeSection([
      paraWithBreak('first', 'page'),
      paraNode('second'),
    ]);
    const layout = layoutDocument([sec]);
    expect(layout.pages.length).toBe(2);
  });
});

// ── 巢狀表格樣式繼承 ─────────────────────────────────────────────────────

describe('Sprint 7 — 巢狀表格樣式繼承', () => {
  it('巢狀表格內 paragraph 繼承外層 effective props', () => {
    const innerPara = paraNode('inner');
    const innerCell = cellNode([innerPara]);
    const inner = tableNode([100], [rowNode([innerCell])]);
    // 外層 cell 內含一段（外層 styles 套用後 props 應傳入）+ 巢狀表格
    const outerPara = paraNode('outer');
    const outerCell = cellNode([outerPara, inner]);
    const outer = tableNode([200], [rowNode([outerCell])]);

    // 外層樣式：粗體 + 紅字
    const styleEntry: StyleEntry = {
      pProps: {},
      rProps: { bold: true, color: 'FF0000' },
    };
    applyTableStyle(outer, styleEntry, DEFAULT_TBL_LOOK);

    // 外層 paragraph 的 run 應有 bold + color
    const outerRun = outerPara.runs[0];
    expect(outerRun.type === 'run' && outerRun.props.bold).toBe(true);
    expect(outerRun.type === 'run' && outerRun.props.color).toBe('FF0000');

    // Sprint 7：巢狀表格的 paragraph 也應繼承
    const innerRun = innerPara.runs[0];
    expect(innerRun.type === 'run' && innerRun.props.bold).toBe(true);
    expect(innerRun.type === 'run' && innerRun.props.color).toBe('FF0000');
  });

  it('巢狀表已有 styleId 時不重新套外層樣式', () => {
    const innerPara = paraNode('inner');
    const innerCell = cellNode([innerPara]);
    const inner: TableNode = {
      type: 'table',
      grid: [100],
      rows: [rowNode([innerCell])],
      styleId: 'NestedTableOwnStyle', // 已有自己 styleId
      props: {},
    };
    const outerCell = cellNode([inner]);
    const outer = tableNode([200], [rowNode([outerCell])]);
    applyTableStyle(outer, { pProps: {}, rProps: { bold: true } }, DEFAULT_TBL_LOOK);

    // 巢狀表已有 styleId：外層樣式不會強制套
    const innerRun = innerPara.runs[0];
    expect(innerRun.type === 'run' && innerRun.props.bold).toBeUndefined();
  });
});

// ── Cell 內部 mid-row break ─────────────────────────────────────────────

describe('Sprint 7 — Cell 內部 mid-row break', () => {
  it('splitRowAtHeight：可分割的 row 切兩半', () => {
    // 一 row 含 1 cell，cell 內 20 個段落（每段 1 行）
    const paras = Array.from({ length: 20 }, (_, i) => paraNode(`段${i}`, 12));
    const cell = cellNode(paras);
    const row = rowNode([cell]);
    const t = tableNode([200], [row]);
    const out = layoutTable(t, 200);
    const fullRow = out.rows[0];

    // 切到一半（20 行 × ~14.4pt ≈ 288pt；切 100pt 約裝 6-7 行）
    const split = splitRowAtHeight(fullRow, 100);
    expect(split).not.toBeNull();
    if (split) {
      expect(split.first.cells[0].lines.length).toBeGreaterThan(0);
      expect(split.second.cells[0].lines.length).toBeGreaterThan(0);
      const total = split.first.cells[0].lines.length + split.second.cells[0].lines.length;
      expect(total).toBe(20);
      // first 高度應 <= 100
      expect(split.first.height).toBeLessThanOrEqual(100);
    }
  });

  it('splitRowAtHeight：cantSplit row 回 null', () => {
    const cell = cellNode([paraNode('x')]);
    const row = rowNode([cell], { cantSplit: true });
    const t = tableNode([200], [row]);
    const out = layoutTable(t, 200);
    const split = splitRowAtHeight(out.rows[0], 50);
    expect(split).toBeNull();
  });

  it('巨大表格的 row：layoutDocument 會 mid-row split 跨頁', () => {
    // 一張 1×1 表格、cell 內 100 段落，遠超過頁面
    const paras = Array.from({ length: 100 }, (_, i) => paraNode(`段${i}`, 12));
    const cell = cellNode(paras);
    const big = tableNode([400], [rowNode([cell])]);
    const sec = makeSection([big]);
    const layout = layoutDocument([sec]);
    // 應跨多頁
    expect(layout.pages.length).toBeGreaterThan(1);
    // 收集所有 table entries
    const tableEntries = layout.pages
      .flatMap((p) => p.entries.filter((e) => e.kind === 'table'));
    expect(tableEntries.length).toBeGreaterThan(1);
    // 第一個 entry isContinuation=false hasMore=true
    expect(tableEntries[0].kind === 'table' && tableEntries[0].isContinuation).toBe(false);
    expect(tableEntries[0].kind === 'table' && tableEntries[0].hasMore).toBe(true);
    // 最後一個 hasMore=false
    const last = tableEntries[tableEntries.length - 1];
    expect(last.kind === 'table' && last.hasMore).toBe(false);
  });

  it('mid-row break：所有 cell 內容仍然出現（無 line 遺失）', () => {
    const targetCount = 50;
    const paras = Array.from({ length: targetCount }, (_, i) => paraNode(`段${i}`, 12));
    const cell = cellNode(paras);
    const big = tableNode([400], [rowNode([cell])]);
    const sec = makeSection([big]);
    const layout = layoutDocument([sec]);

    let totalLines = 0;
    for (const p of layout.pages) {
      for (const e of p.entries) {
        if (e.kind === 'table') {
          for (const r of e.rows) {
            for (const c of r.cells) {
              totalLines += c.lines.length;
            }
          }
        }
      }
    }
    expect(totalLines).toBe(targetCount);
  });
});
