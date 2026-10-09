/**
 * Sprint 210 — Phase 6 ChienYi fixture RunProps preservation audit
 *
 * Sprint 207-208 驗證 ChienYi + LibreOffice + Phase 5 fixture 文字 SHA-256
 * round-trip 100%；但 **文字格式（RunProps：bold / italic / fontSize / color /
 * underline / strike / highlight 等）未獨立驗證**。
 *
 * 對 ChienYi v1 release 而言：
 *   - 文字保留 100%（Sprint 207） → 文字內容不丟
 *   - 格式保留 ? → 若 bold/italic/size 在 round-trip 後丟失、export 在商用
 *     場景仍不可用（例如監造會議記錄的章節標題若沒粗體就跑版）
 *
 * 本 sprint 對 ChienYi 42 production fixture 各 run 的 RunProps 序列化做
 * SHA-256 fingerprint 對照、量化格式保留率。
 *
 * 預期：
 *   - Sprint 186 writeRPr 設計即為對等 path（schema 順序 + toggle property）
 *   - 預期 100% match
 *   - 若 < 100% 即真實 commercial gap、需後續 sprint fix
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

const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;

/** Phase 6 writeRPr 設計即為對等 path、預期 100%、容寬 95%。 */
const MIN_RUNPROPS_MATCH_RATE_PCT = 95;

/**
 * Serialize RunProps 為 deterministic JSON 字串。
 * Key 順序固定為 RunProps interface 宣告順序（Object.keys 不保證、用顯式 list）。
 */
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

/** 收集 doc 中所有 run 的 RunProps signatures（按出現順序）。 */
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

describe('Sprint 210 — Phase 6 ChienYi fixture RunProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`RunProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture 格式保留率 ≥ ${MIN_RUNPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      runCount: number;
      runPropsMatch: boolean;
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

      const originalSigs = collectRunPropsSignatures(originalDoc);
      const reparseSigs = collectRunPropsSignatures(reparseDoc);

      const r: Result = {
        path: f.path,
        category: f.category,
        runCount: originalSigs.length,
        runPropsMatch: false,
      };

      if (originalSigs.length !== reparseSigs.length) {
        r.runPropsMatch = false;
      } else {
        const origConcat = originalSigs.join('|');
        const reparseConcat = reparseSigs.join('|');
        r.runPropsMatch = sha256(origConcat) === sha256(reparseConcat);
        if (!r.runPropsMatch) {
          // 找出第一筆 mismatch 作為 sample
          for (let i = 0; i < originalSigs.length; i++) {
            if (originalSigs[i] !== reparseSigs[i]) {
              r.mismatchSample = {
                idx: i,
                orig: originalSigs[i].slice(0, 100),
                reparse: reparseSigs[i].slice(0, 100),
              };
              break;
            }
          }
        }
      }

      results.push(r);
    }

    // ── 統計 ─────────────────────────────────────────
    const total = results.length;
    const matchCount = results.filter((r) => r.runPropsMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalRuns = results.reduce((acc, r) => acc + r.runCount, 0);

    // Per-category breakdown
    const byCategory: Record<string, { total: number; match: number; runs: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, runs: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].runs += r.runCount;
      if (r.runPropsMatch) byCategory[r.category].match++;
    }

    // ── 觀測 log ──────────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint210] total=${total} runProps match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalRuns=${totalRuns}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint210]   ${cat.padEnd(18)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) runs=${stats.runs}`,
      );
    }
    for (const r of results.filter((x) => !x.runPropsMatch)) {
      // eslint-disable-next-line no-console
      console.log(
        `[sprint210]   DIFF ${r.path}: runCount=${r.runCount} ` +
          (r.mismatchSample
            ? `firstMismatchIdx=${r.mismatchSample.idx} ` +
              `orig=${r.mismatchSample.orig} reparse=${r.mismatchSample.reparse}`
            : `(runCount diff)`),
      );
    }

    // ── Assertion ──────────────────────────────────────
    expect(matchRate).toBeGreaterThanOrEqual(MIN_RUNPROPS_MATCH_RATE_PCT);
  });
});
