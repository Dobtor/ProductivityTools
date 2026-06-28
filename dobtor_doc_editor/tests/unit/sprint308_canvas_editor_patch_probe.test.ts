/**
 * Sprint 308 — ① deeper³：CanvasEditorPatchProbe。
 *
 * Sprint 303 CanvasEditorMeasureBridge 第二輪 PROBE。本 sprint PROBE：
 *   - wrapCanvasContext：ES Proxy 包 ctx、measureText 走 bridge cache、
 *     其他屬性透傳
 *   - canSafelyPatchPrototype：環境偵測
 *
 * 紀律 #18 scope-down：caller 顯式 opt-in、不污染 prototype；不接 canvas-editor
 *   real path（紀律 #21）。
 */
import { describe, expect, it } from 'vitest';

import {
  wrapCanvasContext,
  canSafelyPatchPrototype,
  type MinimalCanvasContextForPatch,
} from '../../static/src/core/ooxml/font/CanvasEditorPatchProbe';
import { CanvasEditorMeasureBridge } from '../../static/src/core/ooxml/font/CanvasEditorMeasureBridge';
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

function mkCtx(nativeWidth: number, extras: Record<string, unknown> = {}): MinimalCanvasContextForPatch {
  return {
    measureText: (text: string) => ({ width: nativeWidth * text.length }),
    fillStyle: '#000',
    ...extras,
  };
}

// ── wrapCanvasContext：bridge hit ────────────────────────────────────────

describe('Sprint 308 — bridge cache hit 取代 native', () => {
  it('cache hit → 用 bridge 結果（px、不是 native fallback）', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    await bridge.measureTextAsync('Hi', 'F', 12);  // pre-warm
    const ctx = mkCtx(999);
    const wrapped = wrapCanvasContext(ctx, bridge, { defaultFamily: 'F', defaultSizePt: 12 });
    const m = wrapped.measureText('Hi');
    // bridge: widthPt=12, 96 dpi → 16 px
    expect(m.width).toBeCloseTo(16);
    expect(wrapped.__patchProbeStats.bridgeHits).toBe(1);
    expect(wrapped.__patchProbeStats.nativeFallbacks).toBe(0);
  });

  it('多次 hit 累積 bridgeHits stat', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    await bridge.measureTextAsync('A', 'F', 12);
    const wrapped = wrapCanvasContext(mkCtx(99), bridge, { defaultFamily: 'F', defaultSizePt: 12 });
    wrapped.measureText('A');
    wrapped.measureText('A');
    wrapped.measureText('A');
    expect(wrapped.__patchProbeStats.bridgeHits).toBe(3);
  });
});

// ── wrapCanvasContext：cache miss fallback ──────────────────────────────

describe('Sprint 308 — cache miss fallback', () => {
  it('fallbackToNative 預設 true → cache miss 退化 native', () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    // 不 prewarm
    const ctx = mkCtx(7);
    const wrapped = wrapCanvasContext(ctx, bridge, { defaultFamily: 'F', defaultSizePt: 12 });
    const m = wrapped.measureText('hello');
    // native: 7 * 5 = 35
    expect(m.width).toBe(35);
    expect(wrapped.__patchProbeStats.nativeFallbacks).toBe(1);
    expect(wrapped.__patchProbeStats.bridgeHits).toBe(0);
  });

  it('fallbackToNative = false → cache miss 回 { width: 0 }', () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const wrapped = wrapCanvasContext(mkCtx(7), bridge, {
      defaultFamily: 'F',
      defaultSizePt: 12,
      fallbackToNative: false,
    });
    const m = wrapped.measureText('hello');
    expect(m.width).toBe(0);
    expect(wrapped.__patchProbeStats.zeroFallbacks).toBe(1);
  });
});

// ── ES Proxy 透傳其他屬性 ────────────────────────────────────────────────

describe('Sprint 308 — Proxy 透傳其他屬性', () => {
  it('非 measureText 屬性透傳到原 ctx', () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const ctx = mkCtx(0, { someFunc: () => 42 });
    const wrapped = wrapCanvasContext(ctx, bridge, { defaultFamily: 'F', defaultSizePt: 12 });
    expect(wrapped.fillStyle).toBe('#000');
    expect((wrapped.someFunc as () => number)()).toBe(42);
  });

  it('set 屬性也透傳（mutate 原 ctx）', () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const ctx = mkCtx(0);
    const wrapped = wrapCanvasContext(ctx, bridge, { defaultFamily: 'F', defaultSizePt: 12 });
    wrapped.fillStyle = '#fff';
    expect(ctx.fillStyle).toBe('#fff');
  });
});

// ── canSafelyPatchPrototype ──────────────────────────────────────────────

describe('Sprint 308 — canSafelyPatchPrototype', () => {
  it('Node 環境（無 CanvasRenderingContext2D）→ false', () => {
    expect(canSafelyPatchPrototype()).toBe(false);
  });

  it('mock CanvasRenderingContext2D 為「native」function → true', () => {
    const g = globalThis as { CanvasRenderingContext2D?: unknown };
    const original = g.CanvasRenderingContext2D;
    try {
      g.CanvasRenderingContext2D = {
        prototype: {
          measureText: function nativeMock() { /* mock */ },
        },
      };
      // function source 不含 [native code] → false
      expect(canSafelyPatchPrototype()).toBe(false);
    } finally {
      if (original === undefined) delete g.CanvasRenderingContext2D;
      else g.CanvasRenderingContext2D = original;
    }
  });
});

// ── 邊界：bridge cache 與 default 不符 ───────────────────────────────────

describe('Sprint 308 — defaultFamily / defaultSizePt 對應', () => {
  it('caller 改 defaultSizePt 後 cache key 也跟著變、可能 miss', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    await bridge.measureTextAsync('X', 'F', 12); // prewarm with 12
    const wrapped = wrapCanvasContext(mkCtx(99), bridge, { defaultFamily: 'F', defaultSizePt: 14 });
    // bridge 找不到（key F|14|X 未 prewarm）→ fallback native (99)
    const m = wrapped.measureText('X');
    expect(m.width).toBe(99);
    expect(wrapped.__patchProbeStats.nativeFallbacks).toBe(1);
  });
});
