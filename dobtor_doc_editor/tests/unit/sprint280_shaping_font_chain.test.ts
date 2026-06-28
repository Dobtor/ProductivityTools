/**
 * Sprint 280 — ShapingFontChain unit tests
 *
 * 驗證 fetch + fallback chain + register 到 ShapingEngine：
 *   1. Primary 200 → register、不試 fallback
 *   2. Primary 404 → 試 fallback 1、register
 *   3. 全 chain 失敗 → FontChainExhaustedError
 *   4. Empty fallbacks + primary 失敗 → throw
 *   5. fetchImpl 注入支援（測試友好、不需 mock global.fetch）
 *   6. Timeout 觸發 abort → 視為失敗、試下一個
 *   7. getDefaultCjkFallbackChain helper 對 urlBuilder 正確呼叫
 *   8. Loaded family = primary.family（即使實際載入 fallback、Sprint 166 行為）
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 */
import { describe, expect, it, vi } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import {
  ShapingEngine,
  loadShapingFontWithChain,
  getDefaultCjkFallbackChain,
  FontChainExhaustedError,
} from '../../static/src/core/ooxml/font';

const FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT);

function makeFetch200(bytes: Uint8Array): typeof fetch {
  return (async () => new Response(bytes, { status: 200, statusText: 'OK' })) as unknown as typeof fetch;
}
function makeFetch404(): typeof fetch {
  return (async () => new Response('not found', { status: 404, statusText: 'Not Found' })) as unknown as typeof fetch;
}
function makeFetchByUrl(map: Record<string, { status: number; bytes?: Uint8Array }>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const entry = map[url];
    if (!entry) return new Response('', { status: 404 });
    return new Response(entry.bytes ?? '', { status: entry.status });
  }) as unknown as typeof fetch;
}

