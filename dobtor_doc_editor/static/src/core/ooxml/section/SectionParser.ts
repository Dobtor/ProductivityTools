/**
 * SectionParser — 解析 <w:sectPr>
 *
 * 職責：
 *   - 取得頁面尺寸 / margins / orientation
 *   - 取得欄位設定（cols count / space / equalWidth）
 *   - 取得 header/footer 引用 rId（default / first / even）
 *   - 取得 titlePg / evenAndOddHeaders 旗標
 *
 * 目前實作層級（Phase A — Sprint 0 通電）：
 *   - parse(sectPrEl): 解析最常見屬性（pgSz / pgMar / headerReference / footerReference / cols 基本欄位）
 *   - 找不到的屬性套 A4 預設值（縱向、四邊界 1 inch）
 *
 * Phase B Sprint 1 將補完：
 *   - <w:pgBorders>、<w:pgNumType>、<w:docGrid>、<w:lnNumType>
 *   - 多 section（依文件中多個 <w:sectPr> 切節）
 *   - <w:cols> 不等寬欄、<w:sep>、<w:space>
 */

import type { Pt, SectionNode } from '../ast/types';
import { twipToPt } from '../units/units';

const A4_WIDTH_PT = 595.3; // 210mm
const A4_HEIGHT_PT = 841.9; // 297mm
const DEFAULT_MARGIN_PT = 72; // 1 inch
const DEFAULT_HEADER_FOOTER_PT = 36; // 0.5 inch

export class SectionParser {
  /**
   * 解析單一 <w:sectPr> 元素為 SectionNode（不含 body）。
   *
   * 設計：本函式只負責「節屬性」，body（BlockNode[]）由呼叫端從
   * DocumentParser 走訪結果填入，避免重造段落/表格走訪邏輯。
   *
   * @param sectPrEl w:sectPr 元素；可為 undefined（沒有節屬性時用全預設值）
   * @returns SectionNode，body 欄位為空陣列由呼叫端填入
   */
  parse(sectPrEl: Element | undefined): SectionNode {
    const page = parsePageSize(sectPrEl);
    const margins = parseMargins(sectPrEl);
    const columns = parseColumns(sectPrEl);
    const { headerRefs, footerRefs } = parseHeaderFooterRefs(sectPrEl);
    const titlePage = boolFlag(directChild(sectPrEl, 'w:titlePg'));
    const sectionBreakType = parseSectionBreakType(sectPrEl);
    const docGrid = parseDocGrid(sectPrEl);

    const node: SectionNode = {
      type: 'section',
      page,
      margins,
      headerRefs,
      footerRefs,
      titlePage,
      evenAndOddHeaders: false, // 來自 settings.xml，由 OoxmlParser 注入；此層先設 false
      body: [], // 由 OoxmlParser orchestrator 填入
    };

    if (columns) node.columns = columns;
    // 只在非預設值時寫入，避免影響 04_ast_snapshot 的 snapshot 穩定性
    if (sectionBreakType && sectionBreakType !== 'nextPage') {
      node.sectionBreakType = sectionBreakType;
    }
    if (docGrid) node.docGrid = docGrid;
    return node;
  }
}

/** Sprint 29：解析 `<w:docGrid w:type="lines" w:linePitch="364"/>` */
function parseDocGrid(
  sectPr: Element | undefined,
): NonNullable<SectionNode['docGrid']> | undefined {
  const dg = directChild(sectPr, 'w:docGrid');
  if (!dg) return undefined;
  const typeRaw = dg.getAttribute('w:type');
  let type: NonNullable<SectionNode['docGrid']>['type'] = 'default';
  if (typeRaw === 'lines') type = 'lines';
  else if (typeRaw === 'linesAndChars') type = 'linesAndChars';
  else if (typeRaw === 'snapToChars') type = 'snapToChars';
  const linePitchRaw = dg.getAttribute('w:linePitch');
  const linePitchTwip = linePitchRaw ? parseInt(linePitchRaw, 10) : NaN;
  const linePitch = Number.isFinite(linePitchTwip) ? twipToPt(linePitchTwip) : 0;
  // 'default' type 對 layout 沒影響（linePitch 是否有值都不 snap）→ 不寫入，保 snapshot 穩定
  if (type === 'default') return undefined;
  return { type, linePitch };
}

/** 解析 <w:type w:val="continuous|evenPage|oddPage|nextPage">；undefined → 預設 nextPage */
function parseSectionBreakType(
  sectPr: Element | undefined,
): 'nextPage' | 'continuous' | 'evenPage' | 'oddPage' | undefined {
  const t = directChild(sectPr, 'w:type');
  if (!t) return undefined;
  const val = t.getAttribute('w:val');
  if (val === 'continuous' || val === 'evenPage' || val === 'oddPage' || val === 'nextPage') {
    return val;
  }
  return undefined;
}

// ── 內部解析 ──────────────────────────────────────────────────────────────────

