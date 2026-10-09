/**
 * Sprint 223 — Phase 6 ChienYi fixture SectionProps preservation audit（第六層）
 *
 * Sprint 218+219 完成 ChienYi TableProps 第五層（71 tables 100%）後、五層
 * 矩陣完備。本 sprint **擴展至第六層 SectionProps**（page size / margins /
 * orientation / columns / docGrid / sectionBreakType / titlePage /
 * evenAndOddHeaders / headerRefs+footerRefs slots）。
 *
 * 對 ChienYi v1 release 商用層次而言：
 *   - 段落 / 表格層級格式保留 100%（Sprint 215+218+219）
 *   - **page 層級設定保留 ?** → 若 page width/height/orientation /margin/欄數
 *     在 round-trip 後丟失、export 紙張規格會跑掉（A4 → letter 視覺破裂）
 *
 * Serialize 策略（紀律 #2）：
 *   - SectionProps 含 6 個 nested object（page/margins/columns/headerRefs/
 *     footerRefs/docGrid）、用 `deepStableStringify` 遞迴排序處理
 *   - **headerRefs/footerRefs 只比對 slot keys（default/first/even 是否存在）、
 *     不比對 rId 字串**（export rId 重排不應算 drift；header/footer 內容
 *     已在其他 path 驗證）
 *   - **body 排除**（內容已由 structure/text/run/para/table 5 層分別驗證、
 *     section 層只驗 page-level metadata）
 *
 * 預期：Phase 6 Sprint 192 sectPr 對等 path 設計，預期 100%、容寬 95%。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  DocumentNode,
  SectionNode,
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

/** Phase 6 sectPr writer 設計為對等 path、預期 100%、容寬 95%。 */
const MIN_SECTION_MATCH_RATE_PCT = 95;

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
 * 序列化 section page-level metadata、排除 body。
 *
 * headerRefs/footerRefs 只記錄 slot 存在性（不記 rId 字串）：export rId 重排
 * 不算 drift（header/footer 內容由其他 path 驗證）。
 */
function serializeSection(s: SectionNode): string {
  const refSlots = (refs: Record<string, string | undefined>) =>
    Object.keys(refs).filter((k) => refs[k] !== undefined).sort();

  const sig = {
    page: s.page,
    margins: s.margins,
    columns: s.columns,
    headerSlots: refSlots(s.headerRefs as unknown as Record<string, string | undefined>),
    footerSlots: refSlots(s.footerRefs as unknown as Record<string, string | undefined>),
    titlePage: s.titlePage,
    evenAndOddHeaders: s.evenAndOddHeaders,
    sectionBreakType: s.sectionBreakType,
    docGrid: s.docGrid,
  };
  return deepStableStringify(sig);
}

function collectSectionSignatures(doc: DocumentNode): string[] {
  return doc.sections.map(serializeSection);
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

describe('Sprint 223 — Phase 6 ChienYi fixture SectionProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`SectionProps SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture section page-metadata 保留率 ≥ ${MIN_SECTION_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      sectionCount: number;
      sectionMatch: boolean;
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

      const originalSigs = collectSectionSignatures(originalDoc);
      const reparseSigs = collectSectionSignatures(reparseDoc);

      let match = false;
      if (originalSigs.length === reparseSigs.length) {
        match = originalSigs.length === 0 ||
          sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
      }
      results.push({
        path: f.path,
        category: f.category,
        sectionCount: originalSigs.length,
        sectionMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.sectionMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalSections = results.reduce((acc, r) => acc + r.sectionCount, 0);

    const byCategory: Record<string, { total: number; match: number; sections: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, sections: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].sections += r.sectionCount;
      if (r.sectionMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint223] total=${total} section match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalSections=${totalSections}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint223]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) sections=${stats.sections}`,
      );
    }
    for (const r of results.filter((x) => !x.sectionMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint223]   DIFF ${r.path}: sectionCount=${r.sectionCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_SECTION_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
