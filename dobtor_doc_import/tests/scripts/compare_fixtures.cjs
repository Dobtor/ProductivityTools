/**
 * compare_fixtures.js — Phase F 視覺基線 / 改進量化 pipeline
 *
 * 流程：
 *   1. puppeteer 登入 Odoo（POST /web/session/authenticate 取 session cookie）
 *   2. 對每份 fixture .docx：
 *        - 開 /dobtor_doc_editor/test?fixture=<rel>
 *        - 等 window.__canvasEditorReady === true
 *        - 對每張 .ce-page 截圖（每頁一張）
 *        - 與 tests/fixtures/<category>/golden/<name>-<page>.png 比對
 *   3. 輸出每份 fixture × 每頁 diff%；產出 markdown + JSON 報告
 *
 * 使用：
 *   node tests/scripts/compare_fixtures.js                    # 全跑
 *   node tests/scripts/compare_fixtures.js --category 03_complex_table
 *   node tests/scripts/compare_fixtures.js --fixture 送審管制
 *   node tests/scripts/compare_fixtures.js --probe            # 只跑 1 份做 DPI 校準
 *   node tests/scripts/compare_fixtures.js --debug            # 額外 dump 截圖元素資訊
 *   node tests/scripts/compare_fixtures.js --md-out docs/baseline_diff_report.md
 *
 * 環境變數：
 *   ODOO_URL=http://localhost:8069   (預設)
 *   ODOO_DB=odoo18_dev               (預設)
 *   ODOO_LOGIN=admin
 *   ODOO_PASSWORD=admin
 *   DEVICE_SCALE_FACTOR=1.5625       (150 DPI / 96 DPI 估算；--probe 後微調)
 *
 * 依賴（package.json devDeps）：
 *   puppeteer pixelmatch pngjs glob
 *
 * 前置條件（Phase F.1 已備）：
 *   - /dobtor_doc_editor/test 路由就緒（doc_controller.py:test_render）
 *   - test_harness.js 設 window.__canvasEditorReady（Phase F.1 已備）
 *   - tests/fixtures/<category>/golden/<name>-<page>.png 已產（make fixtures-golden 已跑）
 *
 * Phase F 設計理念：
 *   pipeline 不應 fail 任何 fixture（PASS_THRESHOLD = 1.0）；
 *   它的目的是「測量基線」，不是 gate。Phase 4 完成後重跑此 pipeline，
 *   比對 docs/baseline_diff_report.md vs docs/phase_4_diff_improvement.md
 *   才是真正的「品質改進量化」。
 */

'use strict';

const puppeteer = require('puppeteer');
// pixelmatch v7 是 pure ESM；require 時 transpiled CJS 介面把 default export 包在 .default
const pixelmatch = require('pixelmatch').default;
const { PNG } = require('pngjs');
const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// ── 設定 ─────────────────────────────────────────────────────────────────────

const ODOO_BASE_URL = process.env.ODOO_URL || 'http://localhost:8069';
const ODOO_DB = process.env.ODOO_DB || 'odoo18_dev';
const ODOO_LOGIN = process.env.ODOO_LOGIN || 'admin';
const ODOO_PASSWORD = process.env.ODOO_PASSWORD || 'admin';
const FONT_READY_TIMEOUT = 30000;
const DEVICE_SCALE_FACTOR = parseFloat(process.env.DEVICE_SCALE_FACTOR || '1.5625');

const FIXTURES_ROOT = path.resolve(__dirname, '../fixtures');

// canvas-editor v0.9.128 DOM 結構（probe_dom.cjs 實機確認）：
//   #ce-test-container > div[editor-component="main"] > div.ce-page-container > canvas[data-index="N"]
// 每張 canvas 為一頁，data-index 表示頁序（0-based）
// 內部尺寸 1240×1754（A4 at 150 DPI），CSS 顯示 794×1123（A4 at 96 DPI）
const CANVAS_PAGE_SELECTOR = 'div.ce-page-container canvas[data-index]';

// ── CLI 引數 ─────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
function arg(flag, def) {
  const i = args.indexOf(flag);
  return i >= 0 && i < args.length - 1 ? args[i + 1] : def;
}
function has(flag) { return args.includes(flag); }

const fixtureFilter = arg('--fixture');
const categoryFilter = arg('--category');
const debugMode = has('--debug');
const probeMode = has('--probe');
const outputMd = arg('--md-out', path.resolve(__dirname, '../../docs/baseline_diff_report.md'));
const outputJson = arg('--json-out');
const concurrency = Math.max(1, parseInt(arg('--parallel', '1'), 10));

// ── 工具函數 ──────────────────────────────────────────────────────────────────

