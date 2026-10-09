/**
 * WorkerHealthMonitor — Sprint 312。
 *
 * Sprint 292/294/299/307 worker dispatcher cluster 第三輪深推。本 sprint 補
 * **observability layer**：wrap 一個 dispatcher、追蹤每筆 request 的 latency
 * + success/error rate + timeout count。
 *
 * 用途：
 *   - 偵測 worker 異常（latency 飆升、error rate > 閾值）→ caller 切換 dispatcher
 *   - Production observability：把 stats 餵 monitoring（Grafana / Sentry / log）
 *   - 雙驗 baseline：比較 MainThread / NodeWorker / BrowserWorker latency
 *
 * 範圍（Strategy A wrap pattern）：
 *   - 對 inflight request 計時：post 記 startedAt、success/error response 算 elapsed
 *   - 累積 stats：count / mean / p50 / p95 / errorRate / timeoutRate
 *   - timeout 由 caller 注入（dispatcher 本身不知道；caller 用 ParseWorkerHarness
 *     的 timeout 已包含、本層只記時數）
 *
 * 紀律 #18 scope-down：
 *   - 不接 production monitoring（caller decide 怎麼 export）
 *   - 不主動 alert（caller 自決閾值）
 *   - 不做 sliding window（保 lifetime stats、caller 自管 reset）
 *
 * 紀律 #21：composes a dispatcher、不改 dispatcher 內部行為；dispose 時 fan-out
 *   terminate 給底層。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

export interface WorkerHealthStats {
  /** 累積 post 數 */
  postCount: number;
  /** 累積 success response 數 */
  successCount: number;
  /** 累積 error response 數 */
  errorCount: number;
  /** caller 顯式呼叫 recordTimeout 的累積數 */
  timeoutCount: number;
  /** 完成（success+error）的 request 平均 latency（ms） */
  meanLatencyMs: number;
  /** p50 latency（ms）；< 1 筆完成時 = 0 */
  p50LatencyMs: number;
  /** p95 latency（ms）；< 1 筆完成時 = 0 */
  p95LatencyMs: number;
  /** error / (success + error)；分母 0 時 = 0 */
  errorRate: number;
  /** 當前 inflight request 數 */
  inflightCount: number;
}

export interface WorkerHealthMonitorOptions {
  /** 底層 dispatcher（被 wrap） */
  dispatcher: ParseWorkerDispatcher;
  /** Caller 提供 now() 給可測試的時鐘（缺省 Date.now） */
  now?: () => number;
}

interface InflightEntry {
  startedAt: number;
}

export class WorkerHealthMonitor implements ParseWorkerDispatcher {
  private readonly inner: ParseWorkerDispatcher;
  private readonly now: () => number;
  private readonly inflight = new Map<string, InflightEntry>();
  private readonly latencies: number[] = [];
  private readonly listeners = new Set<(r: ParseWorkerResponse) => void>();
  private readonly unsubInner: () => void;
  private postCount = 0;
  private successCount = 0;
  private errorCount = 0;
  private timeoutCount = 0;
  private disposed = false;

  constructor(opts: WorkerHealthMonitorOptions) {
    this.inner = opts.dispatcher;
    this.now = opts.now ?? Date.now;
    this.unsubInner = this.inner.subscribe((resp) => this.onInnerResponse(resp));
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    this.postCount++;
    if ('requestId' in request && typeof request.requestId === 'string') {
      this.inflight.set(request.requestId, { startedAt: this.now() });
    }
    this.inner.post(request);
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
    try { this.unsubInner(); } catch { /* ignore */ }
    this.listeners.clear();
    this.inflight.clear();
    try { this.inner.terminate(); } catch { /* dispatcher self-throw 不影響 */ }
  }

  /**
   * Caller 顯式呼叫，記下某個 requestId 已 timeout（ParseWorkerHarness 端通常會
   * cancel + emit 一筆 'cancelled' response、但 monitor 想分開計 timeout 時呼叫）。
   *
   * 從 inflight 移除、累積 timeoutCount。
   */
  recordTimeout(requestId: string): void {
    if (this.inflight.delete(requestId)) {
      this.timeoutCount++;
    }
  }

  /** 取得 lifetime stats（不包含 percentile reset；caller reset 用 clearStats）。 */
  getStats(): WorkerHealthStats {
    const total = this.successCount + this.errorCount;
    let mean = 0;
    let p50 = 0;
    let p95 = 0;
    if (this.latencies.length > 0) {
      const sum = this.latencies.reduce((a, b) => a + b, 0);
      mean = sum / this.latencies.length;
      const sorted = [...this.latencies].sort((a, b) => a - b);
      p50 = sorted[Math.floor(sorted.length * 0.5)];
      p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))];
    }
    return {
      postCount: this.postCount,
      successCount: this.successCount,
      errorCount: this.errorCount,
      timeoutCount: this.timeoutCount,
      meanLatencyMs: mean,
      p50LatencyMs: p50,
      p95LatencyMs: p95,
      errorRate: total === 0 ? 0 : this.errorCount / total,
      inflightCount: this.inflight.size,
    };
  }

  /** 重置 stats（測試 / production 定期 reset 用）。 */
  clearStats(): void {
    this.latencies.length = 0;
    this.postCount = 0;
    this.successCount = 0;
    this.errorCount = 0;
    this.timeoutCount = 0;
  }

  private onInnerResponse(resp: ParseWorkerResponse): void {
    if (this.disposed) return;
    // 計時：從 inflight 取 startedAt、算 elapsed
    if ('requestId' in resp && typeof resp.requestId === 'string') {
      const entry = this.inflight.get(resp.requestId);
      if (entry) {
        const elapsed = this.now() - entry.startedAt;
        this.latencies.push(elapsed);
        this.inflight.delete(resp.requestId);
      }
    }
    if (resp.kind === 'success') this.successCount++;
    else if (resp.kind === 'error') this.errorCount++;
    // 轉發給 monitor 的 listeners
    for (const l of this.listeners) {
      try { l(resp); } catch { /* listener crash 不影響 */ }
    }
  }
}
