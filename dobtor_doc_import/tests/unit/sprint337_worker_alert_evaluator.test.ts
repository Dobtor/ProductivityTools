/**
 * Sprint 337 — ⑥ deeper⁹：WorkerAlertEvaluator。
 *
 * Sprint 332 metrics collector 之後深推。Threshold rules → AlertEvent[]。
 *
 * 紀律 #18：純評估、不接 notification；caller 自接 Slack/email/log。
 */
import { describe, expect, it } from 'vitest';

import {
  evaluateAlertRules,
  thresholdMeanLatency,
  thresholdErrorRate,
  thresholdTimeoutCount,
  consecutiveErrorRate,
  summarizeAlerts,
} from '../../static/src/core/ooxml/worker/WorkerAlertEvaluator';
import type { BucketStats } from '../../static/src/core/ooxml/worker/WorkerMetricsCollector';

const mkBucket = (
  startMs: number,
  successCount = 0,
  errorCount = 0,
  timeoutCount = 0,
  meanLatencyMs = 0,
  maxLatencyMs = 0,
): BucketStats => ({
  startMs,
  endMs: startMs + 10,
  successCount,
  errorCount,
  timeoutCount,
  meanLatencyMs,
  maxLatencyMs,
});

// ── thresholdMeanLatency ───────────────────────────────────────────

describe('Sprint 337 — thresholdMeanLatency', () => {
  it('任一 bucket mean > threshold → alert', () => {
    const buckets = [mkBucket(0, 1, 0, 0, 50), mkBucket(10, 1, 0, 0, 150)];
    const events = thresholdMeanLatency({ thresholdMs: 100 }).evaluate(buckets);
    expect(events).toHaveLength(1);
    expect(events[0].fromBucket).toBe(1);
    expect(events[0].value).toBe(150);
    expect(events[0].severity).toBe('warning');
  });

  it('全在 threshold 內 → 無 event', () => {
    const buckets = [mkBucket(0, 1, 0, 0, 50)];
    expect(thresholdMeanLatency({ thresholdMs: 100 }).evaluate(buckets)).toEqual([]);
  });

  it('custom name + severity', () => {
    const buckets = [mkBucket(0, 1, 0, 0, 200)];
    const events = thresholdMeanLatency({
      thresholdMs: 100,
      name: 'high-latency',
      severity: 'critical',
    }).evaluate(buckets);
    expect(events[0].ruleName).toBe('high-latency');
    expect(events[0].severity).toBe('critical');
  });
});

// ── thresholdErrorRate ─────────────────────────────────────────────

describe('Sprint 337 — thresholdErrorRate', () => {
  it('error rate > threshold → alert', () => {
    const buckets = [mkBucket(0, 1, 4)]; // rate = 0.8
    const events = thresholdErrorRate({ thresholdRate: 0.5 }).evaluate(buckets);
    expect(events).toHaveLength(1);
    expect(events[0].value).toBeCloseTo(0.8);
  });

  it('total=0 → 不觸發', () => {
    const buckets = [mkBucket(0, 0, 0)];
    expect(thresholdErrorRate({ thresholdRate: 0.5 }).evaluate(buckets)).toEqual([]);
  });

  it('全在 threshold 內 → 無 event', () => {
    const buckets = [mkBucket(0, 9, 1)]; // rate 0.1
    expect(thresholdErrorRate({ thresholdRate: 0.5 }).evaluate(buckets)).toEqual([]);
  });
});

// ── thresholdTimeoutCount ──────────────────────────────────────────

describe('Sprint 337 — thresholdTimeoutCount', () => {
  it('timeoutCount > threshold → alert', () => {
    const buckets = [mkBucket(0, 0, 0, 10)];
    const events = thresholdTimeoutCount({ thresholdCount: 5 }).evaluate(buckets);
    expect(events).toHaveLength(1);
    expect(events[0].value).toBe(10);
  });

  it('==threshold → 不觸發（> not >=）', () => {
    const buckets = [mkBucket(0, 0, 0, 5)];
    expect(thresholdTimeoutCount({ thresholdCount: 5 }).evaluate(buckets)).toEqual([]);
  });
});

// ── consecutiveErrorRate ──────────────────────────────────────────

describe('Sprint 337 — consecutiveErrorRate', () => {
  it('連續 N bucket 都超過 → 一次 alert', () => {
    const buckets = [
      mkBucket(0, 1, 4), // 0.8 > 0.5
      mkBucket(10, 1, 4), // 0.8
      mkBucket(20, 1, 4), // 0.8
    ];
    const events = consecutiveErrorRate({
      thresholdRate: 0.5,
      consecutiveBuckets: 3,
    }).evaluate(buckets);
    expect(events).toHaveLength(1);
    expect(events[0].fromBucket).toBe(0);
    expect(events[0].toBucket).toBe(2);
  });

  it('中間斷掉 → 不觸發', () => {
    const buckets = [
      mkBucket(0, 1, 4),
      mkBucket(10, 9, 1), // < 0.5 斷
      mkBucket(20, 1, 4),
    ];
    const events = consecutiveErrorRate({
      thresholdRate: 0.5,
      consecutiveBuckets: 3,
    }).evaluate(buckets);
    expect(events).toEqual([]);
  });

  it('total=0 視為非超標、會打斷 streak', () => {
    const buckets = [mkBucket(0, 1, 4), mkBucket(10, 0, 0), mkBucket(20, 1, 4)];
    expect(
      consecutiveErrorRate({ thresholdRate: 0.5, consecutiveBuckets: 3 }).evaluate(buckets),
    ).toEqual([]);
  });

  it('consecutiveBuckets <= 0 throw', () => {
    expect(() =>
      consecutiveErrorRate({ thresholdRate: 0.5, consecutiveBuckets: 0 }),
    ).toThrow();
  });
});

// ── evaluateAlertRules + summarizeAlerts ─────────────────────────

describe('Sprint 337 — evaluateAlertRules 串多 rule', () => {
  it('多 rule 一次評估', () => {
    const buckets = [mkBucket(0, 1, 4, 10, 150)];
    const events = evaluateAlertRules(buckets, [
      thresholdMeanLatency({ thresholdMs: 100, severity: 'warning' }),
      thresholdErrorRate({ thresholdRate: 0.5, severity: 'critical' }),
      thresholdTimeoutCount({ thresholdCount: 5, severity: 'critical' }),
    ]);
    expect(events.length).toBeGreaterThanOrEqual(3);
  });
});

describe('Sprint 337 — summarizeAlerts', () => {
  it('依 severity 分組', () => {
    const events = [
      { ruleName: 'a', severity: 'warning' as const, fromBucket: 0, toBucket: 0, value: 0, message: '' },
      { ruleName: 'b', severity: 'critical' as const, fromBucket: 0, toBucket: 0, value: 0, message: '' },
      { ruleName: 'c', severity: 'critical' as const, fromBucket: 0, toBucket: 0, value: 0, message: '' },
    ];
    const s = summarizeAlerts(events);
    expect(s.totalEvents).toBe(3);
    expect(s.bySeverity.warning).toBe(1);
    expect(s.bySeverity.critical).toBe(2);
  });

  it('空 → 全 0', () => {
    expect(summarizeAlerts([])).toEqual({
      totalEvents: 0,
      bySeverity: { info: 0, warning: 0, critical: 0 },
    });
  });
});
