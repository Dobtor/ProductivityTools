/**
 * WorkerScheduler — Sprint 352。
 *
 * Sprint 347 WorkerPriorityQueue 之後深推。Priority queue 只管「下一個該跑誰」；
 * 本 sprint 補 **scheduler**：從 queue pull、依 maxConcurrent 限流 dispatch、
 * 追 inflight、完成後自動 pull 下一個。
 *
 *   - submit(value, priority)：入 queue + 嘗試 pump
 *   - onComplete(token)：標記某 inflight 完成 + pump 下一個
 *   - pump：在 concurrency 上限內把 queue 內 item dispatch 出去
 *   - caller 提供 dispatch(value, token)：實際送到 worker（本 module 不接 worker）
 *
 * 紀律 #18 scope-down：
 *   - 純調度邏輯；caller 提供 dispatch callback、自己接 dispatcher
 *   - 不做 retry（用 Sprint 327 retry wrapper 組合）
 *   - 不做 timeout（caller 自管、complete 時回報）
 *   - 不接 production worker real path（紀律 #21）
 *
 * 紀律 #21：純調度 model；組合 Sprint 347 queue；不污染既有 worker pipeline。
 */

import { WorkerPriorityQueue } from './WorkerPriorityQueue';

export interface WorkerSchedulerOptions<T> {
  /** 同時最多幾個 inflight；預設 1（序列） */
  maxConcurrent?: number;
  /** caller 提供：把 value dispatch 出去（回 token 由 scheduler 給） */
  dispatch: (value: T, token: number) => void;
  /** 傳給內部 priority queue（aging 等） */
  now?: () => number;
  agingIntervalMs?: number;
  agingBoost?: number;
}

export class WorkerScheduler<T> {
  private readonly queue: WorkerPriorityQueue<T>;
  private readonly maxConcurrent: number;
  private readonly dispatch: (value: T, token: number) => void;
  private readonly inflight = new Set<number>();
  private tokenCounter = 0;
  private dispatchedTotal = 0;
  private completedTotal = 0;

  constructor(opts: WorkerSchedulerOptions<T>) {
    this.maxConcurrent = opts.maxConcurrent ?? 1;
    if (this.maxConcurrent <= 0) {
      throw new Error('[WorkerScheduler] maxConcurrent must be > 0');
    }
    this.dispatch = opts.dispatch;
    this.queue = new WorkerPriorityQueue<T>({
      now: opts.now,
      agingIntervalMs: opts.agingIntervalMs,
      agingBoost: opts.agingBoost,
    });
  }

  /**
   * 提交一個工作；入 queue 後嘗試 pump。
   */
  submit(value: T, priority = 0): void {
    this.queue.enqueue(value, priority);
    this.pump();
  }

  /**
   * 在 concurrency 上限內、把 queue item dispatch 出去。
   * 每 dispatch 一個就 inflight++ 並呼叫 caller dispatch。
   */
  private pump(): void {
    while (this.inflight.size < this.maxConcurrent && !this.queue.isEmpty()) {
      const value = this.queue.dequeue();
      if (value === undefined) break;
      const token = this.tokenCounter++;
      this.inflight.add(token);
      this.dispatchedTotal += 1;
      this.dispatch(value, token);
    }
  }

  /**
   * caller 在某 inflight 完成（成功 / 失敗都算完成）時呼叫。
   * 釋放 concurrency slot + pump 下一個。
   *
   * @returns 是否確實有此 token 在 inflight（false = unknown token）
   */
  onComplete(token: number): boolean {
    if (!this.inflight.has(token)) return false;
    this.inflight.delete(token);
    this.completedTotal += 1;
    this.pump();
    return true;
  }

  /** 當前 inflight 數。 */
  inflightCount(): number {
    return this.inflight.size;
  }

  /** queue 內待處理數。 */
  pendingCount(): number {
    return this.queue.size();
  }

  /** 是否全空閒（無 inflight 也無 pending）。 */
  isIdle(): boolean {
    return this.inflight.size === 0 && this.queue.isEmpty();
  }

  getStats(): SchedulerStats {
    return {
      maxConcurrent: this.maxConcurrent,
      inflight: this.inflight.size,
      pending: this.queue.size(),
      dispatchedTotal: this.dispatchedTotal,
      completedTotal: this.completedTotal,
    };
  }
}

export interface SchedulerStats {
  maxConcurrent: number;
  inflight: number;
  pending: number;
  dispatchedTotal: number;
  completedTotal: number;
}
