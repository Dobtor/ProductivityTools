/**
 * HeaderFooterParser 單元測試 (Phase B.4)
 *
 * 結構與 document body 相同（BlockNode[]），重用 DocumentParser.parseBodyContent。
 */

import { describe, expect, it } from 'vitest';
import { HeaderFooterParser } from '../../static/src/core/ooxml/header-footer/HeaderFooterParser';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

const parser = new HeaderFooterParser();

describe('HeaderFooterParser — 基本', () => {
  it('解析含段落的 header', () => {
    const xml = `<?xml version="1.0"?>
      <w:hdr ${W_NS}>
        <w:p><w:r><w:t>第一頁頁首</w:t></w:r></w:p>
      </w:hdr>`;
    const out = parser.parse(xml, 'rId10');
    expect(out.rId).toBe('rId10');
    expect(out.content).toHaveLength(1);
    expect(out.content[0].type).toBe('paragraph');
  });

  it('解析含表格的 header（公司 logo 表格佈局）', () => {
    const xml = `<?xml version="1.0"?>
      <w:hdr ${W_NS}>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>左格</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>右格</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:hdr>`;
    const out = parser.parse(xml, 'rId11');
    expect(out.content).toHaveLength(1);
    expect(out.content[0].type).toBe('table');
    if (out.content[0].type === 'table') {
      expect(out.content[0].rows[0].cells).toHaveLength(2);
    }
  });

  it('解析空 header（content = []）', () => {
    const xml = `<?xml version="1.0"?><w:hdr ${W_NS}/>`;
    const out = parser.parse(xml, 'rId12');
    expect(out.content).toEqual([]);
  });

  it('解析 footer 結構（與 header 相同）', () => {
    const xml = `<?xml version="1.0"?>
      <w:ftr ${W_NS}>
        <w:p><w:r><w:t>頁尾文字</w:t></w:r></w:p>
        <w:p><w:r><w:t>第 2 行</w:t></w:r></w:p>
      </w:ftr>`;
    const out = parser.parse(xml, 'rId20');
    expect(out.content).toHaveLength(2);
  });
});

describe('HeaderFooterParser — 邊界', () => {
  it('破碎 XML 降級為空 content（不 throw）', () => {
    const out = parser.parse('<<<broken xml>>>', 'rId13');
    expect(out.rId).toBe('rId13');
    expect(out.content).toEqual([]);
  });

  it('完全空字串降級為空 content', () => {
    const out = parser.parse('', 'rId14');
    expect(out.content).toEqual([]);
  });
});
