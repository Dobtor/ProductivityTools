/**
 * TableParser — 解析 <w:tbl>
 *
 * 範圍（Phase B.5 完整版）：
 *   - <w:tblGrid> + <w:gridCol w:w="..."> 欄寬定義
 *   - <w:tblPr>：tblW / tblInd / tblBorders / tblLook / tblStyle / jc / tblCellMar
 *   - <w:tr> + <w:trPr>：trHeight (含 hRule) / tblHeader / cantSplit
 *   - <w:tc> + <w:tcPr>：
 *       - tcW（dxa / pct / auto / nil）
 *       - gridSpan、vMerge
 *       - tcBorders（top/bottom/left/right/insideH/insideV）
 *       - shd（fill/color/pattern）
 *       - tcMar（儲存格邊界）
 *       - vAlign（top/center/bottom）
 *       - noWrap、hideMark、textDirection
 *
 * 不在此 Parser 範圍：
 *   - <w:tblStylePr> 條件樣式（15 種：firstRow/lastRow/etc.）— 由 StyleResolver 處理
 *   - Border conflict resolution（ECMA-376 17.4.65）— 由 Layout Engine 處理
 *   - 巢狀表格內容：cell.content 目前限定 ParagraphNode[]（AST 限制）
 *
 * Phase B.6 GridResolver 補完後，rowSpan / isContinuation 的計算交由它做。
 */

import type {
  BlockNode,
  CellBorders,
  CellNode,
  HexColor,
  ParagraphNode,
  Pt,
  RowNode,
  StyleMap,
  TableNode,
  TrackChangeMeta,
} from '../ast/types';
import { DocumentParser } from '../document/DocumentParser';
import { twipToPt } from '../units/units';
import { GridResolver } from './GridResolver';
import { applyTableStyle, parseTblLook } from '../styles/TableStyleApplicator';
import { resolveTableBorders } from './BorderConflictResolver';
import { parseBorderDef, parseShading } from '../styles/borderShading';

/**
 * 內部用：每格的原始 vMerge 資訊。
 *
 * 'restart' = vMerge 區塊起點（anchor cell，繪製內容）
 * 'continue' = vMerge 區塊延續（hidden cell，跳過繪製內容）
 */
type VMergeRaw = 'restart' | 'continue' | undefined;

interface RawCell {
  gridSpan: number;
  vMerge: VMergeRaw;
  width?: Pt;
  /** Sprint 5+：cell.content 改為 BlockNode[]，支援巢狀表格 */
  content: BlockNode[];
  borders?: CellBorders;
  shading?: { fill?: HexColor; color?: HexColor; pattern?: string };
  margins?: { top?: Pt; bottom?: Pt; left?: Pt; right?: Pt };
  vAlign?: 'top' | 'center' | 'bottom';
  noWrap?: boolean;
  fitText?: boolean;
  textDirection?: 'lrTb' | 'tbRl' | 'btLr' | 'lrTbV' | 'tbRlV' | 'tbLrV';
  /** Sprint 293：tracked changes（capture-only） */
  cellIns?: TrackChangeMeta;
  cellDel?: TrackChangeMeta;
  cellMerge?: TrackChangeMeta & { val?: 'vert' | 'rest' | 'cont'; vMerge?: 'cont' | 'rest' };
}

interface RawRow {
  cells: RawCell[];
  height?: Pt;
  heightRule?: 'auto' | 'atLeast' | 'exact';
  isHeader: boolean;
  cantSplit: boolean;
}

export class TableParser {
  private _documentParser?: DocumentParser;
  private gridResolver = new GridResolver();

  /** Phase 4.2：StyleMap 用於 tblStyle 解析 */
  private styleMap: StyleMap | null = null;

  constructor(documentParser?: DocumentParser) {
    if (documentParser) this._documentParser = documentParser;
  }

  private get documentParser(): DocumentParser {
    if (!this._documentParser) {
      this._documentParser = new DocumentParser(this);
    }
    return this._documentParser;
  }

  /**
   * 注入 StyleMap（OoxmlParser orchestrator 在 styleResolver.resolve() 後呼叫）。
   *
   * 用於 parse() 結尾解 tblStyle id 並套用條件樣式。null 時跳過 applyTableStyle。
   */
  setStyleMap(map: StyleMap | null): void {
    this.styleMap = map;
  }

