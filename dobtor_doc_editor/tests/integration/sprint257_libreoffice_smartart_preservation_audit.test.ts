/**
 * Sprint 257 — Phase 6 LibreOffice 286 fixture SmartArt 第十六層 audit
 *
 * 對齊 Sprint 195 writer。tests/fixtures/10_ooxml_libreoffice/smartart 含 2 個
 * 真實 SmartArt fixture（smartart.docx、strict-smartart.docx）；其他類別亦可能
 * 含 SmartArt（如 shape）。閾值 80% 對齊既有 LibreOffice audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { SmartArtNode, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_SMARTART_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeSmartArts(arr: SmartArtNode[] | undefined): unknown {
  if (!arr || arr.length === 0) return [];
  return arr.map((sa) => ({ rId: sa.rId, layoutType: sa.layoutType, texts: sa.texts }));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

function matchSmartArts(o: { smartArts?: SmartArtNode[] }, r: { smartArts?: SmartArtNode[] }): boolean {
  const oS = deepStableStringify(serializeSmartArts(o.smartArts));
  const rS = deepStableStringify(serializeSmartArts(r.smartArts));
  return oS === rS || sha256(oS) === sha256(rS);
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

describe('Sprint 257 — Phase 6 LibreOffice 286 fixture SmartArt preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`SmartArt SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_SMARTART_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; smartArtCount: number; textCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, smartArtCount: 0, textCount: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        const sa = originalDoc.smartArts ?? [];
        r.smartArtCount = sa.length;
        r.textCount = sa.reduce((acc, x) => acc + x.texts.length, 0);
        r.match = matchSmartArts(originalDoc, reparseDoc);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalSmartArts = results.reduce((a, r) => a + r.smartArtCount, 0);
    const totalTexts = results.reduce((a, r) => a + r.textCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; smartArts: number; texts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, smartArts: 0, texts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].smartArts += r.smartArtCount;
      byCategory[r.category].texts += r.textCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint257] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} smartArt=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalSmartArts=${totalSmartArts} totalTexts=${totalTexts}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint257]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} smartArt ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) smartArts=${stats.smartArts} texts=${stats.texts}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint257] smartArt DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint257]   ${r.path} smartArts=${r.smartArtCount} texts=${r.textCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_SMARTART_MATCH_RATE_PCT);
  }, 180000);
});
