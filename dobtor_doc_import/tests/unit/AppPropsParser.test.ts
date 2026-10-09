/**
 * AppPropsParser.test.ts — Sprint 150 (Phase 1 capture-only、docProps/app.xml)
 *
 * 涵蓋(沿用 Sprint 145-148 capture-only test archetype):
 *   - 字串元素(Template / Application / AppVersion / Company)
 *   - 整數元素(Pages / Words / Characters / Lines / Paragraphs / TotalTime /
 *     CharactersWithSpaces / DocSecurity)
 *   - 布林元素(ScaleCrop / LinksUpToDate / SharedDoc / HyperlinksChanged)
 *   - 真實 fixture 樣本組合
 *   - 防禦邊界
 */

import { describe, expect, it } from 'vitest';
import { parseAppPropsXml } from '../../static/src/core/ooxml/doc-props/AppPropsParser';

const NS =
  'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" ' +
  'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties ${NS}>${inner}</Properties>`;
}

describe('AppPropsParser — 字串元素', () => {
  it('Template + Application + AppVersion + Company', () => {
    const r = parseAppPropsXml(
      wrap(
        '<Template>Normal</Template>' +
          '<Application>Microsoft Office Word</Application>' +
          '<AppVersion>14.0000</AppVersion>' +
          '<Company>maa</Company>',
      ),
    );
    expect(r.template).toBe('Normal');
    expect(r.application).toBe('Microsoft Office Word');
    expect(r.appVersion).toBe('14.0000');
    expect(r.company).toBe('maa');
  });

  it('空字串 → 不掛 key (紀律 #21)', () => {
    const r = parseAppPropsXml(wrap('<Template></Template><Company>   </Company>'));
    expect(r.template).toBeUndefined();
    expect(r.company).toBeUndefined();
  });
});

describe('AppPropsParser — 整數元素', () => {
  it('Pages / Words / Characters / Lines / Paragraphs', () => {
    const r = parseAppPropsXml(
      wrap(
        '<Pages>3</Pages>' +
          '<Words>237</Words>' +
          '<Characters>1356</Characters>' +
          '<Lines>11</Lines>' +
          '<Paragraphs>3</Paragraphs>',
      ),
    );
    expect(r.pages).toBe(3);
    expect(r.words).toBe(237);
    expect(r.characters).toBe(1356);
    expect(r.lines).toBe(11);
    expect(r.paragraphs).toBe(3);
  });

  it('TotalTime + CharactersWithSpaces + DocSecurity', () => {
    const r = parseAppPropsXml(
      wrap(
        '<TotalTime>92</TotalTime>' +
          '<CharactersWithSpaces>1590</CharactersWithSpaces>' +
          '<DocSecurity>0</DocSecurity>',
      ),
    );
    expect(r.totalTime).toBe(92);
    expect(r.charactersWithSpaces).toBe(1590);
    expect(r.docSecurity).toBe(0);
  });

  it('非數字字串 → 不掛 key (紀律 #21)', () => {
    const r = parseAppPropsXml(wrap('<Pages>abc</Pages>'));
    expect(r.pages).toBeUndefined();
  });

  it('小數 → 不掛 key (整數 only、嚴格)', () => {
    const r = parseAppPropsXml(wrap('<Words>3.14</Words>'));
    expect(r.words).toBeUndefined();
  });

  it('負整數合法 → 解析(用於異常 edge case)', () => {
    const r = parseAppPropsXml(wrap('<TotalTime>-1</TotalTime>'));
    expect(r.totalTime).toBe(-1);
  });
});