  parse(tbl: Element): TableNode {
    const grid = parseTblGrid(tbl);
    const tblProps = parseTblPr(directChild(tbl, 'w:tblPr'));
    const rawRows = this.parseRows(tbl);

    // Pass 1：cursor 推進 gridCol、標記 isContinuation
    let rows: RowNode[] = rawRows.map((rr) => this.materializeRow(rr));

    // Pass 2：GridResolver 解析 vMerge 鏈 → 設定 anchor.rowSpan
    rows = this.gridResolver.resolve(rows);

    const node: TableNode = {
      type: 'table',
      grid,
      rows,
      props: tblProps.props,
    };
    if (tblProps.styleId) node.styleId = tblProps.styleId;

    // Phase 4.2：套用 tblStyle 條件樣式（StyleResolver 已 collect tblStylePr）
    if (tblProps.styleId && this.styleMap) {
      const styleEntry = this.styleMap.get(tblProps.styleId);
      if (styleEntry) {
        const tblLook = parseTblLook(tblProps.props.look);
        applyTableStyle(node, styleEntry, tblLook);
      }
    }

    // Phase 4.3：邊框衝突解決（ECMA-376 §17.4.65）
    // 把 table.props.borders（含 insideH/V）+ 各 cell own borders 合併成
    // 每 cell 的 effective 4 邊；相鄰 cell 邊界協調避免重疊或漏失。
    resolveTableBorders(node);

    return node;
  }

  // ── row / cell 走訪 ────────────────────────────────────────────────────────

  private parseRows(tbl: Element): RawRow[] {
    const rows: RawRow[] = [];
    for (const child of directChildren(tbl)) {
      if (child.tagName !== 'w:tr') continue;
      rows.push(this.parseRow(child));
    }
    return rows;
  }

  private parseRow(tr: Element): RawRow {
    const cells: RawCell[] = [];
    let height: Pt | undefined;
    let heightRule: RawRow['heightRule'] | undefined;
    let isHeader = false;
    let cantSplit = false;

    const trPr = directChild(tr, 'w:trPr');
    if (trPr) {
      const trHeightEl = directChild(trPr, 'w:trHeight');
      if (trHeightEl) {
        // Sprint 121 — 進階 row height 防禦性解析（ECMA-376 §17.4.81）：
        //   - val 必須是有限非負整數；負值 / NaN 視為缺 val
        //   - hRule 顯式為 'exact' / 'atLeast' / 'auto'；其他值 fallback 'auto'
        //   - val=0 配 hRule=exact 是合法的「零高度行」（Word 真的會渲染塌陷列）
        //   - val=0 配 hRule=auto/缺 不視為「行高 0 的下限」（語意上等同沒給 val）
        //   - hRule=exact / atLeast 沒給有效 val 時、demote heightRule 為 'auto'
        //     （避免下游 TableLayout 走「heightRule==='exact' && height」分支但 height undefined）
        const valRaw = trHeightEl.getAttribute('w:val');
        if (valRaw !== null) {
          const n = parseInt(valRaw, 10);
          if (Number.isFinite(n) && n >= 0) height = twipToPt(n);
        }
        const ruleRaw = trHeightEl.getAttribute('w:hRule');
        if (ruleRaw === 'exact' || ruleRaw === 'atLeast') heightRule = ruleRaw;
        else heightRule = 'auto';
        // val=0 + hRule=auto/缺 → strip height（auto 0 沒下限意義）
        if (height === 0 && heightRule === 'auto') height = undefined;
        // hRule 強約束但無有效 val → demote 'auto' 防 TableLayout 分支不一致
        if ((heightRule === 'exact' || heightRule === 'atLeast') && height === undefined) {
          heightRule = 'auto';
        }
      }
      if (boolFlag(directChild(trPr, 'w:tblHeader'))) isHeader = true;
      if (boolFlag(directChild(trPr, 'w:cantSplit'))) cantSplit = true;
    }

    for (const child of directChildren(tr)) {
      if (child.tagName !== 'w:tc') continue;
      cells.push(this.parseCell(child));
    }

    const out: RawRow = { cells, isHeader, cantSplit };
    if (height !== undefined) out.height = height;
    if (heightRule !== undefined) out.heightRule = heightRule;
    return out;
  }

