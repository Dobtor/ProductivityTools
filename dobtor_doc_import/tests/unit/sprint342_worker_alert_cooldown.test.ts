/**
 * Sprint 342 — ⑥ deeper¹⁰：WorkerAlertCooldown。
 *
 * Sprint 337 evaluator 之後深推。同 key cooldown N ms 抑制重複 alert。
 *
 * 紀律 #18：純記憶體 cooldown state；caller 自負持久化 + notification 接線。
 */
import { describe, expect, it } from 'vitest';

import { WorkerAlertCooldown } from '../../static/src/core/ooxml/worker/WorkerAlertCooldown';
import type { AlertEvent } from '../../static/src/core/ooxml/worker/WorkerAlertEvaluator';

const e = (
  ruleName: string,
  severity: AlertEvent['severity'],
  fromBucket = 0,
): AlertEvent => ({
  ruleName,
  severity,
  fromBucket,
  toBucket: fromBucket,
  value: 1,
  message: 'msg',
});

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 342 — constructor', () => {
  it('cooldownMs <= 0 throw', () => {
    expect(() => new WorkerAlertCooldown({ cooldownMs: 0 })).toThrow();
    expect(() => new WorkerAlertCooldown({ cooldownMs: -1 })).toThrow();
  });
  it('default cooldownMs = 60000', () => {
    const c = new WorkerAlertCooldown();
    expect(c.getStats().passed).toBe(0);
  });
});

// ── filter ─────────────────────────────────────────────────────────

describe('Sprint 342 — filter', () => {
  it('第一次通過 → 計 passed', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    const out = c.filter([e('latency', 'warning')]);
    expect(out).toHaveLength(1);
    expect(c.getStats().passed).toBe(1);
    expect(c.getStats().suppressed).toBe(0);
  });

  it('cooldown 內同 key → suppressed', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('latency', 'warning')]);
    t += 500; // 還沒到 cooldown
    const out = c.filter([e('latency', 'warning')]);
    expect(out).toHaveLength(0);
    expect(c.getStats().suppressed).toBe(1);
  });

  it('cooldown 過 → 重新通過', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('latency', 'warning')]);
    t += 2000;
    const out = c.filter([e('latency', 'warning')]);
    expect(out).toHaveLength(1);
    expect(c.getStats().passed).toBe(2);
  });

  it('不同 severity 視為不同 key', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    const out = c.filter([
      e('latency', 'warning'),
      e('latency', 'critical'),
    ]);
    expect(out).toHaveLength(2);
  });

  it('不同 ruleName 視為不同 key', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    const out = c.filter([e('latency', 'warning'), e('errorRate', 'warning')]);
    expect(out).toHaveLength(2);
  });

  it('空 input → 空 output', () => {
    const c = new WorkerAlertCooldown();
    expect(c.filter([])).toEqual([]);
  });
});

// ── isInCooldown ───────────────────────────────────────────────────

describe('Sprint 342 — isInCooldown', () => {
  it('未通過過 → false', () => {
    const c = new WorkerAlertCooldown({ cooldownMs: 1000 });
    expect(c.isInCooldown('a', 'warning')).toBe(false);
  });

  it('已通過 + 在 cooldown 內 → true', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('a', 'warning')]);
    expect(c.isInCooldown('a', 'warning')).toBe(true);
  });

  it('cooldown 過 → false', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('a', 'warning')]);
    t += 2000;
    expect(c.isInCooldown('a', 'warning')).toBe(false);
  });

  it('isInCooldown 不更新 state（純 query）', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('a', 'warning')]);
    c.isInCooldown('a', 'warning');
    c.isInCooldown('a', 'warning');
    expect(c.getStats().passed).toBe(1); // 沒因 query 變多
  });
});

// ── purgeExpired ──────────────────────────────────────────────────

describe('Sprint 342 — purgeExpired', () => {
  it('清掉過期 cooldown key', () => {
    let t = 1000;
    const c = new WorkerAlertCooldown({ cooldownMs: 1000, now: () => t });
    c.filter([e('a', 'warning'), e('b', 'warning')]);
    t += 2000;
    c.filter([e('c', 'warning')]); // 'c' 新進
    expect(c.purgeExpired()).toBe(2); // 'a' 'b' 過期
    expect(c.getStats().activeKeys).toBe(1);
  });
});

// ── reset ──────────────────────────────────────────────────────────

describe('Sprint 342 — reset', () => {
  it('清掉所有 state', () => {
    const c = new WorkerAlertCooldown({ cooldownMs: 1000 });
    c.filter([e('a', 'warning')]);
    c.reset();
    expect(c.getStats().passed).toBe(0);
    expect(c.getStats().activeKeys).toBe(0);
  });
});
