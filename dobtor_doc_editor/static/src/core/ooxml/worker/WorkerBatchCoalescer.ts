/**
 * WorkerBatchCoalescer — Sprint 357。
 *
 * Sprint 307 pool / Sprint 347 priority queue / Sprint 352 scheduler 之後深推。
 * 大量小 parse request 逐筆 dispatch 有 per-message overhead；本 sprint 補
 * **batch coalescing**：在時間 window 內收集 request、達 maxBatchSize 或 flush
 * 時機到 → 一次 flush 成 batch 交給 caller。
 *
 *   - add(item)：加入 pending；達 maxBatchSize → 立即 flush
 *   - flush()：手動 flush 當前 pending（caller 在 timer / idle 時呼叫）
 *   - schedule 可注入（測試用 sync）；caller 提供 onFlush(batch)
 *
 * 紀律 #18 scope-down：
 *   - 純收集 / flush 邏輯；caller 提供 onFlush callback + flush timer
 *   - 不接 production worker real path（紀律 #21）
 *   - 不做 per-item priority（用 Sprint 347 在 batch 內排）
 *
 * 紀律 #21：純調度 model；不污染既有 worker pipeline。
 */

export interface WorkerBatchCoalescerOptions<T> {
  /** 累積到此數量立即 flush；預設 16 */
  maxBatchSize?: number;
  /** flush callback：caller 拿到一批 item 自行 dispatch */
  onFlush: (batch: T[]) => void;
}

export class WorkerBatchCoalescer<T> {
  private readonly maxBatchSize: number;
  private readonly onFlush: (batch: T[]) => void;
  private pending: T[] = [];
  private flushCount = 0;
  private itemCount = 0;
  private autoFlushCount = 0;

  constructor(opts: WorkerBatchCoalescerOptions<T>) {
    this.maxBatchSize = opts.maxBatchSize ?? 16;
    if (this.maxBatchSize <= 0) {
      throw new Error('[WorkerBatchCoalescer] maxBatchSize must be > 0');
    }
    this.onFlush = opts.onFlush;
  }

  /**
   * 加入一個 item。達 maxBatchSize → 立即 auto-flush。
   */
  add(item: T): void {
    this.pending.push(item);
    this.itemCount += 1;
    if (this.pending.length >= this.maxBatchSize) {
      this.autoFlushCount += 1;
      this.flush();
    }
  }

  /**
   * 加入多個（caller 一次塞一串）。可能觸發多次 auto-flush。
   */
  addAll(items: ReadonlyArray<T>): void {
    for (const it of items) this.add(it);
  }

  /**
   * 手動 flush 當前 pending（空 → no-op、不呼叫 onFlush）。
   */
  flush(): void {
    if (this.pending.length === 0) return;
    const batch = this.pending;
    this.pending = [];
    this.flushCount += 1;
    this.onFlush(batch);
  }

  /** 當前 pending 數。 */
  pendingCount(): number {
    return this.pending.length;
  }

  /** 丟棄 pending（不 flush）。 */
  discard(): number {
    const n = this.pending.length;
    this.pending = [];
    return n;
  }

  getStats(): BatchCoalescerStats {
    return {
      pending: this.pending.length,
      flushCount: this.flushCount,
      itemCount: this.itemCount,
      autoFlushCount: this.autoFlushCount,
    };
  }
}

export interface BatchCoalescerStats {
  pending: number;
  flushCount: number;
  itemCount: number;
  autoFlushCount: number;
}
