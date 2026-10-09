/**
 * Sprint 206 — Phase 6 ChienYi 真實 fixture export round-trip 廣域 audit
 *
 * Sprint 199 對 290 LibreOffice 邊緣 fixture 跑 round-trip（288/290 = 99.3%
 * parse / export 100% / reparse 100% / structure 100%（Sprint 200 後））；
 * **未對 ChienYi 監造真實 workflow 42 fixture 系統性驗證 round-trip**。
 *
 * 本 sprint 把 Sprint 199 pattern 套用至 01-06 ChienYi categories（42 fixture）、
 * 驗證 production-grade docx：監造會議記錄、週報、估驗表、安全衛生抽查、
 * 工程表單 等 ChienYi workflow 文件可端到端 round-trip 通過 Phase 6 writer。
 *
 * 對 ChienYi v1 release 的意義：
 *   - LibreOffice 290 fixture 驗證**廣域 docx 相容**
 *   - ChienYi 42 fixture 驗證**真實 workflow 對稱**
 *   - 兩者互補完整 export 端到端 commercial-grade 驗證
 *
 * 排除集：
 *   - 07_chart / 08_smartart / 09_omml：Phase 5 fixture、lossy export 已知
 *   - 10_ooxml_libreoffice：Sprint 199 已驗
 *   - 11_perf_synthetic_large：Sprint 202 已驗（writer 自生）
 *
 * 紀律 #18 scope-down：
 *   - 接受結構保留率 < 100%（部分 ChienYi fixture 含 SmartArt/OMML lossy export）
 *   - 接受 export fail（極少數 edge case）、但必須 throw Error 非 silent corruption
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

/** 紀律 #2：avoid magic number。ChienYi 真實 fixture 6 categories（01-06）。 */
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];

/** Sprint 201 perf baseline 確認 = 42 fixture 跨 6 categories。 */
const EXPECTED_FIXTURE_COUNT = 42;

/** 真實 workflow 標準較廣域邊緣高、本 sprint 立 95% 下限。 */
const MIN_PARSE_SUCCESS_RATE_PCT = 95;
const MIN_EXPORT_SUCCESS_RATE_PCT = 95;
const MIN_REPARSE_SUCCESS_RATE_PCT = 95;
/** 結構保留率（含可能的 SmartArt/Chart lossy；ChienYi fixture 多含表格、保守 80% 下限）。 */
const MIN_STRUCTURE_PRESERVATION_PCT = 80;

interface ChienYiFixture {
  category: string;
  path: string;
  abspath: string;
}

