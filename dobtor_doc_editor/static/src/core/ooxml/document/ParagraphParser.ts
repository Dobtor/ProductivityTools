/**
 * ParagraphParser — 解析 <w:p>（段落）與內部 <w:r>（Run）
 *
 * 處理範圍（Sprint 1）：
 *   - w:pPr 段落屬性：jc, ind, spacing, pStyle, numPr, keepNext, pageBreakBefore
 *   - w:rPr Run 屬性：rFonts, sz, b, i, u, strike, color, highlight, vertAlign
 *   - w:t 文字（含 xml:space="preserve" 保留空白）
 *   - w:br type="line|page|column" → BreakNode
 *   - w:tab → 暫時當文字 "\t"
 *   - w:fldSimple instr="..." → FieldNode
 *
 * 設計原則：
 *   - 用 getElementsByTagName(qualifiedName) 而非 getElementsByTagNameNS
 *     （happy-dom 對預設命名空間 NS 查詢有缺陷；此 walker 全環境一致）
 *   - 只處理「直接子節點」，不遞迴尋找（OOXML 結構非 free-form HTML）
 *   - 樣式繼承鏈交給 StyleResolver 在 Sprint 2 處理；本 Parser 只解 in-line 屬性
 *
 * Sprint 1 issue #4 + #5 + #6
 */

import { twipToPt, halfPointToPt } from '../units/units';
import { DrawingParser } from '../drawing/DrawingParser';
import { effectiveChildren } from '../utils/dom';
import { resolveColorElement } from '../styles/colorResolver';
import { parseParagraphBorders, parseShading } from '../styles/borderShading';
import { parseOmmlChildren } from '../omml';
import type { ThemeMap } from '../styles/ThemeResolver';
import type {
  Alignment,
  BreakNode,
  FieldNode,
  HyperlinkInfo,
  InlineNode,
  LineSpacingRule,
  MathNode,
  ParagraphNode,
  ParagraphProps,
  Pt,
  RubyNode,
  RubyProps,
  RunNode,
  RunProps,
  RunRevision,
  Underline,
  VertAlign,
} from '../ast/types';

const drawingParser = new DrawingParser();

/**
 * Sprint 38：module-level「目前正在解析的 ParagraphParser 實例」reference。
 *
 * 由 ParagraphParser.parse() 在入口處 push、出口處 pop，讓 module-level 函式
 * （parseRun）可以回呼到目前實例（保留 relsLookup / themeMap 等狀態）。
 *
 * 用於 anchor text box (`<wp:anchor><wps:wsp><wps:txbx><w:txbxContent>`) 遞迴解析
 * 內部 `<w:p>`：DrawingParser.parse 接受 paragraphFactory callback。
 */
let currentParagraphParser: ParagraphParser | null = null;

/**
 * Module-scoped ThemeMap，由 setThemeMapForParser() / ParagraphParser.setThemeMap 賦值。
 * parseRunProps / parseParagraphProps 為 named export（不在 class），
 * 此中介變數允許 module-level 函式存取 ThemeMap 而不需重整 API。
 *
 * 對外 named export `setThemeMapForParser` 讓 StyleResolver、test 等其他位置也能直接設定。
 */
let themeMapForParser: ThemeMap | null = null;

export function setThemeMapForParser(theme: ThemeMap | null): void {
  themeMapForParser = theme;
}

/**
 * 把 rId 解析為 External URL 的查詢函式介面。
 *
 * 由 OoxmlParser 在 parse() 時把 mainDoc 的 rels 轉成此介面注入 ParagraphParser，
 * 解析 hyperlink 時即可從 rId 取得實際 URL。
 *
 * 不傳時 hyperlink 仍會解析（rId / anchor / tooltip 會記錄），只是 url 為空。
 */
export type RelsLookup = (rId: string) => string | undefined;

// ── 對外 ──────────────────────────────────────────────────────────────────────

export class ParagraphParser {
  /**
   * 由外部注入的 rId → URL 查詢函式（hyperlink 解析用）。
   *
   * OoxmlParser orchestrator 會在 parse() 開始時設定一次。
   * 若未設定，hyperlink 仍會解析 rId/anchor/tooltip，但 url 會留空。
   */
  private relsLookup?: RelsLookup;

  /**
   * 注入 rels 查詢函式。
   *
   * @example
   *   parser.setRelsLookup((rId) => pkg.relationships.get('word/document.xml')?.get(rId)
   *     ?.targetMode === 'External' ? rels.get(rId).target : undefined);
   */
  setRelsLookup(fn: RelsLookup | undefined): void {
    this.relsLookup = fn;
  }

  /**
   * Phase 4.1：設定 ThemeMap（給 parseRunProps / parseParagraphProps 用以解 themeColor）
   *
   * parseRunProps 是 module-level named export（Phase B+ ADR-008.4），無法直接
   * 從 class state 讀；所以用 module-scoped variable themeMapForParser 中介，
   * 由此 setter 賦值。
   */
  setThemeMap(theme: ThemeMap | null): void {
    setThemeMapForParser(theme);
  }

  /**
   * 解析單一 <w:p> Element 為 ParagraphNode。
   * @param p w:p 元素（已是 DOM Element）
   */
  parse(p: Element): ParagraphNode {
    // Sprint 38：把自己 push 到 module-level current 變數，讓 parseRun 在處理
    // `<w:drawing>` 時能回呼到本實例（保留 relsLookup / themeMap 狀態）。
    // 用 try/finally 確保 nested 呼叫 ( anchor text box 內 paragraph) 正確 push/pop。
    const prevParser = currentParagraphParser;
    currentParagraphParser = this;
    try {
      return this._parseInternal(p);
    } finally {
      currentParagraphParser = prevParser;
    }
  }

