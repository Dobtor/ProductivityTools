/**
 * OverlaySelectionState — Sprint 311。
 *
 * Sprint 291/295/301/306 overlay 工具系列第三輪深推。本 sprint 補
 * single + multi selection 狀態機，整合 Sprint 301 多選 helpers。
 *
 * 場景：
 *   - 使用者點選 image overlay → single select
 *   - Cmd/Ctrl+click 另一個 overlay → add to multi-select
 *   - Shift+click → range select (or extend selection)
 *   - 拖框選取（marquee）→ replace selection with all rects within marquee
 *   - 點 empty area → clear selection
 *
 * 紀律 #18 scope-down：
 *   - 不接 doc_editor.js OWL real path（紀律 #21、同 295/301/306 政策）
 *   - 不做 keyboard navigation（caller 自管）
 *   - 不做 z-order / hit testing（caller 自決哪個 overlay 被 hit）
 *
 * 紀律 #21：純 stateful class、無 DOM 依賴；可在 browser / Node 都跑單元測試。
 */

export type SelectionMode = 'replace' | 'toggle' | 'add' | 'remove';

export interface SelectionChange {
  /** 之前的 selection（複本、不會被 mutate） */
  prev: ReadonlySet<string>;
  /** 之後的 selection（複本、不會被 mutate） */
  next: ReadonlySet<string>;
  /** 此次變動實際 add 的 ids */
  added: string[];
  /** 此次變動實際 remove 的 ids */
  removed: string[];
}

/**
 * Pure stateful selection set。
 *
 * Caller 用 id (string) 識別每個 overlay；OverlaySelectionState 不關心 id 對應到
 * 哪個 AST node、純做集合運算。
 *
 * 用法：
 *   const sel = new OverlaySelectionState();
 *   onClick(id, e): sel.select(id, e.metaKey ? 'toggle' : 'replace');
 *   onMarquee(ids): sel.replaceAll(ids);
 *   onEscape: sel.clear();
 *   getSelected: sel.getIds();
 */
export class OverlaySelectionState {
  private selected = new Set<string>();
  private listeners = new Set<(change: SelectionChange) => void>();

  /**
   * 對單一 id 套用 mode。
   *
   * - replace：清空後加入 id（單選）
   * - toggle：已在 selection 就移除、不在就加入（Cmd/Ctrl+click）
   * - add：加入（已在的不變）
   * - remove：移除（不在的不變）
   */
  select(id: string, mode: SelectionMode = 'replace'): SelectionChange {
    const prev = new Set(this.selected);
    if (mode === 'replace') {
      this.selected = new Set([id]);
    } else if (mode === 'toggle') {
      if (this.selected.has(id)) this.selected.delete(id);
      else this.selected.add(id);
    } else if (mode === 'add') {
      this.selected.add(id);
    } else {
      this.selected.delete(id);
    }
    return this.emit(prev);
  }

  /** 用一批 id 取代 selection（marquee 拖框、select-all 等場景）。 */
  replaceAll(ids: readonly string[]): SelectionChange {
    const prev = new Set(this.selected);
    this.selected = new Set(ids);
    return this.emit(prev);
  }

  /** 把一批 id 加入 selection（保留現有）。 */
  addAll(ids: readonly string[]): SelectionChange {
    const prev = new Set(this.selected);
    for (const id of ids) this.selected.add(id);
    return this.emit(prev);
  }

  /** 把一批 id 從 selection 移除。 */
  removeAll(ids: readonly string[]): SelectionChange {
    const prev = new Set(this.selected);
    for (const id of ids) this.selected.delete(id);
    return this.emit(prev);
  }

  /** 清空 selection。 */
  clear(): SelectionChange {
    const prev = new Set(this.selected);
    this.selected = new Set();
    return this.emit(prev);
  }

  /** 是否有任何 id 被選。 */
  hasSelection(): boolean {
    return this.selected.size > 0;
  }

  /** 是否為單選（恰好 1 個）。 */
  isSingle(): boolean {
    return this.selected.size === 1;
  }

  /** 是否為多選（>= 2）。 */
  isMulti(): boolean {
    return this.selected.size >= 2;
  }

  /** 當前 selection 大小。 */
  size(): number {
    return this.selected.size;
  }

  /** 是否包含特定 id。 */
  has(id: string): boolean {
    return this.selected.has(id);
  }

  /** 拿一份 selection 複本（不 mutate 不會影響內部狀態）。 */
  getIds(): string[] {
    return [...this.selected];
  }

  /** 註冊變更 listener（caller 用於 re-render UI）。 */
  subscribe(listener: (change: SelectionChange) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit(prev: Set<string>): SelectionChange {
    const next = new Set(this.selected);
    const added: string[] = [];
    const removed: string[] = [];
    for (const id of next) if (!prev.has(id)) added.push(id);
    for (const id of prev) if (!next.has(id)) removed.push(id);
    const change: SelectionChange = { prev, next, added, removed };
    if (added.length > 0 || removed.length > 0) {
      for (const l of this.listeners) {
        try {
          l(change);
        } catch {
          // listener crash 不影響其他
        }
      }
    }
    return change;
  }
}
