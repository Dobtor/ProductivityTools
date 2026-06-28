/**
 * Sprint 354 — ③ deeper¹³：wrap_polygon_metrics。
 *
 * 多邊形面積 / 質心 / 周長 / 繞行方向；給 wrap region 排序 / clip 方向統一用。
 *
 * 紀律 #18：純函式幾何工具；簡單多邊形假設；不接 Layout real path。
 */
import { describe, expect, it } from 'vitest';

import {
  signedArea,
  area,
  perimeter,
  centroid,
  windingDirection,
  ensureWinding,
  computeMetrics,
} from '../../static/src/core/ooxml/layout/wrap_polygon_metrics';
import type { WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

const p = (x: number, y: number): WrapPolygonPoint => ({ x, y });

// 10x10 正方形，CCW（數學座標）
const squareCCW = [p(0, 0), p(10, 0), p(10, 10), p(0, 10)];
// 同正方形 CW
const squareCW = [p(0, 0), p(0, 10), p(10, 10), p(10, 0)];

// ── signedArea / area ──────────────────────────────────────────────

describe('Sprint 354 — signedArea / area', () => {
  it('CCW → 正面積', () => {
    expect(signedArea(squareCCW)).toBe(100);
  });

  it('CW → 負面積', () => {
    expect(signedArea(squareCW)).toBe(-100);
  });

  it('area 取絕對值', () => {
    expect(area(squareCW)).toBe(100);
  });

  it('點數 < 3 → 0', () => {
    expect(signedArea([p(0, 0), p(1, 1)])).toBe(0);
    expect(area([])).toBe(0);
  });

  it('三角形面積', () => {
    expect(area([p(0, 0), p(4, 0), p(0, 3)])).toBe(6);
  });
});

// ── perimeter ──────────────────────────────────────────────────────

describe('Sprint 354 — perimeter', () => {
  it('正方形周長 = 40', () => {
    expect(perimeter(squareCCW)).toBe(40);
  });

  it('點數 < 2 → 0', () => {
    expect(perimeter([p(0, 0)])).toBe(0);
  });

  it('直角三角形 3-4-5', () => {
    expect(perimeter([p(0, 0), p(4, 0), p(0, 3)])).toBeCloseTo(12);
  });
});

// ── centroid ───────────────────────────────────────────────────────

describe('Sprint 354 — centroid', () => {
  it('正方形質心在中心', () => {
    const c = centroid(squareCCW);
    expect(c.x).toBeCloseTo(5);
    expect(c.y).toBeCloseTo(5);
  });

  it('CW 正方形質心一樣', () => {
    const c = centroid(squareCW);
    expect(c.x).toBeCloseTo(5);
    expect(c.y).toBeCloseTo(5);
  });

  it('退化（共線）→ fallback 算術平均', () => {
    const c = centroid([p(0, 0), p(2, 0), p(4, 0)]);
    expect(c.x).toBeCloseTo(2);
    expect(c.y).toBeCloseTo(0);
  });

  it('空 → 0,0', () => {
    expect(centroid([])).toEqual({ x: 0, y: 0 });
  });

  it('三角形質心', () => {
    const c = centroid([p(0, 0), p(6, 0), p(0, 6)]);
    expect(c.x).toBeCloseTo(2);
    expect(c.y).toBeCloseTo(2);
  });
});

// ── windingDirection ───────────────────────────────────────────────

describe('Sprint 354 — windingDirection', () => {
  it('CCW', () => {
    expect(windingDirection(squareCCW)).toBe('ccw');
  });
  it('CW', () => {
    expect(windingDirection(squareCW)).toBe('cw');
  });
  it('退化 → degenerate', () => {
    expect(windingDirection([p(0, 0), p(1, 0)])).toBe('degenerate');
  });
});

// ── ensureWinding ──────────────────────────────────────────────────

describe('Sprint 354 — ensureWinding', () => {
  it('已是想要方向 → 不反轉', () => {
    const out = ensureWinding(squareCCW, 'ccw');
    expect(windingDirection(out)).toBe('ccw');
    expect(out[0]).toEqual(p(0, 0));
    expect(out[1]).toEqual(p(10, 0));
  });

  it('反方向 → 反轉', () => {
    const out = ensureWinding(squareCW, 'ccw');
    expect(windingDirection(out)).toBe('ccw');
  });

  it('退化 → 原樣 copy', () => {
    const degen = [p(0, 0), p(1, 0)];
    const out = ensureWinding(degen, 'ccw');
    expect(out).toEqual(degen);
  });

  it('不 mutate 原 array', () => {
    const orig = squareCW.map((q) => ({ ...q }));
    ensureWinding(squareCW, 'ccw');
    expect(squareCW).toEqual(orig);
  });
});

// ── computeMetrics ─────────────────────────────────────────────────

describe('Sprint 354 — computeMetrics', () => {
  it('一次算齊', () => {
    const m = computeMetrics(squareCCW);
    expect(m.area).toBe(100);
    expect(m.signedArea).toBe(100);
    expect(m.perimeter).toBe(40);
    expect(m.centroid.x).toBeCloseTo(5);
    expect(m.winding).toBe('ccw');
  });

  it('CW polygon', () => {
    const m = computeMetrics(squareCW);
    expect(m.signedArea).toBe(-100);
    expect(m.winding).toBe('cw');
  });
});
