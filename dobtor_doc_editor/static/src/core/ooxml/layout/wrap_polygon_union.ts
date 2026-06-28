/**
 * wrap_polygon_union — Sprint 319。
 *
 * Sprint 296/298/304/309/314 polygon 系列第六輪深推。本 sprint 補：多個 polygon
 * 的 **union** 工具，給 caller 在多圖重疊或鄰近時計算合併區域用。
 *
 * 三種 union 策略（caller 依場景挑）：
 *
 *   1. `unionBoundingBox`：取所有 polygon 的 bbox 聯集（最保守、最快、必收斂）。
 *      適合 caller 想要「無腦避開所有 image」的 wrap 區域。
 *
 *   2. `unionConvexHull`：取所有 polygon 點集合的 convex hull（Andrew's monotone chain）。
 *      適合 polygon 大致為凸形且 caller 想要 bbox 與真實 union 之間的折衷。
 *
 *   3. `polygonsOverlap`：偵測兩 polygon 是否相交（bbox 快篩 + 邊段相交檢查）。
 *      caller 用來判斷 union 是否必要。
 *
 * 紀律 #18 scope-down：
 *   - 不做精準 Boolean union（Vatti / Greiner-Hormann 演算法、過度複雜）
 *   - convex hull 限制：input 是 vertex 集合、不保 polygon order
 *   - 不接 Paginator / Renderer real path（紀律 #21）
 */

import type { WrapPolygonPoint } from '../ast/types';
import { polygonBoundingBox, rectIntersectsPolygon, type ImageRect } from './wrap_polygon_math';

export interface BoundingBoxRect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * 多 polygon 的 bbox 聯集 → 單一矩形 polygon（4 vertex）。
 *
 * 不變動 input；空 input 回 null。單 polygon → 其 bbox（仍 4 vertex）。
 */
export function unionBoundingBox(polygons: ReadonlyArray<readonly WrapPolygonPoint[]>): WrapPolygonPoint[] | null {
  if (polygons.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let count = 0;
  for (const poly of polygons) {
    if (poly.length === 0) continue;
    const bbox = polygonBoundingBox(poly);
    if (bbox.minX < minX) minX = bbox.minX;
    if (bbox.minY < minY) minY = bbox.minY;
    if (bbox.maxX > maxX) maxX = bbox.maxX;
    if (bbox.maxY > maxY) maxY = bbox.maxY;
    count++;
  }
  if (count === 0) return null;
  return [
    { x: minX, y: minY },
    { x: maxX, y: minY },
    { x: maxX, y: maxY },
    { x: minX, y: maxY },
  ];
}

/**
 * 多 polygon 的 convex hull（Andrew's monotone chain）。
 *
 * 取所有點、按 x 升序 + y 升序排序、構造 lower + upper hull。
 * 回的 hull 為順時針或逆時針？— Andrew's 結果是 **逆時針**（counter-clockwise）。
 *
 * 不變動 input；空 input 回 null；< 3 點直接回原（無 hull 可言）。
 */
export function unionConvexHull(polygons: ReadonlyArray<readonly WrapPolygonPoint[]>): WrapPolygonPoint[] | null {
  // 合併所有點
  const points: WrapPolygonPoint[] = [];
  for (const poly of polygons) {
    for (const p of poly) {
      points.push({ x: p.x, y: p.y });
    }
  }
  if (points.length === 0) return null;
  if (points.length === 1) return [points[0]];
  if (points.length === 2) return points;

  // 排序：x 升序、tie 用 y 升序
  points.sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x));

  // dedup 完全相同的點
  const dedup: WrapPolygonPoint[] = [];
  for (const p of points) {
    const prev = dedup[dedup.length - 1];
    if (!prev || prev.x !== p.x || prev.y !== p.y) dedup.push(p);
  }
  if (dedup.length < 3) return dedup;

  // Lower hull
  const lower: WrapPolygonPoint[] = [];
  for (const p of dedup) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  // Upper hull
  const upper: WrapPolygonPoint[] = [];
  for (let i = dedup.length - 1; i >= 0; i--) {
    const p = dedup[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  // 移除尾端重複 vertex
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

/**
 * Cross product of vectors (o→a) × (o→b)。
 * > 0 = 左轉（CCW）、< 0 = 右轉（CW）、= 0 = 共線。
 */
function cross(o: WrapPolygonPoint, a: WrapPolygonPoint, b: WrapPolygonPoint): number {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

/**
 * 偵測兩 polygon 是否相交（bbox 快篩 + 一方 vertex 在另一方內 + 邊相交）。
 *
 * 簡化策略：
 *   1. bbox 不交 → 不相交
 *   2. 用 rectIntersectsPolygon（Sprint 296）把 polygon B 的 bbox 視為 rect、檢查與 A 是否相交
 *   3. 任一 polygon 完全在另一內 → bbox 重疊但邊不交、需單獨檢查（用 rect 涵蓋足以）
 */
export function polygonsOverlap(
  a: readonly WrapPolygonPoint[],
  b: readonly WrapPolygonPoint[],
): boolean {
  if (a.length === 0 || b.length === 0) return false;
  const bboxA = polygonBoundingBox(a);
  const bboxB = polygonBoundingBox(b);
  // bbox 快篩
  if (bboxA.maxX < bboxB.minX || bboxB.maxX < bboxA.minX) return false;
  if (bboxA.maxY < bboxB.minY || bboxB.maxY < bboxA.minY) return false;
  // bbox B 對 polygon A 的相交檢查
  const rectB: ImageRect = {
    x: bboxB.minX,
    y: bboxB.minY,
    width: bboxB.maxX - bboxB.minX,
    height: bboxB.maxY - bboxB.minY,
  };
  if (rectIntersectsPolygon(rectB, a)) return true;
  // 反向再檢查一次（A bbox 對 polygon B）
  const rectA: ImageRect = {
    x: bboxA.minX,
    y: bboxA.minY,
    width: bboxA.maxX - bboxA.minX,
    height: bboxA.maxY - bboxA.minY,
  };
  return rectIntersectsPolygon(rectA, b);
}

/**
 * 把多 polygon 依重疊關係分組（彼此重疊 → 同組、不重疊 → 不同組）。
 *
 * O(N²) 簡單實作；caller 用於決定哪些 polygon 該 union 為單一區域、哪些保留獨立。
 *
 * 回 number[] 同長度於 input：每個 polygon 的 group id（0..K-1）。
 */
export function clusterByOverlap(polygons: ReadonlyArray<readonly WrapPolygonPoint[]>): number[] {
  const n = polygons.length;
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = (x: number): number => parent[x] === x ? x : (parent[x] = find(parent[x]));
  const unite = (a: number, b: number): void => {
    const ra = find(a); const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  };
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (polygonsOverlap(polygons[i], polygons[j])) unite(i, j);
    }
  }
  // Compact group ids
  const groupMap = new Map<number, number>();
  let nextId = 0;
  return parent.map((_, i) => {
    const root = find(i);
    let gid = groupMap.get(root);
    if (gid === undefined) {
      gid = nextId++;
      groupMap.set(root, gid);
    }
    return gid;
  });
}
