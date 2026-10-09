/**
 * numberingFormatter.test.ts — Phase 4.3（Sprint 132）
 *
 * 涵蓋：
 *   - 西式：decimal / decimalZero / lowerLetter / upperLetter /
 *           lowerRoman / upperRoman / ordinal / ordinalText / cardinalText
 *   - 中文：chineseCounting / chineseLegalSimplified / ideographDigital /
 *           taiwaneseCounting / japaneseCounting / japaneseLegal /
 *           japaneseDigitalTenThousand
 *   - 循環：ideographZodiac (12) / ideographTraditional (10) / iroha (47) / aiueo (46)
 *   - 邊界：none / bullet → ""、未知 numFmt → fallback decimal、
 *           0 / 負數 / Infinity / NaN 防禦
 *   - expandLvlText：「%1.%2.」展開、缺對應 counter / numFmt、
 *           特殊字串（如「第%1章」）
 */

import { describe, expect, it } from 'vitest';
import {
  formatNumber,
  expandLvlText,
} from '../../static/src/core/ooxml/numbering/numberingFormatter';

// ── 西式 ────────────────────────────────────────────────────────────────────

describe('numberingFormatter — decimal / decimalZero', () => {
  it('decimal 直接回字串', () => {
    expect(formatNumber(1, 'decimal')).toBe('1');
    expect(formatNumber(42, 'decimal')).toBe('42');
    expect(formatNumber(2024, 'decimal')).toBe('2024');
  });

  it('decimalZero 個位數補 0、兩位以上不補', () => {
    expect(formatNumber(0, 'decimalZero')).toBe('00');
    expect(formatNumber(1, 'decimalZero')).toBe('01');
    expect(formatNumber(9, 'decimalZero')).toBe('09');
    expect(formatNumber(10, 'decimalZero')).toBe('10');
    expect(formatNumber(99, 'decimalZero')).toBe('99');
    expect(formatNumber(100, 'decimalZero')).toBe('100');
  });
});

describe('numberingFormatter — lowerLetter / upperLetter', () => {
  it('base-26：1=a, 26=z, 27=aa, 52=az, 53=ba', () => {
    expect(formatNumber(1, 'lowerLetter')).toBe('a');
    expect(formatNumber(2, 'lowerLetter')).toBe('b');
    expect(formatNumber(26, 'lowerLetter')).toBe('z');
    expect(formatNumber(27, 'lowerLetter')).toBe('aa');
    expect(formatNumber(28, 'lowerLetter')).toBe('ab');
    expect(formatNumber(52, 'lowerLetter')).toBe('az');
    expect(formatNumber(53, 'lowerLetter')).toBe('ba');
    expect(formatNumber(703, 'lowerLetter')).toBe('aaa'); // 26*27 + 1
  });

  it('upperLetter 對應大寫', () => {
    expect(formatNumber(1, 'upperLetter')).toBe('A');
    expect(formatNumber(26, 'upperLetter')).toBe('Z');
    expect(formatNumber(27, 'upperLetter')).toBe('AA');
    expect(formatNumber(53, 'upperLetter')).toBe('BA');
  });

  it('0 / 負數防禦回 "a" / "A"', () => {
    expect(formatNumber(0, 'lowerLetter')).toBe('a');
    expect(formatNumber(-5, 'upperLetter')).toBe('A');
  });
});

describe('numberingFormatter — lowerRoman / upperRoman', () => {
  it('基本：1, 4, 5, 9, 10, 40, 50, 90, 100, 400, 500, 900, 1000', () => {
    expect(formatNumber(1, 'upperRoman')).toBe('I');
    expect(formatNumber(4, 'upperRoman')).toBe('IV');
    expect(formatNumber(5, 'upperRoman')).toBe('V');
    expect(formatNumber(9, 'upperRoman')).toBe('IX');
    expect(formatNumber(10, 'upperRoman')).toBe('X');
    expect(formatNumber(40, 'upperRoman')).toBe('XL');
    expect(formatNumber(90, 'upperRoman')).toBe('XC');
    expect(formatNumber(400, 'upperRoman')).toBe('CD');
    expect(formatNumber(900, 'upperRoman')).toBe('CM');
    expect(formatNumber(1000, 'upperRoman')).toBe('M');
  });

  it('組合：49 = XLIX, 1994 = MCMXCIV, 3999 = MMMCMXCIX', () => {
    expect(formatNumber(49, 'upperRoman')).toBe('XLIX');
    expect(formatNumber(1994, 'upperRoman')).toBe('MCMXCIV');
    expect(formatNumber(3999, 'upperRoman')).toBe('MMMCMXCIX');
  });

  it('lowerRoman 全小寫', () => {
    expect(formatNumber(11, 'lowerRoman')).toBe('xi');
    expect(formatNumber(2024, 'lowerRoman')).toBe('mmxxiv');
  });

  it('範圍外（>3999 或 <1）fallback decimal', () => {
    expect(formatNumber(4000, 'upperRoman')).toBe('4000');
    expect(formatNumber(0, 'upperRoman')).toBe('0');
  });
});