  private _parseInternal(p: Element): ParagraphNode {
    const pPrEl = directChild(p, 'w:pPr');
    const props = pPrEl ? parseParagraphProps(pPrEl) : {};
    const styleId = pPrEl
      ? attr(directChild(pPrEl, 'w:pStyle'), 'w:val')
      : undefined;

    const runs: InlineNode[] = [];

    // Sprint 123：複式 field 跨多 w:r 的 state machine。
    // OOXML §17.16.1.7 fldChar：begin → [instrText...] → separate → [w:t...] → end
    // 三段可分屬不同 w:r、必須在 paragraph 層收集。
    // - mode='instr'：收集 instrText 串到 instruction
    // - mode='cached'：收集 w:t 串到 cachedValue
    // - 嵌套不支援（規畫書 §1.9 未列）；遇 nested begin 不嘗試處理、視為 unknown
    let fieldMode: 'instr' | 'cached' | null = null;
    let fieldInstr = '';
    let fieldCached = '';
    const emitField = (): void => {
      if (fieldMode === null && fieldInstr === '' && fieldCached === '') return;
      const node: FieldNode = {
        type: 'field',
        instruction: fieldInstr.trim(),
        fieldType: classifyFieldType(fieldInstr),
      };
      if (fieldCached) node.cachedValue = fieldCached;
      runs.push(node);
      fieldMode = null;
      fieldInstr = '';
      fieldCached = '';
    };

    // Sprint 125：bookmark 名稱收集（段落直屬 + run 內含）
    // ECMA-376 §17.13.6：`<w:bookmarkStart w:id="N" w:name="...">` / `<w:bookmarkEnd w:id="N"/>`
    // 不影響 render（純錨點），但需 capture name 供未來 hyperlink anchor 反查、PDF 內部跳轉。
    const bookmarkNames = new Set<string>();
    // Sprint 177：此段落引用的註解 id（`<w:commentReference w:id>` + `<w:commentRangeStart w:id>`）
    const commentIds = new Set<number>();
    // Sprint 179（Phase 5.1 OMML）：此段落內的數學公式（capture-only、行內 + display）
    const mathNodes: MathNode[] = [];
    // 掃單一 w:r 的子元素、收集 bookmark 名稱（Sprint 125）與 commentReference id（Sprint 177）
    const collectRunAnchors = (r: Element): void => {
      for (const c of directChildren(r)) {
        if (c.tagName === 'w:bookmarkStart') {
          const name = c.getAttribute('w:name');
          if (name) bookmarkNames.add(name);
        } else if (c.tagName === 'w:commentReference') {
          const id = parseInt(c.getAttribute('w:id') ?? '', 10);
          if (Number.isFinite(id)) commentIds.add(id);
        }
        // bookmarkEnd 不帶 name、不收集
      }
    };

    for (const child of effectiveChildren(p)) {
      switch (child.tagName) {
        case 'w:r': {
          // Sprint 125：先收集 run 內 bookmark（即使後續走 field path）
          collectRunAnchors(child);
          // Sprint 123：field state machine 入口
          //   - 已在 field 模式 → 全交給 consumeRunIntoField（含 separate / end 切換）
          //   - 未在 field 模式但 r 內含 fldChar begin → 同樣交給 consumeRunIntoField
          //     （consume 內部會 setMode('instr') 並接後續 instrText / 切換信號）
          const inField = fieldMode !== null;
          const beginFound = !inField && detectFieldBegin(child);
          if (inField || beginFound) {
            consumeRunIntoField(child, () => fieldMode, (m) => { fieldMode = m; }, (s) => { fieldInstr += s; }, (s) => { fieldCached += s; }, emitField);
            break;
          }
          for (const node of parseRun(child)) runs.push(node);
          break;
        }
        case 'w:fldSimple':
          runs.push(parseFldSimple(child));
          break;
        case 'w:hyperlink': {
          const linkInfo = parseHyperlinkInfo(child, this.relsLookup);
          // hyperlink 內含 w:r，視同包裹 — 展平 runs 並標記 hyperlink 資訊
          for (const r of effectiveChildren(child)) {
            if (r.tagName !== 'w:r') continue;
            collectRunAnchors(r);  // Sprint 125：hyperlink 內 w:r 也掃 bookmark
            for (const node of parseRun(r)) {
              if (linkInfo && node.type === 'run') {
                node.hyperlink = linkInfo;
              }
              runs.push(node);
            }
          }
          break;
        }
        case 'w:bookmarkStart': {
          // Sprint 125：段落直屬 bookmarkStart（w:r 同層）
          const name = child.getAttribute('w:name');
          if (name) bookmarkNames.add(name);
          break;
        }
        case 'w:bookmarkEnd':
          // bookmarkEnd 純結尾標記、無 name、無內容、不影響 runs
          break;
        case 'w:commentRangeStart': {
          // Sprint 177：段落直屬註解範圍起點 `<w:commentRangeStart w:id>`
          const id = parseInt(child.getAttribute('w:id') ?? '', 10);
          if (Number.isFinite(id)) commentIds.add(id);
          break;
        }
        case 'w:commentRangeEnd':
          // commentRangeEnd 純結尾標記、id 與 Start 相同、不重複收集
          break;
        case 'w:ins':
        case 'w:del':
        case 'w:moveFrom':
        case 'w:moveTo': {
          // Sprint 174（Phase 5.4 追蹤修訂）：`<w:ins>` 插入 / `<w:del>` 刪除
          // Sprint 290 補（Phase 5.4）：`<w:moveFrom>` / `<w:moveTo>` 移動 來源/目的
          //   四種容器都包裹 `<w:r>`，展平 runs 並標記 revision（author / date / id）。
          //   `<w:del>` / `<w:moveFrom>` 內 run 的文字在 `<w:delText>` —— parseRun 已支援。
          //   Scope-down（紀律 #18）：只處理直接 `<w:r>` 子元素；巢狀 ins/del、
          //   ins/del 內含 hyperlink、段落標記修訂、pPrChange/rPrChange 留後續 sprint。
          const revType =
            child.tagName === 'w:ins' ? 'ins'
              : child.tagName === 'w:del' ? 'del'
                : child.tagName === 'w:moveFrom' ? 'moveFrom'
                  : 'moveTo';
          const revision = parseRevision(child, revType);
          for (const r of effectiveChildren(child)) {
            if (r.tagName !== 'w:r') continue;
            collectRunAnchors(r);
            for (const node of parseRun(r)) {
              if (node.type === 'run') node.revision = revision;
              runs.push(node);
            }
          }
          break;
        }
        case 'm:oMath': {
          // Sprint 179（Phase 5.1 OMML）：段落直屬 `<m:oMath>` = 行內公式。
          //   capture-only：遞迴解 OMML 樹、不解語意、不轉 KaTeX（留 Sprint 180）。
          mathNodes.push({ display: false, omml: parseOmmlChildren(child) });
          break;
        }
        case 'm:oMathPara': {
          // Sprint 179：`<m:oMathPara>` 包裹獨立置中公式（display math）。
          //   可含 `<m:oMathParaPr>` 屬性 + 一或多個 `<m:oMath>`；逐 `<m:oMath>` 收集。
          for (const m of effectiveChildren(child)) {
            if (m.tagName !== 'm:oMath') continue;
            mathNodes.push({ display: true, omml: parseOmmlChildren(m) });
          }
          break;
        }
        // w:pPr 已先處理；其他子節點 (w:proofErr) 暫時忽略
      }
    }

    // 若段落結束時 field 未閉合（malformed docx）、emit 已收集部分為 unknown
    if (fieldMode !== null || fieldInstr !== '' || fieldCached !== '') {
      emitField();
    }

    const node: ParagraphNode = {
      type: 'paragraph',
      props,
      runs,
    };
    if (styleId) node.styleId = styleId;
    // Sprint 125：bookmarks 只有在有內容時才掛 key、避免 AST diff noise
    if (bookmarkNames.size > 0) {
      node.bookmarks = Array.from(bookmarkNames);
    }
    // Sprint 177：commentRefs 同樣只在非空時掛 key（紀律 #21）；升序去重
    if (commentIds.size > 0) {
      node.commentRefs = Array.from(commentIds).sort((a, b) => a - b);
    }
    // Sprint 179：math 只在非空時掛 key（紀律 #21）；capture-only、layout 不消費
    if (mathNodes.length > 0) {
      node.math = mathNodes;
    }
    return node;
  }
}

