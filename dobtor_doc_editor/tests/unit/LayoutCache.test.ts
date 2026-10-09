/**
 * Sprint 58 — LayoutCache 單元測試
 *
 * 範圍：
 *   1. 基本 put/get/has/clear
 *   2. LRU 淘汰 + touch
 *   3. canonicalizeJson 穩定（key 順序不影響輸出）
 *   4. hashLayoutOptions 對相同 opts 回相同 hash、不同 opts 回不同 hash
 *   5. composeLayoutKey 連接 docxHash + optsHash
 */

import { describe, expect, it } from 'vitest';
import {
  LayoutCache,
  canonicalizeJson,
  hashLayoutOptions,
  composeLayoutKey,
} from '../../static/src/core/cache/layout_cache';
import type { DocumentLayout } from '../../static/src/core/layout';

function makeFakeLayout(tag: string): DocumentLayout {
  return {
    pages: [],
    warnings: [tag],
  } as unknown as DocumentLayout;
}

describe('LayoutCache — 基本行為', () => {
  it('miss 回 undefined、hit 回原值', () => {
    const c = new LayoutCache();
    expect(c.get('k1')).toBeUndefined();
    const v = makeFakeLayout('A');
    c.put('k1', v);
    expect(c.get('k1')).toBe(v);
  });

  it('stats 正確計數', () => {
    const c = new LayoutCache();
    c.put('k', makeFakeLayout('v'));
    c.get('k'); // hit
    c.get('k'); // hit
    c.get('nope'); // miss
    expect(c.stats()).toEqual({ hits: 2, misses: 1, size: 1 });
  });

  it('has 不影響 hits/misses', () => {
    const c = new LayoutCache();
    c.put('k', makeFakeLayout('v'));
    c.has('k');
    c.has('nope');
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 1 });
  });

  it('clear() 重置', () => {
    const c = new LayoutCache();
    c.put('k', makeFakeLayout('v'));
    c.get('k');
    c.clear();
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 0 });
    expect(c.get('k')).toBeUndefined();
  });

  it('maxEntries <= 0 throw', () => {
    expect(() => new LayoutCache({ maxEntries: 0 })).toThrow();
    expect(() => new LayoutCache({ maxEntries: -1 })).toThrow();
    expect(() => new LayoutCache({ maxEntries: 1.5 })).toThrow();
  });
});

describe('LayoutCache — LRU 淘汰', () => {
  it('超過 maxEntries 淘汰最舊', () => {
    const c = new LayoutCache({ maxEntries: 3 });
    c.put('A', makeFakeLayout('a'));
    c.put('B', makeFakeLayout('b'));
    c.put('C', makeFakeLayout('c'));
    c.put('D', makeFakeLayout('d')); // A 被淘汰
    expect(c.has('A')).toBe(false);
    expect(c.has('B')).toBe(true);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
  });

  it('get() 後 entry 推到最新端、避免被淘汰', () => {
    const c = new LayoutCache({ maxEntries: 3 });
    c.put('A', makeFakeLayout('a'));
    c.put('B', makeFakeLayout('b'));
    c.put('C', makeFakeLayout('c'));
    c.get('A'); // touch A
    c.put('D', makeFakeLayout('d')); // 應淘汰 B
    expect(c.has('A')).toBe(true);
    expect(c.has('B')).toBe(false);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
  });

  it('既存 key 重複 put 不增加 size', () => {
    const c = new LayoutCache({ maxEntries: 2 });
    c.put('A', makeFakeLayout('a'));
    c.put('B', makeFakeLayout('b'));
    const a2 = makeFakeLayout('a2');
    c.put('A', a2);
    expect(c.stats().size).toBe(2);
    expect(c.get('A')).toBe(a2);
  });
});

describe('canonicalizeJson — key 順序穩定', () => {
  it('同樣 object 不同 key 順序回相同字串', () => {
    expect(canonicalizeJson({ a: 1, b: 2 })).toBe(canonicalizeJson({ b: 2, a: 1 }));
  });

  it('遞迴穩定（nested object）', () => {
    expect(canonicalizeJson({ a: { x: 1, y: 2 } })).toBe(canonicalizeJson({ a: { y: 2, x: 1 } }));
  });

  it('undefined 屬性會被剔除', () => {
    expect(canonicalizeJson({ a: 1, b: undefined })).toBe('{"a":1}');
  });

  it('array 順序保留', () => {
    expect(canonicalizeJson([1, 2, 3])).toBe('[1,2,3]');
    expect(canonicalizeJson([1, 2, 3])).not.toBe(canonicalizeJson([3, 2, 1]));
  });

  it('primitive', () => {
    expect(canonicalizeJson(42)).toBe('42');
    expect(canonicalizeJson('hello')).toBe('"hello"');
    expect(canonicalizeJson(null)).toBe('null');
    expect(canonicalizeJson(true)).toBe('true');
  });
});

describe('hashLayoutOptions — SHA-256 hash 穩定', () => {
  it('相同 opts 回相同 hash（不同 key 順序）', async () => {
    const h1 = await hashLayoutOptions({ a: 1, b: 2 } as never);
    const h2 = await hashLayoutOptions({ b: 2, a: 1 } as never);
    expect(h1).toBe(h2);
    expect(h1).toMatch(/^[0-9a-f]{64}$/);
  });

  it('不同 opts 回不同 hash', async () => {
    const h1 = await hashLayoutOptions({ a: 1 } as never);
    const h2 = await hashLayoutOptions({ a: 2 } as never);
    expect(h1).not.toBe(h2);
  });

  it('空 opts 也能 hash', async () => {
    const h = await hashLayoutOptions({} as never);
    expect(h).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe('composeLayoutKey — 連接 docx + opts hash', () => {
  it('用 | 分隔（兩段都是 hex 不含 |，無歧義）', () => {
    expect(composeLayoutKey('abc', 'def')).toBe('abc|def');
  });

  it('不同 docx 同 opts → 不同 key', () => {
    expect(composeLayoutKey('aaa', 'X')).not.toBe(composeLayoutKey('bbb', 'X'));
  });

  it('同 docx 不同 opts → 不同 key', () => {
    expect(composeLayoutKey('X', 'aaa')).not.toBe(composeLayoutKey('X', 'bbb'));
  });
});