  private parseCell(tc: Element): RawCell {
    let gridSpan = 1;
    let vMerge: VMergeRaw = undefined;
    let width: Pt | undefined;
    let borders: CellBorders | undefined;
    let shading: RawCell['shading'];
    let margins: RawCell['margins'];
    let vAlign: RawCell['vAlign'];
    let noWrap: boolean | undefined;
    let fitText: boolean | undefined;
    let textDirection: RawCell['textDirection'];
    // Sprint 293：tracked cell changes（capture-only）
    let cellIns: TrackChangeMeta | undefined;
    let cellDel: TrackChangeMeta | undefined;
    let cellMerge: RawCell['cellMerge'];

    const tcPr = directChild(tc, 'w:tcPr');
    if (tcPr) {
      // gridSpan
      const gridSpanVal = attr(directChild(tcPr, 'w:gridSpan'), 'w:val');
      if (gridSpanVal) {
        const n = parseInt(gridSpanVal, 10);
        if (Number.isFinite(n) && n > 0) gridSpan = n;
      }

      // vMerge
      const vMergeEl = directChild(tcPr, 'w:vMerge');
      if (vMergeEl) {
        const valRaw = vMergeEl.getAttribute('w:val');
        vMerge = valRaw === 'restart' ? 'restart' : 'continue';
      }

      // tcW
      const tcW = directChild(tcPr, 'w:tcW');
      if (tcW) {
        const wVal = tcW.getAttribute('w:w');
        const wType = tcW.getAttribute('w:type');
        if (wVal && (wType === 'dxa' || wType === null)) {
          const n = parseInt(wVal, 10);
          if (Number.isFinite(n)) width = twipToPt(n);
        }
        // pct / auto / nil 不轉 pt（width undefined，由 Layout 處理）
      }

      // tcBorders
      const tcBordersEl = directChild(tcPr, 'w:tcBorders');
      if (tcBordersEl) {
        borders = parseCellBorders(tcBordersEl);
      }

      // shd
      const shdEl = directChild(tcPr, 'w:shd');
      if (shdEl) {
        shading = parseShading(shdEl);
      }

      // tcMar
      const tcMarEl = directChild(tcPr, 'w:tcMar');
      if (tcMarEl) {
        margins = parseCellMargins(tcMarEl);
      }

      // vAlign
      const vAlignVal = attr(directChild(tcPr, 'w:vAlign'), 'w:val');
      if (vAlignVal === 'top' || vAlignVal === 'center' || vAlignVal === 'bottom') {
        vAlign = vAlignVal;
      }

      // noWrap / hideMark / fitText
      if (boolFlag(directChild(tcPr, 'w:noWrap'))) noWrap = true;
      if (boolFlag(directChild(tcPr, 'w:tcFitText'))) fitText = true;

      // textDirection（OOXML §17.18.93 ST_TextDirection）
      // Sprint 34：擴充接受 V-suffix variants（glyph 旋轉式垂直文字，中文表單常用）
      const tdVal = attr(directChild(tcPr, 'w:textDirection'), 'w:val');
      if (
        tdVal === 'lrTb' || tdVal === 'tbRl' || tdVal === 'btLr'
        || tdVal === 'lrTbV' || tdVal === 'tbRlV' || tdVal === 'tbLrV'
      ) {
        textDirection = tdVal;
      }

      // Sprint 293：cellIns / cellDel / cellMerge 追蹤修訂 capture-only
      const cellInsEl = directChild(tcPr, 'w:cellIns');
      if (cellInsEl) cellIns = parseTrackChangeAttrsTbl(cellInsEl);
      const cellDelEl = directChild(tcPr, 'w:cellDel');
      if (cellDelEl) cellDel = parseTrackChangeAttrsTbl(cellDelEl);
      const cellMergeEl = directChild(tcPr, 'w:cellMerge');
      if (cellMergeEl) {
        const meta = parseTrackChangeAttrsTbl(cellMergeEl);
        const valRaw = cellMergeEl.getAttribute('w:val');
        const vMergeRaw = cellMergeEl.getAttribute('w:vMerge');
        cellMerge = { ...meta };
        if (valRaw === 'vert' || valRaw === 'rest' || valRaw === 'cont') cellMerge.val = valRaw;
        if (vMergeRaw === 'cont' || vMergeRaw === 'rest') cellMerge.vMerge = vMergeRaw;
      }
    }

    // 內容：reuse DocumentParser.parseBodyContent；
    // Sprint 5 起 cell.content = BlockNode[]，支援巢狀表格（不再 filter 掉 TableNode）。
    const content = this.documentParser.parseBodyContent(tc);

    const out: RawCell = { gridSpan, vMerge, content };
    if (width !== undefined) out.width = width;
    if (borders) out.borders = borders;
    if (shading) out.shading = shading;
    if (margins) out.margins = margins;
    if (vAlign) out.vAlign = vAlign;
    if (noWrap) out.noWrap = noWrap;
    if (fitText) out.fitText = fitText;
    if (textDirection) out.textDirection = textDirection;
    // Sprint 293：tracked changes（cellIns/Del/Merge）只在掛上時 propagate
    if (cellIns) out.cellIns = cellIns;
    if (cellDel) out.cellDel = cellDel;
    if (cellMerge) out.cellMerge = cellMerge;
    return out;
  }

