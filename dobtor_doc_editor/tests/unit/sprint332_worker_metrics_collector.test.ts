/**
 * Sprint 332 — ⑥ deeper⁸：WorkerMetricsCollector。
 *
 * Sprint 292/294/299/307/312/317/322/327 worker 系列第八輪深推。Time-series
 * bucket stats given lifetime cumulative stats（Sprint 312）的補充。
 *
 * 紀律 #18：純記憶體 ring buffer；caller 自負持久化、不接 production worker。
 */
import { describe, expect, it } from 'vitest';

import {
  WorkerMetricsCollector,
  recordSuccess,
  recordError,
  recordTimeout,
} from '../../static/src/core/ooxml/worker/WorkerMetricsCollector';

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 332 — constructor', () => {
  it('maxEvents <= 0 → throw', () => {
    expect(() => new WorkerMetricsCollector({ maxEvents: 0 })).toThrow();
    expect(() => new WorkerMetricsCollector({ maxEvents: -1 })).toThrow();
  });

  it('default maxEvents = 1000', () => {
    const c = new WorkerMetricsCollector();
    expect(c.size()).toBe(0);
  });
});

// ── record + FIFO ──────────────────────────────────────────────────

describe('Sprint 332 — record FIFO eviction', () => {
  it('超過 maxEvents → 丟最舊', () => {
    const c = new WorkerMetricsCollector({ maxEvents: 3 });
    c.record({ kind: 'success', atMs: 1, latencyMs: 10 });
    c.record({ kind: 'success', atMs: 2, latencyMs: 20 });
    c.record({ kind: 'success', atMs: 3, latencyMs: 30 });
    c.record({ kind: 'success', atMs: 4, latencyMs: 40 });
    const events = c.exportSnapshot();
    expect(events).toHaveLength(3);
    expect(events[0].atMs).toBe(2); // 1 被丟
    expect(events[2].atMs).toBe(4);
  });
});

// ── getBuckets ─────────────────────────────────────────────────────

describe('Sprint 332 — getBuckets', () => {
  it('bucketSizeMs <= 0 → throw', () => {
    const c = new WorkerMetricsCollector();
    expect(() => c.getBuckets(0, 100, 0)).toThrow();
    expect(() => c.getBuckets(0, 100, -1)).toThrow();
  });

  it('toMs <= fromMs → 空 array', () => {
    const c = new WorkerMetricsCollector();
    expect(c.getBuckets(100, 100, 10)).toEqual([]);
    expect(c.getBuckets(100, 50, 10)).toEqual([]);
  });

  it('連續 bucket（含 0-count 中間 bucket）', () => {
    const c = new WorkerMetricsCollector();
    c.record({ kind: 'success', atMs: 5, latencyMs: 10 });
    c.record({ kind: 'success', atMs: 35, latencyMs: 20 });
    const buckets = c.getBuckets(0, 40, 10);
    expect(buckets).toHaveLength(4);
    expect(buckets[0].successCount).toBe(1);
    expect(buckets[1].successCount).toBe(0);
    expect(buckets[2].successCount).toBe(0);
    expect(buckets[3].successCount).toBe(1);
  });

  it('mean latency 正確', () => {
    const c = new WorkerMetricsCollector();
    c.record({ kind: 'success', atMs: 1, latencyMs: 10 });
    c.record({ kind: 'success', atMs: 2, latencyMs: 30 });
    c.record({ kind: 'error', atMs: 3, latencyMs: 50 });
    const buckets = c.getBuckets(0, 10, 10);
    expect(buckets[0].meanLatencyMs).toBe(30);
    expect(buckets[0].maxLatencyMs).toBe(50);
    expect(buckets[0].successCount).toBe(2);
    expect(buckets[0].errorCount).toBe(1);
  });

  it('event 落在 bucket 外 → ignored', () => {
    const c = new WorkerMetricsCollector();
    c.record({ kind: 'success', atMs: 999, latencyMs: 10 });
    const buckets = c.getBuckets(0, 10, 10);
    expect(buckets[0].successCount).toBe(0);
  });

  it('endMs 對齊不完整 bucket size 時 clamp', () => {
    const c = new WorkerMetricsCollector();
    // 7ms 寬、bucketSize=3、預期 3 個 bucket（0-3、3-6、6-7）
    const buckets = c.getBuckets(0, 7, 3);
    expect(buckets).toHaveLength(3);
    expect(buckets[2].startMs).toBe(6);
    expect(buckets[2].endMs).toBe(7);
  });
});

// ── timeout count ──────────────────────────────────────────────────

describe('Sprint 332 — timeout 計數', () => {
  it('record timeout → bucket.timeoutCount++', () => {
    const c = new WorkerMetricsCollector();
    recordTimeout(c, 1, 5000);
    const buckets = c.getBuckets(0, 10, 10);
    expect(buckets[0].timeoutCount).toBe(1);
    expect(buckets[0].maxLatencyMs).toBe(5000);
  });
});

// ── clear ───────────────────────────────────────────────────────────

describe('Sprint 332 — clear', () => {
  it('清空 events', () => {
    const c = new WorkerMetricsCollector();
    recordSuccess(c, 1, 10);
    recordError(c, 2, 20);
    expect(c.size()).toBe(2);
    c.clear();
    expect(c.size()).toBe(0);
  });
});

// ── helpers ────────────────────────────────────────────────────────

describe('Sprint 332 — helpers', () => {
  it('recordSuccess / recordError / recordTimeout 對應 kind', () => {
    const c = new WorkerMetricsCollector();
    recordSuccess(c, 1, 10);
    recordError(c, 2, 20);
    recordTimeout(c, 3, 30);
    const events = c.exportSnapshot();
    expect(events[0].kind).toBe('success');
    expect(events[1].kind).toBe('error');
    expect(events[2].kind).toBe('timeout');
  });
});
