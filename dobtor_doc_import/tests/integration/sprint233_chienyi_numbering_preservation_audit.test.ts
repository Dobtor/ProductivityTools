/**
 * Sprint 233 — Phase 6 ChienYi fixture NumberingMap preservation audit（第九層）
 *
 * 三 corpus 八層矩陣完備後、擴展第九層 NumberingMap（document.numbering map）。
 * numbering.xml 定義所有列表 / 編號樣式、被 ParagraphNode.numId+ilvl 引用；
 * 若 numbering round-trip drift、ref 解析會錯位、列表編號 / bullet 視覺
 * 失準（如 1.2.3 → ●、●●●● → a.b.c）。
 *
 * Serialize 策略：
 *   - NumberingMap = Map<numId, AbstractNumbering>；numId 排序後串接
 *   - AbstractNumbering 含 abstractNumId + levels[9] array
 *   - 每個 NumberingLevel 含 numFmt / text / start / lvlRestart / indent /
 *     runProps / pProps / isLegal
 *   - 用 deepStableStringify 遞迴序列化所有 props nested objects
 *
 * 預期：Phase 6 Sprint 187 numbering.xml writer 對等 path 設計、預期 ≥ 90%。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  DocumentNode,
  AbstractNumbering,
  NumberingMap,
} from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

const CHIENYI_CATEGORIES = [
  '01_simple',
  '02_std_table',
  '03_complex_table',
  '04_with_image',
  '05_header_footer',
  '06_template',
];
const EXPECTED_FIXTURE_COUNT = 42;

/** Phase 6 numbering writer 對等 path 設計、容寬鬆 90%。 */
const MIN_NUMBERING_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

/** 規範化：只比對 levels[]、忽略 abstractNumId 欄位；每個 level 內的
 * runProps / pProps / indent 空 `{}` 規範化為 undefined（同 Sprint 230
 * root cause #5b 模式：writer 對 empty props 不 emit、reparse 為
 * undefined、語意對等但 SHA-256 drift）。
 *
 * OoxmlWriter 設計（Sprint 191 design comment）：「用 numId 直接當
 * abstractNumId（保證唯一、避免多個 numId 共用 abstractNumId 但 levels
 * 不同被 Map 覆蓋）；parser 不靠 abstractNumId 解析 levels」。故
 * abstractNumId 在 round-trip 後可能變為 numId、為 acceptable lossy
 * normalization、不影響 numbering reference 解析正確性。 */
function serializeAbstractNumbering(num: AbstractNumbering): unknown {
  const normEmpty = (v: unknown): unknown =>
    v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0 ? undefined : v;
  const normLevel = (lvl: AbstractNumbering['levels'][0]) => ({
    ilvl: lvl.ilvl,
    numFmt: lvl.numFmt,
    text: lvl.text,
    start: lvl.start,
    lvlRestart: lvl.lvlRestart,
    indent: normEmpty(lvl.indent),
    runProps: normEmpty(lvl.runProps),
    pProps: normEmpty(lvl.pProps),
    isLegal: lvl.isLegal,
  });
  return { levels: num.levels.map(normLevel) };
}

function serializeNumberingMap(numbering: NumberingMap): string {
  const ids = Array.from(numbering.keys()).sort((a, b) => a - b);
  const entries = ids.map((id) => ({ id, num: serializeAbstractNumbering(numbering.get(id)!) }));
  return deepStableStringify(entries);
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

describe('Sprint 233 — Phase 6 ChienYi fixture NumberingMap preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`NumberingMap SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture 編號定義保留率 ≥ ${MIN_NUMBERING_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      numCount: number;
      numMatch: boolean;
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

      const origSig = serializeNumberingMap(originalDoc.numbering);
      const reparseSig = serializeNumberingMap(reparseDoc.numbering);

      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({
        path: f.path,
        category: f.category,
        numCount: originalDoc.numbering.size,
        numMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.numMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalNums = results.reduce((acc, r) => acc + r.numCount, 0);

    const byCategory: Record<string, { total: number; match: number; nums: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, nums: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].nums += r.numCount;
      if (r.numMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint233] total=${total} numbering match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalNumberings=${totalNums}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint233]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) nums=${stats.nums}`,
      );
    }
    for (const r of results.filter((x) => !x.numMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint233]   DIFF ${r.path}: numCount=${r.numCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_NUMBERING_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
