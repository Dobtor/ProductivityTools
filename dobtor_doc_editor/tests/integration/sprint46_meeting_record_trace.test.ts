/**
 * Sprint 46 — 監造會議記錄過分頁 trace（純診斷）
 *
 * Sprint 45 的 containsImage 二分讓 6 個監造會議記錄 fixture 過分頁 +1。
 * 本 test trace 第一張 table 每 row 的 trHeight val / natural / 排版後 height，
 * 對比 Pillow 量測的 golden row 高度，找出 render 哪些 row 比 golden 高。
 */

import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';
import type { TableNode } from '../../static/src/core/ooxml/ast/types';

describe('Sprint 46 — 監造會議記錄 row height trace', () => {
  it('dump 第一張 table 每 row 的 trHeight / 排版 height + 總頁數', async () => {
    const docxPath = resolve(
      __dirname,
      '../fixtures/01_simple/03.1120815-監造會議記錄.docx',
    );
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const doc = await parser.parse(arr as ArrayBuffer);

    const section = doc.sections[0];
    const firstTable = section.body.find((b) => b.type === 'table') as TableNode | undefined;
    if (!firstTable) {
      // eslint-disable-next-line no-console
      console.log('NO TABLE');
      return;
    }

    const layout = layoutDocument(doc.sections, {});
    // eslint-disable-next-line no-console
    console.log(`\n=== 監造會議記錄：${firstTable.rows.length} rows, 總頁數=${layout.pages.length}（golden=3）===`);

    // 排版後 row heights（從 page entries 收集）
    const renderRows: { height: number }[] = [];
    for (const page of layout.pages) {
      for (const entry of page.entries) {
        if (entry.kind === 'table') {
          for (const r of entry.rows) renderRows.push({ height: r.height });
        }
      }
    }

    // eslint-disable-next-line no-console
    console.log('\nrow | trHeight | heightRule | hasImage | natural(approx) | render height');
    // 重新單獨排版每 row 拿 natural（heightRule 設 undefined 繞過 val-as-min）
    for (let ri = 0; ri < Math.min(firstTable.rows.length, 28); ri++) {
      const row = firstTable.rows[ri];
      const rh = renderRows[ri];
      // eslint-disable-next-line no-console
      console.log(
        `  ${String(ri).padStart(2)} | ${String(row.props.height ?? '-').padStart(8)} | ${String(row.props.heightRule ?? '-').padStart(8)} | ` +
        `${row.cells.some((c) => c.content.some((b) => b.type === 'paragraph' && b.runs.some((r) => r.type === 'inlineImage' || r.type === 'floatImage')))} | ` +
        `       | ${rh ? rh.height.toFixed(1) : '?'}`,
      );
    }
  });
});
