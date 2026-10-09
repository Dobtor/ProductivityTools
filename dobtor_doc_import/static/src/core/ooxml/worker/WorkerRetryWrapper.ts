/**
 * WorkerRetryWrapper — Sprint 327。
 *
 * Sprint 292/294/299/307/312/317/322 worker cluster 第七輪深推。Wrap 一個
 * dispatcher、在 transient error（如 timeout / parse-error）發生時自動重試、
 * 配合 exponential backoff。
 *
 * 範圍：
 *   - 對每個 requestId 維護 retry counter
 *   - error response 進來時：若 attempts < maxAttempts → 重 post（同 request、
 *     可能用 backoff 延遲）；否則向 listeners propagate error
 *   - success response → 清 retry state、propagate
 *   - timeout 機制由 caller 處理（caller 用 ParseWorkerHarness、本層只處理 error response）
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體 retry state、caller 提供 clock 與 schedule fn（用於延遲 retry）
 *   - 不做半 jitter / 自動 jitter（caller 想要自行包）
 *   - 不做 circuit-breaker 邏輯（用 Sprint 317 WorkerCircuitBreaker 組合）
 *
 * 紀律 #21：composes a dispatcher、不改其內部行為；dispose 時 fan-out terminate。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

export interface WorkerRetryWrapperOptions {
  dispatcher: ParseWorkerDispatcher;
  /** 最大嘗試次數（含首次）；< 1 視為 1。預設 3 */
  maxAttempts?: number;
  /** 基底 backoff（ms）；retry n 次延遲 = baseBackoffMs * (2 ^ (n-1))。預設 100 */
  baseBackoffMs?: number;
  /** 上限 backoff（ms）；預設 5000 */
  maxBackoffMs?: number;
  /**
   * Caller 提供 schedule fn（用 setTimeout / requestIdleCallback 等）；
   * 預設 = setTimeout。測試用可注入同步 scheduler。
   */
  schedule?: (fn: () => void, delayMs: number) => void;
  /**
   * 哪些 error reason 可重試。預設 = ['parse-error', 'timeout', 'cancelled']
   * （與 ParseWorkerResponse 中的 reason 對齊）。
   */
  retryableReasons?: ReadonlyArray<string>;
}

export interface RetryStats {
  /** 完成的 request 數（含 retry 後最終 success / 最終 error） */
  completed: number;
  /** 已 retry 過的次數累計 */
  retries: number;
  /** 最終 success（不論用了幾次 attempts） */
  finalSuccess: number;
  /** 最終 error（用完 attempts 仍失敗） */
  finalError: number;
  /** 當前 inflight 中的 request 數 */
  inflightCount: number;
}

interface InflightState {
  request: ParseWorkerRequest;
  attempts: number;
}

const DEFAULT_RETRYABLE: ReadonlyArray<string> = ['parse-error', 'timeout', 'cancelled'];

export class WorkerRetryWrapper implements ParseWorkerDispatcher {
  private readonly inner: ParseWorkerDispatcher;
  private readonly maxAttempts: number;
  private readonly baseBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly schedule: (fn: () => void, delayMs: number) => void;
  private readonly retryableReasons: ReadonlyArray<string>;
  private readonly inflight = new Map<string, InflightState>();
  private readonly listeners = new Set<(r: ParseWorkerResponse) => void>();
  private readonly unsubInner: () => void;
  private completed = 0;
  private retries = 0;
  private finalSuccess = 0;
  private finalError = 0;
  private disposed = false;

  constructor(opts: WorkerRetryWrapperOptions) {
    this.inner = opts.dispatcher;
    this.maxAttempts = Math.max(1, opts.maxAttempts ?? 3);
    this.baseBackoffMs = opts.baseBackoffMs ?? 100;
    this.maxBackoffMs = opts.maxBackoffMs ?? 5000;
    this.schedule = opts.schedule ?? ((fn, delayMs) => { setTimeout(fn, delayMs); });
    this.retryableReasons = opts.retryableReasons ?? DEFAULT_RETRYABLE;
    this.unsubInner = this.inner.subscribe((r) => this.onResponse(r));
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    if ('requestId' in request && typeof request.requestId === 'string') {
      this.inflight.set(request.requestId, { request, attempts: 1 });
    }
    this.inner.post(request);
  }

  subscribe(listener: (r: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    try { this.unsubInner(); } catch { /* ignore */ }
    this.listeners.clear();
    this.inflight.clear();
    try { this.inner.terminate(); } catch { /* ignore */ }
  }

  getStats(): RetryStats {
    return {
      completed: this.completed,
      retries: this.retries,
      finalSuccess: this.finalSuccess,
      finalError: this.finalError,
      inflightCount: this.inflight.size,
    };
  }

  /** 重置 stats（保留 inflight）。 */
  clearStats(): void {
    this.completed = 0;
    this.retries = 0;
    this.finalSuccess = 0;
    this.finalError = 0;
  }

  private onResponse(resp: ParseWorkerResponse): void {
    if (this.disposed) return;
    if (!('requestId' in resp) || typeof resp.requestId !== 'string') {
      this.propagate(resp);
      return;
    }
    const state = this.inflight.get(resp.requestId);
    if (!state) {
      // 非 wrapper 追蹤的 response → 直接 propagate
      this.propagate(resp);
      return;
    }

    if (resp.kind === 'success') {
      this.inflight.delete(resp.requestId);
      this.completed++;
      this.finalSuccess++;
      this.propagate(resp);
      return;
    }
    if (resp.kind === 'error') {
      const canRetry = state.attempts < this.maxAttempts
        && this.retryableReasons.includes(resp.reason);
      if (canRetry) {
        state.attempts++;
        this.retries++;
        const delay = Math.min(
          this.baseBackoffMs * Math.pow(2, state.attempts - 2),
          this.maxBackoffMs,
        );
        this.schedule(() => {
          if (this.disposed) return;
          if (!this.inflight.has(state.request.requestId!)) return;
          this.inner.post(state.request);
        }, delay);
        return;
      }
      // 用完 attempts、放棄 retry
      this.inflight.delete(resp.requestId);
      this.completed++;
      this.finalError++;
      this.propagate(resp);
      return;
    }
    // 其他 response kind（如 progress）直接 propagate
    this.propagate(resp);
  }

  private propagate(resp: ParseWorkerResponse): void {
    for (const l of this.listeners) {
      try { l(resp); } catch { /* listener crash 不影響 */ }
    }
  }
}
