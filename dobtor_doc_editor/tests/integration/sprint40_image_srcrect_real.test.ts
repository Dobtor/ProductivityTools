/**
 * Sprint 40 整合驗證：對真實 05 fixture（含 `<a:srcRect t="4066" b="4066"/>`）
 * 確認 InlineImageNode.srcRect 解析後攜帶 0.04066 上下裁切分數。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type { BlockNode, InlineImageNode, ImageSrcRect } from '../../static/src/core/ooxml/ast/types';

function findFirstInlineImageWithSrcRect(blocks: BlockNode[]): ImageSrcRect | null {
  for (const b of blocks) {
    if (b.type === 'paragraph') {
      for (const r of b.runs) {
        if (r.type === 'inlineImage' && (r as InlineImageNode).srcRect) {
          return (r as InlineImageNode).srcRect ?? null;
        }
      }
    } else if (b.type === 'table') {
      for (const row of b.rows) {
        for (const cell of row.cells) {
          const found = findFirstInlineImageWithSrcRect(cell.content);
          if (found) return found;
        }
      }
    }
  }
  return null;
}

describe('Sprint 40 — 真實 05 fixture srcRect 解析', () => {
  it('05.112磺港溪監造會議照片.docx 內 inline 圖片含 srcRect ~ 4.066%', async () => {
    const docxPath = resolve(__dirname, '../fixtures/04_with_image/05.112磺港溪監造會議照片.docx');
    const buf = readFileSync(docxPath);
    const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const parser = new OoxmlParser();
    const result = await parser.parse(arr as ArrayBuffer);

    // 遞迴巡 sections / tables / cells，找首個含 srcRect 的 inlineImage
    let foundSrcRect: ImageSrcRect | null = null;
    for (const section of result.sections) {
      foundSrcRect = findFirstInlineImageWithSrcRect(section.body);
      if (foundSrcRect) break;
    }

    expect(foundSrcRect).not.toBeNull();
    // 容忍 0.04053 ~ 0.04076 範圍（fixture 內 srcRect 值在此區間）
    expect(foundSrcRect!.topPct).toBeGreaterThan(0.04);
    expect(foundSrcRect!.topPct).toBeLessThan(0.041);
    expect(foundSrcRect!.bottomPct).toBeGreaterThan(0.04);
    expect(foundSrcRect!.bottomPct).toBeLessThan(0.041);
  });
});
