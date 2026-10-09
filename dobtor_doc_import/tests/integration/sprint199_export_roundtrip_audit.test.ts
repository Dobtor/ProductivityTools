/**
 * Sprint 199 — Phase 6 export round-trip 廣域穩定性 audit
 *
 * 對 Sprint 198 已 parse 成功的 288 個 LibreOffice 邊緣 fixture 跑：
 *   parser.parse(originalBytes) → writer.write(doc) → parser.parse(exportedBytes)
 *
 * 量化：
 *   - export success rate（writer 不丟例外完成）
 *   - re-parse success rate（exported bytes 可被 parser 重讀）
 *   - 結構保留率（re-parse 後 sections/paragraphs 數與原 doc 一致）
 *
 * 規畫書 §6 黃金測試「import(export(doc)) ≅ doc」對 42 個 controlled fixture
 * 已驗（Sprint 185-196 round-trip 測試），本 sprint 把該標準推到 LibreOffice
 * 廣域邊緣 corpus、揭示 export 對真實世界 docx 多樣性的相容性。
 *
 * 紀律 #18 scope-down：
 *   - 接受結構保留率 < 100%（OMML / SmartArt / Chart 部件 lossy export 是已知 scope-down）
 *   - 接受 export fail（極少數 edge case OOXML 結構超出 writer 覆蓋）、但必須 throw Error 非 silent corruption
 *   - 接受 re-parse fail（exported bytes 若不完整應 throw 而非崩潰）
 *
 * 失敗的意義：export success rate 或 re-parse success rate < 90%、或結構保留率
 *           大幅下降時，表 OoxmlWriter 對廣域 docx 有 regression。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

/** 紀律 #2：avoid magic number。Sprint 198 量測為 288 parse-OK 檔（總 290）。 */
const EXPECTED_PARSE_OK_BASELINE = 288;

/** 紀律 #2：export round-trip success rate baseline（容寬鬆下限 90%）。 */
const MIN_EXPORT_SUCCESS_RATE_PCT = 90;
const MIN_REPARSE_SUCCESS_RATE_PCT = 90;
/** 結構保留率（成功 round-trip 後 sections/paragraphs 數與原 doc 一致）下限。 */
const MIN_STRUCTURE_PRESERVATION_PCT = 80;

function collectFixtures(): { category: string; path: string; abspath: string }[] {
  const out: { category: string; path: string; abspath: string }[] = [];
  const cats = readdirSync(FIXTURE_ROOT);
  for (const cat of cats) {
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
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
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

describe('Sprint 199 — Phase 6 export round-trip 廣域穩定性 audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`export round-trip 對 ${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 穩定`, () => {
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

    const exportSuccessRate = (exportOk / parseOk) * 100;
    const reparseSuccessRate = (reparseOk / exportOk) * 100;
    const structurePreservationRate = (structureOk / reparseOk) * 100;

    // ── per-category 分布 ────────────────────────────────────
    const byCategory = new Map<string, { total: number; export: number; reparse: number; structure: number }>();
    for (const r of results) {
      let entry = byCategory.get(r.category);
      if (!entry) {
        entry = { total: 0, export: 0, reparse: 0, structure: 0 };
        byCategory.set(r.category, entry);
      }
      entry.total++;
      if (r.exportOk) entry.export++;
      if (r.reparseOk) entry.reparse++;
      if (r.structureOk) entry.structure++;
    }

    // ── 失敗 stage 分布 ──────────────────────────────────────
    const failsByStage = new Map<string, number>();
    for (const r of results) {
      if (r.stage) {
        failsByStage.set(r.stage, (failsByStage.get(r.stage) ?? 0) + 1);
      }
    }

    // ── 印出 audit 報告 ──────────────────────────────────────
    console.log('\n=== Sprint 199 — Export round-trip 廣域穩定性 audit ===');
    console.log(`Total fixtures:         ${total}`);
    console.log(`Stage 1 parse OK:       ${parseOk}/${total} (${(parseOk / total * 100).toFixed(1)}%)`);
    console.log(`Stage 2 export OK:      ${exportOk}/${parseOk} (${exportSuccessRate.toFixed(1)}% of parse-OK)`);
    console.log(`Stage 3 re-parse OK:    ${reparseOk}/${exportOk} (${reparseSuccessRate.toFixed(1)}% of export-OK)`);
    console.log(`Stage 4 structure OK:   ${structureOk}/${reparseOk} (${structurePreservationRate.toFixed(1)}% of reparse-OK)`);

    console.log('\nFailure breakdown by stage:');
    for (const [stage, count] of failsByStage) {
      console.log(`  ${stage.padEnd(10)} ${count}`);
    }

    console.log('\nPer-category export+reparse pass:');
    for (const [cat, s] of [...byCategory.entries()].sort()) {
      const expPct = ((s.export / s.total) * 100).toFixed(0);
      const reparsePct = ((s.reparse / s.total) * 100).toFixed(0);
      const structPct = ((s.structure / s.total) * 100).toFixed(0);
      console.log(
        `  ${cat.padEnd(15)} total=${String(s.total).padStart(3)}  ` +
        `export=${expPct.padStart(3)}%  reparse=${reparsePct.padStart(3)}%  structure=${structPct.padStart(3)}%`,
      );
    }

    // 列出 export 失敗 samples
    const exportFails = results.filter((r) => r.parseOk && !r.exportOk);
    if (exportFails.length > 0) {
      console.log(`\nExport failure samples (first ${Math.min(5, exportFails.length)}):`);
      for (const r of exportFails.slice(0, 5)) {
        console.log(`  [${r.category}] ${r.path}`);
        console.log(`     → ${r.err}`);
      }
    }

    // 列出 re-parse 失敗 samples
    const reparseFails = results.filter((r) => r.exportOk && !r.reparseOk);
    if (reparseFails.length > 0) {
      console.log(`\nRe-parse failure samples (first ${Math.min(5, reparseFails.length)}):`);
      for (const r of reparseFails.slice(0, 5)) {
        console.log(`  [${r.category}] ${r.path}`);
        console.log(`     → ${r.err}`);
      }
    }

    // 列出結構不對稱 samples
    const structureFails = results.filter((r) => r.reparseOk && !r.structureOk);
    if (structureFails.length > 0) {
      console.log(`\nStructure drift samples (first ${Math.min(5, structureFails.length)}):`);
      for (const r of structureFails.slice(0, 5)) {
        console.log(
          `  [${r.category}] ${r.path}: sections ${r.originalSections}→${r.reparseSections}, ` +
          `paragraphs ${r.originalParagraphs}→${r.reparseParagraphs}`,
        );
      }
    }
    console.log('=== end audit ===\n');

    // ── 斷言 ──────────────────────────────────────────────────
    expect(parseOk).toBeGreaterThanOrEqual(EXPECTED_PARSE_OK_BASELINE);
    expect(exportSuccessRate).toBeGreaterThanOrEqual(MIN_EXPORT_SUCCESS_RATE_PCT);
    expect(reparseSuccessRate).toBeGreaterThanOrEqual(MIN_REPARSE_SUCCESS_RATE_PCT);
    expect(structurePreservationRate).toBeGreaterThanOrEqual(MIN_STRUCTURE_PRESERVATION_PCT);
  }, /* timeout：parse+export+reparse 串行 288 檔 */ 300000);
});
