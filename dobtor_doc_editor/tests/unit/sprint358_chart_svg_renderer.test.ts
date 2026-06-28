/**
 * Sprint 358 — ChartSvgRenderer：bar/bar3D ChartNode → SVG。
 *
 * 真實資料 fidelity audit（2026-05-29）後補：圖表不再只剩線性文字、可渲成 SVG image。
 * 紀律 #18：只畫長條圖（真實 corpus 8/8 為 bar/bar3D）、其他型別回 null。
 */
import { describe, expect, it } from 'vitest';

import {
  renderChartSvg,
  svgToDataUrl,
  escapeXml,
} from '../../static/src/core/ooxml/chart/ChartSvgRenderer';
import type { ChartNode } from '../../static/src/core/ooxml/ast/types';

const mkChart = (over: Partial<ChartNode> = {}): ChartNode => ({
  rId: 'rId1',
  chartType: 'barChart',
  series: [{ categories: ['A', 'B', 'C'], values: [10, 20, 30] }],
  ...over,
});

// ── escapeXml ──────────────────────────────────────────────────────

describe('Sprint 358 — escapeXml', () => {
  it('轉義 & < > " \'', () => {
    expect(escapeXml('a&b<c>d"e\'f')).toBe('a&amp;b&lt;c&gt;d&quot;e&apos;f');
  });
  it('純文字不變', () => {
    expect(escapeXml('磺港溪')).toBe('磺港溪');
  });
});

// ── svgToDataUrl ───────────────────────────────────────────────────

describe('Sprint 358 — svgToDataUrl', () => {
  it('產生 utf-8 data URL', () => {
    const url = svgToDataUrl('<svg></svg>');
    expect(url.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
    expect(decodeURIComponent(url.split(',')[1])).toBe('<svg></svg>');
  });
});

// ── renderChartSvg：型別守門 ───────────────────────────────────────

describe('Sprint 358 — renderChartSvg 型別守門', () => {
  it('barChart → 回 SVG', () => {
    const svg = renderChartSvg(mkChart());
    expect(svg).not.toBeNull();
    expect(svg!.startsWith('<svg')).toBe(true);
    expect(svg!.includes('</svg>')).toBe(true);
  });

  it('bar3DChart → 回 SVG（當平面 bar 畫）', () => {
    expect(renderChartSvg(mkChart({ chartType: 'bar3DChart' }))).not.toBeNull();
  });

  it('pieChart / lineChart → null（交給文字 fallback）', () => {
    expect(renderChartSvg(mkChart({ chartType: 'pieChart' }))).toBeNull();
    expect(renderChartSvg(mkChart({ chartType: 'lineChart' }))).toBeNull();
  });

  it('無數列 → null', () => {
    expect(renderChartSvg(mkChart({ series: [] }))).toBeNull();
  });

  it('數列全 null 值 → null', () => {
    expect(
      renderChartSvg(mkChart({ series: [{ categories: ['A'], values: [null] }] })),
    ).toBeNull();
  });

  it('無類別 → null', () => {
    expect(
      renderChartSvg(mkChart({ series: [{ categories: [], values: [] }] })),
    ).toBeNull();
  });
});

// ── renderChartSvg：內容 ───────────────────────────────────────────

describe('Sprint 358 — renderChartSvg 內容', () => {
  it('含標題文字（轉義）', () => {
    const svg = renderChartSvg(mkChart({ title: '自主檢查<統計>' }))!;
    expect(svg).toContain('自主檢查&lt;統計&gt;');
  });

  it('每類別每數列產一個 <rect> bar', () => {
    // 1 數列 × 3 類別 = 3 bar；+ 背景 rect 1 + Y 格線無 rect
    const svg = renderChartSvg(mkChart())!;
    const rects = svg.match(/<rect /g) ?? [];
    // 背景 1 + 3 bars = 至少 4
    expect(rects.length).toBeGreaterThanOrEqual(4);
  });

  it('多數列 + name → 含圖例文字', () => {
    const svg = renderChartSvg(
      mkChart({
        series: [
          { name: '計畫', categories: ['A', 'B'], values: [5, 8] },
          { name: '實際', categories: ['A', 'B'], values: [4, 7] },
        ],
      }),
    )!;
    expect(svg).toContain('計畫');
    expect(svg).toContain('實際');
  });

  it('類別標籤過長被截斷（含 …）', () => {
    const longCat = '一二三四五六七八九十';
    const svg = renderChartSvg(
      mkChart({ series: [{ categories: [longCat], values: [1] }] }),
    )!;
    expect(svg).toContain('…');
  });

  it('null 值的 bar 不渲染（稀疏數列）', () => {
    const svg = renderChartSvg(
      mkChart({ series: [{ categories: ['A', 'B', 'C'], values: [10, null, 30] }] }),
    )!;
    // 只有 2 個 data bar（A、C）+ 背景 1 = 3 rect（不含 null 的 B）
    const rects = svg.match(/<rect /g) ?? [];
    expect(rects.length).toBe(3);
  });

  it('自訂尺寸帶入 viewBox', () => {
    const svg = renderChartSvg(mkChart(), { width: 800, height: 400 })!;
    expect(svg).toContain('width="800"');
    expect(svg).toContain('height="400"');
  });
});
