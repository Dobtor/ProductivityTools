/**
 * Sprint 318 — ① deeper⁵：CanvasEditorPipeline。
 *
 * Sprint 303/308/313 之後第四輪深推。整合 resolver + bridge + ctx 為單一 drop-in API。
 *
 * 紀律 #18 scope-down：仍是 PROBE / caller 顯式呼叫；不快取 ctx.font 解析。
 */
import { describe, expect, it } from 'vitest';

import {
  CanvasEditorPipeline,
  type CanvasContextForPipeline,
} from '../../static/src/core/ooxml/font/CanvasEditorPipeline';
import type { RunMetrics } from '../../static/src/core/ooxml/font/ShapingEngine';

function fakeMeasureRun(text: string, _f: string, sizePt: number): Promise<RunMetrics> {
  return Promise.resolve({
    widthPt: text.length * sizePt * 0.5,
    heightPt: sizePt,
    glyphCount: text.length,
    advancesPt: text.split('').map(() => sizePt * 0.5),
    glyphs: [],
  });
}

function mkCtx(font: string, nativeWidthPerChar = 7): CanvasContextForPipeline {
  return {
    font,
    measureText(text) { return { width: nativeWidthPerChar * text.length }; },
  };
}

// ── 基本 hit / miss ─────────────────────────────────────────────────────

describe('Sprint 318 — measureWithCtxFont', () => {
  it('prewarm 後 cache hit → 用 bridge', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    await pipeline.measureAsync('Hi', 'DejaVu Sans', 12);
    const m = pipeline.measureWithCtxFont(mkCtx('12pt DejaVu Sans'), 'Hi');
    // widthPt 12 * 4/3 = 16 px
    expect(m.width).toBeCloseTo(16);
    expect(pipeline.getStats().bridgeHits).toBe(1);
    expect(pipeline.getStats().nativeFallbacks).toBe(0);
  });

  it('未 prewarm → fallback native', () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    const m = pipeline.measureWithCtxFont(mkCtx('12pt DejaVu Sans', 7), 'Hi');
    expect(m.width).toBe(14); // native: 7 * 2
    expect(pipeline.getStats().nativeFallbacks).toBe(1);
    expect(pipeline.getStats().bridgeHits).toBe(0);
  });

  it('fallbackToNative=false → cache miss 回 { width: 0 }', () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun, { fallbackToNative: false });
    const m = pipeline.measureWithCtxFont(mkCtx('12pt DejaVu Sans'), 'X');
    expect(m.width).toBe(0);
  });
});

// ── ctx.font 解析失敗 fallback ─────────────────────────────────────────

describe('Sprint 318 — ctx.font 解析失敗', () => {
  it('語法錯 → 用 fallback family/sizePt 查 bridge', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun, {
      fallbackFamily: 'F0',
      fallbackSizePt: 10,
    });
    await pipeline.measureAsync('Y', 'F0', 10);
    const m = pipeline.measureWithCtxFont(mkCtx('garbage'), 'Y');
    // widthPt 5 * 4/3 ≈ 6.67 px
    expect(m).not.toBeNull();
    expect(m.width).toBeCloseTo(5 * (4 / 3));
    expect(pipeline.getStats().fontParseFailure).toBe(1);
  });

  it('空字串 ctx.font 也 fallback', () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    pipeline.measureWithCtxFont(mkCtx(''), 'A');
    expect(pipeline.getStats().fontParseFailure).toBe(1);
  });
});

// ── 多 ctx.font 變動 ───────────────────────────────────────────────────

describe('Sprint 318 — 多 ctx.font 切換', () => {
  it('cache 各自獨立、不同 font 不互相 hit', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    await pipeline.measureAsync('A', 'F1', 12);
    await pipeline.measureAsync('A', 'F2', 14);

    const m1 = pipeline.measureWithCtxFont(mkCtx('12pt F1'), 'A');
    const m2 = pipeline.measureWithCtxFont(mkCtx('14pt F2'), 'A');
    const m3 = pipeline.measureWithCtxFont(mkCtx('14pt F1'), 'A'); // 沒 prewarm 此組合

    expect(m1).toEqual({ width: 6 * (4 / 3) });  // widthPt = 6
    expect(m2).toEqual({ width: 7 * (4 / 3) });  // widthPt = 7
    // m3 不在 cache → native fallback
    expect(pipeline.getStats().nativeFallbacks).toBe(1);
    expect(pipeline.getStats().bridgeHits).toBe(2);
  });
});

// ── measureSync / measureAsync passthrough ─────────────────────────────

describe('Sprint 318 — 直接走 bridge sync/async', () => {
  it('measureSync 繞過 ctx.font parse', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    await pipeline.measureAsync('Z', 'F', 12);
    const m = pipeline.measureSync('Z', 'F', 12);
    expect(m?.width).toBeCloseTo(6 * (4 / 3));
  });

  it('measureSync 未 prewarm → null', () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    expect(pipeline.measureSync('X', 'F', 12)).toBeNull();
  });
});

// ── stats / clear ─────────────────────────────────────────────────────

describe('Sprint 318 — stats 與 clear', () => {
  it('stats 含 fontParseSuccess + fontParseFailure + bridgeHits + nativeFallbacks + bridgeStats', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    await pipeline.measureAsync('A', 'F', 12);
    pipeline.measureWithCtxFont(mkCtx('12pt F'), 'A');   // hit
    pipeline.measureWithCtxFont(mkCtx('12pt F'), 'B');   // miss + native
    pipeline.measureWithCtxFont(mkCtx('garbage'), 'C');  // parse fail
    const s = pipeline.getStats();
    expect(s.fontParseSuccess).toBeGreaterThanOrEqual(2);
    expect(s.fontParseFailure).toBe(1);
    expect(s.bridgeHits).toBe(1);
    expect(s.nativeFallbacks).toBeGreaterThanOrEqual(2);
    expect(s.bridgeStats).toBeDefined();
  });

  it('clear 後 cache 與 stats 都歸零', async () => {
    const pipeline = new CanvasEditorPipeline(fakeMeasureRun);
    await pipeline.measureAsync('X', 'F', 12);
    pipeline.measureWithCtxFont(mkCtx('12pt F'), 'X');
    pipeline.clear();
    const s = pipeline.getStats();
    expect(s.bridgeHits).toBe(0);
    expect(s.fontParseSuccess).toBe(0);
    expect(pipeline.measureSync('X', 'F', 12)).toBeNull();
  });
});
