/**
 * Sprint 216 — Phase 6 LibreOffice 286 fixture ParagraphProps preservation audit
 *
 * Sprint 215 對 ChienYi 42 production fixture 驗證 ParagraphProps SHA-256
 * 100% byte-identical（3384 paragraphs 全綠）；本 sprint 把同 pattern 套用至
 * Sprint 198 已 parse 成功的 288 個 LibreOffice 邊緣 fixture、量化 writer 在
 * edge case docx 上的段落層級格式保留率。
 *
 * 預期：
 *   - 邊緣 corpus 含 Phase 5 lossy / 故意畸形 case、預期 < 100%
 *   - ≥ 80% 即代表 writer 對主流結構達 byte-identical 段落格式保留
 *   - per-category 量化哪類 docx 容易丟段落格式
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
  ParagraphProps,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

/** 紀律 #2：Sprint 198 baseline = 288 parse-OK fixture（總 290）。 */
const EXPECTED_PARSE_OK_BASELINE = 288;

/** 邊緣 corpus 含 Phase 5 lossy、容寬鬆 80%（ChienYi Sprint 215 達 100%）。 */
const MIN_PPROPS_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeParagraphProps(props: ParagraphProps | undefined): string {
  if (!props) return '{}';
  return deepStableStringify(props);
}

function collectPParagraphPropsSignatures(doc: DocumentNode): string[] {
  const sigs: string[] = [];

  function visitBlock(block: BlockNode) {
    if (block.type === 'paragraph') visitParagraph(block);
    else if (block.type === 'table') visitTable(block);
  }

  function visitParagraph(p: ParagraphNode) {
    sigs.push(serializeParagraphProps(p.props));
  }

  function visitTable(t: TableNode) {
    for (const row of t.rows) {
      for (const cell of row.cells) {
        for (const blk of cell.content) visitBlock(blk);
      }
    }
  }

  for (const sec of doc.sections) {
    for (const blk of sec.body) visitBlock(blk);
  }
  return sigs;
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

describe('Sprint 216 — Phase 6 LibreOffice 286 fixture ParagraphProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`ParagraphProps SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 格式保留率 ≥ ${MIN_PPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      pPropsMatch: boolean;
      paragraphCount: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path,
        category: f.category,
        parseOk: false,
        pipelineOk: false,
        pPropsMatch: false,
        paragraphCount: 0,
      };

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

        const originalSigs = collectPParagraphPropsSignatures(originalDoc);
        const reparseSigs = collectPParagraphPropsSignatures(reparseDoc);
        r.paragraphCount = originalSigs.length;

        if (originalSigs.length === reparseSigs.length) {
          r.pPropsMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
        }
      } catch {
        // pipeline fail
      }

      results.push(r);
    }

    const total = results.length;
    const parseOk = results.filter((r) => r.parseOk).length;
    const pipelineOk = results.filter((r) => r.pipelineOk).length;
    const matchCount = results.filter((r) => r.pPropsMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalParagraphs = results.reduce((acc, r) => acc + r.paragraphCount, 0);

    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; paragraphs: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, paragraphs: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].paragraphs += r.paragraphCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.pPropsMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint216] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `pProps=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalParagraphs=${totalParagraphs}`,
    );
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint216]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} ` +
          `pProps ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) paragraphs=${stats.paragraphs}`,
      );
    }
    const failed = results.filter((r) => r.pipelineOk && !r.pPropsMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint216] pProps DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint216]   ${r.path} paragraphCount=${r.paragraphCount}`);
      }
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_PPROPS_MATCH_RATE_PCT);
  }, 120000); // 120s timeout for 286 fixtures pipeline
});
