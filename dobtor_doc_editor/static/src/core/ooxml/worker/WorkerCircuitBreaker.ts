/**
 * WorkerCircuitBreaker — Sprint 317。
 *
 * Sprint 292/294/299/307/312 worker cluster 第四輪深推。Composes 一個 primary
 * dispatcher + fallback dispatcher、用 circuit breaker pattern 監控 primary：
 *
 *   - **closed** state：primary 接受所有 post；錯誤率超閾值 / latency 超閾值 → open
 *   - **open** state：所有 post 直接 route 給 fallback；經過 cooldown 後 → half-open
 *   - **half-open** state：放 1 個 probe request 試 primary；成功 → closed、
 *     失敗 → 回 open
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體 state machine、caller 提供 clock；不做持久化
 *   - 錯誤統計用 sliding window；本實作為簡化版「最近 N 筆」（不依時間切窗）
 *   - 不主動定時 retry（caller 必須 post 才 trigger half-open transition）
 *
 * 紀律 #21：composes dispatchers、不改 dispatcher 內部行為；dispose 時 fan-out
 *   terminate 給 primary + fallback。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

export type BreakerState = 'closed' | 'open' | 'half-open';

export interface WorkerCircuitBreakerOptions {
  /** 主要 dispatcher（健康時用） */
  primary: ParseWorkerDispatcher;
  /** Fallback dispatcher（primary down 時用） */
  fallback: ParseWorkerDispatcher;
  /**
   * 錯誤率閾值（0..1）。最近 windowSize 筆 response 中 errorCount/total >= 此值 → open。
   * 預設 0.5。
   */
  errorRateThreshold?: number;
  /** sliding window 大小（response 筆數）；預設 10 */
  windowSize?: number;
  /** 觸發 open 的最小完成樣本數；< 此值不啟動 breaker。預設 5 */
  minSamples?: number;
  /** open → half-open 的 cooldown（ms）。預設 5000 */
  cooldownMs?: number;
  /** 測試用時鐘；缺省 Date.now */
  now?: () => number;
}

export interface CircuitBreakerStats {
  state: BreakerState;
  /** 累積 primary 成功數 */
  primarySuccess: number;
  /** 累積 primary 錯誤數 */
  primaryError: number;
  /** 累積 fallback 成功數 */
  fallbackSuccess: number;
  /** 累積 fallback 錯誤數 */
  fallbackError: number;
  /** sliding window 內 primary error 比率 */
  recentErrorRate: number;
  /** 進入 open 的次數 */
  openCount: number;
}

interface ResponseEntry {
  isError: boolean;
}

export class WorkerCircuitBreaker implements ParseWorkerDispatcher {
  private readonly primary: ParseWorkerDispatcher;
  private readonly fallback: ParseWorkerDispatcher;
  private readonly errorRateThreshold: number;
  private readonly windowSize: number;
  private readonly minSamples: number;
  private readonly cooldownMs: number;
  private readonly now: () => number;
  private state: BreakerState = 'closed';
  private window: ResponseEntry[] = [];
  private openedAt = 0;
  private halfOpenProbeId: string | undefined;
  private routing = new Map<string, 'primary' | 'fallback'>();
  private listeners = new Set<(r: ParseWorkerResponse) => void>();
  private readonly unsubPrimary: () => void;
  private readonly unsubFallback: () => void;
  private primarySuccess = 0;
  private primaryError = 0;
  private fallbackSuccess = 0;
  private fallbackError = 0;
  private openCount = 0;
  private disposed = false;

