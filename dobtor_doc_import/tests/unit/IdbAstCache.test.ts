/**
 * Sprint 52 — IdbAstCache 單元測試（使用 fake-indexeddb 模擬 IDB）
 *
 * 範圍：
 *   - L1 hit（in-memory）
 *   - L2 hit（IDB）：第一次 get/put 走 L1 + L2；clear L1 後再 get 應從 L2 撈回並 promote 回 L1
 *   - 跨 instance 持久化：建 cache A → put → 銷毀 A → 建 cache B（同 dbName）→ get 應命中 L2
 *   - L2 LRU 淘汰：maxIdbEntries 滿時，put 應淘汰最舊 entry
 *   - IDB unavailable fallback：indexedDB undefined 時 L1 仍可用
 */

import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AstCache, IdbAstCache } from '../../static/src/core/cache/ast_cache';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';

function makeFakeAst(tag: string): DocumentNode {
  return {
    type: 'document',
    sections: [],
    headers: new Map(),
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

/** 等所有 microtasks 跑完，確保 IDB 寫入 commit。 */
async function flush() {
  await new Promise((r) => setTimeout(r, 0));
}

let dbCounter = 0;
function freshDbName(): string {
  dbCounter++;
  return `dobtor-ast-cache-test-${dbCounter}-${Date.now()}`;
}

describe('IdbAstCache — L1 + L2', () => {
  let dbName: string;
  beforeEach(() => {
    dbName = freshDbName();
  });

  it('put 後 L1 立即可 get（hit L1）', async () => {
    const c = new IdbAstCache({ dbName });
    const ast = makeFakeAst('A');
    await c.put('hashA', ast);
    const got = await c.get('hashA');
    expect(got).toBeDefined();
    expect(got?.docProps.title).toBe('A');
    expect(c.stats()).toMatchObject({ l1Hits: 1, l2Hits: 0, misses: 0 });
  });

  it('清空 L1 後再 get → 從 L2 撈回並 promote 回 L1', async () => {
    const c = new IdbAstCache({ dbName });
    const ast = makeFakeAst('B');
    await c.put('hashB', ast);
    await flush();

    // 直接 reach in 清 L1（不影響 L2）—— 用內部 path：
    // 簡單法：建第二個 cache 實例同 dbName，模擬 reload 後 L1 empty
    const c2 = new IdbAstCache({ dbName });
    const got = await c2.get('hashB');
    expect(got).toBeDefined();
    expect(got?.docProps.title).toBe('B');
    expect(c2.stats()).toMatchObject({ l1Hits: 0, l2Hits: 1, misses: 0 });

    // 第二次 get 同 hash → 應 L1 hit（剛剛被 promote 上去）
    const got2 = await c2.get('hashB');
    expect(got2).toBeDefined();
    expect(c2.stats()).toMatchObject({ l1Hits: 1, l2Hits: 1, misses: 0 });
  });

  it('未 put 的 hash → miss（L1 + L2 都 miss）', async () => {
    const c = new IdbAstCache({ dbName });
    const got = await c.get('doesNotExist');
    expect(got).toBeUndefined();
    expect(c.stats()).toMatchObject({ l1Hits: 0, l2Hits: 0, misses: 1 });
  });

  it('跨 instance 持久化（模擬 reload）', async () => {
    const c1 = new IdbAstCache({ dbName });
    await c1.put('hashX', makeFakeAst('X'));
    await flush();

    // 新 instance、同 dbName → 應從 L2 命中
    const c2 = new IdbAstCache({ dbName });
    const got = await c2.get('hashX');
    expect(got).toBeDefined();
    expect(got?.docProps.title).toBe('X');
  });

  it('clear() 同時清 L1 與 L2', async () => {
    const c = new IdbAstCache({ dbName });
    await c.put('h1', makeFakeAst('1'));
    await c.put('h2', makeFakeAst('2'));
    await flush();
    await c.clear();

    // 新 instance 確認 L2 也清乾淨
    const c2 = new IdbAstCache({ dbName });
    expect(await c2.get('h1')).toBeUndefined();
    expect(await c2.get('h2')).toBeUndefined();
  });
});

describe('IdbAstCache — L2 LRU 淘汰', () => {
  it('maxIdbEntries 超過時 put 應淘汰最舊 entry', async () => {
    const dbName = freshDbName();
    const c = new IdbAstCache({ dbName, maxIdbEntries: 3, maxMemoryEntries: 1 });
    await c.put('A', makeFakeAst('A'));
    await flush();
    await new Promise((r) => setTimeout(r, 2));
    await c.put('B', makeFakeAst('B'));
    await flush();
    await new Promise((r) => setTimeout(r, 2));
    await c.put('C', makeFakeAst('C'));
    await flush();
    await new Promise((r) => setTimeout(r, 2));
    await c.put('D', makeFakeAst('D')); // 觸發 evict（A 最舊）
    await flush();

    // 用新 instance 避開 L1 干擾，確認 L2 狀態
    const c2 = new IdbAstCache({ dbName, maxIdbEntries: 3, maxMemoryEntries: 1 });
    expect(await c2.get('A')).toBeUndefined(); // 被 evict
    expect(await c2.get('B')).toBeDefined();
    expect(await c2.get('C')).toBeDefined();
    expect(await c2.get('D')).toBeDefined();
  });
});

describe('IdbAstCache — 設定驗證', () => {
  it('maxIdbEntries <= 0 throw', () => {
    expect(() => new IdbAstCache({ maxIdbEntries: 0 })).toThrow();
    expect(() => new IdbAstCache({ maxIdbEntries: -1 })).toThrow();
    expect(() => new IdbAstCache({ maxIdbEntries: 1.5 })).toThrow();
  });
});

describe('PipelineAstCache 介面相容', () => {
  it('AstCache（sync）符合 PipelineAstCache shape', async () => {
    const c: { get: (k: string) => unknown; put: (k: string, v: DocumentNode) => unknown } = new AstCache();
    c.put('h', makeFakeAst('S'));
    const v = await c.get('h'); // await sync 值 = no-op
    expect(v).toBeDefined();
  });

  it('IdbAstCache（async）符合同 shape', async () => {
    const dbName = freshDbName();
    const c: { get: (k: string) => unknown; put: (k: string, v: DocumentNode) => unknown } = new IdbAstCache({
      dbName,
    });
    await c.put('h', makeFakeAst('I'));
    const v = await c.get('h');
    expect(v).toBeDefined();
  });
});
