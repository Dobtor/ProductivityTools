/**
 * LatentStylesParser — 解析 styles.xml `<w:latentStyles>`(OOXML §17.7.4.6)
 *
 * Sprint 153(capture-only、styles/ 子目錄延伸):
 *   - 41/42 fixture 有 latentStyles(Word 預設骨架、平均 ~147 lsdException)
 *   - layout / render 不消費(latent styles 是 Word UI 'Style Gallery' 顯示用)
 *   - 為將來 Phase 6 docx export 對稱性鋪路(export 端要原樣重建 latentStyles)
 *
 * 解析結構:
 *   <w:latentStyles
 *     w:defLockedState="0"
 *     w:defUIPriority="99"
 *     w:defSemiHidden="1"
 *     w:defUnhideWhenUsed="1"
 *     w:defQFormat="0"
 *     w:count="267">
 *     <w:lsdException w:name="Normal" w:uiPriority="0" w:qFormat="1"/>
 *     <w:lsdException w:name="heading 1" ... />
 *     ...
 *   </w:latentStyles>
 *
 * 設計決策:
 *   - 與 StyleResolver 平行(StyleResolver 處理 <w:style>、本 parser 處理 <w:latentStyles>)
 *   - 紀律 #21:屬性不存在 → undefined、不掛 key
 *   - 紀律 #18:exceptions 用 Map<name, LatentStyleException>、不展開為陣列(便於 lookup)
 *   - 重複 name(理論不應發生)→ 後者覆蓋前者
 *
 * 防禦:undefined / 空 / XML 失敗 / 缺 root → 回 {}(不阻塞 OoxmlParser)。
 */

import type { DocumentLatentStyles, LatentStyleException } from '../ast/types';

export class LatentStylesParser {
  /**
   * 從 styles.xml 字串中找 `<w:latentStyles>` 並解析。
   *
   * @param xml styles.xml 完整字串;undefined / 空 / 無 latentStyles → 回 {}
   */
  parse(xml: string | undefined): DocumentLatentStyles {
    if (!xml || !xml.trim()) return {};

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return {};
    }

    const root = doc.documentElement;
    if (!root) return {};

    // 找 latentStyles 子元素(在 <w:styles> 下層)
    const latentEl = findDirectChildByLocalName(root, 'latentStyles');
    if (!latentEl) return {};

    const out: DocumentLatentStyles = {};

    // root 級 defaults(5 個 toggle/integer + count)
    assignToggle(out, 'defLockedState', latentEl, 'defLockedState');
    assignInt(out, 'defUIPriority', latentEl, 'defUIPriority');
    assignToggle(out, 'defSemiHidden', latentEl, 'defSemiHidden');
    assignToggle(out, 'defUnhideWhenUsed', latentEl, 'defUnhideWhenUsed');
    assignToggle(out, 'defQFormat', latentEl, 'defQFormat');
    assignInt(out, 'count', latentEl, 'count');

    // exceptions(0..N 個 lsdException 子元素)
    const exceptions = new Map<string, LatentStyleException>();
    for (let i = 0; i < latentEl.childNodes.length; i++) {
      const n = latentEl.childNodes[i];
      if (n.nodeType !== 1) continue;
      const el = n as Element;
      if (localName(el) !== 'lsdException') continue;

      const name = readAttr(el, 'name');
      if (!name) continue;  // 紀律 #21:無 name 跳過

      const ex: LatentStyleException = {};
      assignToggle(ex, 'locked', el, 'locked');
      assignInt(ex, 'uiPriority', el, 'uiPriority');
      assignToggle(ex, 'semiHidden', el, 'semiHidden');
      assignToggle(ex, 'unhideWhenUsed', el, 'unhideWhenUsed');
      assignToggle(ex, 'qFormat', el, 'qFormat');

      // 紀律 #21:全空的 exception 仍掛 key(name 本身已是資訊、e.g. 區分「存在 latent style」與「不存在」)
      exceptions.set(name, ex);
    }

    if (exceptions.size > 0) {
      out.exceptions = exceptions;
    }

    return out;
  }
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

/** 用 w:* prefix 讀屬性、xmldom 部分版本不能直接用 namespace lookup */
function readAttr(el: Element, localAttrName: string): string | null {
  // 先試 w:name、再試 localName (defensive、實際 fixture 都用 w: prefix)
  const v = el.getAttribute(`w:${localAttrName}`);
  if (v !== null) return v;
  return el.getAttribute(localAttrName);
}

function assignToggle<T>(out: T, key: keyof T, el: Element, attrName: string): void {
  const v = readAttr(el, attrName);
  if (v === null) return;  // 紀律 #21:屬性不存在 → undefined
  // OOXML toggle:"0"/"false" = false、否則 true(包含 "1"/"true"/空字串)
  (out as Record<string, unknown>)[key as string] = v !== '0' && v.toLowerCase() !== 'false';
}

function assignInt<T>(out: T, key: keyof T, el: Element, attrName: string): void {
  const v = readAttr(el, attrName);
  if (v === null) return;
  if (!/^-?\d+$/.test(v)) return;
  const n = parseInt(v, 10);
  if (!Number.isFinite(n)) return;
  (out as Record<string, unknown>)[key as string] = n;
}

function localName(el: Element): string {
  const ln = el.localName;
  if (ln) return ln;
  const tag = el.tagName;
  const colon = tag.indexOf(':');
  return colon >= 0 ? tag.substring(colon + 1) : tag;
}

function findDirectChildByLocalName(parent: Element, target: string): Element | null {
  for (let i = 0; i < parent.childNodes.length; i++) {
    const n = parent.childNodes[i];
    if (n.nodeType !== 1) continue;
    const el = n as Element;
    if (localName(el) === target) return el;
  }
  return null;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'LatentStylesParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`LatentStylesParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
