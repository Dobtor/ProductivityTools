#!/usr/bin/env node
/**
 * Sprint 36 — Pixel distribution grid analysis
 *
 * 對 render PNG vs golden PNG 切 grid（預設 50×70），計算每 grid 的 pixel diff ratio。
 * 找出 top N% 最差 grid 位置，輸出 JSON + 標記過的 overlay PNG。
 *
 * 用法：
 *   node scripts/grid_analysis.cjs --render <path> --golden <path> [--out-json <path>] [--out-overlay <path>] [--grid 50x70] [--top-pct 10]
 *
 * 範例：
 *   node scripts/grid_analysis.cjs \
 *     --render tests/fixtures/.visual_regression_tmp/v14/1121229-全套管基樁混凝土查驗\(共1\)-1.rendered.png \
 *     --golden tests/fixtures/03_complex_table/golden/1121229-全套管基樁混凝土查驗\(共1\)-1.png \
 *     --out-json /tmp/grid_1121229_p1.json \
 *     --out-overlay /tmp/grid_1121229_p1.overlay.png
 *
 * 輸出 JSON 格式：
 *   {
 *     image: { width, height },
 *     grid: { cols, rows, cellWidth, cellHeight },
 *     totalDiffRatio: 0.30,
 *     cells: [{ col, row, x, y, w, h, diffPixels, totalPixels, ratio }, ...],
 *     top: [...sorted by ratio desc...]
 *   }
 */

const fs = require('node:fs');
const path = require('node:path');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch').default || require('pixelmatch');

function parseArgs(argv) {
  const args = { gridCols: 50, gridRows: 70, topPct: 10 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--render') args.render = argv[++i];
    else if (a === '--golden') args.golden = argv[++i];
    else if (a === '--out-json') args.outJson = argv[++i];
    else if (a === '--out-overlay') args.outOverlay = argv[++i];
    else if (a === '--grid') {
      const m = /^(\d+)x(\d+)$/.exec(argv[++i] || '');
      if (m) { args.gridCols = Number(m[1]); args.gridRows = Number(m[2]); }
    } else if (a === '--top-pct') args.topPct = Number(argv[++i]);
  }
  if (!args.render || !args.golden) {
    console.error('Usage: node grid_analysis.cjs --render <p> --golden <p> [--out-json <p>] [--out-overlay <p>] [--grid 50x70] [--top-pct 10]');
    process.exit(2);
  }
  return args;
}

function loadPng(filePath) {
  const buf = fs.readFileSync(filePath);
  return PNG.sync.read(buf);
}

