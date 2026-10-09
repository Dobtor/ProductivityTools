/**
 * Sprint 255 — Phase 6 Phase 5 (07/08/09) fixture DocProps (core+app+custom) 第十五層 audit
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocProps, DocPropsApp, DocPropsCustom } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_DOCPROPS_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeCustom(c: DocPropsCustom): unknown {
  const names = Array.from(c.keys()).sort();
  return names.map((n) => ({ name: n, value: c.get(n) }));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

function matchAll(o: { docProps: DocProps; appProps: DocPropsApp; customProps: DocPropsCustom },
                  r: { docProps: DocProps; appProps: DocPropsApp; customProps: DocPropsCustom }): boolean {
  const oCore = deepStableStringify(o.docProps);
  const rCore = deepStableStringify(r.docProps);
  const oApp = deepStableStringify(o.appProps);
  const rApp = deepStableStringify(r.appProps);
  const oCustom = deepStableStringify(serializeCustom(o.customProps));
  const rCustom = deepStableStringify(serializeCustom(r.customProps));
  return (oCore === rCore || sha256(oCore) === sha256(rCore))
    && (oApp === rApp || sha256(oApp) === sha256(rApp))
    && (oCustom === rCustom || sha256(oCustom) === sha256(rCustom));
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

describe('Sprint 255 — Phase 6 Phase 5 (07/08/09) fixture DocProps (core+app+custom) preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`DocProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_DOCPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; coreKeys: number; appKeys: number; customCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const match = matchAll(originalDoc, reparseDoc);
      results.push({
        path: f.path, category: f.category,
        coreKeys: Object.keys(originalDoc.docProps).length,
        appKeys: Object.keys(originalDoc.appProps).length,
        customCount: originalDoc.customProps.size, match,
      });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalCore = results.reduce((a, r) => a + r.coreKeys, 0);
    const totalApp = results.reduce((a, r) => a + r.appKeys, 0);
    const totalCustom = results.reduce((a, r) => a + r.customCount, 0);
    const byCategory: Record<string, { total: number; match: number; core: number; app: number; custom: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, core: 0, app: 0, custom: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].core += r.coreKeys;
      byCategory[r.category].app += r.appKeys;
      byCategory[r.category].custom += r.customCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint255] total=${total} match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalCoreKeys=${totalCore} totalAppKeys=${totalApp} totalCustomEntries=${totalCustom}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint255]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) core=${stats.core} app=${stats.app} custom=${stats.custom}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint255]   DIFF ${r.path}: core=${r.coreKeys} app=${r.appKeys} custom=${r.customCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_DOCPROPS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
