/**
 * Sprint 230 — Phase 6 ChienYi fixture StyleMap preservation audit（第八層）
 *
 * 三 corpus 七層矩陣完備後、擴展第八層 StyleMap（document.styles map）。
 * styles.xml 定義所有命名樣式、被 ParagraphNode.styleId / RunNode.styleId /
 * TableNode.styleId 引用；若 styles round-trip drift、ref 解析會錯位、
 * 視覺結果不一致即使 paragraph/run/table props 自身對等。
 *
 * Serialize 策略：
 *   - StyleMap = Map<string, StyleEntry>；styleId 排序後串接
 *   - StyleEntry 含 pProps / rProps / basedOn / conditional (Map)
 *   - conditional Map 攤平為 sorted key array（type → {pProps,rProps,cProps}）
 *   - 用 deepStableStringify 遞迴序列化所有 props nested objects
 *
 * 預期：Phase 6 Sprint 187 styles.xml writer 對等 path 設計、預期 ≥ 90%。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  DocumentNode,
  StyleEntry,
  StyleMap,
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

/** Phase 6 styles writer 對等 path 設計、容寬鬆 90%（styles 涵蓋廣、容 edge）。 */
const MIN_STYLE_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

/** 攤平 StyleEntry：把 conditional Map 變成 sorted object、其他 props 保留。
 *
 * 規範化：空 `{}` 視為 undefined（semantic equivalence、避免 writer 對
 * 空 props emit 與不 emit 之間的虛假 drift）。 */
function flattenStyleEntry(entry: StyleEntry): Record<string, unknown> {
  const normEmpty = (v: unknown): unknown =>
    v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0 ? undefined : v;
  const out: Record<string, unknown> = {
    pProps: normEmpty(entry.pProps),
    rProps: normEmpty(entry.rProps),
    basedOn: entry.basedOn,
  };
  if (entry.conditional && entry.conditional.size > 0) {
    const condObj: Record<string, unknown> = {};
    for (const [k, v] of entry.conditional) condObj[String(k)] = v;
    out.conditional = condObj;
  }
  return out;
}

function serializeStyleMap(styles: StyleMap): string {
  const ids = Array.from(styles.keys()).sort();
  const entries = ids.map((id) => ({ id, entry: flattenStyleEntry(styles.get(id)!) }));
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

describe('Sprint 230 — Phase 6 ChienYi fixture StyleMap preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`StyleMap SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture 樣式定義保留率 ≥ ${MIN_STYLE_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      styleCount: number;
      styleMatch: boolean;
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

      const origSig = serializeStyleMap(originalDoc.styles);
      const reparseSig = serializeStyleMap(reparseDoc.styles);

      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({
        path: f.path,
        category: f.category,
        styleCount: originalDoc.styles.size,
        styleMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.styleMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalStyles = results.reduce((acc, r) => acc + r.styleCount, 0);

    const byCategory: Record<string, { total: number; match: number; styles: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, styles: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].styles += r.styleCount;
      if (r.styleMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint230] total=${total} style match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalStyles=${totalStyles}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint230]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) styles=${stats.styles}`,
      );
    }
    for (const r of results.filter((x) => !x.styleMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint230]   DIFF ${r.path}: styleCount=${r.styleCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_STYLE_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
