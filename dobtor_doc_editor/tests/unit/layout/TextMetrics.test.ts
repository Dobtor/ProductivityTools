/**
 * TextMetrics — EstimateMetrics 單元測試
 */

import { describe, expect, it } from 'vitest';
import { EstimateMetrics, isCjkChar } from '../../../static/src/core/layout/TextMetrics';

describe('isCjkChar', () => {
  it('CJK 統一漢字回 true', () => {
    expect(isCjkChar('中')).toBe(true);
    expect(isCjkChar('文')).toBe(true);
    expect(isCjkChar('一')).toBe(true);
  });

  it('全形標點 / 假名回 true', () => {
    expect(isCjkChar('，')).toBe(true);
    expect(isCjkChar('「')).toBe(true);
    expect(isCjkChar('あ')).toBe(true);
  });

  it('Latin 字母 / ASCII 標點 / 數字回 false', () => {
    expect(isCjkChar('a')).toBe(false);
    expect(isCjkChar('A')).toBe(false);
    expect(isCjkChar('1')).toBe(false);
    expect(isCjkChar(',')).toBe(false);
    expect(isCjkChar(' ')).toBe(false);
  });

  it('空字串回 false 不 throw', () => {
    expect(isCjkChar('')).toBe(false);
  });
});

describe('EstimateMetrics — measureWidth', () => {
  it('空字串寬 0', () => {
    const m = new EstimateMetrics();
    expect(m.measureWidth('', { fontSize: 12 })).toBe(0);
  });

  it('CJK 字元寬度 ≈ fontSize × 1.15（Sprint 28 empirical）', () => {
    const m = new EstimateMetrics();
    // 「中文」2 字 × 12pt × 1.15 em ≈ 27.6pt（Sprint 28 提高 CJK em 系數對齊 Word）
    expect(m.measureWidth('中文', { fontSize: 12 })).toBeCloseTo(27.6, 0);
  });

  it('Latin 小寫寬度 ≈ fontSize × 0.5', () => {
    const m = new EstimateMetrics();
    // "abcd" 4 字 × 12pt × 0.5 em ≈ 24pt
    expect(m.measureWidth('abcd', { fontSize: 12 })).toBeCloseTo(24, 0);
  });

  it('粗體寬度 ≈ 1.06×', () => {
    const m = new EstimateMetrics();
    const normal = m.measureWidth('中文', { fontSize: 12 });
    const bold = m.measureWidth('中文', { fontSize: 12, bold: true });
    expect(bold).toBeCloseTo(normal * 1.06, 1);
  });

  it('cache 命中：第二次呼叫不重算', () => {
    const m = new EstimateMetrics();
    const w1 = m.measureWidth('hello world', { fontSize: 12 });
    const w2 = m.measureWidth('hello world', { fontSize: 12 });
    expect(w2).toBe(w1);
  });

  it('字距 spacing 累加：每字 +0.5pt', () => {
    const m = new EstimateMetrics();
    const base = m.measureWidth('中文', { fontSize: 12 });
    const withSpacing = m.measureWidth('中文', { fontSize: 12, spacing: 0.5 });
    expect(withSpacing).toBeCloseTo(base + 0.5 * 2, 1);
  });
});

describe('EstimateMetrics — measureLineHeight', () => {
  it('行高 = fontSize × 1.2', () => {
    const m = new EstimateMetrics();
    expect(m.measureLineHeight({ fontSize: 12 })).toBeCloseTo(14.4, 1);
    expect(m.measureLineHeight({ fontSize: 10.5 })).toBeCloseTo(12.6, 1);
  });

  it('未指定 fontSize 用預設 10.5pt', () => {
    const m = new EstimateMetrics();
    expect(m.measureLineHeight({})).toBeCloseTo(12.6, 1);
  });
});