  // ── raw → AST ─────────────────────────────────────────────────────────────

  private materializeRow(rr: RawRow): RowNode {
    let cursor = 0;
    const cells: CellNode[] = rr.cells.map((rc) => {
      const props: CellNode['props'] = {};
      if (rc.width !== undefined) props.width = rc.width;
      if (rc.borders) props.borders = rc.borders;
      if (rc.shading) props.shading = rc.shading;
      if (rc.margins) props.margins = rc.margins;
      if (rc.vAlign) props.vAlign = rc.vAlign;
      if (rc.noWrap) props.noWrap = rc.noWrap;
      if (rc.fitText) props.fitText = rc.fitText;
      if (rc.textDirection) props.textDirection = rc.textDirection;
      // Sprint 293：tracked cell changes
      if (rc.cellIns) props.cellIns = rc.cellIns;
      if (rc.cellDel) props.cellDel = rc.cellDel;
      if (rc.cellMerge) props.cellMerge = rc.cellMerge;

      const cell: CellNode = {
        type: 'cell',
        gridCol: cursor,
        gridSpan: rc.gridSpan,
        rowSpan: 1, // Phase B.6 GridResolver 補
        isContinuation: rc.vMerge === 'continue',
        content: rc.content,
        props,
      };
      cursor += rc.gridSpan;
      return cell;
    });

    const props: RowNode['props'] = {
      isHeader: rr.isHeader,
      cantSplit: rr.cantSplit,
    };
    if (rr.height !== undefined) props.height = rr.height;
    if (rr.heightRule !== undefined) props.heightRule = rr.heightRule;

    return { type: 'row', cells, props };
  }
}

// ── <w:tblGrid> ───────────────────────────────────────────────────────────────

function parseTblGrid(tbl: Element): Pt[] {
  const tblGrid = directChild(tbl, 'w:tblGrid');
  if (!tblGrid) return [];
  const widths: Pt[] = [];
  for (const child of directChildren(tblGrid)) {
    if (child.tagName !== 'w:gridCol') continue;
    const w = child.getAttribute('w:w');
    if (w === null) continue;
    const n = parseInt(w, 10);
    widths.push(Number.isFinite(n) ? twipToPt(n) : 0);
  }
  return widths;
}

// ── <w:tblPr> ─────────────────────────────────────────────────────────────────

interface TblPrParsed {
  props: TableNode['props'];
  styleId?: string;
}

