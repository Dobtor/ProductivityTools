/**
 * Sprint 5 — 巢狀表格 + multi-column unit tests
 */

import { describe, expect, it } from 'vitest';
import { layoutCell, layoutTable } from '../../../static/src/core/layout/TableLayout';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  TableNode,
  CellNode,
  RowNode,
  RunNode,
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

function rowNode(cells: CellNode[]): RowNode {
  return {
    type: 'row',
    cells,
    props: { isHeader: false, cantSplit: false },
  };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return {
    type: 'table',
    grid,
    rows,
    props: {},
  };
}

// ── 巢狀表格 ─────────────────────────────────────────────────────────────

describe('Sprint 5 — 巢狀表格', () => {
  it('cell 內含 TableNode：layoutCell 產生 nestedTables', () => {
    const inner = tableNode(
      [50, 50],
      [rowNode([
        cellNode([paraNode('A')], { gridCol: 0 }),
        cellNode([paraNode('B')], { gridCol: 1 }),
      ])],
    );
    // 外層 cell 內含 1 段文字 + 1 張巢狀表格
    const outerCell = cellNode([paraNode('outer'), inner], { gridSpan: 1 });
    const out = layoutCell(outerCell, 200, 0, tableNode([200], []));
    // lines 應有外層段落
    expect(out.lines.length).toBeGreaterThanOrEqual(1);
    // nestedTables 應有 1 張
    expect(out.nestedTables).toBeDefined();
    expect(out.nestedTables!.length).toBe(1);
    expect(out.nestedTables![0].rows.length).toBe(1);
    expect(out.nestedTables![0].columnWidths.length).toBe(2);
  });

  it('巢狀表格高度累加到 cell.height', () => {
    const inner = tableNode(
      [50, 50],
      [
        rowNode([cellNode([paraNode('R1')]), cellNode([paraNode('R1b')])]),
        rowNode([cellNode([paraNode('R2')]), cellNode([paraNode('R2b')])]),
      ],
    );
    const cellWithoutNest = cellNode([paraNode('only text')]);
    const cellWithNest = cellNode([paraNode('only text'), inner]);

    const oA = layoutCell(cellWithoutNest, 200, 0, tableNode([200], []));
    const oB = layoutCell(cellWithNest, 200, 1, tableNode([200], []));
    expect(oB.height).toBeGreaterThan(oA.height);
    // B 的 nestedTables[0].height > 0
    expect(oB.nestedTables![0].height).toBeGreaterThan(0);
  });

  it('沒有巢狀表格時 nestedTables 為 undefined', () => {
    const cell = cellNode([paraNode('plain text only')]);
    const out = layoutCell(cell, 200, 0, tableNode([200], []));
    expect(out.nestedTables).toBeUndefined();
  });

  it('layoutTable 對含巢狀表格的 row 統計：高度由內含 + 外層 sum', () => {
    const inner = tableNode([50, 50], [rowNode([cellNode([paraNode('x')]), cellNode([paraNode('y')])])]);
    const outer = tableNode(
      [200],
      [rowNode([cellNode([paraNode('outer'), inner])])],
    );
    const out = layoutTable(outer, 200);
    expect(out.rows.length).toBe(1);
    expect(out.rows[0].cells[0].nestedTables).toBeDefined();
  });
});

// ── Multi-column ────────────────────────────────────────────────────────

describe('Sprint 5 — Multi-column', () => {
  it('section.columns.count=2：lineWidth 變窄、行數變多', () => {
    const text = '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十';
    const sec1col = makeSection([paraNode(text, 12)]);
    const sec2col = makeSection([paraNode(text, 12)], { count: 2, space: 36 });
    const lay1 = layoutDocument([sec1col]);
    const lay2 = layoutDocument([sec2col]);

    const lines1 = lay1.pages.flatMap((p) => p.entries.filter((e) => e.kind === 'line'));
    const lines2 = lay2.pages.flatMap((p) => p.entries.filter((e) => e.kind === 'line'));

    // 雙欄 lineWidth 約是單欄的一半，行數至少多 1.5 倍
    expect(lines2.length).toBeGreaterThan(lines1.length);
    expect(lines2.length).toBeGreaterThanOrEqual(Math.ceil(lines1.length * 1.5));
  });

  it('Multi-column：第二欄的 line entry x 應大於第一欄', () => {
    const fillers = Array.from({ length: 60 }, (_, i) => paraNode(`段${i}`));
    const sec = makeSection(fillers, { count: 2, space: 36 });
    const layout = layoutDocument([sec]);
    const lineEntries = layout.pages
      .flatMap((p) => p.entries.filter((e) => e.kind === 'line'));

    // 收集所有獨特的 X 座標
    const xValues = new Set<number>();
    for (const e of lineEntries) xValues.add(Math.round(e.x));
    // 雙欄應有至少 2 個不同的 X 值（兩個欄位的起始 X）
    expect(xValues.size).toBeGreaterThanOrEqual(2);
  });

  it('Multi-column：欄滿 → 切下一欄；最後一欄滿 → 換頁', () => {
    // 大量段落填滿頁面
    const fillers = Array.from({ length: 200 }, (_, i) => paraNode(`段落${i}`, 12));
    const sec = makeSection(fillers, { count: 2 });
    const layout = layoutDocument([sec]);
    expect(layout.pages.length).toBeGreaterThan(1);
  });

  it('count=1 與沒指定 columns 行為一致', () => {
    const text = '一二三四五六七八九十' . repeat(5);
    const noCol = makeSection([paraNode(text, 12)]);
    const oneCol = makeSection([paraNode(text, 12)], { count: 1 });
    const a = layoutDocument([noCol]);
    const b = layoutDocument([oneCol]);
    const linesA = a.pages.flatMap((p) => p.entries.filter((e) => e.kind === 'line')).length;
    const linesB = b.pages.flatMap((p) => p.entries.filter((e) => e.kind === 'line')).length;
    expect(linesA).toBe(linesB);
  });
});
