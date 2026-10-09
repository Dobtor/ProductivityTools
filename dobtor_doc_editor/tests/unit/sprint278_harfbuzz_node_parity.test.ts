/**
 * Sprint 278 — HarfBuzz browser/Node parity check（spike Node 端對照）
 *
 * 與 spikes/sprint278_harfbuzz_browser/index.html 同 input（DejaVuSans +
 * "Hello world"、sizePt=12）跑 measureRun()，輸出 glyph[0] 5 欄位 + total
 * width；spike doc 之 verification matrix 比對 browser 端結果。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';

const FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT);

describe.skipIf(!HAS_FONT)('Sprint 278 — HarfBuzz Node-side parity (vs browser spike)', () => {
  it('Node-side shape "Hello world" DejaVuSans 12pt → glyph[0] 5 fields + total width', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    const r = await engine.measureRun('Hello world', 'DejaVuSans', 12);

    // eslint-disable-next-line no-console
    console.log('[sprint278-node]', JSON.stringify({
      totalWidthPt: r.widthPt,
      glyphCount: r.glyphCount,
      glyph0: {
        glyphId: r.glyphs[0].glyphId,
        xAdvancePt: r.advancesPt[0],
        yAdvance: r.glyphs[0].yAdvance,
        xOffset: r.glyphs[0].xOffset,
        yOffset: r.glyphs[0].yOffset,
        cluster: r.glyphs[0].cluster,
      },
    }, null, 2));

    expect(r.glyphCount).toBe(11);
    expect(r.glyphs[0]).toMatchObject({
      glyphId: expect.any(Number),
      xAdvance: expect.any(Number),
      yAdvance: expect.any(Number),
      xOffset: expect.any(Number),
      yOffset: expect.any(Number),
      cluster: expect.any(Number),
    });
    // browser spike 量到 67.27pt（DejaVuSans + "Hello world" 12pt）
    expect(r.widthPt).toBeGreaterThan(60);
    expect(r.widthPt).toBeLessThan(75);
  });

  it('Node-side kern toggle on "AV" → kern on tighter than kern off', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    const kernOn = await engine.measureRun('AV', 'DejaVuSans', 12, { features: 'kern' });
    const kernOff = await engine.measureRun('AV', 'DejaVuSans', 12, { features: '-kern' });
    // eslint-disable-next-line no-console
    console.log('[sprint278-node] AV kern on=', kernOn.widthPt, 'off=', kernOff.widthPt, 'delta=', kernOn.widthPt - kernOff.widthPt);
    // browser spike 量 delta=-0.77pt（kern 收緊）
    expect(kernOn.widthPt).toBeLessThan(kernOff.widthPt);
  });
});
