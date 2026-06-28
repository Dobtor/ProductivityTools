#!/usr/bin/env node
/**
 * Sprint 14 — Visual Regression CLI（自家 pipeline 版）
 *
 * 與 visual_regression.mjs（Sprint 1 版，走 canvas-editor 老路）的差別：
 *   - 老路：parse_docx_cli → IElement[] JSON → canvas-editor harness 渲染
 *   - 新路：直接把 docx ArrayBuffer 餵進瀏覽器端 IIFE bundle
 *           （tools/dist/visual_regression_pipeline.iife.js），由 OoxmlParser →
 *           layoutDocument → CanvasRenderer + BrowserCanvasRenderContext 渲染到 <canvas>
 *
 * 為何兩條並存：
 *   - 老 251 份 PNG golden 是 canvas-editor 的渲染結果，跟我們 pipeline 的視覺風格不同
 *     （行高、字距、邊框 sub-pixel、shading 漸層皆有差）
 *   - Sprint 14 不假設「能立刻 0% diff」，反而是建立「自家 pipeline 的視覺基準（baseline）」
 *   - 後續 sprint（HarfBuzz / 註腳 / wrapTight…）讓 pipeline 趨近 golden，逐步收斂 diff%
 *   - 老 CLI 仍保留：可比對 canvas-editor 端的 IElement 邏輯本身有沒有改錯
 *
 * 用法：
 *   node scripts/visual_regression_v14.mjs                       # 全 fixture
 *   node scripts/visual_regression_v14.mjs --filter 01_simple    # 子集
 *   node scripts/visual_regression_v14.mjs --max-fixtures 3      # 只跑前 N 份
 *   node scripts/visual_regression_v14.mjs --no-diff             # 只渲染、不 pixelmatch
 *   node scripts/visual_regression_v14.mjs --max-diff 0.5        # diff 閾值（baseline 階段寬鬆）
 *
 * 退出碼：
 *   0   全部通過閾值（或 --no-diff 模式只渲染成功）
 *   1   有 fixture 超過閾值
 *   2   bundle 不存在 / fatal
 *
 * 輸出：
 *   tests/fixtures/.visual_regression_tmp/v14/<basename>-N.rendered.png
 *   tests/fixtures/<cat>/golden/<basename>-N_v14_diff.png（diff PNG）
 *   tests/fixtures/visual_regression_v14_report.json
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, '..');
const FIXTURE_ROOT = resolve(ROOT, 'tests/fixtures');
const BUNDLE = resolve(ROOT, 'tools/dist/visual_regression_pipeline.iife.js');
const HARNESS_HTML = resolve(ROOT, 'scripts/visual_regression_v14_harness.html');
const TMP_DIR = resolve(ROOT, 'tests/fixtures/.visual_regression_tmp/v14');
const REPORT_JSON = resolve(ROOT, 'tests/fixtures/visual_regression_v14_report.json');

function parseArgs(argv) {
  const args = {
    filter: null,
    maxFixtures: Number.POSITIVE_INFINITY,
    maxDiff: 0.5, // baseline 階段先寬鬆
    noDiff: false,
    headful: false,
    /** Sprint 61：開啟 BrowserTextMetrics（canvas.measureText 真實字寬）— 量 VR mean 改變 */
    browserMetrics: false,
    /**
     * Sprint 62: 開啟 FontMetricsAdapter + load LibreOffice 系統字型（DroidSansFallback + LiberationSerif）
     * Sprint 65: **default 改為 true**（commit Sprint 60-64 5 sprints data backing 後的 promote default-on）
     *   - 用 `--no-font-metrics` 退回 EstimateMetrics 0.074899 baseline（debug / 歷史對照）
     *   - production pipeline.render() 仍是 opt-in（caller 沒供 fontAdapter 就 fallback EstimateMetrics、與舊版相容）
     *   - 只有 VR script 預設啟用、用 LO 系統 fonts；對齊 goldens metric source
     */
    fontMetrics: true,
    /**
     * Sprint 162：開啟 tab stop 解析（settings.defaultTabStop → LineBreaker）。
     *   - 預設 false → tab 維持空白寬（baseline byte-identical 軌道）
     *   - `--tab-stops` 啟用 → Strategy C opt-in、量測含 tab fixture 的 VR delta
     */
    tabStops: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--filter') args.filter = argv[++i];
    else if (a === '--max-fixtures') args.maxFixtures = parseInt(argv[++i], 10);
    else if (a === '--max-diff') args.maxDiff = parseFloat(argv[++i]);
    else if (a === '--no-diff') args.noDiff = true;
    else if (a === '--headful') args.headful = true;
    else if (a === '--browser-metrics') args.browserMetrics = true;
    // Sprint 62 引入；Sprint 65 後 default = true（用 --no-font-metrics 退回）
    else if (a === '--font-metrics') args.fontMetrics = true;
    else if (a === '--no-font-metrics') args.fontMetrics = false;
    // Sprint 162：tab stop 解析 opt-in（Strategy C 量測用）
    else if (a === '--tab-stops') args.tabStops = true;
  }
  return args;
}

