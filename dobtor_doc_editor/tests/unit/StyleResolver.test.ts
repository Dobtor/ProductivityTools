/**
 * StyleResolver 單元測試 (Phase B.1)
 *
 * 用手寫 word/styles.xml 字串驗證：
 *   1. docDefaults 解析
 *   2. <w:style> 收集
 *   3. basedOn 多層繼承展開
 *   4. 迴圈偵測（A→B→A 不會無窮迴圈）
 *   5. 缺失 basedOn 視為無 parent
 *   6. 跨層 merge：docDefaults < 遠祖 < 父 < 本身
 */

import { describe, expect, it } from 'vitest';
import { StyleResolver } from '../../static/src/core/ooxml/styles/StyleResolver';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0"?><w:styles ${W_NS}>${inner}</w:styles>`;
}

const resolver = new StyleResolver();

describe('StyleResolver — 基本', () => {
  it('undefined 輸入回空 Map', () => {
    expect(resolver.resolve(undefined).size).toBe(0);
  });

  it('空 styles.xml 回空 Map', () => {
    expect(resolver.resolve(wrap('')).size).toBe(0);
  });

  it('單一 style 無繼承', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="Heading1">
        <w:rPr><w:b/></w:rPr>
        <w:pPr><w:jc w:val="center"/></w:pPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.size).toBe(1);
    const h1 = map.get('Heading1');
    expect(h1?.rProps?.bold).toBe(true);
    expect(h1?.pProps?.alignment).toBe('center');
  });
});

describe('StyleResolver — docDefaults', () => {
  it('docDefaults 套用到所有 style（無 explicit override）', () => {
    const xml = wrap(`
      <w:docDefaults>
        <w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault>
        <w:pPrDefault><w:pPr><w:jc w:val="left"/></w:pPr></w:pPrDefault>
      </w:docDefaults>
      <w:style w:type="paragraph" w:styleId="Body">
        <w:rPr><w:b/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const body = map.get('Body');
    expect(body?.rProps?.fontSize).toBe(12); // sz=24 half-points → 12pt
    expect(body?.rProps?.bold).toBe(true);
    expect(body?.pProps?.alignment).toBe('left');
  });

  it('explicit 屬性覆蓋 docDefaults', () => {
    const xml = wrap(`
      <w:docDefaults>
        <w:rPrDefault><w:rPr><w:sz w:val="20"/></w:rPr></w:rPrDefault>
      </w:docDefaults>
      <w:style w:type="paragraph" w:styleId="Title">
        <w:rPr><w:sz w:val="40"/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.get('Title')?.rProps?.fontSize).toBe(20); // sz=40 half-points → 20pt
  });
});

describe('StyleResolver — basedOn 繼承鏈', () => {
  it('兩層繼承：B basedOn A', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="A">
        <w:rPr><w:b/></w:rPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="B">
        <w:basedOn w:val="A"/>
        <w:rPr><w:i/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const b = map.get('B');
    expect(b?.rProps?.bold).toBe(true); // 從 A 繼承
    expect(b?.rProps?.italic).toBe(true); // 自身
    expect(b?.basedOn).toBe('A');
  });

  it('五層繼承（A → B → C → D → E）', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="A"><w:rPr><w:b/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="B"><w:basedOn w:val="A"/><w:rPr><w:i/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="C"><w:basedOn w:val="B"/><w:rPr><w:strike/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="D"><w:basedOn w:val="C"/><w:pPr><w:jc w:val="right"/></w:pPr></w:style>
      <w:style w:type="paragraph" w:styleId="E"><w:basedOn w:val="D"/><w:rPr><w:color w:val="FF0000"/></w:rPr></w:style>
    `);
    const map = resolver.resolve(xml);
    const e = map.get('E');
    expect(e?.rProps?.bold).toBe(true);
    expect(e?.rProps?.italic).toBe(true);
    expect(e?.rProps?.strike).toBe(true);
    expect(e?.rProps?.color).toBe('FF0000');
    expect(e?.pProps?.alignment).toBe('right');
  });

  it('子覆寫父屬性（後者勝出）', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="P"><w:rPr><w:sz w:val="20"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="C"><w:basedOn w:val="P"/><w:rPr><w:sz w:val="40"/></w:rPr></w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.get('C')?.rProps?.fontSize).toBe(20); // sz=40 → 20pt
    expect(map.get('P')?.rProps?.fontSize).toBe(10); // sz=20 → 10pt
  });
});

describe('StyleResolver — 邊界', () => {
  it('迴圈 A→B→A 不無窮迴圈，停在第一次重複的祖先', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="A">
        <w:basedOn w:val="B"/>
        <w:rPr><w:b/></w:rPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="B">
        <w:basedOn w:val="A"/>
        <w:rPr><w:i/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.size).toBe(2);
    // 不 throw 即過關；屬性結果不嚴格指定（依 chain 走訪順序而定）
    expect(map.get('A')?.rProps).toBeDefined();
    expect(map.get('B')?.rProps).toBeDefined();
  });

  it('basedOn 指向不存在的 styleId 視為無 parent', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="X">
        <w:basedOn w:val="DoesNotExist"/>
        <w:rPr><w:b/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.get('X')?.rProps?.bold).toBe(true);
    expect(map.get('X')?.basedOn).toBe('DoesNotExist');
  });

  it('沒 styleId 的 <w:style> 跳過', () => {
    const xml = wrap(`
      <w:style w:type="paragraph">
        <w:rPr><w:b/></w:rPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="OK">
        <w:rPr><w:i/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.size).toBe(1);
    expect(map.has('OK')).toBe(true);
  });
});

