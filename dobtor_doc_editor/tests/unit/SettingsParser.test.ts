/**
 * SettingsParser.test.ts — Sprint 146 (Phase 1 capture-only)
 *
 * 涵蓋:
 *   - 真實 fixture (送審管制.docx) 結構解析
 *   - 各高覆蓋元素獨立 test:zoom / defaultTabStop / characterSpacingControl /
 *     footnotePr / endnotePr / compat / proofState / toggle elements
 *   - twip → pt 轉換正確性
 *   - 列舉值驗證 + 未知值降級
 *   - 防禦邊界:undefined / 空 / XML 解析失敗
 */

import { describe, expect, it } from 'vitest';
import { SettingsParser } from '../../static/src/core/ooxml/settings/SettingsParser';

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function wrap(inner: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<w:settings ${NS}>${inner}</w:settings>`;
}

// ── zoom / defaultTabStop / characterSpacingControl 基本欄位 ─────────────────

describe('SettingsParser — 基本欄位', () => {
  it('w:zoom w:percent="100" → zoomPercent = 100', () => {
    const r = new SettingsParser().parse(wrap('<w:zoom w:percent="100"/>'));
    expect(r.zoomPercent).toBe(100);
  });

  it('w:zoom w:percent="200" → zoomPercent = 200', () => {
    const r = new SettingsParser().parse(wrap('<w:zoom w:percent="200"/>'));
    expect(r.zoomPercent).toBe(200);
  });

  it('w:defaultTabStop w:val="720" → 720 twip = 36 pt', () => {
    const r = new SettingsParser().parse(wrap('<w:defaultTabStop w:val="720"/>'));
    expect(r.defaultTabStop).toBeCloseTo(36, 4);
  });

  it('w:characterSpacingControl="compressPunctuation" 合法列舉', () => {
    const r = new SettingsParser().parse(
      wrap('<w:characterSpacingControl w:val="compressPunctuation"/>'),
    );
    expect(r.characterSpacingControl).toBe('compressPunctuation');
  });

  it('w:characterSpacingControl 未知值 → 降級為 undefined', () => {
    const r = new SettingsParser().parse(
      wrap('<w:characterSpacingControl w:val="unknownPolicy"/>'),
    );
    expect(r.characterSpacingControl).toBeUndefined();
  });
});

// ── toggle 元素 (autoHyphenation / evenAndOddHeaders / trackChanges) ────────

describe('SettingsParser — toggle 元素', () => {
  it('w:autoHyphenation (no val) → true', () => {
    const r = new SettingsParser().parse(wrap('<w:autoHyphenation/>'));
    expect(r.autoHyphenation).toBe(true);
  });

  it('w:autoHyphenation w:val="1" → true', () => {
    const r = new SettingsParser().parse(wrap('<w:autoHyphenation w:val="1"/>'));
    expect(r.autoHyphenation).toBe(true);
  });

  it('w:autoHyphenation w:val="0" → false', () => {
    const r = new SettingsParser().parse(wrap('<w:autoHyphenation w:val="0"/>'));
    expect(r.autoHyphenation).toBe(false);
  });

  it('w:trackChanges w:val="false" → false', () => {
    const r = new SettingsParser().parse(wrap('<w:trackChanges w:val="false"/>'));
    expect(r.trackChanges).toBe(false);
  });

  it('w:evenAndOddHeaders 不存在 → undefined (紀律 #21)', () => {
    const r = new SettingsParser().parse(wrap('<w:zoom w:percent="100"/>'));
    expect(r.evenAndOddHeaders).toBeUndefined();
  });
});

// ── proofState ──────────────────────────────────────────────────────────────

describe('SettingsParser — proofState', () => {
  it('spelling="clean" grammar="clean" 兩者皆 capture', () => {
    const r = new SettingsParser().parse(
      wrap('<w:proofState w:spelling="clean" w:grammar="clean"/>'),
    );
    expect(r.proofState).toEqual({ spelling: 'clean', grammar: 'clean' });
  });

  it('只有 spelling 屬性 → grammar undefined (紀律 #21)', () => {
    const r = new SettingsParser().parse(wrap('<w:proofState w:spelling="dirty"/>'));
    expect(r.proofState).toEqual({ spelling: 'dirty' });
  });

  it('兩屬性都未設 → proofState 不掛 key (紀律 #21 空集合)', () => {
    const r = new SettingsParser().parse(wrap('<w:proofState/>'));
    expect(r.proofState).toBeUndefined();
  });
});

// ── footnotePr / endnotePr ──────────────────────────────────────────────────

describe('SettingsParser — footnotePr / endnotePr', () => {
  it('footnotePr 完整解析 (numRestart + numFmt + pos + numStart)', () => {
    const r = new SettingsParser().parse(
      wrap(
        '<w:footnotePr>' +
          '<w:numRestart w:val="eachPage"/>' +
          '<w:numFmt w:val="lowerRoman"/>' +
          '<w:pos w:val="pageBottom"/>' +
          '<w:numStart w:val="5"/>' +
          '</w:footnotePr>',
      ),
    );
    expect(r.footnotePr).toEqual({
      numRestart: 'eachPage',
      numFmt: 'lowerRoman',
      position: 'pageBottom',
      numStart: 5,
    });
  });

  it('endnotePr 只接受合法 position (sectEnd / docEnd)', () => {
    const r = new SettingsParser().parse(
      wrap('<w:endnotePr><w:pos w:val="docEnd"/></w:endnotePr>'),
    );
    expect(r.endnotePr?.position).toBe('docEnd');
  });

  it('endnotePr 不接受 footnote-only 的 pageBottom (合法性檢查)', () => {
    const r = new SettingsParser().parse(
      wrap('<w:endnotePr><w:pos w:val="pageBottom"/></w:endnotePr>'),
    );
    expect(r.endnotePr?.position).toBeUndefined();
  });

  it('footnotePr 真實 fixture 結構 (numRestart=eachPage + 2 個 footnote stub)', () => {
    // 對應 03_complex_table/送審管制.docx 真實 footnotePr
    const r = new SettingsParser().parse(
      wrap(
        '<w:footnotePr>' +
          '<w:numRestart w:val="eachPage"/>' +
          '<w:footnote w:id="-1"/>' +  // stub 引用、本 sprint 不解析
          '<w:footnote w:id="0"/>' +
          '</w:footnotePr>',
      ),
    );
    expect(r.footnotePr?.numRestart).toBe('eachPage');
  });
});

// ── compat ──────────────────────────────────────────────────────────────────

describe('SettingsParser — compat', () => {
  it('compat 子元素名稱列表', () => {
    const r = new SettingsParser().parse(
      wrap(
        '<w:compat>' +
          '<w:spaceForUL/>' +
          '<w:balanceSingleByteDoubleByteWidth/>' +
          '<w:doNotLeaveBackslashAlone/>' +
          '</w:compat>',
      ),
    );
    expect(r.compat).toEqual([
      'spaceForUL',
      'balanceSingleByteDoubleByteWidth',
      'doNotLeaveBackslashAlone',
    ]);
  });

  it('compat 空 → 不掛 key (紀律 #21)', () => {
    const r = new SettingsParser().parse(wrap('<w:compat/>'));
    expect(r.compat).toBeUndefined();
  });
});

// ── 防禦邊界 ────────────────────────────────────────────────────────────────

describe('SettingsParser — 防禦邊界', () => {
  it('undefined → 回 {}', () => {
    expect(new SettingsParser().parse(undefined)).toEqual({});
  });

  it('空字串 → 回 {}', () => {
    expect(new SettingsParser().parse('')).toEqual({});
  });

  it('壞 XML → 回 {} (不 throw)', () => {
    expect(new SettingsParser().parse('<w:settings><not closed>')).toEqual({});
  });

  it('完全空的 w:settings (Word 預設骨架) → 回 {}', () => {
    expect(new SettingsParser().parse(wrap(''))).toEqual({});
  });

  it('w:zoom 缺 percent 屬性 → 不掛 zoomPercent', () => {
    const r = new SettingsParser().parse(wrap('<w:zoom/>'));
    expect(r.zoomPercent).toBeUndefined();
  });

  it('w:zoom percent="0" → 不掛 zoomPercent (>0 才合法)', () => {
    const r = new SettingsParser().parse(wrap('<w:zoom w:percent="0"/>'));
    expect(r.zoomPercent).toBeUndefined();
  });

  it('w:defaultTabStop 非數字 → 不掛 defaultTabStop', () => {
    const r = new SettingsParser().parse(wrap('<w:defaultTabStop w:val="abc"/>'));
    expect(r.defaultTabStop).toBeUndefined();
  });
});

// ── 整合 (真實 fixture 樣本) ─────────────────────────────────────────────────

describe('SettingsParser — 真實 fixture 整合', () => {
  it('組合 6 個常見元素一起解析', () => {
    const xml = wrap(
      '<w:zoom w:percent="100"/>' +
        '<w:embedSystemFonts/>' +  // 未支援 element、跳過
        '<w:proofState w:spelling="clean" w:grammar="clean"/>' +
        '<w:defaultTabStop w:val="720"/>' +
        '<w:characterSpacingControl w:val="compressPunctuation"/>' +
        '<w:footnotePr><w:numRestart w:val="eachPage"/></w:footnotePr>' +
        '<w:endnotePr><w:numFmt w:val="lowerRoman"/></w:endnotePr>' +
        '<w:compat><w:spaceForUL/></w:compat>',
    );
    const r = new SettingsParser().parse(xml);
    expect(r.zoomPercent).toBe(100);
    expect(r.proofState).toEqual({ spelling: 'clean', grammar: 'clean' });
    expect(r.defaultTabStop).toBeCloseTo(36, 4);
    expect(r.characterSpacingControl).toBe('compressPunctuation');
    expect(r.footnotePr?.numRestart).toBe('eachPage');
    expect(r.endnotePr?.numFmt).toBe('lowerRoman');
    expect(r.compat).toEqual(['spaceForUL']);
  });
});
