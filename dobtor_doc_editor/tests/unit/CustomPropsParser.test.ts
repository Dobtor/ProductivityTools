/**
 * CustomPropsParser.test.ts — Sprint 151 (Phase 1 capture-only、docProps/custom.xml)
 *
 * 涵蓋:
 *   - 字串 variant(vt:lpwstr / vt:lpstr / vt:bstr)
 *   - 整數 variant(vt:i4 / vt:i8 / vt:int / vt:uint)
 *   - 布林 variant(vt:bool、含 "1"/"0" 寬鬆 + true/false)
 *   - 浮點 variant(vt:r4 / vt:r8 / vt:decimal)
 *   - filetime variant(vt:filetime / vt:date)
 *   - 未知 variant 降級 unknown
 *   - 真實 fixture 樣本(KSO + Grammarly)
 *   - 防禦邊界
 */

import { describe, expect, it } from 'vitest';
import { parseCustomPropsXml } from '../../static/src/core/ooxml/doc-props/CustomPropsParser';

const NS =
  'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" ' +
  'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"';
const FMTID = '{D5CDD505-2E9C-101B-9397-08002B2CF9AE}';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties ${NS}>${inner}</Properties>`;
}

function prop(name: string, vtVariant: string, pid = 2): string {
  return `<property fmtid="${FMTID}" pid="${pid}" name="${name}">${vtVariant}</property>`;
}

describe('CustomPropsParser — 字串 variant', () => {
  it('vt:lpwstr → kind: string', () => {
    const r = parseCustomPropsXml(wrap(prop('Foo', '<vt:lpwstr>hello</vt:lpwstr>')));
    expect(r.get('Foo')).toEqual({ kind: 'string', value: 'hello' });
  });

  it('vt:lpstr → kind: string', () => {
    const r = parseCustomPropsXml(wrap(prop('Foo', '<vt:lpstr>bar</vt:lpstr>')));
    expect(r.get('Foo')).toEqual({ kind: 'string', value: 'bar' });
  });

  it('vt:bstr → kind: string', () => {
    const r = parseCustomPropsXml(wrap(prop('Foo', '<vt:bstr>baz</vt:bstr>')));
    expect(r.get('Foo')).toEqual({ kind: 'string', value: 'baz' });
  });

  it('空字串字串 variant 合法(允許顯式空值)', () => {
    const r = parseCustomPropsXml(wrap(prop('Foo', '<vt:lpwstr></vt:lpwstr>')));
    expect(r.get('Foo')).toEqual({ kind: 'string', value: '' });
  });

  it('CJK 字串 variant', () => {
    const r = parseCustomPropsXml(wrap(prop('Foo', '<vt:lpwstr>監造日誌</vt:lpwstr>')));
    expect(r.get('Foo')).toEqual({ kind: 'string', value: '監造日誌' });
  });
});

describe('CustomPropsParser — 整數 variant', () => {
  it('vt:i4 → kind: int', () => {
    const r = parseCustomPropsXml(wrap(prop('N', '<vt:i4>42</vt:i4>')));
    expect(r.get('N')).toEqual({ kind: 'int', value: 42 });
  });

  it('vt:i8 / vt:int / vt:uint', () => {
    const r = parseCustomPropsXml(
      wrap(prop('a', '<vt:i8>123</vt:i8>') + prop('b', '<vt:int>-5</vt:int>') + prop('c', '<vt:uint>7</vt:uint>')),
    );
    expect(r.get('a')).toEqual({ kind: 'int', value: 123 });
    expect(r.get('b')).toEqual({ kind: 'int', value: -5 });
    expect(r.get('c')).toEqual({ kind: 'int', value: 7 });
  });

  it('非數字字串於整數 variant → 跳過該 property (紀律 #21)', () => {
    const r = parseCustomPropsXml(wrap(prop('N', '<vt:i4>abc</vt:i4>')));
    expect(r.has('N')).toBe(false);
  });

  it('小數於 i4 → 跳過(嚴格整數)', () => {
    const r = parseCustomPropsXml(wrap(prop('N', '<vt:i4>3.14</vt:i4>')));
    expect(r.has('N')).toBe(false);
  });
});

describe('CustomPropsParser — 布林 variant', () => {
  it('true / false', () => {
    const r = parseCustomPropsXml(
      wrap(prop('a', '<vt:bool>true</vt:bool>') + prop('b', '<vt:bool>false</vt:bool>')),
    );
    expect(r.get('a')).toEqual({ kind: 'bool', value: true });
    expect(r.get('b')).toEqual({ kind: 'bool', value: false });
  });

  it('"1" / "0" 寬鬆相容(vt:bool 允許數字字串)', () => {
    const r = parseCustomPropsXml(
      wrap(prop('a', '<vt:bool>1</vt:bool>') + prop('b', '<vt:bool>0</vt:bool>')),
    );
    expect(r.get('a')).toEqual({ kind: 'bool', value: true });
    expect(r.get('b')).toEqual({ kind: 'bool', value: false });
  });

  it('大小寫不敏感', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:bool>TRUE</vt:bool>')));
    expect(r.get('a')).toEqual({ kind: 'bool', value: true });
  });

  it('不合法布林值 → 跳過', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:bool>yes</vt:bool>')));
    expect(r.has('a')).toBe(false);
  });
});

describe('CustomPropsParser — 浮點 variant', () => {
  it('vt:r4 / vt:r8 / vt:decimal', () => {
    const r = parseCustomPropsXml(
      wrap(
        prop('a', '<vt:r4>3.14</vt:r4>') +
          prop('b', '<vt:r8>-2.5</vt:r8>') +
          prop('c', '<vt:decimal>100</vt:decimal>'),
      ),
    );
    expect(r.get('a')).toEqual({ kind: 'real', value: 3.14 });
    expect(r.get('b')).toEqual({ kind: 'real', value: -2.5 });
    expect(r.get('c')).toEqual({ kind: 'real', value: 100 });
  });

  it('NaN / Infinity 解析失敗 → 跳過', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:r8>not-a-number</vt:r8>')));
    expect(r.has('a')).toBe(false);
  });
});

describe('CustomPropsParser — filetime variant', () => {
  it('vt:filetime → kind: filetime (保留原 ISO 字串)', () => {
    const r = parseCustomPropsXml(
      wrap(prop('a', '<vt:filetime>2026-05-19T10:00:00Z</vt:filetime>')),
    );
    expect(r.get('a')).toEqual({ kind: 'filetime', value: '2026-05-19T10:00:00Z' });
  });

  it('vt:date → kind: filetime', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:date>2026-05-19</vt:date>')));
    expect(r.get('a')).toEqual({ kind: 'filetime', value: '2026-05-19' });
  });

  it('空 filetime → 跳過', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:filetime></vt:filetime>')));
    expect(r.has('a')).toBe(false);
  });
});

describe('CustomPropsParser — 未知 variant 降級', () => {
  it('vt:vector → unknown', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:vector>raw payload</vt:vector>')));
    expect(r.get('a')).toEqual({ kind: 'unknown', raw: 'raw payload' });
  });

  it('vt:cy → unknown', () => {
    const r = parseCustomPropsXml(wrap(prop('a', '<vt:cy>1500.00</vt:cy>')));
    expect(r.get('a')).toEqual({ kind: 'unknown', raw: '1500.00' });
  });
});

describe('CustomPropsParser — 真實 fixture 樣本', () => {
  it('KSO + Grammarly 組合(實 fixture 主流結構)', () => {
    const xml = wrap(
      prop('KSOProductBuildVer', '<vt:lpwstr>1028-10.8.0.6003</vt:lpwstr>') +
        prop('GrammarlyDocumentId', '<vt:lpwstr>f25e78ec-68d7-4d1f-8f3e-68ee93ed95f9</vt:lpwstr>', 3),
    );
    const r = parseCustomPropsXml(xml);
    expect(r.size).toBe(2);
    expect(r.get('KSOProductBuildVer')).toEqual({ kind: 'string', value: '1028-10.8.0.6003' });
    expect(r.get('GrammarlyDocumentId')).toEqual({
      kind: 'string',
      value: 'f25e78ec-68d7-4d1f-8f3e-68ee93ed95f9',
    });
  });
});

describe('CustomPropsParser — 防禦邊界', () => {
  it('undefined → 空 Map', () => {
    expect(parseCustomPropsXml(undefined as never).size).toBe(0);
  });

  it('空字串 → 空 Map', () => {
    expect(parseCustomPropsXml('').size).toBe(0);
  });

  it('壞 XML → 空 Map (不 throw)', () => {
    expect(parseCustomPropsXml('<Properties><not closed>').size).toBe(0);
  });

  it('空 Properties → 空 Map', () => {
    expect(parseCustomPropsXml(wrap('')).size).toBe(0);
  });

  it('property 缺 name 屬性 → 跳過該 property (紀律 #21)', () => {
    const xml = `<?xml version="1.0"?>\n<Properties ${NS}><property fmtid="${FMTID}" pid="2"><vt:lpwstr>orphan</vt:lpwstr></property></Properties>`;
    expect(parseCustomPropsXml(xml).size).toBe(0);
  });

  it('property name 為空字串 → 跳過', () => {
    const xml = wrap(prop('', '<vt:lpwstr>foo</vt:lpwstr>'));
    expect(parseCustomPropsXml(xml).size).toBe(0);
  });

  it('property 無 vt:* 子元素 → 跳過', () => {
    const xml = `<?xml version="1.0"?>\n<Properties ${NS}><property fmtid="${FMTID}" pid="2" name="Empty"></property></Properties>`;
    expect(parseCustomPropsXml(xml).size).toBe(0);
  });

  it('重複 name → 後者覆蓋前者', () => {
    const xml = wrap(
      prop('Same', '<vt:lpwstr>first</vt:lpwstr>') +
        prop('Same', '<vt:lpwstr>second</vt:lpwstr>'),
    );
    const r = parseCustomPropsXml(xml);
    expect(r.size).toBe(1);
    expect(r.get('Same')).toEqual({ kind: 'string', value: 'second' });
  });
});
