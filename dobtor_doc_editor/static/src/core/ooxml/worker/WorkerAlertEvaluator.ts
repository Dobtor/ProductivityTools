/**
 * WorkerAlertEvaluator — Sprint 337。
 *
 * Sprint 292/294/299/307/312/317/322/327/332 worker 系列第九輪深推。Sprint 332
 * WorkerMetricsCollector 提供 time-series buckets；本 sprint 補：
 * 對 buckets 套 caller-defined alert rules → 觸發 alert events。
 *
 * 場景：
 *   - error rate > 0.5 持續 3 個 bucket → 觸 critical alert
 *   - mean latency > 1000ms 任一 bucket → 觸 warning alert
 *   - timeout count > 5 任一 bucket → 觸 critical alert
 *
 * API：
 *   - evaluateAlertRules(buckets, rules) → AlertEvent[]
 *   - 提供常見 rule builder（thresholdMeanLatency / thresholdErrorRate /
 *     thresholdTimeoutCount / consecutiveErrorRate）
 *
 * 紀律 #18 scope-down：
 *   - 純評估、不接 notification（caller 自行 wire 進 Slack/email/log）
 *   - 不做 rate-limit / dedup（同一 rule 多次觸發 → 多筆 event；caller 自管）
 *   - 不接 production worker dispatcher
 *
 * 紀律 #21：純函式、不污染既有 worker pipeline。
 */

import type { BucketStats } from './WorkerMetricsCollector';

export type AlertSeverity = 'info' | 'warning' | 'critical';

export interface AlertEvent {
  ruleName: string;
  severity: AlertSeverity;
  /** Bucket index 開始 / 結束（inclusive）；單 bucket alert 兩者相同 */
  fromBucket: number;
  toBucket: number;
  /** 對應的 metric value（rule 自定義意義） */
  value: number;
  /** Caller-friendly 訊息 */
  message: string;
}

/**
 * Rule 介面：給 buckets array、回 0~N 筆 alert events。
 */
export interface AlertRule {
  name: string;
  evaluate(buckets: ReadonlyArray<BucketStats>): AlertEvent[];
}

/**
 * 串多條 rules 評估。
 */
export function evaluateAlertRules(
  buckets: ReadonlyArray<BucketStats>,
  rules: ReadonlyArray<AlertRule>,
): AlertEvent[] {
  const events: AlertEvent[] = [];
  for (const r of rules) {
    events.push(...r.evaluate(buckets));
  }
  return events;
}

/**
 * 任一 bucket meanLatencyMs > threshold → 觸 alert。
 */
export function thresholdMeanLatency(opts: {
  thresholdMs: number;
  severity?: AlertSeverity;
  name?: string;
}): AlertRule {
  return {
    name: opts.name ?? 'meanLatency',
    evaluate(buckets) {
      const events: AlertEvent[] = [];
      for (let i = 0; i < buckets.length; i++) {
        const b = buckets[i];
        if (b.meanLatencyMs > opts.thresholdMs) {
          events.push({
            ruleName: opts.name ?? 'meanLatency',
            severity: opts.severity ?? 'warning',
            fromBucket: i,
            toBucket: i,
            value: b.meanLatencyMs,
            message: `mean latency ${b.meanLatencyMs.toFixed(0)}ms > ${opts.thresholdMs}ms`,
          });
        }
      }
      return events;
    },
  };
}

/**
 * 任一 bucket errorCount / (successCount + errorCount) > threshold → 觸 alert。
 * 分母 0 時 rate = 0、不觸發。
 */
export function thresholdErrorRate(opts: {
  thresholdRate: number;
  severity?: AlertSeverity;
  name?: string;
}): AlertRule {
  return {
    name: opts.name ?? 'errorRate',
    evaluate(buckets) {
      const events: AlertEvent[] = [];
      for (let i = 0; i < buckets.length; i++) {
        const b = buckets[i];
        const total = b.successCount + b.errorCount;
        if (total === 0) continue;
        const rate = b.errorCount / total;
        if (rate > opts.thresholdRate) {
          events.push({
            ruleName: opts.name ?? 'errorRate',
            severity: opts.severity ?? 'critical',
            fromBucket: i,
            toBucket: i,
            value: rate,
            message: `error rate ${(rate * 100).toFixed(1)}% > ${(opts.thresholdRate * 100).toFixed(1)}%`,
          });
        }
      }
      return events;
    },
  };
}

/**
 * 任一 bucket timeoutCount > threshold → 觸 alert。
 */
export function thresholdTimeoutCount(opts: {
  thresholdCount: number;
  severity?: AlertSeverity;
  name?: string;
}): AlertRule {
  return {
    name: opts.name ?? 'timeoutCount',
    evaluate(buckets) {
      const events: AlertEvent[] = [];
      for (let i = 0; i < buckets.length; i++) {
        const b = buckets[i];
        if (b.timeoutCount > opts.thresholdCount) {
          events.push({
            ruleName: opts.name ?? 'timeoutCount',
            severity: opts.severity ?? 'critical',
            fromBucket: i,
            toBucket: i,
            value: b.timeoutCount,
            message: `timeout count ${b.timeoutCount} > ${opts.thresholdCount}`,
          });
        }
      }
      return events;
    },
  };
}

/**
 * 連續 N 個 bucket error rate 都 > threshold → 觸 alert（避免單個 spike 誤報）。
 */
export function consecutiveErrorRate(opts: {
  thresholdRate: number;
  consecutiveBuckets: number;
  severity?: AlertSeverity;
  name?: string;
}): AlertRule {
  if (opts.consecutiveBuckets <= 0) {
    throw new Error('[WorkerAlertEvaluator] consecutiveBuckets must be > 0');
  }
  return {
    name: opts.name ?? 'consecutiveErrorRate',
    evaluate(buckets) {
      const events: AlertEvent[] = [];
      let streakStart = -1;
      for (let i = 0; i < buckets.length; i++) {
        const b = buckets[i];
        const total = b.successCount + b.errorCount;
        const rate = total === 0 ? 0 : b.errorCount / total;
        if (total > 0 && rate > opts.thresholdRate) {
          if (streakStart === -1) streakStart = i;
          if (i - streakStart + 1 >= opts.consecutiveBuckets) {
            events.push({
              ruleName: opts.name ?? 'consecutiveErrorRate',
              severity: opts.severity ?? 'critical',
              fromBucket: streakStart,
              toBucket: i,
              value: rate,
              message: `error rate > ${(opts.thresholdRate * 100).toFixed(1)}% for ${i - streakStart + 1} consecutive buckets`,
            });
            // continue tracking but reset to avoid duplicate at every subsequent bucket
            streakStart = -1;
          }
        } else {
          streakStart = -1;
        }
      }
      return events;
    },
  };
}

/**
 * 給 caller logging：依 severity 分組事件數。
 */
export interface AlertSummary {
  totalEvents: number;
  bySeverity: { info: number; warning: number; critical: number };
}

export function summarizeAlerts(events: ReadonlyArray<AlertEvent>): AlertSummary {
  const summary: AlertSummary = {
    totalEvents: events.length,
    bySeverity: { info: 0, warning: 0, critical: 0 },
  };
  for (const e of events) summary.bySeverity[e.severity] += 1;
  return summary;
}
