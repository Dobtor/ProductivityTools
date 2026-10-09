#!/usr/bin/env node
/**
 * Sprint Y58 — C：15 份 ChienYi docx 端對端真實渲染驗證
 *
 * 設計原則（5/29 lesson）：「不要只看 audit 腳本數字」 — 跑真實 puppeteer + canvas-editor
 * UMD harness、實際輸出 PNG 截圖。
 *
 * 流程：
 *   1. 對 15 份 fixture（5 監造會議 + 5 週報 + 5 查驗）跑兩遍 parse_docx_cli：
 *        baseline = '--elements --svg-graphics'                              （Y58 兩 flag 都關）
 *        opt-in   = baseline + '--float-textbox --anchored-image'           （Y58 完整透傳）
 *   2. puppeteer 載 scripts/visual_regression_harness.html，把 IElement[] 餵進
 *      canvas-editor UMD bundle → 截 .ce-page DOM PNG，每份 fixture 兩組 PNG
 *   3. 計算指標：
 *        - txbx 文字 delta：opt-in 多出哪些 textbox 字串
 *        - anchor 透傳數量：opt-in IElement.anchor 出現次數
 *        - 視覺 diff：baseline vs opt-in PNG 的 pixelmatch ratio（不是 vs golden）
 *        - element count delta
 *   4. 產出：
 *        - tests/fixtures/.visual_regression_tmp/sprint_y58/<basename>_baseline-N.png
 *        - tests/fixtures/.visual_regression_tmp/sprint_y58/<basename>_opt-in-N.png
 *        - tests/fixtures/.visual_regression_tmp/sprint_y58/<basename>_y58_diff-N.png
 *        - tests/fixtures/sprint_y58_real_path_report.json
 *
 * 用法：
 *   node scripts/sprint_y58_real_path_e2e.mjs
 *   node scripts/sprint_y58_real_path_e2e.mjs --no-screenshot   # 跳過 puppeteer 階段
 *   node scripts/sprint_y58_real_path_e2e.mjs --max-fixtures 3  # 只跑前 N
 */

import { spawnSync } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, '..');
const FIXTURE_ROOT = resolve(ROOT, 'tests/fixtures');
const CLI = resolve(ROOT, 'tools/dist/parse_docx_cli.cjs');
// Sprint Y58 專用 harness（reuse production lib 載入順序：.umd.min + shim + plugin-docx）。
// 老 scripts/visual_regression_harness.html 已切到 canvas-editor-custom.umd.js（不同 global），
// boot 路徑失靈、無法用於 Y58 端對端視覺驗證。
const HARNESS_HTML = resolve(ROOT, 'scripts/sprint_y58_harness.html');
const TMP_DIR = resolve(FIXTURE_ROOT, '.visual_regression_tmp/sprint_y58');
const REPORT_JSON = resolve(FIXTURE_ROOT, 'sprint_y58_real_path_report.json');

// ── 15 份指定 fixture ───────────────────────────────────────────────────────

const FIXTURES_15 = [
  // 5 監造會議
  '01_simple/03.1120210-監造會議記錄-1120801.docx',
  '01_simple/03.1120815-監造會議記錄.docx', // Y57 audit 標的
  '01_simple/03.1120822-監造會議記錄.docx',
  '01_simple/03.1120829-監造會議記錄.docx',
  '01_simple/03.1120905-監造會議記錄.docx',
  // 5 週報
  '02_std_table/1120928-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  '02_std_table/1121006-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  '02_std_table/1121013-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  '02_std_table/1121020-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  '02_std_table/1121027-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
  // 5 查驗
  '03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx',
  '03_complex_table/1130105-全套管基樁混凝土查驗(共2).docx',
  '03_complex_table/1130109-全套管基樁混凝土查驗共(4).docx',
  '03_complex_table/1130112-全套管基樁混凝土查驗共(共3)(承辦).docx',
  '03_complex_table/1130516-共月橋P3帽梁鋼筋查驗.docx',
];

