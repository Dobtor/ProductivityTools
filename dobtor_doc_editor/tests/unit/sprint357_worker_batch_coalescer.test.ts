/**
 * Sprint 357 — ⑥ deeper¹³：WorkerBatchCoalescer。
 *
 * Sprint 352 scheduler 之後補 batch coalescing：window 收集 + maxBatchSize/手動 flush。
 *
 * 紀律 #18：純收集/flush 邏輯；caller 提供 onFlush + flush timer；不接 production worker。
 */
import { describe, expect, it } from 'vitest';

import { WorkerBatchCoalescer } from '../../static/src/core/ooxml/worker/WorkerBatchCoalescer';

function mkCoalescer(maxBatchSize: number) {
  const batches: string[][] = [];
  const c = new WorkerBatchCoalescer<string>({
    maxBatchSize,
    onFlush: (batch) => batches.push(batch),
  });
  return { c, batches };
}

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 357 — constructor', () => {
  it('maxBatchSize <= 0 throw', () => {
    expect(() => new WorkerBatchCoalescer<string>({ maxBatchSize: 0, onFlush: () => {} })).toThrow();
  });
});

// ── add + auto flush ───────────────────────────────────────────────

describe('Sprint 357 — add + auto flush', () => {
  it('達 maxBatchSize → auto flush', () => {
    const { c, batches } = mkCoalescer(3);
    c.add('a');
    c.add('b');
    expect(batches).toHaveLength(0);
    c.add('c'); // 第 3 個 → flush
    expect(batches).toHaveLength(1);
    expect(batches[0]).toEqual(['a', 'b', 'c']);
    expect(c.pendingCount()).toBe(0);
  });

  it('未達 → 不 flush', () => {
    const { c, batches } = mkCoalescer(5);
    c.add('a');
    c.add('b');
    expect(batches).toHaveLength(0);
    expect(c.pendingCount()).toBe(2);
  });

  it('連續超過 → 多次 auto flush', () => {
    const { c, batches } = mkCoalescer(2);
    c.add('a');
    c.add('b'); // flush 1
    c.add('c');
    c.add('d'); // flush 2
    expect(batches).toHaveLength(2);
    expect(batches[0]).toEqual(['a', 'b']);
    expect(batches[1]).toEqual(['c', 'd']);
  });
});

// ── addAll ─────────────────────────────────────────────────────────

describe('Sprint 357 — addAll', () => {
  it('一次塞多個、觸發 auto flush + 留 pending', () => {
    const { c, batches } = mkCoalescer(2);
    c.addAll(['a', 'b', 'c', 'd', 'e']);
    // flush at 2, 4; 'e' pending
    expect(batches).toHaveLength(2);
    expect(c.pendingCount()).toBe(1);
  });
});

// ── 手動 flush ─────────────────────────────────────────────────────

describe('Sprint 357 — 手動 flush', () => {
  it('flush 當前 pending', () => {
    const { c, batches } = mkCoalescer(10);
    c.add('a');
    c.add('b');
    c.flush();
    expect(batches).toHaveLength(1);
    expect(batches[0]).toEqual(['a', 'b']);
    expect(c.pendingCount()).toBe(0);
  });

  it('空 pending flush → no-op、不呼叫 onFlush', () => {
    const { c, batches } = mkCoalescer(10);
    c.flush();
    expect(batches).toHaveLength(0);
  });
});

// ── discard ────────────────────────────────────────────────────────

describe('Sprint 357 — discard', () => {
  it('丟棄 pending、不 flush', () => {
    const { c, batches } = mkCoalescer(10);
    c.add('a');
    c.add('b');
    expect(c.discard()).toBe(2);
    expect(c.pendingCount()).toBe(0);
    expect(batches).toHaveLength(0);
  });
});

// ── stats ──────────────────────────────────────────────────────────

describe('Sprint 357 — getStats', () => {
  it('累計 item / flush / autoFlush', () => {
    const { c } = mkCoalescer(2);
    c.add('a');
    c.add('b'); // auto flush 1
    c.add('c');
    c.flush(); // 手動 flush
    const s = c.getStats();
    expect(s.itemCount).toBe(3);
    expect(s.flushCount).toBe(2); // auto + manual
    expect(s.autoFlushCount).toBe(1);
    expect(s.pending).toBe(0);
  });
});