function scaleTo(src, targetW, targetH) {
  if (src.width === targetW && src.height === targetH) return src;
  // Nearest-neighbor scale；diff 算大致位置足夠
  const out = new PNG({ width: targetW, height: targetH });
  for (let y = 0; y < targetH; y++) {
    const sy = Math.floor((y * src.height) / targetH);
    for (let x = 0; x < targetW; x++) {
      const sx = Math.floor((x * src.width) / targetW);
      const srcIdx = (sy * src.width + sx) * 4;
      const dstIdx = (y * targetW + x) * 4;
      out.data[dstIdx] = src.data[srcIdx];
      out.data[dstIdx + 1] = src.data[srcIdx + 1];
      out.data[dstIdx + 2] = src.data[srcIdx + 2];
      out.data[dstIdx + 3] = src.data[srcIdx + 3];
    }
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const renderPng = loadPng(args.render);
  const goldenPng = loadPng(args.golden);

  // 對齊到 golden 尺寸（與 v14 pipeline 一致）
  const W = goldenPng.width;
  const H = goldenPng.height;
  const rScaled = scaleTo(renderPng, W, H);

  // 算每 pixel 的 diff（pixelmatch 寫到 diffData）
  const diffData = Buffer.alloc(W * H * 4);
  const diffCount = pixelmatch(rScaled.data, goldenPng.data, diffData, W, H, {
    threshold: 0.1,
    includeAA: false,
    alpha: 0.3,
  });
  const totalRatio = diffCount / (W * H);

  // 切 grid
  const cellW = W / args.gridCols;
  const cellH = H / args.gridRows;
  const cells = [];
  // 先把 diff per pixel 整成 boolean array 加速
  // pixelmatch 把 diff pixel 寫成紅色 (255,0,0)；非 diff 是淡灰或透明
  // 簡單判斷：紅 channel 突然飆且綠藍很低
  const isDiff = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) {
    const r = diffData[i * 4];
    const g = diffData[i * 4 + 1];
    const b = diffData[i * 4 + 2];
    if (r > 200 && g < 100 && b < 100) isDiff[i] = 1;
  }

  for (let row = 0; row < args.gridRows; row++) {
    const y0 = Math.floor(row * cellH);
    const y1 = Math.min(Math.floor((row + 1) * cellH), H);
    for (let col = 0; col < args.gridCols; col++) {
      const x0 = Math.floor(col * cellW);
      const x1 = Math.min(Math.floor((col + 1) * cellW), W);
      let cellDiff = 0;
      let cellTotal = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          cellTotal++;
          if (isDiff[y * W + x]) cellDiff++;
        }
      }
      cells.push({
        col, row,
        x: x0, y: y0, w: x1 - x0, h: y1 - y0,
        diffPixels: cellDiff,
        totalPixels: cellTotal,
        ratio: cellTotal > 0 ? cellDiff / cellTotal : 0,
      });
    }
  }

  // Top N% by ratio
  const sorted = [...cells].sort((a, b) => b.ratio - a.ratio);
  const topN = Math.max(1, Math.floor((cells.length * args.topPct) / 100));
  const top = sorted.slice(0, topN);

  const out = {
    inputs: { render: args.render, golden: args.golden },
    image: { width: W, height: H },
    grid: {
      cols: args.gridCols, rows: args.gridRows,
      cellWidth: cellW, cellHeight: cellH,
    },
    overallDiffRatio: totalRatio,
    overallDiffPixels: diffCount,
    topPct: args.topPct,
    topCount: topN,
    topMeanRatio: top.reduce((s, c) => s + c.ratio, 0) / top.length,
    topSumDiff: top.reduce((s, c) => s + c.diffPixels, 0),
    top: top.map((c) => ({
      col: c.col, row: c.row,
      x: c.x, y: c.y, w: c.w, h: c.h,
      ratio: Number(c.ratio.toFixed(4)),
      diffPixels: c.diffPixels,
    })),
    // 完整 grid 也輸出方便 heat-map 視覺化
    cells: cells.map((c) => ({
      col: c.col, row: c.row,
      ratio: Number(c.ratio.toFixed(4)),
    })),
  };

  console.log('=== Grid Analysis ===');
  console.log(`Render        : ${args.render}`);
  console.log(`Golden        : ${args.golden}`);
  console.log(`Image         : ${W}x${H}`);
  console.log(`Grid          : ${args.gridCols}x${args.gridRows} (cell ${cellW.toFixed(1)}x${cellH.toFixed(1)} px)`);
  console.log(`Overall diff  : ${(totalRatio * 100).toFixed(2)}% (${diffCount} px)`);
  console.log(`Top ${args.topPct}%       : ${topN} cells, mean ratio ${(out.topMeanRatio * 100).toFixed(2)}%, ${out.topSumDiff} diff px (${((out.topSumDiff / diffCount) * 100).toFixed(1)}% of total)`);
  console.log('');
  console.log(`Top 10 worst grids:`);
  for (const c of top.slice(0, 10)) {
    console.log(`  grid(${c.col},${c.row}) at px(${c.x},${c.y})-${c.x + c.w}x${c.y + c.h}: ratio=${(c.ratio * 100).toFixed(1)}%, diff=${c.diffPixels}`);
  }

  if (args.outJson) {
    fs.writeFileSync(args.outJson, JSON.stringify(out, null, 2));
    console.log(`\nJSON written: ${args.outJson}`);
  }

  if (args.outOverlay) {
    // 畫紅色半透明矩形標出 top N% grids 在 golden 上
    const overlay = new PNG({ width: W, height: H });
    overlay.data = Buffer.from(goldenPng.data);
    const inTop = new Set(top.map((c) => `${c.col},${c.row}`));
    for (const c of cells) {
      if (!inTop.has(`${c.col},${c.row}`)) continue;
      // 紅色透明覆蓋
      for (let y = c.y; y < c.y + c.h; y++) {
        for (let x = c.x; x < c.x + c.w; x++) {
          const idx = (y * W + x) * 4;
          overlay.data[idx] = Math.min(255, overlay.data[idx] + 80);
          overlay.data[idx + 1] = Math.max(0, overlay.data[idx + 1] - 60);
          overlay.data[idx + 2] = Math.max(0, overlay.data[idx + 2] - 60);
        }
      }
      // 邊框（更深的紅）
      for (let x = c.x; x < c.x + c.w; x++) {
        if (c.y >= 0 && c.y < H) {
          const idx = (c.y * W + x) * 4;
          overlay.data[idx] = 255; overlay.data[idx + 1] = 0; overlay.data[idx + 2] = 0;
        }
      }
    }
    fs.writeFileSync(args.outOverlay, PNG.sync.write(overlay));
    console.log(`Overlay written: ${args.outOverlay}`);
  }
}

main();
