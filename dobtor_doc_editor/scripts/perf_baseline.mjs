#!/usr/bin/env node
/**
 * Sprint 50 — Phase 7 效能基線量測（純診斷）
 *
 * 目的：
 *   規劃書 §11.16 路線 A（商業化先行）第一步 = 先量測再優化。
 *   對 42 份 fixture 跑完整 pipeline，拆 parse / layout / preload / render 四段耗時，
 *   定位「大文件變慢的瓶頸落在哪一段」，給 Sprint 51 的實際優化
 *   （可視頁虛擬化 / Web Worker parser / IndexedDB 快取 AST）定錨。
 *
 * 與 visual_regression_v14.mjs 的關係：
 *   共用同一個 IIFE bundle（tools/dist/visual_regression_pipeline.iife.js）與 harness HTML。
 *   差別：VR 比 pixel diff；本腳本只讀 result.timing（Sprint 50 加的純加性欄位），不截圖、不 diff。
 *
 * 量測方法：
 *   每份 fixture 開新 page、navigate harness、呼叫 __bootDobtorPipeline RUNS 次，
 *   取 totalMs 的中位數那一次（避免 JIT 冷啟動 / GC 抖動污染基線）。
 *
 * 用法：
 *   node scripts/perf_baseline.mjs                    # 全 42 fixture
 *   node scripts/perf_baseline.mjs --filter 04_with   # 子集
 *   node scripts/perf_baseline.mjs --runs 5           # 每份跑 5 次取中位數
 *   node scripts/perf_baseline.mjs --max-fixtures 3   # 只跑前 N 份
 *
 * 退出碼：0 正常；2 bundle/harness 缺或 puppeteer 未裝。
 *
 * 輸出：tests/fixtures/perf_baseline_report.json
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
const REPORT_JSON = resolve(ROOT, 'tests/fixtures/perf_baseline_report.json');

const DEFAULT_RUNS = 3;
const STAGES = ['parseMs', 'layoutMs', 'preloadMs', 'renderMs'];

function parseArgs(argv) {
  const args = {
    filter: null,
    maxFixtures: Number.POSITIVE_INFINITY,
    runs: DEFAULT_RUNS,
    headful: false,
    /** Sprint 51：開啟 in-memory AST cache 並量測 cold vs warm */
    cache: false,
    /** Sprint 52：開啟 IDB-backed AST cache，量測 cold vs warm-from-IDB（跨 page）*/
    cachePersist: false,
    /** Sprint 53：可視頁虛擬化模式 — 比較 baseline（無 virt）vs virt（prerenderPages=2）*/
    virtualize: false,
    /** Sprint 53：virtualize 模式下同步 paint 的前 N 頁（預設 2）*/
    prerenderPages: 2,
    /** Sprint 54：image decode cache 模式 — 同 page run0 cold（clear cache）/ run1+ warm */
    imageCache: false,
    /** Sprint 55：全 warm 組合模式 — 同時啟用 AST cache + image cache，量測 Sprint 51+54 疊加 */
    fullWarm: false,
    /** Sprint 56：ImageBitmap + IDB cache 模式 — 同 page run0 cold（clear cache）/ run1+ warm L1 */
    imageBitmapCache: false,
    /** Sprint 56：ImageBitmap + IDB persist 模式 — page1 cold（put L2）/ page2 fresh JS warm-from-L2 */
    imageBitmapPersist: false,
    /** Sprint 58：layout cache 模式 — 同 page run0 cold（clear cache）/ run1+ warm；通常與 --cache 合用 */
    layoutCache: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--filter') args.filter = argv[++i];
    else if (a === '--max-fixtures') args.maxFixtures = parseInt(argv[++i], 10);
    else if (a === '--runs') args.runs = parseInt(argv[++i], 10);
    else if (a === '--headful') args.headful = true;
    else if (a === '--cache') args.cache = true;
    else if (a === '--cache-persist') args.cachePersist = true;
    else if (a === '--virtualize') args.virtualize = true;
    else if (a === '--prerender-pages') args.prerenderPages = parseInt(argv[++i], 10);
    else if (a === '--image-cache') args.imageCache = true;
    else if (a === '--image-bitmap-cache') args.imageBitmapCache = true;
    else if (a === '--image-bitmap-persist') args.imageBitmapPersist = true;
    else if (a === '--layout-cache') args.layoutCache = true;
    else if (a === '--full-warm') {
      args.fullWarm = true;
      args.cache = true;
      args.imageCache = true;
      args.layoutCache = true; // Sprint 58：full-warm 含 layout cache 才是真正的全 warm
    }
  }
  return args;
}

function listFixtures(filter) {
  const out = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
    if (cat.startsWith('.')) continue;
    for (const f of readdirSync(catDir)) {
      if (!f.endsWith('.docx')) continue;
      const rel = `${cat}/${f}`;
      if (filter && !rel.includes(filter)) continue;
      out.push(rel);
    }
  }
  return out.sort();
}

