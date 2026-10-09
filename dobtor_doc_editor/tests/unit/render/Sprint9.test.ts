/**
 * Sprint 9 — CanvasRenderer 升級：cell.blocks 視覺順序 + shading + 文字裝飾
 *
 * 涵蓋：
 *   1. CellLayout.shading 從 CellNode.props.shading 透傳
 *   2. cell.blocks 走訪：paragraph + 巢狀表 + paragraph 順序保留
 *   3. cell shading：fillRect 在 cell 內容前送出
 *   4. paragraph shading：fillRect 在 line 範圍送出
 *   5. highlight：fillRect 在 box 文字前送出
 *   6. underline：drawLine 在 baseline 下方
 *   7. strike：drawLine 在 fontSize × 0.3 上方
 *   8. drawShading=false / drawTextDecorations=false 開關
 */

import { describe, expect, it } from 'vitest';
import { CanvasRenderer } from '../../../static/src/core/render/CanvasRenderer';
import { MockRenderContext } from '../../../static/src/core/render/MockRenderContext';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import { layoutTable } from '../../../static/src/core/layout/TableLayout';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  TableNode,
  RowNode,
  CellNode,
  CellBorders,
  HexColor,
} from '../../../static/src/core/ooxml/ast/types';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function para(text: string, runProps: Partial<RunNode['props']> = {}): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12, ...runProps } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function paraWithShading(text: string, fill: HexColor): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return {
    type: 'paragraph',
    props: { shading: { fill } },
    runs: [run],
  };
}

function cellNode(
  content: CellNode['content'],
  opts: { borders?: CellBorders; shading?: CellNode['props']['shading'] } = {},
): CellNode {
  const props: CellNode['props'] = {};
  if (opts.borders) props.borders = opts.borders;
  if (opts.shading) props.shading = opts.shading;
  return {
    type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false, content, props,
  };
}

function rowNode(cells: CellNode[]): RowNode {
  return { type: 'row', cells, props: { isHeader: false, cantSplit: false } };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return { type: 'table', grid, rows, props: {} };
}

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section', page: A4, margins: MARGINS,
    headerRefs: {}, footerRefs: {}, titlePage: false, evenAndOddHeaders: false, body,
  };
}

// ── 1. CellLayout.shading 透傳 ──────────────────────────────────────────────

describe('Sprint 9 — CellLayout.shading 透傳', () => {
  it('layoutCell 從 cell.props.shading 透傳', () => {
    const cell = cellNode([para('x')], { shading: { fill: 'FFFF00' } });
    const t = tableNode([200], [rowNode([cell])]);
    const out = layoutTable(t, 200);
    expect(out.rows[0].cells[0].shading).toEqual({ fill: 'FFFF00' });
  });

  it('無 shading 時 CellLayout.shading undefined', () => {
    const cell = cellNode([para('x')]);
    const t = tableNode([200], [rowNode([cell])]);
    const out = layoutTable(t, 200);
    expect(out.rows[0].cells[0].shading).toBeUndefined();
  });
});

// ── 2. cell.blocks 視覺順序 ────────────────────────────────────────────────

