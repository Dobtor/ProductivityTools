/**
 * Sprint 43 photo Y 偏移精細 trace（純診斷）
 *
 * 對 06.環清表(112.10.23-10.27).docx page 1 trace 所有 drawImage ops，
 * 找最大照片的 (x, y, w, h)，並換算為 150 DPI 像素位置，
 * 對比 Pillow 量測的 render pixel y，驗證 trace 工具正確性。
 */

import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';
import { CanvasRenderer } from '../../static/src/core/render/CanvasRenderer';
import { MockRenderContext } from '../../static/src/core/render/MockRenderContext';

describe('Sprint 43 — photo Y trace', () => {
  it('dump page 1 drawImage ops 順序、(x, y, w, h) 與對應 150 DPI 像素值', async () => {
    const docxPath = resolve(__dirname, '../fixtures/04_with_image/06.環清表安全衛生抽查照片(再造)-(112.10.23.-10.27).docx');
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const doc = await parser.parse(arr as ArrayBuffer);
    const layout = layoutDocument(doc.sections, {});
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layout);

    // 找 page 1 範圍
    const beginPage1Idx = ctx.ops.findIndex((op) => op.kind === 'beginPage' && (op as { pageNumber: number }).pageNumber === 1);
    const beginPage2Idx = ctx.ops.findIndex((op) => op.kind === 'beginPage' && (op as { pageNumber: number }).pageNumber === 2);
    const page1Ops = ctx.ops.slice(beginPage1Idx, beginPage2Idx > 0 ? beginPage2Idx : ctx.ops.length);

    const SCALE = 150 / 72;
    // eslint-disable-next-line no-console
    console.log('\n=== Page 1 ALL drawImage ops ===');
    for (const op of page1Ops) {
      if (op.kind !== 'drawImage') continue;
      const o = op as { href: string; x: number; y: number; width: number; height: number };
      const yPx = o.y * SCALE;
      // eslint-disable-next-line no-console
      console.log(`  href=${o.href.slice(0, 30)}... x=${o.x.toFixed(1)}pt y=${o.y.toFixed(1)}pt w=${o.width.toFixed(1)}pt h=${o.height.toFixed(1)}pt  | y_px=${yPx.toFixed(0)} h_px=${(o.height * SCALE).toFixed(0)}`);
    }

    // 找最大 drawImage（= 主照片）
    const imgs = page1Ops.filter((op) => op.kind === 'drawImage') as Array<{ href: string; x: number; y: number; width: number; height: number }>;
    if (imgs.length === 0) {
      // eslint-disable-next-line no-console
      console.log('NO IMAGES on page 1');
      return;
    }
    const biggest = imgs.reduce((a, b) => (a.width * a.height > b.width * b.height ? a : b));
    // eslint-disable-next-line no-console
    console.log('\n=== Biggest photo ===');
    // eslint-disable-next-line no-console
    console.log(`x=${biggest.x.toFixed(1)}pt y=${biggest.y.toFixed(1)}pt w=${biggest.width.toFixed(1)}pt h=${biggest.height.toFixed(1)}pt`);
    // eslint-disable-next-line no-console
    console.log(`→ 150 DPI 像素: x=${(biggest.x * SCALE).toFixed(0)} y=${(biggest.y * SCALE).toFixed(0)} w=${(biggest.width * SCALE).toFixed(0)} h=${(biggest.height * SCALE).toFixed(0)}`);

    // dump page 1 所有 drawLine（border lines）位置給 cross-check
    // eslint-disable-next-line no-console
    console.log('\n=== Page 1 long horizontal drawLines (y1==y2, x diff > 200) ===');
    let horizLines = 0;
    for (const op of page1Ops) {
      if (op.kind !== 'drawLine') continue;
      const o = op as { x1: number; y1: number; x2: number; y2: number };
      if (Math.abs(o.y1 - o.y2) < 0.5 && Math.abs(o.x2 - o.x1) > 200) {
        if (horizLines < 12) {
          // eslint-disable-next-line no-console
          console.log(`  y=${o.y1.toFixed(1)}pt (px ${(o.y1 * SCALE).toFixed(0)})  x=${o.x1.toFixed(1)}→${o.x2.toFixed(1)}`);
        }
        horizLines++;
      }
    }
    // eslint-disable-next-line no-console
    console.log(`Total long horizontal lines on page 1: ${horizLines}`);

    // 也 dump table entry 的 y 起點
    // eslint-disable-next-line no-console
    console.log('\n=== Table entries on page 1 ===');
    const p1 = layout.pages[0];
    for (const entry of p1.entries) {
      if (entry.kind === 'table') {
        // eslint-disable-next-line no-console
        console.log(`  table at (${entry.x.toFixed(1)}, ${entry.y.toFixed(1)})pt = px (${(entry.x * SCALE).toFixed(0)}, ${(entry.y * SCALE).toFixed(0)})  rows=${entry.rows.length}`);
        let cumY = entry.y;
        for (let ri = 0; ri < entry.rows.length; ri++) {
          // eslint-disable-next-line no-console
          console.log(`    row ${ri}: y=${cumY.toFixed(1)}pt (px ${(cumY * SCALE).toFixed(0)})  h=${entry.rows[ri].height.toFixed(1)}pt`);
          cumY += entry.rows[ri].height;
        }
      }
    }
  });
});
