/**
 * Sprint 42 debug：trace 06 fixture photo cell 的 vAlign + rowHeight + contentHeight 實際值
 */

import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';

describe('Sprint 42 — debug 06 photo cell vAlign / dims', () => {
  it('dump page 1 table cells (vAlign, rowHeight, contentHeight, hasImage)', async () => {
    const docxPath = resolve(__dirname, '../fixtures/04_with_image/06.環清表安全衛生抽查照片(再造)-(112.10.23.-10.27).docx');
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const doc = await parser.parse(arr as ArrayBuffer);
    const layout = layoutDocument(doc.sections, {});

    // Dump page 1 entries
    const p1 = layout.pages[0];
    // eslint-disable-next-line no-console
    console.log('page 1 entries:', p1.entries.length);
    for (const entry of p1.entries) {
      if (entry.kind === 'table') {
        // eslint-disable-next-line no-console
        console.log(`\n--- table entry at (${entry.x}, ${entry.y}) ---`);
        for (let ri = 0; ri < Math.min(entry.rows.length, 6); ri++) {
          const row = entry.rows[ri];
          // eslint-disable-next-line no-console
          console.log(`  row ${ri} h=${row.height.toFixed(1)}pt:`);
          for (const cell of row.cells) {
            const hasImg = cell.blocks.some((b) =>
              b.kind === 'lines' && b.lines.some((l) =>
                l.items.some((it) => it.kind === 'box' && (it as { isImage?: boolean }).isImage),
              ),
            );
            // eslint-disable-next-line no-console
            console.log(`    cell.vAlign=${cell.vAlign} ch=${cell.contentHeight.toFixed(1)} h=${cell.height.toFixed(1)} hasImg=${hasImg}`);
          }
        }
      }
    }
  });
});
