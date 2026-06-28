/**
 * WrapPolygonAnchorResolver — Sprint 324。
 *
 * Sprint 296/298/304/309/314/319 polygon 系列第七輪深推。本 sprint 補：
 * **anchor + dist margin** 解析、把 image-relative polygon 加上四方距離邊距、
 * 算出真實 wrap-avoid 區域。
 *
 * 場景：
 *   - Sprint 287 AnchorMetadata 補了 distT/distB/distL/distR（EMU → Pt）
 *   - polygon 定義為 image-coords（drawing units、Sprint 289）；Sprint 296
 *     `transformWrapPolygon` 把 image-coords → 絕對 page Pt
 *   - 但 wrap-avoid 區域 = polygon ⊕ dist margins（Minkowski sum 簡化版：
 *     X 軸 inflate distL/distR、Y 軸 inflate distT/distB）
 *
 * 範圍：
 *   - `inflateByDistMargins(polygon, dist)` → 加 4 方距離 margin
 *   - `resolveAnchorPolygon(polygon, imageRect, anchorMeta)` →
 *       transformWrapPolygon + inflateByDistMargins 整合
 *
 * 紀律 #18 scope-down：
 *   - 簡化 Minkowski sum 為 bbox-relative scale（紀律 #18、同 Sprint 304 polygonWithInflate）
 *   - 不考慮 layoutInCell / behindDoc / hidden 等 anchor 屬性對 wrap 的影響
 *     （caller 自己判斷是否要 layout、本 module 只處理幾何）
 */

import type { WrapPolygon, WrapPolygonPoint } from '../ast/types';
import { transformWrapPolygon, type ImageRect } from './wrap_polygon_math';

export interface DistMargins {
  /** 上方距離（Pt）；缺省 0 */
  distT?: number;
  /** 下方距離（Pt） */
  distB?: number;
  /** 左方距離（Pt） */
  distL?: number;
  /** 右方距離（Pt） */
  distR?: number;
}

/**
 * 用「bbox 邊向外擴 distT/B/L/R」的方式 inflate polygon。
 *
 * 算法：
 *   - 求 polygon bbox
 *   - 對 bbox 邊各加對應 dist margin → 新 bbox
 *   - 每個 vertex 相對於原 bbox 中心做 X/Y 各自 scale（避免直接 Minkowski 複雜度）
 *
 * 簡化（紀律 #18）：與 Sprint 304 polygonWithInflate 同政策、
 *   假設 polygon 接近凸形時結果合理。
 *
 * - 全 dist=0 → 原 polygon copy
 * - 空 polygon → 空
 */
export function inflateByDistMargins(
  polygon: readonly WrapPolygonPoint[],
  dist: DistMargins,
): WrapPolygonPoint[] {
  if (polygon.length === 0) return [];
  const distT = dist.distT ?? 0;
  const distB = dist.distB ?? 0;
  const distL = dist.distL ?? 0;
  const distR = dist.distR ?? 0;
  if (distT === 0 && distB === 0 && distL === 0 && distR === 0) {
    return polygon.map((p) => ({ ...p }));
  }
  // bbox
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of polygon) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  const w = maxX - minX;
  const h = maxY - minY;
  const newMinX = minX - distL;
  const newMaxX = maxX + distR;
  const newMinY = minY - distT;
  const newMaxY = maxY + distB;
  const newW = newMaxX - newMinX;
  const newH = newMaxY - newMinY;
  if (w === 0 || h === 0) {
    // degenerate：直接平移到新 bbox 中心
    const cx = (newMinX + newMaxX) / 2;
    const cy = (newMinY + newMaxY) / 2;
    return polygon.map(() => ({ x: cx, y: cy }));
  }
  // 對每 vertex 做相對 bbox 的線性 remap
  return polygon.map((p) => ({
    x: newMinX + ((p.x - minX) / w) * newW,
    y: newMinY + ((p.y - minY) / h) * newH,
  }));
}

/**
 * 整合：image-coords polygon → 加 imageRect 位置 → 加 dist margins → 絕對 wrap-avoid polygon。
 *
 * - transformWrapPolygon：image-coords → 絕對 Pt
 * - inflateByDistMargins：加 4 方距離 margin
 *
 * 對應 Sprint 287 AnchorMetadata + Sprint 289 WrapPolygon 的整合產出。
 */
export function resolveAnchorPolygon(
  imagePolygon: WrapPolygon,
  imageRect: ImageRect,
  dist: DistMargins,
): WrapPolygonPoint[] {
  const transformed = transformWrapPolygon(imagePolygon, imageRect);
  return inflateByDistMargins(transformed, dist);
}

/**
 * 取絕對 polygon 並加 dist margin（imageRect 已知為絕對座標時的 fast path）。
 *
 * 與 resolveAnchorPolygon 差別：caller 已自行 transform、本 fn 跳過 transform
 * 直接 inflate；節省 transform 重複呼叫。
 */
export function inflateAbsolutePolygon(
  absolutePolygon: readonly WrapPolygonPoint[],
  dist: DistMargins,
): WrapPolygonPoint[] {
  return inflateByDistMargins(absolutePolygon, dist);
}

/** Total horizontal margin（distL + distR）。Caller 估算 wrap-avoid 寬度時用。 */
export function totalHorizontalMargin(dist: DistMargins): number {
  return (dist.distL ?? 0) + (dist.distR ?? 0);
}

/** Total vertical margin（distT + distB）。 */
export function totalVerticalMargin(dist: DistMargins): number {
  return (dist.distT ?? 0) + (dist.distB ?? 0);
}
