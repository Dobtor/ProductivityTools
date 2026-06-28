/**
 * StyleResolver — word/styles.xml 樣式繼承鏈展開
 *
 * 解析三層繼承鏈：docDefaults → parent chain (basedOn) → current。
 * Resolver 完成後輸出已展開的 StyleMap，供 ParagraphParser / TableParser 直接合併。
 *
 * 演算法：
 *   1. 解析 <w:docDefaults>：rPrDefault / pPrDefault → 全域預設
 *   2. 第一遍走訪 <w:style>：收集每個 style 的 raw props + basedOn ID（不展開）
 *   3. 第二遍對每個 styleId：
 *        - DFS 走 basedOn 鏈（cycle detection 用 Set）
 *        - 從最遠祖先往下逐層 merge：docDefaults → ... → parent → current
 *        - 結果存入 StyleMap
 *
 * 注意：
 *   - 缺失的 basedOn（指向不存在的 styleId）視為無 parent，不 throw
 *   - 偵測到迴圈（A.basedOn=B, B.basedOn=A）時，停在 A，不 throw
 *   - <w:style w:type> 不限定為 paragraph：character / table / numbering 也保留
 *     供未來 TableParser / NumberingResolver 使用，目前只展開 pPr / rPr
 */

import type {
  ParagraphProps,
  RunProps,
  StyleEntry,
  StyleMap,
  TableConditionalType,
  TableConditionalCellProps,
  HexColor,
  CellBorders,
} from '../ast/types';
import {
  parseParagraphProps,
  parseRunProps,
  setThemeMapForParser,
} from '../document/ParagraphParser';
import { parseBorderDef } from './borderShading';
import type { ThemeMap } from './ThemeResolver';

interface RawStyleEntry {
  id: string;
  type?: string; // paragraph / character / table / numbering
  basedOn?: string;
  pPr?: ParagraphProps;
  rPr?: RunProps;
  /**
   * 表格條件樣式（僅 type="table" 的 style 才會有）。
   *
   * key = w:tblStylePr 的 type（firstRow/lastRow/firstCol/...，13–15 種）
   * value = 該條件下的 pPr / rPr
   *
   * 條件樣式不參與 basedOn 繼承鏈展開，原樣保留供 Renderer 套用。
   */
  conditional?: Map<
    TableConditionalType,
    { pPr?: ParagraphProps; rPr?: RunProps; cPr?: TableConditionalCellProps }
  >;
}

export class StyleResolver {
  /** Phase 4.1：themeColor 解析時用的 ThemeMap（OoxmlParser 注入）。 */
  private themeMap: ThemeMap | null = null;

  /**
   * 注入 ThemeMap。flattenStyle 走 parseRunProps / parseParagraphProps 時，
   * 透過共用的 module-scope `themeMapForParser`（位於 ParagraphParser）
   * 自動取得 ThemeMap，但本 class 也在 resolve() 開始時主動 set 一次以保險。
   */
  setThemeMap(theme: ThemeMap | null): void {
    this.themeMap = theme;
    // 同步傳遞給 module-scoped variable，讓 parseRunProps / parseParagraphProps 也能解
    // themeColor。允許獨立用 StyleResolver（測試）時 themeColor 仍能解析。
    setThemeMapForParser(theme);
  }

  /**
   * 解析 styles.xml 字串為展開後的 StyleMap。
   *
   * @param xml word/styles.xml 內容；undefined 時回空 Map
   */
  resolve(xml: string | undefined): StyleMap {
    if (!xml) return new Map();

    const doc = parseXml(xml);
    const root = doc.documentElement;
    if (!root) return new Map();

    // Step 1：docDefaults
    const docDefaults = parseDocDefaults(root);

    // Step 2：raw 收集
    const raw = new Map<string, RawStyleEntry>();
    const styleEls = root.getElementsByTagName('w:style');
    for (let i = 0; i < styleEls.length; i++) {
      const entry = parseRawStyle(styleEls[i]);
      if (entry) raw.set(entry.id, entry);
    }

    // Step 3：對每個 styleId 展開繼承鏈，merge 後寫入 StyleMap
    const out: StyleMap = new Map();
    for (const id of raw.keys()) {
      const flat = flattenStyle(id, raw, docDefaults);
      out.set(id, flat);
    }
    return out;
  }
}

// ── docDefaults ──────────────────────────────────────────────────────────────

interface DocDefaults {
  pPr?: ParagraphProps;
  rPr?: RunProps;
}

function parseDocDefaults(root: Element): DocDefaults {
  const out: DocDefaults = {};
  const docDefaultsEl = directChild(root, 'w:docDefaults');
  if (!docDefaultsEl) return out;

  const rPrDefault = directChild(docDefaultsEl, 'w:rPrDefault');
  if (rPrDefault) {
    const rPr = directChild(rPrDefault, 'w:rPr');
    if (rPr) out.rPr = parseRunProps(rPr);
  }
  const pPrDefault = directChild(docDefaultsEl, 'w:pPrDefault');
  if (pPrDefault) {
    const pPr = directChild(pPrDefault, 'w:pPr');
    if (pPr) out.pPr = parseParagraphProps(pPr);
  }
  return out;
}