function parsePageSize(sectPr: Element | undefined): SectionNode['page'] {
  const pgSz = directChild(sectPr, 'w:pgSz');
  if (!pgSz) {
    return { width: A4_WIDTH_PT, height: A4_HEIGHT_PT, orientation: 'portrait' };
  }
  const w = attrInt(pgSz, 'w:w');
  const h = attrInt(pgSz, 'w:h');
  const orientRaw = pgSz.getAttribute('w:orient');
  const orientation: 'portrait' | 'landscape' =
    orientRaw === 'landscape' ? 'landscape' : 'portrait';
  return {
    width: w !== undefined ? twipToPt(w) : A4_WIDTH_PT,
    height: h !== undefined ? twipToPt(h) : A4_HEIGHT_PT,
    orientation,
  };
}

function parseMargins(sectPr: Element | undefined): SectionNode['margins'] {
  const pgMar = directChild(sectPr, 'w:pgMar');
  if (!pgMar) {
    return {
      top: DEFAULT_MARGIN_PT,
      bottom: DEFAULT_MARGIN_PT,
      left: DEFAULT_MARGIN_PT,
      right: DEFAULT_MARGIN_PT,
      header: DEFAULT_HEADER_FOOTER_PT,
      footer: DEFAULT_HEADER_FOOTER_PT,
    };
  }
  const top = attrTwip(pgMar, 'w:top') ?? DEFAULT_MARGIN_PT;
  const bottom = attrTwip(pgMar, 'w:bottom') ?? DEFAULT_MARGIN_PT;
  const left = attrTwip(pgMar, 'w:left') ?? attrTwip(pgMar, 'w:start') ?? DEFAULT_MARGIN_PT;
  const right = attrTwip(pgMar, 'w:right') ?? attrTwip(pgMar, 'w:end') ?? DEFAULT_MARGIN_PT;
  const header = attrTwip(pgMar, 'w:header') ?? DEFAULT_HEADER_FOOTER_PT;
  const footer = attrTwip(pgMar, 'w:footer') ?? DEFAULT_HEADER_FOOTER_PT;
  const gutter = attrTwip(pgMar, 'w:gutter');
  const out: SectionNode['margins'] = { top, bottom, left, right, header, footer };
  if (gutter !== undefined) out.gutter = gutter;
  return out;
}

function parseColumns(sectPr: Element | undefined): SectionNode['columns'] | undefined {
  const cols = directChild(sectPr, 'w:cols');
  if (!cols) return undefined;
  const count = attrInt(cols, 'w:num') ?? 1;
  if (count <= 1) return undefined; // 單欄不寫入
  const space = attrTwip(cols, 'w:space');
  const equalWidthRaw = cols.getAttribute('w:equalWidth');
  const equalWidth = equalWidthRaw === '0' || equalWidthRaw === 'false' ? false : true;
  const sepRaw = cols.getAttribute('w:sep');
  const separator = sepRaw === '1' || sepRaw === 'true';
  const out: NonNullable<SectionNode['columns']> = { count, equalWidth };
  if (space !== undefined) out.space = space;
  if (separator) out.separator = true;

  // Sprint 6：抓個別 <w:col w:w="..." w:space="..."/>
  const colEls = directChildren(cols).filter((c) => c.tagName === 'w:col');
  if (colEls.length > 0 && !equalWidth) {
    const colWidths: Pt[] = [];
    const colSpaces: Pt[] = [];
    for (let i = 0; i < colEls.length; i++) {
      const w = attrTwip(colEls[i], 'w:w');
      if (w !== undefined) colWidths.push(w);
      if (i < colEls.length - 1) {
        const s = attrTwip(colEls[i], 'w:space');
        if (s !== undefined) colSpaces.push(s);
      }
    }
    if (colWidths.length > 0) out.colWidths = colWidths;
    if (colSpaces.length > 0) out.colSpaces = colSpaces;
  }
  return out;
}

function parseHeaderFooterRefs(sectPr: Element | undefined): {
  headerRefs: SectionNode['headerRefs'];
  footerRefs: SectionNode['footerRefs'];
} {
  const headerRefs: SectionNode['headerRefs'] = {};
  const footerRefs: SectionNode['footerRefs'] = {};
  if (!sectPr) return { headerRefs, footerRefs };

  for (const child of directChildren(sectPr)) {
    if (child.tagName === 'w:headerReference') {
      const type = child.getAttribute('w:type') ?? 'default';
      const rId = child.getAttribute('r:id') ?? child.getAttribute('w:id');
      if (rId && (type === 'default' || type === 'first' || type === 'even')) {
        headerRefs[type] = rId;
      }
    } else if (child.tagName === 'w:footerReference') {
      const type = child.getAttribute('w:type') ?? 'default';
      const rId = child.getAttribute('r:id') ?? child.getAttribute('w:id');
      if (rId && (type === 'default' || type === 'first' || type === 'even')) {
        footerRefs[type] = rId;
      }
    }
  }
  return { headerRefs, footerRefs };
}

// ── 共用工具（精簡版） ──────────────────────────────────────────────────────

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

function attrInt(el: Element, name: string): number | undefined {
  const v = el.getAttribute(name);
  if (v === null) return undefined;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : undefined;
}

function attrTwip(el: Element, name: string): number | undefined {
  const n = attrInt(el, name);
  return n !== undefined ? twipToPt(n) : undefined;
}

function boolFlag(el: Element | undefined): boolean {
  if (!el) return false;
  const v = el.getAttribute('w:val');
  if (v === null) return true;
  return v !== '0' && v.toLowerCase() !== 'false';
}
