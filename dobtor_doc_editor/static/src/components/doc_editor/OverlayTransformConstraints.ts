/**
 * OverlayTransformConstraints — Sprint 351。
 *
 * Sprint 291 overlay_geometry（clampPos / clampSize / resizeRectByHandle）之後
 * 第十二輪深推。Sprint 291 已做基本邊界 clamp；本 sprint 補更高階的
 * **transform constraint solver**：
 *
 *   - grid snap：x/y/w/h 對齊網格
 *   - aspect ratio lock：resize 時維持寬高比
 *   - min/max size bounds
 *   - container bounds：不超出畫布範圍
 *
 * 純函式：吃一個 proposed rect、回 constrained rect。caller（doc_editor.js）拖拉
 * 時每幀呼叫。
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *   - 不做 rotation constraint（overlay 目前無旋轉）
 *   - 不做 multi-item 群組 constraint（caller 自己對每個 item 套）
 *
 * 紀律 #21：pure-fn；不污染 doc_editor.js。
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TransformConstraints {
  /** 網格大小（pt）；undefined / 0 → 不 snap */
  gridSize?: number;
  /** 維持寬高比（width/height）；undefined → 不鎖 */
  aspectRatio?: number;
  minWidth?: number;
  minHeight?: number;
  maxWidth?: number;
  maxHeight?: number;
  /** 容器邊界（rect 不可超出）；undefined → 不限制 */
  container?: Rect;
}

/** 把值對齊到最近的 grid 倍數。 */
export function snapToGrid(value: number, gridSize: number): number {
  if (gridSize <= 0) return value;
  return Math.round(value / gridSize) * gridSize;
}

/**
 * 套用 size bounds（min/max）到 width/height。
 */
function clampSize(
  width: number,
  height: number,
  c: TransformConstraints,
): { width: number; height: number } {
  let w = width;
  let h = height;
  if (c.minWidth !== undefined) w = Math.max(w, c.minWidth);
  if (c.minHeight !== undefined) h = Math.max(h, c.minHeight);
  if (c.maxWidth !== undefined) w = Math.min(w, c.maxWidth);
  if (c.maxHeight !== undefined) h = Math.min(h, c.maxHeight);
  return { width: w, height: h };
}

/**
 * 套 aspect ratio：以 width 為主、推導 height = width / aspectRatio。
 */
function applyAspect(
  width: number,
  height: number,
  aspectRatio: number,
): { width: number; height: number } {
  if (aspectRatio <= 0) return { width, height };
  // 以面積較接近原值的方式調整：固定 width、改 height
  return { width, height: width / aspectRatio };
}

/**
 * 把 rect clamp 進 container（位置 + 尺寸都不超界）。
 */
function clampToContainer(rect: Rect, container: Rect): Rect {
  let { x, y, width, height } = rect;
  // 尺寸不超過 container
  width = Math.min(width, container.width);
  height = Math.min(height, container.height);
  // 位置 clamp：右下不超出
  x = Math.max(container.x, Math.min(x, container.x + container.width - width));
  y = Math.max(container.y, Math.min(y, container.y + container.height - height));
  return { x, y, width, height };
}

/**
 * 完整套用約束到 proposed rect。
 *
 * 套用順序：
 *   1. aspect ratio（先鎖比例）
 *   2. size bounds（min/max）
 *   3. grid snap（x/y/w/h）
 *   4. container clamp（最後確保不超界）
 */
export function applyConstraints(rect: Rect, c: TransformConstraints): Rect {
  let width = rect.width;
  let height = rect.height;

  if (c.aspectRatio !== undefined) {
    const a = applyAspect(width, height, c.aspectRatio);
    width = a.width;
    height = a.height;
  }

  const sized = clampSize(width, height, c);
  width = sized.width;
  height = sized.height;

  let x = rect.x;
  let y = rect.y;
  if (c.gridSize !== undefined && c.gridSize > 0) {
    x = snapToGrid(x, c.gridSize);
    y = snapToGrid(y, c.gridSize);
    width = snapToGrid(width, c.gridSize);
    height = snapToGrid(height, c.gridSize);
    // snap 後可能破壞 min bound、再 clamp 一次
    const reSized = clampSize(width, height, c);
    width = reSized.width;
    height = reSized.height;
  }

  let result: Rect = { x, y, width, height };
  if (c.container) {
    result = clampToContainer(result, c.container);
  }
  return result;
}

/**
 * 純移動（不改尺寸）的約束：grid snap + container clamp。
 */
export function applyMoveConstraints(rect: Rect, c: TransformConstraints): Rect {
  let x = rect.x;
  let y = rect.y;
  if (c.gridSize !== undefined && c.gridSize > 0) {
    x = snapToGrid(x, c.gridSize);
    y = snapToGrid(y, c.gridSize);
  }
  let result: Rect = { x, y, width: rect.width, height: rect.height };
  if (c.container) {
    result = clampToContainer(result, c.container);
  }
  return result;
}
