/**
 * Paginator — Section[] → Page[]
 *
 * Sprint 2：單欄、貪婪斷行、表格 placeholder
 * Sprint 3：cell-level table layout、跨頁表格、tblHeader 重複
 * Sprint 4：
 *   - Section break: continuous / evenPage / oddPage（nextPage 預設）
 *   - Float image entries（wrapNone / wrapTopAndBottom；其餘 wrap 模式降級）
 *   - Widow/orphan 完整回退（paragraph push back）
 *
 * 不在本 Sprint：
 *   - wrapSquare / wrapTight / wrapThrough 行寬動態變化（留 Sprint 5）
 *   - 多欄 multi-column
 *   - 巢狀表格
 *   - Cell 內部 mid-row break
 */

import type {
  Pt,
  SectionNode,
  TableNode,
  ParagraphNode,
  RunNode,
  FloatImageNode,
  HeaderFooterContent,
  BlockNode,
  NumberingMap,
  RunProps,
} from '../ooxml/ast/types';
import type {
  DocumentLayout,
  FloatImageEntry,
  LayoutOptions,
  Line,
  LinePageEntry,
  Page,
  PageEntry,
  RowLayout,
  TableLayoutEntry,
} from './types';
import { breakParagraph } from './LineBreaker';
import { buildParagraph, type NumberingPrefix } from './BoxBuilder';
import { EstimateMetrics } from './TextMetrics';
import { layoutTable, splitRowAtHeight, splitRowAtPageBreak } from './TableLayout';
import { computeAlignmentShift } from './alignmentShift';
import { isFramedParagraph, frameGroupLength } from './frameGroup';
import { NumberingCounterState, expandLvlText } from '../ooxml/numbering';

interface PaginateContext {
  pageWidth: Pt;
  pageHeight: Pt;
  marginTop: Pt;
  marginBottom: Pt;
  marginLeft: Pt;
  marginRight: Pt;
  contentWidth: Pt;
  contentHeight: Pt;
  sectionIndex: number;
  pageNumber: number;
  /** 當前頁面已用內容高（從 marginTop 起算）*/
  currentY: Pt;
  /** 當前頁的 entries */
  entries: PageEntry[];
  /** 已生成的 pages */
  pages: Page[];
  warnings: string[];

  // ── Sprint 5-6：multi-column 支援 ──────────────────────────────────────
  /** 欄數（1 = 單欄；> 1 即 multi-column） */
  columnCount: number;
  /** 當前欄 index（0..columnCount-1） */
  columnIndex: number;
  /** 每欄寬度陣列（length = columnCount）；Sprint 6：支援不等寬 */
  columnWidths: Pt[];
  /** 欄間距陣列（length = columnCount - 1）；Sprint 6：支援個別欄距 */
  columnSpaces: Pt[];
  /** Sprint 10：是否畫欄分隔線（OOXML w:cols w:sep） */
  columnSeparator: boolean;

  // ── Sprint 6：wrapSquare 行寬動態 ──────────────────────────────────────
  /**
   * 當前活躍的 float 排除區（wrapSquare 左 / 右浮動圖）。
   *
   * Paginator 在放 wrapSquare floatImage 時 push；layParagraph 用此查詢
   * 「此行 y 位置應該避開哪些區域」，產出 reduced lineWidth + xOffset。
   *
   * 簡化：不依 columnIndex 區分（floatImage 只能屬於某一欄，跨欄行為
   *       由用戶自行處理；常見 fixture 內 wrapSquare 與 multi-column 不同時用）。
   */
  activeFloats: ActiveFloat[];

  // ── Sprint 18：R1 transition 變體狀態追蹤 ────────────────────────────────
  /**
   * 上一個放置的 row 是否為「大型 image row」（R1 條件命中）。
   *
   * 用於 R1 變體（imageRowBreakRatio > 0 時啟用）：當 row block 在 image / std
   * 之間切換時觸發 page break。連續 image row 不破，避免 Sprint 17 ratio=0.3
   * 的 over-paginate 問題（見 docs/sprint18_pagination_transition.md）。
   *
   * 重置時機：
   *   - 每次 flushPage / nextColumnOrPage 後重設為 false（新頁起點視為「未在 image 段」）
   *   - 段落（layParagraph）放完後重設為 false（段落視為 std 內容，打斷 image 段）
   *
   * 更新時機：
   *   - laySingleTable 每放完一個 row 後依該 row 是否為 image row 設定
   */
  lastRowWasImage: boolean;

  // ── Sprint 29：docGrid（OOXML §17.6.5 文件格線）────────────────────────────
  /**
   * 當前 section 的 docGrid linePitch（pt），用於 LineBreaker 行高 snap。
   *
   * - 0 = 未設或 type='default'（不 snap）
   * - > 0 = type ∈ {lines, linesAndChars, snapToChars} 且 linePitch 已從 twip 轉 pt
   *
   * 從 section.docGrid 帶入，跨 section 切換時由 rebindCtxToSection 更新。
   */
  docGridLinePitch: Pt;

  // ── Sprint 139：numbering 計數器（跨 section/cell 共用）────────────────────
  /**
   * 文件 NumberingMap（caller 傳入）；undefined → 不 emit 前綴（Sprint 138 前行為）。
   *
   * 從 LayoutOptions.numbering 注入；跨 section 不重設（OOXML §17.9 預設行為）。
   */
  numberingMap?: NumberingMap;
  /**
   * 跨段落演化的計數器；layParagraph / TableLayout.layoutCell 共用此實例。
   *
   * 跨 section / cell 共用 state（與 ToCanvasEditor Sprint 138 設計一致）。
   */
  numberingCounter: NumberingCounterState;

  // ── Sprint 162：tab stop 解析（跨 section 共用）──────────────────────────
  /**
   * 預設 tab stop 間距（pt）；從 `LayoutOptions.defaultTabStop` 注入。
   * undefined / 0 → LineBreaker 不解析 tab（Strategy C 預設路徑）。
   */
  defaultTabStop?: Pt;
}

/** Sprint 6：wrapSquare 排除區。 */
interface ActiveFloat {
  /** 排除區的 page-local Y top（含 margin）*/
  yTop: Pt;
  /** 排除區的 page-local Y bottom = yTop + height */
  yBottom: Pt;
  /** 排除區的 page-local X left */
  xLeft: Pt;
  /** 排除區的 page-local X right = xLeft + width */
  xRight: Pt;
  /** 浮動圖在欄內的 side */
  side: 'left' | 'right';
  /** padding：浮動圖與內文之間的留白 */
  padding: Pt;
}

/**
 * 對單一 SectionNode 排版。
 *
 * Widow/orphan（Sprint 4 完整版）：
 *   1. 段落 break 為 N 行
 *   2. 計算「當前頁能容納幾行」K
 *   3. 若 K < orphanMin 且段落會跨頁 → 整段推下一頁
 *   4. 若 (N - K) < widowMin → 把當前頁多餘行也推到下一頁（rollback K - (widowMin gap)）
 */
export function paginate(
  section: SectionNode,
  sectionIndex: number,
  startPageNumber: number,
  options: LayoutOptions = {},
  /** 從 caller（layoutDocument）傳入；若有，表示 continuous 接續，不重設 currentY */
  carryCtx?: PaginateContext,
  /** internal：layoutDocument 用來決定是否要在 section 結束時自動 flush 最後一頁。
   *  直接呼叫 paginate（unit test 用）會自動 flush，行為與 Sprint 3 相同。*/
  skipFinalFlush = false,
): { pages: Page[]; warnings: string[]; nextPageNumber: number; lastCtx: PaginateContext } {
  const metrics = options.metrics ?? new EstimateMetrics();
  const widowMin = options.widowMin ?? 2;
  const orphanMin = options.orphanMin ?? 2;

  const ctx: PaginateContext = carryCtx
    ? rebindForSection(carryCtx, section, sectionIndex)
    : makeContext(section, sectionIndex, startPageNumber);
  // Sprint 139：直接呼叫 paginate（unit test 用）也注入 numbering
  if (!carryCtx) ctx.numberingMap = options.numbering;
  // Sprint 162：tab stop 間距注入（同 numbering、跨 section 共用、carryCtx 已帶）
  if (!carryCtx) ctx.defaultTabStop = options.defaultTabStop;

  for (let blockIdx = 0; blockIdx < section.body.length; blockIdx++) {
    const block = section.body[blockIdx];
    if (block.type === 'paragraph') {
      // Sprint 169：framePr 浮動段落框（opt-in）。連續同 framePr 段落合併為一 frame、
      // 抽出正常流由 layFramedParagraphs 處理。enableFramePr 關 → 走一般 layParagraph、
      // 與 Sprint 0-168 byte-identical。
      if (options.enableFramePr && isFramedParagraph(block)) {
        const groupLen = frameGroupLength(section.body, blockIdx);
        const framed: ParagraphNode[] = [];
        for (let i = 0; i < groupLen; i++) framed.push(section.body[blockIdx + i] as ParagraphNode);
        layFramedParagraphs(ctx, framed, blockIdx, metrics);
        blockIdx += groupLen - 1;
      } else {
        layParagraph(ctx, block, blockIdx, metrics, widowMin, orphanMin);
      }
    } else if (block.type === 'table') {
      laySingleTable(ctx, block, blockIdx, options);
    }
  }

  // Sprint 3 行為：直接呼叫 paginate 時自動 flush。layoutDocument 透過
  // skipFinalFlush=true 取得未 flush ctx，決定 continuous 銜接。
  if (!skipFinalFlush) {
    if (ctx.entries.length > 0 || ctx.pages.length === 0) {
      flushPage(ctx);
    }
  }

  return {
    pages: ctx.pages,
    warnings: ctx.warnings,
    nextPageNumber: ctx.pageNumber,
    lastCtx: ctx,
  };
}

