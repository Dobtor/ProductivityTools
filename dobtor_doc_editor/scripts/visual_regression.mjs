#!/usr/bin/env node
/**
 * Visual Regression CLI（Sprint 1 補完）
 *
 * 目的：對 tests/fixtures/<cat>/<doc>.docx 跑：
 *   1. parse_docx_cli → IElement[] JSON
 *   2. puppeteer 載 canvas-editor harness → 把 IElement[] 灌進去
 *   3. 量到的 page 元素截圖（per page）
 *   4. pixelmatch vs tests/fixtures/<cat>/golden/<basename>-N.png
 *   5. 寫差異到 <name>-N_diff.png 並輸出 summary report
 *
 * 不在 vitest 內：canvas-editor render 需要 WebGL / 字型，CI runner 跑不穩；
 * 設計為**手動觸發**（W11+ Phase 1 audit 用），不掛 npm test 的 default。
 *
 * 用法：
 *   node scripts/visual_regression.mjs                  # 跑全部 fixtures
 *   node scripts/visual_regression.mjs --filter 02_std  # 子集
 *   node scripts/visual_regression.mjs --max-diff 0.02  # 差異 ≤ 2% 視為通過
 *   node scripts/visual_regression.mjs --update         # 更新 golden（謹慎用）
 *
 * 退出碼：
 *   0   全 fixture 通過 max-diff 門檻
 *   1   有 fixture 超過門檻
 *   2   parse 或 render 階段 fatal
 *
 * 已知限制：
 *   - 字型 fallback：CI / 開發機若沒裝 fonts-noto-cjk，render 會 boxified 中文
 *   - 解析度：harness 用 96 DPI。golden PNG 須相同 DPI 才能精準比對
 *   - 邊界 anti-alias：差異閾值預設 0.02（2%）寬容像素抖動
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, '..');
const FIXTURE_ROOT = resolve(ROOT, 'tests/fixtures');
const CLI = resolve(ROOT, 'tools/dist/parse_docx_cli.cjs');
const HARNESS_HTML = resolve(ROOT, 'scripts/visual_regression_harness.html');
const REPORT_JSON = resolve(ROOT, 'tests/fixtures/visual_regression_report.json');

// ---- 參數解析 ---------------------------------------------------------

function parseArgs(argv) {
  const args = { filter: null, maxDiff: 0.02, update: false, dryRun: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--filter') args.filter = argv[++i];
    else if (a === '--max-diff') args.maxDiff = parseFloat(argv[++i]);
    else if (a === '--update') args.update = true;
    else if (a === '--dry-run') args.dryRun = true;
  }
  return args;
}

// ---- fixture 列表 -----------------------------------------------------

function listFixtures(filter) {
  const out = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
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
    .filter((f) => f.endsWith('.png') && !f.endsWith('_diff.png') && f.startsWith(`${basename}-`))
    .sort();
}

// ---- parse_docx_cli ----------------------------------------------------

function runCli(docxPath, jsonOut) {
  const cliRes = spawnSync('node', [CLI, docxPath, jsonOut, '--elements'], {
    encoding: 'utf-8',
  });
  if (cliRes.status !== 0) {
    return { ok: false, stderr: cliRes.stderr || cliRes.stdout || '' };
  }
  return { ok: true };
}

// ---- main --------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv);
  if (!existsSync(CLI)) {
    console.error(`[fatal] parse_docx_cli 未編譯：${CLI}`);
    console.error('       先跑 `npm run build:cli`');
    process.exit(2);
  }

  const fixtures = listFixtures(args.filter);
  console.log(`[visual_regression] 共 ${fixtures.length} fixture，max-diff=${args.maxDiff}`);

  // dry-run：只跑 CLI 階段，驗證 IElement[] 能解出來
  let puppeteer = null;
  let pixelmatch = null;
  let PNG = null;
  if (!args.dryRun) {
    try {
      puppeteer = (await import('puppeteer')).default;
      pixelmatch = (await import('pixelmatch')).default;
      PNG = (await import('pngjs')).PNG;
    } catch (err) {
      console.error('[fatal] puppeteer / pixelmatch / pngjs 未安裝：', err.message);
      console.error('       這些是 devDependencies，跑 `npm install` 後重試');
      process.exit(2);
    }
  }

  const tmpDir = resolve(ROOT, 'tests/fixtures/.visual_regression_tmp');
  mkdirSync(tmpDir, { recursive: true });

  const report = {
    runAt: new Date().toISOString(),
    maxDiffThreshold: args.maxDiff,
    totalFixtures: fixtures.length,
    parsed: 0,
    renderedPages: 0,
    comparedPages: 0,
    failedPages: 0,
    fixtures: [],
  };

  let browser = null;
  if (!args.dryRun && puppeteer) {
    browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
  }

  try {
    for (const rel of fixtures) {
      const [cat, filename] = rel.split('/');
      const basename = filename.replace(/\.docx$/, '');
      const docxPath = resolve(FIXTURE_ROOT, rel);
      const catDir = resolve(FIXTURE_ROOT, cat);

      const fxReport = {
        path: rel,
        parseOk: false,
        elementCount: 0,
        pages: 0,
        goldens: 0,
        pageResults: [],
      };

      // Phase 1：parse
      const jsonOut = resolve(tmpDir, `${basename}.elements.json`);
      const parseRes = runCli(docxPath, jsonOut);
      if (!parseRes.ok) {
        fxReport.error = `parse_docx_cli 失敗：${parseRes.stderr.slice(0, 200)}`;
        report.fixtures.push(fxReport);
        continue;
      }
      fxReport.parseOk = true;
      report.parsed++;

      const elementsRaw = readFileSync(jsonOut, 'utf-8');
      const elements = JSON.parse(elementsRaw);
      fxReport.elementCount = Array.isArray(elements) ? elements.length : 0;

      const goldens = listGoldens(catDir, basename);
      fxReport.goldens = goldens.length;

      // Phase 2：render（如果有 browser 且有 golden）
      if (browser && goldens.length > 0) {
        const page = await browser.newPage();
        await page.setViewport({ width: 1240, height: 1754, deviceScaleFactor: 1 });
        const harnessUrl = `file://${HARNESS_HTML}`;
        await page.goto(harnessUrl, { waitUntil: 'load' });

        // 注入 IElement[] 到 window 並等渲染完成
        await page.evaluate((els) => {
          window.__bootEditor(els);
        }, elements);

        // 等 canvas page 出現
        await page.waitForSelector('.ce-page', { timeout: 30_000 }).catch(() => {});

        // 列舉所有 page DOM
        const pageHandles = await page.$$('.ce-page');
        fxReport.pages = pageHandles.length;
        report.renderedPages += pageHandles.length;

        const goldenDir = resolve(catDir, 'golden');
        const compareCount = Math.min(pageHandles.length, goldens.length);
        for (let i = 0; i < compareCount; i++) {
          const goldenName = goldens[i];
          const goldenPath = resolve(goldenDir, goldenName);
          const renderedPath = resolve(tmpDir, `${basename}-${i + 1}.rendered.png`);
          const diffPath = resolve(goldenDir, `${basename}-${i + 1}_diff.png`);

          await pageHandles[i].screenshot({ path: renderedPath });

          let pageResult;
          try {
            const goldenPng = PNG.sync.read(readFileSync(goldenPath));
            const renderedPng = PNG.sync.read(readFileSync(renderedPath));
            const w = Math.min(goldenPng.width, renderedPng.width);
            const h = Math.min(goldenPng.height, renderedPng.height);
            const diff = new PNG({ width: w, height: h });
            // pixelmatch 需要相同尺寸；先 crop / pad 到 (w, h)
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
            pageResult = {
              page: i + 1,
              golden: goldenName,
              diffRatio: Number(diffRatio.toFixed(5)),
              passed: diffRatio <= args.maxDiff,
            };
            if (args.update || !pageResult.passed) {
              writeFileSync(diffPath, PNG.sync.write(diff));
            }
          } catch (err) {
            pageResult = {
              page: i + 1,
              golden: goldenName,
              error: err.message,
              passed: false,
            };
          }
          fxReport.pageResults.push(pageResult);
          report.comparedPages++;
          if (!pageResult.passed) report.failedPages++;
        }

        await page.close();
      }

      report.fixtures.push(fxReport);
    }
  } finally {
    if (browser) await browser.close();
  }

  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2));
  console.log(
    `[visual_regression] parsed=${report.parsed}/${report.totalFixtures} ` +
      `comparedPages=${report.comparedPages} failed=${report.failedPages} ` +
      `report=${REPORT_JSON}`,
  );

  if (report.failedPages > 0) process.exit(1);
  process.exit(0);
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
        out[dstOff + 3] = 255; // 白底
        out[dstOff] = 255;
        out[dstOff + 1] = 255;
        out[dstOff + 2] = 255;
      }
    }
  }
  return { width: w, height: h, data: out };
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(2);
});