/**
 * Sprint 174 / 290：解析 `<w:ins>` / `<w:del>` / `<w:moveFrom>` / `<w:moveTo>` 的
 * w:author / w:date / w:id 為 RunRevision。
 *
 * @param el 四種追蹤修訂容器元素之一
 * @param type 'ins' 插入 / 'del' 刪除 / 'moveFrom' 移動來源 / 'moveTo' 移動目的
 */
function parseRevision(el: Element, type: RunRevision['type']): RunRevision {
  const rev: RunRevision = { type };
  const author = el.getAttribute('w:author');
  if (author) rev.author = author;
  const date = el.getAttribute('w:date');
  if (date) rev.date = date;
  const idRaw = el.getAttribute('w:id');
  if (idRaw) {
    const n = parseInt(idRaw, 10);
    if (Number.isFinite(n)) rev.id = n;
  }
  return rev;
}

/**
 * 解析 <w:hyperlink> 的 r:id / w:anchor / w:tooltip 為 HyperlinkInfo。
 *
 * @param el w:hyperlink 元素
 * @param lookup rId → URL 查詢函式（External 連結才回 URL）
 * @returns HyperlinkInfo；若四個欄位皆無則回 undefined
 */
function parseHyperlinkInfo(
  el: Element,
  lookup: RelsLookup | undefined,
): HyperlinkInfo | undefined {
  const rId = el.getAttribute('r:id') ?? el.getAttribute('id') ?? undefined;
  const anchor = el.getAttribute('w:anchor') ?? undefined;
  const tooltip = el.getAttribute('w:tooltip') ?? undefined;
  const url = rId && lookup ? lookup(rId) : undefined;
  // Sprint 126：額外 rels 屬性
  const tgtFrame = el.getAttribute('w:tgtFrame') ?? undefined;
  const docLocation = el.getAttribute('w:docLocation') ?? undefined;
  const historyRaw = el.getAttribute('w:history');
  // OOXML 布林：'1' / 'true' → true、'0' / 'false' → false、缺則 undefined
  let history: boolean | undefined;
  if (historyRaw === '1' || historyRaw === 'true') history = true;
  else if (historyRaw === '0' || historyRaw === 'false') history = false;

  const info: HyperlinkInfo = {};
  if (rId) info.rId = rId;
  if (url) info.url = url;
  if (anchor) info.anchor = anchor;
  if (tooltip) info.tooltip = tooltip;
  if (tgtFrame) info.tgtFrame = tgtFrame;
  if (history !== undefined) info.history = history;
  if (docLocation) info.docLocation = docLocation;
  // 紀律 #21 候選遵守：空集合不掛 key、只在有值時 set
  return Object.keys(info).length > 0 ? info : undefined;
}

// ── w:pPr ─────────────────────────────────────────────────────────────────────

/**
 * 解析 <w:pPr> 為 ParagraphProps。對外公開供 StyleResolver 共用同一份邏輯。
 *
 * @public 給 StyleResolver / SectionParser 在解析 styles.xml / sectPr 時重用
 */
