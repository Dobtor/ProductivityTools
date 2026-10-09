/**
 * Sprint 18 — imageRowBreakRatio grid search
 *
 * 目的：對 ratio ∈ {0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0} × 全 42 fixture 跑 layoutDocument，
 * 找出全 fixture totalDelta / mismatched / sumAbsDelta 最低的 ratio，作為 R1 預設啟用的依據。
 *
 * 預設從 npm test 跳過（避免每次都跑），由人為 SPRINT18_GRID_SEARCH=1 觸發：
 *
 *   SPRINT18_GRID_SEARCH=1 npx vitest run tests/integration/sprint18_ratio_grid_search.test.ts
 *
 * 輸出：
 *   tests/fixtures/sprint18_ratio_grid_report.json
 *
 * 設計依據：
 *   - 從 Sprint 17 docs/sprint17_pagination_break.md §3.1：ratio=0.3 把 totalDelta -26 翻 +9
 *   - Sprint 17 audit §9 建議：用 grid search 挑最佳 ratio；若無單一 ratio 對所有 fixture 都好
 *     → 改 R1 為 lastRowWasImage=false 才觸發的變體
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const REPORT_PATH = resolve(FIXTURE_ROOT, 'sprint18_ratio_grid_report.json');
const RATIOS = [
  0.0, 0.30, 0.32, 0.34, 0.36, 0.38, 0.40, 0.50, 0.60, 0.70, 0.80, 1.00,
] as const;

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (cat.startsWith('.') || !statSync(catDir).isDirectory()) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) out.push(`${cat}/${f}`);
    }
  }
  return out.sort();
}

function loadDocx(rel: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, rel));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

function countGoldens(rel: string): number {
  const [cat, filename] = rel.split('/');
  const base = filename.replace(/\.docx$/, '');
  const goldenDir = resolve(FIXTURE_ROOT, cat, 'golden');
  if (!existsSync(goldenDir)) return 0;
  return readdirSync(goldenDir).filter(
    (f) =>
      f.endsWith('.png') &&
      !f.includes('_diff') &&
      !f.endsWith('_v14_diff.png') &&
      f.startsWith(`${base}-`),
  ).length;
}

interface CellResult { ours: number; golden: number; delta: number }
interface RatioSummary {
  ratio: number;
  mismatched: number;
  totalDelta: number;
  sumAbsDelta: number;
  fixtureDeltas: Record<string, CellResult>;
}

const enabled = process.env.SPRINT18_GRID_SEARCH === '1';

describe.skipIf(!enabled)('Sprint 18 — imageRowBreakRatio grid search', () => {
  it('跑全 fixture × 全 ratio 矩陣，輸出 JSON 報告', () => {
    const fixtures = listFixtures();
    const summaries: RatioSummary[] = [];

    for (const ratio of RATIOS) {
      const fixtureDeltas: Record<string, CellResult> = {};
      let mismatched = 0;
      let totalDelta = 0;
      let sumAbsDelta = 0;

      for (const rel of fixtures) {
        const doc = new OoxmlParser().parse(loadDocx(rel));
        const layout = layoutDocument(doc.sections, { imageRowBreakRatio: ratio });
        const ours = layout.pages.length;
        const golden = countGoldens(rel);
        const delta = ours - golden;
        fixtureDeltas[rel] = { ours, golden, delta };
        if (delta !== 0) mismatched++;
        totalDelta += delta;
        sumAbsDelta += Math.abs(delta);
      }

      summaries.push({ ratio, mismatched, totalDelta, sumAbsDelta, fixtureDeltas });
    }

    // 排名：最佳 ratio 由 sumAbsDelta 升序、mismatched 升序
    const ranked = [...summaries].sort((a, b) => {
      if (a.sumAbsDelta !== b.sumAbsDelta) return a.sumAbsDelta - b.sumAbsDelta;
      return a.mismatched - b.mismatched;
    });

    const report = {
      generatedAt: new Date().toISOString(),
      ratios: RATIOS,
      totalFixtures: fixtures.length,
      summaries,
      best: ranked[0],
      perRatioSummary: summaries.map((s) => ({
        ratio: s.ratio,
        mismatched: s.mismatched,
        totalDelta: s.totalDelta,
        sumAbsDelta: s.sumAbsDelta,
      })),
    };

    writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));

    // 也 console.log 一份便於 CI / 終端查看
    console.log('\n=== Sprint 18 ratio grid search ===');
    console.log(`fixtures: ${fixtures.length}, ratios: ${RATIOS.length}`);
    console.log('per-ratio:');
    for (const s of summaries) {
      console.log(
        `  ratio=${s.ratio.toFixed(2)}  mismatched=${s.mismatched}/${fixtures.length}`
        + `  totalDelta=${s.totalDelta >= 0 ? '+' : ''}${s.totalDelta}`
        + `  sumAbsDelta=${s.sumAbsDelta}`,
      );
    }
    console.log(
      `best (by sumAbsDelta then mismatched): ratio=${ranked[0].ratio} `
      + `sumAbsDelta=${ranked[0].sumAbsDelta} mismatched=${ranked[0].mismatched}`,
    );
    console.log(`report → ${REPORT_PATH}`);

    expect(report.summaries.length).toBe(RATIOS.length);
  });
});