function getGoldenPages(docxPath) {
  const dir = path.dirname(docxPath);
  const name = path.basename(docxPath, '.docx');
  const goldenDir = path.join(dir, 'golden');
  if (!fs.existsSync(goldenDir)) return [];

  return fs
    .readdirSync(goldenDir)
    .filter(f => f.startsWith(name + '-') && f.endsWith('.png') && !f.includes('_diff'))
    .sort((a, b) => {
      const pageOf = f => parseInt(f.match(/-(\d+)\.png$/)?.[1] ?? '0', 10);
      return pageOf(a) - pageOf(b);
    })
    .map(f => path.join(goldenDir, f));
}

function categoryOf(docxPath) {
  const rel = path.relative(FIXTURES_ROOT, docxPath);
  return rel.split(path.sep)[0];
}

async function loginAsAdmin(browser) {
  const page = await browser.newPage();
  // Odoo 18 JSON-RPC authenticate 設定 cookie
  const loginUrl = `${ODOO_BASE_URL}/web/session/authenticate`;
  await page.goto(`${ODOO_BASE_URL}/web/login`, { waitUntil: 'domcontentloaded' });
  const result = await page.evaluate(async (url, db, login, password) => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'call',
        params: { db, login, password },
      }),
    });
    return await resp.json();
  }, loginUrl, ODOO_DB, ODOO_LOGIN, ODOO_PASSWORD);

  await page.close();
  if (!result || !result.result || !result.result.uid) {
    throw new Error('Odoo login failed: ' + JSON.stringify(result).slice(0, 200));
  }
  return result.result.uid;
}

/**
 * 開啟 fixture 測試頁面，等 ready，截每頁 canvas
 * 回傳：[Buffer, ...] (每頁 PNG，依 data-index 排序)
 */
async function renderFixturePages(page, docxRel) {
  const url = `${ODOO_BASE_URL}/dobtor_doc_editor/test?fixture=${encodeURIComponent(docxRel)}`;
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });

  await page.waitForFunction(
    () => window.__canvasEditorReady === true,
    { timeout: FONT_READY_TIMEOUT }
  );
  await page.evaluate(() => document.fonts && document.fonts.ready);

  // 給 canvas-editor 多一拍時間完成所有頁的繪製（多頁文件可能 rAF 串行）
  await new Promise(r => setTimeout(r, 500));

  const handles = await page.$$(CANVAS_PAGE_SELECTOR);
  if (handles.length === 0) {
    throw new Error(`No canvas found (selector "${CANVAS_PAGE_SELECTOR}"). Page DOM may have changed.`);
  }

  if (debugMode) {
    const info = await page.evaluate((sel) =>
      Array.from(document.querySelectorAll(sel)).map(c => ({
        index: c.dataset.index,
        w: c.width, h: c.height,
        cssW: c.clientWidth, cssH: c.clientHeight,
      })), CANVAS_PAGE_SELECTOR
    );
    console.log(`    [debug] pages:`, JSON.stringify(info));
  }

  const screenshots = [];
  for (const h of handles) {
    const png = await h.screenshot({ encoding: 'binary' });
    screenshots.push(png);
  }
  return screenshots;
}

function comparePngs(goldenBuffer, renderedBuffer, diffOutputPath) {
  const golden = PNG.sync.read(goldenBuffer);
  const rendered = PNG.sync.read(renderedBuffer);

  // 尺寸不一致時：把較小的放大到較大尺寸（簡單 nearest-neighbor）以利比對
  // baseline 階段允許不嚴格對齊，重點是看百分比趨勢
  const w = Math.max(golden.width, rendered.width);
  const h = Math.max(golden.height, rendered.height);

  function fit(png) {
    if (png.width === w && png.height === h) return png;
    // nearest-neighbor scale
    const out = new PNG({ width: w, height: h });
    for (let y = 0; y < h; y++) {
      const sy = Math.floor(y * png.height / h);
      for (let x = 0; x < w; x++) {
        const sx = Math.floor(x * png.width / w);
        const s = (sy * png.width + sx) << 2;
        const t = (y * w + x) << 2;
        out.data[t]   = png.data[s];
        out.data[t+1] = png.data[s+1];
        out.data[t+2] = png.data[s+2];
        out.data[t+3] = png.data[s+3];
      }
    }
    return out;
  }

  const a = fit(golden);
  const b = fit(rendered);

  const diff = new PNG({ width: w, height: h });
  const numDiff = pixelmatch(
    a.data, b.data, diff.data, w, h,
    { threshold: 0.1, includeAA: false }
  );
  const ratio = numDiff / (w * h);

  if (diffOutputPath) {
    fs.writeFileSync(diffOutputPath, PNG.sync.write(diff));
  }
  return { ratio, w, h, sizeMatch: golden.width === rendered.width && golden.height === rendered.height };
}

