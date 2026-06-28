/**
 * ChartParser — 解析圖表（`c:` 命名空間、ECMA-376 §21.2、Phase 5.3）
 *
 * Sprint 182（capture-only）：
 *   Word 圖表（「插入 → 圖表」）在 document.xml 以 `<w:drawing>` 內
 *   `<a:graphicData uri=".../chart"><c:chart r:id="rId..">` 表示，圖本身不內嵌
 *   document.xml —— `r:id` 以 rId 指向獨立的 `charts/chartN.xml`。
 *
 *   chartN.xml 結構（`<c:chartSpace>` root）：
 *     <c:chartSpace>
 *       <c:chart>
 *         <c:title>...<a:t>標題</a:t>...</c:title>          ← 可選
 *         <c:plotArea>
 *           <c:barChart>                                    ← 圖表型別元素
 *             <c:ser>                                       ← 資料數列
 *               <c:tx><c:strRef><c:strCache>...數列名...</c:strCache></c:strRef></c:tx>
 *               <c:cat><c:strRef><c:strCache>...類別軸...</c:strCache></c:strRef></c:cat>
 *               <c:val><c:numRef><c:numCache>...數值...</c:numCache></c:numRef></c:val>
 *             </c:ser>
 *           </c:barChart>
 *         </c:plotArea>
 *       </c:chart>
 *     </c:chartSpace>
 *
 *   快取（`<c:strCache>` / `<c:numCache>`）是 Word 為離線顯示而存的資料副本：
 *   `<c:ptCount val="N"/>` 點數 + 0..N 個 `<c:pt idx="i"><c:v>值</c:v></c:pt>`
 *   （idx 可能稀疏 —— 空白點省略）。
 *
 * mc:Fallback 壓縮策略（user 2026-05-21 拍板）：本 capture 取**數值快取**——
 * 圖表型別 + 標題 + 各數列的類別 / 數值；不重繪座標軸與圖形（degraded fidelity，
 * 同 SmartArt 取資料模型文字）。座標軸 / 圖例 / 圖形 render 留未來 optional sprint。
 *
 * 防禦：undefined / 空 / XML 解析失敗 / root 非 `<c:chartSpace>` → 回 undefined（不 throw）。
 */

import type { ChartNode, ChartSeries } from '../ast/types';
import { directChildren } from '../utils/dom';

/** chart 部件 root 元素 localName。 */
const CHART_SPACE_TAG = 'chartSpace';
/** 圖表型別元素 localName 字尾（barChart / pieChart / bar3DChart …）。 */
const CHART_TYPE_SUFFIX = 'Chart';

export class ChartParser {
  /**
   * 解析 `charts/chartN.xml` 字串為 ChartNode。
   *
   * @param xml `charts/chartN.xml` 完整字串；undefined / 空 → 回 undefined
   * @param rId 對應的 chart 關係 rId（寫入 ChartNode.rId）
   * @returns ChartNode；XML 無法解析 / root 非 chartSpace / 無圖表型別 → undefined（不 throw）
   */
  parse(xml: string | undefined, rId: string): ChartNode | undefined {
    if (!xml) return undefined;

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return undefined;
    }
    const root = doc.documentElement;
    if (!root || stripPrefix(root.tagName) !== CHART_SPACE_TAG) return undefined;

    const chart = firstByTag(root, 'c:chart');
    if (!chart) return undefined;

    const plotArea = firstByTag(chart, 'c:plotArea');
    if (!plotArea) return undefined;

    // 圖表型別：plotArea 直屬子元素中第一個 localName 以 'Chart' 結尾者
    const typeEl = directChildren(plotArea).find((el) =>
      stripPrefix(el.tagName).endsWith(CHART_TYPE_SUFFIX),
    );
    if (!typeEl) return undefined;

    const node: ChartNode = {
      rId,
      chartType: stripPrefix(typeEl.tagName),
      series: [],
    };

    const title = readTitle(chart);
    if (title) node.title = title;

    for (const ser of tagChildren(typeEl, 'c:ser')) {
      node.series.push(readSeries(ser));
    }

    return node;
  }
}

/**
 * Sprint 183：把圖表轉為線性文字 fallback（render 用）。
 *
 * mc:Fallback 壓縮（user 2026-05-21 拍板）：不重繪座標軸與圖形，以
 * 「標題 數列名: 類別=值, …; …」格式呈現數值快取（degraded fidelity）。
 *
 * @returns 線性文字；無數列 → 空字串（或僅標題）
 */