describe('Sprint 9 — cell.blocks 視覺順序', () => {
  it('paragraph + nested table + paragraph 三 block 順序保留', () => {
    const innerCell = cellNode([para('INNER')]);
    const innerRow = rowNode([innerCell]);
    const innerTable = tableNode([100], [innerRow]);
    const outerCell = cellNode([para('BEFORE'), innerTable, para('AFTER')]);
    const outerRow = rowNode([outerCell]);
    const outerTable = tableNode([200], [outerRow]);
    const sec = makeSection([outerTable]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const texts = ctx.filter('fillText').map((op) => op.text);
    const before = texts.findIndex((t) => t.includes('BEFORE'));
    const inner = texts.findIndex((t) => t.includes('INNER'));
    const after = texts.findIndex((t) => t.includes('AFTER'));
    expect(before).toBeGreaterThanOrEqual(0);
    expect(inner).toBeGreaterThan(before);
    expect(after).toBeGreaterThan(inner);
  });

  it('巢狀表內 cell 邊框也會被畫', () => {
    const blackBorder: CellBorders = {
      top: { style: 'single', width: 0.5, color: '000000' },
      bottom: { style: 'single', width: 0.5, color: '000000' },
      left: { style: 'single', width: 0.5, color: '000000' },
      right: { style: 'single', width: 0.5, color: '000000' },
    };
    const innerCell = cellNode([para('inner')], { borders: blackBorder });
    const innerTable = tableNode([100], [rowNode([innerCell])]);
    const outerCell = cellNode([innerTable]);
    const outerTable = tableNode([200], [rowNode([outerCell])]);
    const sec = makeSection([outerTable]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBe(4); // inner cell 4 邊
  });
});

// ── 3. Cell shading ────────────────────────────────────────────────────────

describe('Sprint 9 — cell shading', () => {
  it('cell.shading.fill 觸發 fillRect', () => {
    const cell = cellNode([para('x')], { shading: { fill: 'FFFF00' } });
    const t = tableNode([200], [rowNode([cell])]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const fills = ctx.filter('fillRect');
    // 一個是頁面背景白色、一個是 cell 黃色
    const yellow = fills.filter((f) => f.color.toUpperCase() === 'FFFF00');
    expect(yellow.length).toBe(1);
  });

  it('drawShading=false 不畫 cell 背景', () => {
    const cell = cellNode([para('x')], { shading: { fill: 'FFFF00' } });
    const t = tableNode([200], [rowNode([cell])]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { drawShading: false }).render(layoutDocument([sec]));

    const yellow = ctx.filter('fillRect').filter((f) => f.color.toUpperCase() === 'FFFF00');
    expect(yellow.length).toBe(0);
  });
});

// ── 4. Paragraph shading ──────────────────────────────────────────────────

describe('Sprint 9 — paragraph shading', () => {
  it('段落 shading 觸發 fillRect', () => {
    const sec = makeSection([paraWithShading('hello', '00FF00')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const green = ctx.filter('fillRect').filter((f) => f.color.toUpperCase() === '00FF00');
    expect(green.length).toBeGreaterThanOrEqual(1);
  });
});

// ── 5. Run highlight ──────────────────────────────────────────────────────

describe('Sprint 9 — run highlight', () => {
  it('Run.highlight 觸發 box 範圍 fillRect', () => {
    const sec = makeSection([para('alert text', { highlight: 'FF00FF' })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const magenta = ctx.filter('fillRect').filter((f) => f.color.toUpperCase() === 'FF00FF');
    expect(magenta.length).toBeGreaterThanOrEqual(1);
  });
});

// ── 6 & 7. Underline / Strike ─────────────────────────────────────────────

describe('Sprint 9 — 文字裝飾線', () => {
  it('underline 在 box 下方畫一條 drawLine', () => {
    const sec = makeSection([para('underlined', { underline: 'single' })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const lines = ctx.filter('drawLine');
    expect(lines.length).toBeGreaterThanOrEqual(1);
    // Underline 是水平線（y1 === y2）
    const horizontals = lines.filter((l) => Math.abs(l.y1 - l.y2) < 0.01);
    expect(horizontals.length).toBeGreaterThanOrEqual(1);
  });

  it('underline=double 畫兩條線', () => {
    const sec = makeSection([para('double underline', { underline: 'double' })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    const lines = ctx.filter('drawLine');
    // 至少 2 條（同 box）
    expect(lines.length).toBeGreaterThanOrEqual(2);
  });

  it('underline=none 不畫', () => {
    const sec = makeSection([para('plain', { underline: 'none' })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBe(0);
  });

  it('strike 觸發水平 drawLine', () => {
    const sec = makeSection([para('crossed', { strike: true })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    const lines = ctx.filter('drawLine');
    expect(lines.length).toBeGreaterThanOrEqual(1);
  });

  it('underline + strike 同時畫', () => {
    const sec = makeSection([para('both', { underline: 'single', strike: true })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBeGreaterThanOrEqual(2);
  });

  it('drawTextDecorations=false 不畫底線/刪除線', () => {
    const sec = makeSection([para('x', { underline: 'single', strike: true })]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { drawTextDecorations: false }).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBe(0);
  });
});

// ── 8. 整合：複雜 fixture 不 throw ─────────────────────────────────────────

describe('Sprint 9 — 整合 stress', () => {
  it('shading + 巢狀 + 裝飾 同時存在不 throw', () => {
    const innerCell = cellNode([para('inner', { underline: 'single' })], { shading: { fill: 'EEEEEE' } });
    const innerTable = tableNode([80], [rowNode([innerCell])]);
    const outerCell = cellNode([
      paraWithShading('header line', 'FFFF00'),
      innerTable,
      para('footer', { highlight: 'FFA500', strike: true }),
    ], { shading: { fill: 'F0F8FF' } });
    const outerTable = tableNode([200], [rowNode([outerCell])]);
    const sec = makeSection([outerTable, para('外部段落')]);

    const ctx = new MockRenderContext();
    expect(() => new CanvasRenderer(ctx).render(layoutDocument([sec]))).not.toThrow();
    const counts = ctx.counts();
    expect(counts.beginPage).toBe(counts.endPage);
    expect(counts.fillRect).toBeGreaterThan(0);
    expect(counts.fillText).toBeGreaterThan(0);
    expect(counts.drawLine).toBeGreaterThan(0);
  });
});
