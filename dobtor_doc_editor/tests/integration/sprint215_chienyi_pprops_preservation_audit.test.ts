/**
 * Sprint 215 — Phase 6 ChienYi fixture ParagraphProps preservation audit
 *
 * Sprint 210-212 完成 RunProps SHA-256 三 corpus 三層矩陣（合計 11645 runs
 * 全 byte-identical）；但 **paragraph-level 格式（ParagraphProps：alignment /
 * indent / spacing / borders / shading / numId+ilvl / tabs / textAlignment /
 * framePr 等）未獨立驗證**。
 *
 * 對 ChienYi v1 release 商用層次而言：
 *   - run-level 格式保留 100%（Sprint 210） → 字型 / 顏色 / 粗體 不丟
 *   - **段落層級格式保留 ?** → 若段落對齊 / 縮排 / 間距 在 round-trip 後
 *     丟失、export 排版視覺仍會跑掉（如標題置中變左對齊、條列縮排消失）
 *
 * 本 sprint 對 ChienYi 42 production fixture 各段落的 **ParagraphProps
 * deep-stable JSON SHA-256 fingerprint** 對照、量化段落格式保留率。
 *
 * Serialize 策略（紀律 #2）：
 *   - ParagraphProps 含 5 個 nested object（indent/spacing/borders/shading/framePr）+
 *     1 個 nested array（tabs[]）、Object.keys 順序不可靠
 *   - 用 `deepStableStringify` 遞迴排序所有 object keys、保證對等
 *
 * 預期：Phase 6 Sprint 187 `writePPr` 設計即為對等 path（schema 順序 +
 *      OOXML §17.3 對等屬性）、預期 100%。
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

const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;

/** Phase 6 writePPr 設計為對等 path、預期 100%、容寬 95%。 */
const MIN_PPROPS_MATCH_RATE_PCT = 95;

/**
 * Deep stable stringify：遞迴排序所有 object keys、array 按原順序保留、primitives 直序列化。
 * 確保 ParagraphProps 跨進程 / 跨平台 deterministic、不受 Object.keys 插入順序影響。
 */
function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return '[' + value.map(deepStableStringify).join(',') + ']';
  }
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeParagraphProps(props: ParagraphProps | undefined): string {
  if (!props) return '{}';
  return deepStableStringify(props);
}

/** 收集 doc 中所有 paragraph 的 ParagraphProps signatures（按出現順序）。 */
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

describe('Sprint 215 — Phase 6 ChienYi fixture ParagraphProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`ParagraphProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture 格式保留率 ≥ ${MIN_PPROPS_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      paragraphCount: number;
      pPropsMatch: boolean;
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

      const originalSigs = collectPParagraphPropsSignatures(originalDoc);
      const reparseSigs = collectPParagraphPropsSignatures(reparseDoc);

      const r: Result = {
        path: f.path,
        category: f.category,
        paragraphCount: originalSigs.length,
        pPropsMatch: false,
      };

      if (originalSigs.length !== reparseSigs.length) {
        r.pPropsMatch = false;
      } else {
        r.pPropsMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
        if (!r.pPropsMatch) {
          for (let i = 0; i < originalSigs.length; i++) {
            if (originalSigs[i] !== reparseSigs[i]) {
              r.mismatchSample = {
                idx: i,
                orig: originalSigs[i].slice(0, 150),
                reparse: reparseSigs[i].slice(0, 150),
              };
              break;
            }
          }
        }
      }

      results.push(r);
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
      `[sprint215] total=${total} pProps match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalParagraphs=${totalParagraphs}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint215]   ${cat.padEnd(18)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) paragraphs=${stats.paragraphs}`,
      );
    }
    for (const r of results.filter((x) => !x.pPropsMatch)) {
      // eslint-disable-next-line no-console
      console.log(
        `[sprint215]   DIFF ${r.path}: paragraphCount=${r.paragraphCount} ` +
          (r.mismatchSample
            ? `firstMismatchIdx=${r.mismatchSample.idx}\n        orig=${r.mismatchSample.orig}\n        reparse=${r.mismatchSample.reparse}`
            : `(paragraphCount diff)`),
      );
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_PPROPS_MATCH_RATE_PCT);
  });
});
