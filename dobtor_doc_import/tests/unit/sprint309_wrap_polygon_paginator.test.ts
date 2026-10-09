/**
 * Sprint 309 — ③ deeper³：WrapPolygonPaginator helpers。
 *
 * Sprint 296/298/304 polygon math + LineBreaker + render；本 sprint 補
 * 跨頁時 polygon split + shift to per-page local coords。
 *
 * 紀律 #18 scope-down：不接 Paginator real path（紀律 #21）；只裁 Y 範圍。
 */
import { describe, expect, it } from 'vitest';

import {
  splitPolygonAcrossPages,
  clipPolygonToYRange,
  shiftPolygonForPage,
  preparePolygonForPages,
} from '../../static/src/core/ooxml/layout/wrap_polygon_paginator';
import type { PageYRange } from '../../static/src/core/ooxml/layout/wrap_polygon_paginator';

// 矩形 polygon：(0,100)-(100,200) — Y 範圍 [100, 200]
const RECT_POLY = [
  { x: 0, y: 100 },
  { x: 100, y: 100 },
  { x: 100, y: 200 },
  { x: 0, y: 200 },
];

// ── clipPolygonToYRange ──────────────────────────────────────────────────

describe('Sprint 309 — clipPolygonToYRange', () => {
  it('完全在範圍內 → 原 polygon', () => {
    const out = clipPolygonToYRange(RECT_POLY, 0, 300);
    expect(out).toHaveLength(4);
    expect(out[0]).toEqual({ x: 0, y: 100 });
  });

  it('完全在範圍外（範圍在 polygon 下方）→ 空', () => {
    expect(clipPolygonToYRange(RECT_POLY, 300, 400)).toEqual([]);
  });

  it('完全在範圍外（範圍在 polygon 上方）→ 空', () => {
    expect(clipPolygonToYRange(RECT_POLY, 0, 50)).toEqual([]);
  });

  it('部分跨界（範圍切過 polygon 上半）→ 裁出 [100, 150] 子矩形', () => {
    const out = clipPolygonToYRange(RECT_POLY, 0, 150);
    // 期望 polygon Y 範圍 [100, 150]
    const ys = out.map((p) => p.y).sort((a, b) => a - b);
    expect(ys[0]).toBe(100);
    expect(ys[ys.length - 1]).toBe(150);
  });

  it('部分跨界（範圍切過 polygon 下半）→ 裁出 [150, 200] 子矩形', () => {
    const out = clipPolygonToYRange(RECT_POLY, 150, 300);
    const ys = out.map((p) => p.y).sort((a, b) => a - b);
    expect(ys[0]).toBe(150);
    expect(ys[ys.length - 1]).toBe(200);
  });

  it('空 polygon → 空', () => {
    expect(clipPolygonToYRange([], 0, 100)).toEqual([]);
  });
});

// ── shiftPolygonForPage ───────────────────────────────────────────────────

describe('Sprint 309 — shiftPolygonForPage', () => {
  it('Y 平移到 page-local', () => {
    const out = shiftPolygonForPage(RECT_POLY, 50);
    expect(out).toEqual([
      { x: 0, y: 50 },
      { x: 100, y: 50 },
      { x: 100, y: 150 },
      { x: 0, y: 150 },
    ]);
  });

  it('X 不變', () => {
    const out = shiftPolygonForPage(RECT_POLY, 30);
    expect(out[0].x).toBe(0);
    expect(out[1].x).toBe(100);
  });
});

// ── splitPolygonAcrossPages ─────────────────────────────────────────────

describe('Sprint 309 — splitPolygonAcrossPages', () => {
  it('polygon 全在第 1 頁 → 第 2 頁空', () => {
    const pages: PageYRange[] = [
      { startY: 0, endY: 300 },
      { startY: 300, endY: 600 },
    ];
    const out = splitPolygonAcrossPages(RECT_POLY, pages);
    expect(out[0]).toHaveLength(4);
    expect(out[1]).toEqual([]);
  });

  it('polygon 跨第 1/2 頁 → 各頁有子 polygon', () => {
    // polygon Y [100, 200]，page1=[0,150], page2=[150,300] → 各得 50pt Y range
    const pages: PageYRange[] = [
      { startY: 0, endY: 150 },
      { startY: 150, endY: 300 },
    ];
    const out = splitPolygonAcrossPages(RECT_POLY, pages);
    expect(out[0].length).toBeGreaterThan(0);
    expect(out[1].length).toBeGreaterThan(0);
    // page1 子 polygon Y max <= 150
    expect(Math.max(...out[0].map((p) => p.y))).toBe(150);
    // page2 子 polygon Y min >= 150
    expect(Math.min(...out[1].map((p) => p.y))).toBe(150);
  });
});

// ── preparePolygonForPages 整合 ─────────────────────────────────────────

describe('Sprint 309 — preparePolygonForPages 整合', () => {
  it('split + shift 一次完成', () => {
    const pages: PageYRange[] = [
      { startY: 0, endY: 150 },
      { startY: 150, endY: 300 },
    ];
    const out = preparePolygonForPages(RECT_POLY, pages);
    // page 1: 原 Y [100, 150] → shift -0 → [100, 150]
    expect(Math.min(...out[0].map((p) => p.y))).toBe(100);
    expect(Math.max(...out[0].map((p) => p.y))).toBe(150);
    // page 2: 原 Y [150, 200] → shift -150 → [0, 50]
    expect(Math.min(...out[1].map((p) => p.y))).toBe(0);
    expect(Math.max(...out[1].map((p) => p.y))).toBe(50);
  });

  it('polygon 完全在某頁內 → 該頁子 polygon 為原 + shift、其他頁空', () => {
    const pages: PageYRange[] = [
      { startY: 0, endY: 300 },
      { startY: 300, endY: 600 },
    ];
    const out = preparePolygonForPages(RECT_POLY, pages);
    expect(out[0]).toHaveLength(4);
    expect(out[1]).toEqual([]);
  });
});

// ── 三角形 polygon 跨頁 ────────────────────────────────────────────────

describe('Sprint 309 — 非矩形 polygon 跨頁', () => {
  it('三角形 (0,0)-(100,200)-(200,0)、切過中間 y=100', () => {
    const tri = [
      { x: 0, y: 0 },
      { x: 100, y: 200 },
      { x: 200, y: 0 },
    ];
    const out = clipPolygonToYRange(tri, 0, 100);
    // 期望仍 valid polygon、上邊界 Y=100、底邊不變
    const ys = out.map((p) => p.y);
    expect(Math.max(...ys)).toBe(100);
    expect(Math.min(...ys)).toBe(0);
  });
});