// ── 主程式 ────────────────────────────────────────────────────────────────────

async function main() {
  let docxFiles = await glob('**/*.docx', { cwd: FIXTURES_ROOT, absolute: true, posix: false });
  docxFiles = docxFiles.filter(f => !f.includes(`${path.sep}golden${path.sep}`));

  if (categoryFilter) {
    docxFiles = docxFiles.filter(f => categoryOf(f) === categoryFilter);
  }
  if (fixtureFilter) {
    docxFiles = docxFiles.filter(f => f.includes(fixtureFilter));
  }
  if (probeMode) {
    docxFiles = docxFiles.slice(0, 1);
  }
  if (docxFiles.length === 0) {
    console.error('No fixture DOCX files found.');
    process.exit(1);
  }

  console.log('=== Phase F compare_fixtures.js ===');
  console.log(`Odoo URL     : ${ODOO_BASE_URL}`);
  console.log(`DB           : ${ODOO_DB}`);
  console.log(`Login        : ${ODOO_LOGIN}`);
  console.log(`Fixtures     : ${FIXTURES_ROOT}`);
  console.log(`Filter       : category=${categoryFilter ?? '(all)'} fixture=${fixtureFilter ?? '(all)'} probe=${probeMode}`);
  console.log(`Scale factor : ${DEVICE_SCALE_FACTOR}`);
  console.log(`Total        : ${docxFiles.length} fixtures\n`);

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  let uid;
  try {
    uid = await loginAsAdmin(browser);
    console.log(`Logged in as uid=${uid}\n`);
  } catch (e) {
    console.error('Login failed:', e.message);
    await browser.close();
    process.exit(1);
  }

  const results = [];

  for (let i = 0; i < docxFiles.length; i++) {
    const docxPath = docxFiles[i];
    const relFixture = path.relative(FIXTURES_ROOT, docxPath).split(path.sep).join('/');
    const goldenPages = getGoldenPages(docxPath);

    console.log(`[${i + 1}/${docxFiles.length}] ${relFixture}  (${goldenPages.length} golden page(s))`);

    if (goldenPages.length === 0) {
      console.log('    SKIP — no golden PNG (run generate_golden.sh)');
      results.push({ fixture: relFixture, error: 'no golden' });
      continue;
    }

    const page = await browser.newPage();
    await page.setViewport({
      width: 1400,
      height: 2000,
      deviceScaleFactor: DEVICE_SCALE_FACTOR,
    });

    let renderedPages;
    try {
      renderedPages = await renderFixturePages(page, relFixture);
    } catch (err) {
      console.error(`    RENDER ERROR: ${err.message}`);
      await page.close();
      results.push({ fixture: relFixture, error: err.message });
      continue;
    }
    await page.close();

    const pageResults = [];
    const N = Math.min(goldenPages.length, renderedPages.length);
    for (let p = 0; p < N; p++) {
      const goldenBuf = fs.readFileSync(goldenPages[p]);
      const renderedBuf = Buffer.from(renderedPages[p]);
      const diffPath = goldenPages[p].replace('.png', '_diff.png');
      const { ratio, w, h, sizeMatch } = comparePngs(goldenBuf, renderedBuf, diffPath);
      const pct = (ratio * 100).toFixed(1);
      const sizeNote = sizeMatch ? '' : ` (size mismatch, scaled to ${w}x${h})`;
      console.log(`    page ${p + 1}: ${pct}%${sizeNote}`);
      pageResults.push({ page: p + 1, ratio, sizeMatch });
    }
    if (renderedPages.length > N) {
      console.log(`    note: rendered has ${renderedPages.length - N} extra page(s) (split mismatch)`);
    } else if (goldenPages.length > N) {
      console.log(`    note: golden has ${goldenPages.length - N} extra page(s) (split mismatch)`);
    }

    results.push({
      fixture: relFixture,
      category: categoryOf(docxPath),
      goldenPages: goldenPages.length,
      renderedPages: renderedPages.length,
      pages: pageResults,
      meanDiff: pageResults.length ? pageResults.reduce((a, b) => a + b.ratio, 0) / pageResults.length : null,
    });
  }

  await browser.close();

  // ── 寫報告 ──────────────────────────────────────────────────────────────
  writeMarkdownReport(results, outputMd);
  if (outputJson) {
    fs.writeFileSync(outputJson, JSON.stringify(results, null, 2));
    console.log(`\nJSON report written: ${outputJson}`);
  }

  // 總結
  console.log('\n=== 總結 ===');
  const ok = results.filter(r => !r.error);
  const errors = results.filter(r => r.error);
  console.log(`Successfully measured: ${ok.length}/${results.length}`);
  console.log(`Errors                : ${errors.length}`);
  if (ok.length > 0) {
    const avgs = ok.map(r => r.meanDiff).filter(x => x !== null);
    if (avgs.length > 0) {
      avgs.sort((a, b) => a - b);
      console.log(`Mean diff (avg)       : ${(avgs.reduce((a, b) => a + b, 0) / avgs.length * 100).toFixed(1)}%`);
      console.log(`Median                : ${(avgs[Math.floor(avgs.length / 2)] * 100).toFixed(1)}%`);
      console.log(`Best                  : ${(avgs[0] * 100).toFixed(1)}%`);
      console.log(`Worst                 : ${(avgs[avgs.length - 1] * 100).toFixed(1)}%`);
    }
  }
  console.log(`Markdown report       : ${outputMd}`);
}

