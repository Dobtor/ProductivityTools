/**
 * Sprint 285 — Phase 1 optional bucket 4/6：`<w:lvlOverride>` audit + tests
 *
 * Status：parser 已完整支援（startOverride / integral lvl override / multi-ilvl）。
 * Writer 走 Sprint 191 clone-per-num 策略（每個 num 一個 abstractNum）；
 * lvlOverride 結構在 round-trip 後被 baked 進 abstractNum，display 語意保留、
 * 但 raw XML 結構 lossy。
 *
 * 本 sprint = Strategy C 純 audit 補完整測試覆蓋：
 *   - 既有 2 案（NumberingResolver.test.ts）只覆蓋基本 startOverride / 整層 lvl
 *   - 補：multi-ilvl 同一 num / 與 base lvl 共存 / w:lvl 完整子元素 / round-trip 語意
 *
 * 紀律 #18 scope-down：不重寫 Sprint 191 writer 策略；raw byte preservation 走
 * Sprint 270-274 「第十九層 raw byte preserve」模式（user 未要求、deferred）。
 */
import { describe, expect, it } from 'vitest';
import { unzipSync, strFromU8 } from 'fflate';

import { NumberingResolver } from '../../static/src/core/ooxml/numbering/NumberingResolver';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type {
  AbstractNumbering,
  DocumentNode,
  NumberingMap,
  SectionNode,
} from '../../static/src/core/ooxml/ast/types';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrapNumbering(inner: string): string {
  return `<?xml version="1.0"?><w:numbering ${W_NS}>${inner}</w:numbering>`;
}

