/**
 * Sprint 281 — Phase 2.1 full chain Node parity（與 browser e2e 對照）
 *
 * 完整鏈：setHbModuleLoader（default 路徑）→ loadShapingFontWithChain
 * （mock fetch / primary 404 → fallback 200）→ engine.measureRun → readFontMetrics
 * → resolveOoxmlLineHeight。
 *
 * 與 spikes/sprint281_phase2_1_full_browser/index.html 同 input 比對輸出。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import {
  ShapingEngine,
  loadShapingFontWithChain,
  readFontMetrics,
  resolveOoxmlLineHeight,
} from '../../static/src/core/ooxml/font';

const FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT);

describe.skipIf(!HAS_FONT)('Sprint 281 — Phase 2.1 full chain Node parity', () => {
  // ☠️ `describe.skipIf(...)` **不會阻止 describe 主體執行**——它只是把裡面註冊的
  // test 標成 skip。所以在主體頂層 `readFileSync(FONT)` 會照跑，在沒有 DejaVu
  // 的機器（例如 macOS，那是 Debian 的字型路徑）整個檔案直接 ENOENT 失敗，而不是
  // 乾淨地 skip。2026-10-09 取回 TS 子系統時在 macOS 上踩到。
  // 修法：改成 lazy——第一次用到才讀。
  let _fontBytes: Uint8Array | null = null;
  const fontBytes = () => (_fontBytes ??= new Uint8Array(readFileSync(FONT)));
  it('Full chain: ShapingFontChain(primary 404 → fallback 200) → measureRun → readFontMetrics → resolveOoxmlLineHeight', async () => {
    const engine = new ShapingEngine();
    const fetchImpl: typeof fetch = (async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (url.endsWith('/dejavu.ttf')) return new Response(fontBytes(), { status: 200 });
      return new Response('', { status: 404 });
    }) as unknown as typeof fetch;

    const loadResult = await loadShapingFontWithChain({
      engine,
      primary: { family: 'NotExistFont', url: '/spike-404/does-not-exist.ttf' },
      fallbacks: [{ family: 'DejaVuSans', url: 'http://localhost/dejavu.ttf' }],
      fetchImpl,
    });
    expect(loadResult.chainAttempted ?? loadResult.attemptedCount).toBe(2);
    expect(loadResult.loadedAs).toBe('NotExistFont');
    expect(loadResult.loadedFrom.family).toBe('DejaVuSans');

    // engine 端用 primary.family 查（chain helper register under primary）
    const r = await engine.measureRun('Hello world', 'NotExistFont', 12);
    expect(r.glyphCount).toBe(11);
    expect(r.widthPt).toBeCloseTo(67.271484375, 6);  // 與 browser e2e 完全相同

    // FontMetrics
    const metrics = readFontMetrics(loadResult.bytes);
    expect(metrics.unitsPerEm).toBe(2048);
    expect(metrics.ascender).toBe(1901);
    expect(metrics.descender).toBe(483);
    expect(metrics.lineGap).toBe(410);
    expect(metrics.typoAscender).toBe(1556);

    // resolveOoxmlLineHeight 三種 rule
    const natural = resolveOoxmlLineHeight(metrics, 12);
    const auto = resolveOoxmlLineHeight(metrics, 12, 'auto', 1.5);
    const exact = resolveOoxmlLineHeight(metrics, 12, 'exact', 18);
    const atLeast = resolveOoxmlLineHeight(metrics, 12, 'atLeast', 20);

    // eslint-disable-next-line no-console
    console.log('[sprint281-node]', JSON.stringify({
      chainAttempted: loadResult.attemptedCount,
      shapeGlyphCount: r.glyphCount,
      shapeWidthPt: r.widthPt,
      glyph0: { glyphId: r.glyphs[0].glyphId, xAdvance: r.glyphs[0].xAdvance, advancePt: r.advancesPt[0] },
      metrics: { unitsPerEm: metrics.unitsPerEm, ascender: metrics.ascender, descender: metrics.descender, lineGap: metrics.lineGap, typoAscender: metrics.typoAscender },
      natural: natural.heightPt,
      auto: auto.heightPt,
      exact: exact.heightPt,
      atLeast: atLeast.heightPt,
    }, null, 2));

    expect(natural.heightPt).toBeCloseTo(16.37109375, 6);
    expect(auto.heightPt).toBeCloseTo(24.556640625, 6);
    expect(exact.heightPt).toBe(18);
    expect(atLeast.heightPt).toBe(20);  // natural 16.37 < 20 → 取 20
  });
});
