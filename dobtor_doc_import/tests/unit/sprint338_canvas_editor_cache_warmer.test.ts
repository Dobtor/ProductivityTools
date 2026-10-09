/**
 * Sprint 338 — ① deeper¹⁰：CanvasEditorCacheWarmer。
 *
 * Sprint 328 snapshot + Sprint 333 lifecycle 之後深推。Snapshot → lifecycle seeder。
 *
 * 紀律 #18：pure-fn seeder + key helper；caller 自負 valueFactory + maxEntries。
 */
import { describe, expect, it } from 'vitest';

import {
  keyFor,
  warmFromSnapshot,
  exportLifecycleAsEntries,
  predictWarmFootprint,
} from '../../static/src/core/ooxml/font/CanvasEditorCacheWarmer';
import { CanvasEditorCacheLifecycle } from '../../static/src/core/ooxml/font/CanvasEditorCacheLifecycle';
import { toSnapshot } from '../../static/src/core/ooxml/font/CanvasEditorCacheSnapshot';
import type { PrewarmEntryWithMeta } from '../../static/src/core/ooxml/font/CanvasEditorPrewarmStrategy';

const e = (
  text: string,
  family: string,
  sizePt: number,
  freq = 1,
  charset?: 'cjk' | 'latin' | 'mixed' | 'empty',
): PrewarmEntryWithMeta => ({ text, family, sizePt, frequency: freq, charset });

// ── keyFor ─────────────────────────────────────────────────────────

describe('Sprint 338 — keyFor', () => {
  it('format = family|sizePt|text', () => {
    expect(keyFor(e('hi', 'Arial', 10))).toBe('Arial|10|hi');
  });
  it('text 含 | 不會 mangle key（caller 自負）', () => {
    expect(keyFor(e('a|b', 'Arial', 10))).toBe('Arial|10|a|b');
  });
});

// ── warmFromSnapshot ───────────────────────────────────────────────

describe('Sprint 338 — warmFromSnapshot', () => {
  it('seed 全部 entries → cache.size 等於 entries 數', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    const snapshot = toSnapshot([e('a', 'A', 10), e('b', 'A', 10)]);
    expect(warmFromSnapshot(cache, snapshot, (en) => en.frequency)).toBe(2);
    expect(cache.size()).toBe(2);
  });

  it('cache 有 maxEntries → 超過自然 LRU 驅逐', () => {
    const cache = new CanvasEditorCacheLifecycle<number>({ maxEntries: 2 });
    const snapshot = toSnapshot([e('a', 'A', 10), e('b', 'A', 10), e('c', 'A', 10)]);
    warmFromSnapshot(cache, snapshot, (en) => en.frequency);
    expect(cache.size()).toBe(2);
    // 'a' 被丟（最舊）
    expect(cache.has('A|10|a')).toBe(false);
    expect(cache.has('A|10|c')).toBe(true);
  });

  it('valueFactory 接收 entry 並產生 value', () => {
    const cache = new CanvasEditorCacheLifecycle<{ width: number }>();
    const snapshot = toSnapshot([e('hello', 'Arial', 10)]);
    warmFromSnapshot(cache, snapshot, (en) => ({ width: en.text.length * 6 }));
    expect(cache.get('Arial|10|hello')).toEqual({ width: 30 });
  });

  it('空 snapshot → 寫 0 筆', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    expect(warmFromSnapshot(cache, toSnapshot([]), () => 0)).toBe(0);
    expect(cache.size()).toBe(0);
  });
});

// ── exportLifecycleAsEntries ───────────────────────────────────────

describe('Sprint 338 — exportLifecycleAsEntries', () => {
  it('簡單 dump：frequency 固定 1', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    const entries = exportLifecycleAsEntries(cache, [
      { text: 'a', family: 'Arial', sizePt: 10 },
    ]);
    expect(entries).toHaveLength(1);
    expect(entries[0].frequency).toBe(1);
  });

  it('帶 charset → 一併輸出', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    const entries = exportLifecycleAsEntries(cache, [
      { text: '字', family: 'Arial', sizePt: 12, charset: 'cjk' },
    ]);
    expect(entries[0].charset).toBe('cjk');
  });

  it('空 → 空 array', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    expect(exportLifecycleAsEntries(cache, [])).toEqual([]);
  });
});

// ── predictWarmFootprint ───────────────────────────────────────────

describe('Sprint 338 — predictWarmFootprint', () => {
  it('全留', () => {
    const s = toSnapshot([e('a', 'A', 10), e('b', 'A', 10)]);
    expect(predictWarmFootprint(s, 10)).toEqual({ keptCount: 2, droppedCount: 0 });
  });
  it('部分丟', () => {
    const s = toSnapshot([e('a', 'A', 10), e('b', 'A', 10), e('c', 'A', 10)]);
    expect(predictWarmFootprint(s, 2)).toEqual({ keptCount: 2, droppedCount: 1 });
  });
  it('cacheMax=0 → 全丟', () => {
    const s = toSnapshot([e('a', 'A', 10)]);
    expect(predictWarmFootprint(s, 0)).toEqual({ keptCount: 0, droppedCount: 1 });
  });
});

// ── round-trip 場景：snapshot → cache → 再 export ─────────────────

describe('Sprint 338 — round-trip 場景', () => {
  it('snapshot 灌 cache 後 get/has 命中', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    const snapshot = toSnapshot([e('hello', 'Arial', 10, 5)]);
    warmFromSnapshot(cache, snapshot, (en) => en.frequency);
    expect(cache.get('Arial|10|hello')).toBe(5);
    expect(cache.has('Arial|10|hello')).toBe(true);
  });
});
