/**
 * Overlay 幾何工具 — multi-select / resize-by-handle extensions（Sprint 301）。
 *
 * 為 Sprint 291 overlay_geometry.ts 的 follow-up。Sprint 291 補 single rect 的
 * clamp + align guide；本 sprint 補：
 *
 *   - resizeRectByHandle：8 handle（NW/N/NE/E/SE/S/SW/W）resize 的 rect 計算
 *   - computeMultiSelectBounds：N rect 的群組 bounding box（multi-select bbox）
 *   - translateMultiSelect：群組 move with bounds clamp（保持相對位置）
 *   - alignMultiSelect：對齊多 rect（left / center-h / right / top / middle-v / bottom）
 *   - distributeMultiSelect：均勻分佈多 rect（X 或 Y 軸）
 *
 * 紀律 #18 scope-down：純 stateless 函式 + tests；doc_editor.js 未來 polish
 * sprint 才接此 utility（Sprint 291 同政策、避免破 13 Playwright E2E）。
 *
 * 紀律 #21：不污染既有 production module（從 components/doc_editor/ 下另開檔、
 * 與既有 overlay_geometry.ts 共存）。
 */

import type { Rect, Bounds } from './overlay_geometry';
import { clampPosToBounds, clampSizeToBounds } from './overlay_geometry';

// ── Resize by handle ──────────────────────────────────────────────────────

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';

export interface ResizeOptions {
  minW: number;
  minH: number;
  /** 是否依當前 aspect 比例鎖定（如按住 Shift）；預設 false */
  preserveAspect?: boolean;
  /** Page bounds；提供時 resize 結果不會超出頁面 */
  bounds?: Bounds;
}

/**
 * 從 origin rect + handle + delta（mouse 移動量）計算 resize 後的新 rect。
 *
 * 公式（以左上角為原點、向右+x、向下+y）：
 *   nw → x+=dx, y+=dy, w-=dx, h-=dy
 *   n  → y+=dy, h-=dy
 *   ne → y+=dy, w+=dx, h-=dy
 *   e  → w+=dx
 *   se → w+=dx, h+=dy
 *   s  → h+=dy
 *   sw → x+=dx, w-=dx, h+=dy
 *   w  → x+=dx, w-=dx
 *
 * 接著套用 minW / minH（若 w 或 h 縮到下限、x / y 對應反向修正以維持原 anchor 邊）。
 * Aspect lock 時用 dx / dy 較大者主導另一軸（按 origin aspect）。
 * bounds 提供時最後套 clamp。
 */
export function resizeRectByHandle(
  origin: Rect,
  handle: ResizeHandle,
  dx: number,
  dy: number,
  opts: ResizeOptions,
): Rect {
  let { minW, minH } = opts;
  if (minW <= 0) minW = 1;
  if (minH <= 0) minH = 1;

  let nx = origin.x;
  let ny = origin.y;
  let nw = origin.width;
  let nh = origin.height;

  // Apply per-handle deltas
  if (handle === 'nw' || handle === 'w' || handle === 'sw') { nx += dx; nw -= dx; }
  if (handle === 'ne' || handle === 'e' || handle === 'se') { nw += dx; }
  if (handle === 'nw' || handle === 'n' || handle === 'ne') { ny += dy; nh -= dy; }
  if (handle === 'sw' || handle === 's' || handle === 'se') { nh += dy; }

  // Aspect preservation：以單軸主導（取與原始 aspect 偏離較小的軸）
  if (opts.preserveAspect && origin.width > 0 && origin.height > 0) {
    const aspect = origin.width / origin.height;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const newH = nw / aspect;
      // 維持反向 anchor
      if (handle === 'nw' || handle === 'ne' || handle === 'n') {
        ny = origin.y + origin.height - newH;
      }
      nh = newH;
    } else {
      const newW = nh * aspect;
      if (handle === 'nw' || handle === 'sw' || handle === 'w') {
        nx = origin.x + origin.width - newW;
      }
      nw = newW;
    }
  }

  // Enforce min width/height — 反向 handle 需修正 x / y 以維持 anchor 邊
  if (nw < minW) {
    if (handle === 'nw' || handle === 'w' || handle === 'sw') {
      nx -= (minW - nw);
    }
    nw = minW;
  }
  if (nh < minH) {
    if (handle === 'nw' || handle === 'n' || handle === 'ne') {
      ny -= (minH - nh);
    }
    nh = minH;
  }

  let result: Rect = { x: nx, y: ny, width: nw, height: nh };

  if (opts.bounds) {
    const pos = clampPosToBounds(result, opts.bounds);
    result = { ...result, x: pos.x, y: pos.y };
    const sz = clampSizeToBounds(result, opts.bounds, minW, minH);
    result = { ...result, width: sz.width, height: sz.height };
  }
  return result;
}