function collectChienYiFixtures(): ChienYiFixture[] {
  const out: ChienYiFixture[] = [];
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

function countParagraphs(doc: DocumentNode): number {
  let n = 0;
  for (const sec of doc.sections) {
    for (const block of sec.body) {
      if (block.type === 'paragraph') n++;
    }
  }
  return n;
}

describe('Sprint 206 — Phase 6 ChienYi 真實 fixture export round-trip audit', () => {
  const fixtures = collectChienYiFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`fixture 總數 = ${EXPECTED_FIXTURE_COUNT}（跨 6 ChienYi categories）`, () => {
    expect(fixtures.length).toBe(EXPECTED_FIXTURE_COUNT);
  });

  it(`export round-trip 對 ${EXPECTED_FIXTURE_COUNT} ChienYi fixture 穩定`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      exportOk: boolean;
      reparseOk: boolean;
      structureOk: boolean;
      originalSections?: number;
      originalParagraphs?: number;
      reparseSections?: number;
      reparseParagraphs?: number;
      err?: string;
      stage?: 'parse' | 'export' | 'reparse';
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path,
        category: f.category,
        parseOk: false,
        exportOk: false,
        reparseOk: false,
        structureOk: false,
      };

      // Stage 1: 原始 parse
      let doc: DocumentNode;
      try {
        doc = parser.parse(loadAsArrayBuffer(f.abspath));
        r.parseOk = true;
        r.originalSections = doc.sections.length;
        r.originalParagraphs = countParagraphs(doc);
      } catch (e) {
        r.stage = 'parse';
        r.err = e instanceof Error ? e.message.slice(0, 150) : String(e).slice(0, 150);
        results.push(r);
        continue;
      }

      // Stage 2: export
      let exportedBytes: Uint8Array;
      try {
        exportedBytes = writer.write(doc);
        r.exportOk = true;
      } catch (e) {
        r.stage = 'export';
        r.err = e instanceof Error ? e.message.slice(0, 150) : String(e).slice(0, 150);
        results.push(r);
        continue;
      }

      // Stage 3: re-parse exported bytes
      let reparseDoc: DocumentNode;
      try {
        const ab = exportedBytes.buffer.slice(
          exportedBytes.byteOffset,
          exportedBytes.byteOffset + exportedBytes.byteLength,
        ) as ArrayBuffer;
        reparseDoc = parser.parse(ab);
        r.reparseOk = true;
        r.reparseSections = reparseDoc.sections.length;
        r.reparseParagraphs = countParagraphs(reparseDoc);
      } catch (e) {
        r.stage = 'reparse';
        r.err = e instanceof Error ? e.message.slice(0, 150) : String(e).slice(0, 150);
        results.push(r);
        continue;
      }

      // Stage 4: 結構保留檢查（sections + paragraphs 數一致）
      r.structureOk =
        r.originalSections === r.reparseSections &&
        r.originalParagraphs === r.reparseParagraphs;

      results.push(r);
    }

    // ── 統計 ──────────────────────────────────────────────────
    const total = results.length;
    const parseOk = results.filter((r) => r.parseOk).length;
    const exportOk = results.filter((r) => r.exportOk).length;
    const reparseOk = results.filter((r) => r.reparseOk).length;
    const structureOk = results.filter((r) => r.structureOk).length;

    const parseRate = (parseOk / total) * 100;
    const exportSuccessRate = parseOk > 0 ? (exportOk / parseOk) * 100 : 0;
    const reparseSuccessRate = exportOk > 0 ? (reparseOk / exportOk) * 100 : 0;
    const structurePreservationRate = reparseOk > 0 ? (structureOk / reparseOk) * 100 : 0;

    // Per-category breakdown
    const byCategory: Record<string, { total: number; structureOk: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, structureOk: 0 };
      byCategory[r.category].total++;
      if (r.structureOk) byCategory[r.category].structureOk++;
    }

    // ── 觀測 log（不為 assertion）────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint206] total=${total} parse=${parseOk}/${total} (${parseRate.toFixed(1)}%) ` +
        `export=${exportOk}/${parseOk} (${exportSuccessRate.toFixed(1)}%) ` +
        `reparse=${reparseOk}/${exportOk} (${reparseSuccessRate.toFixed(1)}%) ` +
        `structure=${structureOk}/${reparseOk} (${structurePreservationRate.toFixed(1)}%)`,
    );
    for (const [cat, stats] of Object.entries(byCategory)) {
      const pct = stats.total > 0 ? (stats.structureOk / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint206]   ${cat}: structure ${stats.structureOk}/${stats.total} (${pct.toFixed(1)}%)`);
    }
    // Log fails
    for (const r of results.filter((x) => !x.structureOk)) {
      // eslint-disable-next-line no-console
      console.log(
        `[sprint206]   FAIL ${r.path}: stage=${r.stage ?? 'structure'} ` +
          `orig=(${r.originalSections}s/${r.originalParagraphs}p) ` +
          `reparse=(${r.reparseSections}s/${r.reparseParagraphs}p) ` +
          `err=${r.err ?? '-'}`,
      );
    }

    // ── Assertion（4 個 rate threshold）──────────────────────────
    expect(parseRate).toBeGreaterThanOrEqual(MIN_PARSE_SUCCESS_RATE_PCT);
    expect(exportSuccessRate).toBeGreaterThanOrEqual(MIN_EXPORT_SUCCESS_RATE_PCT);
    expect(reparseSuccessRate).toBeGreaterThanOrEqual(MIN_REPARSE_SUCCESS_RATE_PCT);
    expect(structurePreservationRate).toBeGreaterThanOrEqual(MIN_STRUCTURE_PRESERVATION_PCT);
  });
});
