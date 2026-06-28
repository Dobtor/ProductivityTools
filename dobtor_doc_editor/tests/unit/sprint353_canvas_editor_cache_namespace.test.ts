/**
 * Sprint 353 — ① deeper¹³：CanvasEditorCacheNamespace。
 *
 * Sprint 333 lifecycle + Sprint 348 codec 之後深推。多 doc cache 分區。
 *
 * 紀律 #18：純函式 + 組合既有 module；不接 production canvas-editor。
 */
import { describe, expect, it } from 'vitest';

import {
  nsKey,
  parseNsKey,
  namespacePrefix,
  invalidateNamespace,
  nsSet,
  nsGet,
  groupKeysByNamespace,
} from '../../static/src/core/ooxml/font/CanvasEditorCacheNamespace';
import { CanvasEditorCacheLifecycle } from '../../static/src/core/ooxml/font/CanvasEditorCacheLifecycle';
import type { CacheKeyParts } from '../../static/src/core/ooxml/font/CanvasEditorCacheKeyCodec';

const parts = (family: string, sizePt: number, text: string): CacheKeyParts => ({
  family,
  sizePt,
  text,
});

// ── nsKey / parseNsKey round-trip ─────────────────────────────────

describe('Sprint 353 — nsKey / parseNsKey', () => {
  it('round-trip', () => {
    const k = nsKey('docA', parts('Arial', 10, 'hi'));
    const parsed = parseNsKey(k);
    expect(parsed?.namespace).toBe('docA');
    expect(parsed?.parts).toEqual(parts('Arial', 10, 'hi'));
  });

  it('text 含 | → 仍可還原（codec escape）', () => {
    const k = nsKey('docA', parts('Arial', 10, 'a|b'));
    expect(parseNsKey(k)?.parts.text).toBe('a|b');
  });

  it('namespace 含 :: → throw', () => {
    expect(() => nsKey('doc::bad', parts('A', 10, 'x'))).toThrow();
  });

  it('無 :: → parseNsKey 回 null', () => {
    expect(parseNsKey('no-separator-here')).toBeNull();
  });

  it('parts decode 失敗 → null', () => {
    expect(parseNsKey('docA::malformed')).toBeNull();
  });

  it('encoded 部分含 : 不影響 ns 切分', () => {
    // text 含冒號（非 ::）
    const k = nsKey('docA', parts('Arial', 10, 'a:b:c'));
    const parsed = parseNsKey(k);
    expect(parsed?.namespace).toBe('docA');
    expect(parsed?.parts.text).toBe('a:b:c');
  });
});

// ── namespacePrefix ────────────────────────────────────────────────

describe('Sprint 353 — namespacePrefix', () => {
  it('回 namespace::', () => {
    expect(namespacePrefix('docA')).toBe('docA::');
  });
});

// ── nsSet / nsGet ──────────────────────────────────────────────────

describe('Sprint 353 — nsSet / nsGet', () => {
  it('寫入後可取回', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    nsSet(cache, 'docA', parts('Arial', 10, 'hi'), 42);
    expect(nsGet(cache, 'docA', parts('Arial', 10, 'hi'))).toBe(42);
  });

  it('不同 namespace 同 parts → 互不干擾', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    nsSet(cache, 'docA', parts('Arial', 10, 'hi'), 1);
    nsSet(cache, 'docB', parts('Arial', 10, 'hi'), 2);
    expect(nsGet(cache, 'docA', parts('Arial', 10, 'hi'))).toBe(1);
    expect(nsGet(cache, 'docB', parts('Arial', 10, 'hi'))).toBe(2);
  });
});

// ── invalidateNamespace ────────────────────────────────────────────

describe('Sprint 353 — invalidateNamespace', () => {
  it('只清掉指定 namespace', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    nsSet(cache, 'docA', parts('Arial', 10, 'a'), 1);
    nsSet(cache, 'docA', parts('Arial', 10, 'b'), 2);
    nsSet(cache, 'docB', parts('Arial', 10, 'a'), 3);
    expect(invalidateNamespace(cache, 'docA')).toBe(2);
    expect(nsGet(cache, 'docA', parts('Arial', 10, 'a'))).toBeUndefined();
    expect(nsGet(cache, 'docB', parts('Arial', 10, 'a'))).toBe(3);
  });

  it('不存在 namespace → 0', () => {
    const cache = new CanvasEditorCacheLifecycle<number>();
    expect(invalidateNamespace(cache, 'ghost')).toBe(0);
  });
});

// ── groupKeysByNamespace ──────────────────────────────────────────

describe('Sprint 353 — groupKeysByNamespace', () => {
  it('依 namespace 計數', () => {
    const keys = [
      nsKey('docA', parts('Arial', 10, 'a')),
      nsKey('docA', parts('Arial', 10, 'b')),
      nsKey('docB', parts('Arial', 10, 'a')),
    ];
    const counts = groupKeysByNamespace(keys);
    expect(counts.get('docA')).toBe(2);
    expect(counts.get('docB')).toBe(1);
  });

  it('非 ns key 被忽略', () => {
    const counts = groupKeysByNamespace(['no-sep', nsKey('docA', parts('A', 10, 'x'))]);
    expect(counts.get('docA')).toBe(1);
    expect(counts.size).toBe(1);
  });

  it('空 → 空 map', () => {
    expect(groupKeysByNamespace([]).size).toBe(0);
  });
});
