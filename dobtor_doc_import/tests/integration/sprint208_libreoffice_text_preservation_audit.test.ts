/**
 * Sprint 208 — Phase 6 LibreOffice 288 fixture round-trip 文字內容保留 audit
 *
 * Sprint 207 對 ChienYi 42 production fixture 驗證文字 SHA-256 100% byte-identical；
 * 本 sprint 把同樣 pattern 套用至 **Sprint 198 已 parse 成功的 288 個 LibreOffice
 * 邊緣 fixture**、量化 writer 在 edge case docx 上的文字保留率。
 *
 * 預期：
 *   - 整體保留率 < 100%（含 Phase 5 子功能 lossy fallback）
 *   - 但 ≥ 80%（writer 對主流結構應 byte-identical 保留）
 *   - per-category 可量化哪類 docx 容易丟文字、指引後續改進方向
 *
 * 紀律 #18 scope-down：
 *   - 不修 lossy 行為（OMML/SmartArt/Chart fallback 為設計選擇）
 *   - 只量化、提供 honest visibility
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

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

/** 紀律 #2：avoid magic number。Sprint 198 baseline = 288 parse-OK fixture（總 290）。 */
const EXPECTED_PARSE_OK_BASELINE = 288;

/** 邊緣 corpus 含 Phase 5 lossy、容寬鬆 80% 下限。 */
const MIN_TEXT_PRESERVATION_RATE_PCT = 80;

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

describe('Sprint 208 — Phase 6 LibreOffice 288 fixture round-trip 文字內容保留 audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`文字 SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 文字保留率 ≥ ${MIN_TEXT_PRESERVATION_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      textMatch: boolean;
      originalLen?: number;
      reparseLen?: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, textMatch: false };

      let originalDoc: DocumentNode;
      try {
        originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
        r.parseOk = true;
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
    const textMatch = results.filter((r) => r.textMatch).length;
    const textMatchRate = pipelineOk > 0 ? (textMatch / pipelineOk) * 100 : 0;

    // Per-category breakdown
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0 };
      byCategory[r.category].total++;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.textMatch) byCategory[r.category].match++;
    }

    // ── 觀測 log ──────────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint208] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `text=${textMatch}/${pipelineOk} (${textMatchRate.toFixed(1)}%)`,
    );
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint208]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} ` +
          `text ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%)`,
      );
    }

    // ── Assertion ──────────────────────────────────────
    expect(textMatchRate).toBeGreaterThanOrEqual(MIN_TEXT_PRESERVATION_RATE_PCT);
  }, 120000); // 120s timeout for 288 fixtures pipeline
});
