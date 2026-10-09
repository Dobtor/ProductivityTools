/**
 * Sprint 212 — Phase 6 Phase 5 (07/08/09) fixture RunProps preservation audit
 *
 * Sprint 210 + 211 已對 ChienYi 42 production + LibreOffice 288 edge 雙 corpus
 * 驗證 RunProps SHA-256 100% byte-identical（合計 11622 runs）；本 sprint
 * 補上 Phase 5 進階子功能（07_chart=8 + 08_smartart=4 + 09_omml=6 = 18）
 * 的 RunProps 格式級對稱、完整三 corpus 三層矩陣。
 *
 * 預期：
 *   - Phase 5 fixture 多為純結構（chart/smartart/omml），run 數少
 *   - Sprint 209 已驗 text 100%，RunProps 預期亦 100%
 *   - 容寬鬆 90%（fixture 樣本小、寬限度）
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
  RunProps,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;

/** Phase 5 進階子功能 sample 小、容寬鬆 90%。 */
const MIN_RUNPROPS_MATCH_RATE_PCT = 90;

/** RunProps key 順序與 Sprint 210/211 一致。 */
const RUN_PROPS_KEYS: (keyof RunProps)[] = [
  'fontFamily', 'fontFamilyEastAsia', 'fontFamilyHAnsi', 'fontFamilyCs',
  'fontSize', 'bold', 'italic', 'underline', 'strike', 'dstrike',
  'color', 'highlight', 'vertAlign', 'spacing', 'lang',
];

function serializeRunProps(props: RunProps | undefined): string {
  if (!props) return '{}';
  const ordered: Record<string, unknown> = {};
  for (const key of RUN_PROPS_KEYS) {
    if (props[key] !== undefined) {
      ordered[key] = props[key];
    }
  }
  return JSON.stringify(ordered);
}

function collectRunPropsSignatures(doc: DocumentNode): string[] {
  const sigs: string[] = [];

  function visitBlock(block: BlockNode) {
    if (block.type === 'paragraph') visitParagraph(block);
    else if (block.type === 'table') visitTable(block);
  }

  function visitParagraph(p: ParagraphNode) {
    for (const r of p.runs) {
      if (r.type === 'run') {
        sigs.push(serializeRunProps((r as RunNode).props));
      }
    }
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

describe('Sprint 212 — Phase 6 Phase 5 (07/08/09) fixture RunProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`RunProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 格式保留率 ≥ ${MIN_RUNPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      runCount: number;
      runPropsMatch: boolean;
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

      const originalSigs = collectRunPropsSignatures(originalDoc);
      const reparseSigs = collectRunPropsSignatures(reparseDoc);

      const match = originalSigs.length === reparseSigs.length &&
        sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));

      results.push({
        path: f.path,
        category: f.category,
        runCount: originalSigs.length,
        runPropsMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.runPropsMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalRuns = results.reduce((acc, r) => acc + r.runCount, 0);

    const byCategory: Record<string, { total: number; match: number; runs: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, runs: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].runs += r.runCount;
      if (r.runPropsMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint212] total=${total} runProps match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalRuns=${totalRuns}`,
    );
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint212]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) runs=${stats.runs}`,
      );
    }
    for (const r of results.filter((x) => !x.runPropsMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint212]   DIFF ${r.path}: runCount=${r.runCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_RUNPROPS_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
