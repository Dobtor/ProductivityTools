/**
 * Sprint 45 — row 0 高度 38.9pt 真根因 trace（純診斷）
 *
 * Sprint 43 §5 假設 A1（row trHeight exact rule 未實作）需驗證 precondition。
 * 已知 fixture XML：所有 <w:trHeight> 皆無 w:hRule → TableParser 判 'auto'（非 exact）。
 * 本 test trace row 0 的 cell 內容、每段 spacing.line、每行 height，
 * 確認 38.9pt 從何而來，並驗證「docGrid snap 套用到 lineRule=exact 段落」假設。
 */

import { describe, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { layoutDocument } from '../../static/src/core/layout/Paginator';
import type { TableNode, ParagraphNode } from '../../static/src/core/ooxml/ast/types';

describe('Sprint 45 — exact line docGrid snap trace', () => {
  it('dump 第一張 table row 0 的 trHeight / spacing.line / 排版 height', async () => {
    const docxPath = resolve(
      __dirname,
      '../fixtures/04_with_image/06.環清表安全衛生抽查照片(再造)-(112.10.23.-10.27).docx',
    );
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const doc = await parser.parse(arr as ArrayBuffer);

    // 找第一個 section 內第一張 table
    const section = doc.sections[0];
    const firstTable = section.body.find((b) => b.type === 'table') as TableNode | undefined;
    if (!firstTable) {
      // eslint-disable-next-line no-console
      console.log('NO TABLE in section 0 body');
      return;
    }
    // eslint-disable-next-line no-console
    console.log(`\n=== 第一張 table：${firstTable.rows.length} rows, docGrid linePitch=${section.docGrid?.linePitch ?? 'none'} ===`);

    for (let ri = 0; ri < Math.min(firstTable.rows.length, 6); ri++) {
      const row = firstTable.rows[ri];
      // eslint-disable-next-line no-console
      console.log(`\n--- row ${ri}: trHeight=${row.props.height ?? 'none'}pt heightRule=${row.props.heightRule ?? 'none'} cells=${row.cells.length} ---`);
      for (let ci = 0; ci < row.cells.length; ci++) {
        const cell = row.cells[ci];
        const paras = cell.content.filter((b) => b.type === 'paragraph') as ParagraphNode[];
        for (const p of paras) {
          const txt = p.runs
            .map((r) => (r.type === 'run' ? r.text : `[${r.type}]`))
            .join('');
          const sl = p.props.spacing?.line;
          // eslint-disable-next-line no-console
          console.log(`    cell ${ci}: spacing.line=${sl ? `${sl.rule}/${sl.value}` : 'none'} snapToGrid=${p.props.snapToGrid ?? 'default'} text=${JSON.stringify(txt.slice(0, 24))}`);
        }
        if (paras.length === 0) {
          // eslint-disable-next-line no-console
          console.log(`    cell ${ci}: (no paragraphs, ${cell.content.length} blocks)`);
        }
      }
    }

    // 排版後 trace row heights
    const layout = layoutDocument(doc.sections, {});
    // eslint-disable-next-line no-console
    console.log('\n=== 排版後 page 0 table row heights ===');
    const p0 = layout.pages[0];
    for (const entry of p0.entries) {
      if (entry.kind !== 'table') continue;
      for (let ri = 0; ri < Math.min(entry.rows.length, 6); ri++) {
        const r = entry.rows[ri];
        const lineHeights = r.cells
          .flatMap((c) => c.lines.map((l) => l.height.toFixed(1)))
          .join(', ');
        // eslint-disable-next-line no-console
        console.log(`  row ${ri}: height=${r.height.toFixed(1)}pt  cell line heights=[${lineHeights}]`);
      }
      break;
    }
  });
});
