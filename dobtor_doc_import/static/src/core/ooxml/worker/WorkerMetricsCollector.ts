/**
 * WorkerMetricsCollector — Sprint 332。
 *
 * Sprint 292/294/299/307/312/317/322/327 worker 系列第八輪深推。Sprint 312
 * WorkerHealthMonitor 提供 lifetime cumulative stats（mean / p50 / p95、不分時
 * 段）；本 sprint 補 **time-series**：caller 想看「最近 10 分鐘 latency 趨勢」、
 * 「過去 1 小時 error rate」等視覺化資料。
 *
 * 架構：caller 手動 `record(event, atMs)`、本 module 純記憶體 ring buffer + 即時
 * bucket 分組。
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體；caller 自負持久化
 *   - 不接 production worker dispatcher（caller 從 312 stats 自行轉換或自己 record）
 *   - 不做 sliding window aggregation（getBuckets 即時算）
 *   - maxEvents FIFO 自然淘汰、避免無限成長
 *
 * 紀律 #21：純資料 transform、不污染 production worker pipeline。
 */

export interface WorkerMetricEvent {
  /** 事件種類 */
  kind: 'success' | 'error' | 'timeout';
  /** 事件時間（ms epoch / performance.now、caller 自選單位） */
  atMs: number;
  /** 事件 latency（ms）；timeout 通常為 caller 設定的 timeout 上限 */
  latencyMs: number;
}

export interface WorkerMetricsCollectorOptions {
  /** 最多保留 N 筆 event；達上限後 FIFO 丟棄最舊；預設 1000 */
  maxEvents?: number;
}

export interface BucketStats {
  /** Bucket 起點 ms（inclusive） */
  startMs: number;
  /** Bucket 結束 ms（exclusive） */
  endMs: number;
  successCount: number;
  errorCount: number;
  timeoutCount: number;
  /** Bucket 內所有 event 的平均 latency；空 bucket = 0 */
  meanLatencyMs: number;
  /** Bucket 內 max latency；空 bucket = 0 */
  maxLatencyMs: number;
}

export class WorkerMetricsCollector {
  private readonly maxEvents: number;
  private events: WorkerMetricEvent[] = [];

  constructor(opts: WorkerMetricsCollectorOptions = {}) {
    this.maxEvents = opts.maxEvents ?? 1000;
    if (this.maxEvents <= 0) {
      throw new Error('[WorkerMetricsCollector] maxEvents must be > 0');
    }
  }

  /** 紀錄一筆事件；超過 maxEvents 時 FIFO 丟棄最舊。 */
  record(event: WorkerMetricEvent): void {
    this.events.push(event);
    if (this.events.length > this.maxEvents) {
      this.events.shift();
    }
  }

  /**
   * 取 time-series buckets。
   *
   * @param fromMs - bucket 開始時間（inclusive）
   * @param toMs - bucket 結束時間（exclusive）
   * @param bucketSizeMs - 單一 bucket 寬度
   * @returns Bucket array（含 0-count bucket、確保 caller 連續視覺化）
   */
  getBuckets(fromMs: number, toMs: number, bucketSizeMs: number): BucketStats[] {
    if (bucketSizeMs <= 0) {
      throw new Error('[WorkerMetricsCollector] bucketSizeMs must be > 0');
    }
    if (toMs <= fromMs) return [];

    const numBuckets = Math.ceil((toMs - fromMs) / bucketSizeMs);
    const buckets: BucketStats[] = [];
    for (let i = 0; i < numBuckets; i++) {
      const startMs = fromMs + i * bucketSizeMs;
      const endMs = Math.min(startMs + bucketSizeMs, toMs);
      buckets.push({
        startMs,
        endMs,
        successCount: 0,
        errorCount: 0,
        timeoutCount: 0,
        meanLatencyMs: 0,
        maxLatencyMs: 0,
      });
    }

    const sums: number[] = new Array(numBuckets).fill(0);
    const counts: number[] = new Array(numBuckets).fill(0);

    for (const e of this.events) {
      if (e.atMs < fromMs || e.atMs >= toMs) continue;
      const idx = Math.floor((e.atMs - fromMs) / bucketSizeMs);
      if (idx < 0 || idx >= numBuckets) continue;
      const b = buckets[idx];
      if (e.kind === 'success') b.successCount += 1;
      else if (e.kind === 'error') b.errorCount += 1;
      else if (e.kind === 'timeout') b.timeoutCount += 1;
      sums[idx] += e.latencyMs;
      counts[idx] += 1;
      if (e.latencyMs > b.maxLatencyMs) b.maxLatencyMs = e.latencyMs;
    }

    for (let i = 0; i < numBuckets; i++) {
      if (counts[i] > 0) {
        buckets[i].meanLatencyMs = sums[i] / counts[i];
      }
    }
    return buckets;
  }

  /** 目前儲存的 event 數 */
  size(): number {
    return this.events.length;
  }

  /** 清空所有 event（不釋放 maxEvents 上限） */
  clear(): void {
    this.events = [];
  }

  /** Snapshot 給 caller logging / debug（淺 copy、不深拷貝） */
  exportSnapshot(): ReadonlyArray<WorkerMetricEvent> {
    return [...this.events];
  }
}

/**
 * Helper：把 Sprint 312 WorkerHealthMonitor recordTimeout / observed errors
 * 等 lifetime stats 簡單擴成單一事件，餵給 collector。Caller 自行決定 latency。
 */
export function recordSuccess(c: WorkerMetricsCollector, atMs: number, latencyMs: number): void {
  c.record({ kind: 'success', atMs, latencyMs });
}

export function recordError(c: WorkerMetricsCollector, atMs: number, latencyMs: number): void {
  c.record({ kind: 'error', atMs, latencyMs });
}

export function recordTimeout(c: WorkerMetricsCollector, atMs: number, latencyMs: number): void {
  c.record({ kind: 'timeout', atMs, latencyMs });
}