export function parseParagraphProps(pPr: Element): ParagraphProps {
  const props: ParagraphProps = {};

  const jc = attr(directChild(pPr, 'w:jc'), 'w:val');
  if (jc) {
    const a = mapAlignment(jc);
    if (a) props.alignment = a;
  }

  const indEl = directChild(pPr, 'w:ind');
  if (indEl) {
    const indent: ParagraphProps['indent'] = {};
    const left = attrTwip(indEl, 'w:left') ?? attrTwip(indEl, 'w:start');
    const right = attrTwip(indEl, 'w:right') ?? attrTwip(indEl, 'w:end');
    const firstLine = attrTwip(indEl, 'w:firstLine');
    const hanging = attrTwip(indEl, 'w:hanging');
    if (left !== undefined) indent.left = left;
    if (right !== undefined) indent.right = right;
    if (firstLine !== undefined) indent.firstLine = firstLine;
    if (hanging !== undefined) indent.hanging = hanging;
    if (Object.keys(indent).length > 0) props.indent = indent;
  }

  const spEl = directChild(pPr, 'w:spacing');
  if (spEl) {
    const spacing: ParagraphProps['spacing'] = {};
    const before = attrTwip(spEl, 'w:before');
    const after = attrTwip(spEl, 'w:after');
    if (before !== undefined) spacing.before = before;
    if (after !== undefined) spacing.after = after;

    const lineRaw = spEl.getAttribute('w:line');
    const ruleRaw = spEl.getAttribute('w:lineRule');
    if (lineRaw) {
      const line = parseInt(lineRaw, 10);
      if (Number.isFinite(line)) {
        const rule = mapLineSpacingRule(ruleRaw);
        // auto 規則用 240 分母（Word 慣例）；其餘 rule 與 exact/atLeast 用 twip
        const value: Pt =
          rule === 'auto' ? line / 240 : twipToPt(line);
        spacing.line = { rule, value };
      }
    }
    if (Object.keys(spacing).length > 0) props.spacing = spacing;
  }

  const numPrEl = directChild(pPr, 'w:numPr');
  if (numPrEl) {
    const ilvlVal = attr(directChild(numPrEl, 'w:ilvl'), 'w:val');
    const numIdVal = attr(directChild(numPrEl, 'w:numId'), 'w:val');
    if (ilvlVal !== undefined) {
      const n = parseInt(ilvlVal, 10);
      if (Number.isFinite(n)) props.ilvl = n;
    }
    if (numIdVal !== undefined) {
      const n = parseInt(numIdVal, 10);
      if (Number.isFinite(n)) props.numId = n;
    }
  }

  if (boolFlag(directChild(pPr, 'w:keepNext'))) props.keepNext = true;
  if (boolFlag(directChild(pPr, 'w:keepLines'))) props.keepLines = true;
  if (boolFlag(directChild(pPr, 'w:pageBreakBefore'))) props.pageBreakBefore = true;

  // Sprint 133: w:pBdr — 段落邊框（top / bottom / left / right、between / bar defer）
  const pBdrEl = directChild(pPr, 'w:pBdr');
  if (pBdrEl) {
    const borders = parseParagraphBorders(pBdrEl);
    if (borders) props.borders = borders;
  }

  // Sprint 133: w:shd — 段落底色 / 圖案
  const shdEl = directChild(pPr, 'w:shd');
  if (shdEl) {
    const shading = parseShading(shdEl);
    if (shading.fill || shading.color || shading.pattern) {
      props.shading = shading;
    }
  }

  // Sprint 134: w:textAlignment — 行內垂直對齊（OOXML §17.3.1.36）
  const textAlignEl = directChild(pPr, 'w:textAlignment');
  if (textAlignEl) {
    const v = textAlignEl.getAttribute('w:val');
    if (v === 'auto' || v === 'top' || v === 'center' || v === 'baseline' || v === 'bottom') {
      props.textAlignment = v;
    }
  }

  // Sprint 134: w:framePr — 段落框基礎屬性（OOXML §17.3.1.11）
  const framePrEl = directChild(pPr, 'w:framePr');
  if (framePrEl) {
    const frame = parseFramePr(framePrEl);
    if (frame) props.framePr = frame;
  }

  // Sprint 29：w:snapToGrid — 預設 true（OOXML §17.3.1.32），val="0" 顯式關閉
  const snapEl = directChild(pPr, 'w:snapToGrid');
  if (snapEl) {
    const v = snapEl.getAttribute('w:val');
    if (v === '0' || v === 'false') props.snapToGrid = false;
  }

  // w:tabs — tab stop 定義
  const tabsEl = directChild(pPr, 'w:tabs');
  if (tabsEl) {
    const tabs: NonNullable<ParagraphProps['tabs']> = [];
    for (const child of directChildren(tabsEl)) {
      if (child.tagName !== 'w:tab') continue;
      // w:val 可為 left / right / center / decimal / bar / num / clear / start / end
      const valRaw = child.getAttribute('w:val');
      // 'clear' 表示移除繼承的 tab stop，跳過記錄
      if (valRaw === 'clear') continue;
      let align: NonNullable<ParagraphProps['tabs']>[number]['align'] = 'left';
      if (valRaw === 'right' || valRaw === 'end') align = 'right';
      else if (valRaw === 'center') align = 'center';
      else if (valRaw === 'decimal') align = 'decimal';
      const posRaw = child.getAttribute('w:pos');
      if (posRaw === null) continue;
      const posTwip = parseInt(posRaw, 10);
      if (!Number.isFinite(posTwip)) continue;
      const tab: NonNullable<ParagraphProps['tabs']>[number] = {
        pos: twipToPt(posTwip),
        align,
      };
      const leader = child.getAttribute('w:leader');
      if (leader) tab.leader = leader;
      tabs.push(tab);
    }
    if (tabs.length > 0) {
      // 依 pos 升序排序（OOXML 不保證寫入順序）
      tabs.sort((a, b) => a.pos - b.pos);
      props.tabs = tabs;
    }
  }

  // Sprint 293：<w:pPrChange> 段落屬性修訂（capture-only）
  const pPrChangeEl = directChild(pPr, 'w:pPrChange');
  if (pPrChangeEl) {
    const meta = parseTrackChangeAttrs(pPrChangeEl);
    if (meta) props.pPrChange = meta;
  }

  return props;
}

/**
 * Sprint 293：解析 w:pPrChange / w:rPrChange / w:cellIns / w:cellDel / w:cellMerge
 * 的 author/date/id 屬性為 TrackChangeMeta。
 *
 * 任何屬性都有值 → 回 meta；全缺 → 回 {} 仍視為有效標記（OOXML 規範允許）。
 */
