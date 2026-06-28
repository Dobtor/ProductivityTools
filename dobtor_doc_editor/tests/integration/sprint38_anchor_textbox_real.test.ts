/**
 * Sprint 38 整合驗證：對真實 docx (1121229-全套管) 解析後，
 * 確認 col 2 paragraph runs 含 floatTextBox 節點與其 paragraphs 內容。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

describe('Sprint 38 — 真實 docx anchor text box 解析驗證', () => {
  it('1121229-全套管 col 2 含 floatTextBox 節點，paragraphs 內含 "112.12.29"', async () => {
    const docxPath = resolve(__dirname, '../fixtures/03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx');
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const result = await parser.parse(arr as ArrayBuffer);

    const section = result.sections[0];
    const tableBlock = section.body.find((b) => b.type === 'table');
    if (!tableBlock || tableBlock.type !== 'table') throw new Error('no table');

    const row0 = tableBlock.rows[0];
    const col2 = row0.cells[2];

    let foundTextBox = false;
    let textBoxText = '';
    for (const block of col2.content) {
      if (block.type !== 'paragraph') continue;
      for (const r of block.runs) {
        if (r.type === 'floatTextBox') {
          foundTextBox = true;
          for (const p of r.paragraphs) {
            for (const run of p.runs) {
              if (run.type === 'run') textBoxText += run.text;
            }
          }
        }
      }
    }

    expect(foundTextBox).toBe(true);
    expect(textBoxText).toContain('112.12.29');
  });
});
