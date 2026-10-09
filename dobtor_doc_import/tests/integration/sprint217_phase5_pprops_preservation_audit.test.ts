/**
 * Sprint 217 — Phase 6 Phase 5 (07/08/09) fixture ParagraphProps preservation audit
 *
 * Sprint 215 + 216 已對 ChienYi 42 + LibreOffice 288 雙 corpus 驗證
 * ParagraphProps SHA-256 100% byte-identical（合計 5298 paragraphs）；
 * 本 sprint 補上 Phase 5 進階子功能（07_chart=8 + 08_smartart=4 + 09_omml=6
 * = 18）的 ParagraphProps 對等性、完成三 corpus 四層矩陣。
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

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;

/** Phase 5 sample 小、容寬鬆 90%。 */
const MIN_PPROPS_MATCH_RATE_PCT = 90;

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

describe('Sprint 217 — Phase 6 Phase 5 (07/08/09) fixture ParagraphProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`ParagraphProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 格式保留率 ≥ ${MIN_PPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      paragraphCount: number;
      pPropsMatch: boolean;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(
        exportedBytes.byteOffset,
        exportedBytes.byteOffset + exportedBytes.byteLength,
      ) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);

      const originalSigs = collectPParagraphPropsSignatures(originalDoc);
      const reparseSigs = collectPParagraphPropsSignatures(reparseDoc);

      const match = originalSigs.length === reparseSigs.length &&
        sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));

      results.push({
        path: f.path,
        category: f.category,
        paragraphCount: originalSigs.length,
        pPropsMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.pPropsMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalParagraphs = results.reduce((acc, r) => acc + r.paragraphCount, 0);

    const byCategory: Record<string, { total: number; match: number; paragraphs: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, paragraphs: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].paragraphs += r.paragraphCount;
      if (r.pPropsMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint217] total=${total} pProps match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalParagraphs=${totalParagraphs}`,
    );
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint217]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) paragraphs=${stats.paragraphs}`,
      );
    }
    for (const r of results.filter((x) => !x.pPropsMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint217]   DIFF ${r.path}: paragraphCount=${r.paragraphCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_PPROPS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