function parseTrackChangeAttrs(el: Element): { author?: string; date?: string; id?: number } | undefined {
  const meta: { author?: string; date?: string; id?: number } = {};
  const author = el.getAttribute('w:author');
  if (author) meta.author = author;
  const date = el.getAttribute('w:date');
  if (date) meta.date = date;
  const idRaw = el.getAttribute('w:id');
  if (idRaw) {
    const n = parseInt(idRaw, 10);
    if (Number.isFinite(n)) meta.id = n;
  }
  return meta;
}

// ── Sprint 134：w:framePr 段落框基礎屬性解析 ────────────────────────────────

/**
 * 解析 `<w:framePr/>` 為 ParagraphProps.framePr 子集（OOXML §17.3.1.11）。
 *
 * Word 用此元素標示「位置與大小固定的浮動段落」（drop cap / 邊欄注釋）。
 * 當前 capture 主流屬性、進階（dropCap / lines / anchorLock）defer。
 *
 * 缺所有屬性回 undefined（紀律 #21）。
 */
function parseFramePr(el: Element): NonNullable<ParagraphProps['framePr']> | undefined {
  const out: NonNullable<ParagraphProps['framePr']> = {};

  const w = attrTwip(el, 'w:w');
  if (w !== undefined) out.width = w;
  const h = attrTwip(el, 'w:h');
  if (h !== undefined) out.height = h;
  const hRuleRaw = el.getAttribute('w:hRule');
  if (hRuleRaw === 'auto' || hRuleRaw === 'atLeast' || hRuleRaw === 'exact') {
    out.hRule = hRuleRaw;
  }
  const hSpace = attrTwip(el, 'w:hSpace');
  if (hSpace !== undefined) out.hSpace = hSpace;
  const vSpace = attrTwip(el, 'w:vSpace');
  if (vSpace !== undefined) out.vSpace = vSpace;

  const wrapRaw = el.getAttribute('w:wrap');
  if (
    wrapRaw === 'around' || wrapRaw === 'notBeside' || wrapRaw === 'through' ||
    wrapRaw === 'tight' || wrapRaw === 'none'
  ) {
    out.wrap = wrapRaw;
  }

  const hAnchorRaw = el.getAttribute('w:hAnchor');
  if (hAnchorRaw === 'margin' || hAnchorRaw === 'page' || hAnchorRaw === 'text') {
    out.hAnchor = hAnchorRaw;
  }
  const vAnchorRaw = el.getAttribute('w:vAnchor');
  if (vAnchorRaw === 'margin' || vAnchorRaw === 'page' || vAnchorRaw === 'text') {
    out.vAnchor = vAnchorRaw;
  }

  const xAlignRaw = el.getAttribute('w:xAlign');
  if (
    xAlignRaw === 'left' || xAlignRaw === 'center' || xAlignRaw === 'right' ||
    xAlignRaw === 'inside' || xAlignRaw === 'outside'
  ) {
    out.xAlign = xAlignRaw;
  }
  const yAlignRaw = el.getAttribute('w:yAlign');
  if (
    yAlignRaw === 'top' || yAlignRaw === 'center' || yAlignRaw === 'bottom' ||
    yAlignRaw === 'inside' || yAlignRaw === 'outside' || yAlignRaw === 'inline'
  ) {
    out.yAlign = yAlignRaw;
  }

  const x = attrTwip(el, 'w:x');
  if (x !== undefined) out.x = x;
  const y = attrTwip(el, 'w:y');
  if (y !== undefined) out.y = y;

  if (Object.keys(out).length === 0) return undefined;
  return out;
}

// ── w:r → RunNode[]（單一 run 可能因 w:br 等切多筆） ─────────────────────────

function parseRun(r: Element): InlineNode[] {
  const rPrEl = directChild(r, 'w:rPr');
  const baseProps = rPrEl ? parseRunProps(rPrEl) : {};
  const out: InlineNode[] = [];
  let textBuf = '';

  const flushText = (): void => {
    if (textBuf.length === 0) return;
    out.push({ type: 'run', text: textBuf, props: { ...baseProps } });
    textBuf = '';
  };

  // 用 effectiveChildren 展開 mc:AlternateContent（Run 內 drawing 常被它包）
  for (const child of effectiveChildren(r)) {
    switch (child.tagName) {
      case 'w:t':
      // Sprint 174：`<w:delText>`（`<w:del>` 內刪除文字）與 `<w:t>` 同樣讀取 textContent
      case 'w:delText': {
        // xml:space="preserve" → 保留前後空白
        // 注意：DOM 對缺省屬性取出可能是 null，不影響 textContent 讀取
        textBuf += child.textContent ?? '';
        break;
      }
      case 'w:br': {
        flushText();
        const t = child.getAttribute('w:type');
        const breakType: BreakNode['breakType'] =
          t === 'page' ? 'page' : t === 'column' ? 'column' : 'line';
        out.push({ type: 'break', breakType });
        break;
      }
      case 'w:tab':
        textBuf += '\t';
        break;
      case 'w:noBreakHyphen':
        textBuf += '‑'; // non-breaking hyphen
        break;
      case 'w:softHyphen':
        textBuf += '­'; // soft hyphen
        break;
      case 'w:cr':
        textBuf += '\n';
        break;
      case 'w:drawing': {
        flushText();
        // Sprint 38：透過 module-level currentParagraphParser 提供 paragraphFactory，
        // 讓 DrawingParser 解析 anchor text box (`<wps:txbx>` 內 `<w:p>`) 遞迴回到本實例
        const activeParser = currentParagraphParser;
        const factory = activeParser
          ? (el: Element) => activeParser.parse(el)
          : undefined;
        out.push(drawingParser.parse(child, factory));
        break;
      }
      case 'w:object': {
        // Sprint 122 — OLE 物件降級渲染（ECMA-376 §17.3.3.19）
        // <w:object> 包 <v:shape>（VML preview）+ <o:OLEObject ProgID="..."/>
        // 我們不嘗試渲染實際 OLE blob、emit italic 文字 placeholder 讓使用者
        // 至少知道此處原本有嵌入物件、配合 ProgID / alt 顯示類型。
        flushText();
        const placeholder = buildOleFallbackText(child);
        if (placeholder) {
          out.push({
            type: 'run',
            text: placeholder,
            props: { ...baseProps, italic: true },
          });
        }
        break;
      }
      case 'w:pict': {
        // Sprint 122 — VML 舊圖 placeholder（ECMA-376 §17.3.3.21、Word 97-2003 相容）
        // <w:pict> 內含 <v:shape>、可能有 <o:OLEObject>（圖象化的舊版 OLE）。
        // 同樣 emit italic placeholder、若內含 OLEObject 走 OLE 文案、否則 VML 文案。
        flushText();
        const placeholder = buildPictFallbackText(child);
        if (placeholder) {
          out.push({
            type: 'run',
            text: placeholder,
            props: { ...baseProps, italic: true },
          });
        }
        break;
      }
      // w:rPr 已先處理；w:fldChar 暫不處理（Sprint 123 候選）
      // Sprint 242 — Phase 1 optional 第二批升級：footnoteReference / endnoteReference
      case 'w:footnoteReference':
      case 'w:endnoteReference': {
        flushText();
        const idAttr = child.getAttribute('w:id');
        if (idAttr !== null) {
          const id = parseInt(idAttr, 10);
          if (!Number.isNaN(id)) {
            out.push({
              type: 'footnoteRef',
              noteType: child.tagName === 'w:footnoteReference' ? 'footnote' : 'endnote',
              id,
            });
          }
        }
        break;
      }
      // Sprint 282 — Phase 1 optional bucket 第 1 項：`<w:ruby>` 注音/振假名（§17.3.3.25）
      case 'w:ruby': {
        flushText();
        const ruby = parseRubyNode(child);
        if (ruby) out.push(ruby);
        break;
      }
    }
  }

  flushText();
  return out;
}

