/**
 * Phase 8.2.2 overlay 幾何工具 — Sprint 291。
 *
 * 為 doc_editor.js 的 overlay 拖曳 / resize / 對齊輔助線抽出純函式工具。
 * 純 stateless、不依賴 DOM / OWL / RPC，可獨立單元測試。
 *
 * 設計：
 *   - clampPosToBounds：把 rect 位置 clamp 到 page bounds（拖曳越界限制）
 *   - clampSizeToBounds：把 rect 尺寸 clamp 到 page bounds（resize 越界限制）
 *   - computeAlignGuides：拖曳中計算對齊輔助線（page edge/center + sibling edge/center）
 *
 * 紀律 #18 scope-down：本 sprint 為 utility extraction + tests；doc_editor.js
 * 既有 clamp 邏輯仍 inline（保留現行行為），未來 polish sprint 才接此 utility。
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Bounds {
  width: number;
  height: number;
}

/**
 * 把 rect 的位置 clamp 到 [0, bounds.width - rect.width] × [0, bounds.height - rect.height]。
 *
 * - rect 比 bounds 大時：clamp 到 0（位置）；caller 自行決定 size 是否要 clamp
 * - 負座標 → 0
 * - 超出右下 → 對應 max
 */
export function clampPosToBounds(rect: Rect, bounds: Bounds): { x: number; y: number } {
  const maxX = Math.max(0, bounds.width - rect.width);
  const maxY = Math.max(0, bounds.height - rect.height);
  const x = Math.min(Math.max(0, rect.x), maxX);
  const y = Math.min(Math.max(0, rect.y), maxY);
  return { x, y };
}

/**
 * 把 rect 的尺寸 clamp 到 [minW, bounds.width - rect.x] × [minH, bounds.height - rect.y]。
 *
 * - 確保 minW/minH 下限
 * - 確保不越過 page 右/下緣（從當前 x/y 算可用空間）
 * - 若 x + minW > bounds.width 時 width 退化為 (bounds.width - x)（可能小於 minW）
 */
export function clampSizeToBounds(
  rect: Rect,
  bounds: Bounds,
  minW: number,
  minH: number,
): { width: number; height: number } {
  const maxW = Math.max(0, bounds.width - rect.x);
  const maxH = Math.max(0, bounds.height - rect.y);
  // 先套上限、再套下限 — 若 maxW < minW 則回 maxW（不可能拉到 minW）
  const cappedW = Math.min(rect.width, maxW);
  const cappedH = Math.min(rect.height, maxH);
  const width = maxW >= minW ? Math.max(cappedW, minW) : cappedW;
  const height = maxH >= minH ? Math.max(cappedH, minH) : cappedH;
  return { width, height };
}

export type AlignAxis = 'x' | 'y';
export type AlignReason =
  | 'page-edge-start'
  | 'page-edge-end'
  | 'page-center'
  | 'sibling-edge-start'
  | 'sibling-edge-end'
  | 'sibling-center';

export interface AlignGuide {
  axis: AlignAxis;
  /** 對齊吸附值（pt 或 px、與 caller bounds 同單位） */
  value: number;
  reason: AlignReason;
  /** 命中該 guide 的 sibling rect 索引；page guide 為 undefined */
  siblingIndex?: number;
}

/**
 * 拖曳時計算對齊輔助線候選清單。
 *
 * 對齊規則：
 *   X 軸：
 *     - moving.x ↔ 0（page 左緣）/ bounds.width（page 右緣）/ bounds.width/2（page 中線）
 *     - moving.x ↔ sibling.x（左對齊）/ sibling.x + sibling.width（右對齊）/ sibling.x + sibling.width/2（中對齊）
 *   Y 軸：同理用 moving.y / bounds.height / sibling.y
 *
 * threshold 內的所有候選都回（caller 視覺化全部 guide、實際 snap 取最近一條）。
 */
export function computeAlignGuides(
  moving: Rect,
  siblings: readonly Rect[],
  pageBounds: Bounds,
  threshold: number,
): AlignGuide[] {
  const guides: AlignGuide[] = [];

  const tryX = (candidate: number, reason: AlignReason, siblingIndex?: number) => {
    if (Math.abs(moving.x - candidate) <= threshold) {
      guides.push({ axis: 'x', value: candidate, reason, siblingIndex });
    }
  };
  const tryY = (candidate: number, reason: AlignReason, siblingIndex?: number) => {
    if (Math.abs(moving.y - candidate) <= threshold) {
      guides.push({ axis: 'y', value: candidate, reason, siblingIndex });
    }
  };

  // Page edges + center
  tryX(0, 'page-edge-start');
  tryX(pageBounds.width - moving.width, 'page-edge-end');
  tryX((pageBounds.width - moving.width) / 2, 'page-center');
  tryY(0, 'page-edge-start');
  tryY(pageBounds.height - moving.height, 'page-edge-end');
  tryY((pageBounds.height - moving.height) / 2, 'page-center');

  // Sibling edges + center
  siblings.forEach((s, i) => {
    tryX(s.x, 'sibling-edge-start', i);
    tryX(s.x + s.width - moving.width, 'sibling-edge-end', i);
    tryX(s.x + (s.width - moving.width) / 2, 'sibling-center', i);
    tryY(s.y, 'sibling-edge-start', i);
    tryY(s.y + s.height - moving.height, 'sibling-edge-end', i);
    tryY(s.y + (s.height - moving.height) / 2, 'sibling-center', i);
  });

  return guides;
}

/**
 * 取最近的對齊吸附結果（X 軸 + Y 軸 各一條）。
 *
 * computeAlignGuides 回所有 threshold 內候選；本函式選 X / Y 軸各最接近 moving 當前值的一條，
 * 用於 mousemove 真正套用 snap。
 */
export function pickSnapTargets(
  moving: Rect,
  guides: readonly AlignGuide[],
): { snapX?: AlignGuide; snapY?: AlignGuide } {
  let snapX: AlignGuide | undefined;
  let snapY: AlignGuide | undefined;
  let bestDx = Infinity;
  let bestDy = Infinity;
  for (const g of guides) {
    if (g.axis === 'x') {
      const d = Math.abs(moving.x - g.value);
      if (d < bestDx) { bestDx = d; snapX = g; }
    } else {
      const d = Math.abs(moving.y - g.value);
      if (d < bestDy) { bestDy = d; snapY = g; }
    }
  }
  return { snapX, snapY };
}
