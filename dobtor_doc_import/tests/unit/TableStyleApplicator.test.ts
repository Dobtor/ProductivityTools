/**
 * TableStyleApplicator.test.ts — Phase 4.2
 *
 * 涵蓋：
 *   - parseTblLook：hex 旗標解析 + 預設值
 *   - applyTableStyle：base / wholeTable / firstRow / lastRow / firstCol / lastCol
 *   - banding：band1Horz / band2Horz / band1Vert / band2Vert
 *   - Corner cells：nwCell / neCell / swCell / seCell
 *   - explicit 屬性優先（不被覆蓋）
 *   - vMerge continuation cell 不套用
 */

import { describe, expect, it } from 'vitest';
import {
  applyTableStyle,
  parseTblLook,
  DEFAULT_TBL_LOOK,
} from '../../static/src/core/ooxml/styles/TableStyleApplicator';
import type {
  TableNode,
  CellNode,
  RowNode,
  ParagraphNode,
  StyleEntry,
  TableConditionalType,
  TableConditionalCellProps,
  ParagraphProps,
  RunProps,
} from '../../static/src/core/ooxml/ast/types';

// ── parseTblLook ─────────────────────────────────────────────────────────────

describe('TableStyleApplicator — parseTblLook', () => {
  it('預設值：缺值或無效 hex 回 DEFAULT_TBL_LOOK', () => {
    expect(parseTblLook(undefined)).toEqual(DEFAULT_TBL_LOOK);
    expect(parseTblLook('')).toEqual(DEFAULT_TBL_LOOK);
    expect(parseTblLook('XYZ')).toEqual(DEFAULT_TBL_LOOK);
  });

  it('"04A0"：firstRow + firstColumn + noVBand', () => {
    const look = parseTblLook('04A0');
    expect(look.firstRow).toBe(true);
    expect(look.firstColumn).toBe(true);
    expect(look.noVBand).toBe(true);
    expect(look.lastRow).toBe(false);
    expect(look.lastColumn).toBe(false);
    expect(look.noHBand).toBe(false);
  });

  it('"04E0"：firstRow + lastRow + firstColumn + noVBand', () => {
    const look = parseTblLook('04E0');
    expect(look.firstRow).toBe(true);
    expect(look.lastRow).toBe(true);
    expect(look.firstColumn).toBe(true);
    expect(look.noVBand).toBe(true);
  });

  it('"0000"：所有旗標關閉', () => {
    const look = parseTblLook('0000');
    expect(look.firstRow).toBe(false);
    expect(look.lastRow).toBe(false);
    expect(look.firstColumn).toBe(false);
    expect(look.lastColumn).toBe(false);
    expect(look.noHBand).toBe(false);
    expect(look.noVBand).toBe(false);
  });

  it('"0FE0"：全旗標', () => {
    const look = parseTblLook('0FE0');
    expect(look.firstRow).toBe(true);
    expect(look.lastRow).toBe(true);
    expect(look.firstColumn).toBe(true);
    expect(look.lastColumn).toBe(true);
    expect(look.noHBand).toBe(true);
    expect(look.noVBand).toBe(true);
  });
});

// ── helpers for applyTableStyle tests ────────────────────────────────────────

function makeRun(text: string, props?: RunProps): import('../../static/src/core/ooxml/ast/types').RunNode {
  return { type: 'run', value: text, props: props ?? {} };
}

function makeParagraph(text: string, pProps?: ParagraphProps, rProps?: RunProps): ParagraphNode {
  return {
    type: 'paragraph',
    props: pProps ?? {},
    runs: [makeRun(text, rProps)],
  };
}

function makeCell(content: ParagraphNode[], gridCol: number, gridSpan = 1, isContinuation = false, rowSpan = 1): CellNode {
  return {
    type: 'cell',
    gridCol,
    gridSpan,
    rowSpan,
    isContinuation,
    content,
    props: {},
  };
}

function makeRow(cells: CellNode[], isHeader = false): RowNode {
  return {
    type: 'row',
    cells,
    props: { isHeader, cantSplit: false },
  };
}

function makeTable(rows: RowNode[], cols: number, styleId?: string): TableNode {
  const grid: number[] = Array(cols).fill(50);
  const out: TableNode = {
    type: 'table',
    grid,
    rows,
    props: {},
  };
  if (styleId) out.styleId = styleId;
  return out;
}

