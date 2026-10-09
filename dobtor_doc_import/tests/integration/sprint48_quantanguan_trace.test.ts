/**
 * Sprint 48 — 03 全套管殘餘 gap trace（純診斷）
 *
 * 1121229-全套管 VR diff 29%。結構：2 inline 照片 + 2 mc:AlternateContent
 * （Choice = DrawingML anchored textbox 含 rect 邊框；Fallback = VML 應忽略）。
 * trace render 的 drawImage / drawRect / fillText ops + table 結構，找 diff 來源。
 */

import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';
import { CanvasRenderer } from '../../static/src/core/render/CanvasRenderer';
import { MockRenderContext } from '../../static/src/core/render/MockRenderContext';

describe('Sprint 48 — 全套管 trace', () => {
  it('dump page 1 ops 統計 + drawImage/anchored 內容', async () => {
    const docxPath = resolve(
      __dirname,
      '../fixtures/03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx',
    );
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const doc = await parser.parse(arr as ArrayBuffer);

    // AST 結構統計
    const section = doc.sections[0];
    let paraCount = 0;
    let tableCount = 0;
    let floatImg = 0;
    let floatTextBox = 0;
    let inlineImg = 0;
    function walkBlocks(blocks: unknown[]): void {
      for (const b of blocks as Array<Record<string, unknown>>) {
        if (b.type === 'paragraph') {
          paraCount++;
          for (const r of (b.runs as Array<Record<string, unknown>>) ?? []) {
            if (r.type === 'inlineImage') inlineImg++;
            if (r.type === 'floatImage') floatImg++;
            if (r.type === 'floatTextBox') floatTextBox++;
          }
        } else if (b.type === 'table') {
          tableCount++;
          for (const row of (b.rows as Array<Record<string, unknown>>) ?? []) {
            for (const cell of (row.cells as Array<Record<string, unknown>>) ?? []) {
              walkBlocks((cell.content as unknown[]) ?? []);
            }
          }
        }
      }
    }
    walkBlocks(section.body);
    // eslint-disable-next-line no-console
    console.log(`\n=== AST：paragraphs=${paraCount} tables=${tableCount} inlineImg=${inlineImg} floatImg=${floatImg} floatTextBox=${floatTextBox} ===`);

    const layout = layoutDocument(doc.sections, {});
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layout);

    // ops 統計
    const opCounts: Record<string, number> = {};
    for (const op of ctx.ops) opCounts[op.kind] = (opCounts[op.kind] ?? 0) + 1;
    // eslint-disable-next-line no-console
    console.log(`\n=== render ops 統計：${JSON.stringify(opCounts)} ===`);
    // eslint-disable-next-line no-console
    console.log(`頁數=${layout.pages.length}`);

    const SCALE = 150 / 72;
    // eslint-disable-next-line no-console
    console.log('\n=== drawImage ops ===');
    for (const op of ctx.ops) {
      if (op.kind !== 'drawImage') continue;
      const o = op as { href: string; x: number; y: number; width: number; height: number };
      // eslint-disable-next-line no-console
      console.log(`  ${o.href.slice(0, 24)} x=${o.x.toFixed(1)} y=${o.y.toFixed(1)} w=${o.width.toFixed(1)} h=${o.height.toFixed(1)} | px y=${(o.y * SCALE).toFixed(0)}-${((o.y + o.height) * SCALE).toFixed(0)}`);
    }
    // fillText 樣本（前 20）
    // eslint-disable-next-line no-console
    console.log('\n=== fillText 樣本（前 25）===');
    let n = 0;
    for (const op of ctx.ops) {
      if (op.kind !== 'fillText') continue;
      const o = op as { text: string; x: number; y: number };
      if (n < 25) {
        // eslint-disable-next-line no-console
        console.log(`  ${JSON.stringify(o.text)} @(${o.x.toFixed(0)},${o.y.toFixed(0)})`);
      }
      n++;
    }
    // eslint-disable-next-line no-console
    console.log(`  ... total fillText=${n}`);
  });
});
