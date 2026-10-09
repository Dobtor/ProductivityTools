/**
 * wrap_polygon_metrics — Sprint 354。
 *
 * Sprint 296/.../344/349 polygon 系列第十三輪深推。前面都在「判斷相交 / 簡化 /
 * 排版」；本 sprint 補基礎 **幾何度量**，給 caller 排序 / 優先決策用：
 *
 *   - signedArea：帶號面積（shoelace）；正 = CCW、負 = CW
 *   - area：絕對面積
 *   - centroid：質心（面積加權）
 *   - perimeter：周長
 *   - windingDirection：'ccw' / 'cw' / 'degenerate'
 *
 * 用途：多 wrap region 時、依面積排序決定 layout 優先；或判斷 polygon 方向以
 * 統一 clip 演算法輸入。
 *
 * 紀律 #18 scope-down：
 *   - 不接 Layout real path（紀律 #21）
 *   - 假設簡單多邊形（非自交）；自交時 shoelace 結果未定義（caller 自負）
 *   - 不處理帶洞多邊形
 *
 * 紀律 #21：純函式幾何工具、不污染既有 pipeline。
 */

import type { WrapPolygonPoint } from '../ast/types';

/**
 * Shoelace 帶號面積。
 * 正 = 逆時針（CCW、數學座標）；負 = 順時針。
 * 點數 < 3 → 0。
 *
 * 注意：螢幕座標 Y 向下時方向感相反，caller 自行詮釋。
 */
export function signedArea(polygon: readonly WrapPolygonPoint[]): number {
  const n = polygon.length;
  if (n < 3) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const a = polygon[i];
    const b = polygon[(i + 1) % n];
    sum += a.x * b.y - b.x * a.y;
  }
  return sum / 2;
}

/** 絕對面積。 */
export function area(polygon: readonly WrapPolygonPoint[]): number {
  return Math.abs(signedArea(polygon));
}

/** 周長（含閉合邊；若 polygon 已顯式閉合首尾相同則該邊長 0、不影響）。 */
export function perimeter(polygon: readonly WrapPolygonPoint[]): number {
  const n = polygon.length;
  if (n < 2) return 0;
  let total = 0;
  for (let i = 0; i < n; i++) {
    const a = polygon[i];
    const b = polygon[(i + 1) % n];
    total += Math.hypot(b.x - a.x, b.y - a.y);
  }
  return total;
}

/**
 * 質心（面積加權 centroid）。
 *
 * - 點數 < 3 或退化（面積 0）→ 回頂點算術平均（fallback）
 */
export function centroid(polygon: readonly WrapPolygonPoint[]): WrapPolygonPoint {
  const n = polygon.length;
  if (n === 0) return { x: 0, y: 0 };
  const a2 = signedArea(polygon) * 2; // = 6*area 的分母基準
  if (n < 3 || a2 === 0) {
    // fallback：算術平均
    let sx = 0;
    let sy = 0;
    for (const p of polygon) {
      sx += p.x;
      sy += p.y;
    }
    return { x: sx / n, y: sy / n };
  }
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < n; i++) {
    const p = polygon[i];
    const q = polygon[(i + 1) % n];
    const cross = p.x * q.y - q.x * p.y;
    cx += (p.x + q.x) * cross;
    cy += (p.y + q.y) * cross;
  }
  const factor = 1 / (3 * a2);
  return { x: cx * factor, y: cy * factor };
}

export type WindingDirection = 'ccw' | 'cw' | 'degenerate';

/**
 * 繞行方向（依數學座標：正面積 = CCW）。
 * 面積 0 / 點數 < 3 → 'degenerate'。
 */
export function windingDirection(polygon: readonly WrapPolygonPoint[]): WindingDirection {
  const a = signedArea(polygon);
  if (a > 0) return 'ccw';
  if (a < 0) return 'cw';
  return 'degenerate';
}

/**
 * 確保 polygon 為指定繞行方向（不是則反轉）。回新 array。
 */
export function ensureWinding(
  polygon: readonly WrapPolygonPoint[],
  want: 'ccw' | 'cw',
): WrapPolygonPoint[] {
  const dir = windingDirection(polygon);
  const copy = polygon.map((p) => ({ ...p }));
  if (dir === 'degenerate') return copy;
  if (dir !== want) copy.reverse();
  return copy;
}

export interface PolygonMetrics {
  area: number;
  signedArea: number;
  perimeter: number;
  centroid: WrapPolygonPoint;
  winding: WindingDirection;
}

/** 一次算齊。 */
export function computeMetrics(polygon: readonly WrapPolygonPoint[]): PolygonMetrics {
  const sa = signedArea(polygon);
  return {
    area: Math.abs(sa),
    signedArea: sa,
    perimeter: perimeter(polygon),
    centroid: centroid(polygon),
    winding: sa > 0 ? 'ccw' : sa < 0 ? 'cw' : 'degenerate',
  };
}
