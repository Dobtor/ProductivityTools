/**
 * Sprint 360 — 真實路徑整合驗證：圖表 / SmartArt SVG 渲染（opt-in）。
 *
 * 鎖定 2026-05-29 的修法（commit 5fc953a）：真實 ChienYi chart/smartart docx 走
 * OoxmlParser → ToCanvasEditor({ renderGraphicsAsSvg: true }) 後，graphic frame 應
 * 產出 SVG image IElement（取代線性文字 fallback）。
 *
 * 為什麼是整合測試：sprint358/359 只單測 renderChartSvg/renderSmartArtSvg 本體（合成
 * 輸入）。本測試走真實 docx + 真實 mapper，確保「圖表→SVG」這條已 live 的整合路徑不會
 * 在 parser / DrawingParser / mapper 任一層被靜默改壞。
 *
 * 同時鎖定 opt-in 契約：不開旗標 → 無 SVG image（維持 VR byte-identical 預設行為）。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { ToCanvasEditor } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';
import type { CEElement } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';

/** 遞迴計數 SVG image element（含 table cell trList/tdList 內、hyperlink valueList 內）。 */
function collectSvgImages(els: CEElement[]): CEElement[] {
  const found: CEElement[] = [];
  const walk = (arr: CEElement[] | undefined): void => {
    if (!Array.isArray(arr)) return;
    for (const e of arr) {
      if (!e || typeof e !== 'object') continue;
      if (e.type === 'image' && typeof e.value === 'string' && e.value.startsWith('data:image/svg+xml')) {
        found.push(e);
      }
      if (e.type === 'table' && Array.isArray(e.trList)) {
        for (const tr of e.trList) {
          for (const td of tr.tdList ?? []) walk(td.value as CEElement[] | undefined);
        }
      }
      if (Array.isArray(e.valueList)) walk(e.valueList as CEElement[] | undefined);
    }
  };
  walk(els);
  return found;
}

async function parseDoc(relPath: string) {
  const buf = readFileSync(resolve(__dirname, '../fixtures', relPath));
  const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new OoxmlParser().parse(arr as ArrayBuffer);
}

function decodeSvg(dataUrl: string): string {
  return decodeURIComponent(dataUrl.split(',', 2)[1]);
}

const CHART_DOC = '07_chart/土方統計(浤欣)1140829.docx';
const SMARTART_DOC = '08_smartart/1140831磺港溪C-B中央補助款-V1.docx';

describe('Sprint 360 — 圖表/SmartArt SVG 真實路徑整合', () => {
  it('真實 chart docx + renderGraphicsAsSvg → 含良構 SVG image element', async () => {
    const doc = await parseDoc(CHART_DOC);
    const els = new ToCanvasEditor({ renderGraphicsAsSvg: true }).convert(doc);
    const svgs = collectSvgImages(els);
    expect(svgs.length).toBeGreaterThanOrEqual(1);
    const svg = decodeSvg(svgs[0].value as string);
    expect(svg.startsWith('<svg')).toBe(true);
    expect(svg).toContain('</svg>');
  });

  it('真實 smartart docx + renderGraphicsAsSvg → 含良構 SVG image element', async () => {
    const doc = await parseDoc(SMARTART_DOC);
    const els = new ToCanvasEditor({ renderGraphicsAsSvg: true }).convert(doc);
    const svgs = collectSvgImages(els);
    expect(svgs.length).toBeGreaterThanOrEqual(1);
    const svg = decodeSvg(svgs[0].value as string);
    expect(svg.startsWith('<svg')).toBe(true);
    expect(svg).toContain('</svg>');
  });

  it('opt-in 契約：不開旗標 → 0 個 SVG image（維持預設線性文字 fallback）', async () => {
    const chart = await parseDoc(CHART_DOC);
    const smartart = await parseDoc(SMARTART_DOC);
    expect(collectSvgImages(new ToCanvasEditor().convert(chart)).length).toBe(0);
    expect(collectSvgImages(new ToCanvasEditor().convert(smartart)).length).toBe(0);
  });
});
