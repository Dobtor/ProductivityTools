/**
 * Sprint 314 — ③ deeper⁴：wrap polygon baseline-aware line positioning。
 *
 * Sprint 296/298/304/309 之後深推。給 polygon 算 baseline Y 是否安全 +
 * 找下一安全 baseline。
 *
 * 紀律 #18 scope-down：不接 Paginator real path（紀律 #21）；單一 polygon。
 */
import { describe, expect, it } from 'vitest';

import {
  lineBoxFromBaseline,
  findSafeBaselineY,
  clampBaselineAvoidingPolygon,
  polygonBaselineUnsafeRange,
} from '../../static/src/core/ooxml/layout/wrap_polygon_baseline';

// 矩形 polygon：X[0,100] × Y[50,100]
const RECT_POLY = [
  { x: 0, y: 50 },
  { x: 100, y: 50 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

// ── lineBoxFromBaseline ──────────────────────────────────────────────────

describe('Sprint 314 — lineBoxFromBaseline', () => {
  it('top = baseline - ascent, bottom = baseline + descent', () => {
    const box = lineBoxFromBaseline(100, 10, 3);
    expect(box).toEqual({ top: 90, bottom: 103, height: 13 });
  });

  it('整數 baseline 與 metrics', () => {
    const box = lineBoxFromBaseline(50, 12, 4);
    expect(box.height).toBe(16);
  });
});

// ── findSafeBaselineY ───────────────────────────────────────────────────

describe('Sprint 314 — findSafeBaselineY', () => {
  it('polygon 在範圍外 → 直接回 yMin', () => {
    // polygon Y[50,100]，搜尋 baseline yMin=200、line box 在 polygon 下方
    const y = findSafeBaselineY({
      lineX: 200, lineWidth: 100,  // 在 polygon X 外
      ascentPt: 10, descentPt: 3,
      yMin: 200, yMax: 300,
      polygon: RECT_POLY,
    });
    expect(y).toBe(200);
  });

  it('空 polygon → 回 yMin（無 polygon、整段安全）', () => {
    const y = findSafeBaselineY({
      lineX: 0, lineWidth: 100,
      ascentPt: 10, descentPt: 3,
      yMin: 50, yMax: 100,
      polygon: [],
    });
    expect(y).toBe(50);
  });

  it('polygon 完全擋住搜尋範圍 → undefined', () => {
    // polygon Y[50,100]、ascent=10, descent=3
    // 搜尋 baseline [50, 80]，line box 必然落在 [40, 83] ~ [70, 113]
    // 全與 polygon Y[50,100] 撞
    const y = findSafeBaselineY({
      lineX: 0, lineWidth: 50,  // 在 polygon X 內
      ascentPt: 10, descentPt: 3,
      yMin: 50, yMax: 80,
      polygon: RECT_POLY,
    });
    expect(y).toBeUndefined();
  });

  it('搜尋範圍跨 polygon 下緣 → 找到 polygon 下方第一個安全 baseline', () => {
    // polygon Y[50,100]、ascent=10, descent=3
    // baseline >= 110 時 line box top = 100、剛好不撞（>= polygon maxY）
    const y = findSafeBaselineY({
      lineX: 0, lineWidth: 50,
      ascentPt: 10, descentPt: 3,
      yMin: 50, yMax: 200,
      polygon: RECT_POLY,
      step: 1,
    });
    // 第一條安全 baseline ≈ polygon.maxY + ascent + 1（bbox 邊界相切視為相交、需 +1pt 跳脫）
    expect(y).toBe(111);
  });

  it('step <= 0 throw', () => {
    expect(() => findSafeBaselineY({
      lineX: 0, lineWidth: 50, ascentPt: 10, descentPt: 3,
      yMin: 0, yMax: 100, polygon: RECT_POLY, step: 0,
    })).toThrow();
  });
});

// ── clampBaselineAvoidingPolygon ───────────────────────────────────────

describe('Sprint 314 — clampBaselineAvoidingPolygon', () => {
  it('目標 baseline 不撞 → 回原值', () => {
    const y = clampBaselineAvoidingPolygon(200, {
      lineX: 0, lineWidth: 50,
      ascentPt: 10, descentPt: 3,
      polygon: RECT_POLY,
      yMax: 300,
    });
    expect(y).toBe(200);
  });

  it('目標 baseline 撞 → 推到下一安全位置', () => {
    // 目標 baseline=80 line top=70 撞 polygon Y[50,100]
    const y = clampBaselineAvoidingPolygon(80, {
      lineX: 0, lineWidth: 50,
      ascentPt: 10, descentPt: 3,
      polygon: RECT_POLY,
      yMax: 200,
    });
    expect(y).toBe(111); // polygon.maxY + ascent + 1（邊界相切視為相交）
  });

  it('目標往下也找不到 → undefined', () => {
    const y = clampBaselineAvoidingPolygon(60, {
      lineX: 0, lineWidth: 50,
      ascentPt: 10, descentPt: 3,
      polygon: RECT_POLY,
      yMax: 90,  // 永遠走不出 polygon
    });
    expect(y).toBeUndefined();
  });
});

// ── polygonBaselineUnsafeRange ────────────────────────────────────────

describe('Sprint 314 — polygonBaselineUnsafeRange', () => {
  it('polygon Y[50,100] + ascent=10/descent=3 → unsafe [47, 110]', () => {
    const r = polygonBaselineUnsafeRange(RECT_POLY, 10, 3);
    expect(r).toEqual({ unsafeYStart: 47, unsafeYEnd: 110 });
  });

  it('空 polygon → null', () => {
    expect(polygonBaselineUnsafeRange([], 10, 3)).toBeNull();
  });

  it('傾斜三角形 polygon', () => {
    const tri = [{ x: 0, y: 0 }, { x: 50, y: 100 }, { x: 100, y: 0 }];
    const r = polygonBaselineUnsafeRange(tri, 10, 3);
    expect(r).toEqual({ unsafeYStart: -3, unsafeYEnd: 110 });
  });
});
