/**
 * Sprint 39 診斷：對真實 1121229 docx 確認 floatTextBox 的 bodyPr/fill/border 解析狀況。
 * 此 test 主要為 inspection 用途（log 結構，斷言寬鬆）。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

describe('Sprint 39 — bodyPr/fill/border 對真實 fixture 解析診斷', () => {
  it('1121229 col 2 floatTextBox 含 bodyPr 且 fill/border 應為 undefined (a:noFill)', async () => {
    const docxPath = resolve(__dirname, '../fixtures/03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx');
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const result = await parser.parse(arr as ArrayBuffer);
    const table = result.sections[0].body.find((b) => b.type === 'table');
    if (!table || table.type !== 'table') throw new Error('no table');
    const col2 = table.rows[0].cells[2];

    const dumps: Record<string, unknown> = {};
    for (const block of col2.content) {
      if (block.type !== 'paragraph') continue;
      for (const r of block.runs) {
        if (r.type !== 'floatTextBox') continue;
        dumps.width = r.width;
        dumps.height = r.height;
        dumps.bodyPr = r.bodyPr;
        dumps.fill = r.fill;
        dumps.border = r.border;
        dumps.firstRunColor = r.paragraphs[0]?.runs.find((x) => x.type === 'run')?.props?.color;
        dumps.firstRunFontSize = r.paragraphs[0]?.runs.find((x) => x.type === 'run')?.props?.fontSize;
        break;
      }
    }
    // eslint-disable-next-line no-console
    console.log('[Sprint39 diagnostic]', dumps);
    expect(dumps.bodyPr).toBeDefined();
    expect(dumps.fill).toBeUndefined();
    expect(dumps.border).toBeUndefined();
    expect(dumps.firstRunColor).toBe('FF0000');
  });
});