function makeStyleEntry(
  baseP?: ParagraphProps,
  baseR?: RunProps,
  conditional?: Map<
    TableConditionalType,
    { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
  >,
): StyleEntry {
  const e: StyleEntry = {};
  if (baseP) e.pProps = baseP;
  if (baseR) e.rProps = baseR;
  if (conditional) e.conditional = conditional;
  return e;
}

// ── applyTableStyle ──────────────────────────────────────────────────────────

describe('TableStyleApplicator — applyTableStyle base props', () => {
  it('base pProps 與 rProps 套到所有 cell content', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('A')], 0), makeCell([makeParagraph('B')], 1)]),
        makeRow([makeCell([makeParagraph('C')], 0), makeCell([makeParagraph('D')], 1)]),
      ],
      2,
    );
    const style = makeStyleEntry({ alignment: 'center' }, { fontSize: 10 });
    applyTableStyle(table, style, DEFAULT_TBL_LOOK);

    for (const row of table.rows) {
      for (const cell of row.cells) {
        expect(cell.content[0].props.alignment).toBe('center');
        expect((cell.content[0].runs[0] as { type: string; props: RunProps }).props.fontSize).toBe(10);
      }
    }
  });

  it('explicit cell-level rProps 不被覆蓋', () => {
    const explicitRun = makeRun('A', { fontSize: 16 });
    const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [explicitRun] };
    const table = makeTable([makeRow([makeCell([para], 0)])], 1);

    const style = makeStyleEntry(undefined, { fontSize: 10, bold: true });
    applyTableStyle(table, style, DEFAULT_TBL_LOOK);

    expect(explicitRun.props.fontSize).toBe(16); // explicit 保留
    expect(explicitRun.props.bold).toBe(true);   // base 補入
  });
});

describe('TableStyleApplicator — conditional types', () => {
  it('firstRow conditional 套用第一列', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('header A')], 0)]),
        makeRow([makeCell([makeParagraph('body A')], 0)]),
      ],
      1,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['firstRow', { rProps: { bold: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    const headerRun = table.rows[0].cells[0].content[0].runs[0] as { props: RunProps };
    const bodyRun = table.rows[1].cells[0].content[0].runs[0] as { props: RunProps };
    expect(headerRun.props.bold).toBe(true);
    expect(bodyRun.props.bold).toBeUndefined();
  });

  it('firstRow 不啟用時 conditional 不套用', () => {
    const table = makeTable([makeRow([makeCell([makeParagraph('A')], 0)])], 1);
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['firstRow', { rProps: { bold: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: false });

    const run = table.rows[0].cells[0].content[0].runs[0] as { props: RunProps };
    expect(run.props.bold).toBeUndefined();
  });

  it('lastRow conditional 套用最末列', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('A')], 0)]),
        makeRow([makeCell([makeParagraph('B')], 0)]),
        makeRow([makeCell([makeParagraph('C')], 0)]),
      ],
      1,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['lastRow', { rProps: { italic: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, lastRow: true });

    const lastRun = table.rows[2].cells[0].content[0].runs[0] as { props: RunProps };
    const middleRun = table.rows[1].cells[0].content[0].runs[0] as { props: RunProps };
    expect(lastRun.props.italic).toBe(true);
    expect(middleRun.props.italic).toBeUndefined();
  });

  it('firstCol conditional 套用第一欄', () => {
    const table = makeTable(
      [
        makeRow([
          makeCell([makeParagraph('A')], 0),
          makeCell([makeParagraph('B')], 1),
          makeCell([makeParagraph('C')], 2),
        ]),
      ],
      3,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['firstCol', { rProps: { bold: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstColumn: true });

    expect((table.rows[0].cells[0].content[0].runs[0] as { props: RunProps }).props.bold).toBe(true);
    expect((table.rows[0].cells[1].content[0].runs[0] as { props: RunProps }).props.bold).toBeUndefined();
    expect((table.rows[0].cells[2].content[0].runs[0] as { props: RunProps }).props.bold).toBeUndefined();
  });

  it('wholeTable conditional 套到所有 cell（base 之上）', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('A')], 0), makeCell([makeParagraph('B')], 1)]),
      ],
      2,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['wholeTable', { rProps: { fontFamily: 'Times New Roman' } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, DEFAULT_TBL_LOOK);

    for (const cell of table.rows[0].cells) {
      const run = cell.content[0].runs[0] as { props: RunProps };
      expect(run.props.fontFamily).toBe('Times New Roman');
    }
  });

  it('Corner nwCell：firstRow × firstColumn 同時啟用才套', () => {
    const table = makeTable(
      [
        makeRow([
          makeCell([makeParagraph('A')], 0),
          makeCell([makeParagraph('B')], 1),
        ]),
        makeRow([
          makeCell([makeParagraph('C')], 0),
          makeCell([makeParagraph('D')], 1),
        ]),
      ],
      2,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['nwCell', { rProps: { color: 'FF0000' } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true, firstColumn: true });

    expect((table.rows[0].cells[0].content[0].runs[0] as { props: RunProps }).props.color).toBe('FF0000');
    expect((table.rows[0].cells[1].content[0].runs[0] as { props: RunProps }).props.color).toBeUndefined();
    expect((table.rows[1].cells[0].content[0].runs[0] as { props: RunProps }).props.color).toBeUndefined();
  });
});