// ── 單一 <w:style> 解析（不展開繼承） ────────────────────────────────────────

function parseRawStyle(styleEl: Element): RawStyleEntry | undefined {
  const id = styleEl.getAttribute('w:styleId');
  if (!id) return undefined;
  const type = styleEl.getAttribute('w:type') ?? undefined;

  let basedOn: string | undefined;
  let pPr: ParagraphProps | undefined;
  let rPr: RunProps | undefined;
  let conditional:
    | Map<TableConditionalType, { pPr?: ParagraphProps; rPr?: RunProps }>
    | undefined;

  for (const child of directChildren(styleEl)) {
    switch (child.tagName) {
      case 'w:basedOn': {
        const v = child.getAttribute('w:val');
        if (v) basedOn = v;
        break;
      }
      case 'w:pPr':
        pPr = parseParagraphProps(child);
        break;
      case 'w:rPr':
        rPr = parseRunProps(child);
        break;
      case 'w:tblStylePr': {
        // 表格條件樣式：依 w:type（firstRow/lastRow/etc.）分類
        const condType = child.getAttribute('w:type');
        if (!condType) break;
        const condPPr = directChild(child, 'w:pPr');
        const condRPr = directChild(child, 'w:rPr');
        const condTcPr = directChild(child, 'w:tcPr');
        const entry: {
          pPr?: ParagraphProps;
          rPr?: RunProps;
          cPr?: TableConditionalCellProps;
        } = {};
        if (condPPr) entry.pPr = parseParagraphProps(condPPr);
        if (condRPr) entry.rPr = parseRunProps(condRPr);
        if (condTcPr) {
          // Sprint 131：提取 cell-level 條件 props（shading + vAlign）
          const cPr = parseConditionalTcPr(condTcPr);
          if (cPr) entry.cPr = cPr;
        }
        if (entry.pPr || entry.rPr || entry.cPr) {
          if (!conditional) conditional = new Map();
          conditional.set(condType as TableConditionalType, entry);
        }
        break;
      }
    }
  }

  const out: RawStyleEntry = { id };
  if (type) out.type = type;
  if (basedOn) out.basedOn = basedOn;
  if (pPr) out.pPr = pPr;
  if (rPr) out.rPr = rPr;
  if (conditional && conditional.size > 0) out.conditional = conditional;
  return out;
}

// ── 繼承鏈展開 ────────────────────────────────────────────────────────────────

