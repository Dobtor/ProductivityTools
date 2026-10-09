/**
 * Sprint 272 — Phase 6 LibreOffice 286 fixture theme1.xml raw byte-level audit
 *
 * 對齊 Sprint 271 raw preserve；閾值 80% retention 對齊既有 LibreOffice audit。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { unzipSync, strFromU8 } from 'fflate';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_BYTE_RETENTION_PCT = 80;

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
function extractThemeXml(docxBytes: Uint8Array): string | null {
  try {
    const parts = unzipSync(docxBytes);
    const theme = parts['word/theme/theme1.xml'];
    if (theme === undefined) return null;
    return strFromU8(theme);
  } catch { return null; }
}

describe('Sprint 272 — Phase 6 LibreOffice 286 fixture theme1.xml raw byte-level audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`raw byte retention：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 平均 ≥ ${MIN_BYTE_RETENTION_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; hasTheme: boolean; originalBytes: number; exportedBytes: number; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, hasTheme: false, originalBytes: 0, exportedBytes: 0 };
      const origRaw = readFileSync(f.abspath);
      const origThemeXml = extractThemeXml(origRaw);
      r.hasTheme = origThemeXml !== null;
      r.originalBytes = origThemeXml !== null ? Buffer.byteLength(origThemeXml, 'utf8') : 0;
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const exportedDocx = writer.write(originalDoc);
        const exportedThemeXml = extractThemeXml(exportedDocx);
        r.exportedBytes = exportedThemeXml !== null ? Buffer.byteLength(exportedThemeXml, 'utf8') : 0;
        r.pipelineOk = true;
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const hasThemeCount = results.filter((x) => x.hasTheme).length;
    const totalOrig = results.reduce((a, r) => a + r.originalBytes, 0);
    const totalExp = results.reduce((a, r) => a + r.exportedBytes, 0);
    const retention = totalOrig > 0 ? (totalExp / totalOrig) * 100 : 0;
    // eslint-disable-next-line no-console
    console.log(`[sprint272] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} hasTheme=${hasThemeCount}/${total} bytes orig=${totalOrig} exp=${totalExp} retention=${retention.toFixed(1)}%`);
    // 顯示 retention 過低 (< 50%) 的 fixture（揭發 outlier）
    const lowRetention = results
      .filter((r) => r.hasTheme && r.originalBytes > 0 && (r.exportedBytes / r.originalBytes) < 0.5)
      .slice(0, 10);
    if (lowRetention.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint272] low retention sample (first 10):`);
      for (const r of lowRetention) {
        // eslint-disable-next-line no-console
        console.log(`[sprint272]   ${r.path}: orig=${r.originalBytes}B exp=${r.exportedBytes}B (${((r.exportedBytes / r.originalBytes) * 100).toFixed(1)}%)`);
      }
    }
    expect(retention).toBeGreaterThanOrEqual(MIN_BYTE_RETENTION_PCT);
  }, 180000);
});
