/**
 * TextMetrics — Layout Engine 的文字寬度 / 行高估算
 *
 * 設計：
 *   - 預設用 `EstimateMetrics`：純查表估算，不依賴字型檔
 *   - 介面留 `measureWidth / measureLineHeight`，未來可以注入 HarfBuzz 結果
 *
 * 估算規則（pt）：
 *   - Latin 字符：寬度 = fontSize × 0.5 × 字距倍率
 *   - CJK 字符（U+4E00–U+9FFF / U+3000–U+30FF）：寬度 = fontSize × 1.0
 *   - 半形數字 / 標點：fontSize × 0.55
 *   - 全形標點：fontSize × 1.0
 *   - 行高 = fontSize × 1.2（簡化版 Office 預設 leading）
 *
 * 偏差度：對 12pt 中文段落，估算 vs 實測 typical ±5%。Sprint 2 LineBreaker 不需精確，
 *         能維持「fixture 行數穩定」即可作為 regression baseline。
 */

import type { RunProps, Pt } from '../ooxml/ast/types';
import type { TextMetrics } from './types';

const DEFAULT_FONT_SIZE_PT = 10.5; // OOXML w:sz default = 21 half-points = 10.5pt
const DEFAULT_LINE_HEIGHT_RATIO = 1.2;

const BOLD_WIDTH_FACTOR = 1.06;

/** 判斷字符是否屬於 CJK 區塊（含全形標點）*/
export function isCjkChar(ch: string): boolean {
  if (!ch) return false;
  const code = ch.charCodeAt(0);
  // CJK Unified Ideographs
  if (code >= 0x4e00 && code <= 0x9fff) return true;
  // CJK Compatibility Ideographs
  if (code >= 0xf900 && code <= 0xfaff) return true;
  // CJK Symbols and Punctuation (3000–303F)
  if (code >= 0x3000 && code <= 0x303f) return true;
  // Hiragana / Katakana
  if (code >= 0x3040 && code <= 0x30ff) return true;
  // Halfwidth and Fullwidth Forms (FF00–FFEF)
  if (code >= 0xff00 && code <= 0xffef) return true;
  // Bopomofo
  if (code >= 0x3100 && code <= 0x312f) return true;
  return false;
}

/** Sprint 2 預設文字測量：純查表估算（不需字型檔）。*/
export class EstimateMetrics implements TextMetrics {
  /** measureWidth cache：相同 (text, fontSize, bold) 命中。*/
  private cache = new Map<string, Pt>();

  measureWidth(text: string, props: RunProps): Pt {
    if (!text) return 0;
    const fontSize = props.fontSize ?? DEFAULT_FONT_SIZE_PT;
    const bold = props.bold === true;
    const spacing = props.spacing ?? 0;
    const key = `${text}\x00${fontSize}\x00${bold ? 1 : 0}\x00${spacing}`;
    const cached = this.cache.get(key);
    if (cached !== undefined) return cached;

    let widthEms = 0;
    for (const ch of text) {
      widthEms += charWidthEms(ch);
    }
    let width = widthEms * fontSize;
    if (bold) width *= BOLD_WIDTH_FACTOR;
    // spacing：每字額外字距（pt）
    if (typeof props.spacing === 'number' && props.spacing !== 0) {
      width += props.spacing * countCharsForSpacing(text);
    }
    this.cache.set(key, width);
    return width;
  }

  measureLineHeight(props: RunProps): Pt {
    const fontSize = props.fontSize ?? DEFAULT_FONT_SIZE_PT;
    return fontSize * DEFAULT_LINE_HEIGHT_RATIO;
  }
}

/** 單字符寬度（em 為單位，乘 fontSize 得 pt）*/
function charWidthEms(ch: string): number {
  if (!ch) return 0;
  const code = ch.charCodeAt(0);
  // 常見半形空白
  if (code === 0x20 || code === 0x09) return 0.27;
  // 半形 Latin / 數字 / 基本標點
  if (code >= 0x21 && code <= 0x7e) {
    if (code >= 0x30 && code <= 0x39) return 0.55; // 數字
    if (code >= 0x41 && code <= 0x5a) return 0.61; // 大寫
    if (code >= 0x61 && code <= 0x7a) return 0.5; // 小寫
    return 0.45; // 標點
  }
  // CJK：1.15 em（Sprint 28 empirical）
  //
  // Word 對 CJK 字符的 effective advance width 大約是 fontSize × 1.0-1.20，
  // 來自字距 / cluster shaping / 字型 hinting 的累積。我們原本估算 1.0 過於樂觀，
  // 在多行 CJK 文本（特別是 cell 內）導致每行多塞 ~10-15% 字數，wrap 行數低估 1-2 行。
  //
  // 實驗結果（vitest 09_page_count_baseline）：
  //   - 1.00（原值）：mismatched 5 / 42
  //   - **1.10：mismatched 4（修 1：人手孔調升降）**
  //   - **1.15：mismatched 3（再修 1：地坪鋪面）** ← 採用
  //   - 1.20：mismatched 4（過度，01_simple/03.1120210 退化）
  //
  // 1.15 是甜蜜點：修最多 fixture（+2）且零退化。剩 3 個 -1 fixture（02_std_table/工地密度
  // + 03_complex_table/06-8估驗計價 ×2）root cause 不在 CJK 字寬。
  if (isCjkChar(ch)) return 1.15;
  // 預設半形寬度
  return 0.5;
}

function countCharsForSpacing(text: string): number {
  // 用 Array.from 處理 surrogate pair；spacing 以「字符」為單位
  return Array.from(text).length;
}
