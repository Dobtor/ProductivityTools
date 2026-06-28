/**
 * OverlayClipboard — Sprint 346。
 *
 * Sprint 316 KeyboardCommands 產生 copy / cut / paste / duplicate command；
 * Sprint 326 OverlayCommandExecutor 處理 dispatch；但 **clipboard buffer 本身**
 * 一直沒人管。本 sprint 補純記憶體 clipboard model：
 *
 *   - copy(items)：存一份 payload snapshot
 *   - cut(items)：存 + 標記 source（caller paste 後刪原件）
 *   - paste(offset)：回 payload + 自動遞增 paste offset（多次貼上會階梯位移）
 *   - 提供 hasContent / clear / stats
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體；不接系統 clipboard API（navigator.clipboard）
 *   - payload generic、caller 自負序列化
 *   - 不做跨 doc / 跨 tab（用 Sprint 336 history snapshot 模式自己做）
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *
 * 紀律 #21：純資料 model；不污染 doc_editor.js。
 */

export interface ClipboardPayload<T> {
  items: ReadonlyArray<T>;
  /** 'copy' 來源保留原件；'cut' 來源 caller paste 後應刪 */
  mode: 'copy' | 'cut';
}

export interface PasteResult<T> {
  items: ReadonlyArray<T>;
  /** 第 N 次 paste（從 1 起算）；caller 用來算階梯位移 */
  pasteIndex: number;
  /** offset = pasteIndex * pasteStep（caller 套到 x/y） */
  offset: number;
  /** 來源 mode；'cut' 第一次 paste 後 caller 應刪原件 */
  sourceMode: 'copy' | 'cut';
  /** 此次 paste 是否為 cut 來源的第一次（caller 刪原件用） */
  isFirstCutPaste: boolean;
}

export interface OverlayClipboardOptions {
  /** 每次 paste 階梯位移量；預設 10 */
  pasteStep?: number;
}

export class OverlayClipboard<T> {
  private readonly pasteStep: number;
  private payload: ClipboardPayload<T> | null = null;
  private pasteCount = 0;
  /** cut 來源是否已被 paste 過（決定 isFirstCutPaste） */
  private cutConsumed = false;
  private copyOps = 0;
  private cutOps = 0;
  private pasteOps = 0;

  constructor(opts: OverlayClipboardOptions = {}) {
    this.pasteStep = opts.pasteStep ?? 10;
    if (this.pasteStep < 0) {
      throw new Error('[OverlayClipboard] pasteStep must be >= 0');
    }
  }

  copy(items: ReadonlyArray<T>): void {
    this.payload = { items: [...items], mode: 'copy' };
    this.pasteCount = 0;
    this.cutConsumed = false;
    this.copyOps += 1;
  }

  cut(items: ReadonlyArray<T>): void {
    this.payload = { items: [...items], mode: 'cut' };
    this.pasteCount = 0;
    this.cutConsumed = false;
    this.cutOps += 1;
  }

  /**
   * 取 payload + 階梯 offset。無內容 → null。
   *
   * cut 模式第一次 paste → isFirstCutPaste=true（caller 刪原件）；之後變 copy 行為。
   */
  paste(): PasteResult<T> | null {
    if (!this.payload) return null;
    this.pasteCount += 1;
    this.pasteOps += 1;
    const isFirstCutPaste = this.payload.mode === 'cut' && !this.cutConsumed;
    if (isFirstCutPaste) this.cutConsumed = true;
    return {
      items: this.payload.items,
      pasteIndex: this.pasteCount,
      offset: this.pasteCount * this.pasteStep,
      sourceMode: this.payload.mode,
      isFirstCutPaste,
    };
  }

  hasContent(): boolean {
    return this.payload !== null;
  }

  /** 預覽目前 buffer（不影響 paste count）。 */
  peek(): ClipboardPayload<T> | null {
    return this.payload;
  }

  clear(): void {
    this.payload = null;
    this.pasteCount = 0;
    this.cutConsumed = false;
  }

  getStats(): ClipboardStats {
    return {
      hasContent: this.payload !== null,
      itemCount: this.payload ? this.payload.items.length : 0,
      mode: this.payload ? this.payload.mode : null,
      pasteCount: this.pasteCount,
      copyOps: this.copyOps,
      cutOps: this.cutOps,
      pasteOps: this.pasteOps,
    };
  }
}

export interface ClipboardStats {
  hasContent: boolean;
  itemCount: number;
  mode: 'copy' | 'cut' | null;
  pasteCount: number;
  copyOps: number;
  cutOps: number;
  pasteOps: number;
}
