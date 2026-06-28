/**
 * Sprint 218 — Phase 6 ChienYi fixture TableProps preservation audit
 *
 * Sprint 210-212 完成 RunProps 三 corpus 矩陣 + Sprint 215-217 完成
 * ParagraphProps 三 corpus 矩陣（合計 11645 runs + 5335 paragraphs 全
 * byte-identical）；但 **table-level 格式（TableProps：grid / styleId /
 * tblPr / RowProps：tblHeader/cantSplit/height / CellProps：vAlign/
 * gridSpan/vMerge/textDirection/borders/shading/margins）未獨立驗證**。
 *
 * 對 ChienYi v1 release 商用層次而言：
 *   - 段落 / run 格式 100%（Sprint 215-217 / 210-212）→ 文字 + 段落格式不丟
 *   - **表格層級格式保留 ?** → 若 cell vAlign / vMerge / 表頭重複設定
 *     在 round-trip 後丟失、估驗表 / 通報單表格視覺仍會跑掉
 *
 * 本 sprint 對 ChienYi 42 production fixture 各 table 的 **TableNode
 * deep-stable JSON SHA-256 fingerprint** 對照、量化表格層級格式保留率。
 *
 * Serialize 策略：
 *   - 每 table 序列化 = grid + styleId + props + rows[].props +
 *     cells[].{gridCol,gridSpan,rowSpan,isContinuation,props}
 *   - **不含 cell content**（content 文字 + 段落格式已分別由 Sprint
 *     207/210/215 驗證、此處只專注 table-structure 層級）
 *   - 用 `deepStableStringify` 處理 nested objects（CellBorders / shading
 *     / margins / cellMargins 等）
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

const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;

/**
 * Phase 6 writeTable + BorderConflictResolver 設計為對等 path。
 * Sprint 218 首次量測揭發 cell border width 0.5pt → 0.75pt 漂移（10/42
 * fixture）、Sprint 219 修法（BorderConflictResolver 改為迭代收斂到 fixed
 * point）後達 42/42 全 100%。閾值恢復為 95%（迭代法保有安全餘裕）。
 */
const MIN_TABLE_MATCH_RATE_PCT = 95;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

/**
 * Serialize TableNode structural signature（不含 cell content）。
 *
 * 涵蓋：grid + styleId + table.props + row.props + cell.{gridCol,gridSpan,
 * rowSpan,isContinuation,props}；text 與 paragraph format 已由 Sprint 207/215
 * 等獨立驗證、本 sprint 專注 table-structure。
 */
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

/** 遞迴收集 doc 中所有 table 的 structural signatures（按出現順序、含巢狀表格）。 */
function collectTableSignatures(doc: DocumentNode): string[] {
  const sigs: string[] = [];

  function visitBlock(block: BlockNode) {
    if (block.type === 'table') visitTable(block);
  }

  function visitTable(t: TableNode) {
    sigs.push(serializeTable(t));
    // 巢狀表格：cell.content 內可能再含 TableNode
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

describe('Sprint 218 — Phase 6 ChienYi fixture TableProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`TableProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture table-structure 保留率 ≥ ${MIN_TABLE_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      tableCount: number;
      tableMatch: boolean;
      mismatchSample?: { idx: number; orig: string; reparse: string };
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

      const r: Result = {
        path: f.path,
        category: f.category,
        tableCount: originalSigs.length,
        tableMatch: false,
      };

      if (originalSigs.length !== reparseSigs.length) {
        r.tableMatch = false;
      } else if (originalSigs.length === 0) {
        // 無 table 的 fixture 視為 trivially match（如純文字 docx）
        r.tableMatch = true;
      } else {
        r.tableMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
        if (!r.tableMatch) {
          for (let i = 0; i < originalSigs.length; i++) {
            if (originalSigs[i] !== reparseSigs[i]) {
              // 找出第一個 diff 字元位置、輸出 diff context 而非全頭部
              let diffPos = 0;
              const a = originalSigs[i];
              const b = reparseSigs[i];
              const maxLen = Math.min(a.length, b.length);
              while (diffPos < maxLen && a[diffPos] === b[diffPos]) diffPos++;
              const ctxStart = Math.max(0, diffPos - 30);
              const ctxEnd = diffPos + 120;
              r.mismatchSample = {
                idx: i,
                orig: `...${a.slice(ctxStart, ctxEnd)}...`,
                reparse: `...${b.slice(ctxStart, ctxEnd)}...`,
              };
              break;
            }
          }
        }
      }

      results.push(r);
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
      `[sprint218] total=${total} table match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalTables=${totalTables}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint218]   ${cat.padEnd(18)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) tables=${stats.tables}`,
      );
    }
    for (const r of results.filter((x) => !x.tableMatch)) {
      // eslint-disable-next-line no-console
      console.log(
        `[sprint218]   DIFF ${r.path}: tableCount=${r.tableCount} ` +
          (r.mismatchSample
            ? `firstMismatchIdx=${r.mismatchSample.idx}\n        orig=${r.mismatchSample.orig}\n        reparse=${r.mismatchSample.reparse}`
            : `(tableCount diff)`),
      );
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_TABLE_MATCH_RATE_PCT);
  });
});
