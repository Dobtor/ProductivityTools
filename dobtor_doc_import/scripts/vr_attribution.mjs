/**
 * vr_attribution.mjs — 把 VR 的 diffRatio 拆解成可歸因的維度（優化 2）。
 *
 * ☠️ 為什麼需要它：VR 現在只回**一個總和數字**（per-page mean 7.89%，
 *    主規畫書 §2.2 要求 <2%）。那個數字無法回答「要先修什麼」：
 *    7.89% 裡有多少來自整體位移（邊界／baseline 常數）、多少來自字寬累積、
 *    多少來自表格格線、多少來自圖片？
 *
 *    沒有拆解，優化方向只能猜——而猜錯的代價是接一整條子系統
 *    （例如 core/ooxml/layout 的 16 檔 / 2,413 行）之後發現它不是主因。
 *
 *    **這支不會讓 7.89% 變小。** 它讓「下一步做什麼」從猜變成讀。
 *
 * 設計取捨（為什麼不做 2-D 全域搜尋）：
 *   794×1123 ≈ 892k 像素，13×13 個位移組合 × 126 頁 = 1.5 億次比對，太慢。
 *   改用 **1-D ink profile 的互相關**：把每一列（row）的深色像素數算成一個
 *   長度 h 的陣列，與 golden 的同一個陣列做互相關求最佳 dy；column 同理求 dx。
 *   成本降到 O(h × 位移數) ≈ 1.5 萬次，然後只在最佳位移處做一次完整 diff。
 *
 * 三個產出（都是比例，加起來不必等於 1——它們是不同切面）：
 *   shiftExplained  整體位移能解釋掉多少比例的誤差
 *                   高 → 修的是常數（邊界／baseline），不是排版引擎
 *   byRegion        diff 像素落在「文字／水平線／圖片／空白」各佔多少
 *                   水平線高 → 表格格線位移；圖片高 → 縮放或錨點
 *   advanceDrift    文字列裡 diff 是否由左往右遞增（字寬累積的特徵）
 *                   高 → 字寬度量不準，接 ShapingEngine 才有意義
 */

/** 把 RGBA buffer 的某個像素當「深色」嗎（golden 是白底黑字）。 */
function isInk(data, idx) {
  // 亮度近似：不做精確 luma，閾值夠分出字與白底就好
  return data[idx] + data[idx + 1] + data[idx + 2] < 384;   // 平均 < 128
}

/** 每一列的深色像素數（長度 h）。 */
export function rowInk(data, w, h) {
  const out = new Float64Array(h);
  for (let y = 0; y < h; y++) {
    let n = 0;
    const base = y * w * 4;
    for (let x = 0; x < w; x++) {
      if (isInk(data, base + x * 4)) n++;
    }
    out[y] = n;
  }
  return out;
}

/** 每一欄的深色像素數（長度 w）。 */
export function colInk(data, w, h) {
  const out = new Float64Array(w);
  for (let x = 0; x < w; x++) {
    let n = 0;
    for (let y = 0; y < h; y++) {
      if (isInk(data, (y * w + x) * 4)) n++;
    }
    out[x] = n;
  }
  return out;
}

/**
 * 用互相關找讓兩個 1-D profile 最接近的位移。
 *
 * 回 {shift, ssdAt0, ssdAtBest}：ssd 下降得多就代表「整體位移」是主要誤差。
 */
export function bestShift1D(a, b, maxShift = 6) {
  const n = Math.min(a.length, b.length);
  let best = 0;
  let bestSsd = Infinity;
  let ssdAt0 = 0;
  for (let s = -maxShift; s <= maxShift; s++) {
    let ssd = 0;
    let count = 0;
    for (let i = 0; i < n; i++) {
      const j = i + s;
      if (j < 0 || j >= n) continue;
      const d = a[i] - b[j];
      ssd += d * d;
      count++;
    }
    if (!count) continue;
    ssd /= count;                 // 正規化，否則邊界位移會因樣本少而佔便宜
    if (s === 0) ssdAt0 = ssd;
    if (ssd < bestSsd) {
      bestSsd = ssd;
      best = s;
    }
  }
  return { shift: best, ssdAt0, ssdAtBest: bestSsd };
}

