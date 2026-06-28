/**
 * FootnotesParser.test.ts — Sprint 145(Phase 3.6 capture-only)
 *
 * 涵蓋:
 *   - footnotes.xml 解析:separator / continuationSeparator / 普通 footnote
 *   - endnotes.xml 解析(同結構、不同 root 標籤)
 *   - 缺失 / 空 XML / 解析失敗的防禦
 *   - w:id 數字邊界(-1 / 0 / 1+)、未知 w:type 降級
 *   - 重用 DocumentParser 解析 footnote 內部段落(普通內容)
 *
 * 紀律 #22 應用:本 sprint 是 capture-only、無 wire-up;
 * test 重點是 parser 正確性、不包含 render / layout 驗證。
 */

import { describe, expect, it } from 'vitest';
import { FootnotesParser } from '../../static/src/core/ooxml/footnotes/FootnotesParser';

// ── 真實 fixture 結構(從 03_complex_table/送審管制.docx 摘取)──────────────

const REAL_FOOTNOTES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="separator" w:id="-1">
    <w:p><w:r><w:separator/></w:r></w:p>
  </w:footnote>
  <w:footnote w:type="continuationSeparator" w:id="0">
    <w:p><w:r><w:continuationSeparator/></w:r></w:p>
  </w:footnote>
</w:footnotes>`;

const REAL_ENDNOTES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:endnote w:type="separator" w:id="-1">
    <w:p><w:r><w:separator/></w:r></w:p>
  </w:endnote>
  <w:endnote w:type="continuationSeparator" w:id="0">
    <w:p><w:r><w:continuationSeparator/></w:r></w:p>
  </w:endnote>
</w:endnotes>`;

// ── 合成 fixture:含一般 footnote(模擬 user 提供含 footnoteReference docx)──

const SYNTHETIC_FOOTNOTES_WITH_CONTENT = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="separator" w:id="-1">
    <w:p><w:r><w:separator/></w:r></w:p>
  </w:footnote>
  <w:footnote w:type="continuationSeparator" w:id="0">
    <w:p><w:r><w:continuationSeparator/></w:r></w:p>
  </w:footnote>
  <w:footnote w:id="1">
    <w:p><w:r><w:t>第一個 footnote 內容</w:t></w:r></w:p>
  </w:footnote>
  <w:footnote w:id="2">
    <w:p><w:r><w:t>第二個 footnote 內容</w:t></w:r></w:p>
  </w:footnote>
</w:footnotes>`;

describe('FootnotesParser — 真實 fixture(僅 separator + continuationSeparator)', () => {
  it('解析含 separator + continuationSeparator 兩條目', () => {
    const parser = new FootnotesParser();
    const result = parser.parse(REAL_FOOTNOTES_XML);
    expect(result.size).toBe(2);
    expect(result.get(-1)?.type).toBe('separator');
    expect(result.get(0)?.type).toBe('continuationSeparator');
  });

  it('separator / continuationSeparator content 不為 undefined(雖然只是空段落)', () => {
    const parser = new FootnotesParser();
    const result = parser.parse(REAL_FOOTNOTES_XML);
    // content 應為 BlockNode[]、可能含段落(內 separator/continuationSeparator run)
    expect(result.get(-1)?.content).toBeDefined();
    expect(Array.isArray(result.get(-1)?.content)).toBe(true);
  });
});

describe('FootnotesParser — endnotes.xml(同 parser、不同 root)', () => {
  it('解析 endnotes.xml(w:endnote 根節點)', () => {
    const parser = new FootnotesParser();
    const result = parser.parse(REAL_ENDNOTES_XML);
    expect(result.size).toBe(2);
    expect(result.get(-1)?.type).toBe('separator');
    expect(result.get(0)?.type).toBe('continuationSeparator');
  });
});

describe('FootnotesParser — 含一般 footnote 內容(模擬 user fixture)', () => {
  it('解析 4 條目(2 預設裝飾 + 2 普通內容)', () => {
    const parser = new FootnotesParser();
    const result = parser.parse(SYNTHETIC_FOOTNOTES_WITH_CONTENT);
    expect(result.size).toBe(4);
    // 一般 footnote type 應為 undefined
    expect(result.get(1)?.type).toBeUndefined();
    expect(result.get(2)?.type).toBeUndefined();
    // 預設裝飾 type 仍正確
    expect(result.get(-1)?.type).toBe('separator');
    expect(result.get(0)?.type).toBe('continuationSeparator');
  });

  it('一般 footnote content 含段落 + 文字', () => {
    const parser = new FootnotesParser();
    const result = parser.parse(SYNTHETIC_FOOTNOTES_WITH_CONTENT);
    const f1 = result.get(1);
    expect(f1?.content.length).toBeGreaterThan(0);
    // 第一個 block 應為 paragraph(BlockNode 包 paragraph type)
    const block = f1!.content[0];
    expect(block.type).toBe('paragraph');
  });
});

describe('FootnotesParser — 防禦邊界', () => {
  it('undefined 輸入 → 回空 Map(不 throw)', () => {
    const parser = new FootnotesParser();
    expect(parser.parse(undefined).size).toBe(0);
  });

  it('空字串 → 回空 Map', () => {
    const parser = new FootnotesParser();
    expect(parser.parse('').size).toBe(0);
  });

  it('XML parse 失敗 → 回空 Map(不 throw)', () => {
    const parser = new FootnotesParser();
    // 故意壞 XML
    const result = parser.parse('<w:footnotes><not closed>');
    expect(result.size).toBe(0);
  });

  it('未知 w:type 降級為 undefined(視為普通 footnote)', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="unknownType" w:id="5">
    <w:p><w:r><w:t>x</w:t></w:r></w:p>
  </w:footnote>
</w:footnotes>`;
    const parser = new FootnotesParser();
    const result = parser.parse(xml);
    expect(result.get(5)?.type).toBeUndefined();
  });

  it('缺 w:id 屬性 → 跳過此條目', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="separator">
    <w:p/>
  </w:footnote>
  <w:footnote w:id="1">
    <w:p/>
  </w:footnote>
</w:footnotes>`;
    const parser = new FootnotesParser();
    const result = parser.parse(xml);
    expect(result.size).toBe(1);
    expect(result.get(1)).toBeDefined();
  });

  it('w:id 非數字 → 跳過此條目', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:id="abc">
    <w:p/>
  </w:footnote>
  <w:footnote w:id="42">
    <w:p/>
  </w:footnote>
</w:footnotes>`;
    const parser = new FootnotesParser();
    const result = parser.parse(xml);
    expect(result.size).toBe(1);
    expect(result.get(42)).toBeDefined();
  });
});

describe('FootnotesParser — w:type 列舉完整覆蓋', () => {
  it('continuationNotice 是合法 type', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:footnote w:type="continuationNotice" w:id="3">
    <w:p><w:r><w:t>本頁註腳於次頁延續</w:t></w:r></w:p>
  </w:footnote>
</w:footnotes>`;
    const parser = new FootnotesParser();
    const result = parser.parse(xml);
    expect(result.get(3)?.type).toBe('continuationNotice');
  });
});
