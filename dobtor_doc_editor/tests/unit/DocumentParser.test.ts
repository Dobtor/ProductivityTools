/**
 * DocumentParser 單元測試 (Sprint 1 issue #3)
 *
 * 用手寫 word/document.xml 字串驗證 body 走訪 + dispatch 邏輯。
 * Fixture 整合測試另放 tests/integration/。
 */

import { describe, expect, it } from 'vitest';
import { DocumentParser } from '../../static/src/core/ooxml/document/DocumentParser';

const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(bodyInner: string): string {
  return `<?xml version="1.0"?>
<w:document ${W}>
  <w:body>${bodyInner}</w:body>
</w:document>`;
}

const parser = new DocumentParser();

describe('DocumentParser — 結構', () => {
  it('回傳 DocumentNode 含單一 section + 空 metadata', () => {
    const node = parser.parse(wrap('<w:p><w:r><w:t>hello</w:t></w:r></w:p>'));

    expect(node.type).toBe('document');
    expect(node.sections).toHaveLength(1);
    expect(node.headers.size).toBe(0);
    expect(node.footers.size).toBe(0);
    expect(node.styles.size).toBe(0);
    expect(node.numbering.size).toBe(0);
    expect(node.media.size).toBe(0);
  });

  it('段落順序保留', () => {
    const node = parser.parse(
      wrap(
        '<w:p><w:r><w:t>A</w:t></w:r></w:p>' +
          '<w:p><w:r><w:t>B</w:t></w:r></w:p>' +
          '<w:p><w:r><w:t>C</w:t></w:r></w:p>',
      ),
    );
    const body = node.sections[0].body;
    expect(body.map((b) => (b.type === 'paragraph' ? extractText(b.runs) : ''))).toEqual([
      'A',
      'B',
      'C',
    ]);
  });
});

describe('DocumentParser — dispatch', () => {
  it('w:tbl 產生 table placeholder（單一 fake row 收所有內含 w:p）', () => {
    const node = parser.parse(
      wrap(
        '<w:p><w:r><w:t>before</w:t></w:r></w:p>' +
          '<w:tbl>' +
            '<w:tr><w:tc>' +
              '<w:p><w:r><w:t>cell text 1</w:t></w:r></w:p>' +
              '<w:p><w:r><w:t>cell text 2</w:t></w:r></w:p>' +
            '</w:tc></w:tr>' +
          '</w:tbl>' +
          '<w:p><w:r><w:t>after</w:t></w:r></w:p>',
      ),
    );
    const body = node.sections[0].body;
    expect(body).toHaveLength(3);
    expect(body[0].type).toBe('paragraph');
    expect(body[1].type).toBe('table');
    expect(body[2].type).toBe('paragraph');

    if (body[1].type !== 'table') throw new Error('expected table');
    expect(body[1].grid).toEqual([]);
    expect(body[1].rows).toHaveLength(1);
    const cell = body[1].rows[0].cells[0];
    expect(cell.content).toHaveLength(2);
    expect(cell.content[0].runs[0]).toMatchObject({ type: 'run', text: 'cell text 1' });
    expect(cell.content[1].runs[0]).toMatchObject({ type: 'run', text: 'cell text 2' });
  });

  it('body 末尾 w:sectPr 不進 body[]', () => {
    const node = parser.parse(
      wrap(
        '<w:p><w:r><w:t>p1</w:t></w:r></w:p>' +
          '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>',
      ),
    );
    const body = node.sections[0].body;
    expect(body).toHaveLength(1);
    expect(body[0].type).toBe('paragraph');
  });

  it('未知子節點靜默忽略', () => {
    const node = parser.parse(
      wrap('<w:bookmarkStart w:id="0"/><w:p><w:r><w:t>X</w:t></w:r></w:p>'),
    );
    expect(node.sections[0].body).toHaveLength(1);
  });
});

describe('DocumentParser — section placeholder', () => {
  it('預設 A4 直式 + 1 inch 邊距', () => {
    const node = parser.parse(wrap('<w:p/>'));
    const sec = node.sections[0];
    expect(sec.page.orientation).toBe('portrait');
    expect(sec.page.width).toBeCloseTo(595.3, 1);
    expect(sec.page.height).toBeCloseTo(841.9, 1);
    expect(sec.margins.top).toBe(72);
    expect(sec.margins.left).toBe(72);
  });
});

describe('DocumentParser — 錯誤處理', () => {
  it('缺 <w:body> 應丟錯', () => {
    const xml = `<?xml version="1.0"?><w:document ${W}/>`;
    expect(() => parser.parse(xml)).toThrow(/<w:body> not found/);
  });

  it('完全空字串應丟錯', () => {
    expect(() => parser.parse('')).toThrow();
  });
});

// helpers
function extractText(runs: { type: string; text?: string }[]): string {
  return runs
    .filter((r) => r.type === 'run')
    .map((r) => r.text ?? '')
    .join('');
}
