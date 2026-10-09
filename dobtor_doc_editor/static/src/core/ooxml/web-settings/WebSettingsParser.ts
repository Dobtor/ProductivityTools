/**
 * WebSettingsParser — 解析 word/webSettings.xml(OOXML §17.16)
 *
 * Sprint 148(capture-only、結束 Phase 1 part 三連 cluster):
 *   - 42/42 fixture 都有 webSettings.xml(Word 預設骨架)
 *   - 主要是 docx 匯出 HTML 時的 hint、import / layout / render 不用
 *   - 留 hook 給將來 Phase 6 docx export 對稱性
 *
 * 解析範圍(scope-down、紀律 #18):
 *   - 4 toggle 元素(allowPNG / optimizeForBrowser / saveSmartTagsAsXml / doNotSaveAsSingleFile)
 *   - hasDivs:是否含 w:divs(不深入內部巢狀結構)
 *
 * 防禦:undefined / 空 / XML 失敗 → 回 {}(不阻塞 OoxmlParser)。
 */

import type { DocumentWebSettings } from '../ast/types';

export class WebSettingsParser {
  /**
   * 解析 word/webSettings.xml 字串為 DocumentWebSettings。
   *
   * @param xml webSettings.xml 完整字串;undefined / 空 → 回 {}
   */
  parse(xml: string | undefined): DocumentWebSettings {
    if (!xml) return {};

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return {};
    }

    const root = doc.documentElement;
    if (!root) return {};

    const out: DocumentWebSettings = {};

    for (const child of directChildren(root)) {
      switch (child.tagName) {
        case 'w:optimizeForBrowser':
          out.optimizeForBrowser = readToggle(child);
          break;
        case 'w:allowPNG':
          out.allowPNG = readToggle(child);
          break;
        case 'w:saveSmartTagsAsXml':
          out.saveSmartTagsAsXml = readToggle(child);
          break;
        case 'w:doNotSaveAsSingleFile':
          out.doNotSaveAsSingleFile = readToggle(child);
          break;
        case 'w:divs':
          // 只 capture 存在性、不深入內部結構(紀律 #18)
          // 空 w:divs(無子元素)視為「無 divs」、與 OOXML §17.16.5 一致
          if (directChildren(child).length > 0) {
            out.hasDivs = true;
          }
          break;
      }
    }

    return out;
  }
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

function readToggle(el: Element): boolean {
  const v = el.getAttribute('w:val');
  if (v === null) return true;
  return v !== '0' && v.toLowerCase() !== 'false';
}

function directChildren(el: Element | undefined): Element[] {
  if (!el) return [];
  const out: Element[] = [];
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'WebSettingsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`WebSettingsParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
