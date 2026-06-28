/**
 * Sprint 220 — Phase 6 LibreOffice 286 fixture TableProps preservation audit
 *
 * Sprint 218 對 ChienYi 42 揭發 cell border width drift / Sprint 219 修
 * BorderConflictResolver 迭代收斂、ChienYi 42 達 100%；本 sprint 把 audit
 * 套用至 Sprint 198 已 parse 成功的 288 個 LibreOffice 邊緣 fixture、驗
 * Sprint 219 修法在 edge case 也成立。
 *
 * 預期：
 *   - Sprint 219 修法為一般化、應對所有 wide-cell + vertical neighbor
 *     iteration order 問題、適用 ChienYi 與 LibreOffice
 *   - 邊緣 corpus 含 Phase 5 lossy / 故意畸形 case、預期 ≥ 80%
 *   - 若 ≥ 95% 即代表 Sprint 219 修法亦對邊緣 corpus 達 commercial-grade
 *     table-structure 對稱
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
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

const EXPECTED_PARSE_OK_BASELINE = 288;

/** 邊緣 corpus、寬鬆 80%（ChienYi Sprint 218+219 修後達 100%）。 */
const MIN_TABLE_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeTable(t: TableNode): string {
  const sig = {
    grid: t.grid,
    styleId: t.styleId,
    props: t.props,
    rows: t.rows.map((r) => ({
      props: r.props,
      cells: r.cells.map((c) => ({
        gridCol: c.gridCol,
        gridSpan: c.gridSpan,
        rowSpan: c.rowSpan,
        isContinuation: c.isContinuation,
        props: c.props,
      })),
    })),
  };
  return deepStableStringify(sig);
}

function collectTableSignatures(doc: DocumentNode): string[] {
  const sigs: string[] = [];
  function visitBlock(block: BlockNode) {
    if (block.type === 'table') visitTable(block);
  }
  function visitTable(t: TableNode) {
    sigs.push(serializeTable(t));
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

describe('Sprint 220 — Phase 6 LibreOffice 286 fixture TableProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`TableProps SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture table-structure 保留率 ≥ ${MIN_TABLE_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      tableMatch: boolean;
      tableCount: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path,
        category: f.category,
        parseOk: false,
        pipelineOk: false,
        tableMatch: false,
        tableCount: 0,
      };
      let originalDoc: DocumentNode;
      try {
        originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
        r.parseOk = true;
      } catch { results.push(r); continue; }
      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(
          exportedBytes.byteOffset,
          exportedBytes.byteOffset + exportedBytes.byteLength,
        ) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;

        const originalSigs = collectTableSignatures(originalDoc);
        const reparseSigs = collectTableSignatures(reparseDoc);
        r.tableCount = originalSigs.length;

        if (originalSigs.length === reparseSigs.length) {
          if (originalSigs.length === 0) {
            r.tableMatch = true; // 無 table fixture trivially match
          } else {
            r.tableMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
          }
        }
      } catch {
        // pipeline fail
      }
      results.push(r);
    }

    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.tableMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalTables = results.reduce((acc, r) => acc + r.tableCount, 0);

    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; tables: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, tables: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].tables += r.tableCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.tableMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint220] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `table=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalTables=${totalTables}`,
    );
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint220]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} ` +
          `table ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) tables=${stats.tables}`,
      );
    }
    const failed = results.filter((r) => r.pipelineOk && !r.tableMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint220] table DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint220]   ${r.path} tableCount=${r.tableCount}`);
      }
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_TABLE_MATCH_RATE_PCT);
  }, 120000);
});
