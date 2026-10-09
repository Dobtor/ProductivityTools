/**
 * WrapPolygon render helpers — Sprint 304。
 *
 * Sprint 296 補了 polygon 幾何 pure-fn（transform / bbox / pointIn / rectIntersect）、
 * Sprint 298 把 polygon 接進 LineBreaker。本 sprint 補 **render side** 工具：
 *
 *   - polygonToSvgPath：polygon 點陣列 → SVG `path d=` 字串
 *   - polygonToCanvasPath：polygon → Path2D-compatible commands（Canvas 用）
 *   - applyClipPathToContext：把 polygon 設為 Canvas2D clip region
 *   - polygonWithInflate：caller 想留 padding 給文字繞圖時膨脹 polygon
 *
 * 範圍（Strategy A spike）：
 *   - 純 pure-fn / 接受 polygon 點陣列、回 path string 或 Path2D commands
 *   - 不接 production CanvasRenderer 主路徑（紀律 #21、避免破現有 wrap render）
 *   - 不解決「image content 也要 clip」的複雜場景（caller 自行 decide canvas
 *     layer 順序）
 *
 * 紀律 #18 scope-down：
 *   - 不支援 Bezier curve polygon 平滑（OOXML wrapPolygon spec 是線段折線）
 *   - 不做 polygon simplification（caller 應在 transform 階段拿到 raw polygon）
 *   - clip path 只支援 even-odd fill rule（OOXML 慣例；非零繞數 caller 自行對應）
 */

import type { WrapPolygonPoint } from '../ast/types';

/**
 * Polygon → SVG `path d=` 字串。
 *
 * 範例：`M 10 20 L 50 20 L 50 80 L 10 80 Z`
 *
 * - 空 polygon → 空字串
 * - 單點 polygon → 仍輸出 `M x y Z`（caller 視覺看不到、但 SVG 仍 valid）
 */
export function polygonToSvgPath(polygon: readonly WrapPolygonPoint[]): string {
  if (polygon.length === 0) return '';
  const segments: string[] = [];
  for (let i = 0; i < polygon.length; i++) {
    const p = polygon[i];
    if (i === 0) {
      segments.push(`M ${p.x} ${p.y}`);
    } else {
      segments.push(`L ${p.x} ${p.y}`);
    }
  }
  segments.push('Z');
  return segments.join(' ');
}

/**
 * Canvas Path2D command 序列（caller 可一筆筆 apply 給 CanvasRenderingContext2D）。
 *
 * 範例 commands 序列：
 *   [{ op: 'moveTo', x: 10, y: 20 }, { op: 'lineTo', x: 50, y: 20 }, { op: 'closePath' }]
 *
 * caller 拿到後可選擇：
 *   - 用 Path2D + ctx.clip(path)（modern browser）
 *   - 或一條條呼叫 ctx.moveTo / ctx.lineTo / ctx.closePath（legacy fallback）
 */
export type CanvasPolygonCommand =
  | { op: 'moveTo'; x: number; y: number }
  | { op: 'lineTo'; x: number; y: number }
  | { op: 'closePath' };

export function polygonToCanvasCommands(polygon: readonly WrapPolygonPoint[]): CanvasPolygonCommand[] {
  if (polygon.length === 0) return [];
  const out: CanvasPolygonCommand[] = [];
  for (let i = 0; i < polygon.length; i++) {
    const p = polygon[i];
    out.push(i === 0 ? { op: 'moveTo', x: p.x, y: p.y } : { op: 'lineTo', x: p.x, y: p.y });
  }
  out.push({ op: 'closePath' });
  return out;
}

/**
 * 把 polygon 套用為 Canvas2D 的 clip region。
 *
 * - caller 應在呼叫前 ctx.save()、呼叫後 ctx.restore() 才不會污染後續繪圖
 * - 使用 even-odd fill rule（OOXML wrapPolygon 慣例）
 *
 * caller 拿到的最簡 ctx 型別（避免 import 完整 CanvasRenderingContext2D 型別）。
 */
export interface MinimalCanvasContext {
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  clip(fillRule?: CanvasFillRule): void;
}

export function applyClipPathToContext(
  ctx: MinimalCanvasContext,
  polygon: readonly WrapPolygonPoint[],
): void {
  if (polygon.length === 0) return;
  ctx.beginPath();
  for (let i = 0; i < polygon.length; i++) {
    const p = polygon[i];
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.closePath();
  ctx.clip('evenodd');
}

/**
 * 把 polygon 沿著 bbox 中心向外膨脹 `delta`（caller 想留 padding 給文字環繞）。
 *
 * 算法：每個 vertex 相對於 bbox center 的方向向量 × (1 + delta / radius)，
 * 最終 vertex = center + new_dir * old_dist。
 *
 * - delta = 0 → 原 polygon
 * - delta > 0 → 外擴
 * - delta < 0 → 內縮（caller 視覺要小於 image 用）
 *
 * 簡化（紀律 #18）：用 bbox-center radial scale；非嚴格的「邊向法向量 outset」，
 * 但對大多數 image wrap polygon（凸形或近凸）夠用。caller 真有 inset stroke 需求
 * 時可 follow-up 補 Minkowski sum 算法。
 */
export function polygonWithInflate(polygon: readonly WrapPolygonPoint[], delta: number): WrapPolygonPoint[] {
  if (polygon.length === 0 || delta === 0) return polygon.map((p) => ({ ...p }));
  // bbox center
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of polygon) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return polygon.map((p) => {
    const dx = p.x - cx;
    const dy = p.y - cy;
    const dist = Math.hypot(dx, dy);
    if (dist === 0) return { x: p.x, y: p.y };
    const scale = (dist + delta) / dist;
    return { x: cx + dx * scale, y: cy + dy * scale };
  });
}