/** 對全文件排版（多 section 串接，含 section break 處理）。*/
export function layoutDocument(
  sections: SectionNode[],
  options: LayoutOptions = {},
): DocumentLayout {
  if (sections.length === 0) {
    return { pages: [], warnings: [] };
  }

  // 全程共用單一 ctx，pages / warnings 全部累積在此
  const ctx: PaginateContext = makeContext(sections[0], 0, 1);
  // Sprint 139：注入 numbering map（counter state 已由 makeContext 建好、跨 section 共用）
  ctx.numberingMap = options.numbering;
  // Sprint 162：tab stop 間距注入（跨 section 共用）
  ctx.defaultTabStop = options.defaultTabStop;

  for (let i = 0; i < sections.length; i++) {
    const sec = sections[i];

    // 第二節以後處理 section break
    if (i > 0) {
      const prevBreak = sections[i - 1].sectionBreakType ?? 'nextPage';
      if (prevBreak === 'continuous' && samePageGeometry(sections[i - 1], sec)) {
        // 同一頁繼續：只更新 sectionIndex，currentY/entries 保留
        ctx.sectionIndex = i;
      } else {
        // 換頁：flush 上節最後一頁 + 必要時 ensure parity + rebind 到新 section
        if (ctx.entries.length > 0) flushPage(ctx);
        if (prevBreak === 'evenPage' || prevBreak === 'oddPage') {
          ensurePageParity(ctx, prevBreak);
        }
        rebindCtxToSection(ctx, sec, i);
      }
    }

    layoutSectionInto(sec, ctx, options);
  }

  // 最後一節殘留
  if (ctx.entries.length > 0) flushPage(ctx);

  // Sprint 11：在 PAGE 真值替換之前先排版 header / footer，讓兩者一起被 post-pass 觸及
  if (options.headers || options.footers) {
    layoutHeadersFooters(ctx.pages, sections, options);
  }

  // Sprint 10：post-pass 把 PAGE / NUMPAGES 欄位 box 的 text 換成真值
  // Sprint 11：post-pass 範圍自動涵蓋 header / footer 內的 field box
  // Sprint 12：擴展為 resolveFieldValues 同時處理 DATE / TIME / AUTHOR / FILENAME
  resolveFieldValues(ctx.pages, options);

  return { pages: ctx.pages, warnings: ctx.warnings };
}

/**
 * Sprint 11：依每頁 sectionIndex / pageNumber 選擇 header/footer rId，
 * 把對應 HeaderFooterContent 排版到 page 的頁首/頁尾區塊，並 append 到 page.entries。
 *
 * Header zone（page-local）：
 *   - 起點 y = section.margins.header（與頁面 top 之距）
 *   - 高度上限 = section.margins.top - section.margins.header（避免溢出進 body）
 *
 * Footer zone：
 *   - 結束 y = pageHeight - section.margins.footer
 *   - 高度上限 = section.margins.bottom - section.margins.footer
 *
 * Header/footer rId 選擇規則（OOXML §17.10）：
 *   - first（titlePage=true 且 page=section 第一頁）→ 用 first，否則 fallback default
 *   - even（evenAndOddHeaders=true 且 pageNumber 偶數）→ 用 even，否則 fallback default
 *   - 兩者都不命中 → default
 */
function layoutHeadersFooters(
  pages: Page[],
  sections: SectionNode[],
  options: LayoutOptions,
): void {
  if (pages.length === 0) return;
  const headerMap = options.headers ?? new Map<string, HeaderFooterContent>();
  const footerMap = options.footers ?? new Map<string, HeaderFooterContent>();
  // 每節第一頁：用於 titlePage 判斷
  const firstPageNumberOfSection = computeFirstPageOfSection(pages);

  for (const page of pages) {
    const section = sections[page.sectionIndex];
    if (!section) continue;
    const isSectionFirstPage = firstPageNumberOfSection.get(page.sectionIndex) === page.pageNumber;
    const isEven = page.pageNumber % 2 === 0;

    // Header
    const headerRId = pickHeaderFooterRId(
      section.headerRefs, section.titlePage, section.evenAndOddHeaders,
      isSectionFirstPage, isEven,
    );
    if (headerRId) {
      const content = headerMap.get(headerRId);
      if (content) {
        appendHeaderEntries(page, section, content, options);
      }
    }

    // Footer
    const footerRId = pickHeaderFooterRId(
      section.footerRefs, section.titlePage, section.evenAndOddHeaders,
      isSectionFirstPage, isEven,
    );
    if (footerRId) {
      const content = footerMap.get(footerRId);
      if (content) {
        appendFooterEntries(page, section, content, options);
      }
    }
  }
}

/** 對每節算第一頁 pageNumber（純從 pages.sectionIndex 觀察）。 */
function computeFirstPageOfSection(pages: Page[]): Map<number, number> {
  const out = new Map<number, number>();
  for (const p of pages) {
    if (!out.has(p.sectionIndex)) out.set(p.sectionIndex, p.pageNumber);
  }
  return out;
}

/**
 * 依 OOXML 規則挑 header/footer rId。
 *   優先序：(titlePage 第一頁 → first) > (evenAndOddHeaders 偶頁 → even) > default
 *   找不到優先選項時 fallback 到 default。
 */
function pickHeaderFooterRId(
  refs: { default?: string; first?: string; even?: string },
  titlePage: boolean,
  evenAndOddHeaders: boolean,
  isSectionFirstPage: boolean,
  isEven: boolean,
): string | undefined {
  if (titlePage && isSectionFirstPage && refs.first) return refs.first;
  if (evenAndOddHeaders && isEven && refs.even) return refs.even;
  return refs.default ?? refs.first ?? refs.even;
}

/** 把 HeaderFooterContent 排版進 page header zone，append 到 page.entries。 */
function appendHeaderEntries(
  page: Page,
  section: SectionNode,
  content: HeaderFooterContent,
  options: LayoutOptions,
): void {
  const startY = section.margins.header;
  const innerWidth = page.width - section.margins.left - section.margins.right;
  const baseX = section.margins.left;
  const entries = renderBlocksToEntries(content.content, baseX, startY, innerWidth, options);
  page.entries.push(...entries);
}

/** 把 HeaderFooterContent 排版進 page footer zone，append 到 page.entries。 */
function appendFooterEntries(
  page: Page,
  section: SectionNode,
  content: HeaderFooterContent,
  options: LayoutOptions,
): void {
  const innerWidth = page.width - section.margins.left - section.margins.right;
  const baseX = section.margins.left;
  // 先用「臨時起點 0」排好取得總高度，再整體下移到 (pageHeight - margins.footer - totalHeight)
  const tempEntries = renderBlocksToEntries(content.content, baseX, 0, innerWidth, options);
  let totalH = 0;
  for (const e of tempEntries) {
    const yEnd = e.y + e.height;
    if (yEnd > totalH) totalH = yEnd;
  }
  const targetTop = page.height - section.margins.footer - totalH;
  for (const e of tempEntries) {
    e.y += targetTop;
  }
  page.entries.push(...tempEntries);
}

