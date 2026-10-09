/**
 * Sprint 343 — ① deeper¹¹：CanvasEditorCacheCoordinator。
 *
 * Sprint 328 snapshot + 333 lifecycle + 338 warmer 第四層整合 orchestration。
 *
 * 紀律 #18：純 orchestration；不接 storage / production canvas-editor。
 */
import { describe, expect, it } from 'vitest';

import { CanvasEditorCacheCoordinator } from '../../static/src/core/ooxml/font/CanvasEditorCacheCoordinator';
import { toSnapshot } from '../../static/src/core/ooxml/font/CanvasEditorCacheSnapshot';
import { keyFor } from '../../static/src/core/ooxml/font/CanvasEditorCacheWarmer';
import type { PrewarmEntryWithMeta } from '../../static/src/core/ooxml/font/CanvasEditorPrewarmStrategy';

const e = (
  text: string,
  family: string,
  sizePt: number,
  freq = 1,
): PrewarmEntryWithMeta => ({ text, family, sizePt, frequency: freq });

// ── restore ────────────────────────────────────────────────────────

describe('Sprint 343 — restore', () => {
  it('snapshot → warm cache、回寫入數', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    const written = co.restore(toSnapshot([e('a', 'A', 10), e('b', 'A', 10)]), (en) => en.frequency);
    expect(written).toBe(2);
    expect(co.get(keyFor(e('a', 'A', 10)))).toBe(1);
  });

  it('restore 不標 dirty', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.restore(toSnapshot([e('a', 'A', 10)]), () => 1);
    expect(co.isDirty()).toBe(false);
  });

  it('restoredCount 累計', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.restore(toSnapshot([e('a', 'A', 10)]), () => 1);
    co.restore(toSnapshot([e('b', 'A', 10)]), () => 1);
    expect(co.getStats().restoredCount).toBe(2);
  });
});

// ── set / get / dirty ──────────────────────────────────────────────

describe('Sprint 343 — set/get + dirty tracking', () => {
  it('set 後 dirty=true', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.set('k', 1);
    expect(co.isDirty()).toBe(true);
    expect(co.get('k')).toBe(1);
  });

  it('setByEntry 走 keyFor', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.setByEntry(e('hi', 'Arial', 10), 42);
    expect(co.get('Arial|10|hi')).toBe(42);
    expect(co.has('Arial|10|hi')).toBe(true);
  });
});

// ── persist ────────────────────────────────────────────────────────

describe('Sprint 343 — persist', () => {
  it('dump entries → snapshot + 清 dirty', () => {
    const co = new CanvasEditorCacheCoordinator<number>({
      snapshotNow: () => '2026-05-28T00:00:00.000Z',
    });
    co.set('k', 1);
    expect(co.isDirty()).toBe(true);
    const snap = co.persist([e('a', 'A', 10)]);
    expect(snap.createdAt).toBe('2026-05-28T00:00:00.000Z');
    expect(snap.entries).toHaveLength(1);
    expect(co.isDirty()).toBe(false);
    expect(co.getStats().persistCount).toBe(1);
  });

  it('persist 空 entries → 空 snapshot', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    const snap = co.persist([]);
    expect(snap.entries).toHaveLength(0);
  });
});

// ── invalidate ─────────────────────────────────────────────────────

describe('Sprint 343 — invalidate', () => {
  it('invalidate 命中 → dirty=true', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.restore(toSnapshot([e('a', 'A', 10)]), () => 1);
    expect(co.isDirty()).toBe(false);
    expect(co.invalidate('A|10|a')).toBe(true);
    expect(co.isDirty()).toBe(true);
  });

  it('invalidate 未命中 → 不標 dirty', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    expect(co.invalidate('nope')).toBe(false);
    expect(co.isDirty()).toBe(false);
  });

  it('invalidateByPrefix 命中 → dirty', () => {
    const co = new CanvasEditorCacheCoordinator<number>();
    co.restore(toSnapshot([e('a', 'Arial', 10), e('b', 'Arial', 12)]), () => 1);
    expect(co.invalidateByPrefix('Arial|')).toBe(2);
    expect(co.isDirty()).toBe(true);
  });
});

// ── TTL purge ──────────────────────────────────────────────────────

describe('Sprint 343 — purgeExpired 透傳', () => {
  it('TTL coordinator + 注入 now clock → 過期清掉', () => {
    let t = 1000;
    const co = new CanvasEditorCacheCoordinator<number>({ ttlMs: 100, now: () => t });
    co.set('k', 1);
    t += 200; // 超過 TTL
    expect(co.purgeExpired()).toBe(1);
  });

  it('未過期 → purge 回 0', () => {
    let t = 1000;
    const co = new CanvasEditorCacheCoordinator<number>({ ttlMs: 100, now: () => t });
    co.set('k', 1);
    t += 50;
    expect(co.purgeExpired()).toBe(0);
  });
});

// ── round-trip ─────────────────────────────────────────────────────

describe('Sprint 343 — restore → use → persist round-trip', () => {
  it('還原後使用、再 persist 出 snapshot', () => {
    const co = new CanvasEditorCacheCoordinator<number>({
      snapshotNow: () => '2026-05-28T12:00:00.000Z',
    });
    co.restore(toSnapshot([e('hello', 'Arial', 10, 5)]), (en) => en.frequency);
    expect(co.get('Arial|10|hello')).toBe(5);
    co.setByEntry(e('world', 'Arial', 10, 3), 99);
    const snap = co.persist([e('hello', 'Arial', 10, 5), e('world', 'Arial', 10, 3)]);
    expect(snap.entries).toHaveLength(2);
    expect(co.isDirty()).toBe(false);
  });
});