describe('AppPropsParser — 布林元素', () => {
  it('ScaleCrop true / false', () => {
    expect(parseAppPropsXml(wrap('<ScaleCrop>true</ScaleCrop>')).scaleCrop).toBe(true);
    expect(parseAppPropsXml(wrap('<ScaleCrop>false</ScaleCrop>')).scaleCrop).toBe(false);
  });

  it('LinksUpToDate + SharedDoc + HyperlinksChanged', () => {
    const r = parseAppPropsXml(
      wrap(
        '<LinksUpToDate>false</LinksUpToDate>' +
          '<SharedDoc>false</SharedDoc>' +
          '<HyperlinksChanged>false</HyperlinksChanged>',
      ),
    );
    expect(r.linksUpToDate).toBe(false);
    expect(r.sharedDoc).toBe(false);
    expect(r.hyperlinksChanged).toBe(false);
  });

  it('大小寫不敏感 (TRUE / True)', () => {
    expect(parseAppPropsXml(wrap('<ScaleCrop>TRUE</ScaleCrop>')).scaleCrop).toBe(true);
    expect(parseAppPropsXml(wrap('<ScaleCrop>True</ScaleCrop>')).scaleCrop).toBe(true);
  });

  it('"1" / "0" 不合法布林 → 不掛 key (紀律 #21、嚴格規格)', () => {
    expect(parseAppPropsXml(wrap('<ScaleCrop>1</ScaleCrop>')).scaleCrop).toBeUndefined();
    expect(parseAppPropsXml(wrap('<ScaleCrop>0</ScaleCrop>')).scaleCrop).toBeUndefined();
  });

  it('空值 → 不掛 key', () => {
    expect(parseAppPropsXml(wrap('<ScaleCrop></ScaleCrop>')).scaleCrop).toBeUndefined();
  });
});

describe('AppPropsParser — 真實 fixture 樣本', () => {
  it('完整 Word 14 fixture 樣本(17 elements)', () => {
    const xml = wrap(
      '<Template>Normal</Template>' +
        '<TotalTime>92</TotalTime>' +
        '<Pages>3</Pages>' +
        '<Words>237</Words>' +
        '<Characters>1356</Characters>' +
        '<Application>Microsoft Office Word</Application>' +
        '<DocSecurity>0</DocSecurity>' +
        '<Lines>11</Lines>' +
        '<Paragraphs>3</Paragraphs>' +
        '<ScaleCrop>false</ScaleCrop>' +
        '<Company>maa</Company>' +
        '<LinksUpToDate>false</LinksUpToDate>' +
        '<CharactersWithSpaces>1590</CharactersWithSpaces>' +
        '<SharedDoc>false</SharedDoc>' +
        '<HyperlinksChanged>false</HyperlinksChanged>' +
        '<AppVersion>14.0000</AppVersion>',
    );
    const r = parseAppPropsXml(xml);
    expect(r).toEqual({
      template: 'Normal',
      totalTime: 92,
      pages: 3,
      words: 237,
      characters: 1356,
      application: 'Microsoft Office Word',
      docSecurity: 0,
      lines: 11,
      paragraphs: 3,
      scaleCrop: false,
      company: 'maa',
      linksUpToDate: false,
      charactersWithSpaces: 1590,
      sharedDoc: false,
      hyperlinksChanged: false,
      appVersion: '14.0000',
    });
  });

  it('部分欄位缺失 → 只掛存在的 key', () => {
    const r = parseAppPropsXml(wrap('<Application>WPS</Application><Pages>1</Pages>'));
    expect(r).toEqual({ application: 'WPS', pages: 1 });
  });
});

describe('AppPropsParser — 防禦邊界', () => {
  it('undefined → {}', () => {
    expect(parseAppPropsXml(undefined as never)).toEqual({});
  });

  it('空字串 → {}', () => {
    expect(parseAppPropsXml('')).toEqual({});
  });

  it('只有空白 → {}', () => {
    expect(parseAppPropsXml('   \n  ')).toEqual({});
  });

  it('壞 XML → {} (不 throw)', () => {
    expect(parseAppPropsXml('<Properties><not closed>')).toEqual({});
  });

  it('完全空的 Properties 骨架 → {}', () => {
    expect(parseAppPropsXml(wrap(''))).toEqual({});
  });

  it('未知元素被忽略 (不影響已知元素解析)', () => {
    const r = parseAppPropsXml(
      wrap('<Pages>1</Pages><UnknownFutureElement>foo</UnknownFutureElement>'),
    );
    expect(r).toEqual({ pages: 1 });
  });
});