function writeMarkdownReport(results, outPath) {
  const lines = [];
  lines.push('# Phase F — Visual Baseline Diff Report');
  lines.push('');
  lines.push(`**生成時間**：${new Date().toISOString()}`);
  lines.push(`**Pipeline**：puppeteer + pixelmatch vs LibreOffice golden PNG`);
  lines.push(`**Odoo**：${ODOO_BASE_URL} (${ODOO_DB})`);
  lines.push(`**Scale factor**：${DEVICE_SCALE_FACTOR}`);
  lines.push('');
  lines.push('## 摘要');
  lines.push('');
  const ok = results.filter(r => !r.error);
  const errors = results.filter(r => r.error);
  lines.push(`- 成功：${ok.length} fixture`);
  lines.push(`- 錯誤：${errors.length} fixture`);
  const avgs = ok.map(r => r.meanDiff).filter(x => x !== null);
  if (avgs.length) {
    avgs.sort((a, b) => a - b);
    lines.push(`- 平均 diff%：${(avgs.reduce((a, b) => a + b, 0) / avgs.length * 100).toFixed(1)}%`);
    lines.push(`- 中位數：${(avgs[Math.floor(avgs.length / 2)] * 100).toFixed(1)}%`);
    lines.push(`- 最佳：${(avgs[0] * 100).toFixed(1)}%`);
    lines.push(`- 最差：${(avgs[avgs.length - 1] * 100).toFixed(1)}%`);
  }
  lines.push('');

  // 按 category 分組
  const byCat = {};
  for (const r of ok) {
    if (!r.category) continue;
    if (!byCat[r.category]) byCat[r.category] = [];
    byCat[r.category].push(r);
  }
  lines.push('## 各類別摘要');
  lines.push('');
  lines.push('| 類別 | 數量 | 平均 diff% | 最佳 | 最差 |');
  lines.push('|------|------|-----------|------|------|');
  for (const cat of Object.keys(byCat).sort()) {
    const arr = byCat[cat];
    const m = arr.map(x => x.meanDiff).filter(x => x !== null);
    if (m.length === 0) continue;
    m.sort((a, b) => a - b);
    const avg = m.reduce((a, b) => a + b, 0) / m.length * 100;
    lines.push(`| ${cat} | ${arr.length} | ${avg.toFixed(1)}% | ${(m[0] * 100).toFixed(1)}% | ${(m[m.length - 1] * 100).toFixed(1)}% |`);
  }
  lines.push('');

  // 完整逐 fixture 表
  lines.push('## 全 fixture 逐頁 diff%');
  lines.push('');
  lines.push('| Fixture | 類別 | Golden 頁 | Rendered 頁 | 各頁 diff% | 平均 |');
  lines.push('|---------|------|-----------|-------------|-----------|------|');
  for (const r of results) {
    if (r.error) {
      lines.push(`| ${r.fixture} | — | — | — | ERROR: ${r.error} | — |`);
      continue;
    }
    const perPage = r.pages.map(p => `${(p.ratio * 100).toFixed(1)}%${p.sizeMatch ? '' : '*'}`).join(', ');
    const avg = r.meanDiff !== null ? `${(r.meanDiff * 100).toFixed(1)}%` : '—';
    lines.push(`| ${r.fixture} | ${r.category} | ${r.goldenPages} | ${r.renderedPages} | ${perPage} | ${avg} |`);
  }
  lines.push('');
  lines.push('註：標 `*` 表示 golden 與 rendered 尺寸不符，已 nearest-neighbor 縮放後比對（diff% 偏高，並非真實差異）。');
  lines.push('');

  // 已知瓶頸/觀察（執行時補）
  lines.push('## 觀察（待執行後補充）');
  lines.push('');
  lines.push('- TBD：執行此 pipeline 後依結果填入主要瓶頸分類');
  lines.push('');

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, lines.join('\n'));
  console.log(`\nMarkdown report written: ${outPath}`);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