// Sprint 179：Phase 5 大三項 fixture 目錄（OMML / SmartArt / Charts parser 驗證用）。
// 非 VR baseline 的「42 fixture」成員、無 golden —— VR 不納入。
// Sprint 180+ 待 OMML / SmartArt / Charts render + golden 就緒後再評估納入。
// Sprint 202：11_perf_synthetic_large 為大檔 perf 量測用、VR 不納入（無 golden）。
const PHASE5_FIXTURE_DIRS = new Set(['07_chart', '08_smartart', '09_omml', '11_perf_synthetic_large']);

function listFixtures(filter) {
  const out = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
    if (cat.startsWith('.')) continue;
    if (PHASE5_FIXTURE_DIRS.has(cat)) continue;
    for (const f of readdirSync(catDir)) {
      if (!f.endsWith('.docx')) continue;
      const rel = `${cat}/${f}`;
      if (filter && !rel.includes(filter)) continue;
      out.push(rel);
    }
  }
  return out.sort();
}

function listGoldens(catDir, basename) {
  const goldenDir = resolve(catDir, 'golden');
  if (!existsSync(goldenDir)) return [];
  return readdirSync(goldenDir)
    .filter((f) => f.endsWith('.png') && !f.endsWith('_diff.png') && !f.endsWith('_v14_diff.png') && f.startsWith(`${basename}-`))
    .sort();
}

/** PNG crop / pad 到 (w, h)，避免 pixelmatch 尺寸不同 throw。 */
function cropOrPad(src, w, h) {
  if (src.width === w && src.height === h) return src;
  const out = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const dstOff = (y * w + x) * 4;
      if (x < src.width && y < src.height) {
        const srcOff = (y * src.width + x) * 4;
        out[dstOff] = src.data[srcOff];
        out[dstOff + 1] = src.data[srcOff + 1];
        out[dstOff + 2] = src.data[srcOff + 2];
        out[dstOff + 3] = src.data[srcOff + 3];
      } else {
        out[dstOff] = 255;
        out[dstOff + 1] = 255;
        out[dstOff + 2] = 255;
        out[dstOff + 3] = 255;
      }
    }
  }
  return { width: w, height: h, data: out };
}

