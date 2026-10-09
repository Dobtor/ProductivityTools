/**
 * Sprint 243 — Phase 6 ChienYi 42 fixture DocumentSettings preservation audit (第十二層)
 *
 * Sprint 146 capture-only / 規畫書 §17.15 settings.xml；writer Sprint 239
 * 已補 footnotes/endnotes part、本 sprint 補 settings.xml part 之 audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentSettings } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;
const MIN_SETTINGS_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function normEmpty(v: unknown): unknown {
  return v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0
    ? undefined : v;
}

function serializeSettings(s: DocumentSettings): unknown {
  return {
    zoomPercent: s.zoomPercent,
    defaultTabStop: s.defaultTabStop,
    characterSpacingControl: s.characterSpacingControl,
    autoHyphenation: s.autoHyphenation,
    evenAndOddHeaders: s.evenAndOddHeaders,
    trackChanges: s.trackChanges,
    proofState: normEmpty(s.proofState),
    footnotePr: normEmpty(s.footnotePr),
    endnotePr: normEmpty(s.endnotePr),
    compat: s.compat && s.compat.length > 0 ? [...s.compat].sort() : undefined,
  };
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

interface Fixture { category: string; path: string; abspath: string; }
function collectFixtures(): Fixture[] {
  const out: Fixture[] = [];
  for (const cat of CHIENYI_CATEGORIES) {
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

describe('Sprint 243 — Phase 6 ChienYi 42 fixture DocumentSettings preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Settings SHA-256 對照：${EXPECTED_FIXTURE_COUNT} fixture 保留率 ≥ ${MIN_SETTINGS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; settingsKeys: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origSig = deepStableStringify(serializeSettings(originalDoc.settings));
      const reparseSig = deepStableStringify(serializeSettings(reparseDoc.settings));
      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      const keys = Object.keys(originalDoc.settings).length;
      results.push({ path: f.path, category: f.category, settingsKeys: keys, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalKeys = results.reduce((acc, r) => acc + r.settingsKeys, 0);
    const byCategory: Record<string, { total: number; match: number; keys: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, keys: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].keys += r.settingsKeys;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint243] total=${total} settings match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalKeys=${totalKeys}`);
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint243]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) keys=${stats.keys}`);
    }
    for (const r of results.filter((x) => !x.match).slice(0, 5)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint243]   DIFF ${r.path}: settingsKeys=${r.settingsKeys}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_SETTINGS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
