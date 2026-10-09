/**
 * Phase B+ 補完測試
 *
 * 5 項漏網元素補完後的端到端驗證：
 *   1. <w:hyperlink> URL 記錄（rId / url / anchor / tooltip）
 *   2. <w:tabs> tab stops 解析
 *   3. <mc:AlternateContent> Choice / Fallback 展開
 *   4. rFonts 4 屬性（ascii/eastAsia/hAnsi/cs）
 *   5. <w:tblStylePr> 條件樣式收集
 */

import { describe, expect, it } from 'vitest';
import { ParagraphParser } from '../../static/src/core/ooxml/document/ParagraphParser';
import { StyleResolver } from '../../static/src/core/ooxml/styles/StyleResolver';
import {
  effectiveChildren,
  directChildren,
} from '../../static/src/core/ooxml/utils/dom';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';
const R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
const MC_NS = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"';
const NS = `${W_NS} ${R_NS} ${MC_NS}`;

function parsePFragment(inner: string): Element {
  const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p>${inner}</w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:p')[0];
}

function parseStylesXml(inner: string): string {
  return `<?xml version="1.0"?><w:styles ${NS}>${inner}</w:styles>`;
}

// ── 1. <w:hyperlink> URL 記錄 ────────────────────────────────────────────────

describe('Phase B+.1 — w:hyperlink URL 記錄', () => {
  const parser = new ParagraphParser();

  it('External URL：rId 透過 lookup 解析為 URL', () => {
    parser.setRelsLookup((rId) =>
      rId === 'rId5' ? 'https://anthropic.com' : undefined,
    );
    const p = parsePFragment(`
      <w:hyperlink r:id="rId5" w:tooltip="點此前往">
        <w:r><w:t>Anthropic</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.text).toBe('Anthropic');
    expect(r.hyperlink?.rId).toBe('rId5');
    expect(r.hyperlink?.url).toBe('https://anthropic.com');
    expect(r.hyperlink?.tooltip).toBe('點此前往');
  });

  it('文件內 anchor（無 rId）', () => {
    const p = parsePFragment(`
      <w:hyperlink w:anchor="bookmark1">
        <w:r><w:t>跳到書籤</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.anchor).toBe('bookmark1');
    expect(r.hyperlink?.url).toBeUndefined();
  });

  it('沒有 lookup 時 url 留空但 rId 仍記錄', () => {
    const p2parser = new ParagraphParser();
    // 不呼叫 setRelsLookup
    const p = parsePFragment(`
      <w:hyperlink r:id="rId10">
        <w:r><w:t>x</w:t></w:r>
      </w:hyperlink>
    `);
    const node = p2parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.rId).toBe('rId10');
    expect(r.hyperlink?.url).toBeUndefined();
  });

  it('hyperlink 內多個 run 都帶 hyperlink 標記', () => {
    parser.setRelsLookup(() => 'https://example.com');
    const p = parsePFragment(`
      <w:hyperlink r:id="rId1">
        <w:r><w:t>part1</w:t></w:r>
        <w:r><w:t>part2</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(2);
    for (const r of node.runs) {
      if (r.type !== 'run') continue;
      expect(r.hyperlink?.url).toBe('https://example.com');
    }
  });

  it('普通 run（hyperlink 外）不帶 hyperlink 欄位', () => {
    const p = parsePFragment(`
      <w:r><w:t>plain</w:t></w:r>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink).toBeUndefined();
  });
});

// ── 2. <w:tabs> tab stops ─────────────────────────────────────────────────────