/** 取中位數那一筆 timing（以 totalMs 排序，取中間索引）。 */
function medianRun(runs) {
  const sorted = [...runs].sort((a, b) => a.totalMs - b.totalMs);
  return sorted[Math.floor(sorted.length / 2)];
}

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s : s + ' '.repeat(n - s.length);
}
function padL(s, n) {
  s = String(s);
  return s.length >= n ? s : ' '.repeat(n - s.length) + s;
}
function ms(n) {
  return n.toFixed(1);
}

async function main() {
  const args = parseArgs(process.argv);

  if (!existsSync(BUNDLE)) {
    console.error(`[fatal] IIFE bundle 未編譯：${BUNDLE}`);
    console.error('       先跑 `npx rollup -c rollup.visual_regression.config.js`');
    process.exit(2);
  }
  if (!existsSync(HARNESS_HTML)) {
    console.error(`[fatal] harness HTML 缺：${HARNESS_HTML}`);
    process.exit(2);
  }

  let puppeteer = null;
  try {
    puppeteer = (await import('puppeteer')).default;
  } catch (err) {
    console.error('[fatal] puppeteer 未安裝：', err.message);
    process.exit(2);
  }

  const fixtures = listFixtures(args.filter).slice(0, args.maxFixtures);
  console.log(
    `[perf] 共 ${fixtures.length} fixture${args.filter ? ` (filter=${args.filter})` : ''}，每份 ${args.runs} 次取中位數`,
  );

  mkdirSync(dirname(REPORT_JSON), { recursive: true });

  const browser = await puppeteer.launch({
    headless: !args.headful,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const pipelineLabel = args.fullWarm
    ? 'sprint58_full_warm_with_layout_cache' // Sprint 58：full-warm 升級為含 layout cache
    : args.layoutCache
      ? 'sprint58_layout_cache_cold_vs_warm'
      : args.imageBitmapPersist
        ? 'sprint56_image_bitmap_idb_persist_cold_vs_warm_from_idb'
        : args.imageBitmapCache
          ? 'sprint56_image_bitmap_idb_cache_cold_vs_warm_l1'
          : args.imageCache
            ? 'sprint54_image_decode_cache_cold_vs_warm'
            : args.virtualize
              ? 'sprint53_page_virtualize_baseline_vs_virt'
              : args.cachePersist
                ? 'sprint52_idb_cache_cold_vs_warm_from_idb'
                : args.cache
                  ? 'sprint51_ast_cache_cold_vs_warm'
                  : 'sprint50_perf_baseline';
  const report = {
    runAt: new Date().toISOString(),
    pipeline: pipelineLabel,
    bundlePath: BUNDLE,
    cacheMode: args.cache,
    cachePersistMode: args.cachePersist,
    runsPerFixture: args.runs,
    totalFixtures: fixtures.length,
    measured: 0,
    bootFailed: 0,
    fixtures: [],
  };

  /** 開一個 page、navigate、跑 N 次 boot，回傳所有 timing + bootOk + pageCount。 */
  async function runBootsOnFreshPage(docxBase64, callOptsList) {
    const page = await browser.newPage();
    const out = { bootOk: false, error: null, pageCount: 0, imagesLoaded: 0, runs: [] };
    try {
      await page.setViewport({ width: 1240, height: 1754, deviceScaleFactor: 1 });
      await page.goto(`file://${HARNESS_HTML}`, { waitUntil: 'load' });
      await page.waitForFunction(
        () => typeof window.__bootDobtorPipeline === 'function' && !!window.__dobtorPipeline,
        { timeout: 15_000 },
      );
      for (const opts of callOptsList) {
        const result = await page.evaluate(
          (b64, o) => window.__bootDobtorPipeline(b64, o),
          docxBase64,
          opts,
        );
        if (result.errorMsg) {
          out.error = result.errorMsg.slice(0, 300);
          break;
        }
        out.bootOk = true;
        out.pageCount = result.pageCount;
        out.imagesLoaded = result.imagesLoaded || 0;
        out.runs.push(result.timing);
      }
    } catch (err) {
      out.error = String((err && (err.stack || err.message)) || err).slice(0, 300);
    } finally {
      await page.close();
    }
    return out;
  }

  try {
    for (const rel of fixtures) {
      const [cat, filename] = rel.split('/');
      const docxPath = resolve(FIXTURE_ROOT, rel);
      const fileSizeKB = Math.round(statSync(docxPath).size / 1024);
      const docxBase64 = readFileSync(docxPath).toString('base64');

      const fx = {
        rel,
        category: cat,
        fileSizeKB,
        bootOk: false,
        error: null,
        pageCount: 0,
        imagesLoaded: 0,
        runs: [],
        median: null,
        // Sprint 51：in-memory cache 模式時，run 0 = cold；run 1..N-1 = warm
        cold: null,
        warmMedian: null,
        // Sprint 52：persist mode 額外欄位（page1 cold IDB put / page2 fresh-JS warm-from-IDB / page2 L1-warm）
        warmFromIdb: null,
        warmFromL1: null,
        // Sprint 53：virtualize mode 額外欄位（page1 baseline 全 paint / page2 virt prerender=N）
        baseline: null,
        virt: null,
      };

      if (args.imageBitmapPersist) {
        // ── Sprint 56 image-bitmap-persist ── 跨 page IDB 持久化驗證（L2 hit cross-tab）
        // page1: cold（clear cache 清乾淨 L1+L2、decode + createImageBitmap + put L2 Blob）
        const page1 = await runBootsOnFreshPage(docxBase64, [
          { dpi: 150, useImageBitmapCache: true, clearImageBitmapCacheFirst: true },
        ]);
        if (!page1.bootOk) {
          fx.error = page1.error;
        } else {
          // page2: fresh JS context（L1 空），同 origin → IDB 還在 → run0 = L2 hit / run1 = L1 hit
          const page2 = await runBootsOnFreshPage(docxBase64, [
            { dpi: 150, useImageBitmapCache: true },
            { dpi: 150, useImageBitmapCache: true },
          ]);
          if (!page2.bootOk) {
            fx.error = page2.error;
          } else {
            fx.bootOk = true;
            fx.pageCount = page1.pageCount;
            fx.imagesLoaded = page1.imagesLoaded;
            fx.runs = [page1.runs[0], ...page2.runs];
            fx.cold = page1.runs[0];
            fx.warmFromIdb = page2.runs[0];
            fx.warmFromL1 = page2.runs[1];
            fx.median = fx.warmFromIdb;
          }
        }
      } else if (args.virtualize) {
        // ── Sprint 53 virtualize mode ── 比較 baseline (全 paint) vs virt (prerender=N)
        // page1: 無 virt（同 sprint 50 baseline 路徑）
        const page1 = await runBootsOnFreshPage(docxBase64, [{ dpi: 150 }]);
        if (!page1.bootOk) {
          fx.error = page1.error;
        } else {
          // page2: virt 啟用，prerenderPages = args.prerenderPages
          const page2 = await runBootsOnFreshPage(docxBase64, [
            { dpi: 150, useVirtualize: true, prerenderPages: args.prerenderPages },
          ]);
          if (!page2.bootOk) {
            fx.error = page2.error;
          } else {
            fx.bootOk = true;
            fx.pageCount = page1.pageCount;
            fx.imagesLoaded = page1.imagesLoaded;
            fx.runs = [page1.runs[0], page2.runs[0]];
            fx.baseline = page1.runs[0];
            fx.virt = page2.runs[0];
            fx.median = fx.virt;
          }
        }
      } else if (args.cachePersist) {
        // ── Sprint 52 persist mode ── 跨 page IDB 持久化驗證
        // page1: cold run（clearCacheFirst 清乾淨 L1+L2、parse、put L2）
        const page1 = await runBootsOnFreshPage(docxBase64, [
          { dpi: 150, useCache: true, cacheBackend: 'idb', clearCacheFirst: true },
        ]);
        if (!page1.bootOk) {
          fx.error = page1.error;
        } else {
          // page2: fresh JS context（L1 空），同 origin → IDB 還在 → run0 = L2 hit、run1 = L1 hit
          const page2 = await runBootsOnFreshPage(docxBase64, [
            { dpi: 150, useCache: true, cacheBackend: 'idb' },
            { dpi: 150, useCache: true, cacheBackend: 'idb' },
          ]);
          if (!page2.bootOk) {
            fx.error = page2.error;
          } else {
            fx.bootOk = true;
            fx.pageCount = page1.pageCount;
            fx.imagesLoaded = page1.imagesLoaded;
            fx.runs = [page1.runs[0], ...page2.runs];
            fx.cold = page1.runs[0];
            fx.warmFromIdb = page2.runs[0];
            fx.warmFromL1 = page2.runs[1];
            fx.median = fx.warmFromIdb; // 對既有彙總邏輯保持兼容
          }
        }
      } else {
        // 既有 single-page 路徑（baseline / Sprint 51 --cache / Sprint 54 --image-cache）
        const callOptsList = [];
        for (let r = 0; r < args.runs; r++) {
          const o = { dpi: 150 };
          if (args.cache) {
            o.useCache = true;
            o.clearCacheFirst = r === 0;
          }
          if (args.imageCache) {
            o.useImageCache = true;
            o.clearImageCacheFirst = r === 0;
          }
          if (args.imageBitmapCache) {
            o.useImageBitmapCache = true;
            o.clearImageBitmapCacheFirst = r === 0;
          }
          if (args.layoutCache) {
            // layoutCache 命中需要 AST cache（要 docx hash）；自動連動
            o.useCache = true;
            o.clearCacheFirst = r === 0 ? (o.clearCacheFirst ?? true) : false;
            o.useLayoutCache = true;
            o.clearLayoutCacheFirst = r === 0;
          }
          callOptsList.push(o);
        }
        const result = await runBootsOnFreshPage(docxBase64, callOptsList);
        fx.bootOk = result.bootOk;
        fx.error = result.error;
        fx.pageCount = result.pageCount;
        fx.imagesLoaded = result.imagesLoaded;
        fx.runs = result.runs;
      }

      if (fx.bootOk && fx.runs.length > 0) {
        if (args.virtualize || args.cachePersist || args.imageBitmapPersist) {
          // median 已在對應 branch 設好
        } else if ((args.cache || args.imageCache || args.imageBitmapCache) && fx.runs.length >= 2) {
          fx.cold = fx.runs[0];
          fx.warmMedian = medianRun(fx.runs.slice(1));
          fx.median = fx.warmMedian;
        } else {
          fx.median = medianRun(fx.runs);
        }
        report.measured++;
        if (args.imageBitmapPersist && fx.cold && fx.warmFromIdb && fx.warmFromL1) {
          const c = fx.cold;
          const wIdb = fx.warmFromIdb;
          const wL1 = fx.warmFromL1;
          const preloadIdbSpeedup = c.preloadMs / Math.max(wIdb.preloadMs, 0.001);
          const preloadL1Speedup = c.preloadMs / Math.max(wL1.preloadMs, 0.001);
          const idbHits = wIdb.imageBitmapCacheHits || 0;
          const l1Hits = wL1.imageBitmapCacheHits || 0;
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cold=${padL(ms(c.preloadMs), 7)}ms idb=${padL(ms(wIdb.preloadMs), 7)}ms l1=${padL(ms(wL1.preloadMs), 7)}ms` +
              ` idb=${padL(preloadIdbSpeedup.toFixed(1) + 'x', 5)} l1=${padL(preloadL1Speedup.toFixed(1) + 'x', 5)}` +
              ` (idbHits=${idbHits}/${fx.imagesLoaded || 0} l1Hits=${l1Hits})`,
          );
        } else if (args.imageBitmapCache && fx.cold && fx.warmMedian) {
          const c = fx.cold;
          const w = fx.warmMedian;
          const preloadSpeedup = c.preloadMs / Math.max(w.preloadMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cPreload=${padL(ms(c.preloadMs), 6)}ms wPreload=${padL(ms(w.preloadMs), 6)}ms` +
              ` speedup=${padL(preloadSpeedup.toFixed(1) + 'x', 6)}` +
              ` (warm bitmapHits=${w.imageBitmapCacheHits || 0}/${fx.imagesLoaded || 0})`,
          );
        } else if (args.virtualize && fx.baseline && fx.virt) {
          const b = fx.baseline;
          const v = fx.virt;
          const speedup = b.renderMs / Math.max(v.renderMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` baseRender=${padL(ms(b.renderMs), 7)}ms virtRender=${padL(ms(v.renderMs), 7)}ms` +
              ` speedup=${padL(speedup.toFixed(1) + 'x', 5)}` +
              ` (painted=${v.paintedPages}/${fx.pageCount})`,
          );
        } else if (args.cachePersist && fx.cold && fx.warmFromIdb && fx.warmFromL1) {
          const c = fx.cold;
          const wIdb = fx.warmFromIdb;
          const wL1 = fx.warmFromL1;
          const speedupIdb = c.totalMs / Math.max(wIdb.totalMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cold=${padL(ms(c.totalMs), 7)}ms idb=${padL(ms(wIdb.totalMs), 7)}ms l1=${padL(ms(wL1.totalMs), 7)}ms` +
              ` idbSpeedup=${padL(speedupIdb.toFixed(1) + 'x', 5)}` +
              ` (cold parse=${ms(c.parseMs)} / idb parse=${ms(wIdb.parseMs)} hash=${ms(wIdb.hashMs)})`,
          );
        } else if (args.fullWarm && fx.cold && fx.warmMedian) {
          const c = fx.cold;
          const w = fx.warmMedian;
          const totalSpeedup = c.totalMs / Math.max(w.totalMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cold=${padL(ms(c.totalMs), 7)}ms warm=${padL(ms(w.totalMs), 7)}ms` +
              ` speedup=${padL(totalSpeedup.toFixed(2) + 'x', 6)}` +
              ` (parse ${ms(c.parseMs)}→${ms(w.parseMs)} / preload ${ms(c.preloadMs)}→${ms(w.preloadMs)} / render ${ms(c.renderMs)}→${ms(w.renderMs)})`,
          );
        } else if (args.imageCache && fx.cold && fx.warmMedian) {
          const c = fx.cold;
          const w = fx.warmMedian;
          const preloadSpeedup = c.preloadMs / Math.max(w.preloadMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cPreload=${padL(ms(c.preloadMs), 6)}ms wPreload=${padL(ms(w.preloadMs), 6)}ms` +
              ` speedup=${padL(preloadSpeedup.toFixed(1) + 'x', 6)}` +
              ` (warm imgHits=${w.imageCacheHits}/${fx.imagesLoaded || 0})`,
          );
        } else if (args.cache && fx.cold && fx.warmMedian) {
          const c = fx.cold;
          const w = fx.warmMedian;
          const speedup = c.totalMs / Math.max(w.totalMs, 0.001);
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` cold=${padL(ms(c.totalMs), 7)}ms warm=${padL(ms(w.totalMs), 7)}ms` +
              ` speedup=${padL(speedup.toFixed(1) + 'x', 5)}` +
              ` (cold parse=${ms(c.parseMs)} / warm parse=${ms(w.parseMs)} hash=${ms(w.hashMs)})`,
          );
        } else {
          const m = fx.median;
          const perPage = fx.pageCount > 0 ? m.totalMs / fx.pageCount : 0;
          console.log(
            `[perf] ${pad(rel, 56)} ${padL(fileSizeKB + 'KB', 8)} ${padL(fx.pageCount + 'p', 5)}` +
              ` total=${padL(ms(m.totalMs), 8)}ms` +
              ` (parse=${ms(m.parseMs)} layout=${ms(m.layoutMs)} preload=${ms(m.preloadMs)} render=${ms(m.renderMs)})` +
              ` ${padL(ms(perPage), 7)}ms/p`,
          );
        }
      } else {
        report.bootFailed++;
        console.log(`[perf] ${pad(rel, 56)} boot ✗  ${(fx.error || '').slice(0, 60)}`);
      }
      report.fixtures.push(fx);
    }
  } finally {
    await browser.close();
  }

  // ---- 彙總：分類聚合 + 瓶頸定位 ----
  const measured = report.fixtures.filter((f) => f.median);
  const byCat = {};
  for (const f of measured) {
    const c = (byCat[f.category] ??= {
      count: 0,
      fileSizeKB: 0,
      pageCount: 0,
      parseMs: 0,
      layoutMs: 0,
      preloadMs: 0,
      renderMs: 0,
      totalMs: 0,
    });
    c.count++;
    c.fileSizeKB += f.fileSizeKB;
    c.pageCount += f.pageCount;
    for (const s of STAGES) c[s] += f.median[s];
    c.totalMs += f.median.totalMs;
  }

  const grand = { parseMs: 0, layoutMs: 0, preloadMs: 0, renderMs: 0, totalMs: 0 };
  for (const f of measured) {
    for (const s of STAGES) grand[s] += f.median[s];
    grand.totalMs += f.median.totalMs;
  }

  console.log('\n=== 分類聚合（median 加總）===');
  console.log(
    `${pad('category', 18)}${padL('n', 4)}${padL('totalMs', 11)}${padL('parse%', 9)}` +
      `${padL('layout%', 9)}${padL('preload%', 10)}${padL('render%', 9)}`,
  );
  for (const [cat, c] of Object.entries(byCat).sort()) {
    const pct = (v) => ((v / c.totalMs) * 100).toFixed(1) + '%';
    console.log(
      `${pad(cat, 18)}${padL(c.count, 4)}${padL(ms(c.totalMs), 11)}` +
        `${padL(pct(c.parseMs), 9)}${padL(pct(c.layoutMs), 9)}${padL(pct(c.preloadMs), 10)}${padL(pct(c.renderMs), 9)}`,
    );
  }

  console.log('\n=== 全域瓶頸（42 fixture median 加總占比）===');
  const stageShare = STAGES.map((s) => ({ stage: s, ms: grand[s], pct: (grand[s] / grand.totalMs) * 100 })).sort(
    (a, b) => b.ms - a.ms,
  );
  for (const ss of stageShare) {
    console.log(`  ${pad(ss.stage, 10)} ${padL(ms(ss.ms), 11)}ms  ${ss.pct.toFixed(1)}%`);
  }
  const bottleneck = stageShare[0];
  console.log(`  → 瓶頸 = ${bottleneck.stage}（占 ${bottleneck.pct.toFixed(1)}%）`);

  // 最慢 5 份
  console.log('\n=== 最慢 5 份 fixture（median totalMs）===');
  const slowest = [...measured].sort((a, b) => b.median.totalMs - a.median.totalMs).slice(0, 5);
  for (const f of slowest) {
    console.log(`  ${pad(f.rel, 56)} ${padL(ms(f.median.totalMs), 9)}ms  ${f.fileSizeKB}KB ${f.pageCount}p`);
  }

  // Sprint 56：image-bitmap-persist 模式 → cold / warm-from-IDB / warm-from-L1 聚合
  let imageBitmapPersistSummary = null;
  if (args.imageBitmapPersist) {
    const arr = report.fixtures.filter((f) => f.cold && f.warmFromIdb && f.warmFromL1);
    let coldPreload = 0,
      idbPreload = 0,
      l1Preload = 0,
      coldTotal = 0,
      idbTotal = 0,
      l1Total = 0,
      idbHitsSum = 0,
      l1HitsSum = 0,
      imgsSum = 0;
    for (const f of arr) {
      coldPreload += f.cold.preloadMs;
      idbPreload += f.warmFromIdb.preloadMs;
      l1Preload += f.warmFromL1.preloadMs;
      coldTotal += f.cold.totalMs;
      idbTotal += f.warmFromIdb.totalMs;
      l1Total += f.warmFromL1.totalMs;
      idbHitsSum += f.warmFromIdb.imageBitmapCacheHits || 0;
      l1HitsSum += f.warmFromL1.imageBitmapCacheHits || 0;
      imgsSum += f.imagesLoaded || 0;
    }
    const preloadIdbSpeedup = coldPreload / Math.max(idbPreload, 0.001);
    const preloadL1Speedup = coldPreload / Math.max(l1Preload, 0.001);
    const totalIdbSpeedup = coldTotal / Math.max(idbTotal, 0.001);
    const totalL1Speedup = coldTotal / Math.max(l1Total, 0.001);
    imageBitmapPersistSummary = {
      n: arr.length,
      coldPreloadMs: coldPreload,
      warmFromIdbPreloadMs: idbPreload,
      warmFromL1PreloadMs: l1Preload,
      coldTotalMs: coldTotal,
      warmFromIdbTotalMs: idbTotal,
      warmFromL1TotalMs: l1Total,
      idbHits: idbHitsSum,
      l1Hits: l1HitsSum,
      imagesLoaded: imgsSum,
      preloadIdbSpeedup,
      preloadL1Speedup,
      totalIdbSpeedup,
      totalL1Speedup,
    };
    console.log('\n=== Sprint 56 image-bitmap-persist：cold / warm-from-IDB / warm-from-L1（42 fixture 加總）===');
    console.log(`  cold preload:         ${ms(coldPreload)}ms   total: ${ms(coldTotal)}ms`);
    console.log(`  warm-from-IDB preload: ${ms(idbPreload)}ms   total: ${ms(idbTotal)}ms`);
    console.log(`  warm-from-L1 preload:  ${ms(l1Preload)}ms   total: ${ms(l1Total)}ms`);
    console.log(`  → preload speedup: IDB ${preloadIdbSpeedup.toFixed(2)}x / L1 ${preloadL1Speedup.toFixed(2)}x`);
    console.log(`  → total speedup:   IDB ${totalIdbSpeedup.toFixed(2)}x / L1 ${totalL1Speedup.toFixed(2)}x`);
    console.log(`  → bitmap hits: IDB=${idbHitsSum} / L1=${l1HitsSum} / images=${imgsSum}`);
    console.log(`  → L1 是否優於 L2：${l1Preload < idbPreload ? `是（差 ${ms(idbPreload - l1Preload)}ms = IDB+decode 開銷）` : '否'}`);
  }

  // Sprint 56：image-bitmap-cache 模式 → cold vs warm preload 聚合（L1 only path）
  let imageBitmapCacheSummary = null;
  if (args.imageBitmapCache && !args.imageBitmapPersist) {
    const arr = report.fixtures.filter((f) => f.cold && f.warmMedian);
    let coldPreload = 0,
      warmPreload = 0,
      coldTotal = 0,
      warmTotal = 0,
      hitsSum = 0,
      imgsSum = 0;
    for (const f of arr) {
      coldPreload += f.cold.preloadMs;
      warmPreload += f.warmMedian.preloadMs;
      coldTotal += f.cold.totalMs;
      warmTotal += f.warmMedian.totalMs;
      hitsSum += f.warmMedian.imageBitmapCacheHits || 0;
      imgsSum += f.imagesLoaded || 0;
    }
    const preloadSpeedup = coldPreload / Math.max(warmPreload, 0.001);
    const totalSpeedup = coldTotal / Math.max(warmTotal, 0.001);
    imageBitmapCacheSummary = {
      n: arr.length,
      coldPreloadMs: coldPreload,
      warmPreloadMs: warmPreload,
      coldTotalMs: coldTotal,
      warmTotalMs: warmTotal,
      bitmapCacheHits: hitsSum,
      imagesLoaded: imgsSum,
      preloadSpeedup,
      totalSpeedup,
    };
    console.log('\n=== Sprint 56 image-bitmap-cache：cold vs warm preload（42 fixture 加總，L1 only）===');
    console.log(`  cold preload: ${ms(coldPreload)}ms   total: ${ms(coldTotal)}ms`);
    console.log(`  warm preload: ${ms(warmPreload)}ms   total: ${ms(warmTotal)}ms`);
    console.log(`  → preload speedup = ${preloadSpeedup.toFixed(2)}x   total speedup = ${totalSpeedup.toFixed(2)}x`);
    console.log(`  → warm bitmap cache hits = ${hitsSum} / images loaded (cold) = ${imgsSum}`);
  }

  // Sprint 55+58：full-warm 模式 → cold vs warm（含 layout cache）
  let fullWarmSummary = null;
  if (args.fullWarm) {
    const arr = report.fixtures.filter((f) => f.cold && f.warmMedian);
    const sum = (key) => arr.reduce((s, f) => s + (f.cold[key] || 0), 0);
    const sumW = (key) => arr.reduce((s, f) => s + (f.warmMedian[key] || 0), 0);
    const coldTotal = sum('totalMs');
    const warmTotal = sumW('totalMs');
    const coldParse = sum('parseMs');
    const warmParse = sumW('parseMs');
    const coldLayout = sum('layoutMs');
    const warmLayout = sumW('layoutMs');
    const coldPreload = sum('preloadMs');
    const warmPreload = sumW('preloadMs');
    const coldRender = sum('renderMs');
    const warmRender = sumW('renderMs');
    const warmHash = sumW('hashMs');
    const totalSpeedup = coldTotal / Math.max(warmTotal, 0.001);
    const layoutHits = arr.filter((f) => f.warmMedian.layoutCacheHit).length;
    fullWarmSummary = {
      n: arr.length,
      coldTotalMs: coldTotal,
      warmTotalMs: warmTotal,
      coldParseMs: coldParse,
      warmParseMs: warmParse,
      coldLayoutMs: coldLayout,
      warmLayoutMs: warmLayout,
      coldPreloadMs: coldPreload,
      warmPreloadMs: warmPreload,
      coldRenderMs: coldRender,
      warmRenderMs: warmRender,
      warmHashMs: warmHash,
      layoutCacheHits: layoutHits,
      totalSpeedup,
    };
    console.log('\n=== Sprint 58 full-warm (AST + layout + image cache 合用)：cold vs warm（42 fixture 加總）===');
    console.log(`  cold total:   ${ms(coldTotal)}ms  (parse ${ms(coldParse)} / layout ${ms(coldLayout)} / preload ${ms(coldPreload)} / render ${ms(coldRender)})`);
    console.log(`  warm total:   ${ms(warmTotal)}ms  (parse ${ms(warmParse)} / layout ${ms(warmLayout)} / preload ${ms(warmPreload)} / render ${ms(warmRender)} / hash ${ms(warmHash)})`);
    console.log(`  → total speedup = ${totalSpeedup.toFixed(2)}x`);
    console.log(
      `  → 階段消除程度：parse ${((1 - warmParse / Math.max(coldParse, 0.001)) * 100).toFixed(1)}%` +
        ` / layout ${((1 - warmLayout / Math.max(coldLayout, 0.001)) * 100).toFixed(1)}%` +
        ` / preload ${((1 - warmPreload / Math.max(coldPreload, 0.001)) * 100).toFixed(1)}%` +
        ` / render ${((1 - warmRender / Math.max(coldRender, 0.001)) * 100).toFixed(1)}%`,
    );
    console.log(`  → layout cache hits: ${layoutHits}/${arr.length} fixture warm runs`);
  }

  // Sprint 54：image-cache 模式 → cold vs warm preload 聚合（fullWarm 已有自己 summary，不重複）
  let imageCacheSummary = null;
  if (args.imageCache && !args.fullWarm) {
    const withImg = report.fixtures.filter((f) => f.cold && f.warmMedian);
    let coldPreload = 0,
      warmPreload = 0,
      coldTotal = 0,
      warmTotal = 0,
      hitsSum = 0,
      imgsSum = 0;
    for (const f of withImg) {
      coldPreload += f.cold.preloadMs;
      warmPreload += f.warmMedian.preloadMs;
      coldTotal += f.cold.totalMs;
      warmTotal += f.warmMedian.totalMs;
      hitsSum += f.warmMedian.imageCacheHits || 0;
      imgsSum += f.imagesLoaded || 0;
    }
    const preloadSpeedup = coldPreload / Math.max(warmPreload, 0.001);
    const totalSpeedup = coldTotal / Math.max(warmTotal, 0.001);
    imageCacheSummary = {
      n: withImg.length,
      coldPreloadMs: coldPreload,
      warmPreloadMs: warmPreload,
      coldTotalMs: coldTotal,
      warmTotalMs: warmTotal,
      imageCacheHits: hitsSum,
      imagesLoaded: imgsSum,
      preloadSpeedup,
      totalSpeedup,
    };
    console.log('\n=== Sprint 54 image decode cache：cold vs warm preload（42 fixture 加總）===');
    console.log(`  cold preload: ${ms(coldPreload)}ms   total: ${ms(coldTotal)}ms`);
    console.log(`  warm preload: ${ms(warmPreload)}ms   total: ${ms(warmTotal)}ms`);
    console.log(`  → preload speedup = ${preloadSpeedup.toFixed(2)}x   total speedup = ${totalSpeedup.toFixed(2)}x`);
    console.log(`  → warm image cache hits = ${hitsSum} / images loaded (cold) = ${imgsSum}`);
  }

  // Sprint 53：virtualize 模式 → baseline vs virt 聚合
  let virtSummary = null;
  if (args.virtualize) {
    const withVirt = report.fixtures.filter((f) => f.baseline && f.virt);
    let baseRender = 0,
      baseTotal = 0,
      virtRender = 0,
      virtTotal = 0,
      paintedSum = 0,
      pageSum = 0;
    for (const f of withVirt) {
      baseRender += f.baseline.renderMs;
      baseTotal += f.baseline.totalMs;
      virtRender += f.virt.renderMs;
      virtTotal += f.virt.totalMs;
      paintedSum += f.virt.paintedPages;
      pageSum += f.pageCount;
    }
    const renderSpeedup = baseRender / Math.max(virtRender, 0.001);
    const totalSpeedup = baseTotal / Math.max(virtTotal, 0.001);
    virtSummary = {
      n: withVirt.length,
      prerenderPages: args.prerenderPages,
      baselineRenderMs: baseRender,
      virtRenderMs: virtRender,
      baselineTotalMs: baseTotal,
      virtTotalMs: virtTotal,
      paintedPagesSum: paintedSum,
      totalPages: pageSum,
      renderSpeedup,
      totalSpeedup,
    };
    console.log('\n=== Sprint 53 page virtualize：baseline vs virt（42 fixture 加總，prerender=' + args.prerenderPages + '）===');
    console.log(`  baseline render: ${ms(baseRender)}ms   total: ${ms(baseTotal)}ms`);
    console.log(`  virt render:     ${ms(virtRender)}ms   total: ${ms(virtTotal)}ms`);
    console.log(`  → render speedup = ${renderSpeedup.toFixed(2)}x   total speedup = ${totalSpeedup.toFixed(2)}x`);
    console.log(`  → 同步 paint = ${paintedSum}/${pageSum} 頁（其餘 ${pageSum - paintedSum} 頁延後到 IntersectionObserver 觸發）`);
  }

  // Sprint 52：cache-persist 模式 → cold / warm-from-IDB / warm-from-L1 聚合
  let cachePersistSummary = null;
  if (args.cachePersist) {
    const withPersist = report.fixtures.filter((f) => f.cold && f.warmFromIdb && f.warmFromL1);
    let coldTotal = 0,
      idbTotal = 0,
      l1Total = 0,
      coldParse = 0,
      idbParse = 0,
      idbHash = 0;
    for (const f of withPersist) {
      coldTotal += f.cold.totalMs;
      idbTotal += f.warmFromIdb.totalMs;
      l1Total += f.warmFromL1.totalMs;
      coldParse += f.cold.parseMs;
      idbParse += f.warmFromIdb.parseMs;
      idbHash += f.warmFromIdb.hashMs;
    }
    const idbSpeedup = coldTotal / Math.max(idbTotal, 0.001);
    const l1Speedup = coldTotal / Math.max(l1Total, 0.001);
    cachePersistSummary = {
      n: withPersist.length,
      coldTotalMs: coldTotal,
      warmFromIdbTotalMs: idbTotal,
      warmFromL1TotalMs: l1Total,
      coldParseMs: coldParse,
      warmFromIdbParseMs: idbParse,
      warmFromIdbHashMs: idbHash,
      idbSpeedup,
      l1Speedup,
    };
    console.log('\n=== Sprint 52 IDB persist：cold / warm-from-IDB / warm-from-L1（42 fixture 加總）===');
    console.log(`  cold (page1):       ${ms(coldTotal)}ms  parse=${ms(coldParse)}ms`);
    console.log(`  warm-from-IDB (page2 run0):  ${ms(idbTotal)}ms  parse=${ms(idbParse)}ms  hash=${ms(idbHash)}ms`);
    console.log(`  warm-from-L1 (page2 run1):   ${ms(l1Total)}ms`);
    console.log(`  → IDB hit speedup vs cold = ${idbSpeedup.toFixed(2)}x   L1 hit speedup vs cold = ${l1Speedup.toFixed(2)}x`);
    console.log(`  → L1 是否優於 L2：${l1Total < idbTotal ? `是（差 ${ms(idbTotal - l1Total)}ms = IDB read 開銷）` : '否'}`);
  }

  // Sprint 51：cache 模式 → cold vs warm 聚合（fullWarm 已有自己 summary、不重複）
  let cacheSummary = null;
  if (args.cache && !args.fullWarm) {
    const withCache = report.fixtures.filter((f) => f.cold && f.warmMedian);
    let coldTotal = 0,
      warmTotal = 0,
      coldParse = 0,
      warmParse = 0,
      warmHash = 0;
    for (const f of withCache) {
      coldTotal += f.cold.totalMs;
      warmTotal += f.warmMedian.totalMs;
      coldParse += f.cold.parseMs;
      warmParse += f.warmMedian.parseMs;
      warmHash += f.warmMedian.hashMs;
    }
    const speedup = coldTotal / Math.max(warmTotal, 0.001);
    const parseSpeedup = coldParse / Math.max(warmParse, 0.001);
    cacheSummary = {
      n: withCache.length,
      coldTotalMs: coldTotal,
      warmTotalMs: warmTotal,
      coldParseMs: coldParse,
      warmParseMs: warmParse,
      warmHashMs: warmHash,
      totalSpeedup: speedup,
      parseSpeedup,
    };
    console.log('\n=== Sprint 51 cache cold vs warm（42 fixture 加總）===');
    console.log(`  cold total:  ${ms(coldTotal)}ms  parse=${ms(coldParse)}ms`);
    console.log(`  warm total:  ${ms(warmTotal)}ms  parse=${ms(warmParse)}ms  hash=${ms(warmHash)}ms`);
    console.log(`  → total speedup = ${speedup.toFixed(2)}x   parse speedup = ${parseSpeedup.toFixed(2)}x`);
    console.log(
      `  → warm 配置：hash ${ms(warmHash)}ms（${((warmHash / warmTotal) * 100).toFixed(1)}%）取代 parse ${ms(coldParse)}ms`,
    );
  }

  report.summary = {
    byCategory: byCat,
    grandTotal: grand,
    stageShare,
    bottleneck: bottleneck.stage,
    slowest: slowest.map((f) => ({ rel: f.rel, totalMs: f.median.totalMs, fileSizeKB: f.fileSizeKB, pageCount: f.pageCount })),
    cacheSummary,
    cachePersistSummary,
    virtSummary,
    imageCacheSummary,
    fullWarmSummary,
    imageBitmapCacheSummary,
    imageBitmapPersistSummary,
  };
  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2));
  console.log(
    `\n[perf] measured=${report.measured}/${report.totalFixtures}` +
      `${report.bootFailed ? ` bootFailed=${report.bootFailed}` : ''}  → ${REPORT_JSON}`,
  );
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(2);
});
