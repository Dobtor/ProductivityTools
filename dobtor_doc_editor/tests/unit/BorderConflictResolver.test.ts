/**
 * BorderConflictResolver.test.ts — Phase 4.3
 *
 * 涵蓋：
 *   - resolveCellEdge：兩側 BorderDef 競爭（width / style weight / color / nil）
 *   - mergeCellBorders：cell 自己 vs table inside/outside 邊
 *   - resolveTableBorders：相鄰 cell 邊界協調 + vMerge continuation 不渲染
 */

import { describe, expect, it } from 'vitest';
import {
  resolveCellEdge,
  resolveTableBorders,
  mergeCellBorders,
} from '../../static/src/core/ooxml/table/BorderConflictResolver';
import type {
  BorderDef,
  CellNode,
  RowNode,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const SINGLE_THIN: BorderDef = { style: 'single', width: 0.5, color: '000000' };
const SINGLE_THICK: BorderDef = { style: 'single', width: 2, color: '000000' };
const DOUBLE_THIN: BorderDef = { style: 'double', width: 0.5, color: '000000' };
const NIL: BorderDef = { style: 'nil', width: 0, color: '000000' };
const NONE: BorderDef = { style: 'none', width: 0, color: '000000' };
const RED_SINGLE: BorderDef = { style: 'single', width: 0.5, color: 'FF0000' };
const BLUE_SINGLE: BorderDef = { style: 'single', width: 0.5, color: '0000FF' };

// ── resolveCellEdge ──────────────────────────────────────────────────────────

describe('BorderConflictResolver — resolveCellEdge', () => {
  it('兩邊都 undefined 回 undefined', () => {
    expect(resolveCellEdge(undefined, undefined)).toBeUndefined();
  });

  it('一側 undefined：另一側贏（除非另一側是 nil）', () => {
    expect(resolveCellEdge(SINGLE_THIN, undefined)).toBe(SINGLE_THIN);
    expect(resolveCellEdge(undefined, SINGLE_THIN)).toBe(SINGLE_THIN);
    expect(resolveCellEdge(undefined, NIL)).toBeUndefined();
    expect(resolveCellEdge(NIL, undefined)).toBeUndefined();
  });

  it('雙方皆 nil：回 undefined', () => {
    expect(resolveCellEdge(NIL, NIL)).toBeUndefined();
    expect(resolveCellEdge(NIL, NONE)).toBeUndefined();
  });

  it('一側 nil：另一側贏', () => {
    expect(resolveCellEdge(NIL, SINGLE_THIN)).toBe(SINGLE_THIN);
    expect(resolveCellEdge(SINGLE_THIN, NIL)).toBe(SINGLE_THIN);
  });

  it('width 不同：較寬者勝', () => {
    expect(resolveCellEdge(SINGLE_THIN, SINGLE_THICK)).toBe(SINGLE_THICK);
    expect(resolveCellEdge(SINGLE_THICK, SINGLE_THIN)).toBe(SINGLE_THICK);
  });

  it('width 平手 + style weight 不同：weight 大者勝（double > single）', () => {
    expect(resolveCellEdge(SINGLE_THIN, DOUBLE_THIN)).toBe(DOUBLE_THIN);
    expect(resolveCellEdge(DOUBLE_THIN, SINGLE_THIN)).toBe(DOUBLE_THIN);
  });

  it('width + style 平手 + color 不同：較小字典序勝', () => {
    // 0000FF < FF0000
    expect(resolveCellEdge(RED_SINGLE, BLUE_SINGLE)).toBe(BLUE_SINGLE);
    expect(resolveCellEdge(BLUE_SINGLE, RED_SINGLE)).toBe(BLUE_SINGLE);
  });

  it('全平手回 a（穩定）', () => {
    const a = { ...SINGLE_THIN };
    const b = { ...SINGLE_THIN };
    expect(resolveCellEdge(a, b)).toBe(a);
  });
});

// ── helpers for table-level tests ────────────────────────────────────────────

function makeCell(gridCol: number, gridSpan = 1, isContinuation = false, ownBorders?: import('../../static/src/core/ooxml/ast/types').CellBorders): CellNode {
  return {
    type: 'cell',
    gridCol,
    gridSpan,
    rowSpan: 1,
    isContinuation,
    content: [],
    props: ownBorders ? { borders: ownBorders } : {},
  };
}

function makeRow(cells: CellNode[]): RowNode {
  return { type: 'row', cells, props: { isHeader: false, cantSplit: false } };
}

function makeTable(rows: RowNode[], cols: number, tblBorders?: import('../../static/src/core/ooxml/ast/types').CellBorders): TableNode {
  const t: TableNode = {
    type: 'table',
    grid: Array(cols).fill(50),
    rows,
    props: tblBorders ? { borders: tblBorders } : {},
  };
  return t;
}

// ── mergeCellBorders ─────────────────────────────────────────────────────────

describe('BorderConflictResolver — mergeCellBorders', () => {
  it('cell 無 own borders + table 設外緣：corner cell 取外緣', () => {
    const cell = makeCell(0, 1);
    const row = makeRow([cell]);
    const table = makeTable([row], 1, { top: SINGLE_THICK, bottom: SINGLE_THICK, left: SINGLE_THICK, right: SINGLE_THICK });
    const merged = mergeCellBorders(cell, row, table, 0, 1);
    expect(merged.top).toEqual(SINGLE_THICK);
    expect(merged.bottom).toEqual(SINGLE_THICK);
    expect(merged.left).toEqual(SINGLE_THICK);
    expect(merged.right).toEqual(SINGLE_THICK);
  });

  it('中段 cell 取 insideH/insideV', () => {
    const cells = [makeCell(0), makeCell(1), makeCell(2)];
    const row = makeRow(cells);
    const table = makeTable([row, makeRow([makeCell(0), makeCell(1), makeCell(2)])], 3, {
      top: SINGLE_THICK,
      bottom: SINGLE_THICK,
      left: SINGLE_THICK,
      right: SINGLE_THICK,
      insideH: SINGLE_THIN,
      insideV: DOUBLE_THIN,
    });
    // 中間 cell（gridCol=1）：top/bottom 在 row=0 是 outside top + inside bottom
    const middle = mergeCellBorders(cells[1], row, table, 0, 2);
    expect(middle.top).toEqual(SINGLE_THICK);    // 外緣 top
    expect(middle.bottom).toEqual(SINGLE_THIN);  // insideH
    expect(middle.left).toEqual(DOUBLE_THIN);    // insideV
    expect(middle.right).toEqual(DOUBLE_THIN);   // insideV
  });

  it('cell own borders 與 table inside 競爭：粗線者勝', () => {
    const cell = makeCell(1, 1, false, { top: SINGLE_THICK });
    const row = makeRow([makeCell(0), cell, makeCell(2)]);
    const table = makeTable([row, makeRow([makeCell(0), makeCell(1), makeCell(2)])], 3, {
      top: SINGLE_THIN,
      insideH: SINGLE_THIN,
    });
    const merged = mergeCellBorders(cell, row, table, 0, 2);
    expect(merged.top).toEqual(SINGLE_THICK);  // cell own thick wins
  });
});

// ── resolveTableBorders（整表 mutate）───────────────────────────────────────

describe('BorderConflictResolver — resolveTableBorders', () => {
  it('完整 mutate：每 cell 取得 effective borders', () => {
    const cells1 = [makeCell(0), makeCell(1)];
    const cells2 = [makeCell(0), makeCell(1)];
    const table = makeTable(
      [makeRow(cells1), makeRow(cells2)],
      2,
      { top: SINGLE_THICK, bottom: SINGLE_THICK, left: SINGLE_THICK, right: SINGLE_THICK, insideH: SINGLE_THIN, insideV: SINGLE_THIN },
    );
    resolveTableBorders(table);

    // cells1[0]：左上 corner
    expect(cells1[0].props.borders?.top).toEqual(SINGLE_THICK);
    expect(cells1[0].props.borders?.left).toEqual(SINGLE_THICK);
    // bottom = insideH，但和 cells2[0].top（也是 insideH）競爭，平手 → SINGLE_THIN
    expect(cells1[0].props.borders?.bottom?.style).toBe('single');
    // 右邊 = insideV
    expect(cells1[0].props.borders?.right?.style).toBe('single');

    // cells2[1]：右下 corner
    expect(cells2[1].props.borders?.bottom).toEqual(SINGLE_THICK);
    expect(cells2[1].props.borders?.right).toEqual(SINGLE_THICK);
  });

  it('相鄰 cell 邊界協調：左 cell.right 與右 cell.left 取勝者寫回兩側', () => {
    const cells = [
      makeCell(0, 1, false, { right: SINGLE_THICK }),
      makeCell(1, 1, false, { left: SINGLE_THIN }),
    ];
    const table = makeTable([makeRow(cells)], 2);
    resolveTableBorders(table);

    expect(cells[0].props.borders?.right?.width).toBe(2);  // 取較粗
    expect(cells[1].props.borders?.left?.width).toBe(2);   // 兩側一致
  });

  it('vMerge anchor + continuation：top/bottom 不亂協調', () => {
    const anchor = makeCell(0, 1, false);
    anchor.rowSpan = 2;
    const cont = makeCell(0, 1, true);
    const right1 = makeCell(1);
    const right2 = makeCell(1);
    const table = makeTable(
      [makeRow([anchor, right1]), makeRow([cont, right2])],
      2,
      { top: SINGLE_THICK, bottom: SINGLE_THICK, left: SINGLE_THICK, right: SINGLE_THICK, insideH: SINGLE_THIN, insideV: SINGLE_THIN },
    );
    resolveTableBorders(table);

    // anchor 仍應有 borders（無 nil 化）
    expect(anchor.props.borders?.top).toBeDefined();
    expect(anchor.props.borders?.left).toBeDefined();
  });
});