describe('StyleResolver — Sprint 131 tblStylePr/tcPr 解析', () => {
  it('解析 tblStylePr/firstRow/tcPr/shd → conditional.cProps.shading', () => {
    const xml = wrap(`
      <w:style w:type="table" w:styleId="TableGrid1">
        <w:tblStylePr w:type="firstRow">
          <w:rPr><w:b/></w:rPr>
          <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="DEEAF6"/></w:tcPr>
        </w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const t = map.get('TableGrid1');
    const firstRow = t?.conditional?.get('firstRow');
    expect(firstRow?.rProps?.bold).toBe(true);
    expect(firstRow?.cProps?.shading?.fill).toBe('DEEAF6');
    expect(firstRow?.cProps?.shading?.pattern).toBe('clear');
  });

  it('解析 tblStylePr/lastCol/tcPr/vAlign → conditional.cProps.vAlign', () => {
    const xml = wrap(`
      <w:style w:type="table" w:styleId="TG">
        <w:tblStylePr w:type="lastCol">
          <w:tcPr><w:vAlign w:val="center"/></w:tcPr>
        </w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const t = map.get('TG');
    const lastCol = t?.conditional?.get('lastCol');
    expect(lastCol?.cProps?.vAlign).toBe('center');
    expect(lastCol?.cProps?.shading).toBeUndefined();
  });

  it('Sprint 284：tcBorders 現已開通、cProps.borders 讀到（更新 Sprint 131 defer 假設）', () => {
    const xml = wrap(`
      <w:style w:type="table" w:styleId="TG">
        <w:tblStylePr w:type="firstRow">
          <w:rPr><w:b/></w:rPr>
          <w:tcPr><w:tcBorders><w:top w:val="single"/></w:tcBorders></w:tcPr>
        </w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const firstRow = map.get('TG')?.conditional?.get('firstRow');
    expect(firstRow?.rProps?.bold).toBe(true);
    // Sprint 284：tcBorders 已從 defer 改為支援；borders.top 應讀到（style only，無 sz/color → width=0、color='auto'）
    expect(firstRow?.cProps?.borders?.top).toBeDefined();
    expect(firstRow?.cProps?.borders?.top?.style).toBe('single');
    expect(firstRow?.cProps?.shading).toBeUndefined();  // shading 仍未提供 → undefined
    expect(firstRow?.cProps?.vAlign).toBeUndefined();   // vAlign 仍未提供 → undefined
  });

  it('w:vAlign 無效值（如 baseline）不掛 vAlign key', () => {
    const xml = wrap(`
      <w:style w:type="table" w:styleId="TG">
        <w:tblStylePr w:type="firstRow">
          <w:tcPr><w:vAlign w:val="baseline"/></w:tcPr>
        </w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const firstRow = map.get('TG')?.conditional?.get('firstRow');
    expect(firstRow?.cProps).toBeUndefined(); // baseline 非 top/center/bottom、空 cProps 不掛
  });
});

describe('StyleResolver — 巢狀屬性合併', () => {
  it('indent 各 sub-key 獨立合併（不整個覆蓋）', () => {
    const xml = wrap(`
      <w:style w:type="paragraph" w:styleId="P">
        <w:pPr><w:ind w:left="720" w:firstLine="240"/></w:pPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="C">
        <w:basedOn w:val="P"/>
        <w:pPr><w:ind w:right="360"/></w:pPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const c = map.get('C');
    // 三個 indent sub-key 都應在最終結果中
    expect(c?.pProps?.indent?.left).toBeCloseTo(36, 1); // 720 twip / 20 = 36pt
    expect(c?.pProps?.indent?.firstLine).toBeCloseTo(12, 1); // 240 twip / 20 = 12pt
    expect(c?.pProps?.indent?.right).toBeCloseTo(18, 1); // 360 twip / 20 = 18pt
  });
});
