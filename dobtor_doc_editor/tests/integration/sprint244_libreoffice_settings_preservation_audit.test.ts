/**
 * Sprint 244 — Phase 6 LibreOffice 286 fixture DocumentSettings preservation audit (第十二層)
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentSettings, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_SETTINGS_MATCH_RATE_PCT = 80;

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
    zoomPercent: s.zoomPercent, defaultTabStop: s.defaultTabStop,
    characterSpacingControl: s.characterSpacingControl,
    autoHyphenation: s.autoHyphenation, evenAndOddHeaders: s.evenAndOddHeaders,
    trackChanges: s.trackChanges,
    proofState: normEmpty(s.proofState),
    footnotePr: normEmpty(s.footnotePr), endnotePr: normEmpty(s.endnotePr),
    compat: s.compat && s.compat.length > 0 ? [...s.compat].sort() : undefined,
  };
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

describe('Sprint 244 — Phase 6 LibreOffice 286 fixture DocumentSettings preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Settings SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_SETTINGS_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; keys: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, keys: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.keys = Object.keys(originalDoc.settings).length;
        const origSig = deepStableStringify(serializeSettings(originalDoc.settings));
        const reparseSig = deepStableStringify(serializeSettings(reparseDoc.settings));
        r.match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalKeys = results.reduce((acc, r) => acc + r.keys, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; keys: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, keys: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].keys += r.keys;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint244] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} settings=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalKeys=${totalKeys}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint244]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} settings ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) keys=${stats.keys}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint244] settings DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint244]   ${r.path} keys=${r.keys}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_SETTINGS_MATCH_RATE_PCT);
  }, 180000);
});
