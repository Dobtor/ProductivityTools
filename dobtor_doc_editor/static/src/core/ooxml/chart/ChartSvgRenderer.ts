/**
 * ChartSvgRenderer — Sprint 358。
 *
 * 2026-05-29 真實資料 fidelity audit 發現：8 份真實 ChienYi 圖表文件經產品真實
 * 路徑後**視覺圖表完全消失、只剩 chartToText 線性文字**（真實 docx 無 `word/media/`
 * 內嵌 raster fallback、規劃書 mc:Fallback「吃內嵌圖」假設不成立）。
 *
 * 本模組把 ChartParser 已 capture 的 ChartNode（型別 + 標題 + 數列類別/數值）渲染成
 * **SVG 字串**，由 ToCanvasEditor 以 `image` IElement（data URL）塞進 canvas-editor，
 * 取代純文字 fallback。
 *
 * 範圍（按真實 corpus 需求、非通用引擎）：
 *   - 真實 8 份全為 `barChart` / `bar3DChart` → 本 renderer 只畫**分組長條圖**
 *   - 其他型別（pie/line/scatter…）→ 回 null，caller 沿用文字 fallback
 *
 * 紀律 #18 scope-down：
 *   - 純字串生成、環境無關（不依賴 DOM / Buffer / btoa）
 *   - 不畫 3D 透視（bar3D 當平面 bar、數據忠實即可）
 *   - 不做圖例分頁 / 雙 Y 軸 / 堆疊（真實 corpus 不需要）
 *
 * 紀律 #21：純函式;ToCanvasEditor opt-in 才消費、預設不改變既有輸出。
 */

import type { ChartNode } from '../ast/types';

export interface ChartSvgOptions {
  width?: number;
  height?: number;
}

const DEFAULT_W = 600;
const DEFAULT_H = 360;
const PALETTE = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948', '#b07aa1', '#ff9da7'];

/** XML 特殊字元轉義（SVG 文字節點用）。 */
export function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/** 把 SVG 字串轉成 canvas-editor image 可吃的 data URL（UTF-8、無 base64 環境依賴）。 */
export function svgToDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** 「漂亮」上界：把 max 進位到 1/2/5×10^n 的整齊刻度。 */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = Math.pow(10, exp);
  const f = v / base;
  let nf: number;
  if (f <= 1) nf = 1;
  else if (f <= 2) nf = 2;
  else if (f <= 5) nf = 5;
  else nf = 10;
  return nf * base;
}

/**
 * 渲染 ChartNode → SVG 字串。不支援的型別 / 無有效數據 → null。
 */
export function renderChartSvg(chart: ChartNode, opts: ChartSvgOptions = {}): string | null {
  const type = chart.chartType;
  if (type !== 'barChart' && type !== 'bar3DChart') {
    return null; // 非長條圖 → 交給文字 fallback
  }
  const series = chart.series.filter((s) => s.values.some((v) => v !== null));
  if (series.length === 0) return null;

  // 類別取最長的數列為準
  const categories = series.reduce<string[]>(
    (acc, s) => (s.categories.length > acc.length ? s.categories : acc),
    [],
  );
  const catCount = categories.length;
  if (catCount === 0) return null;

  const W = opts.width ?? DEFAULT_W;
  const H = opts.height ?? DEFAULT_H;
  const padL = 56;
  const padR = 16;
  const padT = chart.title ? 40 : 16;
  const padB = 56;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  // 數值上界
  let maxV = 0;
  for (const s of series) {
    for (const v of s.values) {
      if (v !== null && v > maxV) maxV = v;
    }
  }
  const yMax = niceCeil(maxV);

  const parts: string[] = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="sans-serif">`);
  parts.push(`<rect width="${W}" height="${H}" fill="#ffffff"/>`);

  // 標題
  if (chart.title) {
    parts.push(`<text x="${W / 2}" y="24" text-anchor="middle" font-size="16" font-weight="bold" fill="#222">${escapeXml(chart.title)}</text>`);
  }

  // Y 軸格線 + 刻度（4 段）
  const yTicks = 4;
  for (let i = 0; i <= yTicks; i++) {
    const val = (yMax / yTicks) * i;
    const y = padT + plotH - (plotH * i) / yTicks;
    parts.push(`<line x1="${padL}" y1="${y.toFixed(1)}" x2="${padL + plotW}" y2="${y.toFixed(1)}" stroke="#e0e0e0" stroke-width="1"/>`);
    parts.push(`<text x="${padL - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="#666">${formatNum(val)}</text>`);
  }

  // X 軸線
  const axisY = padT + plotH;
  parts.push(`<line x1="${padL}" y1="${axisY}" x2="${padL + plotW}" y2="${axisY}" stroke="#999" stroke-width="1"/>`);

  // 分組長條
  const groupW = plotW / catCount;
  const barGap = groupW * 0.2;
  const innerW = groupW - barGap;
  const barW = innerW / series.length;
  for (let ci = 0; ci < catCount; ci++) {
    const gx = padL + groupW * ci + barGap / 2;
    for (let si = 0; si < series.length; si++) {
      const v = series[si].values[ci];
      if (v === null || v === undefined) continue;
      const h = yMax > 0 ? (plotH * v) / yMax : 0;
      const x = gx + barW * si;
      const y = axisY - h;
      parts.push(`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(barW * 0.92).toFixed(1)}" height="${h.toFixed(1)}" fill="${PALETTE[si % PALETTE.length]}"/>`);
    }
    // 類別標籤
    const label = categories[ci] ?? '';
    if (label) {
      const lx = padL + groupW * ci + groupW / 2;
      parts.push(`<text x="${lx.toFixed(1)}" y="${axisY + 16}" text-anchor="middle" font-size="11" fill="#444">${escapeXml(truncate(label, 8))}</text>`);
    }
  }

  // 圖例（>1 數列且有 name 時）
  const named = series.filter((s) => s.name);
  if (named.length > 1) {
    let lx = padL;
    const ly = H - 16;
    for (let si = 0; si < series.length; si++) {
      const nm = series[si].name;
      if (!nm) continue;
      parts.push(`<rect x="${lx}" y="${ly - 9}" width="10" height="10" fill="${PALETTE[si % PALETTE.length]}"/>`);
      const txt = truncate(nm, 10);
      parts.push(`<text x="${lx + 14}" y="${ly}" font-size="11" fill="#444">${escapeXml(txt)}</text>`);
      lx += 16 + txt.length * 8 + 12;
    }
  }

  parts.push('</svg>');
  return parts.join('');
}

function formatNum(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(1);
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}
