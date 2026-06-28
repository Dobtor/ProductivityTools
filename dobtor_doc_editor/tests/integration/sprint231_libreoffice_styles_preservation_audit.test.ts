/**
 * Sprint 231 — Phase 6 LibreOffice 286 fixture StyleMap preservation audit
 *
 * Sprint 230 ChienYi 42 達 42/42 100%（writer `<w:basedOn>` emit + audit
 * empty `{}` normalization）；本 sprint 套用至 288 LibreOffice 邊緣 fixture、
 * 驗 Sprint 230 修法在 edge corpus 成立。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode, StyleEntry, StyleMap } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_STYLE_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function flattenStyleEntry(entry: StyleEntry): Record<string, unknown> {
  const normEmpty = (v: unknown): unknown =>
    v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0 ? undefined : v;
  const out: Record<string, unknown> = {
    pProps: normEmpty(entry.pProps),
    rProps: normEmpty(entry.rProps),
    basedOn: entry.basedOn,
  };
  if (entry.conditional && entry.conditional.size > 0) {
    const condObj: Record<string, unknown> = {};
    for (const [k, v] of entry.conditional) condObj[String(k)] = v;
    out.conditional = condObj;
  }
  return out;
}

function serializeStyleMap(styles: StyleMap): string {
  const ids = Array.from(styles.keys()).sort();
  const entries = ids.map((id) => ({ id, entry: flattenStyleEntry(styles.get(id)!) }));
  return deepStableStringify(entries);
}

function sha256(s: string): string {
  return createHash('sha256').update(s, 'utf8').digest('hex');
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

describe('Sprint 231 — Phase 6 LibreOffice 286 fixture StyleMap preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`StyleMap SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_STYLE_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; styleMatch: boolean; styleCount: number; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, styleMatch: false, styleCount: 0 };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.styleCount = originalDoc.styles.size;
        const origSig = serializeStyleMap(originalDoc.styles);
        const reparseSig = serializeStyleMap(reparseDoc.styles);
        r.styleMatch = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.styleMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalStyles = results.reduce((acc, r) => acc + r.styleCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; styles: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, styles: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].styles += r.styleCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.styleMatch) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint231] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} style=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalStyles=${totalStyles}`);
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint231]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} style ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) styles=${stats.styles}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.styleMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint231] style DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint231]   ${r.path} styleCount=${r.styleCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_STYLE_MATCH_RATE_PCT);
  }, 180000);
});
