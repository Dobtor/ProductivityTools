/**
 * Sprint 261 — Phase 6 Phase 5 (07/08/09) fixture Charts 第十七層 audit
 *
 * 07_chart 8 fixture 是核心圖表樣本（user 真實案例）；08_smartart/09_omml
 * 應無 chart（trivially pass）。閾值 90% 對齊 Phase 5 audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { ChartNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_CHARTS_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeCharts(arr: ChartNode[] | undefined): unknown {
  if (!arr || arr.length === 0) return [];
  return arr.map((ch) => ({
    rId: ch.rId,
    chartType: ch.chartType,
    title: ch.title,
    series: ch.series.map((s) => ({ name: s.name, categories: s.categories, values: s.values })),
  }));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

function matchCharts(o: { charts?: ChartNode[] }, r: { charts?: ChartNode[] }): boolean {
  const oC = deepStableStringify(serializeCharts(o.charts));
  const rC = deepStableStringify(serializeCharts(r.charts));
  return oC === rC || sha256(oC) === sha256(rC);
}

interface Fixture { category: string; path: string; abspath: string; }
function collectFixtures(): Fixture[] {
  const out: Fixture[] = [];
  for (const cat of PHASE5_CATEGORIES) {
    const catPath = join(FIXTURE_ROOT, cat);
    let st;
    try { st = statSync(catPath); } catch { continue; }
    if (!st.isDirectory()) continue;
    for (const f of readdirSync(catPath)) {
      if (!f.endsWith('.docx')) continue;
      out.push({ category: cat, path: `${cat}/${f}`, abspath: join(catPath, f) });
    }
  }
  return out;
}
function loadAsArrayBuffer(abspath: string): ArrayBuffer {
  const buf = readFileSync(abspath);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
}

describe('Sprint 261 — Phase 6 Phase 5 (07/08/09) fixture Charts preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Charts SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_CHARTS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; chartCount: number; seriesCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const match = matchCharts(originalDoc, reparseDoc);
      const charts = originalDoc.charts ?? [];
      const seriesCount = charts.reduce((acc, x) => acc + x.series.length, 0);
      results.push({ path: f.path, category: f.category, chartCount: charts.length, seriesCount, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalCharts = results.reduce((a, r) => a + r.chartCount, 0);
    const totalSeries = results.reduce((a, r) => a + r.seriesCount, 0);
    const byCategory: Record<string, { total: number; match: number; charts: number; series: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, charts: 0, series: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].charts += r.chartCount;
      byCategory[r.category].series += r.seriesCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint261] total=${total} match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalCharts=${totalCharts} totalSeries=${totalSeries}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint261]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) charts=${stats.charts} series=${stats.series}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint261]   DIFF ${r.path}: charts=${r.chartCount} series=${r.seriesCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_CHARTS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
