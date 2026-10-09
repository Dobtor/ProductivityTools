/**
 * Sprint 268 — Phase 2 opentype.js 完整字型 metrics + per-glyph advanceWidth
 *
 * 規畫書 §Phase 2 對應：opentype.js 完整字型 metrics
 *   - typo/win/hhea 三組 ascender/descender 都 capture
 *   - fsSelection italic/bold + macStyle italic/bold + weightClass/widthClass
 *   - hhea advanceWidthMax
 *   - 新增 readOpentypeAdvances（per-glyph advances + total，pt）
 *
 * 系統字型依賴：DejaVuSans + LiberationSerif；找不到任一時 skip 相關子測試。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import {
  readFontMetrics,
  readOpentypeAdvances,
} from '../../static/src/core/ooxml/font';

const DEJAVU = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const LIBERATION = '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf';
const HAS_DEJAVU = existsSync(DEJAVU);
const HAS_LIBERATION = existsSync(LIBERATION);

describe.skipIf(!HAS_DEJAVU)('Sprint 268 — readFontMetrics 擴充欄位（DejaVuSans）', () => {
  it('typo ascender/descender/lineGap 存在', () => {
    const bytes = readFileSync(DEJAVU);
    const metrics = readFontMetrics(bytes);
    expect(metrics.typoAscender).toBeGreaterThan(0);
    expect(metrics.typoDescender).toBeGreaterThan(0);
    expect(metrics.typoLineGap).toBeGreaterThanOrEqual(0);
  });

  it('Windows ascent/descent 存在', () => {
    const bytes = readFileSync(DEJAVU);
    const metrics = readFontMetrics(bytes);
    expect(metrics.winAscent).toBeGreaterThan(0);
    expect(metrics.winDescent).toBeGreaterThan(0);
  });

  it('italic/bold flags + weightClass', () => {
    const bytes = readFileSync(DEJAVU);
    const metrics = readFontMetrics(bytes);
    // DejaVuSans Regular：非 italic / 非 bold / weight 400
    expect(metrics.italic).toBe(false);
    expect(metrics.bold).toBe(false);
    expect(metrics.weightClass).toBeGreaterThanOrEqual(300);
    expect(metrics.weightClass).toBeLessThanOrEqual(500);
  });

  it('advanceWidthMax 存在', () => {
    const bytes = readFileSync(DEJAVU);
    const metrics = readFontMetrics(bytes);
    expect(metrics.advanceWidthMax).toBeGreaterThan(0);
    expect(metrics.advanceWidthMax).toBeLessThanOrEqual(metrics.unitsPerEm * 4);
  });

  it('macStyle 與 OS/2 fsSelection italic/bold 一致', () => {
    const bytes = readFileSync(DEJAVU);
    const metrics = readFontMetrics(bytes);
    if (metrics.italic !== undefined && metrics.macStyleItalic !== undefined) {
      expect(metrics.macStyleItalic).toBe(metrics.italic);
    }
    if (metrics.bold !== undefined && metrics.macStyleBold !== undefined) {
      expect(metrics.macStyleBold).toBe(metrics.bold);
    }
  });
});

describe.skipIf(!HAS_DEJAVU)('Sprint 268 — readOpentypeAdvances（per-glyph advance widths）', () => {
  it('文字 advances 長度 = glyph 數 = 字元數（Latin、無 ligature）', () => {
    const bytes = readFileSync(DEJAVU);
    const r = readOpentypeAdvances(bytes, 'Hello', 12);
    expect(r.glyphCount).toBe(5);
    expect(r.advancesPt.length).toBe(5);
    expect(r.advancesPt.every((a) => a > 0)).toBe(true);
  });

  it('總寬度 widthPt > 0 且大致等於 advances 加總（kern 略誤差）', () => {
    const bytes = readFileSync(DEJAVU);
    const r = readOpentypeAdvances(bytes, 'Hello', 12);
    const sum = r.advancesPt.reduce((a, b) => a + b, 0);
    // getAdvanceWidth 套 kerning、可能略低於 sum；容差 5%
    expect(r.widthPt).toBeGreaterThan(0);
    expect(Math.abs(r.widthPt - sum)).toBeLessThan(sum * 0.05);
  });

  it('sizePt 線性 scale：24pt 寬度 ~12pt × 2', () => {
    const bytes = readFileSync(DEJAVU);
    const r12 = readOpentypeAdvances(bytes, 'Hello', 12);
    const r24 = readOpentypeAdvances(bytes, 'Hello', 24);
    expect(r24.widthPt).toBeCloseTo(r12.widthPt * 2, 4);
  });

  it('空字串 → widthPt=0 / advancesPt=[] / glyphCount=0', () => {
    const bytes = readFileSync(DEJAVU);
    const r = readOpentypeAdvances(bytes, '', 12);
    expect(r.glyphCount).toBe(0);
    expect(r.advancesPt.length).toBe(0);
    expect(r.widthPt).toBe(0);
  });
});

describe.skipIf(!HAS_LIBERATION)('Sprint 268 — readFontMetrics（LiberationSerif、第二字型驗證）', () => {
  it('完整 metrics 欄位都能讀（typo / win / italic / weight / advanceWidthMax）', () => {
    const bytes = readFileSync(LIBERATION);
    const metrics = readFontMetrics(bytes);
    expect(metrics.unitsPerEm).toBeGreaterThan(0);
    expect(metrics.ascender).toBeGreaterThan(0);
    expect(metrics.descender).toBeGreaterThan(0);
    expect(metrics.typoAscender).toBeGreaterThan(0);
    expect(metrics.winAscent).toBeGreaterThan(0);
    expect(metrics.italic).toBe(false);
    expect(metrics.weightClass).toBeGreaterThan(0);
  });
});