describe('TableStyleApplicator — banding', () => {
  it('band1Horz / band2Horz 交替套用（無 firstRow）', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('R0')], 0)]),
        makeRow([makeCell([makeParagraph('R1')], 0)]),
        makeRow([makeCell([makeParagraph('R2')], 0)]),
        makeRow([makeCell([makeParagraph('R3')], 0)]),
      ],
      1,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['band1Horz', { rProps: { fontFamily: 'A' } }],
      ['band2Horz', { rProps: { fontFamily: 'B' } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: false, noHBand: false });

    // band index for R0=1, R1=2, R2=1, R3=2
    expect((table.rows[0].cells[0].content[0].runs[0] as { props: RunProps }).props.fontFamily).toBe('A');
    expect((table.rows[1].cells[0].content[0].runs[0] as { props: RunProps }).props.fontFamily).toBe('B');
    expect((table.rows[2].cells[0].content[0].runs[0] as { props: RunProps }).props.fontFamily).toBe('A');
    expect((table.rows[3].cells[0].content[0].runs[0] as { props: RunProps }).props.fontFamily).toBe('B');
  });

  it('noHBand=true 時 banding 不套用', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('A')], 0)]),
        makeRow([makeCell([makeParagraph('B')], 0)]),
      ],
      1,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['band1Horz', { rProps: { bold: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, noHBand: true });

    expect((table.rows[0].cells[0].content[0].runs[0] as { props: RunProps }).props.bold).toBeUndefined();
    expect((table.rows[1].cells[0].content[0].runs[0] as { props: RunProps }).props.bold).toBeUndefined();
  });
});