function makeDocWithNumbering(numbering: NumberingMap): DocumentNode {
  const section: SectionNode = {
    type: 'section',
    page: { width: 595.3, height: 841.9, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body: [],
  };
  return {
    type: 'document',
    sections: [section],
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    comments: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering,
    media: new Map(),
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  } as unknown as DocumentNode;
}

describe('Sprint 285 — w:lvlOverride parser audit (existing 2 tests + 補強)', () => {
  const resolver = new NumberingResolver();

  it('Multi-ilvl override on same num：兩個 lvlOverride 不同 ilvl 都套用', () => {
    const xml = wrapNumbering(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
        <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="5">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0"><w:startOverride w:val="10"/></w:lvlOverride>
        <w:lvlOverride w:ilvl="1"><w:startOverride w:val="20"/></w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(5)?.levels[0].start).toBe(10);
    expect(map.get(5)?.levels[1].start).toBe(20);
  });

  it('startOverride + integral lvl override 混合在不同 ilvl', () => {
    const xml = wrapNumbering(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
        <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%2."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="6">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0">
          <w:startOverride w:val="50"/>
        </w:lvlOverride>
        <w:lvlOverride w:ilvl="1">
          <w:lvl w:ilvl="1">
            <w:numFmt w:val="bullet"/>
            <w:lvlText w:val="•"/>
            <w:start w:val="1"/>
          </w:lvl>
        </w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(6)?.levels[0].start).toBe(50);
    expect(map.get(6)?.levels[0].numFmt).toBe('decimal');
    expect(map.get(6)?.levels[1].numFmt).toBe('bullet');
    expect(map.get(6)?.levels[1].text).toBe('•');
  });

  it('lvlOverride 含 w:lvl 但 base abstract 該 ilvl 不存在 → push 新 level', () => {
    const xml = wrapNumbering(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="7">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="2">
          <w:lvl w:ilvl="2">
            <w:numFmt w:val="bullet"/>
            <w:lvlText w:val="●"/>
            <w:start w:val="1"/>
          </w:lvl>
        </w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    const lvls = map.get(7)!.levels;
    expect(lvls).toHaveLength(2);
    // 排序後 ilvl 0 第一、ilvl 2 第二（applyOverrides 末 sort by ilvl）
    expect(lvls[0].ilvl).toBe(0);
    expect(lvls[1].ilvl).toBe(2);
    expect(lvls[1].numFmt).toBe('bullet');
  });

  it('lvlOverride 缺 w:ilvl 屬性 → 跳過、不 throw', () => {
    const xml = wrapNumbering(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="8">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride><w:startOverride w:val="99"/></w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    expect(map.get(8)?.levels[0].start).toBe(1);  // override 跳過、原值保留
  });

  it('lvlOverride 內含整層 w:lvl + startOverride → integral lvl 優先（per applyOverrides 邏輯）', () => {
    const xml = wrapNumbering(`
      <w:abstractNum w:abstractNumId="0">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
      </w:abstractNum>
      <w:num w:numId="9">
        <w:abstractNumId w:val="0"/>
        <w:lvlOverride w:ilvl="0">
          <w:startOverride w:val="999"/>
          <w:lvl w:ilvl="0">
            <w:start w:val="7"/>
            <w:numFmt w:val="bullet"/>
            <w:lvlText w:val="*"/>
          </w:lvl>
        </w:lvlOverride>
      </w:num>
    `);
    const map = resolver.resolve(xml);
    // applyOverrides: 若 ov.level 存在則整層 replace、startOverride 被忽略
    expect(map.get(9)?.levels[0].start).toBe(7);
    expect(map.get(9)?.levels[0].numFmt).toBe('bullet');
  });
});

describe('Sprint 285 — w:lvlOverride 語意 round-trip（Sprint 191 clone-per-num 策略下）', () => {
  it('startOverride 經 OoxmlWriter → re-parse 後 levels[0].start 仍為 override 值', async () => {
    const abstract: AbstractNumbering = {
      abstractNumId: 0,
      levels: [{
        ilvl: 0,
        numFmt: 'decimal',
        text: '%1.',
        start: 100,  // override applied
      }],
    };
    const numbering: NumberingMap = new Map([[5, abstract]]);
    const doc = makeDocWithNumbering(numbering);

    const writer = new OoxmlWriter();
    const bytes = writer.write(doc);

    const unzipped = unzipSync(bytes);
    const numberingXml = strFromU8(unzipped['word/numbering.xml']);
    // Sprint 191：每個 num 自己的 abstractNum、start 直接 baked
    expect(numberingXml).toContain('<w:start w:val="100"/>');

    const parser = new OoxmlParser();
    const reParsed = await parser.parse(bytes);
    expect(reParsed.numbering.get(5)?.levels[0].start).toBe(100);
  });

  it('Integral lvl override（bullet 取代 decimal）經 round-trip 後 numFmt 保留', async () => {
    const abstract: AbstractNumbering = {
      abstractNumId: 0,
      levels: [{
        ilvl: 0,
        numFmt: 'bullet',  // overridden from decimal
        text: '•',
        start: 1,
      }],
    };
    const numbering: NumberingMap = new Map([[3, abstract]]);
    const doc = makeDocWithNumbering(numbering);

    const writer = new OoxmlWriter();
    const bytes = writer.write(doc);
    const parser = new OoxmlParser();
    const reParsed = await parser.parse(bytes);

    expect(reParsed.numbering.get(3)?.levels[0].numFmt).toBe('bullet');
    expect(reParsed.numbering.get(3)?.levels[0].text).toBe('•');
  });

  it('Multi-num 各自獨立（Sprint 191 clone strategy、不共享 abstract）', async () => {
    const num1: AbstractNumbering = {
      abstractNumId: 0,
      levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 1 }],
    };
    const num2: AbstractNumbering = {
      abstractNumId: 0,
      levels: [{ ilvl: 0, numFmt: 'decimal', text: '%1.', start: 50 }],  // override
    };
    const numbering: NumberingMap = new Map([[1, num1], [2, num2]]);
    const doc = makeDocWithNumbering(numbering);

    const writer = new OoxmlWriter();
    const bytes = writer.write(doc);
    const parser = new OoxmlParser();
    const reParsed = await parser.parse(bytes);

    expect(reParsed.numbering.get(1)?.levels[0].start).toBe(1);
    expect(reParsed.numbering.get(2)?.levels[0].start).toBe(50);
  });
});
