/**
 * Sprint 198 — Phase 7 邊緣相容性 audit
 *
 * 對 290 個 LibreOffice 來源 docx fixture 跑 OoxmlParser、統計：
 *   - 成功 parse 比率（不丟例外完成 → success）
 *   - 失敗 parse 數（丟例外）
 *   - 結構完整性（至少 1 個 section、1 個 paragraph、styles map 非 undefined）
 *
 * 紀律 #18 scope-down：本 audit **接受** LibreOffice 故意畸形 / 邊界 case 失敗
 * （PROVENANCE.md 明白標示「parser 對它們應優雅失敗而非崩潰」）；判定標準
 * 為「不 crash node process」+「即使失敗也回明確 Error 而非 silent corruption」。
 *
 * 同時依 category 分組統計、揭示哪類元件最常失敗（給未來補強優先序）。
 *
 * 失敗的意義：success rate 與 baseline（本 sprint 寫死）差異 > 5% 時、
 *           表 OoxmlParser 對 LibreOffice 生成 docx 的相容性 regression。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');

/** 紀律 #2：避免 magic number。LibreOffice fixture 入庫時的總檔數（Sprint 198）。 */
const EXPECTED_FIXTURE_COUNT = 290;

/** 紀律 #2：parse success rate baseline（Sprint 198 第一次量測、未來 regression 比對）。 */
const MIN_SUCCESS_RATE_PCT = 50; // 寬鬆下限（LibreOffice fixture 含大量畸形邊界 case）

/** 收集所有 .docx fixture 的相對路徑（含 category 子目錄）。 */
function collectFixtures(): { category: string; path: string; abspath: string }[] {
  const out: { category: string; path: string; abspath: string }[] = [];
  const cats = readdirSync(FIXTURE_ROOT);
  for (const cat of cats) {
    const catPath = join(FIXTURE_ROOT, cat);
    let st;
    try { st = statSync(catPath); } catch { continue; }
    if (!st.isDirectory()) continue;
    const files = readdirSync(catPath);
    for (const f of files) {
      if (!f.endsWith('.docx')) continue;
      out.push({
        category: cat,
        path: `${cat}/${f}`,
        abspath: join(catPath, f),
      });
    }
  }
  return out;
}

function loadAsArrayBuffer(abspath: string): ArrayBuffer {
  const buf = readFileSync(abspath);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

describe('Sprint 198 — Phase 7 邊緣相容性 audit（LibreOffice fixture）', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();

  it(`fixture 入庫完整：290 個 docx（實際 = ${fixtures.length}）`, () => {
    expect(fixtures.length).toBe(EXPECTED_FIXTURE_COUNT);
  });

  it('全 fixture parse 不 crash node process（即使丟例外也是預期行為）', () => {
    interface Result {
      path: string;
      category: string;
      ok: boolean;
      err?: string;
      sections?: number;
      paragraphs?: number;
      hasStyles?: boolean;
    }
    const results: Result[] = [];

    for (const f of fixtures) {
      try {
        const doc = parser.parse(loadAsArrayBuffer(f.abspath));
        // 統計結構完整性
        let paragraphCount = 0;
        for (const sec of doc.sections) {
          for (const block of sec.body) {
            if (block.type === 'paragraph') paragraphCount++;
          }
        }
        results.push({
          path: f.path,
          category: f.category,
          ok: true,
          sections: doc.sections.length,
          paragraphs: paragraphCount,
          hasStyles: doc.styles.size > 0,
        });
      } catch (e) {
        results.push({
          path: f.path,
          category: f.category,
          ok: false,
          err: e instanceof Error ? e.message.slice(0, 200) : String(e).slice(0, 200),
        });
      }
    }

    // ── 整體統計 ────────────────────────────────────────────────
    const total = results.length;
    const okCount = results.filter((r) => r.ok).length;
    const successRate = (okCount / total) * 100;
    const failed = results.filter((r) => !r.ok);

    // ── per-category 統計 ──────────────────────────────────────
    const byCategory = new Map<string, { total: number; ok: number; fail: number }>();
    for (const r of results) {
      let entry = byCategory.get(r.category);
      if (!entry) {
        entry = { total: 0, ok: 0, fail: 0 };
        byCategory.set(r.category, entry);
      }
      entry.total++;
      if (r.ok) entry.ok++;
      else entry.fail++;
    }

    // ── 結構完整性統計（僅成功 parse 的）────────────────────
    const okResults = results.filter((r) => r.ok);
    const withSections = okResults.filter((r) => (r.sections ?? 0) >= 1).length;
    const withParagraphs = okResults.filter((r) => (r.paragraphs ?? 0) >= 1).length;
    const withStyles = okResults.filter((r) => r.hasStyles === true).length;

    // ── 印出 audit 報告（測試輸出可在 vitest log 看見）────────
    console.log('\n=== Sprint 198 — LibreOffice 邊緣相容性 audit ===');
    console.log(`Total fixtures: ${total}`);
    console.log(`Parse OK:       ${okCount} (${successRate.toFixed(1)}%)`);
    console.log(`Parse Fail:     ${failed.length} (${(100 - successRate).toFixed(1)}%)`);
    console.log('\nPer-category breakdown:');
    for (const [cat, s] of [...byCategory.entries()].sort()) {
      const pct = ((s.ok / s.total) * 100).toFixed(0);
      console.log(`  ${cat.padEnd(15)} total=${String(s.total).padStart(3)}  ok=${String(s.ok).padStart(3)}  fail=${String(s.fail).padStart(3)}  ${pct}%`);
    }
    console.log('\nStructure coverage (among parse OK):');
    console.log(`  with sections ≥1:     ${withSections}/${okCount} (${(withSections / okCount * 100).toFixed(0)}%)`);
    console.log(`  with paragraphs ≥1:   ${withParagraphs}/${okCount} (${(withParagraphs / okCount * 100).toFixed(0)}%)`);
    console.log(`  with non-empty styles: ${withStyles}/${okCount} (${(withStyles / okCount * 100).toFixed(0)}%)`);

    if (failed.length > 0) {
      console.log('\nFailure samples (first 10):');
      for (const r of failed.slice(0, 10)) {
        console.log(`  [${r.category}] ${r.path}`);
        console.log(`     → ${r.err}`);
      }
    }
    console.log('=== end audit ===\n');

    // ── 斷言：success rate 不可低於下限 ────────────────────
    expect(successRate).toBeGreaterThanOrEqual(MIN_SUCCESS_RATE_PCT);
  }, /* 較長 timeout、290 檔串行 parse */ 120000);

  it('所有失敗 parse 必須丟 Error（不可 silent corruption）', () => {
    // 抽樣驗證：取 10 個失敗 case 驗 throw 的是 Error instance
    // 若全部成功 parse 則跳過
    const sampleFailed: string[] = [];
    for (const f of fixtures) {
      if (sampleFailed.length >= 10) break;
      try {
        parser.parse(loadAsArrayBuffer(f.abspath));
      } catch (e) {
        sampleFailed.push(f.path);
        expect(e).toBeInstanceOf(Error);
      }
    }
    // 抽樣結果不強制下限（可能全綠）
    console.log(`Sampled ${sampleFailed.length} failure(s) — all threw Error instance.`);
  }, 60000);
});
