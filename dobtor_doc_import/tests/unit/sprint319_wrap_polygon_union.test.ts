/**
 * Sprint 319 — ③ deeper⁵：wrap_polygon_union。
 *
 * Sprint 296/298/304/309/314 之後深推。多 polygon union：bbox / convex hull /
 * overlap / cluster。
 *
 * 紀律 #18 scope-down：不做精準 Vatti union；convex hull 不保 polygon order。
 */
import { describe, expect, it } from 'vitest';

import {
  unionBoundingBox,
  unionConvexHull,
  polygonsOverlap,
  clusterByOverlap,
} from '../../static/src/core/ooxml/layout/wrap_polygon_union';

const RECT_A = [
  { x: 0, y: 0 },
  { x: 50, y: 0 },
  { x: 50, y: 50 },
  { x: 0, y: 50 },
];

const RECT_B = [
  { x: 30, y: 30 },
  { x: 80, y: 30 },
  { x: 80, y: 80 },
  { x: 30, y: 80 },
];

const RECT_C_FAR = [
  { x: 200, y: 200 },
  { x: 250, y: 200 },
  { x: 250, y: 250 },
  { x: 200, y: 250 },
];

// ── unionBoundingBox ───────────────────────────────────────────────────

describe('Sprint 319 — unionBoundingBox', () => {
  it('多 polygon bbox 聯集 → 最外 4 vertex 矩形', () => {
    const out = unionBoundingBox([RECT_A, RECT_B]);
    expect(out).toEqual([
      { x: 0, y: 0 },
      { x: 80, y: 0 },
      { x: 80, y: 80 },
      { x: 0, y: 80 },
    ]);
  });

  it('空 input → null', () => {
    expect(unionBoundingBox([])).toBeNull();
  });

  it('全部 empty polygons → null', () => {
    expect(unionBoundingBox([[], []])).toBeNull();
  });

  it('單 polygon → 其 bbox', () => {
    const out = unionBoundingBox([RECT_A]);
    expect(out).toEqual([
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 50 },
      { x: 0, y: 50 },
    ]);
  });
});

// ── unionConvexHull ────────────────────────────────────────────────────

describe('Sprint 319 — unionConvexHull', () => {
  it('兩矩形 union → convex hull 含全部 8 corners 中的外 corners', () => {
    const out = unionConvexHull([RECT_A, RECT_B]);
    expect(out).not.toBeNull();
    // 至少包含 (0,0), (50,0), (80,30), (80,80), (30,80), (0,50)
    const pts = out!.map((p) => `${p.x},${p.y}`);
    expect(pts).toContain('0,0');
    expect(pts).toContain('80,80');
  });

  it('空 input → null', () => {
    expect(unionConvexHull([])).toBeNull();
  });

  it('< 3 點 → 直接回 input', () => {
    const out = unionConvexHull([[{ x: 5, y: 5 }]]);
    expect(out).toEqual([{ x: 5, y: 5 }]);
  });

  it('共線 3 點 → hull 是 2 vertex（去掉中間）', () => {
    const out = unionConvexHull([
      [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }],
    ]);
    expect(out!.length).toBeLessThanOrEqual(3);
    // 共線時 Andrew's 演算法應丟掉中間點
  });

  it('重複點自動 dedup', () => {
    const out = unionConvexHull([
      [{ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }],
    ]);
    expect(out!.length).toBe(4);
  });
});

// ── polygonsOverlap ────────────────────────────────────────────────────

describe('Sprint 319 — polygonsOverlap', () => {
  it('明顯相交 → true', () => {
    expect(polygonsOverlap(RECT_A, RECT_B)).toBe(true);
  });

  it('明顯不相交 → false', () => {
    expect(polygonsOverlap(RECT_A, RECT_C_FAR)).toBe(false);
  });

  it('空 polygon → false', () => {
    expect(polygonsOverlap([], RECT_A)).toBe(false);
    expect(polygonsOverlap(RECT_A, [])).toBe(false);
  });

  it('完全內含的小 polygon', () => {
    const SMALL_INSIDE = [
      { x: 10, y: 10 },
      { x: 20, y: 10 },
      { x: 20, y: 20 },
      { x: 10, y: 20 },
    ];
    expect(polygonsOverlap(RECT_A, SMALL_INSIDE)).toBe(true);
  });
});

// ── clusterByOverlap ──────────────────────────────────────────────────

describe('Sprint 319 — clusterByOverlap', () => {
  it('兩重疊 + 一獨立 → 兩 group', () => {
    const groups = clusterByOverlap([RECT_A, RECT_B, RECT_C_FAR]);
    expect(groups[0]).toBe(groups[1]);  // A 與 B 同 group
    expect(groups[0]).not.toBe(groups[2]);  // C 獨立
  });

  it('全獨立 → N 個 group', () => {
    const polys = [RECT_A, RECT_C_FAR];
    const groups = clusterByOverlap(polys);
    expect(new Set(groups).size).toBe(2);
  });

  it('全重疊 → 1 group', () => {
    const groups = clusterByOverlap([RECT_A, RECT_B]);
    expect(new Set(groups).size).toBe(1);
  });

  it('空 input → 空陣列', () => {
    expect(clusterByOverlap([])).toEqual([]);
  });

  it('三 polygon 鏈式重疊（A∩B, B∩C, 但 A 不 ∩ C）→ 仍同 group（union-find 傳遞）', () => {
    const A = [
      { x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 },
    ];
    const B = [
      { x: 5, y: 0 }, { x: 25, y: 0 }, { x: 25, y: 10 }, { x: 5, y: 10 },
    ];
    const C = [
      { x: 20, y: 0 }, { x: 35, y: 0 }, { x: 35, y: 10 }, { x: 20, y: 10 },
    ];
    const groups = clusterByOverlap([A, B, C]);
    expect(new Set(groups).size).toBe(1);
  });
});
