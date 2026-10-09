#!/usr/bin/env node
/**
 * Sprint 60 — OffscreenCanvas + Web Worker render feasibility probe
 *
 * 目的：規劃書 §11.27 Sprint 60 首選 = OffscreenCanvas + Web Worker render（高風險）。
 *       本腳本是 Sprint 36/43/46/49 模式的純診斷 sprint —— 不改 production code，
 *       只在 puppeteer 環境收集事實，給 Sprint 61 commit 全面改造 vs pivot HarfBuzz 做依據。
 *
 * 檢測項目：
 *   A. Feature detection
 *      - typeof OffscreenCanvas（puppeteer Chromium 應該有）
 *      - 'transferControlToOffscreen' in HTMLCanvasElement.prototype
 *      - typeof Worker（webworker spawn 能力）
 *      - typeof createImageBitmap（worker → main thread ImageBitmap transfer）
 *
 *   B. Minimal worker prototype
 *      - 用 Blob URL 動態啟動 worker（避開 file:// 跨 origin 限制）
 *      - postMessage round-trip 延遲（ping/pong）
 *      - transferControlToOffscreen 是否成功
 *      - worker 內呼叫 OffscreenCanvas.getContext('2d') 並 fillRect 是否可見於主執行緒 canvas
 *
 *   C. 量測（與 Sprint 50-58 基線對比）
 *      - main-thread render 1 fixture 的 wall-clock
 *      - worker render 同 fixture 的 wall-clock（含 postMessage 開銷）
 *      - 推估 production cross-tab UX 改善（不是 puppeteer 量得到的）
 *
 * 輸出：tests/fixtures/offscreen_canvas_probe_report.json（給 audit doc 參考）
 *
 * 退出碼：0 = 探測完成（不論支援與否）；2 = puppeteer / harness 環境問題
 */

import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = resolve(__dirname, '..');
const HARNESS_HTML = resolve(ROOT, 'scripts/visual_regression_v14_harness.html');
const REPORT_JSON = resolve(ROOT, 'tests/fixtures/offscreen_canvas_probe_report.json');
const SAMPLE_FIXTURE = resolve(ROOT, 'tests/fixtures/02_std_table/1121006-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx');

