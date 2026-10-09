/**
 * Sprint 227 — Phase 6 ChienYi fixture HeaderFooterContent preservation audit（第七層）
 *
 * Sprint 223+225+226 完成 SectionProps 第六層三 corpus 矩陣後、矩陣完備。
 * 然而第六層 audit 對 headerRefs / footerRefs 只比對 **slot 存在性**
 * （default / first / even keys）、不比對實際 header/footer block 內容。
 *
 * 對 ChienYi v1 release 商用層次而言：
 *   - SectionProps 100%（Sprint 223） → 頁面 / 邊距 / 欄數 / docGrid 不丟
 *   - **header/footer 內容保留 ?** → 若 header 文字 / 邊框 / shading
 *     在 round-trip 後丟失、export 頁眉頁尾視覺仍會跑掉（如 ChienYi
 *     監造文件「自主檢查表」series 大量 header logo + 工程名）
 *
 * 本 sprint 對 ChienYi 42 production fixture 各 section 的 default / first /
 * even header + footer **content[] deep-stable JSON SHA-256 fingerprint**
 * 對照、量化 header/footer 內容保留率。
 *
 * 範圍：只 audit 有 header/footer slot 的 section（headerRefs.default !==
 * undefined 等）；無 slot 的 section trivially match（無內容）。
 *
 * 預期：Phase 6 Sprint 193+196 header/footer 對等 path 設計、預期 100%。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type {
  DocumentNode,
  HeaderFooterContent,
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

/** Phase 6 header/footer writer 設計為對等 path、預期 100%、容寬 95%。 */
const MIN_HF_MATCH_RATE_PCT = 95;

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
 * 對單一 section 收集 header + footer 內容簽章（每個 slot 一條）。
 *
 * 不依賴 rId 字串（writer 可能重排）；依 slot 類型（default / first /
 * even）為 key、解析 rId → content[] → deepStableStringify。
 */
function collectHFSignatures(
  doc: DocumentNode,
): { headerSigs: string[]; footerSigs: string[]; slotCount: number } {
  const headerSigs: string[] = [];
  const footerSigs: string[] = [];
  let slotCount = 0;

  const sigFor = (rId: string | undefined, map: Map<string, HeaderFooterContent>): string => {
    if (rId === undefined) return '__none__';
    const hf = map.get(rId);
    if (!hf) return '__missing__';
    return deepStableStringify(hf.content);
  };

  for (const sec of doc.sections) {
    const slots: Array<'default' | 'first' | 'even'> = ['default', 'first', 'even'];
    for (const k of slots) {
      const hRid = (sec.headerRefs as Record<string, string | undefined>)[k];
      const fRid = (sec.footerRefs as Record<string, string | undefined>)[k];
      if (hRid !== undefined) {
        headerSigs.push(`H:${k}:${sigFor(hRid, doc.headers)}`);
        slotCount++;
      }
      if (fRid !== undefined) {
        footerSigs.push(`F:${k}:${sigFor(fRid, doc.footers)}`);
        slotCount++;
      }
    }
  }
  return { headerSigs, footerSigs, slotCount };
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

describe('Sprint 227 — Phase 6 ChienYi fixture HeaderFooterContent preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`HeaderFooterContent SHA-256 對照：${EXPECTED_FIXTURE_COUNT} ChienYi fixture header/footer 內容保留率 ≥ ${MIN_HF_MATCH_RATE_PCT}%`, () => {
    interface Result {
      path: string;
      category: string;
      slotCount: number;
      hfMatch: boolean;
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

      const orig = collectHFSignatures(originalDoc);
      const reparse = collectHFSignatures(reparseDoc);

      let match = false;
      if (
        orig.headerSigs.length === reparse.headerSigs.length &&
        orig.footerSigs.length === reparse.footerSigs.length
      ) {
        const allOrig = [...orig.headerSigs, ...orig.footerSigs].join('|');
        const allRepa = [...reparse.headerSigs, ...reparse.footerSigs].join('|');
        match = orig.slotCount === 0 || sha256(allOrig) === sha256(allRepa);
      }
      results.push({
        path: f.path,
        category: f.category,
        slotCount: orig.slotCount,
        hfMatch: match,
      });
    }

    const total = results.length;
    const matchCount = results.filter((r) => r.hfMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalSlots = results.reduce((acc, r) => acc + r.slotCount, 0);

    const byCategory: Record<string, { total: number; match: number; slots: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, slots: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].slots += r.slotCount;
      if (r.hfMatch) byCategory[r.category].match++;
    }

    // eslint-disable-next-line no-console
    console.log(
      `[sprint227] total=${total} hf match=${matchCount}/${total} (${matchRate.toFixed(1)}%) ` +
        `totalSlots=${totalSlots}`,
    );
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(
        `[sprint227]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) slots=${stats.slots}`,
      );
    }
    for (const r of results.filter((x) => !x.hfMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint227]   DIFF ${r.path}: slotCount=${r.slotCount}`);
    }

    expect(matchRate).toBeGreaterThanOrEqual(MIN_HF_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
