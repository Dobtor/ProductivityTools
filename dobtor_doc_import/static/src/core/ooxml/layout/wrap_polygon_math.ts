/**
 * wrap_polygon_math — Sprint 296。
 *
 * Phase 3.4 wrapTight 多邊形 layout 數學工具（純函式、無 DOM 依賴）。
 * Sprint 289 已 capture `<wp:wrapPolygon>` 到 AST、座標為 drawing coordinates
 * （raw int、Office 慣例 21600 ≈ 圖片全寬/高）；本 sprint 補 layout 端需要的
 * 幾何函式：座標轉換、bbox、point-in-polygon、rect-polygon 相交。
 *
 * 紀律 #18 scope-down：本 sprint 純 utility extraction + tests；**不接 Layout
 *   engine**（Phase 3.4 完整 wrapTight 需重寫 Layout 換行邏輯、超出單 sprint scope）；
 *   未來 polish sprint 才把這些 helper 接進 LineBreaker / Paginator。
 * 紀律 #21：純函式、無 side effect、不污染 VR pipeline。
 */

import type { WrapPolygon, WrapPolygonPoint } from '../ast/types';

/** 圖片絕對位置 + 尺寸（pt、與 caller page bounds 同單位）。 */
export interface ImageRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * 把 wrapPolygon 從 drawing coordinates（21600 慣例）轉成絕對 pt 座標。
 *
 * - drawingUnits 預設 21600（OOXML §20.4.2.17 默認）
 * - 結果 = imageRect 座標系下的絕對位置（pt）
 *
 * @param polygon AST 中的 wrapPolygon
 * @param imageRect 圖片在頁面上的絕對位置 + 尺寸
 * @param drawingUnits drawing coordinate 系統的滿格值（預設 21600）
 */
export function transformWrapPolygon(
  polygon: WrapPolygon,
  imageRect: ImageRect,
  drawingUnits = 21600,
): WrapPolygonPoint[] {
  const scaleX = imageRect.width / drawingUnits;
  const scaleY = imageRect.height / drawingUnits;
  const transform = (p: WrapPolygonPoint): WrapPolygonPoint => ({
    x: imageRect.x + p.x * scaleX,
    y: imageRect.y + p.y * scaleY,
  });
  return [transform(polygon.start), ...polygon.lineTo.map(transform)];
}

export interface PolygonBoundingBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * 計算多邊形包圍盒（min/max XY）。
 * polygon 為空 → 回 0/0/0/0（caller 自行決定是否視為「無 polygon」）。
 */
export function polygonBoundingBox(polygon: readonly WrapPolygonPoint[]): PolygonBoundingBox {
  if (polygon.length === 0) return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  let minX = polygon[0].x;
  let minY = polygon[0].y;
  let maxX = polygon[0].x;
  let maxY = polygon[0].y;
  for (let i = 1; i < polygon.length; i++) {
    const p = polygon[i];
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * 點是否在多邊形內（包含邊界）— ray-casting 演算法。
 *
 * - 標準偶/奇射線測試（從 point.x, point.y 向右發射）
 * - 處理邊界 case：射線剛好通過頂點 → 視為相交（偶數次數 = 在外、奇數 = 在內）
 * - polygon 開放或閉合都可（最後一點 == 起點或不等都行、演算法 wrap-around）
 *
 * 退化條件：
 * - polygon 點數 < 3 → 回 false（無法形成多邊形）
 */
export function pointInPolygon(
  point: WrapPolygonPoint,
  polygon: readonly WrapPolygonPoint[],
): boolean {
  if (polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;
    const intersect =
      ((yi > point.y) !== (yj > point.y)) &&
      (point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

/**
 * 矩形是否與多邊形相交（含 bbox 快篩 + 角點 / 邊界檢查）。
 *
 * 演算法（保守、可能 false-positive 但不 miss）：
 *   1. polygon bbox 與 rect 完全不相交 → 必不相交
 *   2. polygon 任一頂點在 rect 內 → 相交
 *   3. rect 四角任一在 polygon 內 → 相交
 *   4. polygon 邊與 rect 邊有 line-line intersection → 相交
 *   5. 都沒命中 → 不相交
 *
 * 給 Layout 端「文字 line box 是否撞到 wrapTight polygon」用。
 * 紀律 #18：不做精確 SAT（Separating Axis Theorem）；對 wrapTight UI 級別
 * 精度足夠、避免複雜度爆炸。
 */
export function rectIntersectsPolygon(
  rect: ImageRect,
  polygon: readonly WrapPolygonPoint[],
): boolean {
  if (polygon.length < 3) return false;
  const bbox = polygonBoundingBox(polygon);
  const rRight = rect.x + rect.width;
  const rBottom = rect.y + rect.height;
  // (1) bbox 完全不相交
  if (bbox.maxX < rect.x || bbox.minX > rRight) return false;
  if (bbox.maxY < rect.y || bbox.minY > rBottom) return false;

  // (2) polygon 任一頂點在 rect 內
  for (const p of polygon) {
    if (p.x >= rect.x && p.x <= rRight && p.y >= rect.y && p.y <= rBottom) {
      return true;
    }
  }

  // (3) rect 四角任一在 polygon 內
  const corners: WrapPolygonPoint[] = [
    { x: rect.x, y: rect.y },
    { x: rRight, y: rect.y },
    { x: rRight, y: rBottom },
    { x: rect.x, y: rBottom },
  ];
  for (const c of corners) {
    if (pointInPolygon(c, polygon)) return true;
  }

  // (4) polygon 邊與 rect 邊相交
  const rectEdges: Array<[WrapPolygonPoint, WrapPolygonPoint]> = [
    [corners[0], corners[1]],
    [corners[1], corners[2]],
    [corners[2], corners[3]],
    [corners[3], corners[0]],
  ];
  for (let i = 0; i < polygon.length; i++) {
    const a = polygon[i];
    const b = polygon[(i + 1) % polygon.length];
    for (const [c, d] of rectEdges) {
      if (segmentsIntersect(a, b, c, d)) return true;
    }
  }

  return false;
}

/** 線段相交（標準 cross-product 判定）。 */
function segmentsIntersect(
  a: WrapPolygonPoint,
  b: WrapPolygonPoint,
  c: WrapPolygonPoint,
  d: WrapPolygonPoint,
): boolean {
  const d1 = cross(d.x - c.x, d.y - c.y, a.x - c.x, a.y - c.y);
  const d2 = cross(d.x - c.x, d.y - c.y, b.x - c.x, b.y - c.y);
  const d3 = cross(b.x - a.x, b.y - a.y, c.x - a.x, c.y - a.y);
  const d4 = cross(b.x - a.x, b.y - a.y, d.x - a.x, d.y - a.y);
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
      ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
    return true;
  }
  // 共線且重疊 → 視為相交（保守）
  if (d1 === 0 && onSegment(c, d, a)) return true;
  if (d2 === 0 && onSegment(c, d, b)) return true;
  if (d3 === 0 && onSegment(a, b, c)) return true;
  if (d4 === 0 && onSegment(a, b, d)) return true;
  return false;
}

function cross(ax: number, ay: number, bx: number, by: number): number {
  return ax * by - ay * bx;
}

function onSegment(a: WrapPolygonPoint, b: WrapPolygonPoint, p: WrapPolygonPoint): boolean {
  return (
    Math.min(a.x, b.x) <= p.x && p.x <= Math.max(a.x, b.x) &&
    Math.min(a.y, b.y) <= p.y && p.y <= Math.max(a.y, b.y)
  );
}
