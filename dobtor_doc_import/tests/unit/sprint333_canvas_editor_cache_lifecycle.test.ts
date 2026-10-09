/**
 * Sprint 333 — ① deeper⁹：CanvasEditorCacheLifecycle。
 *
 * Sprint 302 FIFO / Sprint 328 snapshot 之後深推。LRU + TTL + invalidation。
 *
 * 紀律 #18：純記憶體 K/V cache；caller 自負持久化；不接 production canvas-editor。
 */
import { describe, expect, it } from 'vitest';

import { CanvasEditorCacheLifecycle } from '../../static/src/core/ooxml/font/CanvasEditorCacheLifecycle';

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 333 — constructor 驗證', () => {
  it('maxEntries <= 0 throw', () => {
    expect(() => new CanvasEditorCacheLifecycle({ maxEntries: 0 })).toThrow();
  });
  it('ttlMs <= 0 throw', () => {
    expect(() => new CanvasEditorCacheLifecycle({ ttlMs: 0 })).toThrow();
  });
  it('default maxEntries = 256', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    expect(c.size()).toBe(0);
  });
});

// ── set/get + hit/miss ─────────────────────────────────────────────

describe('Sprint 333 — set/get hit/miss', () => {
  it('set → get 命中', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    expect(c.get('a')).toBe(1);
    expect(c.getStats().hits).toBe(1);
    expect(c.getStats().misses).toBe(0);
  });

  it('未存在 → miss', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    expect(c.get('x')).toBeUndefined();
    expect(c.getStats().misses).toBe(1);
  });

  it('hitRate 計算正確', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    c.get('a');
    c.get('a');
    c.get('x');
    const s = c.getStats();
    expect(s.hitRate).toBeCloseTo(2 / 3);
  });
});

// ── LRU eviction ───────────────────────────────────────────────────

describe('Sprint 333 — LRU eviction', () => {
  it('超過 maxEntries → 丟最久沒用的', () => {
    const c = new CanvasEditorCacheLifecycle<number>({ maxEntries: 2 });
    c.set('a', 1);
    c.set('b', 2);
    c.set('c', 3); // 'a' 被丟
    expect(c.has('a')).toBe(false);
    expect(c.has('b')).toBe(true);
    expect(c.has('c')).toBe(true);
    expect(c.getStats().lruEvictions).toBe(1);
  });

  it('get 後 reorder：剛 get 的不會被丟', () => {
    const c = new CanvasEditorCacheLifecycle<number>({ maxEntries: 2 });
    c.set('a', 1);
    c.set('b', 2);
    c.get('a'); // 'a' 變最新
    c.set('c', 3); // 'b' 被丟
    expect(c.has('a')).toBe(true);
    expect(c.has('b')).toBe(false);
  });

  it('set 同 key → 不算 eviction、只 reorder', () => {
    const c = new CanvasEditorCacheLifecycle<number>({ maxEntries: 2 });
    c.set('a', 1);
    c.set('b', 2);
    c.set('a', 100);
    expect(c.size()).toBe(2);
    expect(c.get('a')).toBe(100);
    expect(c.getStats().lruEvictions).toBe(0);
  });
});

// ── TTL ────────────────────────────────────────────────────────────

describe('Sprint 333 — TTL eviction', () => {
  it('TTL 內 → 命中', () => {
    let t = 1000;
    const c = new CanvasEditorCacheLifecycle<number>({ ttlMs: 100, now: () => t });
    c.set('a', 1);
    t += 50;
    expect(c.get('a')).toBe(1);
  });

  it('TTL 過 → miss + 刪除', () => {
    let t = 1000;
    const c = new CanvasEditorCacheLifecycle<number>({ ttlMs: 100, now: () => t });
    c.set('a', 1);
    t += 200;
    expect(c.get('a')).toBeUndefined();
    expect(c.getStats().ttlEvictions).toBe(1);
    expect(c.size()).toBe(0);
  });

  it('purgeExpired 主動掃 → 清掉過期', () => {
    let t = 1000;
    const c = new CanvasEditorCacheLifecycle<number>({ ttlMs: 100, now: () => t });
    c.set('a', 1);
    c.set('b', 2);
    t += 200;
    c.set('c', 3); // c 仍新
    expect(c.purgeExpired()).toBe(2);
    expect(c.size()).toBe(1);
    expect(c.has('c')).toBe(true);
  });

  it('無 TTL 設定 → purgeExpired 回 0', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    expect(c.purgeExpired()).toBe(0);
  });
});

// ── invalidate ─────────────────────────────────────────────────────

describe('Sprint 333 — invalidate', () => {
  it('invalidate(key) → 刪除單一', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    expect(c.invalidate('a')).toBe(true);
    expect(c.has('a')).toBe(false);
  });

  it('invalidate 不存在 → false', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    expect(c.invalidate('x')).toBe(false);
  });

  it('invalidateByPrefix → 批次清', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('Arial:10:hi', 1);
    c.set('Arial:12:hi', 2);
    c.set('Times:10:hi', 3);
    expect(c.invalidateByPrefix('Arial:')).toBe(2);
    expect(c.has('Times:10:hi')).toBe(true);
  });

  it('invalidateWhere → predicate-based', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    c.set('b', 2);
    c.set('c', 3);
    expect(c.invalidateWhere((_k, v) => v >= 2)).toBe(2);
    expect(c.has('a')).toBe(true);
  });
});

// ── clear ──────────────────────────────────────────────────────────

describe('Sprint 333 — clear', () => {
  it('清掉所有 entries', () => {
    const c = new CanvasEditorCacheLifecycle<number>();
    c.set('a', 1);
    c.set('b', 2);
    c.clear();
    expect(c.size()).toBe(0);
  });
});