/**
 * 簡化版 block-to-entry 排版（只跑 paragraph + 單張表格，不切跨頁、不處理 widow/orphan、
 * 不處理 multi-column。Header / footer 通常 1-3 行，這個簡化版夠用）。
 *
 * 回傳 entries 的 x/y 都是 page-local。
 */
function renderBlocksToEntries(
  blocks: BlockNode[],
  baseX: Pt,
  baseY: Pt,
  innerWidth: Pt,
  options: LayoutOptions,
): PageEntry[] {
  const metrics = options.metrics ?? new EstimateMetrics();
  const entries: PageEntry[] = [];
  let cursorY = baseY;
  for (let bi = 0; bi < blocks.length; bi++) {
    const block = blocks[bi];
    if (block.type === 'paragraph') {
      const indentLeft = block.props.indent?.left ?? 0;
      const indentRight = block.props.indent?.right ?? 0;
      const lineWidth = Math.max(innerWidth - indentLeft - indentRight, 1);
      const input = buildParagraph(block, bi, metrics);
      const lines = breakParagraph(input, {
        lineWidth,
        firstLineIndent: block.props.indent?.firstLine,
        metrics,
        defaultTabStop: options.defaultTabStop,
      });
      for (const line of lines) {
        const lineEntry: LinePageEntry = {
          kind: 'line',
          x: baseX + indentLeft,
          y: cursorY,
          width: lineWidth,
          height: line.height,
          line,
        };
        entries.push(lineEntry);
        cursorY += line.height;
      }
    } else if (block.type === 'table') {
      const inner = layoutTable(block, innerWidth, options);
      const totalH = inner.rows.reduce((s, r) => s + r.height, 0);
      const tableEntry: TableLayoutEntry = {
        kind: 'table',
        x: baseX,
        y: cursorY,
        width: innerWidth,
        height: totalH,
        blockIndex: bi,
        grid: inner.columnWidths,
        rows: inner.rows,
        isContinuation: false,
        hasMore: false,
      };
      entries.push(tableEntry);
      cursorY += totalH;
    }
  }
  return entries;
}

/**
 * Sprint 10/12：對所有頁的 entries 走訪，把欄位 Box 的 text 換成真值：
 *   - PAGE → page.pageNumber
 *   - NUMPAGES → layout.pages.length
 *   - DATE → 由 documentMetadata.now（預設 `new Date()`）+ dateFormat 格式化
 *   - TIME → 同上但格式化為 HH:mm
 *   - AUTHOR / FILENAME → documentMetadata.{author,filename}（無則保留 placeholder）
 *
 * 範圍：line entry / table cell / 巢狀表深層遞迴 / header / footer 已 append 進 page.entries。
 */
function resolveFieldValues(pages: Page[], options: LayoutOptions): void {
  const totalPages = pages.length;
  const meta = options.documentMetadata ?? {};
  const now = meta.now ?? new Date();
  const dateFormat = meta.dateFormat ?? 'yyyy/MM/dd';
  const timeFormat = meta.timeFormat ?? 'HH:mm';
  const dateStr = formatDate(now, dateFormat);
  const timeStr = formatDate(now, timeFormat);

  for (const page of pages) {
    for (const entry of page.entries) {
      if (entry.kind === 'line') {
        resolveLineFields(entry.line, page.pageNumber, totalPages, dateStr, timeStr, meta);
      } else if (entry.kind === 'table') {
        for (const row of entry.rows) {
          for (const cell of row.cells) {
            resolveCellFields(cell, page.pageNumber, totalPages, dateStr, timeStr, meta);
          }
        }
      }
    }
  }
}

function resolveLineFields(
  line: Line,
  pageNumber: number,
  totalPages: number,
  dateStr: string,
  timeStr: string,
  meta: NonNullable<LayoutOptions['documentMetadata']>,
): void {
  for (const item of line.items) {
    if (item.kind !== 'box' || !item.fieldType) continue;
    switch (item.fieldType) {
      case 'PAGE':
        item.text = String(pageNumber);
        break;
      case 'NUMPAGES':
        item.text = String(totalPages);
        break;
      case 'DATE':
        item.text = dateStr;
        break;
      case 'TIME':
        item.text = timeStr;
        break;
      case 'AUTHOR':
        if (meta.author) item.text = meta.author;
        break;
      case 'FILENAME':
        if (meta.filename) item.text = meta.filename;
        break;
      // unknown / 其他 fieldType：保留原 placeholder 不動
    }
  }
}

function resolveCellFields(
  cell: import('./types').CellLayout,
  pageNumber: number,
  totalPages: number,
  dateStr: string,
  timeStr: string,
  meta: NonNullable<LayoutOptions['documentMetadata']>,
): void {
  for (const block of cell.blocks) {
    if (block.kind === 'lines') {
      for (const ln of block.lines) {
        resolveLineFields(ln, pageNumber, totalPages, dateStr, timeStr, meta);
      }
    } else if (block.kind === 'table') {
      for (const row of block.table.rows) {
        for (const c of row.cells) {
          resolveCellFields(c, pageNumber, totalPages, dateStr, timeStr, meta);
        }
      }
    }
  }
}

/**
 * Sprint 12：簡化版 date format（不引外部 lib）。
 *
 * 支援 token：yyyy / MM / dd / HH / mm / ss
 *   - yyyy：4 位西元年
 *   - MM：2 位月（01-12）
 *   - dd：2 位日（01-31）
 *   - HH：2 位時（00-23，24h 制）
 *   - mm：2 位分（00-59）
 *   - ss：2 位秒（00-59）
 *
 * 不支援 yy / MMM / am-pm 等高階 OOXML date format；遇到不認得的字 keep as-is。
 */
