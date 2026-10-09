/**
 * Sprint 324 — ③ deeper⁶：WrapPolygonAnchorResolver。
 *
 * Sprint 296/298/304/309/314/319 之後深推。把 image-coords polygon 加上 imageRect
 * 位置 + dist margin，產生絕對 wrap-avoid 區域。
 *
 * 紀律 #18 scope-down：簡化 Minkowski sum 為 bbox-relative scale。
 */
import { describe, expect, it } from 'vitest';

import {
  inflateByDistMargins,
  resolveAnchorPolygon,
  inflateAbsolutePolygon,
  totalHorizontalMargin,
  totalVerticalMargin,
} from '../../static/src/core/ooxml/layout/wrap_polygon_anchor';

const RECT = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 50 },
  { x: 0, y: 50 },
];

// ── inflateByDistMargins ─────────────────────────────────────────────

describe('Sprint 324 — inflateByDistMargins', () => {
  it('全 dist=0 → 原 polygon copy', () => {
    const out = inflateByDistMargins(RECT, {});
    expect(out).toEqual(RECT);
    expect(out).not.toBe(RECT);
  });

  it('distR=10 → 右邊外擴 10', () => {
    const out = inflateByDistMargins(RECT, { distR: 10 });
    // 原 X[0,100] → 新 X[0,110]、Y 不變
    expect(out[1].x).toBe(110); // (100, 0) → (110, 0)
    expect(out[2].x).toBe(110);
    expect(out[0].x).toBe(0);   // (0, 0) 不動
  });

  it('distL=5, distT=3, distB=7 → 四方各自 inflate', () => {
    const out = inflateByDistMargins(RECT, { distL: 5, distT: 3, distB: 7 });
    // 新 X[-5,100], Y[-3,57]
    expect(out[0]).toEqual({ x: -5, y: -3 });
    expect(out[1]).toEqual({ x: 100, y: -3 });
    expect(out[2]).toEqual({ x: 100, y: 57 });
    expect(out[3]).toEqual({ x: -5, y: 57 });
  });

  it('空 polygon → 空', () => {
    expect(inflateByDistMargins([], { distR: 10 })).toEqual([]);
  });

  it('degenerate polygon（width=0）→ 退化處理', () => {
    const vert = [{ x: 5, y: 0 }, { x: 5, y: 10 }];
    const out = inflateByDistMargins(vert, { distR: 10 });
    // width=0 → 平移到新 bbox 中心
    expect(out).toHaveLength(2);
  });
});

// ── resolveAnchorPolygon ────────────────────────────────────────────

describe('Sprint 324 — resolveAnchorPolygon', () => {
  it('整合 transformWrapPolygon + inflate', () => {
    // image-coords [0..21600] × [0..21600]、imageRect 50,50 ×100×50
    const imagePoly = {
      start: { x: 0, y: 0 },
      lineTo: [
        { x: 21600, y: 0 },
        { x: 21600, y: 21600 },
        { x: 0, y: 21600 },
      ],
    };
    const imageRect = { x: 50, y: 50, width: 100, height: 50 };
    const out = resolveAnchorPolygon(imagePoly, imageRect, { distR: 10 });
    // transform 後 X[50,150] Y[50,100]、inflate distR=10 → X[50,160]
    expect(out[1].x).toBe(160);
    expect(out[2].x).toBe(160);
  });

  it('全 dist=0 → 等同 transformWrapPolygon', () => {
    const imagePoly = {
      start: { x: 0, y: 0 },
      lineTo: [
        { x: 21600, y: 0 },
        { x: 0, y: 21600 },
      ],
    };
    const imageRect = { x: 10, y: 20, width: 100, height: 100 };
    const out = resolveAnchorPolygon(imagePoly, imageRect, {});
    expect(out[0]).toEqual({ x: 10, y: 20 });
    expect(out[1]).toEqual({ x: 110, y: 20 });
  });
});

// ── inflateAbsolutePolygon fast path ───────────────────────────────

describe('Sprint 324 — inflateAbsolutePolygon', () => {
  it('caller 已 transform 過 → 直接 inflate', () => {
    const abs = RECT;
    const out = inflateAbsolutePolygon(abs, { distR: 5 });
    expect(out[1].x).toBe(105);
  });
});

// ── totalHorizontalMargin / totalVerticalMargin ──────────────────

describe('Sprint 324 — total margin helpers', () => {
  it('totalHorizontalMargin = distL + distR', () => {
    expect(totalHorizontalMargin({ distL: 3, distR: 7 })).toBe(10);
    expect(totalHorizontalMargin({})).toBe(0);
  });

  it('totalVerticalMargin = distT + distB', () => {
    expect(totalVerticalMargin({ distT: 5, distB: 8 })).toBe(13);
    expect(totalVerticalMargin({})).toBe(0);
  });
});
