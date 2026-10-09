#!/usr/bin/env node
/**
 * Sprint 64 — `--font-metrics` baseline drift 量測
 *
 * 目的：Sprint 63 證實 VR mean 改善（-0.0017 / 5 大贏全 03 全套管 / 0 regression > 0.001）。
 *       但 Sprint 12（render ops fingerprint）和 Sprint 16（page count baseline）vitest 是用
 *       「default EstimateMetrics」layout 算出來的；切換到 FontMetricsAdapter 後 line height 變動
 *       可能讓 pages.length / fingerprint 漂移。本 sprint 在 Node 環境直接 layout 兩遍比對。
 *
 * 為什麼要在 Node 環境跑（不是 puppeteer）：
 *   - Sprint 12 / 16 baseline 是 vitest 在 Node 跑、不經 IIFE bundle
 *   - 我們要量的就是「若 layout pipeline 改用 real font metrics、整個 Node 端 baseline 會否漂移」
 *   - 這直接給 Sprint 65 promote default-on 的「baseline 是否要重 record」回答
 *
 * 對 42 fixture：
 *   - default layout（EstimateMetrics 1.2em）→ pages count + ops fingerprint
 *   - font-metrics layout（DroidSansFallback + LiberationSerif，TTF bytes 從 /usr/share/fonts/）→ pages count + ops fingerprint
 *   - per-fixture diff：page count delta、fingerprint hash mismatch、ops counter delta
 *
 * 輸出：tests/fixtures/font_metrics_baseline_drift_report.json + console summary
 */

import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, '..');
const FIXTURE_ROOT = resolve(ROOT, 'tests/fixtures');
const REPORT_PATH = resolve(FIXTURE_ROOT, 'font_metrics_baseline_drift_report.json');

// 注入 @xmldom/xmldom 的 DOMParser（與 vitest tests/setup.ts 同邏輯，OoxmlParser 必需）
import { DOMParser, XMLSerializer } from '@xmldom/xmldom';
globalThis.DOMParser = DOMParser;
globalThis.XMLSerializer = XMLSerializer;

// Sprint 14 IIFE bundle 不能在 Node 直接 import（rollup-only target）
// 改用 tsx 載入 .ts source 直接執行
import { OoxmlParser } from '../static/src/core/ooxml/OoxmlParser.ts';
import { layoutDocument } from '../static/src/core/layout/index.ts';
import { FontMetricsAdapter } from '../static/src/core/layout/FontMetricsAdapter.ts';
import { CanvasRenderer } from '../static/src/core/render/CanvasRenderer.ts';
import { MockRenderContext } from '../static/src/core/render/MockRenderContext.ts';
import { fingerprintOps } from '../static/src/core/render/serializeOps.ts';

function listFixtures() {
  const out = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory() || cat.startsWith('.')) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) out.push(`${cat}/${f}`);
    }
  }
  return out.sort();
}

function buildFontAdapter() {
  const adapter = new FontMetricsAdapter();
  const paths = {
    'Times New Roman': '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
    '標楷體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    '微軟正黑體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    '新細明體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    '細明體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    'DFKai-SB': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    'PMingLiU': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    'MingLiU': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    'Arial': '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
  };
  for (const [family, p] of Object.entries(paths)) {
    if (!existsSync(p)) continue;
    const bytes = readFileSync(p);
    adapter.registerFont(family, bytes);
  }
  return adapter;
}

function runLayout(docxBytes, metrics) {
  const parser = new OoxmlParser();
  const ast = parser.parse(docxBytes);
  const opts = metrics ? { metrics } : {};
  const layout = layoutDocument(ast.sections, opts);
  // ops fingerprint
  const mockCtx = new MockRenderContext();
  const renderer = new CanvasRenderer(mockCtx);
  renderer.render(layout);
  const fp = fingerprintOps(mockCtx.ops);
  return {
    pageCount: layout.pages.length,
    opsCount: mockCtx.ops.length,
    fingerprint: fp,
  };
}

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s : s + ' '.repeat(n - s.length);
}

