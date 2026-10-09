/**
 * OverlayCommandExecutor — Sprint 326。
 *
 * Sprint 291/295/301/306/311/316/321 overlay 系列第七輪深推。本 sprint 整合：
 *
 *   - Sprint 311 OverlaySelectionState（selection set）
 *   - Sprint 316 OverlayKeyboardCommands（key event → OverlayCommand）
 *   - Sprint 321 OverlayHistoryStack（undo/redo）
 *
 * 提供 caller 單一 API：把 key event 轉成 command、執行對應動作、自動記錄
 * 到 history、回 caller 應該做什麼（apply / undo / etc）。
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21、同政策）
 *   - 不執行真實的 DOM 變動；只回 ActionDescription（caller 自 apply）
 *   - 不做 IME composition
 *
 * 紀律 #21：composes existing modules、不改其內部行為；caller 顯式呼叫才生效。
 */

import {
  OverlaySelectionState,
} from './OverlaySelectionState';
import {
  mapKeyToCommand,
  type KeyEventLike,
  type OverlayCommand,
  type Platform,
} from './OverlayKeyboardCommands';
import {
  OverlayHistoryStack,
  type HistoryEntry,
} from './OverlayHistoryStack';

/**
 * Executor 對外回的「該做什麼」描述。Caller 自負 apply 到真實 overlay。
 *
 * - `kind: 'apply'`：caller 套用 command（如 delete selected、nudge by dx/dy 等）；
 *   `recordable=true` 時 executor 已寫進 history（caller 不需另記）
 * - `kind: 'apply-from-history'`：caller 套用 history entry（undo / redo）
 * - `kind: 'noop'`：什麼都不做
 */
export type ExecutorAction<P> =
  | { kind: 'apply'; command: OverlayCommand; recordable: boolean }
  | { kind: 'apply-from-history'; direction: 'undo' | 'redo'; entry: HistoryEntry<P> }
  | { kind: 'noop' };

/**
 * Caller 傳的 payload factory：取 command + 當前 selection ids、產生 HistoryEntry payload。
 * 若回 null，executor 不記 history（適合 noop-like commands、或 caller 自記）。
 */
export type PayloadFactory<P> = (command: OverlayCommand, selection: ReadonlyArray<string>) => P | null;

export interface OverlayCommandExecutorOptions<P> {
  selection: OverlaySelectionState;
  history: OverlayHistoryStack<P>;
  platform: Platform;
  /** 把 command 轉 history payload；null 表示不記 */
  payloadFactory?: PayloadFactory<P>;
  /** Mod+Z / Mod+Shift+Z 是否由 executor 自動處理 undo / redo；預設 true */
  autoHandleUndoRedo?: boolean;
}

/**
 * 把 keyboard event 轉為 overlay action。
 *
 * 流程：
 *   1. mapKeyToCommand 得 OverlayCommand
 *   2. 若 command 是 undo / redo 且 autoHandleUndoRedo=true → 處理 history
 *      回 'apply-from-history' 給 caller
 *   3. 其他 command：若 payloadFactory 提供且回 non-null → push history
 *      回 'apply' with recordable=true
 *   4. noop → 回 noop
 *
 * Selection 操作（select-all / clear-selection）：由 executor 直接動 SelectionState、
 *   並回 'apply'（caller 仍需 re-render UI）。
 */
export class OverlayCommandExecutor<P> {
  private readonly selection: OverlaySelectionState;
  private readonly history: OverlayHistoryStack<P>;
  private readonly platform: Platform;
  private readonly payloadFactory?: PayloadFactory<P>;
  private readonly autoHandleUndoRedo: boolean;

  constructor(opts: OverlayCommandExecutorOptions<P>) {
    this.selection = opts.selection;
    this.history = opts.history;
    this.platform = opts.platform;
    this.payloadFactory = opts.payloadFactory;
    this.autoHandleUndoRedo = opts.autoHandleUndoRedo ?? true;
  }

  /**
   * 處理 keyboard event：轉 command + dispatch。
   */
  handleKey(event: KeyEventLike): ExecutorAction<P> {
    const command = mapKeyToCommand(event, {
      platform: this.platform,
      hasSelection: this.selection.hasSelection(),
    });
    return this.dispatch(command);
  }

  /**
   * 直接 dispatch 已知 command（caller toolbar button onClick 用）。
   */
  dispatch(command: OverlayCommand): ExecutorAction<P> {
    // undo / redo：自動處理 history
    if (this.autoHandleUndoRedo) {
      if (command.kind === 'undo') {
        const entry = this.history.undo();
        return entry
          ? { kind: 'apply-from-history', direction: 'undo', entry }
          : { kind: 'noop' };
      }
      if (command.kind === 'redo') {
        const entry = this.history.redo();
        return entry
          ? { kind: 'apply-from-history', direction: 'redo', entry }
          : { kind: 'noop' };
      }
    }

    // selection-only commands：直接動 SelectionState
    if (command.kind === 'clear-selection') {
      this.selection.clear();
      return { kind: 'apply', command, recordable: false };
    }
    // select-all 由 caller 提供 ids；executor 不知道 overlays 全集，回 apply 讓 caller 自處理

    if (command.kind === 'noop') return { kind: 'noop' };

    // 其他 commands：若 caller 有 payloadFactory、push history
    let recordable = false;
    if (this.payloadFactory) {
      const payload = this.payloadFactory(command, this.selection.getIds());
      if (payload !== null) {
        this.history.push({ payload, label: this.labelOf(command) });
        recordable = true;
      }
    }
    return { kind: 'apply', command, recordable };
  }

  /** 提供給 caller 直接 push history（用於非鍵盤 trigger 的操作、如滑鼠拖曳完成後）。 */
  recordToHistory(entry: HistoryEntry<P>): void {
    this.history.push(entry);
  }

  private labelOf(command: OverlayCommand): string {
    switch (command.kind) {
      case 'delete': return 'Delete';
      case 'nudge': return `Nudge (${command.dx}, ${command.dy})`;
      case 'duplicate': return 'Duplicate';
      case 'paste': return 'Paste';
      case 'cut': return 'Cut';
      case 'copy': return 'Copy';
      case 'select-all': return 'Select All';
      default: return command.kind;
    }
  }
}
