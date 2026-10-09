/**
 * Sprint 251 — Phase 6 Phase 5 (07/08/09) fixture DocumentWebSettings preservation audit (第十四層)
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentWebSettings } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_WEBSETTINGS_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeWebSettings(w: DocumentWebSettings): unknown {
  return { optimizeForBrowser: w.optimizeForBrowser, allowPNG: w.allowPNG,
    saveSmartTagsAsXml: w.saveSmartTagsAsXml,
    doNotSaveAsSingleFile: w.doNotSaveAsSingleFile, hasDivs: w.hasDivs };
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

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

describe('Sprint 251 — Phase 6 Phase 5 (07/08/09) fixture DocumentWebSettings preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`WebSettings SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_WEBSETTINGS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; keys: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origSig = deepStableStringify(serializeWebSettings(originalDoc.webSettings));
      const reparseSig = deepStableStringify(serializeWebSettings(reparseDoc.webSettings));
      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({ path: f.path, category: f.category, keys: Object.keys(originalDoc.webSettings).length, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalKeys = results.reduce((acc, r) => acc + r.keys, 0);
    const byCategory: Record<string, { total: number; match: number; keys: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, keys: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].keys += r.keys;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint251] total=${total} webSettings match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalKeys=${totalKeys}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint251]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) keys=${stats.keys}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint251]   DIFF ${r.path}: keys=${r.keys}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_WEBSETTINGS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
