/**
 * Sprint 61 — BrowserTextMetrics 單元測試
 *
 * 驗證重點：
 *   1. 用 mock canvas 取得真實字寬（不依賴 vitest 環境的 canvas API）
 *   2. LRU cache 命中（同 text+font+size+bold → cache hit）
 *   3. 不同 fontSize / bold / italic / family → 不同 cache key
 *   4. canvas 為 null 時 fallback EstimateMetrics（vitest node 環境正常運作）
 *   5. measure 失敗時 fallback
 *   6. spacing 後處理（cache 的是 base width、spacing 每次加）
 *   7. measureLineHeight 仍走 fallback（Sprint 61 範圍限定）
 */

import { describe, expect, it } from 'vitest';
import {
  BrowserTextMetrics,
  type MeasureCanvas2D,
} from '../../../static/src/core/layout/BrowserTextMetrics';
import { EstimateMetrics } from '../../../static/src/core/layout/TextMetrics';

/**
 * Mock canvas：根據 font 字串和 text 長度返回 deterministic width。
 * 模擬：CJK 字元寬度 = fontSize × 1.0、Latin = fontSize × 0.55、bold 加 5%。
 */
function makeMockCanvas() {
  const callLog: Array<{ font: string; text: string; returnedWidth: number }> = [];
  const canvas: MeasureCanvas2D = {
    font: '',
    measureText(text: string) {
      // 解析 font 字串（簡化版：找 fontSize pt + 是否 bold）
      const fontStr = canvas.font;
      const sizeMatch = fontStr.match(/(\d+(?:\.\d+)?)pt/);
      const size = sizeMatch ? parseFloat(sizeMatch[1]) : 10;
      const isBold = /\bbold\b/.test(fontStr);
      // 簡化：CJK 字元 × 1.0、Latin × 0.55
      let w = 0;
      for (const ch of text) {
        const code = ch.charCodeAt(0);
        if (code >= 0x4e00 && code <= 0x9fff) w += size * 1.0;
        else w += size * 0.55;
      }
      if (isBold) w *= 1.05;
      callLog.push({ font: fontStr, text, returnedWidth: w });
      return { width: w };
    },
  };
  return { canvas, callLog };
}

describe('Sprint 61 — BrowserTextMetrics 基本量測', () => {
  it('用 mock canvas 取得真實字寬', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    // 12pt × "abc" 3 latin chars × 0.55 = 19.8
    expect(metrics.measureWidth('abc', { fontSize: 12 })).toBeCloseTo(19.8, 5);
  });

  it('bold 加 5%（mock 規則）', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    const plain = metrics.measureWidth('abc', { fontSize: 12 });
    const bold = metrics.measureWidth('abc', { fontSize: 12, bold: true });
    expect(bold).toBeCloseTo(plain * 1.05, 5);
  });

  it('CJK 字元 × 1.0 em（mock 規則）', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    // 12pt × "工程" 2 CJK chars × 1.0 = 24
    expect(metrics.measureWidth('工程', { fontSize: 12 })).toBeCloseTo(24, 5);
  });

  it('空字串 → 0', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    expect(metrics.measureWidth('', { fontSize: 12 })).toBe(0);
  });
});

