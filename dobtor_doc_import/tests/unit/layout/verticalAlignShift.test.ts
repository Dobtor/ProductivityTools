/**
 * Sprint 167：computeVerticalAlignShift —— `<w:textAlignment>` 行內垂直對齊位移
 *
 * 涵蓋：
 *   - baseline / auto / undefined → 0（預設、byte-identical 保證）
 *   - 等高 box（含行內最高 box 本身）→ 0
 *   - top / center / bottom 對較矮 box 的位移方向與量
 *   - 非有限值防禦
 */

import { describe, expect, it } from 'vitest';
import { computeVerticalAlignShift } from '../../../static/src/core/layout/verticalAlignShift';

describe('computeVerticalAlignShift — 預設路徑（byte-identical 保證）', () => {
  it('baseline / auto / undefined 一律回傳 0', () => {
    expect(computeVerticalAlignShift('baseline', 12, 24)).toBe(0);
    expect(computeVerticalAlignShift('auto', 12, 24)).toBe(0);
    expect(computeVerticalAlignShift(undefined, 12, 24)).toBe(0);
  });

  it('box 等高於行內最高 box → 任何對齊都回傳 0', () => {
    for (const mode of ['top', 'center', 'bottom'] as const) {
      expect(computeVerticalAlignShift(mode, 24, 24)).toBe(0);
    }
  });

  it('行內唯一 box（自己即最高）→ 0', () => {
    expect(computeVerticalAlignShift('center', 14, 14)).toBe(0);
  });
});

describe('computeVerticalAlignShift — 混合高度 box 的位移', () => {
  // 較矮 box height 12、行內最高 24 → delta = -12
  const SHORT = 12;
  const TALL = 24;

  it('top：較矮 box 往上（負位移）= 0.8 × delta', () => {
    const shift = computeVerticalAlignShift('top', SHORT, TALL);
    expect(shift).toBeCloseTo(0.8 * (SHORT - TALL), 9); // -9.6
    expect(shift).toBeLessThan(0);
  });

  it('bottom：較矮 box 往下（正位移）= 0.2 × (TALL - SHORT)', () => {
    const shift = computeVerticalAlignShift('bottom', SHORT, TALL);
    expect(shift).toBeCloseTo(0.2 * (TALL - SHORT), 9); // +2.4
    expect(shift).toBeGreaterThan(0);
  });

  it('center：較矮 box 往上（負位移）= 0.3 × delta', () => {
    const shift = computeVerticalAlignShift('center', SHORT, TALL);
    expect(shift).toBeCloseTo(0.3 * (SHORT - TALL), 9); // -3.6
    expect(shift).toBeLessThan(0);
    // center 位移量介於 top 與 bottom 之間（絕對值）
    const top = Math.abs(computeVerticalAlignShift('top', SHORT, TALL));
    const bottom = Math.abs(computeVerticalAlignShift('bottom', SHORT, TALL));
    expect(Math.abs(shift)).toBeLessThan(top);
    expect(Math.abs(shift)).toBeGreaterThan(bottom);
  });

  it('最高 box 自身位移恆為 0（不被推離基線）', () => {
    for (const mode of ['top', 'center', 'bottom'] as const) {
      expect(computeVerticalAlignShift(mode, TALL, TALL)).toBe(0);
    }
  });

  it('位移量與高度差成正比（線性）', () => {
    const a = computeVerticalAlignShift('center', 12, 24); // delta -12
    const b = computeVerticalAlignShift('center', 18, 24); // delta -6
    expect(a).toBeCloseTo(2 * b, 9);
  });
});

describe('computeVerticalAlignShift — 防禦邊界', () => {
  it('非有限值（NaN / Infinity）→ 0', () => {
    expect(computeVerticalAlignShift('center', NaN, 24)).toBe(0);
    expect(computeVerticalAlignShift('center', 12, Infinity)).toBe(0);
  });
});