  constructor(opts: WorkerCircuitBreakerOptions) {
    this.primary = opts.primary;
    this.fallback = opts.fallback;
    this.errorRateThreshold = opts.errorRateThreshold ?? 0.5;
    this.windowSize = opts.windowSize ?? 10;
    this.minSamples = opts.minSamples ?? 5;
    this.cooldownMs = opts.cooldownMs ?? 5000;
    this.now = opts.now ?? Date.now;
    this.unsubPrimary = this.primary.subscribe((r) => this.onResponse(r, 'primary'));
    this.unsubFallback = this.fallback.subscribe((r) => this.onResponse(r, 'fallback'));
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    // 先檢查是否該從 open 進 half-open（cooldown 過了）
    if (this.state === 'open' && this.now() - this.openedAt >= this.cooldownMs) {
      this.state = 'half-open';
      this.halfOpenProbeId = undefined;
    }

    const route: 'primary' | 'fallback' = this.pickRoute(request);
    if ('requestId' in request && typeof request.requestId === 'string') {
      this.routing.set(request.requestId, route);
      if (this.state === 'half-open' && route === 'primary' && this.halfOpenProbeId === undefined) {
        this.halfOpenProbeId = request.requestId;
      }
    }
    (route === 'primary' ? this.primary : this.fallback).post(request);
  }

  subscribe(listener: (r: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    try { this.unsubPrimary(); } catch { /* ignore */ }
    try { this.unsubFallback(); } catch { /* ignore */ }
    this.listeners.clear();
    this.routing.clear();
    try { this.primary.terminate(); } catch { /* dispatcher self-throw 不影響 */ }
    try { this.fallback.terminate(); } catch { /* ignore */ }
  }

  getStats(): CircuitBreakerStats {
    const errs = this.window.filter((e) => e.isError).length;
    return {
      state: this.state,
      primarySuccess: this.primarySuccess,
      primaryError: this.primaryError,
      fallbackSuccess: this.fallbackSuccess,
      fallbackError: this.fallbackError,
      recentErrorRate: this.window.length === 0 ? 0 : errs / this.window.length,
      openCount: this.openCount,
    };
  }

  /** 強制切換 state（測試 / caller 手動干預用）。 */
  forceState(state: BreakerState): void {
    if (state === 'open' && this.state !== 'open') {
      this.openCount++;
      this.openedAt = this.now();
    }
    this.state = state;
    if (state !== 'half-open') this.halfOpenProbeId = undefined;
  }

  private pickRoute(_req: ParseWorkerRequest): 'primary' | 'fallback' {
    if (this.state === 'closed') return 'primary';
    if (this.state === 'open') return 'fallback';
    // half-open：第一筆送 primary 當 probe、之後續送 fallback 直到 probe 結果回來
    if (this.halfOpenProbeId === undefined) return 'primary';
    return 'fallback';
  }

  private onResponse(resp: ParseWorkerResponse, source: 'primary' | 'fallback'): void {
    if (this.disposed) return;
    const isError = resp.kind === 'error';

    if (source === 'primary') {
      if (isError) this.primaryError++;
      else if (resp.kind === 'success') this.primarySuccess++;
      // sliding window 只記 primary（fallback 健康度不影響 breaker state）
      this.window.push({ isError });
      if (this.window.length > this.windowSize) this.window.shift();
    } else {
      if (isError) this.fallbackError++;
      else if (resp.kind === 'success') this.fallbackSuccess++;
    }

    // half-open probe 結果：成功 → closed、失敗 → 回 open
    if (this.state === 'half-open' && 'requestId' in resp && typeof resp.requestId === 'string'
        && resp.requestId === this.halfOpenProbeId) {
      this.halfOpenProbeId = undefined;
      if (isError) {
        this.transitionToOpen();
      } else {
        this.state = 'closed';
        this.window = []; // reset window 給乾淨起點
      }
    }

    // closed → open 判斷
    if (this.state === 'closed' && this.window.length >= this.minSamples) {
      const errs = this.window.filter((e) => e.isError).length;
      const rate = errs / this.window.length;
      if (rate >= this.errorRateThreshold) {
        this.transitionToOpen();
      }
    }

    // 清 routing 記錄
    if ('requestId' in resp && typeof resp.requestId === 'string') {
      this.routing.delete(resp.requestId);
    }

    // 轉發給 breaker 的 listeners
    for (const l of this.listeners) {
      try { l(resp); } catch { /* listener crash 不影響 */ }
    }
  }

  private transitionToOpen(): void {
    if (this.state !== 'open') {
      this.openCount++;
    }
    this.state = 'open';
    this.openedAt = this.now();
    this.halfOpenProbeId = undefined;
  }
}