describe('numberingFormatter — ordinal / ordinalText / cardinalText', () => {
  it('ordinal：1st, 2nd, 3rd, 4th', () => {
    expect(formatNumber(1, 'ordinal')).toBe('1st');
    expect(formatNumber(2, 'ordinal')).toBe('2nd');
    expect(formatNumber(3, 'ordinal')).toBe('3rd');
    expect(formatNumber(4, 'ordinal')).toBe('4th');
    expect(formatNumber(21, 'ordinal')).toBe('21st');
    expect(formatNumber(102, 'ordinal')).toBe('102nd');
  });

  it('ordinal teen 例外：11th, 12th, 13th（不是 11st/12nd/13rd）', () => {
    expect(formatNumber(11, 'ordinal')).toBe('11th');
    expect(formatNumber(12, 'ordinal')).toBe('12th');
    expect(formatNumber(13, 'ordinal')).toBe('13th');
    expect(formatNumber(111, 'ordinal')).toBe('111th');
    expect(formatNumber(113, 'ordinal')).toBe('113th');
  });

  it('ordinalText 1–20 有英文寫法、>20 fallback ordinal', () => {
    expect(formatNumber(1, 'ordinalText')).toBe('first');
    expect(formatNumber(11, 'ordinalText')).toBe('eleventh');
    expect(formatNumber(20, 'ordinalText')).toBe('twentieth');
    expect(formatNumber(21, 'ordinalText')).toBe('21st');
  });

  it('cardinalText 1–20 有英文寫法、>20 fallback decimal', () => {
    expect(formatNumber(1, 'cardinalText')).toBe('one');
    expect(formatNumber(11, 'cardinalText')).toBe('eleven');
    expect(formatNumber(20, 'cardinalText')).toBe('twenty');
    expect(formatNumber(21, 'cardinalText')).toBe('21');
  });
});

// ── 中文 ────────────────────────────────────────────────────────────────────

describe('numberingFormatter — chineseCounting (中文書寫式)', () => {
  it('1–9 為「一…九」', () => {
    expect(formatNumber(1, 'chineseCounting')).toBe('一');
    expect(formatNumber(5, 'chineseCounting')).toBe('五');
    expect(formatNumber(9, 'chineseCounting')).toBe('九');
  });

  it('10–19 為「十、十一、…、十九」（無「一十」）', () => {
    expect(formatNumber(10, 'chineseCounting')).toBe('十');
    expect(formatNumber(11, 'chineseCounting')).toBe('十一');
    expect(formatNumber(19, 'chineseCounting')).toBe('十九');
  });

  it('20–99 為「二十、二十一、九十九」', () => {
    expect(formatNumber(20, 'chineseCounting')).toBe('二十');
    expect(formatNumber(25, 'chineseCounting')).toBe('二十五');
    expect(formatNumber(99, 'chineseCounting')).toBe('九十九');
  });

  it('100–999 含「零」處理', () => {
    expect(formatNumber(100, 'chineseCounting')).toBe('一百');
    expect(formatNumber(101, 'chineseCounting')).toBe('一百零一');
    expect(formatNumber(110, 'chineseCounting')).toBe('一百十');
    expect(formatNumber(120, 'chineseCounting')).toBe('一百二十');
    expect(formatNumber(125, 'chineseCounting')).toBe('一百二十五');
    expect(formatNumber(999, 'chineseCounting')).toBe('九百九十九');
  });

  it('1000–9999 含千位「零」處理', () => {
    expect(formatNumber(1000, 'chineseCounting')).toBe('一千');
    expect(formatNumber(1001, 'chineseCounting')).toBe('一千零一');
    expect(formatNumber(1010, 'chineseCounting')).toBe('一千零十');
    expect(formatNumber(1100, 'chineseCounting')).toBe('一千一百');
    expect(formatNumber(2024, 'chineseCounting')).toBe('二千零二十四'); // 2024 百位為 0、千-十之間補「零」（與 Word 行為一致）
    expect(formatNumber(9999, 'chineseCounting')).toBe('九千九百九十九');
  });

  it('0 為「〇」、負數加「負」', () => {
    expect(formatNumber(0, 'chineseCounting')).toBe('〇');
    expect(formatNumber(-5, 'chineseCounting')).toBe('負五');
  });

  it('>=10000 fallback decimal', () => {
    expect(formatNumber(10000, 'chineseCounting')).toBe('10000');
    expect(formatNumber(99999, 'chineseCounting')).toBe('99999');
  });

  it('japaneseCounting / taiwaneseCounting 與 chineseCounting 行為相同', () => {
    expect(formatNumber(25, 'japaneseCounting')).toBe('二十五');
    expect(formatNumber(101, 'taiwaneseCounting')).toBe('一百零一');
  });
});