// ── argv ────────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const args = {
    noScreenshot: false,
    maxFixtures: Number.POSITIVE_INFINITY,
    /** Sprint Y58 C 重跑指標時 reuse 既有 IElement JSON + PNG，不再跑 CLI / puppeteer。 */
    reuseArtifacts: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--no-screenshot') args.noScreenshot = true;
    else if (a === '--reuse-artifacts') args.reuseArtifacts = true;
    else if (a === '--max-fixtures') args.maxFixtures = parseInt(argv[++i], 10);
  }
  return args;
}

// ── CLI 呼叫 ────────────────────────────────────────────────────────────────

function runCli(docxPath, jsonOut, extraFlags) {
  const argv = [CLI, docxPath, jsonOut, '--elements', '--svg-graphics', ...extraFlags];
  const proc = spawnSync('node', argv, { encoding: 'utf-8', timeout: 60_000 });
  return {
    ok: proc.status === 0,
    rc: proc.status,
    stdout: proc.stdout ?? '',
    stderr: proc.stderr ?? '',
  };
}

// ── IElement tree 遞迴 utility ─────────────────────────────────────────────

/**
 * 遞迴蒐集 IElement 樹中「真實文字」。
 *
 * 重要：跳過 `type === 'image'` 的 value（那是 base64 dataURL，非使用者可見文字；
 * 週報 fixture 內 wp:anchor 含嵌入圖片，opt-in 後展平會多 1 個 image element、
 * 對應 dataURL 約 500K，如果不跳過會誤判為「opt-in 多了 500K 字」）。
 */
function walkValues(node, out, kind) {
  if (Array.isArray(node)) {
    for (const c of node) walkValues(c, out, kind);
    return out;
  }
  if (node && typeof node === 'object') {
    const t = node.type;
    const isImage = t === 'image';
    const v = node.value;
    if (typeof v === 'string') {
      if (kind === 'text' && !isImage) out.push(v);
      else if (kind === 'image' && isImage) out.push(v);
    } else if (Array.isArray(v)) {
      for (const c of v) walkValues(c, out, kind);
    }
    for (const k of ['trList', 'tdList', 'valueList']) {
      const sub = node[k];
      if (Array.isArray(sub)) for (const c of sub) walkValues(c, out, kind);
    }
  }
  return out;
}

function flattenText(node) {
  return walkValues(node, [], 'text').join('');
}

function countImages(node) {
  return walkValues(node, [], 'image').length;
}

function countAnchored(node, acc = { total: 0, sources: {} }) {
  if (Array.isArray(node)) {
    for (const c of node) countAnchored(c, acc);
    return acc;
  }
  if (node && typeof node === 'object') {
    if (node.anchor && typeof node.anchor === 'object') {
      acc.total += 1;
      const src = node.anchor.source ?? 'unknown';
      acc.sources[src] = (acc.sources[src] ?? 0) + 1;
    }
    const v = node.value;
    if (Array.isArray(v)) for (const c of v) countAnchored(c, acc);
    for (const k of ['trList', 'tdList', 'valueList']) {
      const sub = node[k];
      if (Array.isArray(sub)) for (const c of sub) countAnchored(c, acc);
    }
  }
  return acc;
}

function elementCount(elements) {
  return Array.isArray(elements) ? elements.length : 0;
}

// ── puppeteer harness 渲染（reuse 老路 visual_regression_harness.html）────

