/**
 * Layout Engine 共用型別（Sprint 2）
 *
 * 設計取自 Knuth-Plass：item = Box | Glue | Penalty。Sprint 2 的 LineBreaker 是
 * 貪婪實作，但 item 模型一開始就用 K-P 結構，以便日後切換不必改 BoxBuilder。
 *
 * 全部單位：pt（與 ooxml/ast/types.ts 一致）。Px 換算交給 Renderer。
 */

import type { ParagraphProps, RunProps, HyperlinkInfo, FieldNode } from '../ooxml/ast/types';
import type { Pt } from '../ooxml/ast/types';

// ── Item 模型（K-P breakpoint algebra）──────────────────────────────────────

/** 內容盒：固定寬度的文字 / inline 圖片，斷行時不可拆分（除非含 hyphenation 點，本期不做）。*/
export interface Box {
  kind: 'box';
  width: Pt;
  height: Pt;
  /** 內容 fingerprint，方便 debug / snapshot 比對。圖片填 `image:rId`。*/
  text: string;
  /** 文字屬性（fontSize / bold / color 等），轉發給 Renderer。*/
  runProps: RunProps;
  /** 是否為 inline image（Renderer 用來 dispatch image draw）*/
  isImage?: boolean;
  /** image rId（isImage=true 時有值）*/
  imageRId?: string;
  /** Sprint 40：image srcRect（DrawingML `<a:srcRect>` 裁切；isImage=true 時可有）*/
  imageSrcRect?: import('../ooxml/ast/types').ImageSrcRect;
  /** 超連結資訊（Run 被 hyperlink 包裹時填入）*/
  hyperlink?: HyperlinkInfo;
  /** Sprint 175：追蹤修訂標記（Run 被 `<w:ins>`/`<w:del>` 包裹時填入；Renderer 用來繪插入底線 / 刪除刪除線）*/
  revision?: import('../ooxml/ast/types').RunRevision;
  /**
   * Sprint 10：欄位類型標記（PAGE / NUMPAGES / DATE 等）。
   *
   * BoxBuilder 在處理 FieldNode 時填入；Paginator 排版完所有頁後做 post-pass，
   * 對 fieldType='PAGE' 的 Box 把 text 改成所屬 page.pageNumber，
   * 對 fieldType='NUMPAGES' 的 Box 把 text 改成 layout.pages.length。
   *
   * undefined 表示一般文字 box，不做後處理。
   *
   * Sprint 163：型別對齊 AST `FieldNode['fieldType']`（11 型，含 Sprint 123 擴的
   * SEQ/TOC/REF/HYPERLINK/STYLEREF）。Paginator `resolveFieldValues` 只 post-pass
   * PAGE/NUMPAGES/DATE/TIME/AUTHOR/FILENAME，其餘型別保留原 placeholder。
   */
  fieldType?: FieldNode['fieldType'];
}

/** 伸縮膠：可被壓縮 / 撐開。空白 / 中文字間皆為 glue。*/
export interface Glue {
  kind: 'glue';
  width: Pt;          // ideal width
  stretch: Pt;        // 最多撐開
  shrink: Pt;         // 最多壓縮
  /** 標記為「中文字間」glue（避頭尾規則用）*/
  isCjkBreak?: boolean;
  /**
   * Sprint 161：標記為 tab（來自 `<w:tab/>` → run text 的 `\t`）的 glue。
   *
   * BoxBuilder 一律先以空白寬度建立（行為與 Sprint 0-160 一致）；
   * LineBreaker 在 `LineBreakOptions.defaultTabStop` 有提供時、才把 isTab glue
   * 的寬度重算為「推進到下一個 tab stop」。未提供 → 維持空白寬度。
   */
  isTab?: boolean;
}

