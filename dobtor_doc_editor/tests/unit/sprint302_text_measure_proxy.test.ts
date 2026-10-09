/**
 * Sprint 302 — ① deeper：TextMeasureProxy PROBE。
 *
 * Follow-up to Sprint 269/275/297 honest gap「LayoutPipeline 未接 canvas-editor」
 * 第二輪深推。本 sprint = sync proxy + caller-side pre-warm pattern PROBE，
 * 為 future canvas-editor 整合鋪基礎。
 *
 * 範圍（PROBE / 紀律 #18 scope-down）：
 *   - prewarm + measureSync cache hit / miss
 *   - measureAsync 動態 warm
 *   - FIFO eviction
 *   - stats（hit rate / size）
 *   - clear 重置
 *   - 不接 canvas-editor real path（紀律 #21、避免破現有 13 Playwright E2E）
 */
import { describe, expect, it } from 'vitest';

import { TextMeasureProxy } from '../../static/src/core/ooxml/font/TextMeasureProxy';
import type { RunMetrics } from '../../static/src/core/ooxml/font/ShapingEngine';

/** 假 measureRun：依字串長度 × sizePt 算寬度，模擬 ShapingEngine 行為。 */
function fakeMeasureRun(text: string, _family: string, sizePt: number): Promise<RunMetrics> {
  const widthPt = text.length * sizePt * 0.5;
  return Promise.resolve({
    widthPt,
    heightPt: sizePt,
    glyphCount: text.length,
    advancesPt: text.split('').map(() => sizePt * 0.5),
    glyphs: [],
  });
}

describe('Sprint 302 — TextMeasureProxy prewarm + measureSync', () => {
  it('measureSync 未 prewarm → 回 null', () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun);
    expect(proxy.measureSync('Hello', 'DejaVuSans', 12)).toBeNull();
  });

  it('prewarm 後 measureSync 回 cache entry', async () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun);
    await proxy.prewarm([
      { text: 'Hello', family: 'DejaVuSans', sizePt: 12 },
      { text: 'World', family: 'DejaVuSans', sizePt: 12 },
    ]);
    const a = proxy.measureSync('Hello', 'DejaVuSans', 12);
    const b = proxy.measureSync('World', 'DejaVuSans', 12);
    expect(a).toEqual({ widthPt: 30, heightPt: 12, glyphCount: 5 });
    expect(b).toEqual({ widthPt: 30, heightPt: 12, glyphCount: 5 });
  });

  it('不同 family / sizePt 為獨立 cache key', async () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun);
    await proxy.prewarm([
      { text: 'A', family: 'F1', sizePt: 10 },
      { text: 'A', family: 'F1', sizePt: 20 },
      { text: 'A', family: 'F2', sizePt: 10 },
    ]);
    expect(proxy.measureSync('A', 'F1', 10)?.widthPt).toBe(5);
    expect(proxy.measureSync('A', 'F1', 20)?.widthPt).toBe(10);
    expect(proxy.measureSync('A', 'F2', 10)?.widthPt).toBe(5);
  });
});

describe('Sprint 302 — measureAsync 動態 warm', () => {
  it('未 cache 時觸發 measureRun + 寫 cache', async () => {
    let called = 0;
    const proxy = new TextMeasureProxy((text, family, sizePt) => {
      called++;
      return fakeMeasureRun(text, family, sizePt);
    });
    const r1 = await proxy.measureAsync('X', 'F', 10);
    expect(r1.widthPt).toBe(5);
    expect(called).toBe(1);
    // 第二次同 key → 不重 measure
    const r2 = await proxy.measureAsync('X', 'F', 10);
    expect(r2).toEqual(r1);
    expect(called).toBe(1);
  });
});

describe('Sprint 302 — FIFO eviction', () => {
  it('超過 maxEntries 時 evict 最舊 entry', async () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun, { maxEntries: 2 });
    await proxy.prewarm([
      { text: 'A', family: 'F', sizePt: 10 },
      { text: 'B', family: 'F', sizePt: 10 },
      { text: 'C', family: 'F', sizePt: 10 },
    ]);
    expect(proxy.measureSync('A', 'F', 10)).toBeNull(); // 已 evict
    expect(proxy.measureSync('B', 'F', 10)).not.toBeNull();
    expect(proxy.measureSync('C', 'F', 10)).not.toBeNull();
  });
});

describe('Sprint 302 — stats hit rate', () => {
  it('stats 反映 hit / miss / hitRate', async () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun);
    await proxy.prewarm([{ text: 'Y', family: 'F', sizePt: 10 }]);
    proxy.measureSync('Y', 'F', 10);  // hit
    proxy.measureSync('Y', 'F', 10);  // hit
    proxy.measureSync('Z', 'F', 10);  // miss
    const s = proxy.stats();
    expect(s.hits).toBe(2);
    expect(s.misses).toBe(1);
    expect(s.hitRate).toBeCloseTo(2 / 3, 5);
    expect(s.size).toBe(1);
  });
});

describe('Sprint 302 — clear', () => {
  it('clear 後 cache 空、stats 歸零', async () => {
    const proxy = new TextMeasureProxy(fakeMeasureRun);
    await proxy.prewarm([{ text: 'X', family: 'F', sizePt: 10 }]);
    proxy.measureSync('X', 'F', 10);
    proxy.clear();
    expect(proxy.measureSync('X', 'F', 10)).toBeNull();
    expect(proxy.stats().size).toBe(0);
    expect(proxy.stats().hits).toBe(0);
    expect(proxy.stats().misses).toBe(1); // measureSync 後又算一次 miss
  });
});

describe('Sprint 302 — prewarm dedup', () => {
  it('prewarm 重複 key 只 measure 一次', async () => {
    let called = 0;
    const proxy = new TextMeasureProxy((text, family, sizePt) => {
      called++;
      return fakeMeasureRun(text, family, sizePt);
    });
    await proxy.prewarm([
      { text: 'Z', family: 'F', sizePt: 10 },
      { text: 'Z', family: 'F', sizePt: 10 },
      { text: 'Z', family: 'F', sizePt: 10 },
    ]);
    expect(called).toBe(1);
  });
});