function parseTblPr(tblPr: Element | undefined): TblPrParsed {
  const props: TableNode['props'] = {};
  let styleId: string | undefined;

  if (!tblPr) return { props };

  // tblStyle
  const tblStyleVal = attr(directChild(tblPr, 'w:tblStyle'), 'w:val');
  if (tblStyleVal) styleId = tblStyleVal;

  // tblW
  const tblW = directChild(tblPr, 'w:tblW');
  if (tblW) {
    const wVal = tblW.getAttribute('w:w');
    const wType = tblW.getAttribute('w:type');
    if (wType === 'dxa' || wType === null) {
      if (wVal) {
        const n = parseInt(wVal, 10);
        if (Number.isFinite(n)) props.width = twipToPt(n);
      }
      props.widthType = 'dxa';
    } else if (wType === 'pct' || wType === 'auto' || wType === 'nil') {
      props.widthType = wType;
    }
  }

  // tblInd
  const tblInd = directChild(tblPr, 'w:tblInd');
  if (tblInd) {
    const w = tblInd.getAttribute('w:w');
    if (w !== null) {
      const n = parseInt(w, 10);
      if (Number.isFinite(n)) props.indent = twipToPt(n);
    }
  }

  // jc → alignment
  const jcVal = attr(directChild(tblPr, 'w:jc'), 'w:val');
  if (jcVal === 'left' || jcVal === 'right' || jcVal === 'center') {
    props.alignment = jcVal;
  } else if (jcVal === 'start') props.alignment = 'left';
  else if (jcVal === 'end') props.alignment = 'right';

  // tblBorders
  const tblBordersEl = directChild(tblPr, 'w:tblBorders');
  if (tblBordersEl) {
    props.borders = parseCellBorders(tblBordersEl);
  }

  // tblLook
  const tblLookEl = directChild(tblPr, 'w:tblLook');
  if (tblLookEl) {
    const v = tblLookEl.getAttribute('w:val');
    if (v) props.look = v;
  }

  // tblCellMar → cellMargins
  const tblCellMarEl = directChild(tblPr, 'w:tblCellMar');
  if (tblCellMarEl) {
    props.cellMargins = parseCellMargins(tblCellMarEl);
  }

  return { props, styleId };
}

// ── <w:tcBorders> / <w:tblBorders> ───────────────────────────────────────────

function parseCellBorders(el: Element): CellBorders {
  const out: CellBorders = {};
  for (const child of directChildren(el)) {
    const def = parseBorderDef(child);
    if (!def) continue;
    switch (child.tagName) {
      case 'w:top':
        out.top = def;
        break;
      case 'w:bottom':
        out.bottom = def;
        break;
      case 'w:left':
      case 'w:start':
        out.left = def;
        break;
      case 'w:right':
      case 'w:end':
        out.right = def;
        break;
      case 'w:insideH':
        out.insideH = def;
        break;
      case 'w:insideV':
        out.insideV = def;
        break;
    }
  }
  return out;
}

// Sprint 133：parseBorderDef / parseShading 已抽到 ../styles/borderShading.ts
// 共用、本檔 import 使用、避免雙處維護 BorderDef shape

// ── <w:tcMar> / <w:tblCellMar> ───────────────────────────────────────────────

function parseCellMargins(el: Element): {
  top?: Pt;
  bottom?: Pt;
  left?: Pt;
  right?: Pt;
} {
  const out: { top?: Pt; bottom?: Pt; left?: Pt; right?: Pt } = {};
  for (const child of directChildren(el)) {
    const wVal = child.getAttribute('w:w');
    const wType = child.getAttribute('w:type');
    if (wVal === null) continue;
    if (wType !== null && wType !== 'dxa' && wType !== 'nil') continue; // 只認 dxa
    const n = parseInt(wVal, 10);
    if (!Number.isFinite(n)) continue;
    const v = twipToPt(n);
    switch (child.tagName) {
      case 'w:top':
        out.top = v;
        break;
      case 'w:bottom':
        out.bottom = v;
        break;
      case 'w:left':
      case 'w:start':
        out.left = v;
        break;
      case 'w:right':
      case 'w:end':
        out.right = v;
        break;
    }
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

function attr(el: Element | undefined, name: string): string | undefined {
  if (!el) return undefined;
  const v = el.getAttribute(name);
  return v === null ? undefined : v;
}

function boolFlag(el: Element | undefined): boolean {
  if (!el) return false;
  const v = el.getAttribute('w:val');
  if (v === null) return true;
  return v !== '0' && v.toLowerCase() !== 'false';
}

/**
 * Sprint 293：解析 w:cellIns / w:cellDel / w:cellMerge 的 author/date/id 屬性。
 * 屬性全缺 → 仍回 {}（OOXML 允許）。
 */
function parseTrackChangeAttrsTbl(el: Element): TrackChangeMeta {
  const meta: TrackChangeMeta = {};
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

// ── 對外型別 ──────────────────────────────────────────────────────────────────

export type { RawCell, RawRow, VMergeRaw };