function flattenStyle(
  id: string,
  raw: Map<string, RawStyleEntry>,
  docDefaults: DocDefaults,
): StyleEntry {
  // Step 1：走 basedOn 鏈，從遠祖到本身的順序
  const chain: RawStyleEntry[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined = id;
  while (cursor && !seen.has(cursor)) {
    seen.add(cursor);
    const entry = raw.get(cursor);
    if (!entry) break;
    chain.unshift(entry); // 越早加入 = 越遠祖先（merge 從遠祖開始）
    cursor = entry.basedOn;
  }

  // Step 2：merge 順序 docDefaults → 遠祖 → ... → 本身
  let pProps: ParagraphProps | undefined;
  let rProps: RunProps | undefined;
  if (docDefaults.pPr) pProps = mergePProps(pProps, docDefaults.pPr);
  if (docDefaults.rPr) rProps = mergeRProps(rProps, docDefaults.rPr);
  for (const entry of chain) {
    if (entry.pPr) pProps = mergePProps(pProps, entry.pPr);
    if (entry.rPr) rProps = mergeRProps(rProps, entry.rPr);
  }

  const self = raw.get(id);
  const out: StyleEntry = {};
  if (pProps) out.pProps = pProps;
  if (rProps) out.rProps = rProps;
  if (self?.basedOn) out.basedOn = self.basedOn;
  // 條件樣式直接保留（不參與 basedOn 繼承鏈），把 raw 內部的 pPr/rPr/cPr 轉成 AST 的 pProps/rProps/cProps
  if (self?.conditional) {
    const out2 = new Map<
      TableConditionalType,
      { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
    >();
    for (const [type, entry] of self.conditional) {
      const conv: {
        pProps?: ParagraphProps;
        rProps?: RunProps;
        cProps?: TableConditionalCellProps;
      } = {};
      if (entry.pPr) conv.pProps = entry.pPr;
      if (entry.rPr) conv.rProps = entry.rPr;
      if (entry.cPr) conv.cProps = entry.cPr;
      out2.set(type, conv);
    }
    out.conditional = out2;
  }
  return out;
}

/**
 * Sprint 131：解析 `<w:tblStylePr w:type="firstRow"><w:tcPr>...</w:tcPr></w:tblStylePr>`
 * 內的 cell-level 條件 props。
 *
 * 只提取最常用的兩個：
 *   - w:shd → shading（header row 背景色）
 *   - w:vAlign → 垂直對齊
 *
 * 其他 tcPr 子元素（tcBorders/tcMar/noWrap/textDirection）defer 到未來 sprint。
 *
 * 缺值或全空時回 undefined（caller 用 if (cPr) 檢查是否掛 key）。
 */
function parseConditionalTcPr(tcPr: Element): TableConditionalCellProps | undefined {
  const out: TableConditionalCellProps = {};

  const shdEl = directChild(tcPr, 'w:shd');
  if (shdEl) {
    const fill = shdEl.getAttribute('w:fill');
    const color = shdEl.getAttribute('w:color');
    const pattern = shdEl.getAttribute('w:val');
    const shd: { fill?: HexColor; color?: HexColor; pattern?: string } = {};
    if (fill) shd.fill = fill;
    if (color) shd.color = color;
    if (pattern) shd.pattern = pattern;
    if (shd.fill || shd.color || shd.pattern) out.shading = shd;
  }

  const vAlignEl = directChild(tcPr, 'w:vAlign');
  if (vAlignEl) {
    const v = vAlignEl.getAttribute('w:val');
    if (v === 'top' || v === 'center' || v === 'bottom') out.vAlign = v;
  }

  // Sprint 284：`<w:tcBorders>` 條件邊框（OOXML §17.4.66、user 指定「row+border 條件樣式」）
  const bordersEl = directChild(tcPr, 'w:tcBorders');
  if (bordersEl) {
    const borders = parseConditionalCellBorders(bordersEl);
    if (borders) out.borders = borders;
  }

  // 空集合不掛 key（紀律 #21 候選）
  if (!out.shading && !out.vAlign && !out.borders) return undefined;
  return out;
}

/**
 * Sprint 284：解析 `<w:tcBorders>` 為 CellBorders（六側 top/bottom/left/right/insideH/insideV）。
 *
 * 為何在 StyleResolver inline 而非 import TableParser 的 parseCellBorders：
 *   - TableParser 的 parseCellBorders 是 file-local function（未 export）
 *   - 兩處 import 會造成 styles ↔ table 模組循環、複雜度高
 *   - 與 borderShading.parseParagraphBorders 同模式（每模組自有薄封裝、共用 parseBorderDef）
 *
 * 對齊 TableParser.parseCellBorders 邏輯：
 *   - `w:start` 同 `w:left`、`w:end` 同 `w:right`（OOXML 雙向語意對應）
 *   - 全空 → return undefined（不掛 key、紀律 #21）
 */
function parseConditionalCellBorders(el: Element): CellBorders | undefined {
  const out: CellBorders = {};
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType !== 1) continue;  // Element only
    const ch = child as Element;
    const def = parseBorderDef(ch);
    if (!def) continue;
    switch (ch.tagName) {
      case 'w:top': out.top = def; break;
      case 'w:bottom': out.bottom = def; break;
      case 'w:left':
      case 'w:start': out.left = def; break;
      case 'w:right':
      case 'w:end': out.right = def; break;
      case 'w:insideH': out.insideH = def; break;
      case 'w:insideV': out.insideV = def; break;
    }
  }
  if (!out.top && !out.bottom && !out.left && !out.right && !out.insideH && !out.insideV) {
    return undefined;
  }
  return out;
}

/**
 * 段落屬性合併：override 的非 undefined 值覆蓋 base，否則保留 base。
 * 對巢狀物件（indent / spacing / borders / shading）做淺合併（per-key 覆寫）。
 */
function mergePProps(
  base: ParagraphProps | undefined,
  override: ParagraphProps,
): ParagraphProps {
  const out: ParagraphProps = { ...(base ?? {}) };
  for (const key of Object.keys(override) as (keyof ParagraphProps)[]) {
    const v = override[key];
    if (v === undefined) continue;
    if (key === 'indent' || key === 'spacing' || key === 'borders' || key === 'shading') {
      // 巢狀物件 per-key 合併
      const baseSub = (base?.[key] ?? {}) as Record<string, unknown>;
      const overSub = v as Record<string, unknown>;
      (out[key] as unknown) = { ...baseSub, ...overSub };
    } else {
      (out[key] as unknown) = v;
    }
  }
  return out;
}

/**
 * Run 屬性合併：純扁平，override 值覆蓋 base。
 */
function mergeRProps(
  base: RunProps | undefined,
  override: RunProps,
): RunProps {
  const out: RunProps = { ...(base ?? {}) };
  for (const key of Object.keys(override) as (keyof RunProps)[]) {
    const v = override[key];
    if (v === undefined) continue;
    (out[key] as unknown) = v;
  }
  return out;
}

// ── 共用工具 ──────────────────────────────────────────────────────────────────

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

function directChild(el: Element | undefined, tagName: string): Element | undefined {
  for (const child of directChildren(el)) {
    if (child.tagName === tagName) return child;
  }
  return undefined;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'StyleResolver: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`StyleResolver: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
