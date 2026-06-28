/**
 * Sprint 339 — ③ deeper¹⁰：multi_polygon_paginator。
 *
 * Sprint 309 paginator + Sprint 334 multi flow 之後深推。多 cluster × 多頁
 * 切割 + 每頁 cluster 統計。
 *
 * 紀律 #18：純函式整合層、不接 Paginator real path。
 */
import { describe, expect, it } from 'vitest';

import {
  splitMultiPolygonAcrossPages,
  summarizePagesClusters,
  clustersOnPage,
  clusterPageSpread,
} from '../../static/src/core/ooxml/layout/multi_polygon_paginator';
import { prepareMultiPolygonContext } from '../../static/src/core/ooxml/layout/multi_polygon_flow';
import type { WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

const sq = (x0: number, y0: number, size: number): WrapPolygonPoint[] => [
  { x: x0, y: y0 },
  { x: x0 + size, y: y0 },
  { x: x0 + size, y: y0 + size },
  { x: x0, y: y0 + size },
];

// ── splitMultiPolygonAcrossPages ──────────────────────────────────

describe('Sprint 339 — splitMultiPolygonAcrossPages', () => {
  it('2 cluster × 2 page → 2x2 結果', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(0, 200, 50)],
    });
    const sliced = splitMultiPolygonAcrossPages(ctx, [
      { startY: 0, endY: 100 },
      { startY: 100, endY: 300 },
    ]);
    expect(sliced).toHaveLength(2);
    expect(sliced[0]).toHaveLength(2);
    // 第一頁有 cluster 0、無 cluster 1
    expect(sliced[0][0].length).toBeGreaterThan(0);
    expect(sliced[0][1].length).toBe(0);
    // 第二頁無 cluster 0、有 cluster 1
    expect(sliced[1][0].length).toBe(0);
    expect(sliced[1][1].length).toBeGreaterThan(0);
  });

  it('空 cluster → 每頁回 空 array', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [] });
    const sliced = splitMultiPolygonAcrossPages(ctx, [{ startY: 0, endY: 100 }]);
    expect(sliced).toHaveLength(1);
    expect(sliced[0]).toHaveLength(0);
  });

  it('空 pages → 空 array', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 10)] });
    expect(splitMultiPolygonAcrossPages(ctx, [])).toEqual([]);
  });

  it('保留 cluster 順序', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(0, 0, 50), sq(0, 200, 50)],
    });
    const sliced = splitMultiPolygonAcrossPages(ctx, [{ startY: 0, endY: 300 }]);
    expect(sliced[0]).toHaveLength(ctx.clusterPolygons.length);
  });
});

// ── summarizePagesClusters ────────────────────────────────────────

describe('Sprint 339 — summarizePagesClusters', () => {
  it('回每頁 active cluster index', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(0, 200, 50)],
    });
    const sliced = splitMultiPolygonAcrossPages(ctx, [
      { startY: 0, endY: 100 },
      { startY: 100, endY: 300 },
    ]);
    const stats = summarizePagesClusters(sliced);
    expect(stats[0].activeClusterCount).toBe(1);
    expect(stats[0].activeClusterIndices).toEqual([0]);
    expect(stats[1].activeClusterIndices).toEqual([1]);
  });

  it('全空頁 → activeClusterCount=0', () => {
    expect(summarizePagesClusters([[]])).toEqual([
      { pageIndex: 0, activeClusterCount: 0, activeClusterIndices: [] },
    ]);
  });
});

// ── clustersOnPage ────────────────────────────────────────────────

describe('Sprint 339 — clustersOnPage', () => {
  it('回該頁 active cluster polygons', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(0, 200, 50)],
    });
    const sliced = splitMultiPolygonAcrossPages(ctx, [
      { startY: 0, endY: 100 },
      { startY: 100, endY: 300 },
    ]);
    expect(clustersOnPage(sliced, 0)).toHaveLength(1);
    expect(clustersOnPage(sliced, 1)).toHaveLength(1);
  });

  it('out-of-range pageIndex → 空 list', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 10)] });
    const sliced = splitMultiPolygonAcrossPages(ctx, [{ startY: 0, endY: 100 }]);
    expect(clustersOnPage(sliced, 99)).toEqual([]);
  });

  it('回的是 copy（不 mutate 原 polygon）', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 50)] });
    const sliced = splitMultiPolygonAcrossPages(ctx, [{ startY: 0, endY: 100 }]);
    const dump = clustersOnPage(sliced, 0);
    dump[0].push({ x: 999, y: 999 });
    // 原 sliced 不受影響
    expect(sliced[0][0]).not.toContainEqual({ x: 999, y: 999 });
  });
});

// ── clusterPageSpread ─────────────────────────────────────────────

describe('Sprint 339 — clusterPageSpread', () => {
  it('cluster 跨頁 → 多頁 index', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 50, 100)], // 跨 page 0 (0..100) 與 page 1 (100..200)
    });
    const sliced = splitMultiPolygonAcrossPages(ctx, [
      { startY: 0, endY: 100 },
      { startY: 100, endY: 200 },
    ]);
    const spread = clusterPageSpread(sliced);
    expect(spread.get(0)).toEqual([0, 1]);
  });

  it('cluster 只在單頁', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 50)] });
    const sliced = splitMultiPolygonAcrossPages(ctx, [
      { startY: 0, endY: 100 },
      { startY: 100, endY: 200 },
    ]);
    const spread = clusterPageSpread(sliced);
    expect(spread.get(0)).toEqual([0]);
  });
});
