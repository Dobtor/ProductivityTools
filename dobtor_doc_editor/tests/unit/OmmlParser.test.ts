/**
 * OmmlParser 單元測試（Sprint 179、Phase 5.1 OMML 數學公式 capture-only）
 *
 * 用手寫 OMML XML 驗證 parseOmmlChildren 的遞迴解析輸出。
 * 不依賴 fixture .docx — 純 OOXML 行為單元測試。
 */

import { describe, expect, it } from 'vitest';
import { parseOmmlChildren, ommlToLinearText } from '../../static/src/core/ooxml/omml';

const M_NS_DECL =
  'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"';

/** 把 OMML 片段包進 `<m:oMath>` 並解析為 root Element。 */
function parseOMath(innerXml: string): Element {
  const xml = `<?xml version="1.0"?><m:oMath ${M_NS_DECL}>${innerXml}</m:oMath>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.documentElement;
}

describe('OmmlParser — parseOmmlChildren 基礎', () => {
  it('undefined / null → 空陣列', () => {
    expect(parseOmmlChildren(undefined)).toEqual([]);
    expect(parseOmmlChildren(null)).toEqual([]);
  });

  it('空 <m:oMath> → 空陣列', () => {
    expect(parseOmmlChildren(parseOMath(''))).toEqual([]);
  });

  it('<m:t> 文字葉節點 → tag=t + text', () => {
    const tree = parseOmmlChildren(parseOMath('<m:r><m:t>x</m:t></m:r>'));
    expect(tree).toEqual([
      { tag: 'r', children: [{ tag: 't', text: 'x' }] },
    ]);
  });

  it('標籤去 m: 前綴只留 localName', () => {
    const tree = parseOmmlChildren(parseOMath('<m:r><m:t>α</m:t></m:r>'));
    expect(tree[0].tag).toBe('r');
    expect(tree[0].children?.[0].tag).toBe('t');
  });

  it('空 <m:t> → text 為空字串（非 undefined）', () => {
    const tree = parseOmmlChildren(parseOMath('<m:r><m:t></m:t></m:r>'));
    expect(tree[0].children?.[0]).toEqual({ tag: 't', text: '' });
  });

  it('無子節點的結構元素 → 不掛 children key（紀律 #21）', () => {
    const tree = parseOmmlChildren(parseOMath('<m:f/>'));
    expect(tree).toEqual([{ tag: 'f' }]);
    expect('children' in tree[0]).toBe(false);
  });
});

describe('OmmlParser — 結構元素遞迴', () => {
  it('分數 <m:f>（num / den）→ 巢狀樹', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:f>' +
      '<m:num><m:r><m:t>a</m:t></m:r></m:num>' +
      '<m:den><m:r><m:t>b</m:t></m:r></m:den>' +
      '</m:f>',
    ));
    expect(tree).toEqual([
      {
        tag: 'f',
        children: [
          { tag: 'num', children: [{ tag: 'r', children: [{ tag: 't', text: 'a' }] }] },
          { tag: 'den', children: [{ tag: 'r', children: [{ tag: 't', text: 'b' }] }] },
        ],
      },
    ]);
  });

  it('根號 <m:rad>（deg / e）→ 保留結構', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:rad><m:deg/><m:e><m:r><m:t>9</m:t></m:r></m:e></m:rad>',
    ));
    expect(tree[0].tag).toBe('rad');
    expect(tree[0].children?.map((c) => c.tag)).toEqual(['deg', 'e']);
  });

  it('n 元運算 <m:nary>（sub / sup / e）→ 三子節點', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:nary>' +
      '<m:sub><m:r><m:t>0</m:t></m:r></m:sub>' +
      '<m:sup><m:r><m:t>n</m:t></m:r></m:sup>' +
      '<m:e><m:r><m:t>i</m:t></m:r></m:e>' +
      '</m:nary>',
    ));
    expect(tree[0].tag).toBe('nary');
    expect(tree[0].children?.map((c) => c.tag)).toEqual(['sub', 'sup', 'e']);
  });

  it('上下標 <m:sSubSup> → 結構保留', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:sSubSup><m:e><m:r><m:t>x</m:t></m:r></m:e>' +
      '<m:sub><m:r><m:t>1</m:t></m:r></m:sub>' +
      '<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSubSup>',
    ));
    expect(tree[0].tag).toBe('sSubSup');
    expect(tree[0].children?.map((c) => c.tag)).toEqual(['e', 'sub', 'sup']);
  });

  it('矩陣 <m:m>（mr 列 / e 格）→ 多層巢狀', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:m>' +
      '<m:mr><m:e><m:r><m:t>1</m:t></m:r></m:e><m:e><m:r><m:t>2</m:t></m:r></m:e></m:mr>' +
      '<m:mr><m:e><m:r><m:t>3</m:t></m:r></m:e><m:e><m:r><m:t>4</m:t></m:r></m:e></m:mr>' +
      '</m:m>',
    ));
    expect(tree[0].tag).toBe('m');
    expect(tree[0].children).toHaveLength(2);
    expect(tree[0].children?.[0].tag).toBe('mr');
    expect(tree[0].children?.[0].children).toHaveLength(2);
  });

  it('屬性容器 <m:rPr> / <m:ctrlPr> 一併以通用樹保留', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:r><m:rPr><m:sty m:val="p"/></m:rPr><m:t>z</m:t></m:r>',
    ));
    expect(tree[0].children?.map((c) => c.tag)).toEqual(['rPr', 't']);
  });

  it('多個並列子元素 → 順序保留', () => {
    const tree = parseOmmlChildren(parseOMath(
      '<m:r><m:t>a</m:t></m:r><m:r><m:t>+</m:t></m:r><m:r><m:t>b</m:t></m:r>',
    ));
    expect(tree.map((n) => n.children?.[0].text)).toEqual(['a', '+', 'b']);
  });
});

describe('OmmlParser — Sprint 180 屬性捕捉', () => {
  it('元素屬性 → attrs（去 m: 前綴）', () => {
    const tree = parseOmmlChildren(parseOMath('<m:naryPr><m:chr m:val="∑"/></m:naryPr>'));
    expect(tree[0].children?.[0]).toEqual({ tag: 'chr', attrs: { val: '∑' } });
  });

  it('無屬性元素 → 不掛 attrs key（紀律 #21）', () => {
    const tree = parseOmmlChildren(parseOMath('<m:f/>'));
    expect('attrs' in tree[0]).toBe(false);
  });

  it('xmlns 宣告不計入 attrs', () => {
    const tree = parseOmmlChildren(parseOMath('<m:r><m:t>x</m:t></m:r>'));
    // m:oMath 本身帶 xmlns:m，子節點 m:r 無屬性
    expect('attrs' in tree[0]).toBe(false);
  });
});

describe('OmmlParser — Sprint 180 ommlToLinearText 線性化', () => {
  const lin = (inner: string): string => ommlToLinearText(parseOmmlChildren(parseOMath(inner)));

  it('空樹 → 空字串', () => {
    expect(ommlToLinearText([])).toBe('');
  });

  it('純文字 run → 原文字', () => {
    expect(lin('<m:r><m:t>x+1</m:t></m:r>')).toBe('x+1');
  });

  it('分數 → num/den', () => {
    expect(lin(
      '<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>' +
      '<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>',
    )).toBe('a/b');
  });

  it('根號（無 deg）→ √(x)', () => {
    expect(lin('<m:rad><m:deg/><m:e><m:r><m:t>9</m:t></m:r></m:e></m:rad>')).toBe('√(9)');
  });

  it('n 元運算（含 chr 屬性）→ 運算子 + 上下限', () => {
    expect(lin(
      '<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr>' +
      '<m:sub><m:r><m:t>i=0</m:t></m:r></m:sub>' +
      '<m:sup><m:r><m:t>n</m:t></m:r></m:sup>' +
      '<m:e><m:r><m:t>i</m:t></m:r></m:e></m:nary>',
    )).toBe('∑_(i=0)^(n)(i)');
  });

  it('n 元運算無 chr 屬性 → 預設積分符號 ∫', () => {
    expect(lin('<m:nary><m:e><m:r><m:t>f</m:t></m:r></m:e></m:nary>')).toBe('∫(f)');
  });

  it('上下標 sSubSup → x_(1)^(2)', () => {
    expect(lin(
      '<m:sSubSup><m:e><m:r><m:t>x</m:t></m:r></m:e>' +
      '<m:sub><m:r><m:t>1</m:t></m:r></m:sub>' +
      '<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSubSup>',
    )).toBe('x_(1)^(2)');
  });

  it('矩陣 → [a, b; c, d]', () => {
    expect(lin(
      '<m:m>' +
      '<m:mr><m:e><m:r><m:t>1</m:t></m:r></m:e><m:e><m:r><m:t>2</m:t></m:r></m:e></m:mr>' +
      '<m:mr><m:e><m:r><m:t>3</m:t></m:r></m:e><m:e><m:r><m:t>4</m:t></m:r></m:e></m:mr>' +
      '</m:m>',
    )).toBe('[1, 2; 3, 4]');
  });

  it('屬性容器 rPr → 不產生文字', () => {
    expect(lin('<m:r><m:rPr><m:sty m:val="p"/></m:rPr><m:t>z</m:t></m:r>')).toBe('z');
  });
});
