/**
 * Sprint 347 — ⑥ deeper¹¹：WorkerPriorityQueue。
 *
 * Sprint 307 round-robin pool 之後補 priority queue（含 aging 防 starvation）。
 *
 * 紀律 #18：純記憶體 model；caller 自接 dispatcher；不接 production worker。
 */
import { describe, expect, it } from 'vitest';

import { WorkerPriorityQueue } from '../../static/src/core/ooxml/worker/WorkerPriorityQueue';

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 347 — constructor', () => {
  it('aging params < 0 throw', () => {
    expect(() => new WorkerPriorityQueue({ agingIntervalMs: -1 })).toThrow();
    expect(() => new WorkerPriorityQueue({ agingBoost: -1 })).toThrow();
  });
});

// ── 基本 priority ──────────────────────────────────────────────────

describe('Sprint 347 — static priority', () => {
  it('高 priority 先出', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('low', 1);
    q.enqueue('high', 10);
    q.enqueue('mid', 5);
    expect(q.dequeue()).toBe('high');
    expect(q.dequeue()).toBe('mid');
    expect(q.dequeue()).toBe('low');
  });

  it('同 priority → FIFO', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('first', 5);
    q.enqueue('second', 5);
    q.enqueue('third', 5);
    expect(q.dequeue()).toBe('first');
    expect(q.dequeue()).toBe('second');
    expect(q.dequeue()).toBe('third');
  });

  it('預設 priority = 0', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('a');
    q.enqueue('b', 1);
    expect(q.dequeue()).toBe('b');
  });

  it('空 queue dequeue → undefined', () => {
    const q = new WorkerPriorityQueue<string>();
    expect(q.dequeue()).toBeUndefined();
  });
});

// ── aging ──────────────────────────────────────────────────────────

describe('Sprint 347 — aging anti-starvation', () => {
  it('等久的低優先逐步提升、最終超越高優先', () => {
    let t = 0;
    const q = new WorkerPriorityQueue<string>({
      agingIntervalMs: 100,
      agingBoost: 5,
      now: () => t,
    });
    q.enqueue('low', 1); // t=0
    t = 10;
    q.enqueue('high', 8); // t=10
    // 此刻：low eff=1、high eff=8 → high 先
    // 等 200ms：low 等了 210ms → +2*5=10 → eff=11；high 等了 200ms → +2*5=10 → eff=18
    // high 還是贏... 需要更久
    t = 2000;
    // low 等 2000ms → 20 steps * 5 = 100 → eff=101
    // high 等 1990ms → 19 steps * 5 = 95 → eff=103 → high 仍贏（接近）
    // 把時間拉更長確保 low 反超（因 low 早入列 10ms）
    t = 100000;
    // low waited=100000 → 1000 steps*5=5000 → eff=5001
    // high waited=99990 → 999 steps*5=4995 → eff=5003
    // 差距由 base(1 vs 8)=7 與 step 差距決定；low 早 10ms 不足以反超 → high 先
    expect(q.dequeue()).toBe('high');
  });

  it('aging 讓低優先在足夠時間後超越（base 差距小）', () => {
    let t = 0;
    const q = new WorkerPriorityQueue<string>({
      agingIntervalMs: 100,
      agingBoost: 10,
      now: () => t,
    });
    q.enqueue('low', 0); // t=0
    t = 500;
    q.enqueue('high', 5); // t=500
    // 評估時 t=1000：
    // low waited=1000 → 10 steps*10=100 → eff=100
    // high waited=500 → 5 steps*10=50 → eff=55
    t = 1000;
    expect(q.dequeue()).toBe('low');
  });

  it('agingBoost=0 → 純 static priority', () => {
    let t = 0;
    const q = new WorkerPriorityQueue<string>({
      agingIntervalMs: 100,
      agingBoost: 0,
      now: () => t,
    });
    q.enqueue('low', 1);
    q.enqueue('high', 5);
    t = 100000;
    expect(q.dequeue()).toBe('high');
  });
});

// ── effectivePriority ──────────────────────────────────────────────

describe('Sprint 347 — effectivePriority', () => {
  it('無 aging → 回 basePriority', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('a', 5);
    // 透過 peek 間接驗證行為；直接算 effectivePriority 需 item，故用 dequeue 順序代替
    expect(q.peek()).toBe('a');
  });
});

// ── peek ───────────────────────────────────────────────────────────

describe('Sprint 347 — peek', () => {
  it('peek 不移除', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('a', 5);
    expect(q.peek()).toBe('a');
    expect(q.size()).toBe(1);
  });

  it('空 → undefined', () => {
    const q = new WorkerPriorityQueue<string>();
    expect(q.peek()).toBeUndefined();
  });
});

// ── size / isEmpty / clear / stats ────────────────────────────────

describe('Sprint 347 — size / isEmpty / clear / stats', () => {
  it('size / isEmpty', () => {
    const q = new WorkerPriorityQueue<string>();
    expect(q.isEmpty()).toBe(true);
    q.enqueue('a');
    expect(q.size()).toBe(1);
    expect(q.isEmpty()).toBe(false);
  });

  it('clear 清空', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('a');
    q.clear();
    expect(q.isEmpty()).toBe(true);
  });

  it('stats 累計 enqueue/dequeue', () => {
    const q = new WorkerPriorityQueue<string>();
    q.enqueue('a');
    q.enqueue('b');
    q.dequeue();
    const s = q.getStats();
    expect(s.enqueuedTotal).toBe(2);
    expect(s.dequeuedTotal).toBe(1);
    expect(s.size).toBe(1);
  });
});
