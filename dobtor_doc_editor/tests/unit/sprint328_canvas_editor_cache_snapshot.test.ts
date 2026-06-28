/**
 * Sprint 328 — ① deeper⁸：CanvasEditorCacheSnapshot。
 *
 * Sprint 323 PrewarmStrategy 之後深推。JSON-safe serializer for cross-session
 * persistence of prewarm result。
 *
 * 紀律 #18 scope-down：純 JSON / 記憶體；caller 自行 storage / 壓縮 / 加密。
 */
import { describe, expect, it } from 'vitest';

import {
  CANVAS_EDITOR_CACHE_SCHEMA_VERSION,
  toSnapshot,
  fromSnapshot,
  mergeSnapshots,
  pickByMinFrequency,
  summarizeSnapshot,
} from '../../static/src/core/ooxml/font/CanvasEditorCacheSnapshot';
import type { PrewarmEntryWithMeta } from '../../static/src/core/ooxml/font/CanvasEditorPrewarmStrategy';

const mkEntry = (
  text: string,
  family: string,
  sizePt: number,
  frequency: number,
  charset?: 'cjk' | 'latin' | 'mixed' | 'empty',
): PrewarmEntryWithMeta => ({ text, family, sizePt, frequency, charset });

// ── toSnapshot ─────────────────────────────────────────────────────

describe('Sprint 328 — toSnapshot 結構', () => {
  it('回 v1 snapshot 含 schemaVersion + createdAt + entries', () => {
    const entries = [mkEntry('hello', 'Arial', 10, 5, 'latin')];
    const s = toSnapshot(entries, { now: () => '2026-05-28T00:00:00.000Z' });
    expect(s.schemaVersion).toBe(CANVAS_EDITOR_CACHE_SCHEMA_VERSION);
    expect(s.createdAt).toBe('2026-05-28T00:00:00.000Z');
    expect(s.entries).toBe(entries);
  });

  it('未注入 now → 回的 createdAt 是 ISO string', () => {
    const s = toSnapshot([]);
    expect(s.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

// ── fromSnapshot ───────────────────────────────────────────────────

describe('Sprint 328 — fromSnapshot 驗證', () => {
  it('valid snapshot → 原樣回', () => {
    const orig = toSnapshot([mkEntry('a', 'Arial', 10, 1, 'latin')], {
      now: () => '2026-05-28T00:00:00.000Z',
    });
    const parsed = fromSnapshot(JSON.parse(JSON.stringify(orig)));
    expect(parsed).not.toBeNull();
    expect(parsed?.entries).toHaveLength(1);
    expect(parsed?.entries[0].text).toBe('a');
  });

  it('null / undefined / primitive → 回 null', () => {
    expect(fromSnapshot(null)).toBeNull();
    expect(fromSnapshot(undefined)).toBeNull();
    expect(fromSnapshot(42)).toBeNull();
    expect(fromSnapshot('hello')).toBeNull();
  });

  it('schemaVersion 不符 → 回 null', () => {
    expect(fromSnapshot({ schemaVersion: 2, createdAt: 'x', entries: [] })).toBeNull();
    expect(fromSnapshot({ schemaVersion: 0, createdAt: 'x', entries: [] })).toBeNull();
  });

  it('entries 不是 array → 回 null', () => {
    expect(
      fromSnapshot({ schemaVersion: 1, createdAt: 'x', entries: 'oops' }),
    ).toBeNull();
  });

  it('entry 缺欄位 → 回 null', () => {
    const bad = {
      schemaVersion: 1,
      createdAt: 'x',
      entries: [{ text: 'a', family: 'Arial' /* sizePt 缺 */ }],
    };
    expect(fromSnapshot(bad)).toBeNull();
  });

  it('entry sizePt 為 NaN / Infinity → 回 null', () => {
    expect(
      fromSnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        entries: [{ text: 'a', family: 'Arial', sizePt: NaN, frequency: 1 }],
      }),
    ).toBeNull();
    expect(
      fromSnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        entries: [{ text: 'a', family: 'Arial', sizePt: Infinity, frequency: 1 }],
      }),
    ).toBeNull();
  });

  it('entry charset 為非預設值 → 回 null', () => {
    expect(
      fromSnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        entries: [{ text: 'a', family: 'Arial', sizePt: 10, frequency: 1, charset: 'xx' }],
      }),
    ).toBeNull();
  });

  it('entry charset undefined → OK', () => {
    expect(
      fromSnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        entries: [{ text: 'a', family: 'Arial', sizePt: 10, frequency: 1 }],
      }),
    ).not.toBeNull();
  });
});

