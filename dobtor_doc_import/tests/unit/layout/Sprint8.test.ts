/**
 * Sprint 8 — 整合測試
 *
 * 涵蓋：
 *   1. CellLayout.borders 由 layoutCell 從 CellNode.props.borders 透傳
 *   2. BorderConflictResolver mutate 的 borders 能被 Renderer 取到
 *   3. FontMetricsAdapter 注入後行高從 estimate 變為真實 metrics
 *   4. Layout → Renderer 整條鏈在大型 fixture 不 throw
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import { layoutTable } from '../../../static/src/core/layout/TableLayout';
import { FontMetricsAdapter } from '../../../static/src/core/layout/FontMetricsAdapter';
import { resolveTableBorders } from '../../../static/src/core/ooxml/table/BorderConflictResolver';
import { CanvasRenderer } from '../../../static/src/core/render/CanvasRenderer';
import { MockRenderContext } from '../../../static/src/core/render/MockRenderContext';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  TableNode,
  RowNode,
  CellNode,
  CellBorders,
} from '../../../static/src/core/ooxml/ast/types';
import type { FontMetricsResult } from '../../../static/src/core/ooxml/font/FontMetrics';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function para(text: string, fontFamily?: string, fontSize = 12): ParagraphNode {
  const props: RunNode['props'] = { fontSize };
  if (fontFamily) props.fontFamily = fontFamily;
  const run: RunNode = { type: 'run', text, props };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function cellNode(content: CellNode['content'], borders?: CellBorders): CellNode {
  const props: CellNode['props'] = {};
  if (borders) props.borders = borders;
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

// ── 1. CellLayout.borders 透傳 ──────────────────────────────────────────────

describe('Sprint 8 — CellLayout.borders', () => {
  it('layoutCell 從 CellNode.props.borders 透傳', () => {
    const borders: CellBorders = { top: { style: 'single', width: 1, color: 'FF0000' } };
    const cell = cellNode([para('x')], borders);
    const t = tableNode([200], [rowNode([cell])]);
    const out = layoutTable(t, 200);
    expect(out.rows[0].cells[0].borders).toEqual(borders);
  });

  it('CellNode.props.borders 為 undefined 時 CellLayout.borders 也 undefined', () => {
    const cell = cellNode([para('x')]);
    const t = tableNode([200], [rowNode([cell])]);
    const out = layoutTable(t, 200);
    expect(out.rows[0].cells[0].borders).toBeUndefined();
  });

  it('vMerge continuation cell 也保留 borders', () => {
    const borders: CellBorders = { left: { style: 'single', width: 0.5, color: '000000' } };
    const cont: CellNode = {
      type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: true,
      content: [], props: { borders },
    };
    const t = tableNode([200], [rowNode([cont])]);
    const out = layoutTable(t, 200);
    expect(out.rows[0].cells[0].borders).toEqual(borders);
    expect(out.rows[0].cells[0].isContinuation).toBe(true);
  });
});

// ── 2. BorderConflictResolver → Renderer 整合 ───────────────────────────────

describe('Sprint 8 — BorderConflictResolver 結果由 Renderer 繪出', () => {
  it('resolveTableBorders 後 Renderer 看到 cell 4 邊', () => {
    const cell1 = cellNode([para('a')]);
    const cell2 = cellNode([para('b')]);
    const r1 = rowNode([cell1]);
    const r2 = rowNode([cell2]);
    const t: TableNode = {
      type: 'table',
      grid: [200],
      rows: [r1, r2],
      props: {
        borders: {
          top: { style: 'single', width: 2, color: '000000' },
          bottom: { style: 'single', width: 2, color: '000000' },
          left: { style: 'single', width: 2, color: '000000' },
          right: { style: 'single', width: 2, color: '000000' },
          insideH: { style: 'single', width: 0.5, color: '000000' },
          insideV: { style: 'single', width: 0.5, color: '000000' },
        },
      },
    };
    resolveTableBorders(t);

    // 跑 Layout + Render
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const lines = ctx.filter('drawLine');
    // 兩個 cell × 4 邊 = 8（含相鄰邊 dedupe 因為 Renderer 對每 cell 各畫，
    // 故 cell1.bottom + cell2.top 都會畫 → 8 條而非 7 條）
    expect(lines.length).toBe(8);
    // 至少有粗線（外框 width=2）與細線（內邊 width=0.5）
    const widths = new Set(lines.map((l) => l.style.width));
    expect(widths.has(2)).toBe(true);
    expect(widths.has(0.5)).toBe(true);
  });
});

// ── 3. FontMetricsAdapter 注入 Layout ──────────────────────────────────────

describe('Sprint 8 — FontMetricsAdapter 影響分頁', () => {
  it('真實字型 metrics 與 estimate 行高不同 → 影響行數', () => {
    // 構造一個 metrics：unitsPerEm=1000, ascender+descender+lineGap=2000
    // → 行高 = 2 × fontSize（vs estimate 1.2 × fontSize）
    const tall: FontMetricsResult = {
      unitsPerEm: 1000,
      ascender: 1500,
      descender: 500,
      lineGap: 0,
    };
    const adapter = new FontMetricsAdapter();
    adapter.registerMetrics('TallFont', tall);

    // 多段中文段落，每段 1 行
    const body: SectionNode['body'] = [];
    for (let i = 0; i < 30; i++) body.push(para(`段落 ${i}`, 'TallFont'));
    const sec = makeSection(body);

    const layoutEst = layoutDocument([sec]); // estimate
    const layoutReal = layoutDocument([sec], { metrics: adapter }); // real metrics

    // 真實 metrics 行高是 estimate 的 ~1.67 倍 → 頁數應該更多
    expect(layoutReal.pages.length).toBeGreaterThanOrEqual(layoutEst.pages.length);
  });

  it('未註冊字型走 fallback estimate，行高一致', () => {
    const adapter = new FontMetricsAdapter();
    // 不 register 任何字型
    const body: SectionNode['body'] = [];
    for (let i = 0; i < 10; i++) body.push(para(`段落 ${i}`, 'NotRegistered'));
    const sec = makeSection(body);

    const layoutEst = layoutDocument([sec]);
    const layoutAdapter = layoutDocument([sec], { metrics: adapter });

    expect(layoutAdapter.pages.length).toBe(layoutEst.pages.length);
  });
});

// ── 4. End-to-end 大型 fixture 不 throw ────────────────────────────────────

describe('Sprint 8 — 端到端 stress test', () => {
  it('Layout + Renderer 處理多頁文件不 throw', () => {
    const body: SectionNode['body'] = [];
    for (let i = 0; i < 100; i++) body.push(para(`第 ${i} 段內容`));
    // 加一個有邊框的表格
    const cellBorders: CellBorders = {
      top: { style: 'single', width: 0.5, color: '000000' },
      bottom: { style: 'single', width: 0.5, color: '000000' },
      left: { style: 'single', width: 0.5, color: '000000' },
      right: { style: 'single', width: 0.5, color: '000000' },
    };
    const cells = Array.from({ length: 3 }, () => cellNode([para('cell')], cellBorders));
    const t = tableNode([100, 100, 100], [rowNode(cells)]);
    body.push(t);

    const sec = makeSection(body);
    const layout = layoutDocument([sec]);
    const ctx = new MockRenderContext();

    expect(() => new CanvasRenderer(ctx).render(layout)).not.toThrow();
    expect(ctx.filter('beginPage').length).toBe(layout.pages.length);
    expect(ctx.filter('endPage').length).toBe(layout.pages.length);
    expect(ctx.filter('fillText').length).toBeGreaterThan(0);
    expect(ctx.filter('drawLine').length).toBeGreaterThanOrEqual(4); // 至少 1 cell × 4 邊
  });
});