function formatDate(d: Date, fmt: string): string {
  const yyyy = String(d.getFullYear());
  const MM = pad2(d.getMonth() + 1);
  const dd = pad2(d.getDate());
  const HH = pad2(d.getHours());
  const mm = pad2(d.getMinutes());
  const ss = pad2(d.getSeconds());
  return fmt
    .replace(/yyyy/g, yyyy)
    .replace(/MM/g, MM)
    .replace(/dd/g, dd)
    .replace(/HH/g, HH)
    .replace(/mm/g, mm)
    .replace(/ss/g, ss);
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** 把單一 section 的 body 灌入 ctx（不 flush 最後一頁，由 caller 決定）。 */
function layoutSectionInto(
  section: SectionNode,
  ctx: PaginateContext,
  options: LayoutOptions,
): void {
  const metrics = options.metrics ?? new EstimateMetrics();
  const widowMin = options.widowMin ?? 2;
  const orphanMin = options.orphanMin ?? 2;

  for (let blockIdx = 0; blockIdx < section.body.length; blockIdx++) {
    const block = section.body[blockIdx];
    if (block.type === 'paragraph') {
      // Sprint 169：framePr 浮動段落框（opt-in）。連續同 framePr 段落合併為一 frame、
      // 抽出正常流由 layFramedParagraphs 處理。enableFramePr 關 → 走一般 layParagraph、
      // 與 Sprint 0-168 byte-identical。
      if (options.enableFramePr && isFramedParagraph(block)) {
        const groupLen = frameGroupLength(section.body, blockIdx);
        const framed: ParagraphNode[] = [];
        for (let i = 0; i < groupLen; i++) framed.push(section.body[blockIdx + i] as ParagraphNode);
        layFramedParagraphs(ctx, framed, blockIdx, metrics);
        blockIdx += groupLen - 1;
      } else {
        layParagraph(ctx, block, blockIdx, metrics, widowMin, orphanMin);
      }
    } else if (block.type === 'table') {
      laySingleTable(ctx, block, blockIdx, options);
    }
  }
}

/** 把 ctx 重新綁定到新 section 的頁面 geometry（保留 pages / warnings / pageNumber）。 */
function rebindCtxToSection(
  ctx: PaginateContext,
  section: SectionNode,
  sectionIndex: number,
): void {
  ctx.pageWidth = section.page.width;
  ctx.pageHeight = section.page.height;
  ctx.marginTop = section.margins.top;
  ctx.marginBottom = section.margins.bottom;
  ctx.marginLeft = section.margins.left;
  ctx.marginRight = section.margins.right;
  ctx.contentWidth = ctx.pageWidth - ctx.marginLeft - ctx.marginRight;
  ctx.contentHeight = ctx.pageHeight - ctx.marginTop - ctx.marginBottom;
  ctx.sectionIndex = sectionIndex;
  // Sprint 5-6：multi-column rebind（支援不等寬）
  const { columnWidths, columnSpaces } = computeColumnLayout(section.columns, ctx.contentWidth);
  ctx.columnCount = columnWidths.length;
  ctx.columnWidths = columnWidths;
  ctx.columnSpaces = columnSpaces;
  ctx.columnSeparator = section.columns?.separator === true && columnWidths.length > 1;
  ctx.columnIndex = 0;
  ctx.docGridLinePitch = docGridLinePitchOf(section);
}

/**
 * Sprint 29：把 section.docGrid 翻成 LineBreaker 用的 linePitch (Pt)。
 *
 * - 無 docGrid 或 type='default' → 0（不 snap）
 * - type ∈ {lines, linesAndChars, snapToChars} → 回傳 linePitch
 */
function docGridLinePitchOf(section: SectionNode): Pt {
  const dg = section.docGrid;
  if (!dg) return 0;
  if (dg.type === 'default') return 0;
  if (!Number.isFinite(dg.linePitch) || dg.linePitch <= 0) return 0;
  return dg.linePitch;
}

/** 取當前 column 的 X 座標（page-local）。 */
function currentColumnX(ctx: PaginateContext): Pt {
  let x = ctx.marginLeft;
  for (let i = 0; i < ctx.columnIndex; i++) {
    x += ctx.columnWidths[i] ?? 0;
    x += ctx.columnSpaces[i] ?? 0;
  }
  return x;
}

/** 取當前 column 的寬度。 */
function currentColumnWidth(ctx: PaginateContext): Pt {
  return ctx.columnWidths[ctx.columnIndex] ?? ctx.contentWidth;
}

/** 切到下一欄；若已是最後一欄，flush page 後回 column 0。 */
function nextColumnOrPage(ctx: PaginateContext): void {
  if (ctx.columnIndex < ctx.columnCount - 1) {
    ctx.columnIndex++;
    ctx.currentY = 0;
  } else {
    flushPage(ctx);
  }
}

// ── Paragraph 排版（含 widow/orphan 回退）──────────────────────────────────

function layParagraph(
  ctx: PaginateContext,
  block: ParagraphNode,
  blockIdx: number,
  metrics: import('./types').TextMetrics,
  widowMin: number,
  orphanMin: number,
): void {
  // pageBreakBefore：先 flush 當前頁
  if (block.props.pageBreakBefore && ctx.entries.length > 0) {
    flushPage(ctx);
  }

  // 提取 floatImage / floatTextBox（Sprint 37/38：兩者皆不參與行內排版）
  const floatImages: FloatImageNode[] = [];
  const filteredRuns: ParagraphNode['runs'] = [];
  for (const r of block.runs) {
    if (r.type === 'floatImage') {
      floatImages.push(r);
    } else if (r.type === 'floatTextBox') {
      // Sprint 38：top-level paragraph 的 floatTextBox 暫時不放（top-level 渲染為 floatImage entry
      // 的對應 floatTextBox entry 機制留 Sprint 39+；cell-internal 的 floatTextBox 由 TableLayout
      // 處理。當前頂層 floatTextBox 簡單跳過避免被當 inline Box 推進段內）
      continue;
    } else {
      filteredRuns.push(r);
    }
  }
  const paraForLayout: ParagraphNode = (floatImages.length > 0 || filteredRuns.length !== block.runs.length)
    ? { ...block, runs: filteredRuns }
    : block;

  // 先放 floatImage（topAndBottom：保留垂直空間；wrapNone：不保留）
  for (const img of floatImages) {
    placeFloatImage(ctx, img, blockIdx);
  }

  // 計算可用 line width（Sprint 5：用 columnWidth 而非 contentWidth 支援多欄）
  const indentLeft = block.props.indent?.left ?? 0;
  const indentRight = block.props.indent?.right ?? 0;
  const baseLineWidth = currentColumnWidth(ctx) - indentLeft - indentRight;

  // Sprint 6：如果有 activeFloats（wrapSquare 浮動圖），準備 per-line callback
  // 段落起點的絕對 y
  const paraStartAbsY = ctx.marginTop + ctx.currentY + (block.props.spacing?.before ?? 0);
  const colX = currentColumnX(ctx);
  const colWidth = currentColumnWidth(ctx);

  const exclusionAtY = (absY: Pt): {
    reducedWidth: Pt;
    xOffset: Pt;
  } => {
    if (ctx.activeFloats.length === 0) {
      return { reducedWidth: baseLineWidth, xOffset: 0 };
    }
    let leftPush = 0; // 左 float 推入的右移量
    let rightShrink = 0; // 右 float 削減的右側寬度
    for (const f of ctx.activeFloats) {
      // 排除區的 y 是否與此行重疊
      if (absY < f.yTop || absY >= f.yBottom) continue;
      if (f.side === 'left') {
        const overlap = (f.xRight + f.padding) - colX;
        if (overlap > leftPush) leftPush = overlap;
      } else {
        const overlap = (colX + colWidth) - (f.xLeft - f.padding);
        if (overlap > rightShrink) rightShrink = overlap;
      }
    }
    const reduced = Math.max(baseLineWidth - leftPush - rightShrink, 1);
    return { reducedWidth: reduced, xOffset: leftPush };
  };

  const prefix = computeNumberingPrefix(paraForLayout, ctx.numberingMap, ctx.numberingCounter);
  const para = buildParagraph(paraForLayout, blockIdx, metrics, prefix);
  const lines = breakParagraph(para, {
    lineWidth: Math.max(baseLineWidth, 1),
    firstLineIndent: block.props.indent?.firstLine,
    metrics,
    getLineWidth: ctx.activeFloats.length > 0
      ? (_li, accH) => exclusionAtY(paraStartAbsY + accH).reducedWidth
      : undefined,
    getLineXOffset: ctx.activeFloats.length > 0
      ? (_li, accH) => exclusionAtY(paraStartAbsY + accH).xOffset
      : undefined,
    docGridLinePitch: ctx.docGridLinePitch,
    defaultTabStop: ctx.defaultTabStop,
  });

  if (lines.length === 0) return;

  // Widow/orphan 完整版：先試算當前頁能塞幾行
  const spaceBefore = block.props.spacing?.before ?? 0;
  const spaceAfter = block.props.spacing?.after ?? 0;

  const availableNow = ctx.contentHeight - ctx.currentY - spaceBefore;
  let linesFitNow = 0;
  let cumHeight = 0;
  for (const l of lines) {
    if (cumHeight + l.height <= availableNow) {
      cumHeight += l.height;
      linesFitNow++;
    } else break;
  }
  const linesOverflow = lines.length - linesFitNow;

  // 整段推下一頁的條件：
  //   1. 段落會跨頁（linesOverflow > 0）
  //   2. 當前頁能塞的行數 < orphanMin（孤行）
  //   3. ctx 已有其他 entries（不是空頁，否則推也沒用）
  if (linesOverflow > 0 && linesFitNow < orphanMin && ctx.entries.length > 0) {
    // Sprint 5：multi-column 時切下一欄而非直接換頁
    nextColumnOrPage(ctx);
  }
  // Widow 條件：放下後若下一頁只有 < widowMin 行，把多的也推到下一頁
  else if (
    linesOverflow > 0
    && linesOverflow < widowMin
    && ctx.entries.length > 0
  ) {
    // 把當前頁的最後 (widowMin - linesOverflow) 行也推到下一頁
    const linesToHoldBack = widowMin - linesOverflow;
    const linesToPlaceNow = Math.max(linesFitNow - linesToHoldBack, 0);
    if (linesToPlaceNow < linesFitNow && linesToPlaceNow < lines.length) {
      // 裁掉 linesFitNow 至 linesToPlaceNow，達成 widow control
      // 注意：這裡實作的是「不跨頁放」策略，整段推下頁更安全
      nextColumnOrPage(ctx);
    }
  }

  // 段落 spacing.before：累加到 currentY
  ctx.currentY += block.props.spacing?.before ?? 0;

  // 逐行放（Sprint 5：以欄為單位換行；超過欄高 → next column or new page）
  const paraStartEntryIdx = ctx.entries.length;
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    if (ctx.currentY + line.height > ctx.contentHeight) {
      nextColumnOrPage(ctx);
    }
    const lineColX = currentColumnX(ctx);
    const xOffset = line.xOffset ?? 0;
    // Sprint 32：套用 paragraph alignment 到 x 起點。
    // baseLineWidth 是當前欄可用寬度（已扣 indent），用它判斷 center / right 留白分配。
    const alignShift = computeAlignmentShift(line.alignment, line.width, baseLineWidth);
    const entry: LinePageEntry = {
      kind: 'line',
      line,
      x: lineColX + indentLeft + xOffset + alignShift + (li === 0 ? (block.props.indent?.firstLine ?? 0) : 0),
      y: ctx.marginTop + ctx.currentY,
      width: line.width,
      height: line.height,
    };
    ctx.entries.push(entry);
    ctx.currentY += line.height;
    // Sprint 6：每行放完後清過期 activeFloats
    purgeStaleFloats(ctx);
    // Sprint 7：column break / page break（從 LineBreaker 透傳的 forcedBreakAfter）
    if (line.forcedBreakAfter === 'page') {
      flushPage(ctx);
    } else if (line.forcedBreakAfter === 'column') {
      nextColumnOrPage(ctx);
    }
  }
  void paraStartEntryIdx; // 可供未來精細回退用

  ctx.currentY += block.props.spacing?.after ?? 0;
  // Sprint 18：段落放完後重設 R1 transition 狀態
  // 段落視為 std 內容，打斷 image row 段；下次見到 image row 視為新一輪 transition
  ctx.lastRowWasImage = false;
}