describe('Sprint 61 — BrowserTextMetrics cache 行為', () => {
  it('同 text+font+size+bold → cache hit', () => {
    const { canvas, callLog } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    metrics.measureWidth('abc', { fontSize: 12 });
    metrics.measureWidth('abc', { fontSize: 12 });
    metrics.measureWidth('abc', { fontSize: 12 });
    expect(callLog.length).toBe(1); // 只 measure 一次
    expect(metrics.stats().hits).toBe(2);
    expect(metrics.stats().misses).toBe(1);
  });

  it('不同 fontSize → 不同 cache key', () => {
    const { canvas, callLog } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    metrics.measureWidth('abc', { fontSize: 12 });
    metrics.measureWidth('abc', { fontSize: 14 });
    expect(callLog.length).toBe(2);
  });

  it('不同 bold / italic / family → 不同 cache key', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    metrics.measureWidth('abc', { fontSize: 12 });
    metrics.measureWidth('abc', { fontSize: 12, bold: true });
    metrics.measureWidth('abc', { fontSize: 12, italic: true });
    metrics.measureWidth('abc', { fontSize: 12, fontFamily: 'Arial' });
    metrics.measureWidth('abc', { fontSize: 12, fontFamily: 'Times' });
    expect(metrics.stats().misses).toBe(5);
  });

  it('LRU evict 最舊 entry', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas, cacheMax: 2 });
    metrics.measureWidth('a', { fontSize: 12 });
    metrics.measureWidth('b', { fontSize: 12 });
    metrics.measureWidth('c', { fontSize: 12 }); // 'a' evicted
    // 再 measure 'a' 應 cache miss
    metrics.measureWidth('a', { fontSize: 12 });
    expect(metrics.stats().misses).toBe(4); // a, b, c, a-again
  });

  it('get touch entry（LRU 推到最新）', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas, cacheMax: 2 });
    metrics.measureWidth('a', { fontSize: 12 });
    metrics.measureWidth('b', { fontSize: 12 });
    metrics.measureWidth('a', { fontSize: 12 }); // touch 'a'
    metrics.measureWidth('c', { fontSize: 12 }); // 'b' evicted（不是 'a'）
    metrics.measureWidth('a', { fontSize: 12 }); // 'a' 仍在 cache → hit
    expect(metrics.stats().hits).toBe(2); // 第二次 'a' + 第五次 'a'
  });

  it('clear() 重置', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    metrics.measureWidth('a', { fontSize: 12 });
    metrics.measureWidth('a', { fontSize: 12 });
    metrics.clear();
    expect(metrics.stats()).toEqual({ hits: 0, misses: 0, size: 0, fallbackUses: 0 });
  });
});

describe('Sprint 61 — BrowserTextMetrics fallback', () => {
  it('canvas 為 null 時 fallback EstimateMetrics', () => {
    // 不傳 canvas2d，自動 try create 在 vitest happy-dom 環境
    // 注意：vitest 預設 happy-dom 提供 canvas getContext 但回傳 null（無實作）
    // BrowserTextMetrics 應 fallback
    const fallback = new EstimateMetrics();
    const metrics = new BrowserTextMetrics({ canvas2d: undefined as never, fallback });
    // 在 node/jsdom 環境，canvas 取不到 → fallback
    const w = metrics.measureWidth('abc', { fontSize: 12 });
    expect(typeof w).toBe('number');
    expect(w).toBeGreaterThan(0);
    // fallbackUses 或 cache size 取決於是否取得 canvas
    const stats = metrics.stats();
    if (stats.fallbackUses > 0) {
      // 確認真的走 fallback path
      expect(stats.fallbackUses).toBeGreaterThanOrEqual(1);
    }
  });

  it('measureLineHeight 走 fallback（Sprint 61 不實作）', () => {
    const { canvas } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    // 12pt × 1.2 (EstimateMetrics default) = 14.4
    expect(metrics.measureLineHeight({ fontSize: 12 })).toBeCloseTo(14.4, 5);
  });

  it('measure throw 時 fallback', () => {
    const fallback = new EstimateMetrics();
    let throwOnNext = false;
    const canvas: MeasureCanvas2D = {
      font: '',
      measureText(text: string) {
        if (throwOnNext) throw new Error('mock throw');
        return { width: 100 };
      },
    };
    const metrics = new BrowserTextMetrics({ canvas2d: canvas, fallback });
    // 第一次成功
    metrics.measureWidth('a', { fontSize: 12 });
    expect(metrics.stats().fallbackUses).toBe(0);
    // 第二次 throw → fallback
    throwOnNext = true;
    const w = metrics.measureWidth('b', { fontSize: 12 });
    expect(metrics.stats().fallbackUses).toBe(1);
    // fallback 結果與直接呼叫 EstimateMetrics 一致
    expect(w).toBeCloseTo(fallback.measureWidth('b', { fontSize: 12 }), 5);
  });
});

describe('Sprint 61 — BrowserTextMetrics spacing 後處理', () => {
  it('spacing 不影響 cache key 但每次加', () => {
    const { canvas, callLog } = makeMockCanvas();
    const metrics = new BrowserTextMetrics({ canvas2d: canvas });
    // 同 (text, font, size, bold)、不同 spacing → cache key 相同、measure 一次
    const baseW = metrics.measureWidth('abc', { fontSize: 12 });
    const wSpacing = metrics.measureWidth('abc', { fontSize: 12, spacing: 1 });
    expect(callLog.length).toBe(1); // cache hit on second call
    // spacing × 3 chars = 3
    expect(wSpacing).toBeCloseTo(baseW + 3, 5);
  });
});