describe('Phase B+.2 — w:tabs tab stops', () => {
  const parser = new ParagraphParser();

  it('解析多個 tab stops 並按 pos 排序', () => {
    const p = parsePFragment(`
      <w:pPr>
        <w:tabs>
          <w:tab w:val="right" w:pos="9000"/>
          <w:tab w:val="left" w:pos="2880" w:leader="dot"/>
          <w:tab w:val="center" w:pos="5760"/>
        </w:tabs>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.tabs).toHaveLength(3);
    // 已按 pos 升序排序
    expect(node.props.tabs?.[0].pos).toBeCloseTo(144, 1); // 2880 twip → 144pt
    expect(node.props.tabs?.[0].align).toBe('left');
    expect(node.props.tabs?.[0].leader).toBe('dot');
    expect(node.props.tabs?.[1].pos).toBeCloseTo(288, 1); // 5760 twip → 288pt
    expect(node.props.tabs?.[1].align).toBe('center');
    expect(node.props.tabs?.[2].pos).toBeCloseTo(450, 1); // 9000 twip → 450pt
    expect(node.props.tabs?.[2].align).toBe('right');
  });

  it('val="clear" 跳過記錄', () => {
    const p = parsePFragment(`
      <w:pPr>
        <w:tabs>
          <w:tab w:val="clear" w:pos="2880"/>
          <w:tab w:val="left" w:pos="5760"/>
        </w:tabs>
      </w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.tabs).toHaveLength(1);
    expect(node.props.tabs?.[0].pos).toBeCloseTo(288, 1);
  });

  it('val="decimal" 對齊', () => {
    const p = parsePFragment(`
      <w:pPr><w:tabs><w:tab w:val="decimal" w:pos="2880"/></w:tabs></w:pPr>
    `);
    const node = parser.parse(p);
    expect(node.props.tabs?.[0].align).toBe('decimal');
  });

  it('沒有 w:tabs 時 props.tabs 為 undefined', () => {
    const p = parsePFragment('<w:r><w:t>x</w:t></w:r>');
    const node = parser.parse(p);
    expect(node.props.tabs).toBeUndefined();
  });
});

// ── 3. <mc:AlternateContent> Choice/Fallback ────────────────────────────────

describe('Phase B+.3 — mc:AlternateContent expander', () => {
  function parseEl(xml: string): Element {
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.documentElement;
  }

  it('優先取 mc:Choice', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <mc:AlternateContent>
          <mc:Choice Requires="wps"><w:r><w:t>NEW</w:t></w:r></mc:Choice>
          <mc:Fallback><w:r><w:t>OLD</w:t></w:r></mc:Fallback>
        </mc:AlternateContent>
      </w:p>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].tagName).toBe('w:r');
    expect(children[0].textContent).toBe('NEW');
  });

  it('無 Choice 時降為 Fallback', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <mc:AlternateContent>
          <mc:Fallback><w:r><w:t>OLD</w:t></w:r></mc:Fallback>
        </mc:AlternateContent>
      </w:p>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].textContent).toBe('OLD');
  });

  it('Choice 與 Fallback 都無時跳過', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <mc:AlternateContent></mc:AlternateContent>
        <w:r><w:t>after</w:t></w:r>
      </w:p>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].tagName).toBe('w:r');
  });

  it('巢狀 AlternateContent 遞迴展開', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <mc:AlternateContent>
          <mc:Choice Requires="x">
            <mc:AlternateContent>
              <mc:Choice Requires="y"><w:r><w:t>inner</w:t></w:r></mc:Choice>
            </mc:AlternateContent>
          </mc:Choice>
        </mc:AlternateContent>
      </w:p>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].textContent).toBe('inner');
  });

  it('directChildren 不展開（保留原行為）', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <mc:AlternateContent>
          <mc:Choice><w:r><w:t>x</w:t></w:r></mc:Choice>
        </mc:AlternateContent>
      </w:p>`);
    const children = directChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].tagName).toBe('mc:AlternateContent');
  });

  it('段落內的 AlternateContent 經 ParagraphParser 後 run 直接出現', () => {
    const parser = new ParagraphParser();
    const p = parsePFragment(`
      <mc:AlternateContent>
        <mc:Choice Requires="wps"><w:r><w:t>選擇優先</w:t></w:r></mc:Choice>
        <mc:Fallback><w:r><w:t>備援</w:t></w:r></mc:Fallback>
      </mc:AlternateContent>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(1);
    if (node.runs[0].type === 'run') {
      expect(node.runs[0].text).toBe('選擇優先');
    }
  });
});