// ── Framed Paragraphs（Sprint 169-170：`<w:framePr>` 浮動段落框）─────────────

/** Sprint 170：framePr.hSpace 未設時、框與側繞內文間距（pt、同 placeFloatImage padding）。 */
const FRAME_DEFAULT_HSPACE_PT = 6;
/** Sprint 170：側繞時內文至少需保留的寬度（pt、1 inch）；不足則退回保留垂直空間。 */
const FRAME_MIN_WRAP_TEXT_PT = 72;

/**
 * Sprint 169-170：把連續同 framePr 的段落（已由 frameGroupLength 分組）排成一個浮動框。
 *
 * - 子排版：逐段 buildParagraph + breakParagraph、收集行與框內相對座標。
 * - 框寬：framePr.width 顯式 → 用之；否則 auto → 用欄寬（內容 jc 在框內生效）。
 * - 定位：vAnchor（text / margin / page）+ y 偏移決定框頂 y；hAnchor + x / xAlign
 *   決定框左 x。各行以絕對座標 emit 為 LinePageEntry。
 * - 垂直空間策略（Sprint 170 依 framePr.wrap 分派）：
 *   - `around` / `tight` / `through` / 未設 + 顯式 framePr.width + 框寬留得下內文
 *     → 註冊 activeFloats 排除區、currentY 不推進（後續內文 per-line 側繞、複用 Sprint 6）
 *   - `notBeside` / auto-width / 框過寬無側繞空間 → 保留垂直空間（topAndBottom-like）
 *   - `none` → 純浮動、不保留也不排除
 *
 * Scope-down（紀律 #18）：框內不解析 floatImage / numbering 前綴（罕見、過濾後當純內文）；
 * 框本身跨頁留 Sprint 171；vAnchor=page/margin 純浮動不影響內文流（Sprint 171）；
 * auto-width 框維持「保留空間」—— 自然寬度 sizing + 側繞語意依賴 decision B golden、留後續。
 */
function layFramedParagraphs(
  ctx: PaginateContext,
  blocks: ParagraphNode[],
  blockIdx: number,
  metrics: import('./types').TextMetrics,
): void {
  const framePr = blocks[0].props.framePr;
  if (!framePr) return;

  const colX = currentColumnX(ctx);
  const colWidth = currentColumnWidth(ctx);
  // 框寬度：顯式 framePr.width 優先；否則 auto → 欄寬
  const frameWidth = (framePr.width !== undefined && framePr.width > 0) ? framePr.width : colWidth;

  // 子排版：逐段排版、收集各行框內相對座標（x = 框左起算、yRel = 框頂起算）
  const placed: Array<{ line: Line; xRel: Pt; yRel: Pt }> = [];
  let cursorY = 0;
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    // floatImage / floatTextBox 在框內 scope-down：過濾掉、框視為純內文
    const inlineRuns: ParagraphNode['runs'] = [];
    let hadFloat = false;
    for (const r of b.runs) {
      if (r.type === 'floatImage' || r.type === 'floatTextBox') hadFloat = true;
      else inlineRuns.push(r);
    }
    if (hadFloat) {
      ctx.warnings.push(`[paginate] block#${blockIdx + i} framed 段落含 floatImage/floatTextBox、框內 scope-down 略過（Sprint 169）。`);
    }
    const paraNode: ParagraphNode = inlineRuns.length === b.runs.length ? b : { ...b, runs: inlineRuns };
    const indentLeft = b.props.indent?.left ?? 0;
    const indentRight = b.props.indent?.right ?? 0;
    const lineWidth = Math.max(frameWidth - indentLeft - indentRight, 1);
    const para = buildParagraph(paraNode, blockIdx + i, metrics, undefined);
    const lines = breakParagraph(para, {
      lineWidth,
      firstLineIndent: b.props.indent?.firstLine,
      metrics,
      docGridLinePitch: ctx.docGridLinePitch,
      defaultTabStop: ctx.defaultTabStop,
    });
    cursorY += b.props.spacing?.before ?? 0;
    for (let li = 0; li < lines.length; li++) {
      const ln = lines[li];
      const alignShift = computeAlignmentShift(ln.alignment, ln.width, lineWidth);
      const firstLineIndent = li === 0 ? (b.props.indent?.firstLine ?? 0) : 0;
      const xRel = indentLeft + (ln.xOffset ?? 0) + alignShift + firstLineIndent;
      placed.push({ line: ln, xRel, yRel: cursorY });
      cursorY += ln.height;
    }
    cursorY += b.props.spacing?.after ?? 0;
  }
  if (placed.length === 0) return;
  const frameHeight = cursorY;

  // 垂直錨點
  const yOffset = framePr.y ?? 0;
  const anchoredToFlow = framePr.vAnchor !== 'page' && framePr.vAnchor !== 'margin';
  let frameTopY: Pt;
  if (framePr.vAnchor === 'page') {
    frameTopY = yOffset;
  } else if (framePr.vAnchor === 'margin') {
    frameTopY = ctx.marginTop + yOffset;
  } else {
    // vAnchor=text（預設）：相對當前文字流位置
    // 框放不下當前頁 → 先 flush（scope-down：框本身不跨頁、留 Sprint 171）
    if (ctx.currentY + yOffset + frameHeight > ctx.contentHeight && ctx.entries.length > 0) {
      flushPage(ctx);
    }
    frameTopY = ctx.marginTop + ctx.currentY + yOffset;
  }

  // 水平錨點
  const frameX = computeFrameX(framePr, frameWidth, colX, colWidth);

  // emit 各行為絕對座標 LinePageEntry
  for (const p of placed) {
    const entry: LinePageEntry = {
      kind: 'line',
      line: p.line,
      x: frameX + p.xRel,
      y: frameTopY + p.yRel,
      width: p.line.width,
      height: p.line.height,
    };
    ctx.entries.push(entry);
  }

  // ── 垂直空間策略（Sprint 170）：依 framePr.wrap 分派保留空間 / 側繞排除區 / 純浮動 ──
  const wrap = framePr.wrap;
  if (!anchoredToFlow) {
    // vAnchor=page/margin：純浮動、不影響內文流（scope-down、Sprint 171 補）
    ctx.warnings.push(`[paginate] block#${blockIdx} framePr vAnchor=${framePr.vAnchor}：純浮動、未保留垂直空間、可能與內文重疊（Sprint 171 補）。`);
  } else if (wrap === 'none') {
    // wrap=none：框浮於內文上、不保留空間也不排除
    ctx.warnings.push(`[paginate] block#${blockIdx} framePr wrap=none：框浮於內文上、未保留垂直空間。`);
  } else {
    // 側繞條件（全部成立）：非 notBeside + 顯式 framePr.width + 框寬旁留得下內文
    const frameHSpace = framePr.hSpace ?? FRAME_DEFAULT_HSPACE_PT;
    const hasExplicitWidth = framePr.width !== undefined && framePr.width > 0;
    const roomBeside = colWidth - frameWidth - frameHSpace >= FRAME_MIN_WRAP_TEXT_PT;
    if (wrap !== 'notBeside' && hasExplicitWidth && roomBeside) {
      // 側繞：註冊 activeFloats 排除區（複用 Sprint 6 wrapSquare 機制）、currentY 不推進
      const colMid = colX + colWidth / 2;
      const side: ActiveFloat['side'] = (frameX + frameWidth / 2) <= colMid ? 'left' : 'right';
      ctx.activeFloats.push({
        yTop: frameTopY,
        yBottom: frameTopY + frameHeight,
        xLeft: frameX,
        xRight: frameX + frameWidth,
        side,
        padding: frameHSpace,
      });
    } else {
      // 保留垂直空間（notBeside / auto-width / 框過寬無側繞空間；Sprint 169 topAndBottom-like）
      ctx.currentY += yOffset + frameHeight;
    }
  }
  ctx.lastRowWasImage = false;
}