/** 強制 / 可選斷點。-Infinity = 強制斷，+Infinity = 禁止斷。*/
export interface Penalty {
  kind: 'penalty';
  width: Pt;          // 斷在此處時要塞的字（連字符等），通常 0
  cost: number;       // -Infinity / +Infinity / 中等成本
  flagged?: boolean;
  /**
   * Sprint 7：強制斷的類型（僅 cost=-Infinity 且 flagged=true 時有意義）。
   *
   * - `page`：對應 `<w:br type="page">`，Paginator 看到後 flushPage
   * - `column`：對應 `<w:br type="column">`，Paginator 看到後 nextColumnOrPage
   * - undefined：等同於普通強制斷行（不換頁、不換欄）
   */
  breakKind?: 'page' | 'column';
}

export type LayoutItem = Box | Glue | Penalty;

/** 段落層級的物件（送進 LineBreaker 之前已打包好 props 與 items）*/
export interface ParagraphInput {
  items: LayoutItem[];
  props: ParagraphProps;
  /** 預設 fontSize（pt），用於空段落算 line height */
  defaultFontSize: Pt;
  /** 段落屬於哪個 styleId（snapshot 用）*/
  styleId?: string;
  /** Source paragraph index（debug 用）*/
  sourceIndex: number;
}

// ── 斷行輸出 ──────────────────────────────────────────────────────────────

/** 一行排版結果（已決定 baseline / leading）*/
export interface Line {
  /** 此行包含的 items（已 strip 行首/尾 trim 的 glue）*/
  items: LayoutItem[];
  /** 行寬度總和（已含 stretch/shrink 後）*/
  width: Pt;
  /** 行高（包含 leading；行間距）*/
  height: Pt;
  /**
   * Sprint 47：行高「未經 docGrid snap」的版本（= applySpacingLine 後、applyDocGridSnap 前）。
   *
   * 用於 TableLayout val-as-min 的比較基準——docGrid snap 會把 exact 行上推到 pitch
   * 整數倍（如 exact 20pt → 36pt），使「row natural」被人為撐高、卡住 `trHeight val >
   * natural` 判斷（Sprint 46 診斷的監造會議記錄過分頁真根因）。
   * 未設時 caller 應 fallback 用 `height`。
   */
  heightUnsnapped?: Pt;
  /** 基線距行頂的距離 */
  baseline: Pt;
  /** 行被指派的對齊方式 */
  alignment: 'left' | 'center' | 'right' | 'justify' | 'distribute';
  /** 是否是該段落的最後一行（justify 時最後一行不撐滿）*/
  isLastLine: boolean;
  /** 段落 source index（widow/orphan 控制用）*/
  paragraphIndex: number;
  /** 此行原段落的 props 摘錄（borders / shading / numId 渲染用）*/
  paragraphProps: ParagraphProps;
  /**
   * Sprint 6：此行相對欄起點的 X 偏移（pt）。
   *
   * 由 LineBreaker 從 `getLineXOffset` 取得（wrapSquare 左 float 時推右）；
   * 預設 0。Paginator 在 LinePageEntry.x = columnX + indentLeft + xOffset。
   */
  xOffset?: Pt;
  /**
   * Sprint 7：此行結束後是否強制換頁/換欄。
   *
   * - 'page'：Paginator 在加入此行後 flushPage（對應 `<w:br type="page">`）
   * - 'column'：Paginator nextColumnOrPage（對應 `<w:br type="column">`）
   * - undefined：正常推進
   */
  forcedBreakAfter?: 'page' | 'column';
}

// ── Pagination 輸出 ──────────────────────────────────────────────────────

