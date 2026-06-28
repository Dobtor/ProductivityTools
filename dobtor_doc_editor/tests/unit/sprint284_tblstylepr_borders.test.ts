/**
 * Sprint 284 — Phase 1 optional bucket 3/6：`<w:tblStylePr>` row + border 條件樣式
 *
 * 揭發 gap：types.ts:943 註明「`w:tcBorders` 需與 BorderConflictResolver 互動、複雜度高」
 * 而 defer。本 sprint 開 borders（user 指定「row+border 條件樣式」）。
 *
 * 改動：
 *   1. types.ts — TableConditionalCellProps.borders?: CellBorders
 *   2. StyleResolver.parseConditionalTcPr — 讀 w:tcBorders + inline parseConditionalCellBorders
 *   3. TableStyleApplicator.mergeCellConditionalProps — per-side 合併
 *   4. TableStyleApplicator.applyConditionalCellProps — explicit cell border 優先、per-side 補入
 */
import { describe, expect, it } from 'vitest';
import { DOMParser } from '@xmldom/xmldom';

import { StyleResolver } from '../../static/src/core/ooxml/styles/StyleResolver';
import { applyTableStyle, DEFAULT_TBL_LOOK } from '../../static/src/core/ooxml/styles/TableStyleApplicator';
import type {
  StyleEntry,
  TableConditionalType,
  TableConditionalCellProps,
  CellNode,
  RowNode,
  TableNode,
  ParagraphNode,
  CellBorders,
  BorderDef,
} from '../../static/src/core/ooxml/ast/types';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function makeParagraph(text = ''): ParagraphNode {
  return { type: 'paragraph', props: {}, runs: text ? [{ type: 'run', text, props: {} }] : [] };
}

function makeCell(gridCol: number, gridSpan = 1, props: CellNode['props'] = {}): CellNode {
  return { type: 'cell', gridCol, gridSpan, rowSpan: 1, isContinuation: false, content: [makeParagraph('x')], props };
}

function makeRow(cells: CellNode[]): RowNode {
  return { type: 'row', cells, props: { isHeader: false, cantSplit: false } };
}

function makeTable(rows: RowNode[], cols: number, styleId?: string): TableNode {
  const grid = Array<number>(cols).fill(50);
  const out: TableNode = { type: 'table', grid, rows, props: {} };
  if (styleId) out.styleId = styleId;
  return out;
}

function makeStyleEntry(cond: Map<TableConditionalType, { cProps: TableConditionalCellProps }>): StyleEntry {
  return { conditional: cond };
}

function expectBorder(b: BorderDef | undefined, color: string, widthPt: number): void {
  expect(b).toBeDefined();
  expect(b!.color).toBe(color);
  expect(b!.width).toBe(widthPt);
}

describe('Sprint 284 — StyleResolver parseConditionalTcPr w:tcBorders', () => {
  function buildStylesXml(tblStyleId: string, conditionalType: string, tcBorderXml: string): string {
    return `<?xml version="1.0"?>
      <w:styles ${W_NS}>
        <w:style w:type="table" w:styleId="${tblStyleId}">
          <w:name w:val="${tblStyleId}"/>
          <w:tblStylePr w:type="${conditionalType}">
            <w:tcPr>${tcBorderXml}</w:tcPr>
          </w:tblStylePr>
        </w:style>
      </w:styles>`;
  }

  it('firstRow 帶 w:tcBorders top + bottom → conditional cProps.borders 讀到 2 side', () => {
    const xml = buildStylesXml('GridTable1', 'firstRow', `
      <w:tcBorders>
        <w:top w:val="single" w:sz="12" w:color="FF0000"/>
        <w:bottom w:val="single" w:sz="8" w:color="000000"/>
      </w:tcBorders>
    `);
    const resolver = new StyleResolver();
    const styleMap = resolver.resolve(xml);

    const entry = styleMap.get('GridTable1');
    expect(entry).toBeDefined();
    const first = entry!.conditional?.get('firstRow');
    expect(first?.cProps?.borders).toBeDefined();
    expectBorder(first!.cProps!.borders!.top, 'FF0000', 1.5);  // sz=12 half-pt = 1.5pt
    expectBorder(first!.cProps!.borders!.bottom, '000000', 1.0); // sz=8 half-pt = 1pt
    expect(first!.cProps!.borders!.left).toBeUndefined();
  });

  it('lastRow w:tcBorders left + right + insideH 三 side 全讀', () => {
    const xml = buildStylesXml('GridTable1', 'lastRow', `
      <w:tcBorders>
        <w:left w:val="single" w:sz="4" w:color="111111"/>
        <w:right w:val="single" w:sz="4" w:color="222222"/>
        <w:insideH w:val="single" w:sz="4" w:color="333333"/>
      </w:tcBorders>
    `);
    const styleMap = new StyleResolver().resolve(xml);
    const c = styleMap.get('GridTable1')!.conditional!.get('lastRow')!.cProps!.borders!;
    expectBorder(c.left, '111111', 0.5);
    expectBorder(c.right, '222222', 0.5);
    expectBorder(c.insideH, '333333', 0.5);
    expect(c.top).toBeUndefined();
  });

  it('w:start / w:end alias 視同 left / right', () => {
    const xml = buildStylesXml('GridTable1', 'firstRow', `
      <w:tcBorders>
        <w:start w:val="single" w:sz="4" w:color="AAAAAA"/>
        <w:end w:val="single" w:sz="4" w:color="BBBBBB"/>
      </w:tcBorders>
    `);
    const c = new StyleResolver().resolve(xml).get('GridTable1')!
      .conditional!.get('firstRow')!.cProps!.borders!;
    expectBorder(c.left, 'AAAAAA', 0.5);
    expectBorder(c.right, 'BBBBBB', 0.5);
  });

  it('全空 w:tcBorders → cProps.borders undefined、且 tblStylePr 整體不掛 conditional entry（紀律 #21）', () => {
    const xml = buildStylesXml('GridTable1', 'firstRow', `<w:tcBorders/>`);
    const entry = new StyleResolver().resolve(xml).get('GridTable1')!;
    // 整個 tblStylePr 因 cPr 空、無 pPr/rPr → conditional 整個 undefined
    expect(entry.conditional).toBeUndefined();
  });

  it('shading + borders 並存：兩 key 同 cProps、互不影響', () => {
    const xml = buildStylesXml('GridTable1', 'firstRow', `
      <w:shd w:fill="EEEEEE"/>
      <w:tcBorders>
        <w:top w:val="single" w:sz="4" w:color="FF0000"/>
      </w:tcBorders>
    `);
    const c = new StyleResolver().resolve(xml).get('GridTable1')!
      .conditional!.get('firstRow')!.cProps!;
    expect(c.shading?.fill).toBe('EEEEEE');
    expectBorder(c.borders?.top, 'FF0000', 0.5);
  });
});