// ── w:rPr ─────────────────────────────────────────────────────────────────────

/**
 * 解析 <w:rPr> 為 RunProps。對外公開供 StyleResolver 共用同一份邏輯。
 *
 * @public 給 StyleResolver 解析 styles.xml 時重用
 */
export function parseRunProps(rPr: Element): RunProps {
  const props: RunProps = {};

  const fontsEl = directChild(rPr, 'w:rFonts');
  if (fontsEl) {
    const ascii = fontsEl.getAttribute('w:ascii');
    const east = fontsEl.getAttribute('w:eastAsia');
    const hAnsi = fontsEl.getAttribute('w:hAnsi');
    const cs = fontsEl.getAttribute('w:cs');
    if (ascii) props.fontFamily = ascii;
    if (east) props.fontFamilyEastAsia = east;
    if (hAnsi) props.fontFamilyHAnsi = hAnsi;
    if (cs) props.fontFamilyCs = cs;
  }

  // w:sz 與 w:szCs 都是 half-point；CS 給 complex script。先用 w:sz。
  const szVal = attr(directChild(rPr, 'w:sz'), 'w:val');
  if (szVal !== undefined) {
    const n = parseInt(szVal, 10);
    if (Number.isFinite(n)) props.fontSize = halfPointToPt(n);
  }

  if (boolFlag(directChild(rPr, 'w:b'))) props.bold = true;
  if (boolFlag(directChild(rPr, 'w:i'))) props.italic = true;
  if (boolFlag(directChild(rPr, 'w:strike'))) props.strike = true;
  if (boolFlag(directChild(rPr, 'w:dstrike'))) props.dstrike = true;

  const uVal = attr(directChild(rPr, 'w:u'), 'w:val');
  if (uVal) props.underline = uVal as Underline;

  // 顏色：優先 w:val（顯式 hex），再嘗試 themeColor + tint/shade（透過 ThemeMap）
  const colorEl = directChild(rPr, 'w:color');
  const resolvedColor = resolveColorElement(colorEl, themeMapForParser);
  if (resolvedColor) props.color = resolvedColor;

  // w:highlight 用具名色（yellow/cyan/...）；w:shd val + w:fill 才是 hex shading
  const highlight = attr(directChild(rPr, 'w:highlight'), 'w:val');
  if (highlight) props.highlight = highlight;

  const vert = attr(directChild(rPr, 'w:vertAlign'), 'w:val');
  if (vert === 'superscript' || vert === 'subscript' || vert === 'baseline') {
    props.vertAlign = vert as VertAlign;
  }

  const spacing = attr(directChild(rPr, 'w:spacing'), 'w:val');
  if (spacing !== undefined) {
    const n = parseInt(spacing, 10);
    if (Number.isFinite(n)) props.spacing = twipToPt(n);
  }

  const lang = attr(directChild(rPr, 'w:lang'), 'w:val');
  if (lang) props.lang = lang;

  // Sprint 293：<w:rPrChange> run 屬性修訂（capture-only、不解 old rPr 子樹）
  const rPrChangeEl = directChild(rPr, 'w:rPrChange');
  if (rPrChangeEl) {
    const meta = parseTrackChangeAttrs(rPrChangeEl);
    if (meta) props.rPrChange = meta;
  }

  return props;
}

// ── Sprint 122：OLE / VML pict 降級 placeholder ─────────────────────────────

/**
 * Sprint 122 — `<w:object>` placeholder 文字。
 *
 * OOXML §17.3.3.19：`<w:object>` 包 VML `<v:shape>` + `<o:OLEObject>`。
 *   - 嘗試讀 `<o:OLEObject ProgID="Equation.3"/>` → `[嵌入物件: Equation.3]`
 *   - 若有 `<v:shape alt="...">` → 加 alt 補充
 *   - 兩者都缺 → 純 `[嵌入物件]`
 *
 * 設計：getElementsByTagName 不限 namespace 前綴（OOXML 真實 docx 偶見
 *   `<OLEObject>` 無前綴、或 `<v:shape>` 改成 `<vml:shape>`）。
 */
