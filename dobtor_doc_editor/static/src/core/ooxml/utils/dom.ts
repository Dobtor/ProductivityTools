/**
 * DOM 走訪共用工具
 *
 * 集中放跨 Parser 共用的 DOM helper，避免每個檔案重複定義。
 *
 * 主要 API：
 *   - directChildren(el)：取直接子 Element（過濾 text node / comment）
 *   - directChild(el, tag)：取首個指定 tagName 的直接子 Element
 *   - effectiveChildren(el)：directChildren 但展開 <mc:AlternateContent>
 *
 * 為什麼要 effectiveChildren：
 *   Word 365 產出常含 <mc:AlternateContent>：
 *     <mc:AlternateContent>
 *       <mc:Choice Requires="...">新版內容</mc:Choice>
 *       <mc:Fallback>舊版相容內容</mc:Fallback>
 *     </mc:AlternateContent>
 *   Parser 應優先讀 <mc:Choice>；若無 Choice 子元素，讀 <mc:Fallback>。
 *   此函式把 AlternateContent 包裝層展開，讓上層 walker 直接看到「實際內容子元素」。
 *   也支援巢狀 AlternateContent（雖極罕見）。
 */

/** 直接 Element 子節點（過濾 text/comment 等非 Element 子節點）。 */
export function directChildren(el: Element | undefined | null): Element[] {
  if (!el) return [];
  const out: Element[] = [];
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

/** 找首個指定 tagName 的直接子 Element。 */
export function directChild(
  el: Element | undefined | null,
  tagName: string,
): Element | undefined {
  for (const child of directChildren(el)) {
    if (child.tagName === tagName) return child;
  }
  return undefined;
}

/**
 * 直接 Element 子節點，但 mc:AlternateContent 子層自動展開。
 *
 * 展開規則：
 *   - 若直接子是 mc:AlternateContent：
 *       - 優先取其 mc:Choice 子元素的子節點（多個 Choice 取第一個）
 *       - 若無 Choice，取 mc:Fallback 子元素的子節點
 *       - 兩者都無時跳過此 AlternateContent
 *   - 其餘子節點原樣保留
 *   - 展開後若還含 mc:AlternateContent（巢狀），再遞迴展開
 *
 * @example
 *   <w:r>
 *     <mc:AlternateContent>
 *       <mc:Choice Requires="wps">  <newDrawing/>  </mc:Choice>
 *       <mc:Fallback>              <oldPict/>     </mc:Fallback>
 *     </mc:AlternateContent>
 *     <w:t>after</w:t>
 *   </w:r>
 *   →  effectiveChildren(<w:r>) = [<newDrawing/>, <w:t>after</w:t>]
 */
export function effectiveChildren(el: Element | undefined | null): Element[] {
  const out: Element[] = [];
  for (const child of directChildren(el)) {
    if (child.tagName === 'mc:AlternateContent') {
      // 優先 Choice，否則 Fallback
      const choice = directChild(child, 'mc:Choice');
      const fallback = directChild(child, 'mc:Fallback');
      const target = choice ?? fallback;
      if (target) {
        // 遞迴展開：target 內可能再有 AlternateContent
        out.push(...effectiveChildren(target));
      }
      // Choice 與 Fallback 都無時：跳過此 AlternateContent
    } else if (child.tagName === 'w:sdt') {
      // Sprint 124 — SDT 結構化文件標籤透明展開（ECMA-376 §17.5.2）
      // `<w:sdt>` 包 `<w:sdtPr>` (metadata) + `<w:sdtContent>` (actual content)。
      // 我們不渲染 sdtPr 的 alias / tag / form control type、純取 sdtContent
      // 子節點 inline 到父級（block-level / inline-level / cell-level 都適用）。
      // 遞迴展開 sdtContent（OOXML 允許 sdt 嵌套，且 sdtContent 內可能再含
      // AlternateContent 或 sdt）。
      const sdtContent = directChild(child, 'w:sdtContent');
      if (sdtContent) {
        out.push(...effectiveChildren(sdtContent));
      }
      // sdtContent 缺失（malformed docx）→ 此 sdt 不貢獻內容、跳過
    } else {
      out.push(child);
    }
  }
  return out;
}

/** 取屬性，無屬性時回 undefined（簡化 null/string 二元判斷）。 */
export function attr(el: Element | undefined, name: string): string | undefined {
  if (!el) return undefined;
  const v = el.getAttribute(name);
  return v === null ? undefined : v;
}

/**
 * OOXML 布林屬性慣例：
 *   - 元素存在且無 w:val 屬性 → true
 *   - w:val="0" / "false" → false
 *   - w:val="1" / "true" → true
 */
export function boolFlag(el: Element | undefined): boolean {
  if (!el) return false;
  const v = el.getAttribute('w:val');
  if (v === null) return true;
  return v !== '0' && v.toLowerCase() !== 'false';
}
