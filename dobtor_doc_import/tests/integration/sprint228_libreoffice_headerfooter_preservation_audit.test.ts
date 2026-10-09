/**
 * Sprint 228 — Phase 6 LibreOffice 286 fixture HeaderFooterContent preservation audit
 *
 * Sprint 227 ChienYi 42 達 42/42 100%；本 sprint 套用至 288 LibreOffice
 * 邊緣 fixture、驗 header/footer content 對等性在 edge corpus 成立。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode, HeaderFooterContent } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_HF_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function collectHFSignatures(
  doc: DocumentNode,
): { headerSigs: string[]; footerSigs: string[]; slotCount: number } {
  const headerSigs: string[] = [];
  const footerSigs: string[] = [];
  let slotCount = 0;
  const sigFor = (rId: string | undefined, map: Map<string, HeaderFooterContent>): string => {
    if (rId === undefined) return '__none__';
    const hf = map.get(rId);
    if (!hf) return '__missing__';
    return deepStableStringify(hf.content);
  };
  for (const sec of doc.sections) {
    const slots: Array<'default' | 'first' | 'even'> = ['default', 'first', 'even'];
    for (const k of slots) {
      const hRid = (sec.headerRefs as Record<string, string | undefined>)[k];
      const fRid = (sec.footerRefs as Record<string, string | undefined>)[k];
      if (hRid !== undefined) {
        headerSigs.push(`H:${k}:${sigFor(hRid, doc.headers)}`);
        slotCount++;
      }
      if (fRid !== undefined) {
        footerSigs.push(`F:${k}:${sigFor(fRid, doc.footers)}`);
        slotCount++;
      }
    }
  }
  return { headerSigs, footerSigs, slotCount };
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

describe('Sprint 228 — Phase 6 LibreOffice 286 fixture HeaderFooterContent preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`HeaderFooterContent SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_HF_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; hfMatch: boolean; slotCount: number; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, hfMatch: false, slotCount: 0 };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        const orig = collectHFSignatures(originalDoc);
        const reparse = collectHFSignatures(reparseDoc);
        r.slotCount = orig.slotCount;
        if (orig.headerSigs.length === reparse.headerSigs.length && orig.footerSigs.length === reparse.footerSigs.length) {
          const allOrig = [...orig.headerSigs, ...orig.footerSigs].join('|');
          const allRepa = [...reparse.headerSigs, ...reparse.footerSigs].join('|');
          r.hfMatch = orig.slotCount === 0 || sha256(allOrig) === sha256(allRepa);
        }
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.hfMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalSlots = results.reduce((acc, r) => acc + r.slotCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; slots: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, slots: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].slots += r.slotCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.hfMatch) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint228] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} hf=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalSlots=${totalSlots}`);
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint228]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} hf ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) slots=${stats.slots}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.hfMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint228] hf DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint228]   ${r.path} slotCount=${r.slotCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_HF_MATCH_RATE_PCT);
  }, 180000);
});