/** Sprint 169：framePr 水平錨點 → 框左 x（絕對座標）。 */
function computeFrameX(
  framePr: NonNullable<ParagraphNode['props']['framePr']>,
  frameWidth: Pt,
  colX: Pt,
  colWidth: Pt,
): Pt {
  // xAlign 優先於 x 偏移
  switch (framePr.xAlign) {
    case 'center':
      return colX + (colWidth - frameWidth) / 2;
    case 'right':
    case 'outside':
      return colX + colWidth - frameWidth;
    case 'left':
    case 'inside':
      return colX;
    default:
      break;
  }
  // 無 xAlign：x 偏移、基準依 hAnchor
  const x = framePr.x ?? 0;
  if (framePr.hAnchor === 'page') return x;
  // margin / text（預設）→ 相對欄左（單欄時 = marginLeft）
  return colX + x;
}

// ── Float Image ────────────────────────────────────────────────────────────

function placeFloatImage(
  ctx: PaginateContext,
  img: FloatImageNode,
  blockIdx: number,
): void {
  // Sprint 6 補完：
  //   - wrapTopAndBottom: 保留垂直空間（currentY += img.height）
  //   - wrapNone / behindText / inFrontOfText: 不擠壓內文
  //   - wrapSquare / wrapTight / wrapThrough: 註冊 activeFloat 排除區，
  //     後續段落 lines 自動避開（per-y lineWidth callback）
  //     注意：tight / through 的 polygon 緊密貼邊規格 Sprint 6 簡化為 square 矩形
  let effectiveWrap: 'topAndBottom' | 'none' | 'square' = 'topAndBottom';

  switch (img.wrapType) {
    case 'topAndBottom':
      effectiveWrap = 'topAndBottom';
      break;
    case 'none':
    case 'behindText':
    case 'inFrontOfText':
      effectiveWrap = 'none';
      break;
    case 'square':
      effectiveWrap = 'square';
      break;
    case 'tight':
    case 'through':
      effectiveWrap = 'square';
      ctx.warnings.push(
        `[paginate] block#${blockIdx} floatImage wrap=${img.wrapType} 簡化為 square 矩形；`
        + `Sprint 7+ 補完 polygon 緊密繞排。`,
      );
      break;
  }

  // 解 X 座標
  const x = computeFloatX(ctx, img);
  const y = ctx.marginTop + ctx.currentY;

  // wrapTopAndBottom 太大時換頁；wrapSquare 不換頁（讓內文與圖共存）
  if (effectiveWrap === 'topAndBottom') {
    if (ctx.currentY + img.height > ctx.contentHeight && ctx.entries.length > 0) {
      flushPage(ctx);
    }
  }

  const placedY = effectiveWrap === 'topAndBottom' ? ctx.marginTop + ctx.currentY : y;
  const entry: FloatImageEntry = {
    kind: 'floatImage',
    rId: img.rId,
    blockIndex: blockIdx,
    wrapType: img.wrapType,
    behindDoc: img.behindDoc ?? false,
    x,
    y: placedY,
    width: img.width,
    height: img.height,
  };
  if (img.srcRect) entry.srcRect = img.srcRect; // Sprint 40
  ctx.entries.push(entry);

  if (effectiveWrap === 'topAndBottom') {
    ctx.currentY += img.height;
  } else if (effectiveWrap === 'square') {
    // Sprint 6：註冊 activeFloat 排除區
    // 判斷 side：以欄中線為界（左側則 side='left'，右側則 side='right'）
    const colX = currentColumnX(ctx);
    const colMid = colX + currentColumnWidth(ctx) / 2;
    const imgMid = x + img.width / 2;
    const side: ActiveFloat['side'] = imgMid <= colMid ? 'left' : 'right';
    ctx.activeFloats.push({
      yTop: placedY,
      yBottom: placedY + img.height,
      xLeft: x,
      xRight: x + img.width,
      side,
      padding: 6, // 與內文留 6pt（≈ 0.08 inch）
    });
  }
  // 'none' 不影響 currentY 也不註冊 activeFloat
}

/** 清理已過期（yBottom < currentAbsY）的 activeFloats。 */
function purgeStaleFloats(ctx: PaginateContext): void {
  const currentAbsY = ctx.marginTop + ctx.currentY;
  ctx.activeFloats = ctx.activeFloats.filter((f) => f.yBottom > currentAbsY);
}

function computeFloatX(ctx: PaginateContext, img: FloatImageNode): Pt {
  // 簡化：取 posH.posOffset；若 align 給的，根據 columnWidth 推算（Sprint 5：以欄為基準）
  const posOffset = img.posH?.posOffset ?? 0;
  const align = img.posH?.align;
  const colX = currentColumnX(ctx);
  if (align === 'left') return colX;
  if (align === 'right') return colX + currentColumnWidth(ctx) - img.width;
  if (align === 'center') return colX + (currentColumnWidth(ctx) - img.width) / 2;
  // posOffset：相對 margin/page 的位移
  const relFrom = img.posH?.relativeFrom ?? 'margin';
  if (relFrom === 'page') return posOffset;
  return colX + posOffset;
}

// ── 表格排版 + 跨頁 ──────────────────────────────────────────────────────

