/**
 * Sprint 349 — ③ deeper¹²：wrap_polygon_simplify。
 *
 * Douglas–Peucker 多邊形簡化、減少 vertex 數提升 intersect/contains 效能。
 *
 * 紀律 #18：純函式幾何工具；不接 Layout real path。
 */
import { describe, expect, it } from 'vitest';

import {
  perpendicularDistance,
  simplifyPolygon,
  simplifyClosedPolygon,
  simplifyStats,
} from '../../static/src/core/ooxml/layout/wrap_polygon_simplify';
import type { WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

const p = (x: number, y: number): WrapPolygonPoint => ({ x, y });

// ── perpendicularDistance ─────────────────────────────────────────

describe('Sprint 349 — perpendicularDistance', () => {
  it('點在線上 → 距離 0', () => {
    expect(perpendicularDistance(p(5, 0), p(0, 0), p(10, 0))).toBeCloseTo(0);
  });

  it('點離線 → 垂距', () => {
    expect(perpendicularDistance(p(5, 3), p(0, 0), p(10, 0))).toBeCloseTo(3);
  });

  it('退化線段 a==b → 點到 a 距離', () => {
    expect(perpendicularDistance(p(3, 4), p(0, 0), p(0, 0))).toBeCloseTo(5);
  });
});

// ── simplifyPolygon ────────────────────────────────────────────────

describe('Sprint 349 — simplifyPolygon', () => {
  it('共線中間點被移除', () => {
    const line = [p(0, 0), p(5, 0), p(10, 0)];
    const out = simplifyPolygon(line, 0.1);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual(p(0, 0));
    expect(out[1]).toEqual(p(10, 0));
  });

  it('關鍵轉折保留', () => {
    const zigzag = [p(0, 0), p(5, 5), p(10, 0)];
    const out = simplifyPolygon(zigzag, 0.1);
    expect(out).toHaveLength(3); // 尖點 (5,5) 必留
  });

  it('epsilon 大 → 簡化更激進', () => {
    const pts = [p(0, 0), p(5, 1), p(10, 0)];
    // 垂距 = 1；epsilon=2 → 中間點移除
    expect(simplifyPolygon(pts, 2)).toHaveLength(2);
    // epsilon=0.5 → 中間點保留
    expect(simplifyPolygon(pts, 0.5)).toHaveLength(3);
  });

  it('epsilon <= 0 → 原樣 copy', () => {
    const pts = [p(0, 0), p(5, 5), p(10, 0)];
    expect(simplifyPolygon(pts, 0)).toEqual(pts);
    expect(simplifyPolygon(pts, -1)).toEqual(pts);
  });

  it('點數 <= 2 → 原樣 copy', () => {
    expect(simplifyPolygon([p(0, 0)], 1)).toHaveLength(1);
    expect(simplifyPolygon([p(0, 0), p(1, 1)], 1)).toHaveLength(2);
  });

  it('回的是 copy（不 mutate 原）', () => {
    const pts = [p(0, 0), p(5, 0), p(10, 0)];
    const out = simplifyPolygon(pts, 0.1);
    out[0].x = 999;
    expect(pts[0].x).toBe(0);
  });

  it('長共線串大幅縮減', () => {
    const many: WrapPolygonPoint[] = [];
    for (let i = 0; i <= 100; i++) many.push(p(i, 0));
    expect(simplifyPolygon(many, 0.1)).toHaveLength(2);
  });
});

// ── simplifyClosedPolygon ─────────────────────────────────────────

describe('Sprint 349 — simplifyClosedPolygon', () => {
  it('點數 <= 3 → 原樣', () => {
    const tri = [p(0, 0), p(10, 0), p(5, 10)];
    expect(simplifyClosedPolygon(tri, 1)).toHaveLength(3);
  });

  it('矩形邊上多餘共線點被移除', () => {
    // 矩形邊上加共線中點
    const rectExtra = [
      p(0, 0), p(5, 0), p(10, 0),
      p(10, 5), p(10, 10),
      p(5, 10), p(0, 10),
      p(0, 5),
    ];
    const out = simplifyClosedPolygon(rectExtra, 0.1);
    // 應縮到 4 角（可能含閉合重複、放寬到 <= 5）
    expect(out.length).toBeLessThanOrEqual(5);
    expect(out.length).toBeGreaterThanOrEqual(4);
  });

  it('open input 簡化後仍 open', () => {
    const open = [p(0, 0), p(5, 0), p(10, 0), p(10, 10), p(0, 10)];
    const out = simplifyClosedPolygon(open, 0.1);
    const first = out[0];
    const last = out[out.length - 1];
    // 不應強制閉合（首尾不相等）
    expect(first.x === last.x && first.y === last.y).toBe(false);
  });

  it('epsilon <= 0 → 原樣 copy', () => {
    const pts = [p(0, 0), p(10, 0), p(10, 10), p(0, 10)];
    expect(simplifyClosedPolygon(pts, 0)).toHaveLength(4);
  });
});

// ── simplifyStats ──────────────────────────────────────────────────

describe('Sprint 349 — simplifyStats', () => {
  it('計算 removed + ratio', () => {
    const before = [p(0, 0), p(5, 0), p(10, 0)];
    const after = simplifyPolygon(before, 0.1);
    const stats = simplifyStats(before, after);
    expect(stats.before).toBe(3);
    expect(stats.after).toBe(2);
    expect(stats.removed).toBe(1);
    expect(stats.reductionRatio).toBeCloseTo(1 / 3);
  });

  it('空 before → ratio 0', () => {
    expect(simplifyStats([], []).reductionRatio).toBe(0);
  });
});
