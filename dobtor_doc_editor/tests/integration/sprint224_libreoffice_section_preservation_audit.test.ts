/**
 * Sprint 224 — Phase 6 LibreOffice 286 fixture SectionProps preservation audit
 *
 * Sprint 223 對 ChienYi 42 揭發 writer 漏寫 `<w:docGrid>`、修 OoxmlWriter
 * `writeSectPr` 加 docGrid 序列化分支、ChienYi 42 達 100%；本 sprint 把
 * audit 套用至 Sprint 198 已 parse 成功的 288 個 LibreOffice 邊緣 fixture、
 * 驗 Sprint 223 修法在 edge case 也成立。
 *
 * 預期：
 *   - Sprint 223 修法為一般化、應對所有 CJK 文件 docGrid round-trip drift
 *   - 邊緣 corpus 含 Phase 5 lossy / 故意畸形 case、預期 ≥ 80%
 *   - 若 ≥ 95% 即代表 Sprint 223 修法亦對邊緣 corpus 達 commercial-grade
 *     section-metadata 對稱
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode, SectionNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

const EXPECTED_PARSE_OK_BASELINE = 288;

/** 邊緣 corpus、寬鬆 80%（ChienYi Sprint 223 修後達 100%）。 */
const MIN_SECTION_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

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

describe('Sprint 224 — Phase 6 LibreOffice 286 fixture SectionProps preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`SectionProps SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture section page-metadata 保留率 ≥ ${MIN_SECTION_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      parseOk: boolean;
      pipelineOk: boolean;
      sectionMatch: boolean;
      sectionCount: number;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      const r: Result = {
        path: f.path,
        category: f.category,
        parseOk: false,
        pipelineOk: false,
        sectionMatch: false,
        sectionCount: 0,
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

        const originalSigs = collectSectionSignatures(originalDoc);
        const reparseSigs = collectSectionSignatures(reparseDoc);
        r.sectionCount = originalSigs.length;

        if (originalSigs.length === reparseSigs.length) {
          if (originalSigs.length === 0) {
            r.sectionMatch = true;
          } else {
            r.sectionMatch = sha256(originalSigs.join('|')) === sha256(reparseSigs.join('|'));
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
    const matchCount = results.filter((x) => x.sectionMatch).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalSections = results.reduce((acc, r) => acc + r.sectionCount, 0);

    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; sections: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, sections: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].sections += r.sectionCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.sectionMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint224] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} ` +
        `section=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalSections=${totalSections}`,
    );
    const cats = Object.keys(byCategory).sort();
    for (const cat of cats) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint224]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} ` +
          `section ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) sections=${stats.sections}`,
      );
    }
    const failed = results.filter((r) => r.pipelineOk && !r.sectionMatch);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint224] section DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint224]   ${r.path} sectionCount=${r.sectionCount}`);
      }
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_SECTION_MATCH_RATE_PCT);
  }, 120000);
});