describe('Sprint 284 — TableStyleApplicator borders apply', () => {
  function buildConditional(
    type: TableConditionalType,
    borders: CellBorders,
  ): Map<TableConditionalType, { cProps: TableConditionalCellProps }> {
    return new Map([[type, { cProps: { borders } }]]);
  }

  const RED_TOP: BorderDef = { width: 1.5, color: 'FF0000', style: 'single' };
  const BLUE_BOTTOM: BorderDef = { width: 1.0, color: '0000FF', style: 'single' };

  it('firstRow 條件 borders top → 第一列 cell.props.borders.top 寫入', () => {
    const table = makeTable([
      makeRow([makeCell(0)]),
      makeRow([makeCell(0)]),
    ], 1);
    const style = makeStyleEntry(buildConditional('firstRow', { top: RED_TOP }));

    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });
    expectBorder(table.rows[0].cells[0].props.borders?.top, 'FF0000', 1.5);
    // 非首列不套
    expect(table.rows[1].cells[0].props.borders).toBeUndefined();
  });

  it('lastRow 條件 borders bottom → 末列 cell.props.borders.bottom 寫入', () => {
    const table = makeTable([
      makeRow([makeCell(0)]),
      makeRow([makeCell(0)]),
      makeRow([makeCell(0)]),
    ], 1);
    const style = makeStyleEntry(buildConditional('lastRow', { bottom: BLUE_BOTTOM }));

    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: false, lastRow: true });
    expect(table.rows[0].cells[0].props.borders).toBeUndefined();
    expect(table.rows[1].cells[0].props.borders).toBeUndefined();
    expectBorder(table.rows[2].cells[0].props.borders?.bottom, '0000FF', 1.0);
  });

  it('band1Horz 條件 borders insideH → odd band 列套用、even / firstRow 不套', () => {
    const table = makeTable([
      makeRow([makeCell(0)]),  // row 0 = firstRow（不算 band）
      makeRow([makeCell(0)]),  // row 1 = band1（odd）
      makeRow([makeCell(0)]),  // row 2 = band2（even）
      makeRow([makeCell(0)]),  // row 3 = band1
    ], 1);
    const INSIDE: BorderDef = { width: 0.5, color: '888888', style: 'single' };
    const style = makeStyleEntry(buildConditional('band1Horz', { insideH: INSIDE }));

    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });
    expect(table.rows[0].cells[0].props.borders).toBeUndefined();
    expectBorder(table.rows[1].cells[0].props.borders?.insideH, '888888', 0.5);
    expect(table.rows[2].cells[0].props.borders).toBeUndefined();
    expectBorder(table.rows[3].cells[0].props.borders?.insideH, '888888', 0.5);
  });

  it('Explicit cell border 優先：條件樣式 top + cell explicit top → 保留 explicit', () => {
    const explicitBorder: BorderDef = { width: 3.0, color: 'EXPLICIT', style: 'double' };
    const cellWithBorder = makeCell(0, 1, { borders: { top: explicitBorder } });
    const table = makeTable([makeRow([cellWithBorder])], 1);
    const style = makeStyleEntry(buildConditional('firstRow', { top: RED_TOP }));

    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });
    // explicit top 保留
    expect(table.rows[0].cells[0].props.borders?.top).toEqual(explicitBorder);
  });

  it('Per-side 補入：explicit top 存在、條件 bottom + top → top 保留 explicit、bottom 補條件', () => {
    const explicitTop: BorderDef = { width: 3.0, color: 'EXPLICIT', style: 'double' };
    const cellWithTop = makeCell(0, 1, { borders: { top: explicitTop } });
    const table = makeTable([makeRow([cellWithTop])], 1);
    const style = makeStyleEntry(buildConditional('firstRow', {
      top: RED_TOP,
      bottom: BLUE_BOTTOM,
    }));

    applyTableStyle(table, style, { ...DEFAULT_TBL_LOOK, firstRow: true });
    expect(table.rows[0].cells[0].props.borders?.top).toEqual(explicitTop);  // explicit 留
    expectBorder(table.rows[0].cells[0].props.borders?.bottom, '0000FF', 1.0);  // condition 補
  });
});