/** 一頁排版結果。座標都相對於 page top-left。*/
export interface Page {
  /** 頁面尺寸 */
  width: Pt;
  height: Pt;
  /** 內容區（margin-box），所有 entries 的 y 已加上 marginTop 偏移 */
  margins: { top: Pt; bottom: Pt; left: Pt; right: Pt };
  /** 此頁所屬節索引（從 SectionNode 切出）*/
  sectionIndex: number;
  /** 頁碼（1-based） */
  pageNumber: number;
  /** 此頁被排入的內容（Line / 表格 / 圖片）*/
  entries: PageEntry[];
  /**
   * Sprint 10：此頁的多欄佈局資訊（給 Renderer 畫欄分隔線用）。
   *
   * 單欄頁面 undefined。多欄頁面填入：
   *   - count: 欄數
   *   - startX: 每欄起點 X（page-local，含 marginLeft）；長度 = count
   *   - widths: 每欄寬度；長度 = count
   *   - separator: 是否畫垂直分隔線（OOXML w:cols w:sep）
   */
  columnLayout?: {
    count: number;
    startX: Pt[];
    widths: Pt[];
    separator: boolean;
  };
}

export type PageEntry =
  | LinePageEntry
  | TablePageEntry
  | TableLayoutEntry
  | ImagePageEntry
  | FloatImageEntry;

interface BasePageEntry {
  /** 距頁面 top 的位移（含 margin） */
  y: Pt;
  /** 距頁面 left 的位移（含 margin） */
  x: Pt;
  /** 此 entry 的高度 */
  height: Pt;
  /** 此 entry 的寬度 */
  width: Pt;
}

export interface LinePageEntry extends BasePageEntry {
  kind: 'line';
  line: Line;
}

/** Sprint 2 placeholder：一整張表用 estimated height 占位。
 *  Sprint 3 起以 TableLayoutEntry 取代；保留 type 供超大表 fallback。*/
export interface TablePageEntry extends BasePageEntry {
  kind: 'table-placeholder';
  rowCount: number;
  colCount: number;
  /** 表格在 source AST 的 block index（AST diff 對照用）*/
  blockIndex: number;
}

/** Sprint 3：cell-level 排版完成的表格 entry（可跨頁）。 */
export interface TableLayoutEntry extends BasePageEntry {
  kind: 'table';
  /** 表格在 source AST 的 block index */
  blockIndex: number;
  /** 整張表的 grid 寬度（pt 為單位）*/
  grid: Pt[];
  /** 此 entry 內含的 row layouts（已扣除前面頁顯示的 row 後剩下的）*/
  rows: RowLayout[];
  /** 此 entry 是否為跨頁延續（true 時會在頂端重複 tblHeader 列）*/
  isContinuation: boolean;
  /** 此 entry 是否還會繼續到下一頁 */
  hasMore: boolean;
}

/** 一列排版結果。 */
export interface RowLayout {
  /** 此列在原 TableNode rows 內的 index */
  rowIndex: number;
  /** 此列實際高度（cells 中最高者） */
  height: Pt;
  /** 是否是 tblHeader（跨頁時要重複） */
  isHeader: boolean;
  /** cantSplit：此列不可被切斷（Sprint 3 沿用 row-level 切，cell 內部不切）*/
  cantSplit: boolean;
  cells: CellLayout[];
  /**
   * Sprint 17：此列是否含 inline image（Box.isImage=true 的內容）。
   *
   * 由 layoutCell / layoutRow 計算：cell.blocks → CellBlock(kind='lines') → line.items
   * 中是否存在 isImage box。Paginator 用此判定是否要套用 image-row break heuristic
   * （規則 R1，見 docs/word_pagebreak_rules.md §1）。
   */
  containsImage: boolean;
}

