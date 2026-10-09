/**
 * Sprint 51 — AstCache 單元測試
 *
 * 範圍：
 *   - computeDocxHash 對相同 bytes 回相同 hash（決定性）；不同 bytes 回不同 hash
 *   - AstCache LRU：put/get、超過 maxEntries 淘汰最舊、touch 變新
 *   - stats：hits/misses/size 計數正確
 *
 * 不測 IndexedDB 層 — node 環境無瀏覽器 IDB，IDB 層待 Sprint 52 加 fake-indexeddb。
 */

import { describe, expect, it } from 'vitest';
import { AstCache, computeDocxHash } from '../../static/src/core/cache/ast_cache';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';

/** 構造一個最小 DocumentNode（測試用，欄位齊全但內容空）。 */
function makeFakeAst(tag: string): DocumentNode {
  return {
    type: 'document',
    sections: [],
    headers: new Map([['h1', { type: 'header', paragraphs: [], tables: [] } as never]]),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering: new Map(),
    media: new Map([['rId1', `data:text/plain;base64,${tag}`]]),
    docProps: { title: tag },
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  };
}

describe('computeDocxHash', () => {
  it('相同 bytes → 相同 hash（決定性）', async () => {
    const bytes = new Uint8Array([1, 2, 3, 4, 5]);
    const h1 = await computeDocxHash(bytes);
    const h2 = await computeDocxHash(bytes);
    expect(h1).toBe(h2);
    expect(h1).toMatch(/^[0-9a-f]{64}$/);
  });

  it('不同 bytes → 不同 hash', async () => {
    const h1 = await computeDocxHash(new Uint8Array([1, 2, 3]));
    const h2 = await computeDocxHash(new Uint8Array([1, 2, 4]));
    expect(h1).not.toBe(h2);
  });

  it('接受 ArrayBuffer 與 Uint8Array 兩者（等價 bytes 應同 hash）', async () => {
    const u8 = new Uint8Array([42, 43, 44]);
    const ab = u8.buffer;
    const h1 = await computeDocxHash(u8);
    const h2 = await computeDocxHash(ab);
    expect(h1).toBe(h2);
  });
});

describe('AstCache — 基本 put/get', () => {
  it('miss 回 undefined、hit 回原物件', () => {
    const c = new AstCache();
    const ast = makeFakeAst('A');
    expect(c.get('hashA')).toBeUndefined();
    c.put('hashA', ast);
    expect(c.get('hashA')).toBe(ast);
  });

  it('has 不影響 hits/misses 計數', () => {
    const c = new AstCache();
    c.put('h', makeFakeAst('x'));
    c.has('h');
    c.has('nope');
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 1 });
  });

  it('stats 正確計數 hits 與 misses', () => {
    const c = new AstCache();
    c.put('h', makeFakeAst('x'));
    c.get('h'); // hit
    c.get('h'); // hit
    c.get('nope'); // miss
    expect(c.stats()).toEqual({ hits: 2, misses: 1, size: 1 });
  });

  it('clear() 同時重置 entries 與計數', () => {
    const c = new AstCache();
    c.put('h', makeFakeAst('x'));
    c.get('h');
    c.get('nope');
    c.clear();
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 0 });
    expect(c.get('h')).toBeUndefined();
  });
});

describe('AstCache — LRU 淘汰', () => {
  it('超過 maxEntries 時淘汰最舊 entry', () => {
    const c = new AstCache({ maxEntries: 3 });
    c.put('A', makeFakeAst('A'));
    c.put('B', makeFakeAst('B'));
    c.put('C', makeFakeAst('C'));
    c.put('D', makeFakeAst('D')); // A 被淘汰
    expect(c.has('A')).toBe(false);
    expect(c.has('B')).toBe(true);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
    expect(c.stats().size).toBe(3);
  });

  it('get() 命中後 entry 移到最新端，後續插入不會淘汰它', () => {
    const c = new AstCache({ maxEntries: 3 });
    c.put('A', makeFakeAst('A'));
    c.put('B', makeFakeAst('B'));
    c.put('C', makeFakeAst('C'));
    // touch A 把它推到最新端
    expect(c.get('A')).toBeDefined();
    // 插 D：應淘汰 B（現在最舊）而非 A
    c.put('D', makeFakeAst('D'));
    expect(c.has('A')).toBe(true);
    expect(c.has('B')).toBe(false);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
  });

  it('既存 entry 重複 put 不增加 size、不觸發淘汰', () => {
    const c = new AstCache({ maxEntries: 2 });
    c.put('A', makeFakeAst('A'));
    c.put('B', makeFakeAst('B'));
    c.put('A', makeFakeAst('A2')); // 覆寫
    expect(c.stats().size).toBe(2);
    expect(c.has('B')).toBe(true);
    expect(c.get('A')?.docProps.title).toBe('A2');
  });

  it('maxEntries <= 0 throw', () => {
    expect(() => new AstCache({ maxEntries: 0 })).toThrow();
    expect(() => new AstCache({ maxEntries: -1 })).toThrow();
    expect(() => new AstCache({ maxEntries: 1.5 })).toThrow();
  });
});
