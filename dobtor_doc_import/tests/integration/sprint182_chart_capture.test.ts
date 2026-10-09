/**
 * Sprint 182 整合驗證（Phase 5.3 Charts capture-only）
 *
 * 對 07_chart fixture 的真實 .docx 解析後，確認 OoxmlParser 把圖表的型別、
 * 數列、類別與數值快取 capture 進 DocumentNode.charts。
 *
 * 註：07_chart fixture 已排除於 04/08/09 baseline 與 VR（PHASE5_FIXTURE_DIRS），
 * 故本檔以專屬 integration test 覆蓋這批 fixture。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

function parseFixture(name: string) {
  const buf = readFileSync(resolve(__dirname, '../fixtures/07_chart/' + name));
  const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new OoxmlParser().parse(arr as ArrayBuffer);
}

describe('Sprint 182 — 真實 docx Chart capture', () => {
  it('預定進度表(通河)：barChart、2 數列、類別軸', () => {
    const doc = parseFixture('預定進度表(通河).docx');
    expect(doc.charts).toBeDefined();
    expect(doc.charts).toHaveLength(1);

    const chart = doc.charts![0];
    expect(chart.chartType).toBe('barChart');
    expect(chart.series).toHaveLength(2);
    expect(chart.series[0].categories[0]).toBe('新設箱涵工程');
    expect(chart.series[0].categories).toContain('拆除既有設施物');
  });

  it('磺港溪C-A自主檢查統計1130311：bar3DChart、1 數列', () => {
    const doc = parseFixture('磺港溪C-A自主檢查統計1130311.docx');
    expect(doc.charts).toHaveLength(1);
    const chart = doc.charts![0];
    expect(chart.chartType).toBe('bar3DChart');
    expect(chart.series).toHaveLength(1);
    expect(chart.series[0].categories[0]).toBe('測量放樣');
  });

  it('土方統計(浤欣)1140829：barChart、類別與數值快取等長', () => {
    const doc = parseFixture('土方統計(浤欣)1140829.docx');
    const chart = doc.charts![0];
    expect(chart.chartType).toBe('barChart');
    const s = chart.series[0];
    // 類別軸與數值依 ptCount 對位、長度一致
    expect(s.categories.length).toBe(s.values.length);
    expect(s.values.length).toBeGreaterThan(0);
  });

  it('北投監造及工程標進度-113.06.15：barChart、6 數列', () => {
    const doc = parseFixture('北投監造及工程標進度-113.06.15(任泰北投).docx');
    const chart = doc.charts![0];
    expect(chart.series).toHaveLength(6);
  });

  it('圖表數值皆為 number 或 null（numCache 正確解析）', () => {
    const doc = parseFixture('磺港溪C-A自主檢查統計1130527.docx');
    for (const s of doc.charts![0].series) {
      for (const v of s.values) {
        expect(v === null || typeof v === 'number').toBe(true);
      }
    }
  });
});
