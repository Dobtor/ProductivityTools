#!/usr/bin/env node
/**
 * Sprint 278 — Node-side cross-platform parity check
 *
 * 同 input（DejaVuSans + "Hello world"、sizePt=12）跑 ShapingEngine.shape()，
 * 對比 browser 端 glyph[0].xAdvance / totalWidth / kernDelta；確認 harfbuzzjs
 * Node + browser 兩端輸出 byte-identical。
 */
import { existsSync, readFileSync } from 'node:fs';
import { ShapingEngine } from '../../static/src/core/ooxml/font/index.ts';

// 同 spike 寬度算法（hb json raw → 5-field glyph、按 upem + sizePt 換 pt）
async function shape(engine, text, family, sizePt) {
  const metrics = await engine.measureRun(text, family, sizePt);
  // measureRun returns { widthPt, glyphCount, advancesPt, glyphs }
  return metrics;
}

const FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
if (!existsSync(FONT)) { console.error('DejaVuSans not found'); process.exit(2); }

const engine = new ShapingEngine();
engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));

const r = await shape(engine, 'Hello world', 'DejaVuSans', 12);
console.log(JSON.stringify({
  totalWidthPt: r.widthPt,
  glyphCount: r.glyphCount,
  sampleGlyph: {
    glyphId: r.glyphs[0].glyphId,
    xAdvance: r.advancesPt[0],
    yAdvance: r.glyphs[0].yAdvance,
    xOffset: r.glyphs[0].xOffset,
    yOffset: r.glyphs[0].yOffset,
    cluster: r.glyphs[0].cluster,
  },
}, null, 2));
