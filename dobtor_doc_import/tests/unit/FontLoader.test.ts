/**
 * Sprint 64b — FontLoader 單元測試（fake-indexeddb + fetch mock）
 *
 * 驗證：
 *   1. IDB miss → fetch → 存 IDB → 回 bytes
 *   2. IDB hit → 跳過 fetch
 *   3. fetch 404 / 失敗 → silent fallback、adapter 未註冊該 family
 *   4. IDB unavailable → 走 fetch、不存 cache
 *   5. clearFontCache 重置
 *   6. 多 family 並行載入
 */

import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { loadFontsAndBuildAdapter, clearFontCache } from '../../static/src/core/font_loader';
import { FontMetricsAdapter } from '../../static/src/core/layout/FontMetricsAdapter';
import type { FontTable, FontEntry } from '../../static/src/core/ooxml/ast/types';

// 真實 TTF bytes（從系統字型載入；測試只用 1-2 個 family、不依賴更多檔案）
const LIBERATION_SERIF = '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf';
const DROID_SANS = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf';

function loadRealFont(path: string): ArrayBuffer | null {
  if (!existsSync(path)) return null;
  const buf = readFileSync(path);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const LIBERATION_BYTES = loadRealFont(LIBERATION_SERIF);

// fetch mock
let fetchCalls: Array<{ url: string; response: 'ok' | '404' | 'error' }> = [];

function setupFetchMock(behaviorMap: Record<string, ArrayBuffer | 'error' | '404'>) {
  globalThis.fetch = vi.fn(async (url: string | URL | Request) => {
    const urlStr = typeof url === 'string' ? url : url.toString();
    // 路徑最後一段（URL-decoded）為 family
    const family = decodeURIComponent(urlStr.split('/').pop() || '');
    const behavior = behaviorMap[family];
    if (behavior === 'error') {
      fetchCalls.push({ url: urlStr, response: 'error' });
      throw new Error('mock network error');
    }
    if (behavior === '404' || behavior === undefined) {
      fetchCalls.push({ url: urlStr, response: '404' });
      return new Response(null, { status: 404 });
    }
    fetchCalls.push({ url: urlStr, response: 'ok' });
    return new Response(behavior, { status: 200, headers: { 'Content-Type': 'font/ttf' } });
  }) as unknown as typeof fetch;
}

beforeEach(async () => {
  fetchCalls = [];
  await clearFontCache();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Sprint 64b — FontLoader', () => {
  it.skipIf(!LIBERATION_BYTES)('IDB miss → fetch → 註冊 adapter → bytes 存 IDB', async () => {
    setupFetchMock({ 'Times New Roman': LIBERATION_BYTES! });
    const adapter = await loadFontsAndBuildAdapter(['Times New Roman']);
    expect(adapter.hasFont('Times New Roman')).toBe(true);
    // fetch 被呼叫一次
    expect(fetchCalls.length).toBe(1);
    expect(fetchCalls[0].response).toBe('ok');
  });

  it.skipIf(!LIBERATION_BYTES)('IDB hit → 跳過 fetch', async () => {
    setupFetchMock({ 'Times New Roman': LIBERATION_BYTES! });
    // 第一次 fetch + 存 IDB
    await loadFontsAndBuildAdapter(['Times New Roman']);
    fetchCalls = [];
    // 第二次 instance → IDB hit、不該 fetch
    const adapter2 = await loadFontsAndBuildAdapter(['Times New Roman']);
    expect(adapter2.hasFont('Times New Roman')).toBe(true);
    expect(fetchCalls.length).toBe(0); // 沒打 network
  });

  it('fetch 404 → silent fallback、adapter 未註冊', async () => {
    setupFetchMock({}); // 任何 family 都 404
    const adapter = await loadFontsAndBuildAdapter(['不存在的字型']);
    expect(adapter.hasFont('不存在的字型')).toBe(false);
    expect(adapter.listFonts().length).toBe(0);
  });

  it('fetch error → silent fallback', async () => {
    setupFetchMock({ '出錯字型': 'error' });
    const adapter = await loadFontsAndBuildAdapter(['出錯字型']);
    expect(adapter.hasFont('出錯字型')).toBe(false);
  });

  it.skipIf(!LIBERATION_BYTES)('多 family 並行載入', async () => {
    setupFetchMock({
      'Times New Roman': LIBERATION_BYTES!,
      '不存在': '404',
      '出錯': 'error',
    });
    const adapter = await loadFontsAndBuildAdapter(['Times New Roman', '不存在', '出錯']);
    expect(adapter.hasFont('Times New Roman')).toBe(true);
    expect(adapter.hasFont('不存在')).toBe(false);
    expect(adapter.hasFont('出錯')).toBe(false);
    expect(fetchCalls.length).toBe(3);
  });

  it.skipIf(!LIBERATION_BYTES)('clearFontCache 後再 load 重新 fetch', async () => {
    setupFetchMock({ 'Times New Roman': LIBERATION_BYTES! });
    await loadFontsAndBuildAdapter(['Times New Roman']);
    expect(fetchCalls.length).toBe(1);
    await clearFontCache();
    fetchCalls = [];
    await loadFontsAndBuildAdapter(['Times New Roman']);
    expect(fetchCalls.length).toBe(1); // 又 fetch 了一次
  });

  it.skipIf(!LIBERATION_BYTES)('caller 注入 adapter（不自動建）', async () => {
    setupFetchMock({ 'Times New Roman': LIBERATION_BYTES! });
    const customAdapter = new FontMetricsAdapter();
    const returned = await loadFontsAndBuildAdapter(['Times New Roman'], {
      adapter: customAdapter,
    });
    expect(returned).toBe(customAdapter); // 同一個 instance
    expect(customAdapter.hasFont('Times New Roman')).toBe(true);
  });

  it.skipIf(!LIBERATION_BYTES)('endpoint URL 含 CJK family 正確 URL-encode', async () => {
    setupFetchMock({ '標楷體': LIBERATION_BYTES! }); // 用同一 TTF 模擬
    await loadFontsAndBuildAdapter(['標楷體']);
    expect(fetchCalls.length).toBe(1);
    // URL encoding 後路徑應該是 %E6%A8%99%E6%A5%B7%E9%AB%94
    expect(fetchCalls[0].url).toContain('%E6%A8%99%E6%A5%B7%E9%AB%94');
  });

  it.skipIf(!LIBERATION_BYTES)('自訂 endpoint', async () => {
    setupFetchMock({ 'Times New Roman': LIBERATION_BYTES! });
    await loadFontsAndBuildAdapter(['Times New Roman'], {
      endpoint: 'https://cdn.example.com/fonts',
    });
    expect(fetchCalls[0].url).toContain('https://cdn.example.com/fonts/Times%20New%20Roman');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Sprint 157 — fontTable.altName fallback chain（規畫書 Phase 2 §2.2 wire-up）
// 接續 Sprint 147 FontTableParser capture、OOXML §17.8 altName 語意
// ─────────────────────────────────────────────────────────────────────────────

function mkFontTable(entries: Array<{ name: string; altName?: string }>): FontTable {
  const table: FontTable = new Map();
  for (const e of entries) {
    const entry: FontEntry = { name: e.name };
    if (e.altName !== undefined) entry.altName = e.altName;
    table.set(e.name, entry);
  }
  return table;
}

describe('Sprint 157 — fontTable.altName fallback', () => {
  it.skipIf(!LIBERATION_BYTES)('主 family 404 + altName 200 → adapter 用主 family 名註冊', async () => {
    setupFetchMock({
      '微軟正黑體': '404',
      'Microsoft JhengHei': LIBERATION_BYTES!, // altName 對應的真實 bytes
    });
    const fontTable = mkFontTable([{ name: '微軟正黑體', altName: 'Microsoft JhengHei' }]);
    const adapter = await loadFontsAndBuildAdapter(['微軟正黑體'], { fontTable });

    expect(adapter.hasFont('微軟正黑體')).toBe(true); // 用主 family 名註冊、便於 caller 查
    expect(adapter.hasFont('Microsoft JhengHei')).toBe(false); // altName 不單獨註冊
    expect(fetchCalls.length).toBe(2); // 主 family 404 + altName 200
    expect(fetchCalls[0].response).toBe('404');
    expect(fetchCalls[1].response).toBe('ok');
  });

  it.skipIf(!LIBERATION_BYTES)('主 family error + altName 200 → 仍 fallback 成功', async () => {
    setupFetchMock({
      'BrokenFont': 'error',
      'WorkingAlt': LIBERATION_BYTES!,
    });
    const fontTable = mkFontTable([{ name: 'BrokenFont', altName: 'WorkingAlt' }]);
    const adapter = await loadFontsAndBuildAdapter(['BrokenFont'], { fontTable });

    expect(adapter.hasFont('BrokenFont')).toBe(true);
    expect(fetchCalls.length).toBe(2);
  });

  it.skipIf(!LIBERATION_BYTES)('主 family 200 → 不查 altName（fast path）', async () => {
    setupFetchMock({
      'Times New Roman': LIBERATION_BYTES!,
      'Times': LIBERATION_BYTES!,
    });
    const fontTable = mkFontTable([{ name: 'Times New Roman', altName: 'Times' }]);
    await loadFontsAndBuildAdapter(['Times New Roman'], { fontTable });

    expect(fetchCalls.length).toBe(1); // 主成功就不查 altName
    expect(fetchCalls[0].url).toContain('Times%20New%20Roman');
  });

  it('主 + altName 都 404 → silent fallback、adapter 未註冊', async () => {
    setupFetchMock({}); // 都 404
    const fontTable = mkFontTable([{ name: '無此字型', altName: '也無此' }]);
    const adapter = await loadFontsAndBuildAdapter(['無此字型'], { fontTable });

    expect(adapter.hasFont('無此字型')).toBe(false);
    expect(fetchCalls.length).toBe(2); // 兩次都打、都 404
  });

  it('fontTable 沒這個 family → 不 retry altName（與 Sprint 64b 行為一致）', async () => {
    setupFetchMock({});
    // fontTable 完全空、或這個 family 不在 fontTable
    const fontTable = mkFontTable([{ name: '別的字型', altName: 'AltOfOther' }]);
    const adapter = await loadFontsAndBuildAdapter(['這個字型'], { fontTable });

    expect(adapter.hasFont('這個字型')).toBe(false);
    expect(fetchCalls.length).toBe(1); // 只試主 family、無 altName retry
  });

  it('fontTable 有 family 但無 altName → 不 retry', async () => {
    setupFetchMock({});
    const fontTable = mkFontTable([{ name: '主字型' }]); // 無 altName
    const adapter = await loadFontsAndBuildAdapter(['主字型'], { fontTable });

    expect(adapter.hasFont('主字型')).toBe(false);
    expect(fetchCalls.length).toBe(1); // 無 altName 不 retry
  });

  it('altName 等於主 family → 不 retry（防無限 / 防 spec 病態 docx）', async () => {
    setupFetchMock({});
    const fontTable = mkFontTable([{ name: 'SelfRef', altName: 'SelfRef' }]);
    const adapter = await loadFontsAndBuildAdapter(['SelfRef'], { fontTable });

    expect(adapter.hasFont('SelfRef')).toBe(false);
    expect(fetchCalls.length).toBe(1); // 主 fetch 一次、不因 altName=family 再 fetch
  });

  it('不傳 fontTable → 與 Sprint 64b 行為完全一致（backward compat）', async () => {
    setupFetchMock({});
    const adapter = await loadFontsAndBuildAdapter(['任何字型']);

    expect(adapter.hasFont('任何字型')).toBe(false);
    expect(fetchCalls.length).toBe(1); // 純 Sprint 64b path、無 altName retry
  });

  it.skipIf(!LIBERATION_BYTES)('多 family 並行 + 部分 altName fallback 成功、部分失敗', async () => {
    setupFetchMock({
      '主A': LIBERATION_BYTES!, // 主 200
      '主B': '404',
      '替B': LIBERATION_BYTES!, // altName 200
      '主C': '404',
      '替C': '404', // 兩個都 404
    });
    const fontTable = mkFontTable([
      { name: '主A', altName: '替A' }, // 不該被 retry（主成功）
      { name: '主B', altName: '替B' },
      { name: '主C', altName: '替C' },
    ]);
    const adapter = await loadFontsAndBuildAdapter(['主A', '主B', '主C'], { fontTable });

    expect(adapter.hasFont('主A')).toBe(true); // 主成功
    expect(adapter.hasFont('主B')).toBe(true); // altName fallback 成功
    expect(adapter.hasFont('主C')).toBe(false); // 兩個都 404
    // fetch:主A(1) + 主B(2、404+替B) + 主C(2、404+替C) = 5
    expect(fetchCalls.length).toBe(5);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Sprint 166 — CJK fallback chain（規畫書 Phase 2 §2.2 wire-up）
// 主 + altName 都失敗、且 fontTable.charset 判定為 CJK → 試通用 CJK fallback chain
// ─────────────────────────────────────────────────────────────────────────────

function mkCjkFontTable(
  entries: Array<{ name: string; altName?: string; charset?: string }>,
): FontTable {
  const table: FontTable = new Map();
  for (const e of entries) {
    const entry: FontEntry = { name: e.name };
    if (e.altName !== undefined) entry.altName = e.altName;
    if (e.charset !== undefined) entry.charset = e.charset;
    table.set(e.name, entry);
  }
  return table;
}

describe('Sprint 166 — CJK fallback chain', () => {
  it.skipIf(!LIBERATION_BYTES)(
    '主 + altName 都 404、charset=88（繁中）→ CJK chain 第一個可用者勝出、用主 family 名註冊',
    async () => {
      setupFetchMock({
        標楷體: '404',
        'DFKai-SB': '404',
        思源黑體: LIBERATION_BYTES!, // chain 第一個
      });
      const fontTable = mkCjkFontTable([
        { name: '標楷體', altName: 'DFKai-SB', charset: '88' },
      ]);
      const adapter = await loadFontsAndBuildAdapter(['標楷體'], { fontTable });

      expect(adapter.hasFont('標楷體')).toBe(true); // 用主 family 名註冊
      expect(adapter.hasFont('思源黑體')).toBe(false); // fallback 不單獨註冊
      // fetch:主(404) + altName(404) + 思源黑體(200) = 3
      expect(fetchCalls.length).toBe(3);
    },
  );

  it.skipIf(!LIBERATION_BYTES)(
    '主 404、無 altName、charset=86（簡中）→ CJK chain 試',
    async () => {
      setupFetchMock({ 宋體: '404', 思源黑體: LIBERATION_BYTES! });
      const fontTable = mkCjkFontTable([{ name: '宋體', charset: '86' }]);
      const adapter = await loadFontsAndBuildAdapter(['宋體'], { fontTable });

      expect(adapter.hasFont('宋體')).toBe(true);
      // fetch:主(404) + 思源黑體(200) = 2（無 altName 不 retry）
      expect(fetchCalls.length).toBe(2);
    },
  );

  it.skipIf(!LIBERATION_BYTES)(
    '主 404、charset=80（日文 ShiftJIS）→ CJK chain 試（驗 charset 集合涵蓋日文）',
    async () => {
      setupFetchMock({ メイリオ: '404', 思源黑體: LIBERATION_BYTES! });
      const fontTable = mkCjkFontTable([{ name: 'メイリオ', charset: '80' }]);
      const adapter = await loadFontsAndBuildAdapter(['メイリオ'], { fontTable });

      expect(adapter.hasFont('メイリオ')).toBe(true);
      expect(fetchCalls.length).toBe(2);
    },
  );

  it('charset=00（ANSI 拉丁）→ CJK chain 不試、主 404 即 silent fallback', async () => {
    setupFetchMock({}); // 全 404
    const fontTable = mkCjkFontTable([{ name: 'Arial', charset: '00' }]);
    const adapter = await loadFontsAndBuildAdapter(['Arial'], { fontTable });

    expect(adapter.hasFont('Arial')).toBe(false);
    expect(fetchCalls.length).toBe(1); // 只試主 family、不套 CJK chain
  });

  it('fontTable 有 family 但無 charset → CJK chain 不試', async () => {
    setupFetchMock({});
    const fontTable = mkCjkFontTable([{ name: '某字型' }]); // 無 charset
    const adapter = await loadFontsAndBuildAdapter(['某字型'], { fontTable });

    expect(adapter.hasFont('某字型')).toBe(false);
    expect(fetchCalls.length).toBe(1);
  });

  it('family 不在 fontTable → CJK chain 不試（與 Sprint 64b/157 行為一致）', async () => {
    setupFetchMock({});
    const fontTable = mkCjkFontTable([{ name: '別的字型', charset: '88' }]);
    const adapter = await loadFontsAndBuildAdapter(['這個字型'], { fontTable });

    expect(adapter.hasFont('這個字型')).toBe(false);
    expect(fetchCalls.length).toBe(1);
  });

  it('charset=88 但 CJK chain 全 404 → silent fallback、adapter 未註冊', async () => {
    setupFetchMock({}); // 主 + chain 全 404
    const fontTable = mkCjkFontTable([{ name: '怪字型', charset: '88' }]);
    const adapter = await loadFontsAndBuildAdapter(['怪字型'], { fontTable });

    expect(adapter.hasFont('怪字型')).toBe(false);
    // fetch:主(1) + 思源黑體 + 微軟正黑體 + 新細明體 = 4
    expect(fetchCalls.length).toBe(4);
  });

  it.skipIf(!LIBERATION_BYTES)(
    'chain 成員等於主 family / altName → 跳過、不重複 fetch',
    async () => {
      setupFetchMock({
        思源黑體: '404', // 主 family 本身就是 chain[0]
        微軟正黑體: '404', // altName 本身就是 chain[1]
        新細明體: LIBERATION_BYTES!, // 只有 chain[2] 該被試
      });
      const fontTable = mkCjkFontTable([
        { name: '思源黑體', altName: '微軟正黑體', charset: '88' },
      ]);
      const adapter = await loadFontsAndBuildAdapter(['思源黑體'], { fontTable });

      expect(adapter.hasFont('思源黑體')).toBe(true);
      // fetch:主'思源黑體'(404) + altName'微軟正黑體'(404) + 新細明體(200) = 3
      // chain[0]'思源黑體'==family 跳過、chain[1]'微軟正黑體'==altName 跳過
      expect(fetchCalls.length).toBe(3);
    },
  );

  it.skipIf(!LIBERATION_BYTES)('主 family 200 → CJK chain 不試（fast path）', async () => {
    setupFetchMock({ 標楷體: LIBERATION_BYTES! });
    const fontTable = mkCjkFontTable([{ name: '標楷體', charset: '88' }]);
    await loadFontsAndBuildAdapter(['標楷體'], { fontTable });

    expect(fetchCalls.length).toBe(1); // 主成功就不套 chain
  });

  it('不傳 fontTable → CJK chain 不套（backward compat、與 Sprint 157 一致）', async () => {
    setupFetchMock({});
    const adapter = await loadFontsAndBuildAdapter(['標楷體']);

    expect(adapter.hasFont('標楷體')).toBe(false);
    expect(fetchCalls.length).toBe(1);
  });
});
