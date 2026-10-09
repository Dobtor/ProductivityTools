/**
 * multi_polygon_flow — Sprint 334。
 *
 * Sprint 296/298/304/309/314/319/324/329 polygon 系列第九輪深推。Sprint 329
 * text_flow_around_polygon 是 **單一 polygon**；本 sprint 補多 polygon 場景：
 *
 *   1. cluster：把彼此重疊的 polygon 合成同一群（Sprint 319 clusterByOverlap）
 *   2. union per cluster：每群算 unionConvexHull / unionBoundingBox
 *   3. combined wrap context：caller 拿一個 polygonAbs list、可選擇 union 策略
 *
 * 紀律 #18 scope-down：
 *   - 不接 Paginator real path（紀律 #21）
 *   - union 策略只支援 bbox / hull（Sprint 319 既有兩種）
 *   - 不重做 anchor transform、caller 自己預先 transform（與 Sprint 329 prepareWrapContext 對稱）
 *   - findFlowBaseline 仍走 single polygon（caller 自己合成 super-polygon 後傳入）
 *
 * 紀律 #21：純函式整合層、不污染既有 pipeline。
 */

import type { WrapPolygonPoint } from '../ast/types';
import { polygonBoundingBox, type PolygonBoundingBox } from './wrap_polygon_math';
import {
  clusterByOverlap,
  unionBoundingBox,
  unionConvexHull,
} from './wrap_polygon_union';

export type UnionStrategy = 'bbox' | 'hull';

export interface MultiPolygonContextOptions {
  /** Caller 已 transform 為絕對 page-Pt 座標的 polygons */
  polygonsAbs: ReadonlyArray<readonly WrapPolygonPoint[]>;
  /** 用 bbox 還是 convex hull 合成每個 cluster；預設 'hull' */
  unionStrategy?: UnionStrategy;
}

export interface MultiPolygonContext {
  /** 每個 cluster 合成後的 polygon（empty cluster 或 union 失敗會被跳過） */
  clusterPolygons: WrapPolygonPoint[][];
  /** 對應 cluster 的 bbox（同 index） */
  clusterBboxes: PolygonBoundingBox[];
  /** 全部 cluster 合成的 super bbox（caller 想做 cheap range check 用） */
  superBbox: PolygonBoundingBox;
  /** 原本 caller 傳的 polygon 對應到哪個 cluster index */
  polygonToCluster: number[];
}

/**
 * 用 cluster + union 處理多 polygon。
 *
 * 流程：
 *   1. clusterByOverlap → 每個 polygon 分群
 *   2. 對每群執行 unionStrategy（bbox / hull）
 *   3. 計算每群 bbox + 全部 bbox 合 super bbox
 *
 * 空 polygonsAbs → 空 clusterPolygons + 全 0 super bbox。
 */
export function prepareMultiPolygonContext(
  opts: MultiPolygonContextOptions,
): MultiPolygonContext {
  const polygons = opts.polygonsAbs;
  const strategy = opts.unionStrategy ?? 'hull';

  if (polygons.length === 0) {
    return {
      clusterPolygons: [],
      clusterBboxes: [],
      superBbox: { minX: 0, minY: 0, maxX: 0, maxY: 0 },
      polygonToCluster: [],
    };
  }

  const polygonToCluster = clusterByOverlap(polygons);
  const numClusters = polygonToCluster.reduce((m, c) => (c > m ? c : m), -1) + 1;

  const clusterPolygons: WrapPolygonPoint[][] = [];
  const clusterBboxes: PolygonBoundingBox[] = [];

  for (let i = 0; i < numClusters; i++) {
    const members: ReadonlyArray<readonly WrapPolygonPoint[]> = polygons.filter(
      (_, idx) => polygonToCluster[idx] === i,
    );
    if (members.length === 0) continue;
    const merged =
      strategy === 'bbox' ? unionBoundingBox(members) : unionConvexHull(members);
    if (!merged || merged.length === 0) continue;
    clusterPolygons.push(merged);
    clusterBboxes.push(polygonBoundingBox(merged));
  }

  const superBbox = computeSuperBbox(clusterBboxes);
  return { clusterPolygons, clusterBboxes, superBbox, polygonToCluster };
}

function computeSuperBbox(bboxes: ReadonlyArray<PolygonBoundingBox>): PolygonBoundingBox {
  if (bboxes.length === 0) return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  let minX = bboxes[0].minX;
  let minY = bboxes[0].minY;
  let maxX = bboxes[0].maxX;
  let maxY = bboxes[0].maxY;
  for (let i = 1; i < bboxes.length; i++) {
    if (bboxes[i].minX < minX) minX = bboxes[i].minX;
    if (bboxes[i].minY < minY) minY = bboxes[i].minY;
    if (bboxes[i].maxX > maxX) maxX = bboxes[i].maxX;
    if (bboxes[i].maxY > maxY) maxY = bboxes[i].maxY;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * Caller 想知道 Y 範圍會撞到哪些 cluster（fast lookup、不算行內細節）。
 * 回 cluster index list。
 */
export function clustersBlockingYRange(
  ctx: MultiPolygonContext,
  yMin: number,
  yMax: number,
): number[] {
  const out: number[] = [];
  for (let i = 0; i < ctx.clusterBboxes.length; i++) {
    const b = ctx.clusterBboxes[i];
    if (b.maxY >= yMin && b.minY <= yMax) out.push(i);
  }
  return out;
}

/**
 * 給定 cluster index、取對應 polygon（caller 直接餵給 Sprint 329 findFlowBaseline）。
 */
export function clusterPolygon(
  ctx: MultiPolygonContext,
  clusterIndex: number,
): readonly WrapPolygonPoint[] | undefined {
  return ctx.clusterPolygons[clusterIndex];
}

/**
 * 多 cluster 場景下的 super-bbox cheap check（同 Sprint 329 isYRangeBlockedByWrap）。
 *
 * 空 cluster → 永遠 false。
 */
export function isYRangeBlockedByAnyCluster(
  ctx: MultiPolygonContext,
  yMin: number,
  yMax: number,
): boolean {
  if (ctx.clusterPolygons.length === 0) return false;
  return ctx.superBbox.maxY >= yMin && ctx.superBbox.minY <= yMax;
}
