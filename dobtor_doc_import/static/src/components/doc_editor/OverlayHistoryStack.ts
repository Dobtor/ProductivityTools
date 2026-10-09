/**
 * OverlayHistoryStack — Sprint 321。
 *
 * Sprint 291/295/301/306/311/316 overlay 系列第五輪深推。本 sprint 補：
 * undo/redo 棧、追蹤 overlay 操作歷史。
 *
 * 設計：caller 把每個 overlay 操作（move / resize / delete / property change）
 * 包成 HistoryEntry（含 forward action + reverse action）push 進 stack。
 * undo → 執行 reverse；redo → 重新執行 forward。
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *   - 不做 transaction batch（caller 自管多步驟合併為單一 entry）
 *   - 不持久化（純記憶體；caller 想存 localStorage 自管 serialize/deserialize）
 *   - entry payload 為 caller-defined（generic）；本層不關心其結構
 *
 * 紀律 #21：純 stateful class、無 DOM 依賴。
 */

/**
 * 一筆操作的雙向記錄：caller 必須提供「正向」與「反向」兩個 action 描述。
 * Stack 不執行 action（caller 自己 apply），只負責管理順序與當前 cursor。
 *
 * Payload 為 caller-defined generic（如 { kind: 'move', id, before: {x,y}, after: {x,y} }）。
 */
export interface HistoryEntry<P> {
  /** Caller-defined payload（描述這次操作） */
  payload: P;
  /** Human-readable label（caller 想顯示 "Undo Move" 用） */
  label?: string;
}

export interface HistoryStackOptions {
  /** 最大保留筆數；超過時 evict 最舊。預設 100。 */
  maxEntries?: number;
}

export type HistoryListener<P> = (event: HistoryEvent<P>) => void;

export interface HistoryEvent<P> {
  kind: 'push' | 'undo' | 'redo' | 'clear';
  /** 對應的 entry（kind=clear 時為 undefined） */
  entry?: HistoryEntry<P>;
  /** 操作後當前 cursor 狀態 */
  canUndo: boolean;
  canRedo: boolean;
}

export class OverlayHistoryStack<P> {
  private readonly entries: HistoryEntry<P>[] = [];
  /** cursor 指向「下一個要 push 的位置」；undo 之後 cursor 往前、redo 之後 cursor 往後 */
  private cursor = 0;
  private readonly maxEntries: number;
  private listeners = new Set<HistoryListener<P>>();

  constructor(opts: HistoryStackOptions = {}) {
    this.maxEntries = opts.maxEntries ?? 100;
  }

  /**
   * Push 一筆新 entry：
   *   - 若 cursor 不在末端（剛 undo 過、有未消費 redo）→ 丟棄 redo 後段
   *   - cursor++（指向下一個 push 位置 = entries.length）
   *   - 超過 maxEntries 時 evict 最舊（cursor 對應修正）
   */
  push(entry: HistoryEntry<P>): void {
    // 丟棄 cursor 之後的 entries（redo 路徑無效）
    if (this.cursor < this.entries.length) {
      this.entries.length = this.cursor;
    }
    this.entries.push(entry);
    this.cursor = this.entries.length;
    // Evict 最舊
    while (this.entries.length > this.maxEntries) {
      this.entries.shift();
      this.cursor--;
    }
    this.emit({ kind: 'push', entry, canUndo: this.canUndo(), canRedo: this.canRedo() });
  }

  /**
   * 後退一步：cursor 往前移、回 cursor 指向的 entry（caller apply reverse action）。
   * 無可 undo → undefined。
   */
  undo(): HistoryEntry<P> | undefined {
    if (!this.canUndo()) return undefined;
    this.cursor--;
    const entry = this.entries[this.cursor];
    this.emit({ kind: 'undo', entry, canUndo: this.canUndo(), canRedo: this.canRedo() });
    return entry;
  }

  /**
   * 前進一步：caller apply forward action、cursor 往後移、回該 entry。
   * 無可 redo → undefined。
   */
  redo(): HistoryEntry<P> | undefined {
    if (!this.canRedo()) return undefined;
    const entry = this.entries[this.cursor];
    this.cursor++;
    this.emit({ kind: 'redo', entry, canUndo: this.canUndo(), canRedo: this.canRedo() });
    return entry;
  }

  /** cursor > 0。 */
  canUndo(): boolean {
    return this.cursor > 0;
  }

  /** cursor < entries.length。 */
  canRedo(): boolean {
    return this.cursor < this.entries.length;
  }

  /** 當前 entries 數量（含未 cursor 過的）。 */
  size(): number {
    return this.entries.length;
  }

  /** 當前 cursor 位置。 */
  position(): number {
    return this.cursor;
  }

  /** peek 但不移動 cursor：下一個會被 undo 的 entry。 */
  peekUndo(): HistoryEntry<P> | undefined {
    return this.canUndo() ? this.entries[this.cursor - 1] : undefined;
  }

  /** peek 但不移動 cursor：下一個會被 redo 的 entry。 */
  peekRedo(): HistoryEntry<P> | undefined {
    return this.canRedo() ? this.entries[this.cursor] : undefined;
  }

  /** 清空全部歷史（caller 想重置時用）。 */
  clear(): void {
    this.entries.length = 0;
    this.cursor = 0;
    this.emit({ kind: 'clear', canUndo: false, canRedo: false });
  }

  /** 註冊 listener（caller 用於 UI button enable/disable）。 */
  subscribe(listener: HistoryListener<P>): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private emit(event: HistoryEvent<P>): void {
    for (const l of this.listeners) {
      try { l(event); } catch { /* listener crash 不影響其他 */ }
    }
  }
}
