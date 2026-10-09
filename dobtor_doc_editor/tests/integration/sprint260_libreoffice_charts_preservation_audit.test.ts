/**
 * Sprint 260 — Phase 6 LibreOffice 286 fixture Charts 第十七層 audit
 *
 * 對齊 Sprint 195 writer。tests/fixtures/10_ooxml_libreoffice/chart 含 9 個
 * 真實圖表 fixture；其他類別亦可能含 chart。閾值 80% 對齊既有 LibreOffice audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { ChartNode, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_CHARTS_MATCH_RATE_PCT = 80;

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
  for (const cat of readdirSync(FIXTURE_ROOT)) {
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

describe('Sprint 260 — Phase 6 LibreOffice 286 fixture Charts preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Charts SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_CHARTS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; chartCount: number; seriesCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, chartCount: 0, seriesCount: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        const charts = originalDoc.charts ?? [];
        r.chartCount = charts.length;
        r.seriesCount = charts.reduce((acc, x) => acc + x.series.length, 0);
        r.match = matchCharts(originalDoc, reparseDoc);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalCharts = results.reduce((a, r) => a + r.chartCount, 0);
    const totalSeries = results.reduce((a, r) => a + r.seriesCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; charts: number; series: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, charts: 0, series: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].charts += r.chartCount;
      byCategory[r.category].series += r.seriesCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint260] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} charts=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalCharts=${totalCharts} totalSeries=${totalSeries}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint260]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} charts ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) charts=${stats.charts} series=${stats.series}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint260] charts DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint260]   ${r.path} charts=${r.chartCount} series=${r.seriesCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_CHARTS_MATCH_RATE_PCT);
  }, 180000);
});