async function renderAndShoot(browser, elements, outPrefix) {
  const page = await browser.newPage();
  const pagesShot = [];
  let bootError = null;
  try {
    await page.setViewport({ width: 1240, height: 1754, deviceScaleFactor: 1 });
    await page.goto(`file://${HARNESS_HTML}`, { waitUntil: 'load' });
    await page.waitForFunction(
      () => typeof window.__y58Boot === 'function',
      { timeout: 10_000 },
    );
    await page.evaluate((els) => {
      // eslint-disable-next-line no-undef
      window.__y58Boot(els);
    }, elements);
    // 等 boot 完成（__y58Ready 由 harness 在 canvas 出現或 error 後設）
    await page.waitForFunction(() => window.__y58Ready === true, {
      timeout: 30_000,
    });
    bootError = await page.evaluate(() => window.__y58Error ?? null);
    if (bootError) return { pagesShot, bootError };
    // 試 .ce-page (canvas-editor 分頁) 或退回 canvas 元素
    let pageHandles = await page.$$('.ce-page');
    if (pageHandles.length === 0) {
      // 退路：直接截 #ce-test-container 內所有 canvas（canvas-editor 0.9.x 結構變動安全網）
      pageHandles = await page.$$('#ce-test-container canvas');
    }
    for (let i = 0; i < pageHandles.length; i++) {
      const pngPath = `${outPrefix}-${i + 1}.png`;
      await pageHandles[i].screenshot({ path: pngPath });
      pagesShot.push(pngPath);
    }
    if (pageHandles.length === 0) {
      // 整頁 fallback（debug 用）
      const pngPath = `${outPrefix}-full.png`;
      await page.screenshot({ path: pngPath, fullPage: true });
      pagesShot.push(pngPath);
    }
  } finally {
    await page.close();
  }
  return { pagesShot, bootError };
}

// ── pixelmatch ─────────────────────────────────────────────────────────────

function diffPngs(baselinePath, optInPath, diffOut, pixelmatch, PNG) {
  if (!existsSync(baselinePath) || !existsSync(optInPath)) return null;
  const a = PNG.sync.read(readFileSync(baselinePath));
  const b = PNG.sync.read(readFileSync(optInPath));
  const w = Math.min(a.width, b.width);
  const h = Math.min(a.height, b.height);
  const diff = new PNG({ width: w, height: h });
  function crop(src) {
    if (src.width === w && src.height === h) return src.data;
    const out = new Uint8Array(w * h * 4);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const di = (y * w + x) * 4;
        const si = (y * src.width + x) * 4;
        out[di] = src.data[si];
        out[di + 1] = src.data[si + 1];
        out[di + 2] = src.data[si + 2];
        out[di + 3] = src.data[si + 3];
      }
    }
    return out;
  }
  const aData = crop(a);
  const bData = crop(b);
  const numDiff = pixelmatch(aData, bData, diff.data, w, h, { threshold: 0.1 });
  writeFileSync(diffOut, PNG.sync.write(diff));
  return { width: w, height: h, numDiff, ratio: numDiff / (w * h) };
}

