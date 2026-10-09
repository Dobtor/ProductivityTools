/**
 * OverlayTouchMapper — Sprint 331。
 *
 * Sprint 291/295/301/306/311/316/321/326 overlay 系列第八輪深推。Sprint 316
 * 已做 keyboard → command；本 sprint 補 **touch / pointer gesture** → command。
 *
 * 場景：行動裝置 / 平板 overlay 互動。caller 已從 DOM PointerEvent 抽出 normalize
 * 後的 PointerSnapshot，本 module 純 pure-fn classifyGesture → mapToCommand。
 *
 * 範圍：
 *   - classifyTap：given press duration + move distance → tap / long-press / drag
 *   - recognizePinch：given 2 個 pointer snapshot 對 → scale + delta
 *   - mapGestureToCommand：gesture → OverlayCommand（複用 Sprint 316 type）
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *   - 不做 momentum / inertia / flick
 *   - 不負責 multi-touch >2、3指以上 caller 自處理
 *   - PointerSnapshot 由 caller normalize、本 module 不直接吃 PointerEvent
 *
 * 紀律 #21：pure-fn、不污染 doc_editor.js。
 */

import type { OverlayCommand } from './OverlayKeyboardCommands';

/**
 * Caller 從原始 PointerEvent 抽出的最小 snapshot（避免依賴 DOM）。
 */
export interface PointerSnapshot {
  id: number;
  x: number;
  y: number;
  /** 按下時間（ms epoch、performance.now、或 caller 自選單位） */
  timestamp: number;
}

export type GestureKind = 'tap' | 'long-press' | 'drag' | 'pinch' | 'two-finger-drag' | 'unknown';

export interface ClassifyTapOptions {
  /** Long-press 認定為 long-press 的最短毫秒、預設 500ms */
  longPressMs?: number;
  /** 移動距離超過則歸為 drag 而非 tap、預設 8（caller 單位） */
  dragThreshold?: number;
}

/**
 * Single-touch press → tap / long-press / drag。
 *
 * - moveDistance > dragThreshold → 'drag'
 * - duration >= longPressMs → 'long-press'
 * - 其他 → 'tap'
 */
export function classifyTap(
  durationMs: number,
  moveDistance: number,
  opts: ClassifyTapOptions = {},
): 'tap' | 'long-press' | 'drag' {
  const dragThreshold = opts.dragThreshold ?? 8;
  const longPressMs = opts.longPressMs ?? 500;
  if (moveDistance > dragThreshold) return 'drag';
  if (durationMs >= longPressMs) return 'long-press';
  return 'tap';
}

export interface PinchResult {
  /** 兩指起始距離 → 結束距離的比值 */
  scale: number;
  /** 中心點移動 dx / dy（end - start） */
  dx: number;
  dy: number;
}

/**
 * Two-touch start/end snapshots → pinch scale + center drift。
 *
 * - start[].length !== 2 或 end[].length !== 2 → null
 * - 起始距離 0 → null（避免除零）
 */
export function recognizePinch(
  start: readonly PointerSnapshot[],
  end: readonly PointerSnapshot[],
): PinchResult | null {
  if (start.length !== 2 || end.length !== 2) return null;
  const sDist = Math.hypot(start[0].x - start[1].x, start[0].y - start[1].y);
  const eDist = Math.hypot(end[0].x - end[1].x, end[0].y - end[1].y);
  if (sDist === 0) return null;
  const sCx = (start[0].x + start[1].x) / 2;
  const sCy = (start[0].y + start[1].y) / 2;
  const eCx = (end[0].x + end[1].x) / 2;
  const eCy = (end[0].y + end[1].y) / 2;
  return { scale: eDist / sDist, dx: eCx - sCx, dy: eCy - sCy };
}

export interface MapGestureOptions {
  hasSelection: boolean;
  /** long-press 對應 command 種類；預設 'duplicate' */
  longPressCommand?: 'duplicate' | 'copy' | 'noop';
  /** Two-finger drag 對應 command kind 預設 'nudge' */
  twoFingerDragNudge?: { dx: number; dy: number };
}

/**
 * 把 gesture kind + 補充資訊映射為 OverlayCommand。
 *
 * - 'tap'：noop（caller 自決定 select-at-point 行為、不歸本 module）
 * - 'long-press' + hasSelection：依 opts.longPressCommand
 * - 'drag' + hasSelection：caller 自處理位移（本 module 回 noop）
 * - 'pinch' / 'two-finger-drag'：caller 提供具體 command
 *
 * 純資料 mapping、不假設「應該發生什麼」、把控制權留給 caller。
 */
export function mapGestureToCommand(
  gesture: GestureKind,
  opts: MapGestureOptions,
): OverlayCommand {
  if (gesture === 'long-press') {
    if (!opts.hasSelection) return { kind: 'noop' };
    switch (opts.longPressCommand ?? 'duplicate') {
      case 'duplicate':
        return { kind: 'duplicate' };
      case 'copy':
        return { kind: 'copy' };
      default:
        return { kind: 'noop' };
    }
  }
  if (gesture === 'two-finger-drag' && opts.twoFingerDragNudge) {
    return { kind: 'nudge', dx: opts.twoFingerDragNudge.dx, dy: opts.twoFingerDragNudge.dy };
  }
  return { kind: 'noop' };
}

/**
 * Caller 紀錄手勢 stats（除錯 / telemetry 用）。
 */
export interface GestureStats {
  taps: number;
  longPresses: number;
  drags: number;
  pinches: number;
  twoFingerDrags: number;
}

export function createGestureStats(): GestureStats {
  return { taps: 0, longPresses: 0, drags: 0, pinches: 0, twoFingerDrags: 0 };
}

export function recordGesture(stats: GestureStats, gesture: GestureKind): void {
  if (gesture === 'tap') stats.taps += 1;
  else if (gesture === 'long-press') stats.longPresses += 1;
  else if (gesture === 'drag') stats.drags += 1;
  else if (gesture === 'pinch') stats.pinches += 1;
  else if (gesture === 'two-finger-drag') stats.twoFingerDrags += 1;
}
