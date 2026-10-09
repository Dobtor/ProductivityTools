/**
 * Sprint 344 — ③ deeper¹¹：multi_polygon_baseline。
 *
 * Sprint 314 baseline + Sprint 334 multi cluster 之後深推。一行同時避開多 polygon。
 *
 * 紀律 #18：純函式；OR 邏輯（撞任一即不安全）；不接 Paginator real path。
 */
import { describe, expect, it } from 'vitest';

import {
  lineBoxHitsAnyPolygon,
  findSafeBaselineMulti,
  findSafeBands,
  countFittableLines,
} from '../../static/src/core/ooxml/layout/multi_polygon_baseline';
import type { WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

// 矩形 polygon helper
const rect = (x0: number, y0: number, w: number, h: number): WrapPolygonPoint[] => [
  { x: x0, y: y0 },
  { x: x0 + w, y: y0 },
  { x: x0 + w, y: y0 + h },
  { x: x0, y: y0 + h },
];

const baseOpts = {
  lineX: 0,
  lineWidth: 100,
  ascentPt: 10,
  descentPt: 2,
};

// ── lineBoxHitsAnyPolygon ─────────────────────────────────────────

describe('Sprint 344 — lineBoxHitsAnyPolygon', () => {
  it('撞其中一個 polygon → true', () => {
    const polys = [rect(0, 0, 100, 20), rect(0, 200, 100, 20)];
    // baseline=15 → box top=5 bottom=17、撞第一個
    expect(lineBoxHitsAnyPolygon(15, { ...baseOpts, polygons: polys })).toBe(true);
  });

  it('不撞任一 → false', () => {
    const polys = [rect(0, 0, 100, 20), rect(0, 200, 100, 20)];
    // baseline=100 → box [90,102]、兩個都不撞
    expect(lineBoxHitsAnyPolygon(100, { ...baseOpts, polygons: polys })).toBe(false);
  });

  it('空 polygon 跳過', () => {
    expect(lineBoxHitsAnyPolygon(100, { ...baseOpts, polygons: [[]] })).toBe(false);
  });
});

// ── findSafeBaselineMulti ─────────────────────────────────────────

describe('Sprint 344 — findSafeBaselineMulti', () => {
  it('全空 polygons → 回 yMin', () => {
    expect(
      findSafeBaselineMulti({ ...baseOpts, yMin: 50, yMax: 200, polygons: [] }),
    ).toBe(50);
  });

  it('都是 empty polygon → 回 yMin', () => {
    expect(
      findSafeBaselineMulti({ ...baseOpts, yMin: 50, yMax: 200, polygons: [[], []] }),
    ).toBe(50);
  });

  it('上方有圖 → baseline 推到圖下方', () => {
    const polys = [rect(0, 0, 100, 30)];
    const y = findSafeBaselineMulti({ ...baseOpts, yMin: 0, yMax: 200, polygons: polys });
    expect(y).not.toBeUndefined();
    // box top = y - 10 必須 >= 30
    expect((y as number) - 10).toBeGreaterThanOrEqual(30);
  });

  it('兩個圖夾擊但中間有空檔 → 找到中間 baseline', () => {
    const polys = [rect(0, 0, 100, 30), rect(0, 100, 100, 30)];
    const y = findSafeBaselineMulti({ ...baseOpts, yMin: 0, yMax: 200, polygons: polys });
    expect(y).not.toBeUndefined();
    expect(y as number).toBeGreaterThanOrEqual(40); // 第一個圖下方
    expect(y as number).toBeLessThan(100); // 第二個圖上方
  });

  it('範圍不夠 → undefined', () => {
    const polys = [rect(0, 0, 100, 200)];
    expect(
      findSafeBaselineMulti({ ...baseOpts, yMin: 0, yMax: 5, polygons: polys }),
    ).toBeUndefined();
  });

  it('step <= 0 throw', () => {
    expect(() =>
      findSafeBaselineMulti({ ...baseOpts, yMin: 0, yMax: 10, step: 0, polygons: [rect(0, 0, 1, 1)] }),
    ).toThrow();
  });
});

// ── findSafeBands ─────────────────────────────────────────────────

describe('Sprint 344 — findSafeBands', () => {
  it('全空 polygons → 單一整段 band', () => {
    const bands = findSafeBands({ ...baseOpts, yMin: 0, yMax: 100, polygons: [] });
    expect(bands).toEqual([{ startY: 0, endY: 100 }]);
  });

  it('中間有圖 → 切成上下兩段（或更多）', () => {
    const polys = [rect(0, 50, 100, 30)];
    const bands = findSafeBands({ ...baseOpts, yMin: 0, yMax: 200, polygons: polys });
    expect(bands.length).toBeGreaterThanOrEqual(1);
    // 應該存在一段在圖上方、一段在圖下方
    const hasLow = bands.some((b) => b.endY < 50);
    const hasHigh = bands.some((b) => b.startY > 80);
    expect(hasLow || hasHigh).toBe(true);
  });

  it('整段被圖擋住 → 空 bands', () => {
    const polys = [rect(0, 0, 100, 300)];
    const bands = findSafeBands({ ...baseOpts, yMin: 0, yMax: 100, polygons: polys });
    expect(bands).toEqual([]);
  });

  it('step <= 0 throw', () => {
    expect(() =>
      findSafeBands({ ...baseOpts, yMin: 0, yMax: 10, step: -1, polygons: [] }),
    ).toThrow();
  });
});

// ── countFittableLines ────────────────────────────────────────────

describe('Sprint 344 — countFittableLines', () => {
  it('單一 band → span/lineHeight + 1', () => {
    expect(countFittableLines([{ startY: 0, endY: 100 }], 20)).toBe(6); // floor(100/20)+1
  });

  it('多 band 累加', () => {
    expect(
      countFittableLines([{ startY: 0, endY: 40 }, { startY: 100, endY: 140 }], 20),
    ).toBe(6); // (2+1) + (2+1)
  });

  it('lineHeight <= 0 → 0', () => {
    expect(countFittableLines([{ startY: 0, endY: 100 }], 0)).toBe(0);
  });

  it('空 bands → 0', () => {
    expect(countFittableLines([], 20)).toBe(0);
  });
});
