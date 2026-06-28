/**
 * Sprint 246 — Phase 6 ChienYi 42 fixture FontTable preservation audit (第十三層)
 *
 * Sprint 147 capture-only / 規畫書 §17.8.3 fontTable.xml；writer Sprint
 * 239/243 已補 footnotes/endnotes/settings part、本 sprint 補 fontTable
 * 之 audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { FontEntry, FontTable } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;
const MIN_FONT_MATCH_RATE_PCT = 90;

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

function serializeFontEntry(f: FontEntry): unknown {
  return { name: f.name, altName: f.altName, charset: f.charset, family: f.family,
    pitch: f.pitch, panose1: f.panose1, sig: normEmpty(f.sig) };
}

function serializeFontTable(ft: FontTable): string {
  const names = Array.from(ft.keys()).sort();
  return deepStableStringify(names.map((n) => serializeFontEntry(ft.get(n)!)));
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

describe('Sprint 246 — Phase 6 ChienYi 42 fixture FontTable preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`FontTable SHA-256 對照：${EXPECTED_FIXTURE_COUNT} fixture 保留率 ≥ ${MIN_FONT_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; fontCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origSig = serializeFontTable(originalDoc.fontTable);
      const reparseSig = serializeFontTable(reparseDoc.fontTable);
      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({ path: f.path, category: f.category, fontCount: originalDoc.fontTable.size, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalFonts = results.reduce((acc, r) => acc + r.fontCount, 0);
    const byCategory: Record<string, { total: number; match: number; fonts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, fonts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].fonts += r.fontCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint246] total=${total} font match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalFonts=${totalFonts}`);
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint246]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) fonts=${stats.fonts}`);
    }
    for (const r of results.filter((x) => !x.match).slice(0, 5)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint246]   DIFF ${r.path}: fontCount=${r.fontCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_FONT_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