// ── main ──────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv);
  if (!existsSync(CLI)) {
    console.error(`[fatal] CLI 未編譯：${CLI}\n       npm run build:cli`);
    process.exit(2);
  }
  if (!args.reuseArtifacts) {
    rmSync(TMP_DIR, { recursive: true, force: true });
  }
  mkdirSync(TMP_DIR, { recursive: true });

  const fixtures = FIXTURES_15.slice(0, args.maxFixtures);
  console.log(`[sprint_y58] 共 ${fixtures.length} fixture，screenshot=${!args.noScreenshot}`);

  let puppeteer = null;
  let pixelmatch = null;
  let PNG = null;
  let browser = null;
  if (!args.noScreenshot) {
    try {
      puppeteer = (await import('puppeteer')).default;
      pixelmatch = (await import('pixelmatch')).default;
      PNG = (await import('pngjs')).PNG;
    } catch (err) {
      console.error('[fatal] puppeteer / pixelmatch / pngjs 未安裝');
      process.exit(2);
    }
    browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
  }

  const report = {
    runAt: new Date().toISOString(),
    totalFixtures: fixtures.length,
    cliPath: CLI,
    harness: HARNESS_HTML,
    screenshotEnabled: !args.noScreenshot,
    summary: {
      parsedBoth: 0,
      textboxDeltaDocs: 0,
      anchorDeltaDocs: 0,
      imageDeltaDocs: 0,
      avgTextboxAddedChars: 0,
      avgTextboxAddedImages: 0,
      avgAnchorAdded: 0,
      avgVisualDiffRatio: null,
    },
    fixtures: [],
  };

  let totalTextboxAdded = 0;
  let totalImageAdded = 0;
  let totalAnchorAdded = 0;
  let visualDiffRatios = [];

  try {
    for (const rel of fixtures) {
      const [cat, filename] = rel.split('/');
      const basename = filename.replace(/\.docx$/, '');
      const docxPath = resolve(FIXTURE_ROOT, rel);
      const baselineJson = resolve(TMP_DIR, `${basename}_baseline.json`);
      const optInJson = resolve(TMP_DIR, `${basename}_optin.json`);

      const fxReport = { path: rel, baseline: {}, optIn: {}, delta: {} };
      report.fixtures.push(fxReport);

      // ── CLI pass 1: baseline ──
      if (!args.reuseArtifacts || !existsSync(baselineJson)) {
        const r1 = runCli(docxPath, baselineJson, []);
        if (!r1.ok) {
          fxReport.error = `baseline CLI rc=${r1.rc} stderr=${r1.stderr.slice(0, 200)}`;
          console.log(`[Y58] ${rel} baseline CLI ✗`);
          continue;
        }
      }
      // ── CLI pass 2: opt-in ──
      if (!args.reuseArtifacts || !existsSync(optInJson)) {
        const r2 = runCli(docxPath, optInJson, ['--float-textbox', '--anchored-image']);
        if (!r2.ok) {
          fxReport.error = `opt-in CLI rc=${r2.rc} stderr=${r2.stderr.slice(0, 200)}`;
          console.log(`[Y58] ${rel} opt-in CLI ✗`);
          continue;
        }
      }
      report.summary.parsedBoth += 1;

      const baselineElements = JSON.parse(readFileSync(baselineJson, 'utf-8'));
      const optInElements = JSON.parse(readFileSync(optInJson, 'utf-8'));

      // 基本指標
      const baselineText = flattenText(baselineElements);
      const optInText = flattenText(optInElements);
      const baselineAnchor = countAnchored(baselineElements);
      const optInAnchor = countAnchored(optInElements);

      const baselineImageCount = countImages(baselineElements);
      const optInImageCount = countImages(optInElements);
      fxReport.baseline = {
        elementCount: elementCount(baselineElements),
        textLength: baselineText.length,
        anchorTotal: baselineAnchor.total,
        imageCount: baselineImageCount,
      };
      fxReport.optIn = {
        elementCount: elementCount(optInElements),
        textLength: optInText.length,
        anchorTotal: optInAnchor.total,
        anchorSources: optInAnchor.sources,
        imageCount: optInImageCount,
      };

      // delta：opt-in 比 baseline 多出什麼（textboxAddedChars 已排除 image dataURL，
      // 故反映「真實使用者可見文字」的增量；imageAddedCount 獨立追蹤 textbox 內圖片）
      const textboxAdded = optInText.length - baselineText.length;
      const anchorAdded = optInAnchor.total - baselineAnchor.total;
      const elementAdded = elementCount(optInElements) - elementCount(baselineElements);
      const imageAdded = optInImageCount - baselineImageCount;

      // 頁碼/常見 textbox 字串檢出（Y57 fixture 已知會多出 "第X頁，共Y頁"）
      const pageNumRegex = /第[\s\d]*頁[，,][\s\d]*共[\s\d]*頁|第[\s\d]*頁，共[\s\d]*頁/g;
      const baselinePageNums = baselineText.match(pageNumRegex) ?? [];
      const optInPageNums = optInText.match(pageNumRegex) ?? [];

      fxReport.delta = {
        textboxAddedChars: textboxAdded,
        textboxAddedImages: imageAdded,
        anchorAddedCount: anchorAdded,
        elementAddedCount: elementAdded,
        pageNumBaseline: baselinePageNums.length,
        pageNumOptIn: optInPageNums.length,
        pageNumDiff: optInPageNums,
      };

      if (textboxAdded > 0) {
        report.summary.textboxDeltaDocs += 1;
        totalTextboxAdded += textboxAdded;
      }
      if (imageAdded > 0) {
        report.summary.imageDeltaDocs += 1;
        totalImageAdded += imageAdded;
      }
      if (anchorAdded > 0) {
        report.summary.anchorDeltaDocs += 1;
        totalAnchorAdded += anchorAdded;
      }

      // ── 截圖 + pixel diff ──
      if (browser) {
        try {
          const baselinePrefix = resolve(TMP_DIR, `${basename}_baseline`);
          const optInPrefix = resolve(TMP_DIR, `${basename}_optin`);
          const baselineResult = await renderAndShoot(browser, baselineElements, baselinePrefix);
          const optInResult = await renderAndShoot(browser, optInElements, optInPrefix);
          const baselinePngs = baselineResult.pagesShot;
          const optInPngs = optInResult.pagesShot;

          fxReport.screenshots = {
            baselinePages: baselinePngs.length,
            optInPages: optInPngs.length,
            pageDiffs: [],
          };
          if (baselineResult.bootError) fxReport.screenshots.baselineBootError = baselineResult.bootError;
          if (optInResult.bootError) fxReport.screenshots.optInBootError = optInResult.bootError;

          const numPages = Math.min(baselinePngs.length, optInPngs.length);
          for (let i = 0; i < numPages; i++) {
            const diffOut = resolve(TMP_DIR, `${basename}_y58_diff-${i + 1}.png`);
            const dr = diffPngs(baselinePngs[i], optInPngs[i], diffOut, pixelmatch, PNG);
            if (dr) {
              fxReport.screenshots.pageDiffs.push({
                page: i + 1,
                width: dr.width,
                height: dr.height,
                pixelDiff: dr.numDiff,
                ratio: dr.ratio,
              });
              visualDiffRatios.push(dr.ratio);
            }
          }
          console.log(
            `[Y58] ${rel}`
              + `  txDelta=${textboxAdded}c`
              + `  imgDelta=+${imageAdded}`
              + `  anchorDelta=+${anchorAdded}`
              + `  baseline=${baselinePngs.length}p`
              + `  optIn=${optInPngs.length}p`
              + (fxReport.screenshots.pageDiffs.length
                ? `  meanDiff=${(
                  fxReport.screenshots.pageDiffs.reduce((s, d) => s + d.ratio, 0)
                    / fxReport.screenshots.pageDiffs.length
                ).toFixed(4)}`
                : ''),
          );
        } catch (err) {
          fxReport.screenshotError = err.message ?? String(err);
          console.log(`[Y58] ${rel}  截圖 ✗  ${(err.message ?? '').slice(0, 80)}`);
        }
      } else {
        console.log(
          `[Y58] ${rel}  txDelta=${textboxAdded}c  imgDelta=+${imageAdded}`
            + `  anchorDelta=+${anchorAdded}  elDelta=${elementAdded}`,
        );
      }
    }
  } finally {
    if (browser) await browser.close();
  }

  // summary
  if (report.summary.textboxDeltaDocs > 0) {
    report.summary.avgTextboxAddedChars = Math.round(
      totalTextboxAdded / report.summary.textboxDeltaDocs,
    );
  }
  if (report.summary.imageDeltaDocs > 0) {
    report.summary.avgTextboxAddedImages = Math.round(
      (totalImageAdded / report.summary.imageDeltaDocs) * 100,
    ) / 100;
  }
  if (report.summary.anchorDeltaDocs > 0) {
    report.summary.avgAnchorAdded = Math.round(
      totalAnchorAdded / report.summary.anchorDeltaDocs,
    );
  }
  if (visualDiffRatios.length > 0) {
    report.summary.avgVisualDiffRatio =
      visualDiffRatios.reduce((s, r) => s + r, 0) / visualDiffRatios.length;
  }

  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2));
  console.log(`\n[sprint_y58] report → ${REPORT_JSON}`);
  console.log(JSON.stringify(report.summary, null, 2));
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(2);
});