/** Cell 排版結果（含內部 paragraph + 巢狀表格 layout）。 */
export interface CellLayout {
  /** 此 cell 在 row 中的 index */
  cellIndex: number;
  /** Cell 起始 grid column（0-based） */
  gridCol: number;
  /** 跨多少 grid column */
  gridSpan: number;
  /** 跨多少列（vMerge anchor 才會 > 1） */
  rowSpan: number;
  /** 是否是 vMerge 的延續（不繪內容，但保留邊框決策資訊） */
  isContinuation: boolean;
  /** Cell 寬度（pt，含 padding，已加總 gridSpan 範圍）*/
  width: Pt;
  /** Cell 高度（內部 blocks 總和 + cellMargins 上下）*/
  height: Pt;
  /**
   * 內部排版好的 lines（用 LineBreaker 對 cell paragraph 跑出來）。
   *
   * Sprint 5 模型；Sprint 6 仍保留以維持 Sprint 5 unit tests 不破。
   * 新版 Renderer 應使用 `blocks` 取得正確視覺順序。
   */
  lines: Line[];
  /**
   * Sprint 5：巢狀表格陣列（cell.content 內 TableNode 遞迴 layout 結果）。
   * Sprint 6 仍保留以維持 Sprint 5 unit tests 不破。
   * 新版 Renderer 應使用 `blocks` 取得正確視覺順序。
   */
  nestedTables?: NestedTableInCell[];
  /**
   * Sprint 6：cell 內按原始 source order 排列的 blocks（lines / nestedTable 交錯）。
   *
   * 解決 Sprint 5 的「先 lines、後 nestedTables」簡化模型導致的混排順序錯誤。
   * Renderer 視 blocks 順序逐塊繪製即還原 Word 視覺順序。
   *
   * `lines` 與 `nestedTables` 仍同步保留以維持向下相容。
   */
  blocks: CellBlock[];
  /** Cell padding：實際畫內容時要扣掉的內邊距 */
  padding: { top: Pt; bottom: Pt; left: Pt; right: Pt };
  /** Cell 對齊（垂直） */
  vAlign: 'top' | 'center' | 'bottom';
  /**
   * Sprint 42：blocks 內容總高度（單位 Pt）。
   *
   * = Σ line.height（lines block）+ Σ nestedTable.totalHeight
   * 用於 renderCell 依 vAlign 計算內容區 Y 起點：
   *   - top（預設）：yCursor = y + padding.top
   *   - center：yCursor = y + padding.top + max(0, (availableH - contentHeight) / 2)
   *   - bottom：yCursor = y + rowHeight - padding.bottom - contentHeight
   *
   * 由 layoutCell pass 預算。若 cell.vAlign='top'，此值可不參與計算（保持向下相容）。
   */
  contentHeight: Pt;
  /**
   * Sprint 47：blocks 內容總高度「未經 docGrid snap」的版本。
   *
   * = Σ line.heightUnsnapped（lines block）+ Σ nestedTable.height（table block 不 snap）。
   * 用於 layoutRow 的 val-as-min 比較基準（見 [[Line.heightUnsnapped]]）。
   */
  contentHeightUnsnapped: Pt;
  /**
   * Sprint 34：文字方向（V-suffix = 旋轉式垂直 glyph，最常見 tbRlV）。
   *
   * undefined / lrTb / tbRl / btLr：renderer 走原本水平流程。
   * lrTbV / tbRlV / tbLrV：renderer 對 cell 內容區套 ctx.translate + rotate；
   * layoutCell 已用「假設 cell 高度無限」做 break 並把 line.width 累加為 cell.height。
   */
  textDirection?: 'lrTb' | 'tbRl' | 'btLr' | 'lrTbV' | 'tbRlV' | 'tbLrV';
  /**
   * Sprint 8：cell 已 resolve 的 effective borders（4 邊）。
   *
   * 由 layoutCell 從原 CellNode.props.borders 透傳；BorderConflictResolver
   * 已在 TableParser 階段 mutate 過 cellNode.props.borders 為 resolved 結果，
   * 因此這裡直接複製即可（淺拷貝，不再二次解析）。
   *
   * Renderer 用此繪格線；undefined 表示該 cell 無顯式邊框（不畫）。
   */
  borders?: import('../ooxml/ast/types').CellBorders;
  /**
   * Sprint 9：cell 背景填色（OOXML w:shd）。
   *
   * 從原 CellNode.props.shading 透傳；Renderer 在繪 cell 內容前 fillRect 全 cell。
   * undefined 表示無背景色。
   */
  shading?: { fill?: import('../ooxml/ast/types').HexColor; color?: import('../ooxml/ast/types').HexColor; pattern?: string };
  /**
   * Sprint 37：cell 內 floatImage（wp:anchor）— 由 layoutCell 從 paragraph.runs 提取
   * 並算成 cell-relative 絕對位置（xRel/yRel = cell 起點左上 + padding 為原點）。
   *
   * Renderer 在 cell 邊框與背景之後、文字之上（除非 behindDoc）繪製。
   * 不參與 LineBreaker / 行寬計算，避免 Sprint 2 把 floatImage 當 inline Box 推進段內
   * 造成 column 內容位置全偏（Sprint 36 grid analysis 找到的真根因）。
   */
  floats?: CellFloat[];
}

