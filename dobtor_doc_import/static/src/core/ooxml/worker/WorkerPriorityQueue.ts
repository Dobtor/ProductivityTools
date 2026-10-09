/**
 * WorkerPriorityQueue — Sprint 347。
 *
 * Sprint 292/294/299/307/312/317/322/327/332/337/342 worker 系列第十一輪深推。
 * Sprint 307 WorkerPoolDispatcher 是 round-robin、不分輕重；本 sprint 補
 * **priority queue**：caller 想讓某些 parse request 先跑（例如可視區域 > 背景頁）。
 *
 *   - enqueue(item, priority)：priority 越大越優先
 *   - dequeue()：取最高優先（同優先 → FIFO）
 *   - aging：等越久的 item 有效優先逐步提升、避免低優先 starvation
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體 queue model；caller 自己接到 dispatcher
 *   - 不接 production worker real path（紀律 #21）
 *   - O(n) dequeue（線性掃描）；caller 量大時自換 heap（本 spike 不做 binary heap）
 *
 * 紀律 #21：純資料 model；不污染既有 worker pipeline。
 */

export interface QueueItem<T> {
  value: T;
  /** 基礎優先度（越大越優先） */
  basePriority: number;
  /** 入列時間（caller now() 注入、給 aging 用） */
  enqueuedAtMs: number;
  /** 入列序號（同 effective priority 時 FIFO tie-break） */
  seq: number;
}

export interface WorkerPriorityQueueOptions {
  /**
   * Aging：每等待 agingIntervalMs 毫秒、effective priority +agingBoost。
   * agingBoost=0 → 關閉 aging（純 static priority）。
   */
  agingIntervalMs?: number;
  agingBoost?: number;
  /** Caller 注入 now()；缺省 Date.now */
  now?: () => number;
}

export class WorkerPriorityQueue<T> {
  private readonly items: QueueItem<T>[] = [];
  private readonly agingIntervalMs: number;
  private readonly agingBoost: number;
  private readonly now: () => number;
  private seqCounter = 0;
  private enqueuedTotal = 0;
  private dequeuedTotal = 0;

  constructor(opts: WorkerPriorityQueueOptions = {}) {
    this.agingIntervalMs = opts.agingIntervalMs ?? 0;
    this.agingBoost = opts.agingBoost ?? 0;
    if (this.agingIntervalMs < 0 || this.agingBoost < 0) {
      throw new Error('[WorkerPriorityQueue] aging params must be >= 0');
    }
    this.now = opts.now ?? (() => Date.now());
  }

  enqueue(value: T, basePriority = 0): void {
    this.items.push({
      value,
      basePriority,
      enqueuedAtMs: this.now(),
      seq: this.seqCounter++,
    });
    this.enqueuedTotal += 1;
  }

  /**
   * effective priority = basePriority + aging boost。
   * aging boost = floor(waited / agingIntervalMs) * agingBoost（agingBoost=0 → 無）。
   */
  effectivePriority(item: QueueItem<T>, atMs: number): number {
    if (this.agingBoost === 0 || this.agingIntervalMs === 0) return item.basePriority;
    const waited = atMs - item.enqueuedAtMs;
    const steps = Math.floor(waited / this.agingIntervalMs);
    return item.basePriority + steps * this.agingBoost;
  }

  /**
   * 取最高 effective priority；同 priority → FIFO（seq 小者先）。
   * 空 queue → undefined。
   */
  dequeue(): T | undefined {
    if (this.items.length === 0) return undefined;
    const atMs = this.now();
    let bestIdx = 0;
    let bestPrio = this.effectivePriority(this.items[0], atMs);
    for (let i = 1; i < this.items.length; i++) {
      const prio = this.effectivePriority(this.items[i], atMs);
      if (
        prio > bestPrio ||
        (prio === bestPrio && this.items[i].seq < this.items[bestIdx].seq)
      ) {
        bestPrio = prio;
        bestIdx = i;
      }
    }
    const [removed] = this.items.splice(bestIdx, 1);
    this.dequeuedTotal += 1;
    return removed.value;
  }

  /** 看下一個會出列的（不移除）。 */
  peek(): T | undefined {
    if (this.items.length === 0) return undefined;
    const atMs = this.now();
    let bestIdx = 0;
    let bestPrio = this.effectivePriority(this.items[0], atMs);
    for (let i = 1; i < this.items.length; i++) {
      const prio = this.effectivePriority(this.items[i], atMs);
      if (
        prio > bestPrio ||
        (prio === bestPrio && this.items[i].seq < this.items[bestIdx].seq)
      ) {
        bestPrio = prio;
        bestIdx = i;
      }
    }
    return this.items[bestIdx].value;
  }

  size(): number {
    return this.items.length;
  }

  isEmpty(): boolean {
    return this.items.length === 0;
  }

  clear(): void {
    this.items.length = 0;
  }

  getStats(): PriorityQueueStats {
    return {
      size: this.items.length,
      enqueuedTotal: this.enqueuedTotal,
      dequeuedTotal: this.dequeuedTotal,
    };
  }
}

export interface PriorityQueueStats {
  size: number;
  enqueuedTotal: number;
  dequeuedTotal: number;
}
