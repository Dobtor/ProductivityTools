import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';

describe('S49 trace', () => {
  it('table + cell + photo detail', async () => {
    const p = resolve(__dirname, '../fixtures/03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx');
    const buf = readFileSync(p);
    const doc = await new OoxmlParser().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer);
    const layout = layoutDocument(doc.sections, {});
    const pg = layout.pages[0];
    for (const e of pg.entries) {
      const ee = e as Record<string, unknown>;
      if (ee.kind === 'line') {
        const li = ee as { y: number; height: number };
        // eslint-disable-next-line no-console
        console.log(`line y=${li.y.toFixed(1)} h=${li.height.toFixed(1)}`);
      } else if (ee.kind === 'table') {
        const t = ee as { x: number; y: number; rows: Array<Record<string, unknown>> };
        // eslint-disable-next-line no-console
        console.log(`TABLE at y=${t.y.toFixed(1)}`);
        let cy = t.y;
        for (let ri = 0; ri < t.rows.length; ri++) {
          const row = t.rows[ri] as { height: number; cells: Array<Record<string, unknown>> };
          // eslint-disable-next-line no-console
          console.log(`  row${ri} y=${cy.toFixed(1)} h=${row.height.toFixed(1)}`);
          for (const c of row.cells) {
            const cc = c as { cellIndex: number; vAlign: string; contentHeight: number; height: number; padding: {top:number;bottom:number}; blocks: Array<Record<string, unknown>> };
            const imgs: string[] = [];
            for (const b of cc.blocks) {
              if (b.kind === 'lines') {
                for (const ln of (b as {lines: Array<{items: Array<Record<string,unknown>>}>}).lines) {
                  for (const it of ln.items) {
                    if (it.kind === 'box' && it.isImage) imgs.push(`img h=${(it.height as number).toFixed(1)}`);
                  }
                }
              }
            }
            // eslint-disable-next-line no-console
            console.log(`    c${cc.cellIndex} vAlign=${cc.vAlign} contentH=${cc.contentHeight.toFixed(1)} cellH=${cc.height.toFixed(1)} pad=${cc.padding.top}/${cc.padding.bottom} imgs=[${imgs.join(',')}] floats=${(c as {floats?:unknown[]}).floats?.length ?? 0}`);
          }
          cy += row.height;
        }
      }
    }
  });
});