// ── 4. rFonts 4 屬性 ─────────────────────────────────────────────────────────

describe('Phase B+.4 — rFonts 4 屬性', () => {
  const parser = new ParagraphParser();

  it('ascii / eastAsia / hAnsi / cs 全部解析', () => {
    const p = parsePFragment(`
      <w:r>
        <w:rPr>
          <w:rFonts w:ascii="Times New Roman" w:eastAsia="細明體"
                    w:hAnsi="Calibri" w:cs="Arabic Typesetting"/>
        </w:rPr>
        <w:t>x</w:t>
      </w:r>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.props.fontFamily).toBe('Times New Roman');
    expect(r.props.fontFamilyEastAsia).toBe('細明體');
    expect(r.props.fontFamilyHAnsi).toBe('Calibri');
    expect(r.props.fontFamilyCs).toBe('Arabic Typesetting');
  });

  it('只給 ascii 時其他 3 個為 undefined', () => {
    const p = parsePFragment(`
      <w:r><w:rPr><w:rFonts w:ascii="Arial"/></w:rPr><w:t>x</w:t></w:r>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.props.fontFamily).toBe('Arial');
    expect(r.props.fontFamilyEastAsia).toBeUndefined();
    expect(r.props.fontFamilyHAnsi).toBeUndefined();
    expect(r.props.fontFamilyCs).toBeUndefined();
  });
});

// ── 5. <w:tblStylePr> 條件樣式收集 ──────────────────────────────────────────

