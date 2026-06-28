/**
 * Sprint 57 — BrowserCanvasRenderContext string memoization 單元測試
 *
 * Sprint 57 初版嘗試「拿掉 save/restore + setState dedup」於 VR 翻車（mean 0.0749 → 0.0998），
 * 退到「只 memoize toCssColor / toCssFont 字串輸出」的最小安全版。本檔測：
 *   1. memoize 不影響輸出（相同輸入回相同字串）
 *   2. 不同輸入回不同字串（key 區分正確）
 *   3. 預設值處理（empty color → '#000000'、no fontFamily → 'sans-serif'）
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  toCssColor,
  toCssFont,
  _clearRenderCachesForTest,
} from '../../static/src/core/render/BrowserCanvasRenderContext';

beforeEach(() => {
  _clearRenderCachesForTest();
});

describe('Sprint 57 — toCssColor memoization', () => {
  it('6 位 hex (無 #) → #RRGGBB', () => {
    expect(toCssColor('FF0000')).toBe('#FF0000');
    expect(toCssColor('000000')).toBe('#000000');
  });

  it('已含 # → 直接通過', () => {
    expect(toCssColor('#FF0000')).toBe('#FF0000');
    expect(toCssColor('#abc')).toBe('#abc');
  });

  it('3 位 short form → 展開 6 位', () => {
    expect(toCssColor('abc')).toBe('#aabbcc');
    expect(toCssColor('123')).toBe('#112233');
  });

  it('空字串 / undefined → #000000 預設', () => {
    expect(toCssColor('')).toBe('#000000');
  });

  it('相同輸入回同一個字串（memoize 後）', () => {
    const a = toCssColor('FF0000');
    const b = toCssColor('FF0000');
    expect(a).toBe(b);
  });

  it('不同輸入回不同字串', () => {
    expect(toCssColor('FF0000')).not.toBe(toCssColor('00FF00'));
  });
});

describe('Sprint 57 — toCssFont memoization', () => {
  it('基本字級 + family', () => {
    const css = toCssFont({ fontSize: 12, fontFamily: 'Arial' }, 1);
    expect(css).toBe('12.00px Arial');
  });

  it('bold + italic 加 prefix', () => {
    const css = toCssFont({ fontSize: 12, fontFamily: 'Arial', bold: true, italic: true }, 1);
    expect(css).toBe('italic bold 12.00px Arial');
  });

  it('含空白 family 雙引號包', () => {
    const css = toCssFont({ fontSize: 12, fontFamily: 'Times New Roman' }, 1);
    expect(css).toBe('12.00px "Times New Roman"');
  });

  it('無 family → sans-serif', () => {
    const css = toCssFont({ fontSize: 12 }, 1);
    expect(css).toBe('12.00px sans-serif');
  });

  it('scale 改變字級', () => {
    const a = toCssFont({ fontSize: 12, fontFamily: 'Arial' }, 1);
    const b = toCssFont({ fontSize: 12, fontFamily: 'Arial' }, 2);
    expect(a).toContain('12.00px');
    expect(b).toContain('24.00px');
  });

  it('相同 style 回同一個字串（memoize 後）', () => {
    const style = { fontSize: 12, fontFamily: 'Arial', bold: true };
    expect(toCssFont(style, 1)).toBe(toCssFont(style, 1));
  });

  it('不同 bold / italic / fontSize / family / scale → key 不同 → 不同字串', () => {
    const base = { fontSize: 12, fontFamily: 'Arial' };
    const plain = toCssFont(base, 1);
    const bold = toCssFont({ ...base, bold: true }, 1);
    const italic = toCssFont({ ...base, italic: true }, 1);
    const bigger = toCssFont({ ...base, fontSize: 14 }, 1);
    const otherFamily = toCssFont({ ...base, fontFamily: 'Helvetica' }, 1);
    const otherScale = toCssFont(base, 2);
    expect(new Set([plain, bold, italic, bigger, otherFamily, otherScale]).size).toBe(6);
  });
});
