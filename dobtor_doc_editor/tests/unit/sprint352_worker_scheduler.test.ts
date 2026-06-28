/**
 * Sprint 352 — ⑥ deeper¹²：WorkerScheduler。
 *
 * Sprint 347 priority queue 之後補 scheduler：concurrency 限流 + inflight 追蹤 +
 * 完成後自動 pump。
 *
 * 紀律 #18：純調度 model；caller 提供 dispatch；不接 production worker。
 */
import { describe, expect, it } from 'vitest';

import { WorkerScheduler } from '../../static/src/core/ooxml/worker/WorkerScheduler';

interface Dispatched {
  value: string;
  token: number;
}

function mkScheduler(maxConcurrent: number) {
  const dispatched: Dispatched[] = [];
  const scheduler = new WorkerScheduler<string>({
    maxConcurrent,
    dispatch: (value, token) => dispatched.push({ value, token }),
  });
  return { scheduler, dispatched };
}

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 352 — constructor', () => {
  it('maxConcurrent <= 0 throw', () => {
    expect(() => new WorkerScheduler<string>({ maxConcurrent: 0, dispatch: () => {} })).toThrow();
  });
});

// ── concurrency 限流 ───────────────────────────────────────────────

describe('Sprint 352 — concurrency 限流', () => {
  it('maxConcurrent=1 → 一次只 dispatch 一個', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a', 1);
    scheduler.submit('b', 1);
    scheduler.submit('c', 1);
    expect(dispatched).toHaveLength(1);
    expect(scheduler.inflightCount()).toBe(1);
    expect(scheduler.pendingCount()).toBe(2);
  });

  it('maxConcurrent=2 → 同時 dispatch 兩個', () => {
    const { scheduler, dispatched } = mkScheduler(2);
    scheduler.submit('a');
    scheduler.submit('b');
    scheduler.submit('c');
    expect(dispatched).toHaveLength(2);
    expect(scheduler.pendingCount()).toBe(1);
  });

  it('onComplete 釋放 slot → pump 下一個', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a');
    scheduler.submit('b');
    expect(dispatched).toHaveLength(1);
    scheduler.onComplete(dispatched[0].token);
    expect(dispatched).toHaveLength(2);
    expect(dispatched[1].value).toBe('b');
  });
});

// ── priority 順序 ──────────────────────────────────────────────────

describe('Sprint 352 — priority 影響 dispatch 順序', () => {
  it('高 priority 先 dispatch', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('low', 1);
    scheduler.submit('high', 10);
    // 第一個 submit 立即 dispatch 'low'（queue 當時只有它）
    expect(dispatched[0].value).toBe('low');
    // 完成後 pump → 'high'
    scheduler.onComplete(dispatched[0].token);
    expect(dispatched[1].value).toBe('high');
  });

  it('一次提交多個再 pump → 依 priority', () => {
    // maxConcurrent=0 不可，用 1 但先塞 queue：submit 會即時 pump
    // 改用 maxConcurrent=1、第一個佔住、後續排隊依 priority
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('first', 0); // 立即 dispatch
    scheduler.submit('mid', 5);
    scheduler.submit('high', 10);
    scheduler.submit('low', 1);
    // 完成 first → 應 pump 'high'（queue 內最高）
    scheduler.onComplete(dispatched[0].token);
    expect(dispatched[1].value).toBe('high');
    scheduler.onComplete(dispatched[1].token);
    expect(dispatched[2].value).toBe('mid');
    scheduler.onComplete(dispatched[2].token);
    expect(dispatched[3].value).toBe('low');
  });
});

// ── onComplete unknown token ──────────────────────────────────────

describe('Sprint 352 — onComplete unknown token', () => {
  it('unknown token → false、不 pump', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a');
    scheduler.submit('b');
    expect(scheduler.onComplete(999)).toBe(false);
    expect(dispatched).toHaveLength(1); // 'b' 還沒被 pump
  });

  it('known token → true', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a');
    expect(scheduler.onComplete(dispatched[0].token)).toBe(true);
  });
});

// ── isIdle ─────────────────────────────────────────────────────────

describe('Sprint 352 — isIdle', () => {
  it('初始 idle', () => {
    const { scheduler } = mkScheduler(1);
    expect(scheduler.isIdle()).toBe(true);
  });

  it('有 inflight → 非 idle', () => {
    const { scheduler } = mkScheduler(1);
    scheduler.submit('a');
    expect(scheduler.isIdle()).toBe(false);
  });

  it('全部完成 → 回 idle', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a');
    scheduler.onComplete(dispatched[0].token);
    expect(scheduler.isIdle()).toBe(true);
  });
});

// ── stats ──────────────────────────────────────────────────────────

describe('Sprint 352 — getStats', () => {
  it('累計 dispatched / completed + 當前 inflight/pending', () => {
    const { scheduler, dispatched } = mkScheduler(2);
    scheduler.submit('a');
    scheduler.submit('b');
    scheduler.submit('c');
    scheduler.onComplete(dispatched[0].token);
    const s = scheduler.getStats();
    expect(s.maxConcurrent).toBe(2);
    expect(s.dispatchedTotal).toBe(3); // a,b dispatched + c pumped after complete
    expect(s.completedTotal).toBe(1);
    expect(s.inflight).toBe(2);
    expect(s.pending).toBe(0);
  });
});

// ── 全程序列 drain ─────────────────────────────────────────────────

describe('Sprint 352 — 序列 drain 全部', () => {
  it('逐一完成直到 idle', () => {
    const { scheduler, dispatched } = mkScheduler(1);
    scheduler.submit('a');
    scheduler.submit('b');
    scheduler.submit('c');
    let i = 0;
    while (!scheduler.isIdle() && i < 10) {
      scheduler.onComplete(dispatched[dispatched.length - 1].token);
      i++;
    }
    expect(scheduler.isIdle()).toBe(true);
    expect(dispatched.map((d) => d.value)).toEqual(['a', 'b', 'c']);
  });
});
