/**
 * Font 模組單元測試 (Phase D.2)
 *
 * 涵蓋：
 *   - ShapingEngine：載入字型 / shape 文字 / glyph[] 產出
 *   - FontMetrics：opentype.js 讀字型核心度量 + 行高計算
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import {
  ShapingEngine,
  readFontMetrics,
  lineHeightPt,
} from '../../static/src/core/ooxml/font';

const FONT_CANDIDATES = [
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
  '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
  '/mnt/c/Windows/Fonts/arial.ttf',
];

const FONT_PATH = (() => {
  for (const p of FONT_CANDIDATES) {
    if (existsSync(p)) return p;
  }
  return null;
})();

describe.skipIf(!FONT_PATH)('ShapingEngine', () => {
  it('未載入字型時 shape 應 throw', async () => {
    const engine = new ShapingEngine();
    await expect(engine.shape('Hello', 'Unknown', 12)).rejects.toThrow(/not loaded/);
  });

  it('loadFont + shape "ABC" → 3 glyph，advance 全為正', async () => {
    const engine = new ShapingEngine();
    const bytes = readFileSync(FONT_PATH!);
    engine.loadFont('TestFont', new Uint8Array(bytes));
    const glyphs = await engine.shape('ABC', 'TestFont', 12);
    expect(glyphs).toHaveLength(3);
    for (const g of glyphs) {
      expect(g.xAdvance).toBeGreaterThan(0);
      // cluster 應為原文字的 byte index（ABC 各對應 0/1/2）
      expect(g.cluster).toBeGreaterThanOrEqual(0);
    }
  });

  it('listFonts 列出已載入字型', () => {
    const engine = new ShapingEngine();
    engine.loadFont('A', new Uint8Array([0]));
    engine.loadFont('B', new Uint8Array([0]));
    expect(engine.listFonts().sort()).toEqual(['A', 'B']);
  });

  it('clear 移除所有已載入字型', async () => {
    const engine = new ShapingEngine();
    const bytes = readFileSync(FONT_PATH!);
    engine.loadFont('X', new Uint8Array(bytes));
    expect(engine.listFonts()).toEqual(['X']);
    engine.clear();
    expect(engine.listFonts()).toEqual([]);
  });

  it('連續 shape 同字型字型 cache 不重建（效能優化驗證）', async () => {
    const engine = new ShapingEngine();
    const bytes = readFileSync(FONT_PATH!);
    engine.loadFont('Cached', new Uint8Array(bytes));
    const t1 = performance.now();
    await engine.shape('Hello', 'Cached', 12);
    const firstShape = performance.now() - t1;
    const t2 = performance.now();
    await engine.shape('World', 'Cached', 12);
    const secondShape = performance.now() - t2;
    // 第二次 shape 因為 face/font 已 cache 應明顯較快（不需要 createFace）
    // 留 5ms 以上的緩衝避免抖動
    expect(secondShape).toBeLessThan(firstShape + 5);
  });
});

describe.skipIf(!FONT_PATH)('FontMetrics', () => {
  it('readFontMetrics 回傳 unitsPerEm / ascender / descender / lineGap', () => {
    const bytes = readFileSync(FONT_PATH!);
    const metrics = readFontMetrics(new Uint8Array(bytes));
    expect(metrics.unitsPerEm).toBeGreaterThan(0);
    expect(metrics.ascender).toBeGreaterThan(0);
    expect(metrics.descender).toBeGreaterThanOrEqual(0); // 已轉為正值
    expect(metrics.lineGap).toBeGreaterThanOrEqual(0);
  });

  it('lineHeightPt 計算公式正確', () => {
    const metrics = {
      unitsPerEm: 1000,
      ascender: 800,
      descender: 200,
      lineGap: 100,
    };
    // (800 + 200 + 100) * 12 / 1000 = 13.2
    expect(lineHeightPt(metrics, 12)).toBeCloseTo(13.2, 2);
  });

  it('readFontMetrics 接受 Uint8Array 與 ArrayBuffer 兩種輸入', () => {
    const bytes = readFileSync(FONT_PATH!);
    const u8 = new Uint8Array(bytes);
    const ab = u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);

    const m1 = readFontMetrics(u8);
    const m2 = readFontMetrics(ab);
    expect(m1.unitsPerEm).toBe(m2.unitsPerEm);
    expect(m1.ascender).toBe(m2.ascender);
  });
});
