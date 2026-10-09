/**
 * Sprint 56 — ImageBitmapIdbCache 單元測試（fake-indexeddb 模擬 IDB）
 *
 * 範圍：
 *   - L1 hit（in-memory ImageBitmap sentinel）
 *   - L2 hit（IDB Blob）：清 L1 → 第二 instance 同 dbName 應 promote
 *   - 跨 instance 持久化
 *   - L2 LRU 淘汰
 *   - dataUrl → Blob conversion 行為（fetch dataURL）
 *   - createImageBitmap 不存在時 graceful degrade（node 環境）
 *
 * 設計取捨：
 *   - node 環境沒有 createImageBitmap → 用 `globalThis.createImageBitmap = mock` 注入
 *   - mock 回傳 sentinel object（任何 truthy 值，模擬 ImageBitmap）
 *   - 真實 ImageBitmap 行為由 puppeteer perf 驗證
 *
 * fetch(dataURL) 在 node 18+ 內建支援 dataURL scheme（測試環境 OK）
 */

import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ImageBitmapIdbCache, hashDataUrl } from '../../static/src/core/cache/image_bitmap_idb_cache';

let dbCounter = 0;
function freshDbName(): string {
  dbCounter++;
  return `dobtor-bitmap-cache-test-${dbCounter}-${Date.now()}`;
}

// 1×1 PNG dataURL（用 fetch(dataURL) 能取得 Blob 的合法形式）
// 多個變體確保 hash 不同（測 LRU 淘汰用）
const TINY_PNG_DATAURL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

const TINY_PNG_DATAURL_2 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg==';

const TINY_PNG_DATAURL_3 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==';

const TINY_PNG_DATAURL_4 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/PjxfwAJAANCfNQGYwAAAABJRU5ErkJggg==';

async function flush() {
  await new Promise((r) => setTimeout(r, 0));
}

// 注入 mock createImageBitmap：node 環境沒有此 API，必須 stub
function installMockCreateImageBitmap(): { sentinel: object; restore: () => void } {
  const sentinel = { __mockImageBitmap: true };
  const original = (globalThis as any).createImageBitmap;
  (globalThis as any).createImageBitmap = vi.fn(async () => sentinel);
  return {
    sentinel,
    restore: () => {
      if (original === undefined) {
        delete (globalThis as any).createImageBitmap;
      } else {
        (globalThis as any).createImageBitmap = original;
      }
    },
  };
}

describe('ImageBitmapIdbCache — L1 行為', () => {
  let restore: () => void;
  let sentinel: object;
  beforeEach(() => {
    const m = installMockCreateImageBitmap();
    restore = m.restore;
    sentinel = m.sentinel;
  });
  afterEach(() => restore());

  it('put 後 L1 立即可 get（hit L1，不走 IDB）', async () => {
    const c = new ImageBitmapIdbCache({ dbName: freshDbName() });
    await c.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    const got = await c.get(TINY_PNG_DATAURL);
    expect(got).toBe(sentinel);
    expect(c.stats()).toMatchObject({ l1Hits: 1, l2Hits: 0, misses: 0 });
  });

  it('未 put 的 dataUrl → miss', async () => {
    const c = new ImageBitmapIdbCache({ dbName: freshDbName() });
    const got = await c.get(TINY_PNG_DATAURL);
    expect(got).toBeUndefined();
    expect(c.stats()).toMatchObject({ l1Hits: 0, l2Hits: 0, misses: 1 });
  });

  it('L1 LRU 淘汰：超過 maxMemoryEntries 時 evict 最舊', async () => {
    const c = new ImageBitmapIdbCache({
      dbName: freshDbName(),
      maxMemoryEntries: 2,
    });
    await c.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    await c.put(TINY_PNG_DATAURL_2, sentinel as ImageBitmap);
    await c.put(TINY_PNG_DATAURL_3, sentinel as ImageBitmap); // 第一個被 evict L1
    expect(c.stats().l1Size).toBe(2);
  });

  it('L1 LRU touch：get 後 entry 推到最新端', async () => {
    const c = new ImageBitmapIdbCache({
      dbName: freshDbName(),
      maxMemoryEntries: 2,
    });
    await c.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    await c.put(TINY_PNG_DATAURL_2, sentinel as ImageBitmap);
    await c.get(TINY_PNG_DATAURL); // touch
    await c.put(TINY_PNG_DATAURL_3, sentinel as ImageBitmap); // 應淘汰 TINY_PNG_DATAURL_2
    expect(c.stats().l1Size).toBe(2);
    const a = await c.get(TINY_PNG_DATAURL);
    expect(a).toBe(sentinel);
  });
});