async function main() {
  console.log('[drift] 載入 FontMetricsAdapter...');
  const adapter = buildFontAdapter();
  console.log(`[drift] adapter 註冊字型: ${adapter.listFonts().join(', ')}`);

  const fixtures = listFixtures();
  console.log(`[drift] 對 ${fixtures.length} fixture 跑 default vs font-metrics`);

  const results = [];
  let driftPageCount = 0;
  let driftFingerprint = 0;
  let driftOpsCount = 0;

  for (const rel of fixtures) {
    const buf = readFileSync(resolve(FIXTURE_ROOT, rel));
    const docxBytes = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

    let def, fm, error;
    try {
      def = runLayout(docxBytes, null);
      fm = runLayout(docxBytes, adapter);
    } catch (err) {
      error = String(err.message || err).slice(0, 200);
    }

    if (error) {
      console.log(`[drift] ${pad(rel, 60)} ERROR ${error}`);
      results.push({ rel, error });
      continue;
    }

    const pageDelta = fm.pageCount - def.pageCount;
    const opsDelta = fm.opsCount - def.opsCount;
    const fpSame = def.fingerprint === fm.fingerprint;
    if (pageDelta !== 0) driftPageCount++;
    if (!fpSame) driftFingerprint++;
    if (opsDelta !== 0) driftOpsCount++;

    const marker = pageDelta !== 0 || !fpSame
      ? (pageDelta !== 0 ? `[PAGE ${pageDelta >= 0 ? '+' : ''}${pageDelta}]` : '[FP]')
      : '   ';
    console.log(
      `[drift] ${pad(rel, 60)} pages ${def.pageCount}→${fm.pageCount}` +
        ` ops ${def.opsCount}→${fm.opsCount}` +
        `  ${marker}`,
    );

    results.push({
      rel,
      default: def,
      fontMetrics: fm,
      pageDelta,
      opsDelta,
      fingerprintSame: fpSame,
    });
  }

  console.log('\n=== Summary ===');
  console.log(`Fixtures: ${fixtures.length}`);
  console.log(`Page count drift: ${driftPageCount} / ${fixtures.length}`);
  console.log(`Fingerprint drift: ${driftFingerprint} / ${fixtures.length}`);
  console.log(`Ops count drift: ${driftOpsCount} / ${fixtures.length}`);

  // 分類 drift
  const byCat = {};
  for (const r of results) {
    if (!r.default) continue;
    const cat = r.rel.split('/')[0];
    if (!byCat[cat]) byCat[cat] = { n: 0, pageShift: 0, fpDiff: 0, opsShift: 0, pageGain: 0, pageLoss: 0 };
    byCat[cat].n++;
    if (r.pageDelta !== 0) byCat[cat].pageShift++;
    if (!r.fingerprintSame) byCat[cat].fpDiff++;
    if (r.opsDelta !== 0) byCat[cat].opsShift++;
    if (r.pageDelta < 0) byCat[cat].pageGain++; // 比 default 少頁 = layout 更緊湊
    if (r.pageDelta > 0) byCat[cat].pageLoss++;
  }
  console.log('\nPer-category:');
  for (const [cat, s] of Object.entries(byCat).sort()) {
    console.log(
      `  ${pad(cat, 18)} n=${s.n}  page-shift=${s.pageShift}  fp-diff=${s.fpDiff}` +
        `  page-gain(less)=${s.pageGain} page-loss(more)=${s.pageLoss}`,
    );
  }

  writeFileSync(
    REPORT_PATH,
    JSON.stringify({
      runAt: new Date().toISOString(),
      probe: 'sprint64_font_metrics_baseline_drift',
      totalFixtures: fixtures.length,
      driftPageCount,
      driftFingerprint,
      driftOpsCount,
      perCategory: byCat,
      perFixture: results,
    }, null, 2),
  );
  console.log(`\n→ ${REPORT_PATH}`);
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(2);
});
