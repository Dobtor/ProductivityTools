/**
 * wrap_polygon_simplify — Sprint 349。
 *
 * Sprint 296/298/304/309/314/319/324/329/334/339/344 polygon 系列第十二輪深推。
 * 真實 docx 的 wrapPolygon（尤其 wrapTight 自動產生的）可能有上百個 vertex；
 * 每次 rectIntersectsPolygon / pointInPolygon 都 O(n)，多行 × 多 polygon 會放大。
 * 本 sprint 補 **Douglas–Peucker 簡化**、在可接受誤差下減少 vertex 數。
 *
 *   - simplifyPolygon(polygon, epsilon)：DP 遞迴、保留關鍵轉折點
 *   - perpendicularDistance：點到線段的垂直距離
 *   - simplifyClosedPolygon：閉合多邊形（首尾相連）的簡化
 *
 * 紀律 #18 scope-down：
 *   - 不接 Layout real path（紀律 #21、caller opt-in 簡化後再餵 Sprint 344）
 *   - 不做 Visvalingam / topology-preserving（純 DP）
 *   - epsilon 由 caller 給（pt 單位）；不自動推估
 *
 * 紀律 #21：純函式幾何工具、不污染既有 pipeline。
 */

import type { WrapPolygonPoint } from '../ast/types';

/**
 * 點 p 到線段 [a, b] 的垂直距離。
 * a == b（退化線段）→ 回 p 到 a 的距離。
 */
export function perpendicularDistance(
  p: WrapPolygonPoint,
  a: WrapPolygonPoint,
  b: WrapPolygonPoint,
): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const segLenSq = dx * dx + dy * dy;
  if (segLenSq === 0) {
    return Math.hypot(p.x - a.x, p.y - a.y);
  }
  // 投影參數 t（不 clamp、用無限長直線的垂距，標準 DP）
  const t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / segLenSq;
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;
  return Math.hypot(p.x - projX, p.y - projY);
}

/**
 * Douglas–Peucker 簡化開放折線。
 *
 * - epsilon <= 0 → 回原 polygon copy（不簡化）
 * - 點數 <= 2 → 原樣 copy
 * - 保留首尾 + 垂距 > epsilon 的關鍵點
 */
export function simplifyPolygon(
  polygon: readonly WrapPolygonPoint[],
  epsilon: number,
): WrapPolygonPoint[] {
  if (polygon.length <= 2 || epsilon <= 0) {
    return polygon.map((p) => ({ ...p }));
  }
  return dpRecursive(polygon, 0, polygon.length - 1, epsilon);
}

function dpRecursive(
  pts: readonly WrapPolygonPoint[],
  startIdx: number,
  endIdx: number,
  epsilon: number,
): WrapPolygonPoint[] {
  let maxDist = 0;
  let maxIdx = startIdx;
  for (let i = startIdx + 1; i < endIdx; i++) {
    const d = perpendicularDistance(pts[i], pts[startIdx], pts[endIdx]);
    if (d > maxDist) {
      maxDist = d;
      maxIdx = i;
    }
  }
  if (maxDist > epsilon) {
    const left = dpRecursive(pts, startIdx, maxIdx, epsilon);
    const right = dpRecursive(pts, maxIdx, endIdx, epsilon);
    // left 尾 == right 頭（maxIdx 重複）→ 去重串接
    return [...left.slice(0, -1), ...right];
  }
  return [{ ...pts[startIdx] }, { ...pts[endIdx] }];
}

/**
 * 閉合多邊形簡化：把首點 append 到尾、簡化後再去掉重複尾點。
 *
 * - 點數 <= 3 → 原樣 copy（三角形無法再簡化）
 */
export function simplifyClosedPolygon(
  polygon: readonly WrapPolygonPoint[],
  epsilon: number,
): WrapPolygonPoint[] {
  if (polygon.length <= 3 || epsilon <= 0) {
    return polygon.map((p) => ({ ...p }));
  }
  const first = polygon[0];
  const last = polygon[polygon.length - 1];
  const isClosed = first.x === last.x && first.y === last.y;
  const open = isClosed ? polygon.slice(0, -1) : polygon;
  // 把首點接到尾形成 explicit closed loop 再簡化
  const looped = [...open, { ...open[0] }];
  const simplified = simplifyPolygon(looped, epsilon);
  // 去掉重複的閉合尾點（保持與 input 是否閉合一致）
  if (
    simplified.length > 1 &&
    simplified[0].x === simplified[simplified.length - 1].x &&
    simplified[0].y === simplified[simplified.length - 1].y &&
    !isClosed
  ) {
    return simplified.slice(0, -1);
  }
  return simplified;
}

/**
 * 簡化前後 vertex 數變化（caller 想知道省了多少）。
 */
export interface SimplifyStats {
  before: number;
  after: number;
  removed: number;
  reductionRatio: number;
}

export function simplifyStats(
  before: readonly WrapPolygonPoint[],
  after: readonly WrapPolygonPoint[],
): SimplifyStats {
  const removed = before.length - after.length;
  return {
    before: before.length,
    after: after.length,
    removed,
    reductionRatio: before.length === 0 ? 0 : removed / before.length,
  };
}
