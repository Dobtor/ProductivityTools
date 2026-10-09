/**
 * multi_polygon_paginator — Sprint 339。
 *
 * Sprint 309 wrap_polygon_paginator（single polygon × N 頁）+ Sprint 334
 * multi_polygon_flow（多 polygon cluster）之後深推。把多 cluster polygon
 * 一次切到多頁、回每頁每 cluster 的子 polygon。
 *
 * 場景：caller 已用 Sprint 334 prepareMultiPolygonContext 合好 clusterPolygons、
 * 接著要分頁排版；本 module 提供 page × cluster 二維結果。
 *
 * 紀律 #18 scope-down：
 *   - 不接 Paginator real path（紀律 #21）
 *   - 不重做 anchor transform / union（caller 自負）
 *   - 不做 footer margin / page break heuristic
 *
 * 紀律 #21：純函式整合層、不污染既有 pipeline。
 */

import type { WrapPolygonPoint } from '../ast/types';
import { splitPolygonAcrossPages, type PageYRange } from './wrap_polygon_paginator';
import type { MultiPolygonContext } from './multi_polygon_flow';

/**
 * 切多 cluster 到多頁。
 *
 * @returns 二維 array：`result[pageIndex][clusterIndex]` = 該頁該 cluster 的子 polygon
 *   - 若該頁該 cluster 完全不重疊 → 該位置 `[]`
 *   - 結果保留 caller 的 cluster 順序、不會 reorder
 */
export function splitMultiPolygonAcrossPages(
  ctx: MultiPolygonContext,
  pages: readonly PageYRange[],
): WrapPolygonPoint[][][] {
  const result: WrapPolygonPoint[][][] = [];
  for (let pageIdx = 0; pageIdx < pages.length; pageIdx++) {
    const page = pages[pageIdx];
    const perCluster: WrapPolygonPoint[][] = [];
    for (const polygon of ctx.clusterPolygons) {
      // 用 single-polygon paginator 對 [page] 切、取 result[0]
      const sliced = splitPolygonAcrossPages(polygon, [page]);
      perCluster.push(sliced[0] ?? []);
    }
    result.push(perCluster);
  }
  return result;
}

export interface PageClusterStats {
  pageIndex: number;
  /** 該頁實際與 N 個 cluster 重疊 */
  activeClusterCount: number;
  /** 重疊 cluster 的 index list */
  activeClusterIndices: number[];
}

/**
 * 每頁列出實際與哪些 cluster 重疊。
 *
 * 條件：sliced[pageIndex][clusterIndex].length > 0 → 視為 active。
 */
export function summarizePagesClusters(
  sliced: ReadonlyArray<ReadonlyArray<readonly WrapPolygonPoint[]>>,
): PageClusterStats[] {
  return sliced.map((perCluster, pageIndex) => {
    const indices: number[] = [];
    for (let i = 0; i < perCluster.length; i++) {
      if (perCluster[i].length > 0) indices.push(i);
    }
    return {
      pageIndex,
      activeClusterCount: indices.length,
      activeClusterIndices: indices,
    };
  });
}

/**
 * 給定 page index → 拿該頁所有 active cluster polygon 合成 flat list（caller 之後
 * 想對該頁做 union 或 baseline 計算用）。
 *
 * 空頁 → 空 list。
 */
export function clustersOnPage(
  sliced: ReadonlyArray<ReadonlyArray<readonly WrapPolygonPoint[]>>,
  pageIndex: number,
): WrapPolygonPoint[][] {
  const page = sliced[pageIndex];
  if (!page) return [];
  return page.filter((p) => p.length > 0).map((p) => p.slice());
}

/**
 * 跨頁總覽：每個 cluster 出現在哪幾頁。
 *
 * 回 Map<clusterIndex, pageIndexes[]>。
 */
export function clusterPageSpread(
  sliced: ReadonlyArray<ReadonlyArray<readonly WrapPolygonPoint[]>>,
): Map<number, number[]> {
  const map = new Map<number, number[]>();
  for (let pageIdx = 0; pageIdx < sliced.length; pageIdx++) {
    const perCluster = sliced[pageIdx];
    for (let cIdx = 0; cIdx < perCluster.length; cIdx++) {
      if (perCluster[cIdx].length === 0) continue;
      let arr = map.get(cIdx);
      if (!arr) {
        arr = [];
        map.set(cIdx, arr);
      }
      arr.push(pageIdx);
    }
  }
  return map;
}