describe('Phase B+.5 — w:tblStylePr 條件樣式收集', () => {
  const resolver = new StyleResolver();

  it('收集 firstRow / lastRow 兩個條件樣式', () => {
    const xml = parseStylesXml(`
      <w:style w:type="table" w:styleId="MyTable">
        <w:rPr><w:sz w:val="24"/></w:rPr>
        <w:tblStylePr w:type="firstRow">
          <w:rPr><w:b/></w:rPr>
          <w:pPr><w:jc w:val="center"/></w:pPr>
        </w:tblStylePr>
        <w:tblStylePr w:type="lastRow">
          <w:rPr><w:i/></w:rPr>
        </w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const t = map.get('MyTable');
    expect(t?.conditional).toBeDefined();
    expect(t?.conditional?.size).toBe(2);
    expect(t?.conditional?.get('firstRow')?.rProps?.bold).toBe(true);
    expect(t?.conditional?.get('firstRow')?.pProps?.alignment).toBe('center');
    expect(t?.conditional?.get('lastRow')?.rProps?.italic).toBe(true);
  });

  it('15 種 type 都能收（wholeTable 等）', () => {
    const xml = parseStylesXml(`
      <w:style w:type="table" w:styleId="T1">
        <w:tblStylePr w:type="wholeTable"><w:rPr><w:b/></w:rPr></w:tblStylePr>
        <w:tblStylePr w:type="band1Horz"><w:rPr><w:i/></w:rPr></w:tblStylePr>
        <w:tblStylePr w:type="nwCell"><w:rPr><w:strike/></w:rPr></w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    const t = map.get('T1');
    expect(t?.conditional?.has('wholeTable')).toBe(true);
    expect(t?.conditional?.has('band1Horz')).toBe(true);
    expect(t?.conditional?.has('nwCell')).toBe(true);
  });

  it('沒有 tblStylePr 時 conditional 為 undefined', () => {
    const xml = parseStylesXml(`
      <w:style w:type="paragraph" w:styleId="Body">
        <w:rPr><w:b/></w:rPr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    expect(map.get('Body')?.conditional).toBeUndefined();
  });

  it('條件樣式不參與 basedOn 繼承（原樣保留）', () => {
    // 子表格 style basedOn 父：條件樣式只屬於各自，不應 merge
    const xml = parseStylesXml(`
      <w:style w:type="table" w:styleId="Parent">
        <w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr>
      </w:style>
      <w:style w:type="table" w:styleId="Child">
        <w:basedOn w:val="Parent"/>
        <w:tblStylePr w:type="lastRow"><w:rPr><w:i/></w:rPr></w:tblStylePr>
      </w:style>
    `);
    const map = resolver.resolve(xml);
    // Parent 有 firstRow
    expect(map.get('Parent')?.conditional?.has('firstRow')).toBe(true);
    expect(map.get('Parent')?.conditional?.size).toBe(1);
    // Child 自己只有 lastRow（不從 Parent 繼承 firstRow）
    expect(map.get('Child')?.conditional?.has('lastRow')).toBe(true);
    expect(map.get('Child')?.conditional?.has('firstRow')).toBe(false);
    expect(map.get('Child')?.conditional?.size).toBe(1);
  });
});

// ── Sprint 124：w:sdt 結構化文件標籤透明展開 ────────────────────────────────────
describe('Sprint 124 — w:sdt unwrap in effectiveChildren', () => {
  function parseEl(xml: string): Element {
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.documentElement;
  }

  it('block-level w:sdt → 子段落 inline 到 body 層', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:p><w:r><w:t>before</w:t></w:r></w:p>
        <w:sdt>
          <w:sdtPr>
            <w:tag w:val="myTag"/>
            <w:alias w:val="My Field"/>
            <w:id w:val="123"/>
            <w:text/>
          </w:sdtPr>
          <w:sdtContent>
            <w:p><w:r><w:t>inside sdt</w:t></w:r></w:p>
          </w:sdtContent>
        </w:sdt>
        <w:p><w:r><w:t>after</w:t></w:r></w:p>
      </w:body>`);
    const children = effectiveChildren(root);
    // 預期 3 個 w:p（sdt 透明）；sdtPr 不出現在結果中
    expect(children).toHaveLength(3);
    expect(children.every((c) => c.tagName === 'w:p')).toBe(true);
    expect(children[0].textContent).toBe('before');
    expect(children[1].textContent).toBe('inside sdt');
    expect(children[2].textContent).toBe('after');
  });

  it('inline w:sdt → 子 run inline 到段落層', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:p ${NS}>
        <w:r><w:t>Hello </w:t></w:r>
        <w:sdt>
          <w:sdtPr><w:tag w:val="name"/></w:sdtPr>
          <w:sdtContent>
            <w:r><w:t>John</w:t></w:r>
          </w:sdtContent>
        </w:sdt>
        <w:r><w:t>!</w:t></w:r>
      </w:p>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(3);
    expect(children.every((c) => c.tagName === 'w:r')).toBe(true);
    expect(children[0].textContent).toBe('Hello ');
    expect(children[1].textContent).toBe('John');
    expect(children[2].textContent).toBe('!');
  });

  it('w:sdt 缺 sdtContent（malformed）→ 跳過、其他兄弟不受影響', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:p><w:r><w:t>keep</w:t></w:r></w:p>
        <w:sdt>
          <w:sdtPr><w:tag w:val="orphan"/></w:sdtPr>
        </w:sdt>
        <w:p><w:r><w:t>also keep</w:t></w:r></w:p>
      </w:body>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(2);
    expect(children.map((c) => c.textContent)).toEqual(['keep', 'also keep']);
  });

  it('嵌套 w:sdt 遞迴展開', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:sdt>
          <w:sdtPr><w:tag w:val="outer"/></w:sdtPr>
          <w:sdtContent>
            <w:sdt>
              <w:sdtPr><w:tag w:val="inner"/></w:sdtPr>
              <w:sdtContent>
                <w:p><w:r><w:t>nested</w:t></w:r></w:p>
              </w:sdtContent>
            </w:sdt>
          </w:sdtContent>
        </w:sdt>
      </w:body>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].tagName).toBe('w:p');
    expect(children[0].textContent).toBe('nested');
  });

  it('sdt 內含 AlternateContent → 兩層展開都正常', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:sdt>
          <w:sdtPr><w:tag w:val="x"/></w:sdtPr>
          <w:sdtContent>
            <mc:AlternateContent>
              <mc:Choice Requires="wps"><w:p><w:r><w:t>NEW</w:t></w:r></w:p></mc:Choice>
              <mc:Fallback><w:p><w:r><w:t>OLD</w:t></w:r></w:p></mc:Fallback>
            </mc:AlternateContent>
          </w:sdtContent>
        </w:sdt>
      </w:body>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].tagName).toBe('w:p');
    expect(children[0].textContent).toBe('NEW');
  });

  it('sdt 多個段落內容全部 inline', () => {
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:sdt>
          <w:sdtPr><w:tag w:val="multi"/></w:sdtPr>
          <w:sdtContent>
            <w:p><w:r><w:t>p1</w:t></w:r></w:p>
            <w:p><w:r><w:t>p2</w:t></w:r></w:p>
            <w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>
          </w:sdtContent>
        </w:sdt>
      </w:body>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(3);
    expect(children[0].tagName).toBe('w:p');
    expect(children[1].tagName).toBe('w:p');
    expect(children[2].tagName).toBe('w:tbl');
  });

  it('sdt 內含 sdtEndPr 不影響 sdtContent 展開', () => {
    // ECMA-376 允許 sdt 有 optional sdtEndPr 在 sdtContent 之後；我們只看 sdtContent
    const root = parseEl(`<?xml version="1.0"?>
      <w:body ${NS}>
        <w:sdt>
          <w:sdtPr><w:tag w:val="x"/></w:sdtPr>
          <w:sdtEndPr/>
          <w:sdtContent>
            <w:p><w:r><w:t>kept</w:t></w:r></w:p>
          </w:sdtContent>
        </w:sdt>
      </w:body>`);
    const children = effectiveChildren(root);
    expect(children).toHaveLength(1);
    expect(children[0].textContent).toBe('kept');
  });
});

