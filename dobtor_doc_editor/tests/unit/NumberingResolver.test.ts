/**
 * NumberingResolver 單元測試 (Phase B.2)
 *
 * 驗證 abstractNum / num / lvlOverride 解析鏈。
 */

import { describe, expect, it } from 'vitest';
import { NumberingResolver } from '../../static/src/core/ooxml/numbering/NumberingResolver';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0"?><w:numbering ${W_NS}>${inner}</w:numbering>`;
}

const resolver = new NumberingResolver();

describe('NumberingResolver — 基本', () => {
  it('undefined 輸入回空 Map', () => {
    expect(resolver.resolve(undefined).size).toBe(0);
  });

  it('空 numbering.xml 回空 Map', () => {
    expect(resolver.resolve(wrap('')).size).toBe(0);
  });
});

describe('NumberingResolver — 單層 decimal 編號', () => {
  it('解析 abstractNum + num，回傳 NumberingMap[numId]', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0">
          <w:start w:val="1"/>
          <w:numFmt w:val="decimal"/>
          <w:lvlText w:val="%1."/>
        </w:lvl>
      </w:abstractNum>
      <w:num w:numId="1">
        <w:abstractNumId w:val="0"/>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.size).toBe(1);
    const num1 = map.get(1);
    expect(num1?.abstractNumId).toBe(0);
    expect(num1?.levels).toHaveLength(1);
    expect(num1?.levels[0].ilvl).toBe(0);
    expect(num1?.levels[0].numFmt).toBe('decimal');
    expect(num1?.levels[0].text).toBe('%1.');
    expect(num1?.levels[0].start).toBe(1);
  });
});

describe('NumberingResolver — 多層次清單', () => {
  it('9 層 (ilvl 0-8) 全解析，按 ilvl 排序', () => {
    const lvls = Array.from({ length: 9 }, (_, i) =>
      `<w:lvl w:ilvl="${8 - i}"><w:numFmt w:val="decimal"/><w:lvlText w:val="%${8 - i + 1}."/></w:lvl>`,
    ).join('');
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="5">${lvls}</w:abstractNum>
      <w:num w:numId="3"><w:abstractNumId w:val="5"/></w:num>
    `);
    const map = resolver.resolve(xml);
    const num3 = map.get(3);
    expect(num3?.levels).toHaveLength(9);
    // 應已按 ilvl 0..8 排序
    for (let i = 0; i < 9; i++) {
      expect(num3?.levels[i].ilvl).toBe(i);
    }
  });

  it('lvlText 模板原樣保留（"%1.%2."）', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="1">
          <w:numFmt w:val="decimal"/>
          <w:lvlText w:val="%1.%2."/>
        </w:lvl>
      </w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(1)?.levels[0].text).toBe('%1.%2.');
  });
});

describe('NumberingResolver — numFmt 全套', () => {
  const formats = [
    'decimal',
    'lowerLetter',
    'upperLetter',
    'lowerRoman',
    'upperRoman',
    'bullet',
    'chineseCounting',
    'chineseCountingThousand',
    'japaneseCounting',
    'taiwaneseCounting',
    'ordinal',
    'iroha',
    'aiueo',
  ];

  it.each(formats)('numFmt=%s 透傳到 NumberingLevel', (fmt) => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0">
          <w:numFmt w:val="${fmt}"/>
          <w:lvlText w:val="%1."/>
        </w:lvl>
      </w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(1)?.levels[0].numFmt).toBe(fmt);
  });
});

describe('NumberingResolver — lvlOverride', () => {
  it('startOverride 覆蓋 base.start', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="2">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0">
          <w:startOverride w:val="100"/>
        </w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(2)?.levels[0].start).toBe(100);
  });

  it('整層 lvl 覆蓋', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="3">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0">
          <w:lvl w:ilvl="0">
            <w:numFmt w:val="bullet"/>
            <w:lvlText w:val="•"/>
          </w:lvl>
        </w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    const lvl = map.get(3)?.levels[0];
    expect(lvl?.numFmt).toBe('bullet');
    expect(lvl?.text).toBe('•');
  });
});

describe('NumberingResolver — 共用 abstractNum', () => {
  it('多個 numId 共用同一 abstractNumId（互不影響）', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="1">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0"><w:startOverride w:val="50"/></w:lvlOverride>
      </w:num>
      <w:num w:numId="2">
        <w:abstractNumId w:val="0"/>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(1)?.levels[0].start).toBe(50);
    expect(map.get(2)?.levels[0].start).toBe(1); // 未覆蓋
  });
});

describe('NumberingResolver — 邊界', () => {
  it('缺失 abstractNumId 視為空殼（不 throw）', () => {
    const xml = wrap(`
      <w:num w:numId="9"><w:abstractNumId w:val="999"/></w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(9)?.levels).toHaveLength(0);
  });

  it('沒 numId 屬性的 <w:num> 跳過', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num><w:abstractNumId w:val="0"/></w:num>
      <w:num w:numId="5"><w:abstractNumId w:val="0"/></w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.size).toBe(1);
    expect(map.has(5)).toBe(true);
  });
});

describe('NumberingResolver — pPr / rPr 解析', () => {
  it('lvl 內 pPr 的 indent 抽出到 indent 欄位、其餘留在 pProps', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0">
          <w:numFmt w:val="decimal"/>
          <w:lvlText w:val="%1."/>
          <w:pPr>
            <w:ind w:left="720" w:hanging="360"/>
            <w:jc w:val="left"/>
          </w:pPr>
        </w:lvl>
      </w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
    `);
    const map = resolver.resolve(xml);
    const lvl = map.get(1)?.levels[0];
    expect(lvl?.indent?.left).toBeCloseTo(36, 1); // 720 twip → 36pt
    expect(lvl?.indent?.hanging).toBeCloseTo(18, 1); // 360 twip → 18pt
    expect(lvl?.pProps?.alignment).toBe('left');
  });

  it('lvl 內 rPr 解析為 runProps', () => {
    const xml = wrap(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0">
          <w:numFmt w:val="decimal"/>
          <w:lvlText w:val="%1."/>
          <w:rPr><w:b/><w:color w:val="0000FF"/></w:rPr>
        </w:lvl>
      </w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
    `);
    const map = resolver.resolve(xml);
    const lvl = map.get(1)?.levels[0];
    expect(lvl?.runProps?.bold).toBe(true);
    expect(lvl?.runProps?.color).toBe('0000FF');
  });
});