describe('numberingFormatter — chineseLegalSimplified (大寫法定)', () => {
  it('1–9 為「壹貳…玖」', () => {
    expect(formatNumber(1, 'chineseLegalSimplified')).toBe('壹');
    expect(formatNumber(5, 'chineseLegalSimplified')).toBe('伍');
    expect(formatNumber(9, 'chineseLegalSimplified')).toBe('玖');
  });

  it('10 為「拾」、用「佰」「仟」', () => {
    expect(formatNumber(10, 'chineseLegalSimplified')).toBe('拾');
    expect(formatNumber(11, 'chineseLegalSimplified')).toBe('拾壹');
    expect(formatNumber(100, 'chineseLegalSimplified')).toBe('壹佰');
    expect(formatNumber(101, 'chineseLegalSimplified')).toBe('壹佰零壹');
    expect(formatNumber(1000, 'chineseLegalSimplified')).toBe('壹仟');
    expect(formatNumber(1001, 'chineseLegalSimplified')).toBe('壹仟零壹');
  });

  it('複雜：2024 = 貳仟零貳拾肆（百位 0 補零、法定用法）', () => {
    expect(formatNumber(2024, 'chineseLegalSimplified')).toBe('貳仟零貳拾肆');
  });

  it('>=10000 fallback decimal（簡化）', () => {
    expect(formatNumber(10000, 'chineseLegalSimplified')).toBe('10000');
  });
});

describe('numberingFormatter — ideographDigital (每位獨立)', () => {
  it('單一位數同 chineseCounting', () => {
    expect(formatNumber(1, 'ideographDigital')).toBe('一');
    expect(formatNumber(9, 'ideographDigital')).toBe('九');
  });

  it('多位數獨立轉換、不含十百千', () => {
    expect(formatNumber(10, 'ideographDigital')).toBe('一〇');
    expect(formatNumber(23, 'ideographDigital')).toBe('二三');
    expect(formatNumber(100, 'ideographDigital')).toBe('一〇〇');
    expect(formatNumber(2024, 'ideographDigital')).toBe('二〇二四');
    expect(formatNumber(2026, 'ideographDigital')).toBe('二〇二六');
  });

  it('0 為「〇」、負數加「負」', () => {
    expect(formatNumber(0, 'ideographDigital')).toBe('〇');
    expect(formatNumber(-23, 'ideographDigital')).toBe('負二三');
  });
});

describe('numberingFormatter — japaneseLegal (日文大寫)', () => {
  it('1–3 為「壱弐参」、4–9 為普通漢字', () => {
    expect(formatNumber(1, 'japaneseLegal')).toBe('壱');
    expect(formatNumber(2, 'japaneseLegal')).toBe('弐');
    expect(formatNumber(3, 'japaneseLegal')).toBe('参');
    expect(formatNumber(4, 'japaneseLegal')).toBe('四');
    expect(formatNumber(9, 'japaneseLegal')).toBe('九');
  });

  it('用「拾」、結構同 chineseLegal', () => {
    expect(formatNumber(10, 'japaneseLegal')).toBe('拾');
    expect(formatNumber(12, 'japaneseLegal')).toBe('拾弐');
    expect(formatNumber(23, 'japaneseLegal')).toBe('弐拾参');
  });
});

describe('numberingFormatter — japaneseDigitalTenThousand', () => {
  it('< 10000 同 chineseCounting', () => {
    expect(formatNumber(9999, 'japaneseDigitalTenThousand')).toBe('九千九百九十九');
  });

  it('= 10000 為「一万」', () => {
    expect(formatNumber(10000, 'japaneseDigitalTenThousand')).toBe('一万');
  });

  it('複雜：12345 = 一万二千三百四十五', () => {
    expect(formatNumber(12345, 'japaneseDigitalTenThousand')).toBe('一万二千三百四十五');
  });

  it('20000 = 二万', () => {
    expect(formatNumber(20000, 'japaneseDigitalTenThousand')).toBe('二万');
  });
});

// ── 循環序列 ────────────────────────────────────────────────────────────────

describe('numberingFormatter — ideographZodiac (12 地支循環)', () => {
  it('1=子, 2=丑, ..., 12=亥, 13=子（循環）', () => {
    expect(formatNumber(1, 'ideographZodiac')).toBe('子');
    expect(formatNumber(2, 'ideographZodiac')).toBe('丑');
    expect(formatNumber(11, 'ideographZodiac')).toBe('戌');
    expect(formatNumber(12, 'ideographZodiac')).toBe('亥');
    expect(formatNumber(13, 'ideographZodiac')).toBe('子');
    expect(formatNumber(24, 'ideographZodiac')).toBe('亥');
  });
});

