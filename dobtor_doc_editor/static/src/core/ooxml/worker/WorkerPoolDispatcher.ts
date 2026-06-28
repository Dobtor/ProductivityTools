/**
 * WorkerPoolDispatcher — Sprint 307。
 *
 * Sprint 292 / 294 / 299 補了 worker dispatcher cluster（MainThread fallback +
 * Node worker_threads + browser Worker）；本 sprint 補 **pool 層**：把 N 個
 * dispatcher 包成一個 ParseWorkerDispatcher、用 round-robin 分配 request。
 *
 * 用途：
 *   - 多 core 機器同時跑多份 parse、提升 throughput（CPU-bound 場景）
 *   - 主程式只 hold 一個 ParseWorkerHarness、底層自動分配到 worker pool
 *   - mix-and-match：同 pool 內可放 Node + Browser dispatcher（caller 自選）
 *
 * 紀律 #18 scope-down：
 *   - 純 round-robin（不做 least-busy / least-pending）
 *     真實 workload-aware 排程需要 dispatcher 暴露「目前 pending count」，
 *     當前 ParseWorkerDispatcher interface 無此資訊；follow-up sprint 可擴
 *   - 不主動 spawn worker（caller 自建 N 個 dispatcher、傳入 pool）
 *   - 不做 worker crash recovery（dispatcher fail 時 propagate response、
 *     caller 視 timeout 處理）
 *
 * 紀律 #21：composes existing dispatchers、不污染既有 dispatcher 內部行為；
 *   dispose 時 fan-out terminate 給所有底層 dispatcher。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

export interface WorkerPoolDispatcherOptions {
  /** 底層 dispatcher 陣列；至少 1 個。 */
  dispatchers: ParseWorkerDispatcher[];
}

/**
 * Round-robin pool。每個 request 派發到「下一個」dispatcher（modulo N）；
 * subscribe / terminate fan-out 到全部底層。
 */
export class WorkerPoolDispatcher implements ParseWorkerDispatcher {
  private readonly pool: ParseWorkerDispatcher[];
  private readonly listeners = new Set<(response: ParseWorkerResponse) => void>();
  private readonly unsubscribers: Array<() => void> = [];
  private nextIndex = 0;
  private disposed = false;
  /** requestId → pool index 對位（保證 same request 的 response 不論從哪個 worker 來都能轉發） */
  private readonly inflight = new Map<string, number>();

  constructor(opts: WorkerPoolDispatcherOptions) {
    if (!opts.dispatchers || opts.dispatchers.length === 0) {
      throw new Error('[WorkerPoolDispatcher] dispatchers must have at least 1 entry');
    }
    this.pool = [...opts.dispatchers];
    // fan-out subscribe：任一底層 response → 通知 pool listeners
    for (const d of this.pool) {
      const unsub = d.subscribe((resp) => {
        // 清 inflight 記錄
        if ('requestId' in resp && typeof resp.requestId === 'string') {
          this.inflight.delete(resp.requestId);
        }
        for (const l of this.listeners) {
          try { l(resp); } catch { /* listener crash 不影響其他 */ }
        }
      });
      this.unsubscribers.push(unsub);
    }
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    const idx = this.nextIndex % this.pool.length;
    this.nextIndex++;
    if ('requestId' in request && typeof request.requestId === 'string') {
      this.inflight.set(request.requestId, idx);
    }
    this.pool[idx].post(request);
  }

  subscribe(listener: (response: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    // 先撤底層 subscribe（避免 terminate 期間還收到 response）
    for (const unsub of this.unsubscribers) {
      try { unsub(); } catch { /* ignore */ }
    }
    this.unsubscribers.length = 0;
    // fan-out terminate
    for (const d of this.pool) {
      try { d.terminate(); } catch { /* dispatcher 自己 throw 不影響其他 */ }
    }
    this.listeners.clear();
    this.inflight.clear();
  }

  /** Pool 大小（測試 / monitoring 用）。 */
  size(): number {
    return this.pool.length;
  }

  /** 當前未完成的 request 數（caller 想做 backpressure 判斷用）。 */
  inflightCount(): number {
    return this.inflight.size;
  }
}
