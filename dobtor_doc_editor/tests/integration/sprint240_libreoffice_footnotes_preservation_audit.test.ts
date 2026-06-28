/**
 * Sprint 240 — Phase 6 LibreOffice 286 fixture Footnotes preservation audit (第十一層)
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { FootnoteContent, BlockNode, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_FOOTNOTE_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function extractBlockText(block: BlockNode): string {
  if (block.type === 'paragraph') {
    return (block.runs || []).map((r) => ('text' in r ? r.text : '')).join('');
  }
  if (block.type === 'table') {
    return (block.rows || []).map((row) =>
      (row.cells || []).map((cell) =>
        (cell.content || []).map(extractBlockText).join('\n'),
      ).join('\t'),
    ).join('\n');
  }
  return '';
}

function serializeFootnote(f: FootnoteContent): unknown {
  return { id: f.id, type: f.type,
    blockCount: f.content.length, text: f.content.map(extractBlockText).join('\n') };
}

function serializeFootnoteMap(footnotes: Map<number, FootnoteContent>): string {
  const ids = Array.from(footnotes.keys()).sort((a, b) => a - b);
  return deepStableStringify(ids.map((id) => serializeFootnote(footnotes.get(id)!)));
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

describe('Sprint 240 — Phase 6 LibreOffice 286 fixture Footnotes preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Footnotes SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_FOOTNOTE_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; footnoteCount: number; endnoteCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, footnoteCount: 0, endnoteCount: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.footnoteCount = originalDoc.footnotes.size;
        r.endnoteCount = originalDoc.endnotes.size;
        const origFnSig = serializeFootnoteMap(originalDoc.footnotes);
        const reparseFnSig = serializeFootnoteMap(reparseDoc.footnotes);
        const origEnSig = serializeFootnoteMap(originalDoc.endnotes);
        const reparseEnSig = serializeFootnoteMap(reparseDoc.endnotes);
        const fnMatch = origFnSig === reparseFnSig || sha256(origFnSig) === sha256(reparseFnSig);
        const enMatch = origEnSig === reparseEnSig || sha256(origEnSig) === sha256(reparseEnSig);
        r.match = fnMatch && enMatch;
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalFn = results.reduce((acc, r) => acc + r.footnoteCount, 0);
    const totalEn = results.reduce((acc, r) => acc + r.endnoteCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; fn: number; en: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, fn: 0, en: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].fn += r.footnoteCount;
      byCategory[r.category].en += r.endnoteCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint240] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} match=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalFn=${totalFn} totalEn=${totalEn}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint240]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} match ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) fn=${stats.fn} en=${stats.en}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint240] DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint240]   ${r.path} fn=${r.footnoteCount} en=${r.endnoteCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_FOOTNOTE_MATCH_RATE_PCT);
  }, 180000);
});