function buildOleFallbackText(objectEl: Element): string {
  let progId = '';
  let alt = '';

  // 寬鬆 walk：對 wildcard tagName endsWith 比對
  // happy-dom / browser 對 namespace 前綴處理不一致、用 walker 統一
  const walk = (root: Element): void => {
    const children = root.childNodes;
    for (let i = 0; i < children.length; i++) {
      const c = children[i];
      if (c.nodeType !== 1) continue;
      const el = c as Element;
      const local = el.localName ?? el.tagName.split(':').pop() ?? '';
      if (!progId && local === 'OLEObject') {
        progId = el.getAttribute('ProgID') ?? '';
      }
      if (!alt && local === 'shape') {
        alt = el.getAttribute('alt') ?? '';
      }
      walk(el);
    }
  };
  walk(objectEl);

  if (progId && alt) return `[嵌入物件: ${progId} — ${alt}]`;
  if (progId) return `[嵌入物件: ${progId}]`;
  if (alt) return `[嵌入物件: ${alt}]`;
  return '[嵌入物件]';
}

/**
 * Sprint 122 — `<w:pict>` placeholder 文字（VML legacy picture）。
 *
 * OOXML §17.3.3.21：Word 97-2003 相容圖片包裝。
 *   - 內含 `<o:OLEObject>` → 走 OLE 文案
 *   - 否則純 VML → `[圖片(VML)]` 或 `[圖片(VML): <alt>]`
 */
function buildPictFallbackText(pictEl: Element): string {
  let hasOle = false;
  let progId = '';
  let alt = '';

  const walk = (root: Element): void => {
    const children = root.childNodes;
    for (let i = 0; i < children.length; i++) {
      const c = children[i];
      if (c.nodeType !== 1) continue;
      const el = c as Element;
      const local = el.localName ?? el.tagName.split(':').pop() ?? '';
      if (local === 'OLEObject') {
        hasOle = true;
        if (!progId) progId = el.getAttribute('ProgID') ?? '';
      }
      if (!alt && local === 'shape') {
        alt = el.getAttribute('alt') ?? '';
      }
      walk(el);
    }
  };
  walk(pictEl);

  if (hasOle) {
    if (progId && alt) return `[嵌入物件: ${progId} — ${alt}]`;
    if (progId) return `[嵌入物件: ${progId}]`;
    if (alt) return `[嵌入物件: ${alt}]`;
    return '[嵌入物件]';
  }

  if (alt) return `[圖片(VML): ${alt}]`;
  return '[圖片(VML)]';
}

// ── Sprint 123：複式 fldChar 跨多 w:r state machine helpers ─────────────────

/**
 * Sprint 123 — 偵測 w:r 內是否含 `<w:fldChar w:fldCharType="begin">`。
 * 用於 paragraph-level state machine 起始判斷（不消費內容）。
 */
function detectFieldBegin(r: Element): boolean {
  for (const child of directChildren(r)) {
    if (child.tagName !== 'w:fldChar') continue;
    if (child.getAttribute('w:fldCharType') === 'begin') return true;
  }
  return false;
}

/**
 * Sprint 123 — 在 field-collection mode 中消費一個 w:r 的內容。
 *
 * w:r 子元素可能含：
 *   - `<w:fldChar w:fldCharType="separate">` → 切換 instr → cached
 *   - `<w:fldChar w:fldCharType="end">` → emit field、結束 mode
 *   - `<w:instrText>` → instr mode 時 append 到 instruction
 *   - `<w:t>` → cached mode 時 append 到 cachedValue（instr mode 時忽略）
 *
 * @returns true 若此 w:r 完全被 field machine 消費；false 表示應 fallthrough 普通處理
 */
function consumeRunIntoField(
  r: Element,
  getMode: () => 'instr' | 'cached' | null,
  setMode: (m: 'instr' | 'cached' | null) => void,
  appendInstr: (s: string) => void,
  appendCached: (s: string) => void,
  emit: () => void,
): boolean {
  // mode 可能在迭代中變動（begin / separate / end），故每個元素都重新讀
  for (const child of directChildren(r)) {
    switch (child.tagName) {
      case 'w:fldChar': {
        const type = child.getAttribute('w:fldCharType');
        if (type === 'begin') {
          // begin 已由 caller 處理（或嵌套：不支援、清空已有累積以 unknown 開新 field）
          if (getMode() !== null) {
            emit(); // 強制 close 前一個（malformed）
          }
          setMode('instr');
        } else if (type === 'separate') {
          if (getMode() !== null) setMode('cached');
        } else if (type === 'end') {
          if (getMode() !== null) emit();
        }
        break;
      }
      case 'w:instrText': {
        if (getMode() === 'instr') appendInstr(child.textContent ?? '');
        break;
      }
      case 'w:t': {
        if (getMode() === 'cached') appendCached(child.textContent ?? '');
        // instr 模式時 w:t 是異常（spec 用 instrText）、忽略
        break;
      }
      // 其他 (w:rPr / w:br 等) field 模式內忽略
    }
  }
  return getMode() !== null;
}

// ── w:fldSimple → FieldNode ──────────────────────────────────────────────────

function parseFldSimple(el: Element): FieldNode {
  const instruction = (el.getAttribute('w:instr') ?? '').trim();
  const fieldType = classifyFieldType(instruction);

  // 快取值：fldSimple 內部的 w:r → w:t 串接
  let cached = '';
  for (const r of directChildren(el)) {
    if (r.tagName !== 'w:r') continue;
    for (const t of directChildren(r)) {
      if (t.tagName === 'w:t') cached += t.textContent ?? '';
    }
  }

  const node: FieldNode = { type: 'field', instruction, fieldType };
  if (cached) node.cachedValue = cached;
  return node;
}

/**
 * Sprint 123 — instruction 字串 → FieldNode['fieldType'] 分類。
 * 第一個非空字 token 轉大寫對映已知集合；未知者回 'unknown'。
 * 共用給 parseFldSimple（簡式）+ 複式 fldChar（同 paragraph 跨多 w:r）。
 */