// ── Sprint 124 整合：ParagraphParser 對 inline sdt 透明 ─────────────────────────
describe('Sprint 124 — ParagraphParser SDT 整合', () => {
  function parsePXml(innerPXml: string): Element {
    const xml = `<?xml version="1.0"?><w:p ${W_NS}>${innerPXml}</w:p>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.documentElement;
  }
  const parser = new ParagraphParser();

  it('inline sdt 內含 w:r → run 出現在段落 runs 中', () => {
    const p = parsePXml(`
      <w:r><w:t>前綴</w:t></w:r>
      <w:sdt>
        <w:sdtPr><w:tag w:val="customer"/></w:sdtPr>
        <w:sdtContent>
          <w:r><w:t>客戶名稱</w:t></w:r>
        </w:sdtContent>
      </w:sdt>
      <w:r><w:t>後綴</w:t></w:r>
    `);
    const node = parser.parse(p);
    expect(node.runs).toHaveLength(3);
    expect(node.runs[0]).toMatchObject({ type: 'run', text: '前綴' });
    expect(node.runs[1]).toMatchObject({ type: 'run', text: '客戶名稱' });
    expect(node.runs[2]).toMatchObject({ type: 'run', text: '後綴' });
  });
});

// ── Sprint 126：hyperlink rels 完整覆蓋（tgtFrame / history / docLocation）─────
describe('Sprint 126 — w:hyperlink rels 完整覆蓋', () => {
  const parser = new ParagraphParser();

  it('w:tgtFrame=_blank → HyperlinkInfo.tgtFrame=_blank', () => {
    parser.setRelsLookup(() => 'https://example.com');
    const p = parsePFragment(`
      <w:hyperlink r:id="rId1" w:tgtFrame="_blank">
        <w:r><w:t>新分頁</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.tgtFrame).toBe('_blank');
    expect(r.hyperlink?.url).toBe('https://example.com');
  });

  it('w:history="1" → history=true', () => {
    const p = parsePFragment(`
      <w:hyperlink w:anchor="bm" w:history="1">
        <w:r><w:t>x</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.history).toBe(true);
    expect(r.hyperlink?.anchor).toBe('bm');
  });

  it('w:history="0" → history=false（顯式禁止計入歷史）', () => {
    const p = parsePFragment(`
      <w:hyperlink w:anchor="bm" w:history="0">
        <w:r><w:t>x</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.history).toBe(false);
  });

  it('w:history="true" / "false" 兩種布林字串同樣解析', () => {
    const pTrue = parsePFragment(`
      <w:hyperlink w:anchor="a" w:history="true">
        <w:r><w:t>t</w:t></w:r>
      </w:hyperlink>
    `);
    const pFalse = parsePFragment(`
      <w:hyperlink w:anchor="b" w:history="false">
        <w:r><w:t>f</w:t></w:r>
      </w:hyperlink>
    `);
    const tNode = parser.parse(pTrue);
    const fNode = parser.parse(pFalse);
    const tRun = tNode.runs[0];
    const fRun = fNode.runs[0];
    if (tRun.type !== 'run' || fRun.type !== 'run') throw new Error('expected runs');
    expect(tRun.hyperlink?.history).toBe(true);
    expect(fRun.hyperlink?.history).toBe(false);
  });

  it('w:history 缺 → history 不在 info 內（紀律 #21 候選）', () => {
    parser.setRelsLookup(() => 'https://example.com');
    const p = parsePFragment(`
      <w:hyperlink r:id="rIdH">
        <w:r><w:t>x</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink).toBeDefined();
    expect(r.hyperlink?.history).toBeUndefined();
  });

  it('w:docLocation 跨文件位置', () => {
    parser.setRelsLookup((rId) => rId === 'rIdDL' ? 'other.docx' : undefined);
    const p = parsePFragment(`
      <w:hyperlink r:id="rIdDL" w:docLocation="Section3">
        <w:r><w:t>跳到他文件</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.docLocation).toBe('Section3');
    expect(r.hyperlink?.url).toBe('other.docx');
  });

  it('External + anchor 共存（跨文件指定位置）', () => {
    parser.setRelsLookup(() => 'https://docs.example.com/spec.html');
    const p = parsePFragment(`
      <w:hyperlink r:id="rId99" w:anchor="section3" w:tooltip="see §3">
        <w:r><w:t>See section 3</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.url).toBe('https://docs.example.com/spec.html');
    expect(r.hyperlink?.anchor).toBe('section3');
    expect(r.hyperlink?.tooltip).toBe('see §3');
  });

  it('五屬性全帶 → 全部出現在 HyperlinkInfo', () => {
    parser.setRelsLookup(() => 'https://full.example.com');
    const p = parsePFragment(`
      <w:hyperlink r:id="rIdAll" w:anchor="top" w:tooltip="hint" w:tgtFrame="_self" w:history="1" w:docLocation="loc1">
        <w:r><w:t>all</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink).toMatchObject({
      rId: 'rIdAll',
      url: 'https://full.example.com',
      anchor: 'top',
      tooltip: 'hint',
      tgtFrame: '_self',
      history: true,
      docLocation: 'loc1',
    });
  });

  it('rId 存在但 lookup 沒命中 → url undefined、rId 仍保留供下游診斷', () => {
    parser.setRelsLookup(() => undefined);
    const p = parsePFragment(`
      <w:hyperlink r:id="rIdBroken" w:tooltip="壞掉的 rels">
        <w:r><w:t>broken</w:t></w:r>
      </w:hyperlink>
    `);
    const node = parser.parse(p);
    const r = node.runs[0];
    if (r.type !== 'run') throw new Error('expected run');
    expect(r.hyperlink?.rId).toBe('rIdBroken');
    expect(r.hyperlink?.url).toBeUndefined();
    expect(r.hyperlink?.tooltip).toBe('壞掉的 rels');
  });

  it('完全空的 w:hyperlink（無屬性、無 run）→ 該段落 runs 空、hyperlink 為 undefined', () => {
    const p = parsePFragment(`<w:hyperlink></w:hyperlink>`);
    const node = parser.parse(p);
    expect(node.runs).toEqual([]);
  });
});
