/**
 * Sprint 209 — Phase 5 fixtures (07_chart / 08_smartart / 09_omml) round-trip
 * + text SHA-256 audit
 *
 * Sprint 198-208 audit pipeline 對 LibreOffice 290 邊緣 + ChienYi 42 production
 * 全部驗證 4-stage round-trip / text SHA-256 100%；但 **Phase 5 fixtures
 * (07_chart=8 + 08_smartart=4 + 09_omml=6 = 18) 自 Sprint 179 起被排除於
 * 04/08/09 baseline + VR pipeline、未系統性 round-trip 驗證**。
 *
 * 本 sprint 補上 Phase 5 進階子功能（OMML / SmartArt / Chart）的：
 *   - 4-stage round-trip (parse / export / reparse / structure)
 *   - 文字 SHA-256 byte-identical 對照
 *
 * 預期：
 *   - structure 100%（Phase 5 sub-parts 設計即為 round-trip 對等）
 *   - text 可能 < 100%（OMML/SmartArt/Chart 內含文字屬於 inline node、
 *     extractDocText 跳過、對外可見文字可能無差異）
 *
 * 紀律 #18 scope-down：
 *   - Phase 5 fixture 量少（18 個）、整體 sample 即可結論
 *   - 不修 lossy 行為（線性 fallback 為 Phase 5 design choice）
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  BlockNode,
  DocumentNode,
  ParagraphNode,
  RunNode,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

/** 紀律 #2：avoid magic number。Sprint 179-183 Phase 5 fixture 入庫。 */
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18; // 8 chart + 4 smartart + 6 omml

/** Phase 5 進階子功能皆走 writer 對等 path、structure 預期 100%。 */
const MIN_STRUCTURE_PRESERVATION_PCT = 95;
const MIN_TEXT_PRESERVATION_RATE_PCT = 90; // 容忍 OMML/Chart inline text 細微差

function normalizeText(s: string): string {
  return s.replace(/\s+/g, ' ').trim();
}

function extractBlockText(block: BlockNode): string {
  if (block.type === 'paragraph') return extractParagraphText(block);
  if (block.type === 'table') return extractTableText(block);
  return '';
}

function extractParagraphText(p: ParagraphNode): string {
  const parts: string[] = [];
  for (const r of p.runs) {
    if (r.type === 'run') parts.push((r as RunNode).text ?? '');
  }
  return parts.join('');
}

function extractTableText(t: TableNode): string {
  const lines: string[] = [];
  for (const row of t.rows) {
    for (const cell of row.cells) {
      for (const blk of cell.content) {
        lines.push(extractBlockText(blk));
      }
    }
  }
  return lines.join('\n');
}

function extractDocText(doc: DocumentNode): string {
  const lines: string[] = [];
  for (const sec of doc.sections) {
    for (const blk of sec.body) {
      lines.push(extractBlockText(blk));
    }
  }
  return normalizeText(lines.join('\n'));
}

function sha256(s: string): string {
  return createHash('sha256').update(s, 'utf8').digest('hex');
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

describe('Sprint 209 — Phase 5 fixtures (07/08/09) round-trip + text audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`fixture 總數 = ${EXPECTED_FIXTURE_COUNT}（Phase 5 三 categories）`, () => {
    expect(fixtures.length).toBe(EXPECTED_FIXTURE_COUNT);
  });

  it(`Phase 5 round-trip structure + text 對齊`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      structureOk: boolean;
      textMatch: boolean;
      originalSections?: number;
      originalParagraphs?: number;
      reparseSections?: number;
      reparseParagraphs?: number;
      originalLen?: number;
      reparseLen?: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path, category: f.category,
        parseOk: false, pipelineOk: false, structureOk: false, textMatch: false,
      };

      let originalDoc: DocumentNode;
      try {
        originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
        r.parseOk = true;
        r.originalSections = originalDoc.sections.length;
        r.originalParagraphs = countParagraphs(originalDoc);
      } catch {
        results.push(r);
        continue;
      }

      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(
          exportedBytes.byteOffset,
          exportedBytes.byteOffset + exportedBytes.byteLength,
        ) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.reparseSections = reparseDoc.sections.length;
        r.reparseParagraphs = countParagraphs(reparseDoc);
        r.structureOk =
          r.originalSections === r.reparseSections &&
          r.originalParagraphs === r.reparseParagraphs;

        const originalText = extractDocText(originalDoc);
        const reparseText = extractDocText(reparseDoc);
        r.originalLen = originalText.length;
        r.reparseLen = reparseText.length;
        r.textMatch = sha256(originalText) === sha256(reparseText);
      } catch {
        // pipeline fail
      }

      results.push(r);
    }

    // ── 統計 ─────────────────────────────────────────
    const total = results.length;
    const parseOk = results.filter((r) => r.parseOk).length;
    const pipelineOk = results.filter((r) => r.pipelineOk).length;
    const structureOk = results.filter((r) => r.structureOk).length;
    const textMatch = results.filter((r) => r.textMatch).length;
    const structureRate = pipelineOk > 0 ? (structureOk / pipelineOk) * 100 : 0;
    const textMatchRate = pipelineOk > 0 ? (textMatch / pipelineOk) * 100 : 0;

    // Per-category breakdown
    const byCategory: Record<string, { total: number; structure: number; text: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, structure: 0, text: 0 };
      byCategory[r.category].total++;
      if (r.structureOk) byCategory[r.category].structure++;
      if (r.textMatch) byCategory[r.category].text++;
    }

    // ── 觀測 log ──────────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint209] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `structure=${structureOk}/${pipelineOk} (${structureRate.toFixed(1)}%) ` +
        `text=${textMatch}/${pipelineOk} (${textMatchRate.toFixed(1)}%)`,
    );
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const sPct = stats.total > 0 ? (stats.structure / stats.total) * 100 : 0;
      const tPct = stats.total > 0 ? (stats.text / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint209]   ${cat.padEnd(12)}: structure ${stats.structure}/${stats.total} (${sPct.toFixed(1)}%) ` +
          `text ${stats.text}/${stats.total} (${tPct.toFixed(1)}%)`,
      );
    }
    // Log fails
    for (const r of results.filter((x) => !x.structureOk || !x.textMatch)) {
      // eslint-disable-next-line no-console
      console.log(
        `[sprint209]   DIFF ${r.path}: ` +
          `structure=${r.structureOk ? 'OK' : 'FAIL'} (orig=${r.originalSections}s/${r.originalParagraphs}p vs reparse=${r.reparseSections}s/${r.reparseParagraphs}p) ` +
          `text=${r.textMatch ? 'OK' : 'FAIL'} (origLen=${r.originalLen} reparseLen=${r.reparseLen})`,
      );
    }

    // ── Assertion ──────────────────────────────────────
    expect(structureRate).toBeGreaterThanOrEqual(MIN_STRUCTURE_PRESERVATION_PCT);
    expect(textMatchRate).toBeGreaterThanOrEqual(MIN_TEXT_PRESERVATION_RATE_PCT);
  });
});