function classifyFieldType(instruction: string): FieldNode['fieldType'] {
  const firstToken = instruction.trim().split(/\s+/)[0]?.toUpperCase() ?? '';
  const knownTypes = [
    'PAGE', 'NUMPAGES',
    'DATE', 'TIME',
    'AUTHOR', 'FILENAME',
    'SEQ', 'TOC', 'REF', 'HYPERLINK', 'STYLEREF',
  ] as const;
  type Known = (typeof knownTypes)[number];
  return (knownTypes as readonly string[]).includes(firstToken)
    ? (firstToken as Known)
    : 'unknown';
}

// ── 共用工具 ──────────────────────────────────────────────────────────────────

function directChildren(el: Element): Element[] {
  const out: Element[] = [];
  const children = el.childNodes;
  for (let i = 0; i < children.length; i++) {
    const n = children[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

function directChild(el: Element | undefined | null, tagName: string): Element | undefined {
  if (!el) return undefined;
  for (const child of directChildren(el)) {
    if (child.tagName === tagName) return child;
  }
  return undefined;
}

function attr(el: Element | undefined, name: string): string | undefined {
  if (!el) return undefined;
  const v = el.getAttribute(name);
  return v === null ? undefined : v;
}

function attrTwip(el: Element | undefined, name: string): Pt | undefined {
  const v = attr(el, name);
  if (v === undefined) return undefined;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? twipToPt(n) : undefined;
}

/**
 * OOXML 布林屬性慣例：
 *   - 元素存在且無 w:val 屬性 → true
 *   - w:val="0" / "false" → false
 *   - w:val="1" / "true"  → true
 */
function boolFlag(el: Element | undefined): boolean {
  if (!el) return false;
  const v = el.getAttribute('w:val');
  if (v === null) return true;
  return v !== '0' && v.toLowerCase() !== 'false';
}

function mapAlignment(jc: string): Alignment | undefined {
  switch (jc) {
    case 'left':
    case 'start':
      return 'left';
    case 'right':
    case 'end':
      return 'right';
    case 'center':
      return 'center';
    case 'both':
    case 'justify':
      return 'justify';
    case 'distribute':
      return 'distribute';
    default:
      return undefined;
  }
}

function mapLineSpacingRule(rule: string | null): LineSpacingRule {
  if (rule === 'exact') return 'exact';
  if (rule === 'atLeast') return 'atLeast';
  return 'auto';
}

// 對外便捷 export，供 RunNode 型別使用者
export type { RunNode };

// ── Sprint 282 — Phase 1 optional bucket 第 1 項：`<w:ruby>` 注音/振假名 ──────

/**
 * 解析 `<w:ruby>` 元素為 RubyNode（OOXML §17.3.3.25）。
 *
 * 結構：
 *   `<w:ruby>` 直屬 `<w:rubyPr>` + `<w:rt>` + `<w:rubyBase>`；
 *   `<w:rt>` / `<w:rubyBase>` 內各含 `<w:r>` runs。
 *
 * 紀律 #18 scope-down（capture-only、Sprint 145-153 模式）：
 *   - parser 把 ruby 結構讀進 AST、不 render / 不 writer round-trip
 *   - rubyPr 缺漏 → props 整段 undefined（不寫空 object）
 *   - rt / rubyBase 任一無 runs → 仍 emit 節點（caller 自決定）；但兩端皆空 → return undefined
 *
 * @return RubyNode 或 undefined（兩端皆空時、避免污染 AST）
 */
function parseRubyNode(ruby: Element): RubyNode | undefined {
  const rubyPrEl = directChild(ruby, 'w:rubyPr');
  const rtEl = directChild(ruby, 'w:rt');
  const baseEl = directChild(ruby, 'w:rubyBase');

  const annotationRuns: RunNode[] = [];
  if (rtEl) {
    for (const child of effectiveChildren(rtEl)) {
      if (child.tagName !== 'w:r') continue;
      for (const node of parseRun(child)) {
        if (node.type === 'run') annotationRuns.push(node);
      }
    }
  }

  const baseRuns: RunNode[] = [];
  if (baseEl) {
    for (const child of effectiveChildren(baseEl)) {
      if (child.tagName !== 'w:r') continue;
      for (const node of parseRun(child)) {
        if (node.type === 'run') baseRuns.push(node);
      }
    }
  }

  if (annotationRuns.length === 0 && baseRuns.length === 0) return undefined;

  const props = rubyPrEl ? parseRubyProps(rubyPrEl) : undefined;
  const node: RubyNode = { type: 'ruby', annotationRuns, baseRuns };
  if (props !== undefined) node.props = props;
  return node;
}

/** 解析 `<w:rubyPr>` 為 RubyProps；所有子元素皆 optional、無則 undefined。 */
function parseRubyProps(rubyPr: Element): RubyProps | undefined {
  const props: RubyProps = {};

  const alignEl = directChild(rubyPr, 'w:rubyAlign');
  if (alignEl) {
    const v = alignEl.getAttribute('w:val');
    if (v === 'center' || v === 'distributeLetter' || v === 'distributeSpace'
        || v === 'left' || v === 'right' || v === 'rightVertical') {
      props.align = v;
    }
  }

  for (const [tag, key] of [
    ['w:hps', 'hps'],
    ['w:hpsRaise', 'hpsRaise'],
    ['w:hpsBaseText', 'hpsBaseText'],
  ] as const) {
    const el = directChild(rubyPr, tag);
    const raw = el?.getAttribute('w:val');
    if (raw !== null && raw !== undefined) {
      const n = parseInt(raw, 10);
      if (Number.isFinite(n)) (props as Record<string, unknown>)[key] = n;
    }
  }

  const lidEl = directChild(rubyPr, 'w:lid');
  if (lidEl) {
    const v = lidEl.getAttribute('w:val');
    if (v !== null) props.lid = v;
  }

  const dirtyEl = directChild(rubyPr, 'w:dirty');
  if (dirtyEl) {
    const v = dirtyEl.getAttribute('w:val');
    props.dirty = v === '1' || v === 'true' || v === null;  // 預設 1（empty val）→ true
  }

  return Object.keys(props).length > 0 ? props : undefined;
}