/** 把一張表加入當前 ctx，跨頁時自動切並重複 tblHeader 列。 */
function laySingleTable(
  ctx: PaginateContext,
  table: TableNode,
  blockIdx: number,
  options: LayoutOptions,
): void {
  // Sprint 5：multi-column 時，表格以欄為單位排版（X 在 flushTableEntry 即時計算）
  const tableContentWidth = Math.min(
    table.props.width ?? currentColumnWidth(ctx),
    currentColumnWidth(ctx),
  );

  // Sprint 29：把當前 section 的 docGrid linePitch 透傳到 TableLayout（cell 內 LineBreaker 用）
  // Sprint 139：把 ctx.numberingMap + numberingCounter 同樣透傳，讓 cell 內 paragraph 與 body 共用 counter
  const optionsWithGrid: LayoutOptions = {
    ...options,
    docGridLinePitch:
      ctx.docGridLinePitch > 0 && options.docGridLinePitch !== ctx.docGridLinePitch
        ? ctx.docGridLinePitch
        : options.docGridLinePitch,
    numbering: ctx.numberingMap ?? options.numbering,
    _numberingCounter: ctx.numberingCounter,
  };
  const { columnWidths, rows } = layoutTable(table, tableContentWidth, optionsWithGrid);

  // Sprint 18：判斷整張表是否含 image row。含 image 表代表 R1 transition 規則會處理
  // 頁邊界，cell-internal page break 則是同一表格內的「分頁加標題」結構（與 R1 重疊），
  // 啟用會雙觸發 over-paginate（04_with_image 早期實驗 +5 偏差）
  const tableHasImageRow = rows.some((r) => r.containsImage);

  // Sprint 17 + 18：image-row break heuristic 門檻（規則 R1）
  // 預設 0.34 — Sprint 18 grid search（ratio ∈ {0.0, 0.30..0.40 step 0.02, 0.50..1.00}）
  // 結果：ratio=0.34 對 04_with_image 4 個 -3 完美對齊 0，且零 regression
  //   - mismatched: 17→13 (-4)
  //   - totalDelta: -26→-14 (46% 收斂)
  //   - sumAbsDelta: 26→14 (-46%)
  // 詳見 docs/sprint18_pagination_transition.md §3。
  const imageBreakRatio = options.imageRowBreakRatio ?? 0.34;

  // 萬一全部 row 都異常（高度 0），fallback：估算後 placeholder
  const totalHeight = rows.reduce((s, r) => s + r.height, 0);
  if (totalHeight <= 0) {
    ctx.warnings.push(
      `[paginate] block#${blockIdx} 表格 (${rows.length}×${columnWidths.length}) `
      + `所有列高度 0；資料異常，跳過。`,
    );
    return;
  }

  // tblHeader 列（會被重複到每個跨頁的延續部分）
  const headerRows: RowLayout[] = rows.filter((r) => r.isHeader);
  const headerHeight = headerRows.reduce((s, r) => s + r.height, 0);

  let pendingRows: RowLayout[] = [];
  let pendingHeight = 0;
  let isContinuation = false;

  const flushTableEntry = (more: boolean): void => {
    if (pendingRows.length === 0) return;
    const tableX = currentColumnX(ctx) + (table.props.indent ?? 0);
    const entry: TableLayoutEntry = {
      kind: 'table',
      blockIndex: blockIdx,
      grid: columnWidths,
      rows: pendingRows.slice(),
      isContinuation,
      hasMore: more,
      x: tableX,
      y: ctx.marginTop + ctx.currentY,
      width: tableContentWidth,
      height: pendingHeight,
    };
    ctx.entries.push(entry);
    ctx.currentY += pendingHeight;
    pendingRows = [];
    pendingHeight = 0;
  };

  // Sprint 7：用 while loop 處理當前要放的 row，因 splitRowAtHeight 可能會
  //          產生「待放下半段」需要在下一頁繼續切。原 row 一進迴圈就 advance ri，
  //          split 時把 second half 暫存 leftoverRow，下次迴圈優先處理。
  let ri = 0;
  let leftoverRow: RowLayout | null = null;
  while (true) {
    let row: RowLayout;
    if (leftoverRow) {
      row = leftoverRow;
      leftoverRow = null;
    } else if (ri < rows.length) {
      row = rows[ri];
      ri++;
    } else {
      break;
    }

    let availableHeight = ctx.contentHeight - ctx.currentY;
    const continuationOverhead = isContinuation ? headerHeight : 0;

    // Sprint 18：cell-internal explicit page break（<w:br w:type="page"/> 在 cell 內）
    // 偵測 row 內任一 cell 的 line 含 forcedBreakAfter='page' → 在該 line 處 split
    // first half 入 pendingRows、flushTable + flushPage、second half 進 leftoverRow 下輪處理
    //
    // 排除整張表含 image row：此類表的頁邊界由規則 R1 transition 主導；cell-internal
    // break 在這類表內常與 R1 重疊（04_with_image 早期實驗：雙觸發 6→11 頁 over-paginate +5）
    if (!tableHasImageRow) {
      const pageBreakSplit = splitRowAtPageBreak(row);
      if (pageBreakSplit) {
        pendingRows.push(pageBreakSplit.first);
        pendingHeight += pageBreakSplit.first.height;
        flushTableEntry(/* more = */ true);
        flushPage(ctx);
        isContinuation = true;
        for (const hr of headerRows) {
          if (hr.rowIndex !== row.rowIndex) {
            pendingRows.push(hr);
            pendingHeight += hr.height;
          }
        }
        leftoverRow = pageBreakSplit.second;
        continue;
      }
    }

    // Sprint 17 + 18：規則 R1 — image-row break heuristic（transition 變體）
    // 條件 4 件齊全：
    //   (a) 此 row 是「大型 image row」（含 image + cantSplit + height ≥ ratio × contentHeight）
    //   (b) imageBreakRatio > 0（opt-in；預設 0 = OFF，與 Sprint 16 baseline 相同）
    //   (c) 當前頁已有內容（pendingRows 或 ctx.entries 任一非空）
    //   (d) 與前一個 row 是「不同類別」（std→image 進入 / image→std 離開）
    //       透過 ctx.lastRowWasImage 追蹤；連續 image row 不觸發避免 over-paginate
    // 觸發：flush 已 pending 的 rows，新頁從此 row 起點放，重 push tblHeader
    const isLargeImageRow = row.containsImage
      && row.cantSplit
      && imageBreakRatio > 0
      && row.height >= ctx.contentHeight * imageBreakRatio;
    const hasPriorContent = pendingRows.length > 0 || ctx.entries.length > 0;
    const enterImageBlock = isLargeImageRow && !ctx.lastRowWasImage;
    const leaveImageBlock = !isLargeImageRow && ctx.lastRowWasImage;
    // Sprint 31：R1 只在 row 真的會 overflow 當前頁時觸發。
    //
    // 舊行為（Sprint 17-18）：transition 一發生就 break，導致 04_with_image 系列把
    // 「header rows + image rows」全 fit 進一頁的 fixture 過度 split（header → 頁 N，
    // image → 頁 N+1）→ Visual Regression v14 04_with_image 平均 diff 0.38 包辦剩 48%。
    //
    // 新條件：transition + 加上此 row 已 overflow current page（pendingHeight + row.height > availableHeight）。
    // 不會 overflow 的 transition 不必 break，讓 row 自然 packed 進當前頁。
    //
    // 對 Sprint 18 原本修的 fixture 沒影響：那些 fixture 的 image rows 本就 overflow 當前頁，
    // 所以 transition + overflow 都成立，R1 還是會觸發。
    const wouldOverflow = pendingHeight + row.height > availableHeight;
    if ((enterImageBlock || leaveImageBlock) && hasPriorContent && imageBreakRatio > 0 && wouldOverflow) {
      if (pendingRows.length > 0) flushTableEntry(/* more = */ true);
      nextColumnOrPage(ctx);
      isContinuation = true;
      availableHeight = ctx.contentHeight - ctx.currentY;
      for (const hr of headerRows) {
        if (hr.rowIndex !== row.rowIndex) {
          pendingRows.push(hr);
          pendingHeight += hr.height;
        }
      }
    }
    // 更新 last-row tracking（無論是否觸發 break）
    ctx.lastRowWasImage = isLargeImageRow;

    // Sprint 7：嘗試 mid-row break 條件 — 整 row 超過頁面剩餘空間
    //   1. 先試一般 row 跨頁（Sprint 3-6 邏輯）
    //   2. 若一整列高度 > contentHeight 且 !cantSplit：用 splitRowAtHeight 切
    if (
      pendingRows.length > 0
      && pendingHeight + row.height > availableHeight
    ) {
      // 標準跨頁：先嘗試整列推下一欄/頁
      flushTableEntry(/* more = */ true);
      nextColumnOrPage(ctx);
      isContinuation = true;
      availableHeight = ctx.contentHeight - ctx.currentY;
      for (const hr of headerRows) {
        if (hr.rowIndex !== row.rowIndex) {
          pendingRows.push(hr);
          pendingHeight += hr.height;
        }
      }
    } else if (
      pendingRows.length === 0
      && ctx.entries.length > 0
      && row.height + continuationOverhead > availableHeight
    ) {
      nextColumnOrPage(ctx);
      isContinuation = true;
      availableHeight = ctx.contentHeight - ctx.currentY;
      for (const hr of headerRows) {
        if (hr.rowIndex !== row.rowIndex) {
          pendingRows.push(hr);
          pendingHeight += hr.height;
        }
      }
    }

    // Sprint 7：row 本身超過剩餘空間 → mid-row break（cell 內部切）
    const remainingHeightForRow = ctx.contentHeight - ctx.currentY - pendingHeight;
    if (
      row.height > remainingHeightForRow
      && !row.cantSplit
      && remainingHeightForRow > 0
    ) {
      const split = splitRowAtHeight(row, remainingHeightForRow);
      if (split && split.first.cells.some((c) => c.height > c.padding.top + c.padding.bottom)) {
        // 把 first half 加到 pending、flush；second half 暫存 leftoverRow
        pendingRows.push(split.first);
        pendingHeight += split.first.height;
        flushTableEntry(/* more = */ true);
        nextColumnOrPage(ctx);
        isContinuation = true;
        for (const hr of headerRows) {
          if (hr.rowIndex !== row.rowIndex) {
            pendingRows.push(hr);
            pendingHeight += hr.height;
          }
        }
        leftoverRow = split.second;
        continue;
      }
      // splitRowAtHeight 回 null 或 first 是空 cell：放棄 split，整列推下一頁/欄
      ctx.warnings.push(
        `[paginate] block#${blockIdx} row#${row.rowIndex} 高度 ${row.height.toFixed(0)}pt `
        + `超過剩餘空間 ${remainingHeightForRow.toFixed(0)}pt；無法 mid-row split，`
        + `整列推下一頁。`,
      );
    }

    pendingRows.push(row);
    pendingHeight += row.height;
  }

  flushTableEntry(/* more = */ false);
}