describe.skipIf(!HAS_FONT)('Sprint 280 — ShapingFontChain (fetch + fallback chain)', () => {
  const fontBytes = new Uint8Array(readFileSync(FONT));

  it('Primary 200 → register 到 engine、不試 fallback', async () => {
    const engine = new ShapingEngine();
    const warnSpy = vi.fn();
    const r = await loadShapingFontWithChain({
      engine,
      primary: { family: 'A', url: 'https://example.com/a.ttf' },
      fallbacks: [
        { family: 'B', url: 'https://example.com/b.ttf' },
        { family: 'C', url: 'https://example.com/c.ttf' },
      ],
      fetchImpl: makeFetch200(fontBytes),
      warn: warnSpy,
    });
    expect(r.loadedAs).toBe('A');
    expect(r.loadedFrom.family).toBe('A');
    expect(r.attemptedCount).toBe(1);
    expect(engine.listFonts()).toContain('A');
    expect(warnSpy).not.toHaveBeenCalled();  // primary 成功不 warn
  });

  it('Primary 404 → 試 fallback 1、register under primary.family', async () => {
    const engine = new ShapingEngine();
    const warnSpy = vi.fn();
    const r = await loadShapingFontWithChain({
      engine,
      primary: { family: 'PrimaryName', url: 'https://example.com/primary.ttf' },
      fallbacks: [{ family: 'FallbackA', url: 'https://example.com/fallback-a.ttf' }],
      fetchImpl: makeFetchByUrl({
        'https://example.com/primary.ttf': { status: 404 },
        'https://example.com/fallback-a.ttf': { status: 200, bytes: fontBytes },
      }),
      warn: warnSpy,
    });
    expect(r.loadedAs).toBe('PrimaryName');  // 註冊用 primary 名
    expect(r.loadedFrom.family).toBe('FallbackA');
    expect(r.attemptedCount).toBe(2);
    expect(engine.listFonts()).toContain('PrimaryName');
    expect(engine.listFonts()).not.toContain('FallbackA');  // 不註冊原始 fallback name
    expect(warnSpy).toHaveBeenCalledOnce();
    expect(warnSpy.mock.calls[0][0]).toMatch(/PrimaryName.*FallbackA/);
  });

  it('全 chain 失敗 → FontChainExhaustedError、含所有 errors', async () => {
    const engine = new ShapingEngine();
    await expect(
      loadShapingFontWithChain({
        engine,
        primary: { family: 'A', url: 'https://example.com/a.ttf' },
        fallbacks: [
          { family: 'B', url: 'https://example.com/b.ttf' },
          { family: 'C', url: 'https://example.com/c.ttf' },
        ],
        fetchImpl: makeFetch404(),
      }),
    ).rejects.toBeInstanceOf(FontChainExhaustedError);
  });

  it('Empty fallbacks + primary 失敗 → throw（chain 至少有 1 個 entry = primary）', async () => {
    const engine = new ShapingEngine();
    await expect(
      loadShapingFontWithChain({
        engine,
        primary: { family: 'A', url: 'https://example.com/a.ttf' },
        fetchImpl: makeFetch404(),
      }),
    ).rejects.toBeInstanceOf(FontChainExhaustedError);
  });

  it('fetchImpl 缺省且 global.fetch undefined → 顯式 throw（caller 收到清楚錯誤）', async () => {
    const engine = new ShapingEngine();
    const originalFetch = (globalThis as any).fetch;
    (globalThis as any).fetch = undefined;
    try {
      await expect(
        loadShapingFontWithChain({
          engine,
          primary: { family: 'A', url: 'https://example.com/a.ttf' },
        }),
      ).rejects.toThrow(/global\.fetch unavailable/);
    } finally {
      (globalThis as any).fetch = originalFetch;
    }
  });

  it('Timeout 觸發 abort → 視為失敗、試下一個 fallback', async () => {
    const engine = new ShapingEngine();
    const slowFetch: typeof fetch = (async (_input, init) => {
      // 100ms 才 resolve、若 abort 先觸發則 throw AbortError
      return new Promise((resolve, reject) => {
        const t = setTimeout(() => resolve(new Response(fontBytes, { status: 200 })), 100);
        const signal = (init as RequestInit | undefined)?.signal;
        if (signal) {
          signal.addEventListener('abort', () => {
            clearTimeout(t);
            reject(new Error('aborted'));
          });
        }
      });
    }) as unknown as typeof fetch;
    const fastFetch: typeof fetch = makeFetch200(fontBytes);
    let callCount = 0;
    const composed: typeof fetch = (async (...args: Parameters<typeof fetch>) => {
      callCount++;
      return callCount === 1 ? slowFetch(...args) : fastFetch(...args);
    }) as typeof fetch;

    const r = await loadShapingFontWithChain({
      engine,
      primary: { family: 'A', url: 'https://example.com/a.ttf' },
      fallbacks: [{ family: 'B', url: 'https://example.com/b.ttf' }],
      timeoutMs: 30,  // 比 100ms 短、必觸發 abort
      fetchImpl: composed,
    });
    expect(r.loadedAs).toBe('A');
    expect(r.loadedFrom.family).toBe('B');
    expect(r.attemptedCount).toBe(2);
  });

  it('getDefaultCjkFallbackChain 對 urlBuilder 正確呼叫、回 [思源黑體, 微軟正黑體, 新細明體]', () => {
    const calls: string[] = [];
    const chain = getDefaultCjkFallbackChain((family) => {
      calls.push(family);
      return `/fonts/${encodeURIComponent(family)}`;
    });
    expect(chain.map((e) => e.family)).toEqual(['思源黑體', '微軟正黑體', '新細明體']);
    expect(calls).toEqual(['思源黑體', '微軟正黑體', '新細明體']);
    expect(chain[0].url).toMatch(/%E6%80%9D%E6%BA%90/);  // 思源 url-encoded
  });

  it('Loaded font 可被 measureRun 用（end-to-end smoke test）', async () => {
    const engine = new ShapingEngine();
    await loadShapingFontWithChain({
      engine,
      primary: { family: 'DejaVuSans', url: 'https://example.com/dejavu.ttf' },
      fetchImpl: makeFetch200(fontBytes),
    });
    const r = await engine.measureRun('Hello', 'DejaVuSans', 12);
    expect(r.glyphCount).toBe(5);
    expect(r.widthPt).toBeGreaterThan(0);
  });
});
