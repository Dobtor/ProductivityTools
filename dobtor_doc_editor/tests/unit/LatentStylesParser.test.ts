/**
 * LatentStylesParser.test.ts — Sprint 153 (Phase 1 capture-only、styles.xml `<w:latentStyles>`)
 *
 * 涵蓋:
 *   - root 級 defaults(5 toggles/integer + count)
 *   - lsdException 各屬性(name / locked / uiPriority / semiHidden / unhideWhenUsed / qFormat)
 *   - 真實 fixture 樣本(Word 預設 latentStyles 骨架)
 *   - 防禦邊界
 */

import { describe, expect, it } from 'vitest';
import { LatentStylesParser } from '../../static/src/core/ooxml/styles/LatentStylesParser';

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrapStyles(latentInner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:styles ${NS}><w:latentStyles ${latentInner}></w:latentStyles></w:styles>`;
}

function wrapStylesWithChildren(rootAttrs: string, children: string): string {
  return `<?xml version="1.0"?>\n<w:styles ${NS}><w:latentStyles ${rootAttrs}>${children}</w:latentStyles></w:styles>`;
}

describe('LatentStylesParser — root defaults', () => {
  it('全 6 個 default 屬性(5 toggle + count)', () => {
    const r = new LatentStylesParser().parse(
      wrapStyles(
        'w:defLockedState="0" w:defUIPriority="99" w:defSemiHidden="1" ' +
          'w:defUnhideWhenUsed="1" w:defQFormat="0" w:count="267"',
      ),
    );
    expect(r.defLockedState).toBe(false);
    expect(r.defUIPriority).toBe(99);
    expect(r.defSemiHidden).toBe(true);
    expect(r.defUnhideWhenUsed).toBe(true);
    expect(r.defQFormat).toBe(false);
    expect(r.count).toBe(267);
  });

  it('部分屬性缺失 → 只掛存在的 key (紀律 #21)', () => {
    const r = new LatentStylesParser().parse(wrapStyles('w:count="100"'));
    expect(r.count).toBe(100);
    expect(r.defLockedState).toBeUndefined();
    expect(r.defUIPriority).toBeUndefined();
  });

  it('toggle 屬性接受 "1" / "true" / 空字串為 true、"0" / "false" 為 false', () => {
    expect(new LatentStylesParser().parse(wrapStyles('w:defQFormat="1"')).defQFormat).toBe(
      true,
    );
    expect(new LatentStylesParser().parse(wrapStyles('w:defQFormat="true"')).defQFormat).toBe(
      true,
    );
    expect(new LatentStylesParser().parse(wrapStyles('w:defQFormat="0"')).defQFormat).toBe(
      false,
    );
    expect(new LatentStylesParser().parse(wrapStyles('w:defQFormat="false"')).defQFormat).toBe(
      false,
    );
  });

  it('count 不是整數 → undefined (紀律 #21)', () => {
    const r = new LatentStylesParser().parse(wrapStyles('w:count="abc"'));
    expect(r.count).toBeUndefined();
  });
});

describe('LatentStylesParser — lsdException', () => {
  it('單一 exception 完整 5 屬性', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren(
        '',
        '<w:lsdException w:name="Normal" w:locked="0" w:uiPriority="0" w:semiHidden="0" w:unhideWhenUsed="0" w:qFormat="1"/>',
      ),
    );
    expect(r.exceptions).toBeDefined();
    expect(r.exceptions!.size).toBe(1);
    const ex = r.exceptions!.get('Normal');
    expect(ex).toEqual({
      locked: false,
      uiPriority: 0,
      semiHidden: false,
      unhideWhenUsed: false,
      qFormat: true,
    });
  });

  it('部分屬性 exception(紀律 #21、缺失屬性 undefined)', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren(
        '',
        '<w:lsdException w:name="heading 2" w:uiPriority="9" w:qFormat="1"/>',
      ),
    );
    expect(r.exceptions!.get('heading 2')).toEqual({ uiPriority: 9, qFormat: true });
  });

  it('多個 exception 用 name 作 key', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren(
        '',
        '<w:lsdException w:name="Normal" w:qFormat="1"/>' +
          '<w:lsdException w:name="heading 1" w:uiPriority="9"/>' +
          '<w:lsdException w:name="Title" w:uiPriority="10" w:qFormat="1"/>',
      ),
    );
    expect(r.exceptions!.size).toBe(3);
    expect(r.exceptions!.get('Normal')!.qFormat).toBe(true);
    expect(r.exceptions!.get('heading 1')!.uiPriority).toBe(9);
    expect(r.exceptions!.get('Title')!.uiPriority).toBe(10);
  });

  it('全空屬性的 exception 仍掛 key(name 本身已是資訊)', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren('', '<w:lsdException w:name="Index 1"/>'),
    );
    expect(r.exceptions!.has('Index 1')).toBe(true);
    expect(r.exceptions!.get('Index 1')).toEqual({});
  });

  it('無 name 屬性的 exception → 跳過 (紀律 #21)', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren('', '<w:lsdException w:qFormat="1"/>'),
    );
    expect(r.exceptions).toBeUndefined();
  });

  it('重複 name → 後者覆蓋前者', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren(
        '',
        '<w:lsdException w:name="X" w:uiPriority="5"/>' +
          '<w:lsdException w:name="X" w:uiPriority="9"/>',
      ),
    );
    expect(r.exceptions!.size).toBe(1);
    expect(r.exceptions!.get('X')!.uiPriority).toBe(9);
  });

  it('exception 大量(147 個、模擬 Word 預設骨架)', () => {
    const names = Array.from({ length: 147 }, (_, i) => `LatentStyle${i}`);
    const inner = names
      .map(n => `<w:lsdException w:name="${n}" w:uiPriority="${1}"/>`)
      .join('');
    const r = new LatentStylesParser().parse(wrapStylesWithChildren('', inner));
    expect(r.exceptions!.size).toBe(147);
    expect(r.exceptions!.get('LatentStyle0')!.uiPriority).toBe(1);
    expect(r.exceptions!.get('LatentStyle146')!.uiPriority).toBe(1);
  });
});

describe('LatentStylesParser — 真實 fixture 樣本', () => {
  it('Word 14 預設 latentStyles 骨架(defaults + 3 exceptions)', () => {
    const r = new LatentStylesParser().parse(
      wrapStylesWithChildren(
        'w:defLockedState="0" w:defUIPriority="99" w:defSemiHidden="1" w:defUnhideWhenUsed="1" w:defQFormat="0" w:count="267"',
        '<w:lsdException w:name="Normal" w:semiHidden="0" w:uiPriority="0" w:unhideWhenUsed="0" w:qFormat="1"/>' +
          '<w:lsdException w:name="heading 1" w:semiHidden="0" w:uiPriority="9" w:unhideWhenUsed="0" w:qFormat="1"/>' +
          '<w:lsdException w:name="heading 2" w:uiPriority="9" w:qFormat="1"/>',
      ),
    );
    expect(r.count).toBe(267);
    expect(r.defSemiHidden).toBe(true);
    expect(r.exceptions!.size).toBe(3);
    expect(r.exceptions!.get('Normal')!.qFormat).toBe(true);
    expect(r.exceptions!.get('Normal')!.semiHidden).toBe(false);
  });
});

describe('LatentStylesParser — 防禦邊界', () => {
  it('undefined → {}', () => {
    expect(new LatentStylesParser().parse(undefined)).toEqual({});
  });

  it('空字串 → {}', () => {
    expect(new LatentStylesParser().parse('')).toEqual({});
  });

  it('只有空白 → {}', () => {
    expect(new LatentStylesParser().parse('   \n  ')).toEqual({});
  });

  it('壞 XML → {} (不 throw)', () => {
    expect(new LatentStylesParser().parse('<w:styles><not closed>')).toEqual({});
  });

  it('styles.xml 無 latentStyles 元素 → {}', () => {
    const xml = `<?xml version="1.0"?>\n<w:styles ${NS}><w:style w:type="paragraph" w:styleId="Normal"/></w:styles>`;
    expect(new LatentStylesParser().parse(xml)).toEqual({});
  });

  it('完全空的 latentStyles 骨架(無屬性、無子元素)→ {}', () => {
    expect(new LatentStylesParser().parse(wrapStylesWithChildren('', ''))).toEqual({});
  });

  it('latentStyles 只有 defaults、無 exceptions → exceptions undefined', () => {
    const r = new LatentStylesParser().parse(wrapStyles('w:count="100"'));
    expect(r.count).toBe(100);
    expect(r.exceptions).toBeUndefined();
  });
});