// ── mergeSnapshots ─────────────────────────────────────────────────

describe('Sprint 328 — mergeSnapshots', () => {
  it('同 (text,family,sizePt) → frequency 累加', () => {
    const a = toSnapshot([mkEntry('hello', 'Arial', 10, 3, 'latin')], {
      now: () => '2026-05-27T00:00:00.000Z',
    });
    const b = toSnapshot([mkEntry('hello', 'Arial', 10, 7, 'latin')], {
      now: () => '2026-05-28T00:00:00.000Z',
    });
    const merged = mergeSnapshots(a, b);
    expect(merged.entries).toHaveLength(1);
    expect(merged.entries[0].frequency).toBe(10);
    expect(merged.createdAt).toBe('2026-05-28T00:00:00.000Z');
  });

  it('不同 key → 兩個 entry 都留', () => {
    const a = toSnapshot([mkEntry('hello', 'Arial', 10, 3)]);
    const b = toSnapshot([mkEntry('world', 'Arial', 10, 2)]);
    const merged = mergeSnapshots(a, b);
    expect(merged.entries).toHaveLength(2);
  });

  it('b 有 charset、a 無 → 取 b', () => {
    const a = toSnapshot([mkEntry('hi', 'Arial', 10, 1)]);
    const b = toSnapshot([mkEntry('hi', 'Arial', 10, 1, 'latin')]);
    const merged = mergeSnapshots(a, b);
    expect(merged.entries[0].charset).toBe('latin');
  });

  it('a 有 charset → 優先用 a', () => {
    const a = toSnapshot([mkEntry('hi', 'Arial', 10, 1, 'mixed')]);
    const b = toSnapshot([mkEntry('hi', 'Arial', 10, 1, 'latin')]);
    const merged = mergeSnapshots(a, b);
    expect(merged.entries[0].charset).toBe('mixed');
  });
});

// ── pickByMinFrequency ──────────────────────────────────────────────

describe('Sprint 328 — pickByMinFrequency', () => {
  it('過濾掉低於 min 的', () => {
    const entries = [
      mkEntry('a', 'A', 10, 1),
      mkEntry('b', 'A', 10, 5),
      mkEntry('c', 'A', 10, 10),
    ];
    expect(pickByMinFrequency(entries, 5)).toHaveLength(2);
  });

  it('min=0 → 全留', () => {
    const entries = [mkEntry('a', 'A', 10, 0)];
    expect(pickByMinFrequency(entries, 0)).toHaveLength(1);
  });
});

// ── summarizeSnapshot ──────────────────────────────────────────────

describe('Sprint 328 — summarizeSnapshot', () => {
  it('累加 frequency + 各 charset 計數', () => {
    const s = toSnapshot([
      mkEntry('a', 'A', 10, 2, 'latin'),
      mkEntry('字', 'B', 12, 3, 'cjk'),
      mkEntry('mix', 'C', 10, 1, 'mixed'),
      mkEntry('?', 'D', 10, 1),
    ]);
    const sum = summarizeSnapshot(s);
    expect(sum.totalEntries).toBe(4);
    expect(sum.totalFrequency).toBe(7);
    expect(sum.byCharset.latin).toBe(1);
    expect(sum.byCharset.cjk).toBe(1);
    expect(sum.byCharset.mixed).toBe(1);
    expect(sum.byCharset.unknown).toBe(1);
  });

  it('空 snapshot → 全 0', () => {
    const sum = summarizeSnapshot(toSnapshot([]));
    expect(sum.totalEntries).toBe(0);
    expect(sum.totalFrequency).toBe(0);
  });
});
