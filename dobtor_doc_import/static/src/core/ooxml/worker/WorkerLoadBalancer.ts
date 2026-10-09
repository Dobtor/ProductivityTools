/**
 * WorkerLoadBalancer — Sprint 322。
 *
 * Sprint 292/294/299/307/312/317 worker cluster 第五輪深推。Round-robin pool
 * （Sprint 307）的智慧版：根據 WorkerHealthMonitor stats 選最閒 / 最快的 worker
 * 派發 request。
 *
 * 三種選擇策略：
 *
 *   1. `least-inflight`：選 inflight count 最少的（適合短 request、想避免 head-of-line blocking）
 *   2. `lowest-p95`：選 p95 latency 最低的（適合 long-tail 對 latency 敏感場景）
 *   3. `lowest-error-rate`：選 errorRate 最低的（適合多 worker 健康度不一致）
 *
 * 紀律 #18 scope-down：
 *   - 純基於 WorkerHealthMonitor 的 stats（caller 必須先 wrap dispatcher）
 *   - 不做加權組合（單一 criterion 排序）；caller 想要 hybrid 自行 wrap
 *   - 不做 dynamic worker 增刪（pool size 固定、caller 自管）
 *
 * 紀律 #21：composes monitors、不改 monitor 或 dispatcher 內部行為；
 *   terminate fan-out。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';
import { WorkerHealthMonitor } from './WorkerHealthMonitor';

export type LoadBalanceStrategy = 'least-inflight' | 'lowest-p95' | 'lowest-error-rate';

export interface WorkerLoadBalancerOptions {
  /** 已 wrap 過 HealthMonitor 的 dispatcher 列表；至少 1 個。 */
  monitors: WorkerHealthMonitor[];
  /** 派發策略；預設 'least-inflight' */
  strategy?: LoadBalanceStrategy;
  /** Tie-break：當多 monitor 同分時用 round-robin 切換；預設 true */
  roundRobinTieBreak?: boolean;
}

/**
 * Load-balancing dispatcher（implements ParseWorkerDispatcher）。
 *
 * 每個 post：
 *   1. 依 strategy 排序 monitors
 *   2. 取「首位」（最佳）；多個並列時用 round-robin 切換
 *   3. post 給該 monitor
 *
 * Subscribe fan-out：任一 monitor emit → balancer listeners 全收。
 * Terminate fan-out 給所有 monitor。
 */
export class WorkerLoadBalancer implements ParseWorkerDispatcher {
  private readonly monitors: WorkerHealthMonitor[];
  private readonly strategy: LoadBalanceStrategy;
  private readonly roundRobinTieBreak: boolean;
  private readonly listeners = new Set<(r: ParseWorkerResponse) => void>();
  private readonly unsubs: Array<() => void> = [];
  private nextTieBreakIndex = 0;
  private disposed = false;

  constructor(opts: WorkerLoadBalancerOptions) {
    if (!opts.monitors || opts.monitors.length === 0) {
      throw new Error('[WorkerLoadBalancer] monitors must have at least 1 entry');
    }
    this.monitors = [...opts.monitors];
    this.strategy = opts.strategy ?? 'least-inflight';
    this.roundRobinTieBreak = opts.roundRobinTieBreak ?? true;
    // fan-out subscribe
    for (const m of this.monitors) {
      const unsub = m.subscribe((r) => this.dispatchToListeners(r));
      this.unsubs.push(unsub);
    }
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    const idx = this.pickIndex();
    this.monitors[idx].post(request);
  }

  subscribe(listener: (r: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const unsub of this.unsubs) {
      try { unsub(); } catch { /* ignore */ }
    }
    this.unsubs.length = 0;
    this.listeners.clear();
    for (const m of this.monitors) {
      try { m.terminate(); } catch { /* ignore */ }
    }
  }

  /** 當前 strategy 觀察的 metric 對每個 monitor 的值（debug / monitoring 用）。 */
  getMetrics(): Array<{ index: number; metric: number }> {
    return this.monitors.map((m, i) => ({ index: i, metric: this.metricOf(m) }));
  }

  /** 當前最被選中的 monitor index（不變動 round-robin tie-break 狀態）。 */
  peekNextIndex(): number {
    return this.pickIndexInternal(false);
  }

  size(): number {
    return this.monitors.length;
  }

  private pickIndex(): number {
    return this.pickIndexInternal(true);
  }

  private pickIndexInternal(advance: boolean): number {
    const metrics = this.monitors.map((m) => this.metricOf(m));
    const minMetric = Math.min(...metrics);
    // 找所有 metric === minMetric 的 indices
    const ties: number[] = [];
    for (let i = 0; i < metrics.length; i++) {
      if (metrics[i] === minMetric) ties.push(i);
    }
    if (ties.length === 1) return ties[0];
    if (!this.roundRobinTieBreak) return ties[0];
    // round-robin 在 ties 內輪替
    const choice = ties[this.nextTieBreakIndex % ties.length];
    if (advance) this.nextTieBreakIndex++;
    return choice;
  }

  private metricOf(m: WorkerHealthMonitor): number {
    const s = m.getStats();
    switch (this.strategy) {
      case 'least-inflight': return s.inflightCount;
      case 'lowest-p95': return s.p95LatencyMs;
      case 'lowest-error-rate': return s.errorRate;
    }
  }

  private dispatchToListeners(r: ParseWorkerResponse): void {
    if (this.disposed) return;
    for (const l of this.listeners) {
      try { l(r); } catch { /* ignore */ }
    }
  }
}
