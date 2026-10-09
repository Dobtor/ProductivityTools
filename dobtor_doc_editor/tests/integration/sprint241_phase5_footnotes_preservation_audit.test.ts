/**
 * Sprint 241 — Phase 6 Phase 5 (07/08/09) fixture Footnotes preservation audit (第十一層)
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { FootnoteContent, BlockNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_FOOTNOTE_MATCH_RATE_PCT = 90;

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

describe('Sprint 241 — Phase 6 Phase 5 (07/08/09) fixture Footnotes preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Footnotes SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_FOOTNOTE_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; footnoteCount: number; endnoteCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origFnSig = serializeFootnoteMap(originalDoc.footnotes);
      const reparseFnSig = serializeFootnoteMap(reparseDoc.footnotes);
      const origEnSig = serializeFootnoteMap(originalDoc.endnotes);
      const reparseEnSig = serializeFootnoteMap(reparseDoc.endnotes);
      const fnMatch = origFnSig === reparseFnSig || sha256(origFnSig) === sha256(reparseFnSig);
      const enMatch = origEnSig === reparseEnSig || sha256(origEnSig) === sha256(reparseEnSig);
      results.push({ path: f.path, category: f.category,
        footnoteCount: originalDoc.footnotes.size, endnoteCount: originalDoc.endnotes.size,
        match: fnMatch && enMatch });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalFn = results.reduce((acc, r) => acc + r.footnoteCount, 0);
    const totalEn = results.reduce((acc, r) => acc + r.endnoteCount, 0);
    const byCategory: Record<string, { total: number; match: number; fn: number; en: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, fn: 0, en: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].fn += r.footnoteCount;
      byCategory[r.category].en += r.endnoteCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint241] total=${total} match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalFn=${totalFn} totalEn=${totalEn}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint241]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) fn=${stats.fn} en=${stats.en}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint241]   DIFF ${r.path}: fn=${r.footnoteCount} en=${r.endnoteCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_FOOTNOTE_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
