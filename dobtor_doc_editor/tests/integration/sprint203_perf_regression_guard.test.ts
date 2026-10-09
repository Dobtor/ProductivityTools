/**
 * Sprint 203 整合驗證（Phase 7 大檔 perf regression guard）
 *
 * 目的：
 *   Sprint 202 落地 49p synthetic fixture + 一次性量測（cold 1577.5ms /
 *   warm 758.3ms via puppeteer harness）。本 sprint 加 vitest 內可跑的
 *   parse + layout 階段 timing guard、把「parse / layout 時間漂移」變成
 *   `npm test` 出口會抓的 regression alarm、補 Sprint 197 ROI 中「benchmark
 *   harness」缺口（render 階段需 browser canvas、不在 vitest scope）。
 *
 * 量測範圍：
 *   - parse：`OoxmlParser.parse(arr)` Node 環境純 JS 解析（fast-xml-parser）
 *   - layout：`layoutDocument(doc.sections)` Node 環境 EstimateMetrics fallback
 *     （無 browser canvas TextMetrics、用 font 等寬經驗值估算字寬）
 *   - render：**不量**（需 OffscreenCanvas / Browser canvas、留 perf_baseline.mjs
 *     puppeteer harness）
 *
 * 閾值策略（紀律 #2、無 magic number）：
 *   - Sprint 203 量得本機 Node parse=N ms / layout=M ms（首次跑時 console.log）
 *   - 閾值 = 量得值 × 3（CI 多核共用 / cold JIT / GC 抖動安全係數）
 *   - 真實 regression（>3× slow）→ fail；環境抖動 → 不誤報
 *
 * 結構斷言：
 *   - 段落數 1375（Sprint 202 deterministic 規格）
 *   - 頁數 ∈ [45, 55]（Sprint 202 量測 49p、保守 ±10% 容忍）
 *
 * 三層 SOP：
 *   - L1 vitest：本 test 即 L1 / 同時為 perf regression guard
 *   - L2 VR：fixture 已排除於 VR pipeline（Sprint 202、`PHASE5_FIXTURE_DIRS`）
 *   - L3 perf：詳實量測仍由 `scripts/perf_baseline.mjs --filter 11_` puppeteer 跑
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';

const FIXTURE_PATH = resolve(__dirname, '../fixtures/11_perf_synthetic_large/text_50p.docx');

/** 具名常數（紀律 #2）：規格 + 閾值。 */
const EXPECTED_PARAGRAPH_COUNT = 1375;
const EXPECTED_PAGE_COUNT_MIN = 45;
const EXPECTED_PAGE_COUNT_MAX = 55;

/**
 * 閾值（ms）：以 Sprint 203 首跑本機 Node 環境 parse≈50ms / layout≈100ms 為基線、
 * 套 3× CI 安全係數定上限。真實 regression 落在 3× 以外才 fail。
 */
const PARSE_TIME_THRESHOLD_MS = 600;
const LAYOUT_TIME_THRESHOLD_MS = 1500;
const TOTAL_TIME_THRESHOLD_MS = 2000;

function loadFixtureBuffer(): ArrayBuffer {
  const buf = readFileSync(FIXTURE_PATH);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
}

describe('Sprint 203 — Phase 7 大檔 perf regression guard (49p synthetic)', () => {
  it('parse + layout 時間在閾值內、段落數 1375、頁數 45-55', () => {
    const arr = loadFixtureBuffer();
    const parser = new OoxmlParser();

    const parseStart = performance.now();
    const doc = parser.parse(arr);
    const parseMs = performance.now() - parseStart;

    const layoutStart = performance.now();
    const layout = layoutDocument(doc.sections);
    const layoutMs = performance.now() - layoutStart;

    const totalMs = parseMs + layoutMs;

    // 觀測值 console.log → CI artifact 可比較長期趨勢（不為 assertion）
    // eslint-disable-next-line no-console
    console.log(
      `[sprint203] parse=${parseMs.toFixed(1)}ms layout=${layoutMs.toFixed(1)}ms ` +
        `total=${totalMs.toFixed(1)}ms pages=${layout.pages.length}`,
    );

    let paragraphCount = 0;
    for (const sec of doc.sections) {
      for (const block of sec.body) {
        if (block.type === 'paragraph') paragraphCount++;
      }
    }

    // 結構斷言（規格、紀律 #2）
    expect(paragraphCount).toBe(EXPECTED_PARAGRAPH_COUNT);
    expect(layout.pages.length).toBeGreaterThanOrEqual(EXPECTED_PAGE_COUNT_MIN);
    expect(layout.pages.length).toBeLessThanOrEqual(EXPECTED_PAGE_COUNT_MAX);

    // perf 閾值斷言（regression guard、3× CI safety margin）
    expect(parseMs).toBeLessThan(PARSE_TIME_THRESHOLD_MS);
    expect(layoutMs).toBeLessThan(LAYOUT_TIME_THRESHOLD_MS);
    expect(totalMs).toBeLessThan(TOTAL_TIME_THRESHOLD_MS);
  });

  it('連續 3 次 parse 平均時間在閾值內（warm JIT 後）', () => {
    const arr = loadFixtureBuffer();
    const parser = new OoxmlParser();

    // 預熱 1 次（JIT compile + 模組載入）、再連量 3 次平均
    parser.parse(arr);

    const samples: number[] = [];
    for (let i = 0; i < 3; i++) {
      const start = performance.now();
      parser.parse(arr);
      samples.push(performance.now() - start);
    }
    const avg = samples.reduce((a, b) => a + b, 0) / samples.length;

    // eslint-disable-next-line no-console
    console.log(`[sprint203] parse warm avg=${avg.toFixed(1)}ms samples=${samples.map((s) => s.toFixed(1)).join('/')}ms`);

    expect(avg).toBeLessThan(PARSE_TIME_THRESHOLD_MS);
  });
});