// ── Multi-select bbox + translate ──────────────────────────────────────────

/** N rects 的群組 bounding box（min(x,y), max(x+w, y+h)）。 */
export function computeMultiSelectBounds(rects: readonly Rect[]): Rect | null {
  if (rects.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rects) {
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

/**
 * 群組 translate（拖曳整組）。各 rect 保持相對位置；若給 bounds、整體 bbox 不超出 page。
 *
 * 演算法：先算群組 bbox、決定 group delta（自身限制在 bounds 內），再 apply 給每個 rect。
 */
export function translateMultiSelect(
  rects: readonly Rect[],
  dx: number,
  dy: number,
  bounds?: Bounds,
): Rect[] {
  const bbox = computeMultiSelectBounds(rects);
  if (!bbox) return [];
  let appliedDx = dx;
  let appliedDy = dy;
  if (bounds) {
    const moved = { x: bbox.x + dx, y: bbox.y + dy, width: bbox.width, height: bbox.height };
    const clamped = clampPosToBounds(moved, bounds);
    appliedDx = clamped.x - bbox.x;
    appliedDy = clamped.y - bbox.y;
  }
  return rects.map((r) => ({ ...r, x: r.x + appliedDx, y: r.y + appliedDy }));
}

// ── Align multi-select ────────────────────────────────────────────────────

export type AlignMode = 'left' | 'center-h' | 'right' | 'top' | 'middle-v' | 'bottom';

/**
 * 對齊 N rects 至群組 bbox（不是 page）的指定邊 / 中線。
 *
 * - left / center-h / right：對齊 X 軸
 * - top / middle-v / bottom：對齊 Y 軸
 *
 * rects.length < 2 時直接回原陣列（無對齊意義）。
 */
export function alignMultiSelect(rects: readonly Rect[], mode: AlignMode): Rect[] {
  if (rects.length < 2) return rects.map((r) => ({ ...r }));
  const bbox = computeMultiSelectBounds(rects);
  if (!bbox) return rects.map((r) => ({ ...r }));

  return rects.map((r) => {
    switch (mode) {
      case 'left':
        return { ...r, x: bbox.x };
      case 'center-h':
        return { ...r, x: bbox.x + (bbox.width - r.width) / 2 };
      case 'right':
        return { ...r, x: bbox.x + bbox.width - r.width };
      case 'top':
        return { ...r, y: bbox.y };
      case 'middle-v':
        return { ...r, y: bbox.y + (bbox.height - r.height) / 2 };
      case 'bottom':
        return { ...r, y: bbox.y + bbox.height - r.height };
    }
  });
}

// ── Distribute multi-select ───────────────────────────────────────────────

export type DistributeAxis = 'horizontal' | 'vertical';

/**
 * 均勻分佈 N rects；首尾不動、中間按相等間隔重排。
 *
 * - horizontal：按 x + width/2 排序；間隔 = (lastCenter - firstCenter) / (n-1)
 * - vertical：同理用 y + height/2
 *
 * rects.length < 3 時直接回原陣列（< 3 無需分佈）。
 */
export function distributeMultiSelect(rects: readonly Rect[], axis: DistributeAxis): Rect[] {
  if (rects.length < 3) return rects.map((r) => ({ ...r }));
  const indexed = rects.map((r, i) => ({ r, i, center: axis === 'horizontal' ? r.x + r.width / 2 : r.y + r.height / 2 }));
  indexed.sort((a, b) => a.center - b.center);
  const first = indexed[0].center;
  const last = indexed[indexed.length - 1].center;
  const step = (last - first) / (indexed.length - 1);
  const out: Rect[] = rects.map((r) => ({ ...r }));
  for (let k = 1; k < indexed.length - 1; k++) {
    const desiredCenter = first + step * k;
    const item = indexed[k];
    if (axis === 'horizontal') {
      out[item.i] = { ...item.r, x: desiredCenter - item.r.width / 2 };
    } else {
      out[item.i] = { ...item.r, y: desiredCenter - item.r.height / 2 };
    }
  }
  return out;
}