describe('numberingFormatter — ideographTraditional (10 天干循環)', () => {
  it('1=甲, 10=癸, 11=甲（循環）', () => {
    expect(formatNumber(1, 'ideographTraditional')).toBe('甲');
    expect(formatNumber(2, 'ideographTraditional')).toBe('乙');
    expect(formatNumber(10, 'ideographTraditional')).toBe('癸');
    expect(formatNumber(11, 'ideographTraditional')).toBe('甲');
  });
});

describe('numberingFormatter — iroha / aiueo (日文假名循環)', () => {
  it('iroha 1=い, 2=ろ, 3=は, 47=す, 48=い（循環）', () => {
    expect(formatNumber(1, 'iroha')).toBe('い');
    expect(formatNumber(2, 'iroha')).toBe('ろ');
    expect(formatNumber(3, 'iroha')).toBe('は');
    expect(formatNumber(47, 'iroha')).toBe('す');
    expect(formatNumber(48, 'iroha')).toBe('い');
  });

  it('aiueo 1=あ, 2=い, 3=う, 46=ん', () => {
    expect(formatNumber(1, 'aiueo')).toBe('あ');
    expect(formatNumber(2, 'aiueo')).toBe('い');
    expect(formatNumber(3, 'aiueo')).toBe('う');
    expect(formatNumber(46, 'aiueo')).toBe('ん');
  });
});

// ── 邊界與防禦 ──────────────────────────────────────────────────────────────

describe('numberingFormatter — 邊界與防禦', () => {
  it('none / bullet 不渲染、回空字串', () => {
    expect(formatNumber(1, 'none')).toBe('');
    expect(formatNumber(5, 'bullet')).toBe('');
  });

  it('未知 numFmt fallback decimal、不 throw', () => {
    expect(formatNumber(42, 'foo')).toBe('42');
    expect(formatNumber(42, 'mysteryFormat')).toBe('42');
  });

  it('Infinity / NaN 回空字串', () => {
    expect(formatNumber(Infinity, 'decimal')).toBe('');
    expect(formatNumber(NaN, 'chineseCounting')).toBe('');
  });

  it('浮點數 floor 處理', () => {
    expect(formatNumber(3.7, 'decimal')).toBe('3.7'); // decimal 直回字串
    expect(formatNumber(3.7, 'upperRoman')).toBe('III'); // roman floor
    expect(formatNumber(3.7, 'chineseCounting')).toBe('三'); // CN floor
  });
});

// ── expandLvlText ──────────────────────────────────────────────────────────

describe('numberingFormatter — expandLvlText', () => {
  it('基本：「%1.%2.」+ counters [3, 2] + formats [decimal, lowerLetter] → "3.b."', () => {
    expect(expandLvlText('%1.%2.', [3, 2], ['decimal', 'lowerLetter'])).toBe('3.b.');
  });

  it('中文：「第%1章」+ [5] + [chineseCounting] → "第五章"', () => {
    expect(expandLvlText('第%1章', [5], ['chineseCounting'])).toBe('第五章');
  });

  it('複雜：「第%1.%2.%3 節」三層展開', () => {
    expect(
      expandLvlText('第%1.%2.%3 節', [1, 2, 3], ['chineseCounting', 'decimal', 'lowerRoman']),
    ).toBe('第一.2.iii 節');
  });

  it('缺對應 counter / numFmt 時 placeholder 變空字串、literal 字元保留', () => {
    // %2 缺、保留 literal "." → "3.." (兩個點)
    expect(expandLvlText('%1.%2.', [3], ['decimal'])).toBe('3..');
    // %3 缺、保留 literal end → "1.2."
    expect(expandLvlText('%1.%2.%3', [1, 2], ['decimal', 'decimal'])).toBe('1.2.');
  });

  it('無 placeholder 字串原樣返回', () => {
    expect(expandLvlText('附錄：', [1], ['decimal'])).toBe('附錄：');
  });

  it('連續 placeholder「%1%2」（無分隔符）', () => {
    expect(expandLvlText('%1%2', [1, 2], ['chineseCounting', 'chineseCounting'])).toBe('一二');
  });

  it('bullet level 展開為空字串（lvlText 通常是 "•"、不過此測 fallback path）', () => {
    expect(expandLvlText('%1', [5], ['bullet'])).toBe('');
  });

  it('%0 與 %A 等非 1-9 placeholder 不被替換（保留原樣）', () => {
    expect(expandLvlText('%0-%1', [5], ['decimal'])).toBe('%0-5');
    expect(expandLvlText('%A %1', [5], ['decimal'])).toBe('%A 5');
  });
});
