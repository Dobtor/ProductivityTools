/**
 * colorResolver — 統一處理 <w:color> 元素 → hex 解析（含 themeColor）
 *
 * Word 的 <w:color> 元素三種寫法：
 *   1. <w:color w:val="FF0000"/>             → 直接 hex
 *   2. <w:color w:val="auto"/>               → 系統預設（黑色）
 *   3. <w:color w:themeColor="accent1"
 *               w:themeTint="80"/>           → theme reference + tint
 *
 * 此 helper 把三種統一回傳 6-hex；無 ThemeMap 或無法解析時降級為 undefined。
 *
 * 使用情境：
 *   - ParagraphParser.parseRunProps 對 <w:color> 子元素呼叫
 *   - StyleResolver.flattenStyle 對 <w:color> 子元素呼叫
 *   - 未來 BorderConflictResolver 對 <w:tcBorders> / <w:tblBorders> 內每邊呼叫
 */

import type { HexColor } from '../ast/types';
import type { ThemeMap } from './ThemeResolver';
import { resolveThemeColor } from './ThemeResolver';
import { attr } from '../utils/dom';

/**
 * 從 <w:color w:val="..." w:themeColor="..." w:themeTint="..." w:themeShade="..."/>
 * 取出最終 hex color。
 *
 * @param colorEl  `<w:color>` Element（可能 undefined）
 * @param theme    ThemeMap（可能 null，無 theme 時不解析 themeColor）
 * @returns 6-hex；找不到合法值回 undefined
 */
export function resolveColorElement(
  colorEl: Element | undefined,
  theme: ThemeMap | null,
): HexColor | undefined {
  if (!colorEl) return undefined;

  const val = attr(colorEl, 'w:val');
  // val="auto" 表示自動色（系統預設，通常黑）；不視為明確指定
  if (val && val.toLowerCase() !== 'auto' && /^[0-9A-Fa-f]{6}$/.test(val)) {
    return val.toUpperCase();
  }

  const themeColor = attr(colorEl, 'w:themeColor');
  if (themeColor && theme) {
    const tint = attr(colorEl, 'w:themeTint');
    const shade = attr(colorEl, 'w:themeShade');
    return resolveThemeColor(theme, themeColor, tint, shade);
  }

  return undefined;
}