async function main() {
  const args = parseArgs(process.argv);

  if (!existsSync(BUNDLE)) {
    console.error(`[fatal] Sprint 14 IIFE bundle 未編譯：${BUNDLE}`);
    console.error('       先跑 `npx rollup -c rollup.visual_regression.config.js`');
    process.exit(2);
  }
  if (!existsSync(HARNESS_HTML)) {
    console.error(`[fatal] harness HTML 缺：${HARNESS_HTML}`);
    process.exit(2);
  }

  let puppeteer = null;
  let pixelmatch = null;
  let PNG = null;
  try {
    puppeteer = (await import('puppeteer')).default;
    if (!args.noDiff) {
      pixelmatch = (await import('pixelmatch')).default;
      PNG = (await import('pngjs')).PNG;
    }
  } catch (err) {
    console.error('[fatal] puppeteer / pixelmatch / pngjs 未安裝：', err.message);
    process.exit(2);
  }

  const fixtures = listFixtures(args.filter).slice(0, args.maxFixtures);
  console.log(
    `[v14] 共 ${fixtures.length} fixture${args.filter ? ` (filter=${args.filter})` : ''}` +
      `，diff=${args.noDiff ? 'off' : `≤${args.maxDiff}`}`,
  );

  // Sprint 62：load LibreOffice 系統字型 bytes（與 LO 渲染 goldens 時使用的 fallback font 對齊）
  // - DroidSansFallbackFull.ttf → CJK 字元（標楷體 / 微軟正黑體 / 新細明體 fallback）
  // - LiberationSerif-Regular.ttf → Times New Roman fallback
  // 不在 fontMetrics 開時不 load（避免無用 I/O）
  let fontBytesBase64 = null;
  if (args.fontMetrics) {
    const fontPaths = {
      'Times New Roman': '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
      // 中文字 fallback：以 DroidSansFallback 對齊 LibreOffice CJK render
      // family 名同時註冊多個常用中文字型，layout 對任一族都查到同個 metrics
      '標楷體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      '微軟正黑體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      '新細明體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      '細明體': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      'DFKai-SB': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      'PMingLiU': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
      'MingLiU': '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    };
    fontBytesBase64 = {};
    for (const [family, path] of Object.entries(fontPaths)) {
      if (!existsSync(path)) {
        console.warn(`[v14] font not found: ${path}（skip ${family}）`);
        continue;
      }
      fontBytesBase64[family] = readFileSync(path).toString('base64');
    }
    const totalKB = Math.round(
      Object.values(fontBytesBase64).reduce((s, b64) => s + (b64.length * 3) / 4, 0) / 1024,
    );
    console.log(`[v14] --font-metrics: loaded ${Object.keys(fontBytesBase64).length} font families, ~${totalKB}KB`);
  }

  mkdirSync(TMP_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    headless: !args.headful,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const report = {
    runAt: new Date().toISOString(),
    pipeline: 'sprint14_dobtor',
    bundlePath: BUNDLE,
    maxDiffThreshold: args.noDiff ? null : args.maxDiff,
    totalFixtures: fixtures.length,
    rendered: 0,
    bootFailed: 0,
    comparedPages: 0,
    failedPages: 0,
    fixtures: [],
  };

  try {
    for (const rel of fixtures) {
      const [cat, filename] = rel.split('/');
      const basename = filename.replace(/\.docx$/, '');
      const docxPath = resolve(FIXTURE_ROOT, rel);
      const catDir = resolve(FIXTURE_ROOT, cat);

      const fxReport = {
        path: rel,
        bootOk: false,
        renderedPages: 0,
        warnings: [],
        pageResults: [],
      };

      const docxBuf = readFileSync(docxPath);
      const docxBase64 = docxBuf.toString('base64');

      const page = await browser.newPage();
      try {
        await page.setViewport({ width: 1240, height: 1754, deviceScaleFactor: 1 });
        const harnessUrl = `file://${HARNESS_HTML}`;
        await page.goto(harnessUrl, { waitUntil: 'load' });

        // 等 harness JS 跑完（IIFE bundle 載入 + __bootDobtorPipeline 已掛 window）
        await page.waitForFunction(
          () => typeof window.__bootDobtorPipeline === 'function' && !!window.__dobtorPipeline,
          { timeout: 15_000 },
        );

        // 灌 docx 進去渲染
        // Sprint 30：DPI 150 對齊 goldens（1241×1754 = A4 @ 150 DPI）
        // 之前用 96 DPI 渲出 794×1123，pixelmatch 把 golden crop 到 794×1123 等於只比較
        // 左上 64×64% 區域 → 02_std_table 週報 / 03_complex_table 等 fixture diff 達 0.4-0.64
        // （內容在 cropped 區域外完全 mismatch）。改 150 DPI 後 pixel 對齊正確
        const result = await page.evaluate(
          (b64, useBrowserMetrics, useFontMetrics, fontBytes, useTabStops) => {
            const opts = { dpi: 150 };
            if (useBrowserMetrics) opts.useBrowserMetrics = true;
            if (useFontMetrics && fontBytes) {
              opts.useFontMetrics = true;
              opts.fontBytes = fontBytes;
            }
            if (useTabStops) opts.enableTabStops = true;
            const r = window.__bootDobtorPipeline(b64, opts);
            return r;
          },
          docxBase64,
          args.browserMetrics,
          args.fontMetrics,
          fontBytesBase64,
          args.tabStops,
        );

        if (result.errorMsg) {
          fxReport.bootOk = false;
          fxReport.error = result.errorMsg.slice(0, 500);
          report.bootFailed++;
          console.log(`[v14] ${rel}  boot ✗  ${result.errorMsg.slice(0, 60)}`);
        } else {
          fxReport.bootOk = true;
          fxReport.renderedPages = result.pageCount;
          fxReport.warnings = result.warnings.slice(0, 10);
          report.rendered++;

          // 等 .ce-page DOM 就位
          await page.waitForSelector('.ce-page', { timeout: 10_000 }).catch(() => {});
          const pageHandles = await page.$$('.ce-page');

          // 截圖（無論 diff 是否做都產截圖，便於人工 review）
          for (let i = 0; i < pageHandles.length; i++) {
            const renderedPath = resolve(TMP_DIR, `${basename}-${i + 1}.rendered.png`);
            await pageHandles[i].screenshot({ path: renderedPath });

            if (!args.noDiff) {
              const goldens = listGoldens(catDir, basename);
              if (i < goldens.length) {
                const goldenName = goldens[i];
                const goldenPath = resolve(catDir, 'golden', goldenName);
                const diffPath = resolve(catDir, 'golden', `${basename}-${i + 1}_v14_diff.png`);
                try {
                  const goldenPng = PNG.sync.read(readFileSync(goldenPath));
                  const renderedPng = PNG.sync.read(readFileSync(renderedPath));
                  const w = Math.min(goldenPng.width, renderedPng.width);
                  const h = Math.min(goldenPng.height, renderedPng.height);
                  const diff = new PNG({ width: w, height: h });
                  const goldenCropped = cropOrPad(goldenPng, w, h);
                  const renderedCropped = cropOrPad(renderedPng, w, h);
                  const numDiff = pixelmatch(
                    goldenCropped.data,
                    renderedCropped.data,
                    diff.data,
                    w,
                    h,
                    { threshold: 0.1 },
                  );
                  const diffRatio = numDiff / (w * h);
                  const passed = diffRatio <= args.maxDiff;
                  fxReport.pageResults.push({
                    page: i + 1,
                    golden: goldenName,
                    diffRatio: Number(diffRatio.toFixed(5)),
                    passed,
                  });
                  if (!passed) {
                    writeFileSync(diffPath, PNG.sync.write(diff));
                    report.failedPages++;
                  }
                  report.comparedPages++;
                } catch (err) {
                  fxReport.pageResults.push({
                    page: i + 1,
                    golden: goldenName,
                    error: err.message,
                    passed: false,
                  });
                  report.failedPages++;
                  report.comparedPages++;
                }
              }
            }
          }
          const passedCount = fxReport.pageResults.filter((r) => r.passed).length;
          const totalCount = fxReport.pageResults.length;
          const meanDiff =
            totalCount > 0
              ? (
                  fxReport.pageResults.reduce((s, r) => s + (r.diffRatio || 0), 0) / totalCount
                ).toFixed(4)
              : '—';
          console.log(
            `[v14] ${rel}  pages=${result.pageCount}  diff=${args.noDiff ? '—' : `${passedCount}/${totalCount} pass, mean=${meanDiff}`}`,
          );
        }
      } finally {
        await page.close();
      }

      report.fixtures.push(fxReport);
    }
  } finally {
    await browser.close();
  }

  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2));
  console.log(
    `[v14] rendered=${report.rendered}/${report.totalFixtures}` +
      `  bootFailed=${report.bootFailed}` +
      `  comparedPages=${report.comparedPages}  failedPages=${report.failedPages}` +
      `\n     report=${REPORT_JSON}`,
  );

  if (!args.noDiff && report.failedPages > 0) process.exit(1);
  if (report.bootFailed > 0) process.exit(1);
  process.exit(0);
}

main().catch((err) => {
  console.error('[v14 fatal]', err);
  process.exit(2);
});
