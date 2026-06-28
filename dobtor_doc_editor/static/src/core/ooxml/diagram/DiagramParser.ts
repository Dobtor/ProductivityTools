/**
 * DiagramParser — 解析 SmartArt 圖表資料模型（`dgm:` 命名空間、ECMA-376 §21.4、Phase 5.2）
 *
 * Sprint 181（capture-only）：
 *   Word SmartArt（「插入 → SmartArt」）在 document.xml 以 `<w:drawing>` 內
 *   `<a:graphicData uri=".../diagram"><dgm:relIds r:dm="rId..">` 表示，圖本身不內嵌於
 *   document.xml —— `r:dm` 以 rId 指向獨立的 `diagrams/dataN.xml`（資料模型部件）。
 *
 *   dataN.xml 結構（`<dgm:dataModel>`）：
 *     <dgm:dataModel>
 *       <dgm:ptLst>
 *         <dgm:pt type="doc"><dgm:prSet loTypeId="...VerticalCircleList"/>...</dgm:pt>
 *         <dgm:pt modelId="{..}">                  ← 內容點（無 type 屬性）
 *           <dgm:t><a:p><a:r><a:t>節點文字</a:t></a:r></a:p></dgm:t>
 *         </dgm:pt>
 *         <dgm:pt type="pres">...</dgm:pt>          ← presentation 點（跳過）
 *         <dgm:pt type="parTrans"/> <dgm:pt type="sibTrans"/>  ← 連接點（跳過）
 *       </dgm:ptLst>
 *       <dgm:cxnLst>...</dgm:cxnLst>                ← 連接關係（本 capture 不取）
 *     </dgm:dataModel>
 *
 * mc:Fallback 壓縮策略（user 2026-05-21 拍板）：本 capture 僅取資料模型的**文字內容**
 * 與版面類型識別碼，不重建圖形版面與連接線（degraded fidelity，對應 OMML 線性文字
 * fallback）。圖形精確 render 留未來 optional sprint。
 *
 * 防禦：undefined / 空 / XML 解析失敗 / root 非 `<dgm:dataModel>` → 回 undefined（不 throw）。
 */

import type { SmartArtNode } from '../ast/types';
import { directChild, directChildren } from '../utils/dom';

/** SmartArt 資料模型 root 元素 localName。 */
const DATA_MODEL_TAG = 'dataModel';
/** 內容點（非 presentation / 連接點）的 type 值；亦涵蓋「無 type 屬性」。 */
const CONTENT_PT_TYPE = 'node';
/** 跳過的 presentation / 結構點 type 值（不含使用者輸入文字的語意內容）。 */
const SKIP_PT_TYPES = new Set(['doc', 'pres', 'parTrans', 'sibTrans']);

export class DiagramParser {
  /**
   * 解析 `diagrams/dataN.xml` 字串為 SmartArtNode。
   *
   * @param xml `diagrams/dataN.xml` 完整字串；undefined / 空 → 回 undefined
   * @param rId 對應的 diagramData 關係 rId（寫入 SmartArtNode.rId）
   * @returns SmartArtNode；XML 無法解析 / root 非 dataModel → undefined（不 throw）
   */
  parse(xml: string | undefined, rId: string): SmartArtNode | undefined {
    if (!xml) return undefined;

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return undefined;
    }
    const root = doc.documentElement;
    if (!root || stripDgmPrefix(root.tagName) !== DATA_MODEL_TAG) return undefined;

    const ptLst = directChild(root, 'dgm:ptLst');
    const pts = ptLst ? directChildren(ptLst) : [];

    const node: SmartArtNode = { rId, texts: [] };

    for (const pt of pts) {
      if (stripDgmPrefix(pt.tagName) !== 'pt') continue;
      const type = pt.getAttribute('type') ?? CONTENT_PT_TYPE;
      // doc 點：抓版面類型識別碼（loTypeId）
      if (type === 'doc') {
        const layoutType = readLayoutType(pt);
        if (layoutType) node.layoutType = layoutType;
        continue;
      }
      // presentation / 連接點：無語意文字、跳過
      if (SKIP_PT_TYPES.has(type)) continue;
      // 內容點：抓 <dgm:t> 文字
      const text = readPtText(pt);
      if (text) node.texts.push(text);
    }

    return node;
  }
}

/**
 * Sprint 183：把 SmartArt 轉為線性文字 fallback（render 用）。
 *
 * mc:Fallback 壓縮（user 2026-05-21 拍板）：不重建圖形版面與連接線，
 * 各內容點文字以 ` / ` 串接呈現（degraded fidelity、對應 OMML 線性文字 fallback）。
 *
 * @returns 線性文字；無文字 → 空字串
 */
export function smartArtToText(node: SmartArtNode): string {
  return node.texts.join(' / ');
}

/**
 * 從 `<dgm:pt type="doc">` 的 `<dgm:prSet loTypeId>` 取版面類型識別碼。
 * 無 prSet 或無 loTypeId → undefined。
 */
function readLayoutType(docPt: Element): string | undefined {
  const prSet = directChild(docPt, 'dgm:prSet');
  const loTypeId = prSet?.getAttribute('loTypeId');
  return loTypeId && loTypeId.length > 0 ? loTypeId : undefined;
}

/**
 * 取 `<dgm:pt>` 內 `<dgm:t>` 的文字：各 `<a:p>` 段落以 `\n` 串接，
 * 段落內所有 `<a:t>` 文字依序拼接。無文字 → 空字串。
 */
function readPtText(pt: Element): string {
  const t = directChild(pt, 'dgm:t');
  if (!t) return '';
  const paras: string[] = [];
  for (const p of directChildren(t)) {
    if (stripDgmPrefix(p.tagName) !== 'p') continue; // <a:p>
    const runs = p.getElementsByTagName('a:t');
    let line = '';
    for (let i = 0; i < runs.length; i++) {
      line += runs[i].textContent ?? '';
    }
    paras.push(line);
  }
  return paras.join('\n').trim();
}

/**
 * 去掉標籤名的命名空間前綴（`dgm:` / `a:` 等），回傳 localName。
 * 無前綴則原樣回傳。
 */
function stripDgmPrefix(name: string): string {
  const idx = name.indexOf(':');
  return idx >= 0 ? name.slice(idx + 1) : name;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'DiagramParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`DiagramParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
