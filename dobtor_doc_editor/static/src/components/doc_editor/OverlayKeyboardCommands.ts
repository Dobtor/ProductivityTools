/**
 * OverlayKeyboardCommands — Sprint 316。
 *
 * Sprint 291/295/301/306/311 overlay 系列第四輪深推。本 sprint 補 pure-fn：
 * 給 keyboard event 摘要 + 當前 selection state、回應該執行的 overlay 操作。
 *
 * 範圍：
 *   - mapKeyToCommand：keyboard event → OverlayCommand（delete / nudge /
 *     resize / select-all / escape / copy / paste / undo / redo）
 *   - 區分 Cmd / Ctrl（Mac vs Windows）— caller 傳 platform
 *   - Shift 修飾 → 大步 nudge（10pt vs 1pt）
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21、同 295/301/306/311 政策）
 *   - 不處理 IME composition 中的 key events（caller 自管 compositionend 等）
 *   - copy/paste 只回 command name、不負責 clipboard 互動
 */

export type OverlayCommand =
  | { kind: 'delete' }
  | { kind: 'nudge'; dx: number; dy: number }
  | { kind: 'select-all' }
  | { kind: 'clear-selection' }
  | { kind: 'copy' }
  | { kind: 'paste' }
  | { kind: 'cut' }
  | { kind: 'undo' }
  | { kind: 'redo' }
  | { kind: 'duplicate' }
  | { kind: 'noop' };

export type Platform = 'mac' | 'pc';

/**
 * Caller 把 KeyboardEvent 拿到的相關欄位濃縮成這個結構（避免依賴 DOM）。
 */
export interface KeyEventLike {
  key: string;
  /** 'a', 'A', 'Backspace', 'ArrowLeft' 等 */
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
}

export interface MapKeyOptions {
  /** Mac 用 Cmd / PC 用 Ctrl 作為 modifier */
  platform: Platform;
  /** 是否有 selection（無 selection 時 delete / nudge 為 noop） */
  hasSelection: boolean;
  /** Shift 修飾的大步距，預設 10pt */
  nudgeBig?: number;
  /** 一般步距，預設 1pt */
  nudgeSmall?: number;
}

/**
 * 把 keyboard event 映射為 overlay command。
 *
 * 對應表（subset of common UX）：
 *   - Backspace / Delete：delete（hasSelection 才生效）
 *   - Arrow*：nudge（hasSelection 才生效；Shift 大步）
 *   - Mod+A：select-all
 *   - Escape：clear-selection
 *   - Mod+C / Mod+X / Mod+V：copy / cut / paste
 *   - Mod+Z / Mod+Shift+Z：undo / redo
 *   - Mod+D：duplicate
 *   - 其他：noop
 *
 * Mod = Cmd on mac、Ctrl on pc。
 */
export function mapKeyToCommand(event: KeyEventLike, opts: MapKeyOptions): OverlayCommand {
  const mod = opts.platform === 'mac' ? !!event.metaKey : !!event.ctrlKey;
  const shift = !!event.shiftKey;
  const big = opts.nudgeBig ?? 10;
  const small = opts.nudgeSmall ?? 1;
  const step = shift ? big : small;

  // 單鍵 key 名稱（注意 ' ' 與字母大小寫）
  const k = event.key;

  // selection 必要 commands
  if (k === 'Backspace' || k === 'Delete') {
    return opts.hasSelection ? { kind: 'delete' } : { kind: 'noop' };
  }
  if (k === 'ArrowLeft') return opts.hasSelection ? { kind: 'nudge', dx: -step, dy: 0 } : { kind: 'noop' };
  if (k === 'ArrowRight') return opts.hasSelection ? { kind: 'nudge', dx: step, dy: 0 } : { kind: 'noop' };
  if (k === 'ArrowUp') return opts.hasSelection ? { kind: 'nudge', dx: 0, dy: -step } : { kind: 'noop' };
  if (k === 'ArrowDown') return opts.hasSelection ? { kind: 'nudge', dx: 0, dy: step } : { kind: 'noop' };
  if (k === 'Escape') return { kind: 'clear-selection' };

  // Modifier-driven
  if (mod) {
    const key = k.toLowerCase();
    if (key === 'a') return { kind: 'select-all' };
    if (key === 'c') return opts.hasSelection ? { kind: 'copy' } : { kind: 'noop' };
    if (key === 'x') return opts.hasSelection ? { kind: 'cut' } : { kind: 'noop' };
    if (key === 'v') return { kind: 'paste' };
    if (key === 'd') return opts.hasSelection ? { kind: 'duplicate' } : { kind: 'noop' };
    if (key === 'z') return shift ? { kind: 'redo' } : { kind: 'undo' };
  }
  return { kind: 'noop' };
}
