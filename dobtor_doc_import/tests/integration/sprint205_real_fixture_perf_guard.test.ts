/**
 * Sprint 205 整合驗證（Phase 7 真實 ChienYi 大檔 perf regression guard）
 *
 * 目的：
 *   Sprint 203 對 49p synthetic text-heavy fixture 落地 parse + layout
 *   regression guard。本 sprint **擴展同樣機制至 top-3 真實 ChienYi fixture**
 *   ——`04_with_image` 系列含 2MB 圖片的監造表單 + `02_std_table` 系列含
 *   大量表格的週報。涵蓋 ChienYi 監造實際 workflow 場景（圖片密集 + 表格
 *   密集）、補 synthetic 純文字無法覆蓋的 perf 面向。
 *
 * 選定 fixture（依 Sprint 201 baseline 由大到小取前 3 個真實 fixture、
 * 跨 category 覆蓋）：
 *   1. 04_with_image/6.環清表安全衛生抽查照片(再造)-(112.10.2.-10.6).docx
 *      — 2.1MB / 6 頁、含多張 2MB 圖片（最大檔）
 *   2. 02_std_table/1120928-磺港溪再造C段護岸及步道整建工程週報.docx
 *      — 1.8MB / 2 頁、表格密集（最大表格檔）
 *   3. 04_with_image/06.環清表安全衛生抽查照片(再造)-(112.10.9.-10.13).docx
 *      — 1.9MB / 6 頁（為 1 對比點、相同 category 不同 case）
 *
 * 閾值策略：
 *   - Sprint 201 puppeteer baseline：parse 144-190ms / layout 5-6ms
 *   - Node 環境 ~2-3× 慢（無 V8 browser optimizations、含 JIT cold）
 *   - 套 3× CI safety margin：parse < 1500ms、layout < 500ms、total < 2000ms
 *
 * 與 Sprint 203 區別：
 *   - Sprint 203：49p synthetic text-heavy（cold parse 266ms、layout 228ms）
 *   - Sprint 205：2MB 真實 ChienYi 圖文+表格（cold parse 預估 500-800ms、
 *                layout 預估 30-60ms——圖片解析占 parse 大宗、表格 layout cost 較低）
 *
 * 三層 SOP：
 *   - L1 vitest：本 test 即 L1 / 同時為 real-world perf regression guard
 *   - L2 VR：使用既有 04/02 fixture、本身已在 VR pipeline 內（不改動 VR）
 *   - L3 perf：詳實量測仍由 `scripts/perf_baseline.mjs` puppeteer harness 跑
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

/** Top-3 真實 fixture（具名常數、無 magic、紀律 #2） */
const TOP_REAL_FIXTURES = [
  '04_with_image/6.環清表安全衛生抽查照片(再造)-(112.10.2.-10.6).docx',
  '02_std_table/1120928-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  '04_with_image/06.環清表安全衛生抽查照片(再造)-(112.10.9.-10.13).docx',
];

/**
 * 閾值（ms）：Sprint 201 puppeteer 量得 parse 144-190ms / layout 5-6ms；
 * Node 環境 ~2-3× 慢 + JIT cold + GC pressure → 套 3× CI safety margin。
 */
const PARSE_TIME_THRESHOLD_MS = 1500;
const LAYOUT_TIME_THRESHOLD_MS = 500;
const TOTAL_TIME_THRESHOLD_MS = 2000;

function loadFixtureBuffer(rel: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, rel));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
}

describe('Sprint 205 — Phase 7 真實 ChienYi 大檔 perf regression guard (top-3 fixture)', () => {
  it.each(TOP_REAL_FIXTURES)('%s — parse + layout 時間在閾值內', (rel) => {
    const arr = loadFixtureBuffer(rel);
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
      `[sprint205] ${rel.split('/')[0]} parse=${parseMs.toFixed(1)}ms ` +
        `layout=${layoutMs.toFixed(1)}ms total=${totalMs.toFixed(1)}ms ` +
        `pages=${layout.pages.length}`,
    );

    // 結構斷言：至少 1 頁、layout 不 crash
    expect(layout.pages.length).toBeGreaterThanOrEqual(1);

    // perf 閾值斷言（regression guard、3× CI safety margin）
    expect(parseMs).toBeLessThan(PARSE_TIME_THRESHOLD_MS);
    expect(layoutMs).toBeLessThan(LAYOUT_TIME_THRESHOLD_MS);
    expect(totalMs).toBeLessThan(TOTAL_TIME_THRESHOLD_MS);
  });
});
