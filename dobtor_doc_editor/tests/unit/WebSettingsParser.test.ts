/**
 * WebSettingsParser.test.ts — Sprint 148 (Phase 1 capture-only、結束 part 三連 cluster)
 *
 * 涵蓋:
 *   - 4 toggle 元素獨立 test
 *   - hasDivs 判定(空 / 含子元素)
 *   - 防禦邊界
 */

import { describe, expect, it } from 'vitest';
import { WebSettingsParser } from '../../static/src/core/ooxml/web-settings/WebSettingsParser';

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:webSettings ${NS}>${inner}</w:webSettings>`;
}

describe('WebSettingsParser — toggle 元素', () => {
  it('w:optimizeForBrowser → true', () => {
    const r = new WebSettingsParser().parse(wrap('<w:optimizeForBrowser/>'));
    expect(r.optimizeForBrowser).toBe(true);
  });

  it('w:allowPNG → true', () => {
    const r = new WebSettingsParser().parse(wrap('<w:allowPNG/>'));
    expect(r.allowPNG).toBe(true);
  });

  it('w:allowPNG w:val="0" → false', () => {
    const r = new WebSettingsParser().parse(wrap('<w:allowPNG w:val="0"/>'));
    expect(r.allowPNG).toBe(false);
  });

  it('w:saveSmartTagsAsXml → true', () => {
    const r = new WebSettingsParser().parse(wrap('<w:saveSmartTagsAsXml/>'));
    expect(r.saveSmartTagsAsXml).toBe(true);
  });

  it('w:doNotSaveAsSingleFile → true', () => {
    const r = new WebSettingsParser().parse(wrap('<w:doNotSaveAsSingleFile/>'));
    expect(r.doNotSaveAsSingleFile).toBe(true);
  });

  it('不存在的 toggle → undefined (紀律 #21)', () => {
    const r = new WebSettingsParser().parse(wrap(''));
    expect(r.optimizeForBrowser).toBeUndefined();
    expect(r.allowPNG).toBeUndefined();
    expect(r.saveSmartTagsAsXml).toBeUndefined();
    expect(r.doNotSaveAsSingleFile).toBeUndefined();
  });
});

describe('WebSettingsParser — hasDivs', () => {
  it('w:divs 含子元素 → hasDivs = true', () => {
    const r = new WebSettingsParser().parse(
      wrap('<w:divs><w:div w:id="123"/></w:divs>'),
    );
    expect(r.hasDivs).toBe(true);
  });

  it('w:divs 空(無子元素) → 不掛 hasDivs', () => {
    const r = new WebSettingsParser().parse(wrap('<w:divs/>'));
    expect(r.hasDivs).toBeUndefined();
  });

  it('無 w:divs → 不掛 hasDivs', () => {
    const r = new WebSettingsParser().parse(wrap('<w:allowPNG/>'));
    expect(r.hasDivs).toBeUndefined();
  });
});

describe('WebSettingsParser — 真實 fixture 樣本', () => {
  it('組合 allowPNG + optimizeForBrowser + divs', () => {
    const xml = wrap(
      '<w:optimizeForBrowser/>' +
        '<w:allowPNG/>' +
        '<w:divs><w:div w:id="123"><w:bodyDiv w:val="1"/></w:div></w:divs>',
    );
    const r = new WebSettingsParser().parse(xml);
    expect(r.optimizeForBrowser).toBe(true);
    expect(r.allowPNG).toBe(true);
    expect(r.hasDivs).toBe(true);
  });
});

describe('WebSettingsParser — 防禦邊界', () => {
  it('undefined → {}', () => {
    expect(new WebSettingsParser().parse(undefined)).toEqual({});
  });

  it('空字串 → {}', () => {
    expect(new WebSettingsParser().parse('')).toEqual({});
  });

  it('壞 XML → {} (不 throw)', () => {
    expect(new WebSettingsParser().parse('<w:webSettings><not closed>')).toEqual({});
  });

  it('完全空的 w:webSettings (Word 預設骨架) → {}', () => {
    expect(new WebSettingsParser().parse(wrap(''))).toEqual({});
  });
});