// ── 工具 ─────────────────────────────────────────────────────────────────

function makeContext(
  section: SectionNode,
  sectionIndex: number,
  startPageNumber: number,
): PaginateContext {
  const pageWidth = section.page.width;
  const pageHeight = section.page.height;
  const m = section.margins;
  const contentWidth = pageWidth - m.left - m.right;
  const contentHeight = pageHeight - m.top - m.bottom;
  const { columnWidths, columnSpaces } = computeColumnLayout(section.columns, contentWidth);
  return {
    pageWidth,
    pageHeight,
    marginTop: m.top,
    marginBottom: m.bottom,
    marginLeft: m.left,
    marginRight: m.right,
    contentWidth,
    contentHeight,
    sectionIndex,
    pageNumber: startPageNumber,
    currentY: 0,
    entries: [],
    pages: [],
    warnings: [],
    columnCount: columnWidths.length,
    columnIndex: 0,
    columnWidths,
    columnSpaces,
    columnSeparator: section.columns?.separator === true && columnWidths.length > 1,
    activeFloats: [],
    lastRowWasImage: false,
    docGridLinePitch: docGridLinePitchOf(section),
    numberingMap: undefined,
    numberingCounter: new NumberingCounterState(),
  };
}

/**
 * Sprint 139：計算段落的 numbering 前綴（若有 numId）。
 *
 * 演化 counter state、展開 lvlText 為字串。回傳 undefined 表示「無前綴」
 * （無 numId、或 numberingMap 未注入、或 lvlText 展開為空）。
 *
 * 跨段落共用同一 counter 實例（cell 內外段落共用、與 ToCanvasEditor Sprint 138 一致）。
 */
function computeNumberingPrefix(
  para: ParagraphNode,
  numbering: NumberingMap | undefined,
  counter: NumberingCounterState,
): NumberingPrefix | undefined {
  if (!numbering || para.props.numId === undefined) return undefined;
  const ilvl = para.props.ilvl ?? 0;
  const abstractNum = numbering.get(para.props.numId);
  const result = counter.advance(para.props.numId, ilvl, abstractNum);
  const text = expandLvlText(result.level.text, result.counters, result.numFmts);
  if (text === '') return undefined;
  // 取首個 RunNode 的 props 當 baseStyle、fallback level.runProps
  const firstRun = para.runs.find((r): r is RunNode => r.type === 'run');
  const baseProps: RunProps = firstRun?.props ?? result.level.runProps ?? {};
  return { text, runProps: baseProps };
}

/**
 * Sprint 6：依 SectionNode.columns 計算每欄寬度與欄間距。
 *
 * 優先順序：
 *   1. 若有 colWidths（個別欄寬）：直接用，缺的補等寬填滿
 *   2. 否則用 count + space 等寬計算
 *   3. count <= 1 或無 columns：單欄
 */
function computeColumnLayout(
  cols: SectionNode['columns'] | undefined,
  contentWidth: Pt,
): { columnWidths: Pt[]; columnSpaces: Pt[] } {
  if (!cols || cols.count <= 1) {
    return { columnWidths: [contentWidth], columnSpaces: [] };
  }

  const count = cols.count;
  const defaultSpace = cols.space ?? 36; // 0.5 inch

  // 個別 colSpaces
  const colSpaces: Pt[] = [];
  for (let i = 0; i < count - 1; i++) {
    colSpaces.push(cols.colSpaces?.[i] ?? defaultSpace);
  }

  // 個別 colWidths
  if (cols.colWidths && cols.colWidths.length > 0) {
    const widths: Pt[] = [];
    for (let i = 0; i < count; i++) {
      widths.push(cols.colWidths[i] ?? 0);
    }
    // 若有 0（缺值），把剩餘 contentWidth 平均分配給 0 的欄位
    const zeros: number[] = [];
    let nonzeroSum = 0;
    for (let i = 0; i < widths.length; i++) {
      if (widths[i] === 0) zeros.push(i);
      else nonzeroSum += widths[i];
    }
    const totalSpace = colSpaces.reduce((a, b) => a + b, 0);
    if (zeros.length > 0) {
      const remaining = Math.max(contentWidth - nonzeroSum - totalSpace, 0);
      const each = remaining / zeros.length;
      for (const idx of zeros) widths[idx] = each;
    }
    return { columnWidths: widths, columnSpaces: colSpaces };
  }

  // 等寬
  const totalSpace = colSpaces.reduce((a, b) => a + b, 0);
  const each = (contentWidth - totalSpace) / count;
  return {
    columnWidths: Array.from({ length: count }, () => each),
    columnSpaces: colSpaces,
  };
}

/** continuous 接續：保留 currentY / entries，只更新 sectionIndex 與 page geometry（理論不變）。*/
function rebindForSection(
  prev: PaginateContext,
  section: SectionNode,
  sectionIndex: number,
): PaginateContext {
  return {
    ...prev,
    sectionIndex,
    // page geometry 用前一節的（continuous 假設相同）；safety check 在 layoutDocument
    pageWidth: prev.pageWidth,
    pageHeight: prev.pageHeight,
    marginTop: prev.marginTop,
    marginBottom: prev.marginBottom,
    marginLeft: prev.marginLeft,
    marginRight: prev.marginRight,
    contentWidth: prev.contentWidth,
    contentHeight: prev.contentHeight,
  };
}

/** 偵測 continuous 是否合法（page geometry 必須相同） */
function samePageGeometry(a: SectionNode, b: SectionNode): boolean {
  return (
    a.page.width === b.page.width
    && a.page.height === b.page.height
    && a.margins.top === b.margins.top
    && a.margins.bottom === b.margins.bottom
    && a.margins.left === b.margins.left
    && a.margins.right === b.margins.right
  );
}

/** evenPage / oddPage：插入空白頁直到 ctx.pageNumber 達到指定 parity。 */
function ensurePageParity(ctx: PaginateContext, kind: 'evenPage' | 'oddPage'): void {
  const wantEven = kind === 'evenPage';
  // 下一頁編號 = ctx.pageNumber（flush 後 currentY 重設、pageNumber 已自增）
  const nextPageNumber = ctx.pageNumber;
  const nextIsEven = nextPageNumber % 2 === 0;
  if ((wantEven && !nextIsEven) || (!wantEven && nextIsEven)) {
    // 插入一頁空白頁
    ctx.pages.push({
      width: ctx.pageWidth,
      height: ctx.pageHeight,
      margins: {
        top: ctx.marginTop,
        bottom: ctx.marginBottom,
        left: ctx.marginLeft,
        right: ctx.marginRight,
      },
      sectionIndex: ctx.sectionIndex,
      pageNumber: ctx.pageNumber,
      entries: [],
    });
    ctx.pageNumber++;
  }
}

function flushPage(ctx: PaginateContext): void {
  const page: Page = {
    width: ctx.pageWidth,
    height: ctx.pageHeight,
    margins: {
      top: ctx.marginTop,
      bottom: ctx.marginBottom,
      left: ctx.marginLeft,
      right: ctx.marginRight,
    },
    sectionIndex: ctx.sectionIndex,
    pageNumber: ctx.pageNumber,
    entries: ctx.entries,
  };
  if (ctx.columnCount > 1) {
    page.columnLayout = buildColumnLayout(ctx);
  }
  ctx.pages.push(page);
  ctx.pageNumber++;
  ctx.entries = [];
  ctx.currentY = 0;
  ctx.columnIndex = 0; // 換頁後從第一欄開始
  // Sprint 18：新頁起點視為「未在 image row 段」
  ctx.lastRowWasImage = false;
}

/** Sprint 10：把 ctx 的多欄資訊組成 Page.columnLayout（含 startX / widths / separator）。 */
function buildColumnLayout(ctx: PaginateContext): NonNullable<Page['columnLayout']> {
  const startX: Pt[] = [];
  let x = ctx.marginLeft;
  for (let i = 0; i < ctx.columnCount; i++) {
    startX.push(x);
    x += ctx.columnWidths[i] ?? 0;
    x += ctx.columnSpaces[i] ?? 0;
  }
  return {
    count: ctx.columnCount,
    startX,
    widths: [...ctx.columnWidths],
    separator: ctx.columnSeparator,
  };
}

function sumHeights(lines: Line[]): Pt {
  let h = 0;
  for (const l of lines) h += l.height;
  return h;
}
void sumHeights;