describe('ImageBitmapIdbCache — L2 持久化', () => {
  let restore: () => void;
  let sentinel: object;
  beforeEach(() => {
    const m = installMockCreateImageBitmap();
    restore = m.restore;
    sentinel = m.sentinel;
  });
  afterEach(() => restore());

  it('清空 L1 後 → 同 dbName 新 instance 應 L2 hit 並 promote 回 L1', async () => {
    const dbName = freshDbName();
    const c1 = new ImageBitmapIdbCache({ dbName });
    await c1.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    await flush();

    // 新 instance 模擬 page reload（L1 empty）
    const c2 = new ImageBitmapIdbCache({ dbName });
    const got = await c2.get(TINY_PNG_DATAURL);
    expect(got).toBeDefined();
    expect(c2.stats()).toMatchObject({ l1Hits: 0, l2Hits: 1, misses: 0 });

    // 第二次 get 同 dataUrl → 應 L1 hit
    await c2.get(TINY_PNG_DATAURL);
    expect(c2.stats()).toMatchObject({ l1Hits: 1, l2Hits: 1, misses: 0 });
  });

  it('clear() 同時清 L1 與 L2', async () => {
    const dbName = freshDbName();
    const c = new ImageBitmapIdbCache({ dbName });
    await c.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    await flush();
    await c.clear();

    const c2 = new ImageBitmapIdbCache({ dbName });
    expect(await c2.get(TINY_PNG_DATAURL)).toBeUndefined();
  });

  it('L2 LRU 淘汰：超過 maxIdbEntries 時 evict 最舊', async () => {
    const dbName = freshDbName();
    const c = new ImageBitmapIdbCache({
      dbName,
      maxMemoryEntries: 1,
      maxIdbEntries: 2,
    });
    await c.put(TINY_PNG_DATAURL, sentinel as ImageBitmap);
    await flush();
    await new Promise((r) => setTimeout(r, 2));
    await c.put(TINY_PNG_DATAURL_2, sentinel as ImageBitmap);
    await flush();
    await new Promise((r) => setTimeout(r, 2));
    await c.put(TINY_PNG_DATAURL_3, sentinel as ImageBitmap); // 觸發 evict（第一個最舊）
    await flush();

    // 用新 instance 確認 L2 狀態（避開 L1 promote）
    const c2 = new ImageBitmapIdbCache({
      dbName,
      maxMemoryEntries: 1,
      maxIdbEntries: 2,
    });
    expect(await c2.get(TINY_PNG_DATAURL)).toBeUndefined();
    expect(await c2.get(TINY_PNG_DATAURL_2)).toBeDefined();
    expect(await c2.get(TINY_PNG_DATAURL_3)).toBeDefined();
  });
});

describe('ImageBitmapIdbCache — 設定驗證', () => {
  it('maxMemoryEntries <= 0 throw', () => {
    expect(() => new ImageBitmapIdbCache({ maxMemoryEntries: 0 })).toThrow();
    expect(() => new ImageBitmapIdbCache({ maxMemoryEntries: -1 })).toThrow();
    expect(() => new ImageBitmapIdbCache({ maxMemoryEntries: 1.5 })).toThrow();
  });

  it('maxIdbEntries <= 0 throw', () => {
    expect(() => new ImageBitmapIdbCache({ maxIdbEntries: 0 })).toThrow();
    expect(() => new ImageBitmapIdbCache({ maxIdbEntries: -1 })).toThrow();
    expect(() => new ImageBitmapIdbCache({ maxIdbEntries: 1.5 })).toThrow();
  });
});

describe('ImageBitmapIdbCache — createImageBitmap 不可用時 graceful degrade', () => {
  it('L2 hit 但 createImageBitmap 未注入 → return undefined（caller 應降級為 fresh decode）', async () => {
    // 先 put（需 createImageBitmap）
    const m1 = installMockCreateImageBitmap();
    const dbName = freshDbName();
    const c1 = new ImageBitmapIdbCache({ dbName });
    await c1.put(TINY_PNG_DATAURL, m1.sentinel as ImageBitmap);
    await flush();
    m1.restore();

    // 模擬另一 page 沒有 createImageBitmap
    delete (globalThis as any).createImageBitmap;
    const c2 = new ImageBitmapIdbCache({ dbName });
    const got = await c2.get(TINY_PNG_DATAURL);
    expect(got).toBeUndefined();
    // L2 hit 仍計入 stats（IDB 確實找到了，只是無法 decode）
    expect(c2.stats().l2Hits).toBe(1);
  });
});

describe('ImageBitmapIdbCache — hash key 內容定址', () => {
  it('hashDataUrl 對同字串穩定（內容定址）', async () => {
    const h1 = await hashDataUrl(TINY_PNG_DATAURL);
    const h2 = await hashDataUrl(TINY_PNG_DATAURL);
    expect(h1).toBe(h2);
    expect(h1).toMatch(/^[0-9a-f]{64}$/);
  });

  it('不同 dataUrl 產生不同 hash', async () => {
    const h1 = await hashDataUrl(TINY_PNG_DATAURL);
    const h2 = await hashDataUrl(TINY_PNG_DATAURL_2);
    expect(h1).not.toBe(h2);
  });
});
