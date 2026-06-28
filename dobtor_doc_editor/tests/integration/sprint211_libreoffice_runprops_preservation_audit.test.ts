/**
 * Sprint 211 — Phase 6 LibreOffice 286 fixture RunProps preservation audit
 *
 * Sprint 210 對 ChienYi 42 production fixture 驗證 RunProps SHA-256 100%
 * byte-identical（9508 runs 全綠）；本 sprint 把同樣 pattern 套用至 Sprint 198
 * 已 parse 成功的 288 個 LibreOffice 邊緣 fixture、量化 writer 在 edge case
 * docx 上的格式級保留率。
 *
 * 預期：
 *   - 邊緣 corpus 含 Phase 5 lossy / 故意畸形 case、預期 < 100%
 *   - ≥ 80% 即代表 writer 對主流結構達 byte-identical 格式保留
 *   - 若 < 95%、per-category log 可指引後續 audit 改進方向
 *
 * 紀律 #18 scope-down：
 *   - 不修 lossy 行為（OMML/SmartArt/Chart fallback 為設計選擇）
 *   - 純量化，提供 honest visibility
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

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

/** 紀律 #2：avoid magic number。Sprint 198 baseline = 288 parse-OK fixture（總 290）。 */
const EXPECTED_PARSE_OK_BASELINE = 288;

/** 邊緣 corpus 含 Phase 5 lossy、容寬鬆 80% 下限（ChienYi 同類 Sprint 210 達 100%）。 */
const MIN_RUNPROPS_MATCH_RATE_PCT = 80;

/** RunProps 序列化 key 順序固定（避免 Object.keys 不確定性、與 Sprint 210 一致）。 */
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

describe('Sprint 211 — Phase 6 LibreOffice 286 fixture RunProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`RunProps SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 格式保留率 ≥ ${MIN_RUNPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      runPropsMatch: boolean;
      runCount: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path,
        category: f.category,
        parseOk: false,
        pipelineOk: false,
        runPropsMatch: false,
        runCount: 0,
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

        const originalSigs = collectRunPropsSignatures(originalDoc);
        const reparseSigs = collectRunPropsSignatures(reparseDoc);
        r.runCount = originalSigs.length;

        if (originalSigs.length === reparseSigs.length) {
          r.runPropsMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
        }
      } catch {
        // pipeline fail
      }

      results.push(r);
    }

    // ── 統計 ─────────────────────────────────────────
    const total = results.length;
    const parseOk = results.filter((r) => r.parseOk).length;
    const pipelineOk = results.filter((r) => r.pipelineOk).length;
    const matchCount = results.filter((r) => r.runPropsMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalRuns = results.reduce((acc, r) => acc + r.runCount, 0);

    // Per-category breakdown
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; runs: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, runs: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].runs += r.runCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.runPropsMatch) byCategory[r.category].match++;
    }

    // ── 觀測 log ──────────────────────────────────────
    // eslint-disable-next-line no-console
    console.log(
      `[sprint211] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `runProps=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalRuns=${totalRuns}`,
    );
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint211]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} ` +
          `runProps ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) runs=${stats.runs}`,
      );
    }
    // 失敗 fixture sample（取前 10 個）
    const failed = results.filter((r) => r.pipelineOk && !r.runPropsMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint211] runProps DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint211]   ${r.path} runCount=${r.runCount}`);
      }
    }

    // ── Assertion ──────────────────────────────────────
    expect(matchRate).toBeGreaterThanOrEqual(MIN_RUNPROPS_MATCH_RATE_PCT);
  }, 120000); // 120s timeout for 286 fixtures pipeline
});
