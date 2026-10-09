/**
 * Sprint 334 — ③ deeper⁹：multi_polygon_flow。
 *
 * Sprint 329 single-polygon flow shim 之後深推。把 Sprint 319 union/cluster 與
 * Sprint 296 bbox 整合到多 polygon façade。
 *
 * 紀律 #18：純函式整合層、不接 Paginator real path。
 */
import { describe, expect, it } from 'vitest';

import {
  prepareMultiPolygonContext,
  clustersBlockingYRange,
  clusterPolygon,
  isYRangeBlockedByAnyCluster,
} from '../../static/src/core/ooxml/layout/multi_polygon_flow';
import type { WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

const sq = (x0: number, y0: number, size: number): WrapPolygonPoint[] => [
  { x: x0, y: y0 },
  { x: x0 + size, y: y0 },
  { x: x0 + size, y: y0 + size },
  { x: x0, y: y0 + size },
];

// ── prepareMultiPolygonContext ─────────────────────────────────────

describe('Sprint 334 — prepareMultiPolygonContext', () => {
  it('空 polygons → 空 cluster + 全 0 super bbox', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [] });
    expect(ctx.clusterPolygons).toEqual([]);
    expect(ctx.superBbox).toEqual({ minX: 0, minY: 0, maxX: 0, maxY: 0 });
  });

  it('2 個不重疊 polygon → 2 cluster', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 10), sq(100, 100, 10)],
    });
    expect(ctx.clusterPolygons).toHaveLength(2);
    expect(ctx.clusterBboxes).toHaveLength(2);
    expect(ctx.superBbox.minX).toBe(0);
    expect(ctx.superBbox.maxX).toBe(110);
  });

  it('2 個重疊 polygon → 1 cluster（union）', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(25, 25, 50)],
    });
    expect(ctx.clusterPolygons).toHaveLength(1);
    expect(ctx.clusterBboxes[0].minX).toBe(0);
    expect(ctx.clusterBboxes[0].maxX).toBe(75);
  });

  it('default unionStrategy = hull', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(25, 25, 50)],
    });
    // hull 至少 3 vertex
    expect(ctx.clusterPolygons[0].length).toBeGreaterThanOrEqual(3);
  });

  it('unionStrategy=bbox → 4 vertex rect', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 50), sq(25, 25, 50)],
      unionStrategy: 'bbox',
    });
    expect(ctx.clusterPolygons[0]).toHaveLength(4);
  });

  it('polygonToCluster 對應正確', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 10), sq(100, 100, 10), sq(5, 5, 10)],
    });
    // polygon 0 與 2 重疊、polygon 1 獨立
    expect(ctx.polygonToCluster[0]).toBe(ctx.polygonToCluster[2]);
    expect(ctx.polygonToCluster[1]).not.toBe(ctx.polygonToCluster[0]);
  });
});

// ── clustersBlockingYRange ─────────────────────────────────────────

describe('Sprint 334 — clustersBlockingYRange', () => {
  it('回所有撞 Y 範圍的 cluster index', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 0, 10), sq(100, 100, 10), sq(0, 200, 10)],
    });
    const blocking = clustersBlockingYRange(ctx, 0, 50);
    expect(blocking).toContain(0);
    expect(blocking).not.toContain(1);
  });

  it('空 cluster → 空 array', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [] });
    expect(clustersBlockingYRange(ctx, 0, 100)).toEqual([]);
  });
});

// ── clusterPolygon ─────────────────────────────────────────────────

describe('Sprint 334 — clusterPolygon', () => {
  it('valid index → polygon', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 10)] });
    expect(clusterPolygon(ctx, 0)?.length).toBeGreaterThan(0);
  });
  it('out-of-range → undefined', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [sq(0, 0, 10)] });
    expect(clusterPolygon(ctx, 99)).toBeUndefined();
  });
});

// ── isYRangeBlockedByAnyCluster ─────────────────────────────────────

describe('Sprint 334 — isYRangeBlockedByAnyCluster', () => {
  it('空 → 永遠 false', () => {
    const ctx = prepareMultiPolygonContext({ polygonsAbs: [] });
    expect(isYRangeBlockedByAnyCluster(ctx, 0, 100)).toBe(false);
  });

  it('super bbox 撞 Y 範圍 → true', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 50, 10)],
    });
    expect(isYRangeBlockedByAnyCluster(ctx, 0, 100)).toBe(true);
  });

  it('super bbox 完全在 Y 範圍下方 → false', () => {
    const ctx = prepareMultiPolygonContext({
      polygonsAbs: [sq(0, 200, 10)],
    });
    expect(isYRangeBlockedByAnyCluster(ctx, 0, 100)).toBe(false);
  });
});