describe('TableStyleApplicator — vMerge continuation', () => {
  it('isContinuation cell 不套用 conditional', () => {
    const cont = makeCell([makeParagraph('continuation')], 0, 1, true);
    const anchor = makeCell([makeParagraph('anchor')], 0, 1, false, 2);
    const table = makeTable(
      [
        makeRow([anchor]),
        makeRow([cont]),
      ],
      1,
    );
    const cond = new Map<TableConditionalType, { pProps?: ParagraphProps; rProps?: RunProps }>([
      ['wholeTable', { rProps: { bold: true } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, DEFAULT_TBL_LOOK);

    expect((anchor.content[0].runs[0] as { props: RunProps }).props.bold).toBe(true);
    expect((cont.content[0].runs[0] as { props: RunProps }).props.bold).toBeUndefined();
  });
});

// ── Sprint 131：tblStylePr/tcPr 條件樣式 cell-level props（shading + vAlign）───

describe('TableStyleApplicator — Sprint 131 cell-level conditional props', () => {
  it('firstRow tcPr shading 套用第一列 cell 背景色', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('header')], 0), makeCell([makeParagraph('header2')], 1)]),
        makeRow([makeCell([makeParagraph('body')], 0), makeCell([makeParagraph('body2')], 1)]),
      ],
      2,
    );
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['firstRow', { cProps: { shading: { fill: 'DEEAF6' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    expect(table.rows[0].cells[0].props.shading?.fill).toBe('DEEAF6');
    expect(table.rows[0].cells[1].props.shading?.fill).toBe('DEEAF6');
    expect(table.rows[1].cells[0].props.shading).toBeUndefined();
    expect(table.rows[1].cells[1].props.shading).toBeUndefined();
  });

  it('lastCol tcPr vAlign 套用最後一欄 cell 垂直對齊', () => {
    const table = makeTable(
      [
        makeRow([
          makeCell([makeParagraph('A')], 0),
          makeCell([makeParagraph('B')], 1),
          makeCell([makeParagraph('C')], 2),
        ]),
      ],
      3,
    );
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['lastCol', { cProps: { vAlign: 'center' } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, lastColumn: true });

    expect(table.rows[0].cells[0].props.vAlign).toBeUndefined();
    expect(table.rows[0].cells[1].props.vAlign).toBeUndefined();
    expect(table.rows[0].cells[2].props.vAlign).toBe('center');
  });

  it('explicit cell shading 不被 conditional 覆蓋', () => {
    const explicitCell = makeCell([makeParagraph('explicit')], 0);
    explicitCell.props.shading = { fill: 'FF0000' }; // explicit 紅
    const otherCell = makeCell([makeParagraph('other')], 1);
    const table = makeTable([makeRow([explicitCell, otherCell])], 2);
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['firstRow', { cProps: { shading: { fill: 'DEEAF6' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    expect(explicitCell.props.shading?.fill).toBe('FF0000');  // explicit 保留
    expect(otherCell.props.shading?.fill).toBe('DEEAF6');     // conditional 套用
  });

  it('wholeTable + firstRow cProps 後者覆蓋（merge 順序、firstRow 優先）', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('header')], 0)]),
        makeRow([makeCell([makeParagraph('body')], 0)]),
      ],
      1,
    );
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['wholeTable', { cProps: { shading: { fill: 'EEEEEE' }, vAlign: 'top' } }],
      ['firstRow', { cProps: { shading: { fill: 'DEEAF6' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    // header：firstRow shading 覆蓋 wholeTable shading；vAlign 由 wholeTable 保留
    expect(table.rows[0].cells[0].props.shading?.fill).toBe('DEEAF6');
    expect(table.rows[0].cells[0].props.vAlign).toBe('top');
    // body：只套用 wholeTable
    expect(table.rows[1].cells[0].props.shading?.fill).toBe('EEEEEE');
    expect(table.rows[1].cells[0].props.vAlign).toBe('top');
  });

  it('shading 巢狀 per-key 合併（wholeTable fill + firstRow color 共存）', () => {
    const table = makeTable([makeRow([makeCell([makeParagraph('h')], 0)])], 1);
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['wholeTable', { cProps: { shading: { fill: 'EEEEEE', pattern: 'clear' } } }],
      ['firstRow', { cProps: { shading: { color: 'FF0000' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    const shd = table.rows[0].cells[0].props.shading!;
    expect(shd.fill).toBe('EEEEEE');    // wholeTable 保留
    expect(shd.pattern).toBe('clear');  // wholeTable 保留
    expect(shd.color).toBe('FF0000');   // firstRow 補入
  });

  it('nwCell cProps：第一列第一欄角落 cell 套用', () => {
    const table = makeTable(
      [
        makeRow([makeCell([makeParagraph('NW')], 0), makeCell([makeParagraph('NE')], 1)]),
        makeRow([makeCell([makeParagraph('SW')], 0), makeCell([makeParagraph('SE')], 1)]),
      ],
      2,
    );
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['nwCell', { cProps: { shading: { fill: '000000' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true, firstColumn: true });

    expect(table.rows[0].cells[0].props.shading?.fill).toBe('000000'); // NW
    expect(table.rows[0].cells[1].props.shading).toBeUndefined();      // NE
    expect(table.rows[1].cells[0].props.shading).toBeUndefined();      // SW
    expect(table.rows[1].cells[1].props.shading).toBeUndefined();      // SE
  });

  it('tblLook firstRow=false 時 firstRow cProps 不套用', () => {
    const table = makeTable([makeRow([makeCell([makeParagraph('h')], 0)])], 1);
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['firstRow', { cProps: { shading: { fill: 'DEEAF6' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: false });

    expect(table.rows[0].cells[0].props.shading).toBeUndefined();
  });

  it('isContinuation cell 不套用 cProps shading', () => {
    const cont = makeCell([makeParagraph('continuation')], 0, 1, true);
    const anchor = makeCell([makeParagraph('anchor')], 0, 1, false, 2);
    const table = makeTable([makeRow([anchor]), makeRow([cont])], 1);
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['wholeTable', { cProps: { shading: { fill: 'EEEEEE' } } }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, DEFAULT_TBL_LOOK);

    expect(anchor.props.shading?.fill).toBe('EEEEEE');
    expect(cont.props.shading).toBeUndefined();
  });

  it('cProps 與 pProps/rProps 同時存在時、三者各自獨立套用', () => {
    const table = makeTable([makeRow([makeCell([makeParagraph('h')], 0)])], 1);
    const cond = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >([
      ['firstRow', {
        pProps: { alignment: 'center' },
        rProps: { bold: true },
        cProps: { shading: { fill: 'DEEAF6' }, vAlign: 'center' },
      }],
    ]);
    const style = makeStyleEntry(undefined, undefined, cond);
    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });

    const cell = table.rows[0].cells[0];
    expect(cell.props.shading?.fill).toBe('DEEAF6');
    expect(cell.props.vAlign).toBe('center');
    expect(cell.content[0].props.alignment).toBe('center');
    expect((cell.content[0].runs[0] as { props: RunProps }).props.bold).toBe(true);
  });
});