async function main() {
  if (!existsSync(HARNESS_HTML)) {
    console.error(`[fatal] harness 不存在：${HARNESS_HTML}`);
    process.exit(2);
  }
  if (!existsSync(SAMPLE_FIXTURE)) {
    console.error(`[fatal] sample fixture 不存在：${SAMPLE_FIXTURE}`);
    process.exit(2);
  }

  let puppeteer;
  try {
    puppeteer = (await import('puppeteer')).default;
  } catch (err) {
    console.error('[fatal] puppeteer 未安裝：', err.message);
    process.exit(2);
  }

  const sampleBase64 = readFileSync(SAMPLE_FIXTURE).toString('base64');
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const report = {
    runAt: new Date().toISOString(),
    probe: 'sprint60_offscreen_canvas_feasibility',
    featureDetection: null,
    workerProbe: null,
    renderBench: null,
  };

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1240, height: 1754, deviceScaleFactor: 1 });
    await page.goto(`file://${HARNESS_HTML}`, { waitUntil: 'load' });
    await page.waitForFunction(
      () => typeof window.__bootDobtorPipeline === 'function' && !!window.__dobtorPipeline,
      { timeout: 15_000 },
    );

    // ── A. Feature detection ─────────────────────────────────────────────
    const featureDetection = await page.evaluate(() => {
      return {
        hasOffscreenCanvas: typeof OffscreenCanvas !== 'undefined',
        hasTransferControlToOffscreen:
          typeof HTMLCanvasElement !== 'undefined' &&
          'transferControlToOffscreen' in HTMLCanvasElement.prototype,
        hasWorker: typeof Worker !== 'undefined',
        hasCreateImageBitmap: typeof createImageBitmap !== 'undefined',
        userAgent: navigator.userAgent,
      };
    });
    report.featureDetection = featureDetection;
    console.log('\n=== A. Feature detection ===');
    console.log(`  OffscreenCanvas:             ${featureDetection.hasOffscreenCanvas ? '✓' : '✗'}`);
    console.log(`  transferControlToOffscreen:  ${featureDetection.hasTransferControlToOffscreen ? '✓' : '✗'}`);
    console.log(`  Worker:                       ${featureDetection.hasWorker ? '✓' : '✗'}`);
    console.log(`  createImageBitmap:            ${featureDetection.hasCreateImageBitmap ? '✓' : '✗'}`);

    const allFeaturesSupported =
      featureDetection.hasOffscreenCanvas &&
      featureDetection.hasTransferControlToOffscreen &&
      featureDetection.hasWorker &&
      featureDetection.hasCreateImageBitmap;

    if (!allFeaturesSupported) {
      console.log('\n[probe] Feature detection 不全 — Sprint 61 候選需 fallback path');
      report.workerProbe = { skipped: true, reason: 'feature_unsupported' };
      report.renderBench = { skipped: true, reason: 'feature_unsupported' };
    } else {
      // ── B. Worker spawn + postMessage round-trip ─────────────────────────
      const workerProbe = await page.evaluate(async () => {
        const workerCode = `
          self.onmessage = (e) => {
            if (e.data.type === 'ping') {
              self.postMessage({ type: 'pong', sentAt: e.data.sentAt, receivedAt: performance.now() });
              return;
            }
            if (e.data.type === 'paintOffscreen') {
              const canvas = e.data.canvas;
              const ctx = canvas.getContext('2d');
              ctx.fillStyle = '#ff0000';
              ctx.fillRect(10, 10, 50, 50);
              ctx.fillStyle = '#0000ff';
              ctx.fillRect(70, 10, 50, 50);
              self.postMessage({ type: 'painted' });
            }
          };
        `;
        const blob = new Blob([workerCode], { type: 'application/javascript' });
        const url = URL.createObjectURL(blob);

        let workerReady = true;
        let worker;
        try {
          worker = new Worker(url);
        } catch (err) {
          return { ok: false, error: 'worker_construct: ' + String(err) };
        }

        // Ping-pong
        const t0 = performance.now();
        const pongMs = await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('pong timeout 2s')), 2000);
          worker.addEventListener('message', function once(e) {
            if (e.data.type === 'pong') {
              clearTimeout(timeout);
              worker.removeEventListener('message', once);
              resolve(performance.now() - t0);
            }
          });
          worker.postMessage({ type: 'ping', sentAt: performance.now() });
        }).catch((err) => ({ error: String(err) }));

        if (typeof pongMs !== 'number') {
          worker.terminate();
          URL.revokeObjectURL(url);
          return { ok: false, error: 'pong: ' + JSON.stringify(pongMs) };
        }

        // transferControlToOffscreen → paint in worker
        const visibleCanvas = document.createElement('canvas');
        visibleCanvas.width = 200;
        visibleCanvas.height = 100;
        let offscreen;
        try {
          offscreen = visibleCanvas.transferControlToOffscreen();
        } catch (err) {
          worker.terminate();
          URL.revokeObjectURL(url);
          return { ok: false, error: 'transfer: ' + String(err), pongMs };
        }

        const paintMs = await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('paint timeout 2s')), 2000);
          const t1 = performance.now();
          worker.addEventListener('message', function once(e) {
            if (e.data.type === 'painted') {
              clearTimeout(timeout);
              worker.removeEventListener('message', once);
              resolve(performance.now() - t1);
            }
          });
          worker.postMessage({ type: 'paintOffscreen', canvas: offscreen }, [offscreen]);
        }).catch((err) => ({ error: String(err) }));

        worker.terminate();
        URL.revokeObjectURL(url);
        return { ok: true, pongMs, paintMs, workerReady };
      });
      report.workerProbe = workerProbe;
      console.log('\n=== B. Worker prototype ===');
      if (workerProbe.ok) {
        console.log(`  postMessage ping/pong:       ${workerProbe.pongMs.toFixed(2)}ms`);
        console.log(`  transferControlToOffscreen:  ✓`);
        console.log(`  worker paint to OffscreenCanvas: ${typeof workerProbe.paintMs === 'number' ? workerProbe.paintMs.toFixed(2) + 'ms' : 'ERROR ' + JSON.stringify(workerProbe.paintMs)}`);
      } else {
        console.log(`  ✗ ${workerProbe.error}`);
      }

      // ── C. Render benchmark：main-thread vs worker 同份 fixture ──────────
      // 限定範圍：只測 1 個 fixture（02_std_table 週報，2p、含表格 + image），
      // 量測 5 次取中位數，main thread 與 worker 各跑
      const renderBench = await page.evaluate(async (sampleB64) => {
        function base64ToArrayBuffer(b64) {
          const bin = atob(b64);
          const u8 = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
          return u8.buffer;
        }
        const buf = base64ToArrayBuffer(sampleB64);

        // Main-thread baseline：直接呼叫現有 pipeline
        const RUNS = 5;
        const mainTimes = [];
        const tempContainer = document.createElement('div');
        document.body.appendChild(tempContainer);
        for (let i = 0; i < RUNS; i++) {
          const t0 = performance.now();
          // clone buffer 避免 detached（pipeline 不 detach 但 worker 會 transfer）
          const bufClone = buf.slice(0);
          tempContainer.innerHTML = '';
          await window.__dobtorPipeline.render(bufClone, tempContainer, { dpi: 150 });
          mainTimes.push(performance.now() - t0);
        }
        tempContainer.remove();
        mainTimes.sort((a, b) => a - b);
        const mainMedian = mainTimes[Math.floor(mainTimes.length / 2)];

        // 結論：worker render 路徑需要把整個 pipeline IIFE 跑在 worker 內
        //       → 即「worker 內 importScripts(visual_regression_pipeline.iife.js) + 呼叫 render」
        //       本 probe 不實作完整 worker pipeline（那是 Sprint 61 工作）
        //       這裡只量「postMessage docx ArrayBuffer + 用 OffscreenCanvas 在 worker 跑簡單 fillRect」當 overhead 上限
        const workerCode = `
          self.onmessage = (e) => {
            const t0 = performance.now();
            if (e.data.type === 'simpleRender') {
              const canvas = e.data.canvas;
              const ctx = canvas.getContext('2d');
              // 模擬簡單 render workload（fillRect × 500 + fillText × 100）
              ctx.fillStyle = '#ffffff';
              ctx.fillRect(0, 0, canvas.width, canvas.height);
              for (let i = 0; i < 500; i++) {
                ctx.fillStyle = '#' + (i % 256).toString(16).padStart(2, '0') + '0000';
                ctx.fillRect(i % 100, Math.floor(i / 100) * 20, 50, 18);
              }
              ctx.fillStyle = '#000000';
              ctx.font = '16px sans-serif';
              for (let i = 0; i < 100; i++) {
                ctx.fillText('Hello ' + i, 10, 200 + i * 5);
              }
              self.postMessage({ type: 'done', renderMs: performance.now() - t0 });
            }
          };
        `;
        const blob = new Blob([workerCode], { type: 'application/javascript' });
        const url = URL.createObjectURL(blob);
        const worker = new Worker(url);

        const workerTimes = [];
        for (let i = 0; i < RUNS; i++) {
          const visibleCanvas = document.createElement('canvas');
          visibleCanvas.width = 800;
          visibleCanvas.height = 600;
          const offscreen = visibleCanvas.transferControlToOffscreen();
          const t0 = performance.now();
          const renderMs = await new Promise((resolve) => {
            worker.addEventListener('message', function once(e) {
              if (e.data.type === 'done') {
                worker.removeEventListener('message', once);
                resolve(e.data.renderMs);
              }
            });
            worker.postMessage({ type: 'simpleRender', canvas: offscreen }, [offscreen]);
          });
          const totalMs = performance.now() - t0;
          workerTimes.push({ totalMs, workerInternalMs: renderMs });
        }
        worker.terminate();
        URL.revokeObjectURL(url);
        workerTimes.sort((a, b) => a.totalMs - b.totalMs);
        const workerMedian = workerTimes[Math.floor(workerTimes.length / 2)];

        return {
          mainThread: { medianMs: mainMedian, samples: mainTimes },
          workerSimulated: {
            medianTotalMs: workerMedian.totalMs,
            workerInternalMs: workerMedian.workerInternalMs,
            postMessageOverheadMs: workerMedian.totalMs - workerMedian.workerInternalMs,
            samples: workerTimes,
          },
          note: 'workerSimulated 是「轉移 canvas + 跑簡單 ~500 ops」量 worker 路徑的 overhead 上限，不是完整 pipeline 在 worker 內的真實 wall-clock（那需要 Sprint 61 工程實作）',
        };
      }, sampleBase64);
      report.renderBench = renderBench;
      console.log('\n=== C. Render benchmark ===');
      console.log(`  Main-thread pipeline median:  ${renderBench.mainThread.medianMs.toFixed(2)}ms（完整 pipeline）`);
      console.log(`  Worker simulated render:      ${renderBench.workerSimulated.medianTotalMs.toFixed(2)}ms total`);
      console.log(`    (worker 內 render: ${renderBench.workerSimulated.workerInternalMs.toFixed(2)}ms)`);
      console.log(`    postMessage overhead:       ${renderBench.workerSimulated.postMessageOverheadMs.toFixed(2)}ms`);
      console.log(`  ⚠️ ${renderBench.note}`);
    }

    await page.close();
  } finally {
    await browser.close();
  }

  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2));
  console.log(`\n[probe] → ${REPORT_JSON}`);
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(2);
});
