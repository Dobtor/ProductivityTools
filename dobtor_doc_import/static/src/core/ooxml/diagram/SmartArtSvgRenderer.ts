/**
 * SmartArtSvgRenderer — Sprint 359。
 *
 * 配合 Sprint 358 ChartSvgRenderer。2026-05-29 fidelity audit 發現 2 份真實
 * SmartArt 文件經真實路徑後只剩 `smartArtToText` 線性文字（真實 docx 無
 * `word/media/` 內嵌圖、只有 `diagrams/*.xml` 資料模型）。
 *
 * 本模組把 SmartArtNode 的內容節點文字渲染成 **SVG 垂直方塊清單**——忠實表達
 * 「離散節點」結構，遠勝 `text / text / text` 線性串接。由 ToCanvasEditor opt-in
 * 以 image IElement 消費。
 *
 * 紀律 #18 scope-down：
 *   - 不精確還原各 layoutType 的版面（circle/pyramid/process…）；統一畫垂直方塊
 *     清單（誠實：表達節點集合，不假裝 1:1 還原 SmartArt 版面）
 *   - 純字串、環境無關（複用 ChartSvgRenderer 的 escapeXml / svgToDataUrl）
 *
 * 紀律 #21：純函式;ToCanvasEditor opt-in 才消費。
 */

import type { SmartArtNode } from '../ast/types';
import { escapeXml } from '../chart/ChartSvgRenderer';

export interface SmartArtSvgOptions {
  width?: number;
}

const DEFAULT_W = 360;
const BOX_H = 40;
const BOX_GAP = 14;
const PAD = 16;
const ARROW_H = BOX_GAP; // 箭頭佔 gap

/**
 * 渲染 SmartArtNode → SVG 字串（垂直方塊清單 + 連接箭頭）。
 * 無內容文字 → null（caller 沿用文字 fallback / 不 emit）。
 */
export function renderSmartArtSvg(node: SmartArtNode, opts: SmartArtSvgOptions = {}): string | null {
  const texts = node.texts.filter((t) => t.trim() !== '');
  if (texts.length === 0) return null;

  const W = opts.width ?? DEFAULT_W;
  const boxW = W - PAD * 2;
  const n = texts.length;
  const H = PAD * 2 + n * BOX_H + (n - 1) * BOX_GAP;

  const parts: string[] = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="sans-serif">`);
  parts.push(`<rect width="${W}" height="${H}" fill="#ffffff"/>`);

  for (let i = 0; i < n; i++) {
    const y = PAD + i * (BOX_H + BOX_GAP);
    const cx = W / 2;
    // 方塊
    parts.push(`<rect x="${PAD}" y="${y}" width="${boxW}" height="${BOX_H}" rx="6" ry="6" fill="#eef3fb" stroke="#4e79a7" stroke-width="1.5"/>`);
    // 文字（垂直置中、過長截斷）
    const ty = y + BOX_H / 2 + 4;
    parts.push(`<text x="${cx}" y="${ty.toFixed(1)}" text-anchor="middle" font-size="13" fill="#234">${escapeXml(truncate(texts[i], 22))}</text>`);
    // 連接箭頭（非最後一個）
    if (i < n - 1) {
      const ax = cx;
      const ay0 = y + BOX_H;
      const ay1 = ay0 + ARROW_H;
      parts.push(`<line x1="${ax}" y1="${ay0}" x2="${ax}" y2="${(ay1 - 3).toFixed(1)}" stroke="#4e79a7" stroke-width="1.5"/>`);
      parts.push(`<path d="M ${ax - 4} ${(ay1 - 5).toFixed(1)} L ${ax} ${ay1.toFixed(1)} L ${ax + 4} ${(ay1 - 5).toFixed(1)} Z" fill="#4e79a7"/>`);
    }
  }

  parts.push('</svg>');
  return parts.join('');
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}