/**
 * Sprint 37：cell 內 floatImage（`<wp:anchor>` + `<a:blip>`）排版結果。
 * Sprint 38：擴展為 union，加入 floatTextBox（`<wp:anchor>` + `<wps:txbx>`）。
 *
 * 共用 xRel / yRel cell-relative 絕對位置語意；node 型別不同：
 *   - FloatImageNode：渲染走 ctx.drawImage(rId)
 *   - FloatTextBoxNode：渲染走 ctx.fillText（內部 paragraphs 用 LineBreaker + 逐行繪製）
 */
export type CellFloat =
  | { node: import('../ooxml/ast/types').FloatImageNode; xRel: Pt; yRel: Pt }
  | { node: import('../ooxml/ast/types').FloatTextBoxNode; xRel: Pt; yRel: Pt };

/** Cell block：cell 內單一 paragraph 的 lines 或單一巢狀表格。 */
export type CellBlock =
  | { kind: 'lines'; sourceIndex: number; lines: Line[]; height: Pt }
  | { kind: 'table'; sourceIndex: number; table: NestedTableInCell };

/** Sprint 5：cell 內巢狀表格的排版結果。 */
export interface NestedTableInCell {
  /** 內含 column widths */
  columnWidths: Pt[];
  /** 內含 rows（已 cell-level 排版） */
  rows: RowLayout[];
  /** 此巢狀表格在 cell 內的高度（rows 高度總和） */
  height: Pt;
  /** 在 source cell.content 內的 block index（debug 用） */
  blockIndex: number;
}

export interface ImagePageEntry extends BasePageEntry {
  kind: 'image';
  rId: string;
  /** Sprint 40：DrawingML `<a:srcRect>` 裁切（如有） */
  srcRect?: import('../ooxml/ast/types').ImageSrcRect;
}

/** Sprint 4：FloatImage entry（wrapNone / wrapTopAndBottom 等浮動圖片）。
 *  Renderer 用 wrapType 判斷：
 *    - none / behindText / inFrontOfText：圖層獨立繪製，不影響內文位置
 *    - topAndBottom：上下保留垂直空間（Paginator 已扣 currentY）
 *    - square / tight / through：Sprint 4 暫降級為 topAndBottom，留 Sprint 5 行寬動態
 */
export interface FloatImageEntry extends BasePageEntry {
  kind: 'floatImage';
  rId: string;
  blockIndex: number;
  wrapType: 'none' | 'square' | 'tight' | 'through' | 'topAndBottom'
    | 'behindText' | 'inFrontOfText';
  /** behindDoc：圖片在文字後方（z-index 負方向）*/
  behindDoc: boolean;
  /** Sprint 40：DrawingML `<a:srcRect>` 裁切（如有） */
  srcRect?: import('../ooxml/ast/types').ImageSrcRect;
}

// ── 全文件 ───────────────────────────────────────────────────────────────

export interface DocumentLayout {
  pages: Page[];
  /** 引擎在 layout 時收集的警告（如：fixture 含不支援功能）*/
  warnings: string[];
}

