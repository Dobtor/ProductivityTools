/**
 * Sprint 267 — Phase 2 OOXML 行高公式：resolveOoxmlLineHeight + baselineOffsetPt
 *
 * 規畫書 §Phase 2 對應：行高公式（OOXML §17.3.1.33 w:spacing/w:line + w:lineRule）
 *
 * 三種 rule：
 *   - auto：multiplier (1.0 單行、1.5、2.0 雙行)
 *   - exact：固定 pt 行高、忽略字型 metrics
 *   - atLeast：max(natural, value)
 *
 * 不需字型檔（用 mock FontMetricsResult、驗證純公式邏輯）。
 */
import { describe, expect, it } from 'vitest';

import {
  resolveOoxmlLineHeight,
  baselineOffsetPt,
  lineHeightPt,
  type FontMetricsResult,
} from '../../static/src/core/ooxml/font';

const MOCK_METRICS: FontMetricsResult = {
  unitsPerEm: 2048,        // 常見 OTF 值
  ascender: 1900,          // ≈ 0.928 em
  descender: 500,          // ≈ 0.244 em
  lineGap: 100,            // ≈ 0.049 em
};
// natural lineHeight @ 12pt = (1900+500+100) × 12 / 2048 = 2500 × 12 / 2048 = 14.6484... pt
const NATURAL_AT_12PT = ((1900 + 500 + 100) * 12) / 2048;

describe('Sprint 267 — resolveOoxmlLineHeight 公式（純函式）', () => {
  it('無 lineRule → rule=natural、heightPt = natural', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12);
    expect(r.rule).toBe('natural');
    expect(r.heightPt).toBeCloseTo(NATURAL_AT_12PT, 6);
    expect(r.naturalHeightPt).toBeCloseTo(NATURAL_AT_12PT, 6);
    expect(r.lineValue).toBeUndefined();
  });

  it('auto rule + value=1.0（單行）→ heightPt = natural', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'auto', 1.0);
    expect(r.rule).toBe('auto');
    expect(r.heightPt).toBeCloseTo(NATURAL_AT_12PT, 6);
    expect(r.lineValue).toBe(1.0);
  });

  it('auto rule + value=1.5（1.5 行）→ heightPt = natural × 1.5', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'auto', 1.5);
    expect(r.rule).toBe('auto');
    expect(r.heightPt).toBeCloseTo(NATURAL_AT_12PT * 1.5, 6);
  });

  it('auto rule + value=2.0（雙行）→ heightPt = natural × 2', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'auto', 2.0);
    expect(r.heightPt).toBeCloseTo(NATURAL_AT_12PT * 2, 6);
  });

  it('exact rule → 固定 pt、忽略字型 metrics', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'exact', 20);
    expect(r.rule).toBe('exact');
    expect(r.heightPt).toBe(20);
    expect(r.naturalHeightPt).toBeCloseTo(NATURAL_AT_12PT, 6);

    // exact 小於 natural 也照給（render 責任）
    const small = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'exact', 5);
    expect(small.heightPt).toBe(5);
  });

  it('atLeast rule → max(natural, value)', () => {
    // natural ≈ 14.65、value=10 → 用 natural
    const below = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'atLeast', 10);
    expect(below.rule).toBe('atLeast');
    expect(below.heightPt).toBeCloseTo(NATURAL_AT_12PT, 6);

    // natural ≈ 14.65、value=20 → 用 value
    const above = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'atLeast', 20);
    expect(above.rule).toBe('atLeast');
    expect(above.heightPt).toBe(20);
  });

  it('字級線性 scale：24pt = 12pt × 2', () => {
    const r12 = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'auto', 1.0);
    const r24 = resolveOoxmlLineHeight(MOCK_METRICS, 24, 'auto', 1.0);
    expect(r24.heightPt).toBeCloseTo(r12.heightPt * 2, 6);
  });

  it('lineHeightPt 與 resolveOoxmlLineHeight natural 一致', () => {
    const direct = lineHeightPt(MOCK_METRICS, 12);
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12);
    expect(direct).toBeCloseTo(r.heightPt, 6);
  });
});

describe('Sprint 267 — baselineOffsetPt 公式', () => {
  it('natural rule：基線 = ascent（無 extra gap 平均）', () => {
    const natural = lineHeightPt(MOCK_METRICS, 12);
    const ascentPt = (1900 * 12) / 2048; // ≈ 11.13pt
    const offset = baselineOffsetPt(MOCK_METRICS, 12, natural);
    expect(offset).toBeCloseTo(ascentPt, 6);
  });

  it('exact 大於 natural：extra gap 平均分到 top/bottom（baseline 下移）', () => {
    const ascentPt = (1900 * 12) / 2048;
    const natural = lineHeightPt(MOCK_METRICS, 12);
    const lh = 30; // 大於 natural ~14.65
    const offset = baselineOffsetPt(MOCK_METRICS, 12, lh);
    const expectedExtra = (lh - natural) / 2;
    expect(offset).toBeCloseTo(ascentPt + expectedExtra, 6);
  });

  it('atLeast 小於 natural（natural 勝出）：基線 = ascent', () => {
    const r = resolveOoxmlLineHeight(MOCK_METRICS, 12, 'atLeast', 5);
    const ascentPt = (1900 * 12) / 2048;
    const offset = baselineOffsetPt(MOCK_METRICS, 12, r.heightPt);
    expect(offset).toBeCloseTo(ascentPt, 6);
  });

  it('exact 小於 natural：extra=0、基線仍 = ascent（render 端責任處理 clip）', () => {
    const ascentPt = (1900 * 12) / 2048;
    const offset = baselineOffsetPt(MOCK_METRICS, 12, 5);
    expect(offset).toBeCloseTo(ascentPt, 6);
  });
});