/**
 * 把 golden 的每一列分類：水平線／文字／圖片／空白。
 *
 * 判準（經驗值，寫在這裡而不是散在呼叫端）：
 *   水平線  一列的深色像素 ≥ 寬度的 30%，且上下相鄰列的深色數驟降
 *           （表格格線與底線是這個形狀）
 *   圖片    一列的深色像素 ≥ 寬度的 30%，且上下相鄰列也一樣高（連續區塊）
 *   文字    深色像素佔 1%–30%
 *   空白    < 1%
 */
export function classifyRows(goldenData, w, h) {
  const ink = rowInk(goldenData, w, h);
  const dense = w * 0.30;
  const sparse = w * 0.01;
  const kinds = new Array(h);
  for (let y = 0; y < h; y++) {
    if (ink[y] < sparse) {
      kinds[y] = 'blank';
    } else if (ink[y] >= dense) {
      const up = y > 0 ? ink[y - 1] : 0;
      const down = y < h - 1 ? ink[y + 1] : 0;
      // 上下都一樣密 → 連續區塊（圖片）；孤立的一條 → 線
      kinds[y] = (up >= dense && down >= dense) ? 'image' : 'rule';
    } else {
      kinds[y] = 'text';
    }
  }
  return kinds;
}

/** diff 像素按 golden 的列分類歸屬。回各類的像素數與比例。 */
export function attributeByRegion(diffData, goldenData, w, h) {
  const kinds = classifyRows(goldenData, w, h);
  const counts = { text: 0, rule: 0, image: 0, blank: 0 };
  let total = 0;
  for (let y = 0; y < h; y++) {
    const kind = kinds[y];
    const base = y * w * 4;
    for (let x = 0; x < w; x++) {
      // pixelmatch 把差異標成紅色（255,0,0 系）；非零 alpha 且偏紅
      const i = base + x * 4;
      if (diffData[i] > 200 && diffData[i + 1] < 100 && diffData[i + 2] < 100) {
        counts[kind]++;
        total++;
      }
    }
  }
  const ratios = {};
  for (const k of Object.keys(counts)) {
    ratios[k] = total ? Number((counts[k] / total).toFixed(4)) : 0;
  }
  return { counts, total, ratios };
}

/**
 * 文字列裡的 diff 是否由左往右遞增（字寬累積的特徵）。
 *
 * 回 0–1：0 ＝ 均勻分布（不是字寬問題），1 ＝ 全部集中在右半
 * ——**字寬誤差會累積**，所以同一行越往右偏得越多。
 */
export function advanceDrift(diffData, goldenData, w, h) {
  const kinds = classifyRows(goldenData, w, h);
  let leftHalf = 0;
  let rightHalf = 0;
  const mid = Math.floor(w / 2);
  for (let y = 0; y < h; y++) {
    if (kinds[y] !== 'text') continue;
    const base = y * w * 4;
    for (let x = 0; x < w; x++) {
      const i = base + x * 4;
      if (diffData[i] > 200 && diffData[i + 1] < 100 && diffData[i + 2] < 100) {
        if (x < mid) leftHalf++;
        else rightHalf++;
      }
    }
  }
  const total = leftHalf + rightHalf;
  if (!total) return 0;
  // 0.5 ＝ 均勻；映射成 0–1，只在「右邊多」時才算 drift
  return Number(Math.max(0, (rightHalf / total - 0.5) * 2).toFixed(4));
}

/** 把 rendered buffer 平移 (dx, dy)，超出範圍補白。 */
export function shiftBuffer(data, w, h, dx, dy) {
  const out = new Uint8Array(w * h * 4).fill(255);
  for (let y = 0; y < h; y++) {
    const sy = y - dy;
    if (sy < 0 || sy >= h) continue;
    for (let x = 0; x < w; x++) {
      const sx = x - dx;
      if (sx < 0 || sx >= w) continue;
      const si = (sy * w + sx) * 4;
      const di = (y * w + x) * 4;
      out[di] = data[si];
      out[di + 1] = data[si + 1];
      out[di + 2] = data[si + 2];
      out[di + 3] = data[si + 3];
    }
  }
  return out;
}
