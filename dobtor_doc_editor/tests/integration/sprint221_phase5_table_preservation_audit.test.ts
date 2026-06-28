/**
 * Sprint 221 — Phase 6 Phase 5 (07/08/09) fixture TableProps preservation audit
 *
 * Sprint 218+219 ChienYi 42 達 42/42 100% / Sprint 220 LibreOffice 288 達
 * 281/288 (97.6%)；本 sprint 補 Phase 5 18 fixture、完成三 corpus 五層矩陣。
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

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;

/** Phase 5 sample 小、容寬鬆 90%。 */
const MIN_TABLE_MATCH_RATE_PCT = 90;

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

describe('Sprint 221 — Phase 6 Phase 5 (07/08/09) fixture TableProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`TableProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture table-structure 保留率 ≥ ${MIN_TABLE_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      tableCount: number;
      tableMatch: boolean;
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

      const originalSigs = collectTableSignatures(originalDoc);
      const reparseSigs = collectTableSignatures(reparseDoc);
      let match = false;
      if (originalSigs.length === reparseSigs.length) {
        match = originalSigs.length === 0 ||
          sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
      }
      results.push({
        path: f.path,
        category: f.category,
        tableCount: originalSigs.length,
        tableMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.tableMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalTables = results.reduce((acc, r) => acc + r.tableCount, 0);

    const byCategory: Record<string, { total: number; match: number; tables: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, tables: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].tables += r.tableCount;
      if (r.tableMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint221] total=${total} table match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalTables=${totalTables}`,
    );
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint221]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) tables=${stats.tables}`,
      );
    }
    for (const r of results.filter((x) => !x.tableMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint221]   DIFF ${r.path}: tableCount=${r.tableCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_TABLE_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
