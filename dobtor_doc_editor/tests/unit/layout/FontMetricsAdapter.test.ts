/**
 * FontMetricsAdapter — Sprint 8 / Phase 2
 *
 * 涵蓋：
 *   - registerMetrics 注入後 measureLineHeight 用真實 metrics 算
 *   - 未註冊字型走 fallback estimate
 *   - measureWidth 永遠走 estimate（不受 metrics 影響）
 *   - listFonts / hasFont / clear 行為
 *   - 大小寫不敏感的 family 對應
 */

import { describe, expect, it } from 'vitest';
import { FontMetricsAdapter } from '../../../static/src/core/layout/FontMetricsAdapter';
import type { FontMetricsResult } from '../../../static/src/core/ooxml/font/FontMetrics';
import type { RunProps } from '../../../static/src/core/ooxml/ast/types';

const TIMES_LIKE: FontMetricsResult = {
  unitsPerEm: 2048,
  ascender: 1825,
  descender: 443,
  lineGap: 87,
};

describe('FontMetricsAdapter — measureLineHeight', () => {
  it('已註冊字型用真實 metrics 計算行高', () => {
    const a = new FontMetricsAdapter();
    a.registerMetrics('Times New Roman', TIMES_LIKE);
    const h = a.measureLineHeight({ fontFamily: 'Times New Roman', fontSize: 12 } as RunProps);
    // (1825 + 443 + 87) * 12 / 2048 ≈ 13.78pt
    expect(h).toBeCloseTo(((1825 + 443 + 87) * 12) / 2048, 4);
  });

  it('未註冊字型 fallback estimate (1.2 × fontSize)', () => {
    const a = new FontMetricsAdapter();
    const h = a.measureLineHeight({ fontFamily: 'Unknown Font', fontSize: 12 } as RunProps);
    expect(h).toBeCloseTo(12 * 1.2, 6);
  });

  it('無 fontFamily 也走 estimate', () => {
    const a = new FontMetricsAdapter();
    a.registerMetrics('Times New Roman', TIMES_LIKE);
    const h = a.measureLineHeight({ fontSize: 14 } as RunProps);
    expect(h).toBeCloseTo(14 * 1.2, 6);
  });

  it('family 比對大小寫不敏感', () => {
    const a = new FontMetricsAdapter();
    a.registerMetrics('Times New Roman', TIMES_LIKE);
    const lower = a.measureLineHeight({ fontFamily: 'times new roman', fontSize: 10 } as RunProps);
    const upper = a.measureLineHeight({ fontFamily: 'TIMES NEW ROMAN', fontSize: 10 } as RunProps);
    const exact = a.measureLineHeight({ fontFamily: 'Times New Roman', fontSize: 10 } as RunProps);
    expect(lower).toBeCloseTo(exact, 6);
    expect(upper).toBeCloseTo(exact, 6);
  });

  it('字級放大後行高線性放大', () => {
    const a = new FontMetricsAdapter();
    a.registerMetrics('Test', TIMES_LIKE);
    const h12 = a.measureLineHeight({ fontFamily: 'Test', fontSize: 12 } as RunProps);
    const h24 = a.measureLineHeight({ fontFamily: 'Test', fontSize: 24 } as RunProps);
    expect(h24).toBeCloseTo(h12 * 2, 4);
  });
});

describe('FontMetricsAdapter — measureWidth', () => {
  it('永遠走 estimate（不受 metrics 影響）', () => {
    const a = new FontMetricsAdapter();
    a.registerMetrics('Times New Roman', TIMES_LIKE);
    const w = a.measureWidth('Hello', { fontFamily: 'Times New Roman', fontSize: 12 } as RunProps);
    // EstimateMetrics: H=0.61, e=0.5, l=0.5, l=0.5, o=0.5 → 2.61em × 12pt = 31.32pt
    expect(w).toBeCloseTo(2.61 * 12, 1);
  });

  it('未註冊字型 measureWidth 結果一致', () => {
    const a = new FontMetricsAdapter();
    const w1 = a.measureWidth('Hello', { fontFamily: 'X', fontSize: 12 } as RunProps);
    const w2 = a.measureWidth('Hello', { fontFamily: 'Y', fontSize: 12 } as RunProps);
    expect(w1).toBeCloseTo(w2, 6);
  });
});

describe('FontMetricsAdapter — registry 行為', () => {
  it('listFonts / hasFont / clear', () => {
    const a = new FontMetricsAdapter();
    expect(a.listFonts()).toEqual([]);
    expect(a.hasFont('Arial')).toBe(false);

    a.registerMetrics('Arial', TIMES_LIKE);
    a.registerMetrics('SimSun', TIMES_LIKE);
    expect(a.listFonts().sort()).toEqual(['arial', 'simsun']);
    expect(a.hasFont('Arial')).toBe(true);
    expect(a.hasFont('arial')).toBe(true);

    a.clear();
    expect(a.listFonts()).toEqual([]);
    expect(a.hasFont('Arial')).toBe(false);
  });

  it('重複註冊同 family 會覆蓋', () => {
    const a = new FontMetricsAdapter();
    const m1: FontMetricsResult = { unitsPerEm: 1000, ascender: 800, descender: 200, lineGap: 0 };
    const m2: FontMetricsResult = { unitsPerEm: 1000, ascender: 1000, descender: 0, lineGap: 0 };
    a.registerMetrics('Test', m1);
    const h1 = a.measureLineHeight({ fontFamily: 'Test', fontSize: 10 } as RunProps);
    a.registerMetrics('Test', m2);
    const h2 = a.measureLineHeight({ fontFamily: 'Test', fontSize: 10 } as RunProps);
    expect(h1).toBeCloseTo(10, 4);
    expect(h2).toBeCloseTo(10, 4);
    // 都是 10pt（總高 1000/1000 × 10），但兩者意義不同
  });
});
