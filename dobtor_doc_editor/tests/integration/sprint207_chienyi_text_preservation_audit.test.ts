/**
 * Sprint 207 — Phase 6 ChienYi 真實 fixture round-trip 文字內容保留 audit
 *
 * Sprint 206 驗證 42 ChienYi fixture 4-stage round-trip 100%（parse/export/
 * reparse/structure 對稱）；但 **structure 只驗 sections + paragraphs 數對齊、
 * 不驗文字內容**——理論上 writer 可能損壞文字但保留段落數。
 *
 * 規畫書 §6 黃金測試「import(export(doc)) ≅ doc」要求**文字級對稱**、本 sprint
 * 對 Sprint 206 已驗 42 ChienYi fixture 補上**文字 SHA-256 fingerprint 對照**、
 * 量化 round-trip 後文字保留率、明確標示已知 lossy（如表格 cell content 順序、
 * OMML 線性化、註解 fallback）。
 *
 * 量測：
 *   - originalText = extractAllText(originalDoc)
 *   - reparseText  = extractAllText(reparseDoc)
 *   - textMatchRate = matches / total
 *
 * 紀律 #18 scope-down：
 *   - 接受文字保留率 < 100%（lossy fallback 已知）、但須 ≥ 95%
 *   - 接受 whitespace 差異（trim + collapse spaces 比對）
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

/** 紀律 #2：avoid magic number。Sprint 206 baseline = 42 fixture 跨 6 categories。 */
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;

/** 文字內容保留率下限（接受 lossy fallback、但須高過 95% 為 commercial-grade）。 */
const MIN_TEXT_PRESERVATION_RATE_PCT = 95;

/** Normalize 文字以避免無關緊要的 whitespace 差異污染對比。 */
function normalizeText(s: string): string {
  return s
    .replace(/\s+/g, ' ')
    .trim();
}

/** 遞迴展開 block tree → 純文字（含表格 cell content）。 */
function extractBlockText(block: BlockNode): string {
  if (block.type === 'paragraph') {
    return extractParagraphText(block);
  }
  if (block.type === 'table') {
    return extractTableText(block);
  }
  return '';
}

function extractParagraphText(p: ParagraphNode): string {
  const parts: string[] = [];
  for (const r of p.runs) {
    if (r.type === 'run') {
      parts.push((r as RunNode).text ?? '');
    }
    // 其餘 inline node（field/break/tab/image/math）跳過、不計入文字對稱
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

interface ChienYiFixture { category: string; path: string; abspath: string; }

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

describe('Sprint 207 — Phase 6 ChienYi 真實 fixture round-trip 文字內容保留 audit', () => {
  const fixtures = collectChienYiFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`文字 SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture round-trip 後保留率 ≥ ${MIN_TEXT_PRESERVATION_RATE_PCT}%`, () => {
    interface TextResult {
      path: string;
      category: string;
      originalLen: number;
      reparseLen: number;
      originalSha: string;
      reparseSha: string;
      textMatch: boolean;
    }
    const results: TextResult[] = [];

    for (const f of fixtures) {
      // parse → write → reparse pipeline（Sprint 206 已驗 100% 成功率）
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(
        exportedBytes.byteOffset,
        exportedBytes.byteOffset + exportedBytes.byteLength,
      ) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);

      const originalText = extractDocText(originalDoc);
      const reparseText = extractDocText(reparseDoc);
      const originalSha = sha256(originalText);
      const reparseSha = sha256(reparseText);

      results.push({
        path: f.path,
        category: f.category,
        originalLen: originalText.length,
        reparseLen: reparseText.length,
        originalSha,
        reparseSha,
        textMatch: originalSha === reparseSha,
      });
    }

    // ── 統計 ─────────────────────────────────────────
    const total = results.length;
    const textMatchCount = results.filter((r) => r.textMatch).length;
    const textMatchRate = (textMatchCount / total) * 100;

    // Per-category breakdown
    const byCategory: Record<string, { total: number; match: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0 };
      byCategory[r.category].total++;
      if (r.textMatch) byCategory[r.category].match++;
    }

    // ── 觀測 log ──────────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint207] total=${total} textMatch=${textMatchCount}/${total} (${textMatchRate.toFixed(1)}%)`,
    );
    for (const [cat, stats] of Object.entries(byCategory)) {
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint207]   ${cat}: text ${stats.match}/${stats.total} (${pct.toFixed(1)}%)`);
    }
    // Log 文字不對齊的 fixture（截字長度差）
    for (const r of results.filter((x) => !x.textMatch)) {
      const lenDiff = r.reparseLen - r.originalLen;
      const sign = lenDiff >= 0 ? '+' : '';
      // eslint-disable-next-line no-console
      console.log(
        `[sprint207]   DIFF ${r.path}: ` +
          `original=${r.originalLen}chars / reparse=${r.reparseLen}chars (${sign}${lenDiff}) ` +
          `origSha=${r.originalSha.slice(0, 8)} / reparseSha=${r.reparseSha.slice(0, 8)}`,
      );
    }

    // ── Assertion ──────────────────────────────────────
    expect(textMatchRate).toBeGreaterThanOrEqual(MIN_TEXT_PRESERVATION_RATE_PCT);
  });
});
