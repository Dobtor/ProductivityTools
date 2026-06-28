/**
 * BackgroundParser — 解析 word/document.xml 的 `<w:background>`（OOXML §17.2.1）
 *
 * Sprint 171（Phase 5.6 浮水印 + 背景）：
 *   `<w:background>` 是 `<w:document>` 的直接子元素（`<w:body>` 的 sibling）、
 *   描述頁面背景色。Word「設計 → 頁面色彩」功能的儲存位置。
 *
 * 解析範圍（對應 DocumentBackground interface）：
 *   - `w:color`      → color（6-hex 大寫；"auto" / 非法 / 缺 → 不掛）
 *   - `w:themeColor` → themeColor（capture raw 主題色名、未解析為 hex）
 *
 * Scope-down（紀律 #18）：themeColor 不解析為 hex（render wire-up 用 color）；
 * `<v:background>` VML 圖片填充背景留後續 sprint。
 *
 * 紀律 #21：無 `<w:background>` 或無有效屬性 → 回 undefined（不掛空 key）。
 * 防禦：undefined / 空 / XML 解析失敗 → 回 undefined（不阻塞 OoxmlParser）。
 */

import type { DocumentBackground } from '../ast/types';
import type { ThemeMap } from '../styles/ThemeResolver';
import { resolveThemeColor } from '../styles/ThemeResolver';

/** OOXML hex 色：6 位 16 進位。 */
const HEX6_RE = /^[0-9A-Fa-f]{6}$/;

export class BackgroundParser {
  /**
   * 解析 word/document.xml 字串、抽出 `<w:background>` 為 DocumentBackground。
   *
   * @param documentXml document.xml 完整字串；undefined / 空 → 回 undefined
   * @param themeMap    Sprint 178：已解析的 ThemeMap；提供時把 `w:themeColor`
   *                    （含 themeTint/themeShade）解析為具體 hex 寫入 `color`
   *                    （`w:color` 已直接給時不覆寫）。
   * @returns DocumentBackground 或 undefined（無背景設定）
   */
  parse(documentXml: string | undefined, themeMap?: ThemeMap): DocumentBackground | undefined {
    if (!documentXml) return undefined;

    let doc: Document;
    try {
      doc = parseXml(documentXml);
    } catch {
      return undefined;
    }

    const root = doc.documentElement;
    if (!root) return undefined;

    const bg = directChild(root, 'w:background');
    if (!bg) return undefined;

    const out: DocumentBackground = {};
    const color = bg.getAttribute('w:color');
    if (color && HEX6_RE.test(color)) {
      out.color = color.toUpperCase();
    }
    const themeColor = bg.getAttribute('w:themeColor');
    if (themeColor) {
      out.themeColor = themeColor;
      // Sprint 178：themeColor → 具體 hex（w:color 已直接給時不覆寫）。
      //   含 themeTint / themeShade（resolveThemeColor 內套變亮 / 變暗）。
      if (out.color === undefined && themeMap) {
        const tint = bg.getAttribute('w:themeTint') ?? undefined;
        const shade = bg.getAttribute('w:themeShade') ?? undefined;
        out.color = resolveThemeColor(themeMap, themeColor, tint, shade);
      }
    }

    // 紀律 #21：無有效屬性（如僅 w:color="auto"）→ 不掛空物件
    return Object.keys(out).length > 0 ? out : undefined;
  }
}

/** 取得第一個 tagName 相符的直接子元素。 */
function directChild(el: Element, tagName: string): Element | undefined {
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1 && (n as Element).tagName === tagName) {
      return n as Element;
    }
  }
  return undefined;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'BackgroundParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`BackgroundParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
