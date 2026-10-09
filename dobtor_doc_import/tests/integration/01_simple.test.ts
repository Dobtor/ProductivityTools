/**
 * 整合測試 — 真實 fixture (01_simple/) 經 PackageReader → DocumentParser 後
 * 結構與內容符合預期。
 *
 * 對應 Sprint 1 issue #7（部分驗收，issue #7 完整驗收還需要對段落數量與
 * Word 原檔一致 — 本測試先用結構性 assertion 兜出底線）。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PackageReader } from '../../static/src/core/ooxml/package/PackageReader';
import { DocumentParser } from '../../static/src/core/ooxml/document/DocumentParser';
import type { BlockNode, ParagraphNode } from '../../static/src/core/ooxml/ast/types';

/**
 * 把 BlockNode 樹遞迴展平成所有段落（含 table 內 cell content）。
 * Sprint 3 TableParser 完成後仍保留此 helper —— 表格中當然會有段落。
 */
function flattenParagraphs(blocks: BlockNode[]): ParagraphNode[] {
  const out: ParagraphNode[] = [];
  for (const b of blocks) {
    if (b.type === 'paragraph') {
      out.push(b);
    } else if (b.type === 'table') {
      for (const row of b.rows) {
        for (const cell of row.cells) {
          out.push(...flattenParagraphs(cell.content));
        }
      }
    }
  }
  return out;
}

function paragraphsToText(ps: ParagraphNode[]): string {
  return ps
    .flatMap((p) => p.runs)
    .filter((r) => r.type === 'run')
    .map((r) => (r.type === 'run' ? r.text : ''))
    .join('');
}

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function loadDocxAsBuffer(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const SIMPLE_FIXTURES = [
  '01_simple/03.1120210-監造會議記錄-1120801.docx',
  '01_simple/03.1120815-監造會議記錄.docx',
  '01_simple/03.1120822-監造會議記錄.docx',
  '01_simple/03.1120829-監造會議記錄.docx',
  '01_simple/03.1120905-監造會議記錄.docx',
  '01_simple/03.1120912-監造會議記錄.docx',
  '01_simple/03.1120919-監造會議記錄.docx',
];

const reader = new PackageReader();
const docParser = new DocumentParser();

describe('Integration — 01_simple 監造會議記錄', () => {
  it.each(SIMPLE_FIXTURES)('%s 解析後段落數 > 5（含表格 cell 段落）且文字含關鍵字', (path) => {
    const pkg = reader.parse(loadDocxAsBuffer(path));
    const xml = pkg.partAsText('word/document.xml');
    expect(xml).toBeDefined();

    const doc = docParser.parse(xml!);
    const allParas = flattenParagraphs(doc.sections[0].body);

    expect(allParas.length).toBeGreaterThan(5);

    const allText = paragraphsToText(allParas);
    expect(allText.length).toBeGreaterThan(0);
    // 監造會議記錄至少含其一固定字眼
    expect(allText).toMatch(/(會議|監造|出席|工程|主持)/);
  });

  it('03.1120815 解析後文字含「監造」', () => {
    const pkg = reader.parse(
      loadDocxAsBuffer('01_simple/03.1120815-監造會議記錄.docx'),
    );
    const doc = docParser.parse(pkg.partAsText('word/document.xml')!);
    const allText = paragraphsToText(flattenParagraphs(doc.sections[0].body));
    expect(allText).toContain('監造');
  });

  it('table placeholder 在 02_std_table 週報的 body 中出現', () => {
    const pkg = reader.parse(
      loadDocxAsBuffer(
        '02_std_table/1120928-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
      ),
    );
    const doc = docParser.parse(pkg.partAsText('word/document.xml')!);
    const tables = doc.sections[0].body.filter((b) => b.type === 'table');
    expect(tables.length).toBeGreaterThan(0);
  });
});
