/**
 * Sprint 258 — Phase 6 Phase 5 (07/08/09) fixture SmartArt 第十六層 audit
 *
 * 08_smartart 4 fixture 是核心 SmartArt 樣本（user 真實案例 + 系統介紹）；
 * 07_chart/09_omml 應無 SmartArt（trivially pass）。閾值 90% 對齊 Phase 5 audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { SmartArtNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_SMARTART_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeSmartArts(arr: SmartArtNode[] | undefined): unknown {
  if (!arr || arr.length === 0) return [];
  return arr.map((sa) => ({ rId: sa.rId, layoutType: sa.layoutType, texts: sa.texts }));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

function matchSmartArts(o: { smartArts?: SmartArtNode[] }, r: { smartArts?: SmartArtNode[] }): boolean {
  const oS = deepStableStringify(serializeSmartArts(o.smartArts));
  const rS = deepStableStringify(serializeSmartArts(r.smartArts));
  return oS === rS || sha256(oS) === sha256(rS);
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

describe('Sprint 258 — Phase 6 Phase 5 (07/08/09) fixture SmartArt preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`SmartArt SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_SMARTART_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; smartArtCount: number; textCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const match = matchSmartArts(originalDoc, reparseDoc);
      const sa = originalDoc.smartArts ?? [];
      const textCount = sa.reduce((acc, x) => acc + x.texts.length, 0);
      results.push({ path: f.path, category: f.category, smartArtCount: sa.length, textCount, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalSmartArts = results.reduce((a, r) => a + r.smartArtCount, 0);
    const totalTexts = results.reduce((a, r) => a + r.textCount, 0);
    const byCategory: Record<string, { total: number; match: number; smartArts: number; texts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, smartArts: 0, texts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].smartArts += r.smartArtCount;
      byCategory[r.category].texts += r.textCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint258] total=${total} match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalSmartArts=${totalSmartArts} totalTexts=${totalTexts}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint258]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) smartArts=${stats.smartArts} texts=${stats.texts}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint258]   DIFF ${r.path}: smartArts=${r.smartArtCount} texts=${r.textCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_SMARTART_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