// ── 設定 / 注入 ───────────────────────────────────────────────────────────

/** TextMetrics 介面：給 BoxBuilder 估文字寬度。Sprint 2 預設 EstimateMetrics，
 *  日後可注入 HarfBuzz 結果（見 font/ShapingEngine.ts）。 */
export interface TextMetrics {
  /**
   * 估計一段文字在指定字型 / 字級下的寬度（pt）。
   * 必須是純函式（無 side effect），LineBreaker 會 cache。
   */
  measureWidth(text: string, props: RunProps): Pt;
  /** 行高（含 leading）。預設用 1.2 * fontSize；可被覆寫。*/
  measureLineHeight(props: RunProps): Pt;
}

export interface LayoutOptions {
  /** 文字測量；不傳則用 EstimateMetrics */
  metrics?: TextMetrics;
  /** 寡行（widow，段落最後一行落到下一頁）控制：至少保留 N 行在當頁。預設 2。*/
  widowMin?: number;
  /** 孤行（orphan，段落首行被孤留在當頁）控制：至少 push N 行到下一頁前。預設 2。*/
  orphanMin?: number;
  /**
   * Sprint 11：頁首內容 map（rId → HeaderFooterContent）。
   *
   * 來源 = `DocumentNode.headers`。沒傳 / 空 map → Paginator 不繪 header。
   * 對應的 `SectionNode.headerRefs.{default,first,even}` 決定每頁用哪個 rId。
   */
  headers?: Map<string, import('../ooxml/ast/types').HeaderFooterContent>;
  /** Sprint 11：頁尾內容 map（rId → HeaderFooterContent）。 */
  footers?: Map<string, import('../ooxml/ast/types').HeaderFooterContent>;
  /**
   * Sprint 12：文件元資料，用於 DATE / TIME / AUTHOR / FILENAME 等欄位真值替換。
   *
   * - date / time：未提供時用 `new Date()`
   * - author / filename / title：caller 從 docProps/core.xml + 上傳檔名注入
   *
   * Paginator post-pass 用 `resolveFieldValues` 把對應 `Box.fieldType` 的 text
   * 換成這份 metadata 的對應值（PAGE/NUMPAGES 仍用 page.pageNumber/總頁數）。
   */
  documentMetadata?: {
    /** 預設用 `new Date()`；測試 / 強制固定值時可覆寫 */
    now?: Date;
    /** Date format string；undefined → 'yyyy/MM/dd' */
    dateFormat?: string;
    /** Time format string；undefined → 'HH:mm' */
    timeFormat?: string;
    author?: string;
    filename?: string;
    title?: string;
  };
  /**
   * Sprint 17 + 18：image-row break heuristic 門檻（規則 R1，transition 變體）。
   *
   * 觸發條件（4 件齊全）：
   *   (a) row.containsImage && row.cantSplit && row.height ≥ contentHeight × imageRowBreakRatio
   *   (b) imageRowBreakRatio > 0
   *   (c) 當前頁已有內容（pendingRows 或 ctx.entries 任一非空）
   *   (d) std → image 進入 OR image → std 離開的 transition
   *       （透過 ctx.lastRowWasImage 追蹤；連續 image row 不破，避免 over-paginate）
   *
   * - 預設 **0.34**（Sprint 18 grid search 全 42 fixture 矩陣最佳值）
   *   - mismatched 17→13、totalDelta -26→-14、sumAbsDelta 26→14（-46%）
   *   - 零 regression：4 個 04_with_image fixture 從 -3 完美對齊 0
   * - 設 0 = OFF（保留 Sprint 16 行為）
   * - 設 > 0.4 等同 0（fixture 中無 row.height ≥ 0.4 × contentHeight 觸發）
   *
   * 詳細推導見 [docs/sprint18_pagination_transition.md §3](../docs/sprint18_pagination_transition.md)
   * 與 [docs/word_pagebreak_rules.md §1](../docs/word_pagebreak_rules.md)。
   */
  imageRowBreakRatio?: number;
  /**
   * Sprint 29：當前 section 的 docGrid linePitch（pt），用於 cell 內 LineBreaker 行高 snap。
   *
   * Paginator 將 ctx.docGridLinePitch 透傳到 TableLayout.layoutTable/layoutCell，
   * 確保表格 cell 內容也遵循 docGrid 規則。
   *
   * - 0 / undefined：不 snap
   * - > 0：每行 height 經 spacing 規則計算後 ceil 到 linePitch 整數倍
   */
  docGridLinePitch?: Pt;
  /**
   * Sprint 139：文件 NumberingMap（來自 DocumentNode.numbering）。
   *
   * 提供後、Paginator/TableLayout 對含 `props.numId` 的段落會：
   *   1. 透過 NumberingCounterState 演化計數器（跨 section/cell 共用 state）
   *   2. expandLvlText 展開為前綴字串（如「1.」「（一）」「第一章」）
   *   3. 在 buildParagraph 時 prepend 為前綴 Box + tab Glue
   *
   * 省略（undefined）→ 維持 Sprint 138 前行為（VR 不顯示編號）。
   *
   * 紀律 #1.b 候選驗證:本欄位是 opt-in、layout 路徑 wire-up 翻車時可全 revert byte-identical。
   */
  numbering?: import('../ooxml/ast/types').NumberingMap;
  /**
   * Sprint 139：internal — Paginator 透傳給 TableLayout.layoutCell 的 counter 實例。
   *
   * **不要由 caller 設定**；Paginator.laySingleTable 自動從 ctx.numberingCounter 注入，
   * 讓 cell 內 paragraph 與 body 段落共用同一 counter state（OOXML §17.9 預期行為）。
   *
   * undefined → TableLayout 不 emit numbering prefix（保 backward compat）。
   */
  _numberingCounter?: import('../ooxml/numbering').NumberingCounterState;
  /**
   * Sprint 162：預設 tab stop 間距（pt，來自 `DocumentNode.settings.defaultTabStop`、
   * OOXML §17.15.1.25；Word 預設 720 twip = 36pt）。
   *
   * 提供後、Paginator/TableLayout 把它透傳給 `LineBreakOptions.defaultTabStop`，
   * LineBreaker 在 `makeLine` 把 `\t`（isTab glue）寬度重算為「推進到下一個 tab stop」
   * （Sprint 161 落地的解析引擎）。
   *
   * 省略（undefined）/ 0 → tab glue 維持空白寬度（Sprint 0-161 行為）。
   * 紀律 #1.b：本欄位 opt-in、layout 路徑 wire-up；caller 不傳 → VR baseline byte-identical。
   */
  defaultTabStop?: Pt;
  /**
   * Sprint 169：`<w:framePr>` 浮動段落框 wire-up 開關（opt-in、預設 false）。
   *
   * 提供 `true` 後、Paginator 對連續且 framePr 相同的段落（`ParagraphProps.framePr`）：
   *   1. 從正常垂直流抽出、合併為單一 frame group
   *   2. frame 內容子排版求寬高、依 hAnchor/vAnchor + x/y 偏移定出絕對位置
   *   3. 各行以絕對座標 emit 為 `LinePageEntry`
   *   4. Sprint 169：保留垂直空間（topAndBottom-like、不重疊）；Sprint 170 升級為
   *      `wrap=around` 排除區、後續內文側繞
   *
   * 省略（undefined）/ false → framePr 段落走一般 `layParagraph`、與 Sprint 0-168
   * 行為 byte-identical（Strategy C；framePr probe Sprint 168、user 2026-05-21 選
   * opt-in 實作）。生效驗證待 decision B（OnlyOffice goldens 重生）。
   */
  enableFramePr?: boolean;
}