export function chartToText(node: ChartNode): string {
  const parts: string[] = [];
  for (const s of node.series) {
    const pairs: string[] = [];
    for (let i = 0; i < s.categories.length; i++) {
      const cat = s.categories[i];
      const val = s.values[i];
      const hasVal = val !== null && val !== undefined;
      if (cat === '' && !hasVal) continue; // 完全空白點 → 跳過
      pairs.push(hasVal ? `${cat}=${val}` : cat);
    }
    const body = pairs.join(', ');
    const line = s.name ? `${s.name}: ${body}` : body;
    if (line !== '') parts.push(line);
  }
  const joined = parts.join('; ');
  return node.title ? `${node.title} ${joined}`.trim() : joined;
}

/** 從 `<c:chart>` 的 `<c:title>` 取標題文字（拼接所有 `<a:t>`）。空 → undefined。 */
function readTitle(chart: Element): string | undefined {
  const title = firstByTag(chart, 'c:title');
  if (!title) return undefined;
  const ts = title.getElementsByTagName('a:t');
  let out = '';
  for (let i = 0; i < ts.length; i++) out += ts[i].textContent ?? '';
  return out.trim() || undefined;
}

/** 解析單一 `<c:ser>` 為 ChartSeries。 */
function readSeries(ser: Element): ChartSeries {
  const series: ChartSeries = { categories: [], values: [] };

  // 數列名稱：<c:tx> 內快取的第一個 <c:v>
  const tx = firstByTag(ser, 'c:tx');
  if (tx) {
    const v = firstByTag(tx, 'c:v');
    const name = v?.textContent?.trim();
    if (name) series.name = name;
  }

  // 類別軸：<c:cat> 快取（字串）
  const cat = firstByTag(ser, 'c:cat');
  if (cat) {
    const { count, pts } = readCachePoints(cat);
    series.categories = Array.from({ length: count }, (_, i) => pts.get(i) ?? '');
  }

  // 數值：<c:val> numCache
  const val = firstByTag(ser, 'c:val');
  if (val) {
    const { count, pts } = readCachePoints(val);
    series.values = Array.from({ length: count }, (_, i) => {
      const raw = pts.get(i);
      if (raw === undefined || raw === '') return null;
      const n = Number(raw);
      return Number.isFinite(n) ? n : null;
    });
  }

  return series;
}

/**
 * 從 `<c:cat>` / `<c:val>` / `<c:tx>` 容器內的 `<c:strCache>` / `<c:numCache>`
 * 讀取點資料。
 *
 * @returns count = `<c:ptCount val>`（缺則用最大 idx+1）；pts = idx → `<c:v>` 文字
 */
function readCachePoints(container: Element): { count: number; pts: Map<number, string> } {
  const pts = new Map<number, string>();
  let maxIdx = -1;

  const ptEls = container.getElementsByTagName('c:pt');
  for (let i = 0; i < ptEls.length; i++) {
    const pt = ptEls[i];
    const idx = parseInt(pt.getAttribute('idx') ?? '', 10);
    if (!Number.isFinite(idx) || idx < 0) continue;
    const v = firstByTag(pt, 'c:v');
    pts.set(idx, v?.textContent ?? '');
    if (idx > maxIdx) maxIdx = idx;
  }

  // ptCount 優先；缺漏時退回最大 idx + 1
  let count = maxIdx + 1;
  const ptCountEls = container.getElementsByTagName('c:ptCount');
  if (ptCountEls.length > 0) {
    const n = parseInt(ptCountEls[0].getAttribute('val') ?? '', 10);
    if (Number.isFinite(n) && n >= 0) count = n;
  }
  return { count, pts };
}

/** 取第一個 localName 相符的後代元素（含命名空間前綴比對）。 */
function firstByTag(el: Element, qualifiedName: string): Element | undefined {
  const list = el.getElementsByTagName(qualifiedName);
  return list.length > 0 ? list[0] : undefined;
}

/** 取直屬子元素中 tagName 相符者。 */
function tagChildren(el: Element, qualifiedName: string): Element[] {
  return directChildren(el).filter((c) => c.tagName === qualifiedName);
}

/** 去掉標籤名的命名空間前綴（`c:` / `a:` 等），回傳 localName。 */
function stripPrefix(name: string): string {
  const idx = name.indexOf(':');
  return idx >= 0 ? name.slice(idx + 1) : name;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'ChartParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`ChartParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
