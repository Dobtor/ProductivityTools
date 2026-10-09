/**
 * Sprint 247 — Phase 6 LibreOffice 286 fixture FontTable preservation audit (第十三層)
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { FontEntry, FontTable, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_FONT_MATCH_RATE_PCT = 80;

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

describe('Sprint 247 — Phase 6 LibreOffice 286 fixture FontTable preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`FontTable SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_FONT_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; fontCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, fontCount: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.fontCount = originalDoc.fontTable.size;
        const origSig = serializeFontTable(originalDoc.fontTable);
        const reparseSig = serializeFontTable(reparseDoc.fontTable);
        r.match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalFonts = results.reduce((acc, r) => acc + r.fontCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; fonts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, fonts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].fonts += r.fontCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint247] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} font=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalFonts=${totalFonts}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint247]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} font ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) fonts=${stats.fonts}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint247] font DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint247]   ${r.path} fontCount=${r.fontCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_FONT_MATCH_RATE_PCT);
  }, 180000);
});
