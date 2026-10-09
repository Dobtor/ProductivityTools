/**
 * OOXML AST 型別定義
 *
 * 設計原則：
 * - Parser 輸出已解析完畢的扁平結構，所有樣式繼承鏈已展開
 * - 所有長度單位統一為 pt（點），Renderer 根據 DPI 換算 px
 * - Table Cell 的 gridCol / gridSpan / rowSpan 由 GridResolver 預先計算
 * - LineMetrics 介面在 Phase 1 預留，Phase 2 由 HarfBuzz WASM 實作
 */

// ── 基礎單位型別 ──────────────────────────────────────────────────────────────

export type Pt = number;      // 點（points），所有長度的標準單位
export type HexColor = string; // "RRGGBB"（不含 #），或 "auto"

// ── 邊框 ──────────────────────────────────────────────────────────────────────

export type BorderStyle =
  | 'none' | 'single' | 'double' | 'thick'
  | 'dashed' | 'dotted' | 'dashDot' | 'dashDotDot'
  | 'triple' | 'thinThickSmallGap' | 'thickThinSmallGap'
  | string;

export interface BorderDef {
  style: BorderStyle;
  width: Pt;        // w:sz / 8（原始單位為 1/8 pt）
  color: HexColor;
  space?: Pt;       // w:space
}

export interface CellBorders {
  top?: BorderDef;
  bottom?: BorderDef;
  left?: BorderDef;
  right?: BorderDef;
  insideH?: BorderDef;
  insideV?: BorderDef;
}

// ── 行高度量介面（Phase 1 預留，Phase 2 由 HarfBuzz WASM 精確實作）────────────
//
// 重要：Layout Engine 必須只透過此介面取得字型度量，
// 不可直接呼叫 ctx.measureText()，確保 Phase 2 切換時不需重寫 Layout Engine。

export interface LineMetrics {
  fontFamily: string;
  fontSize: Pt;
  ascender: Pt;     // 基線以上高度
  descender: Pt;    // 基線以下深度（正值）
  lineGap: Pt;      // 字型建議的額外行距
  // Phase 1：以 ctx.measureText() 近似填入
  // Phase 2：改由 opentype.js 或 HarfBuzz WASM 從字型檔直接讀取
}

// ── Run（文字片段）屬性 ───────────────────────────────────────────────────────

export type VertAlign = 'baseline' | 'superscript' | 'subscript';
export type Underline =
  | 'none' | 'single' | 'double' | 'dotted' | 'dashed'
  | 'words' | 'thick' | 'wave'
  | string;

export interface RunProps {
  fontFamily?: string;          // w:ascii — 西文字型
  fontFamilyEastAsia?: string;  // w:eastAsia — CJK 字型
  fontFamilyHAnsi?: string;     // w:hAnsi — High ANSI 字型（西方擴展字符集）
  fontFamilyCs?: string;        // w:cs — Complex Script 字型（阿拉伯/希伯來等）
  fontSize?: Pt;
  bold?: boolean;
  italic?: boolean;
  underline?: Underline;
  strike?: boolean;
  dstrike?: boolean;            // 雙刪除線
  color?: HexColor;
  highlight?: HexColor;
  vertAlign?: VertAlign;
  spacing?: Pt;                 // 字元間距 w:spacing
  lang?: string;                // w:lang val
  /** Sprint 293：`<w:rPrChange>` run 屬性修訂（OOXML §17.13.5.31）。 */
  rPrChange?: TrackChangeMeta;
}

/**
 * Sprint 293：追蹤修訂共用 metadata（author / date / id）。
 *
 * 用於 pPrChange / rPrChange / cellIns / cellDel / cellMerge 等屬性級或
 * 結構級追蹤修訂。與 RunRevision（包裹 run 的 ins/del/moveFrom/moveTo）不同，
 * 這些 *Change 為「就地註記」改變了什麼，不展開 runs。
 *
 * 紀律 #21 capture-only：parser 補完整、writer/render 不消費。
 */
export interface TrackChangeMeta {
  /** w:author 修訂者 */
  author?: string;
  /** w:date 修訂時間（ISO 字串、capture raw） */
  date?: string;
  /** w:id 修訂編號 */
  id?: number;
}

// ── 段落屬性 ──────────────────────────────────────────────────────────────────

export type Alignment = 'left' | 'center' | 'right' | 'justify' | 'distribute';
export type LineSpacingRule = 'auto' | 'exact' | 'atLeast';

export interface ParagraphProps {
  alignment?: Alignment;
  indent?: {
    left?: Pt;
    right?: Pt;
    firstLine?: Pt;   // 正值 = 縮排，負值 = 懸掛
    hanging?: Pt;     // w:hanging（等同負 firstLine）
  };
  spacing?: {
    before?: Pt;
    after?: Pt;
    line?: { rule: LineSpacingRule; value: Pt; };
  };
  borders?: {
    top?: BorderDef;
    bottom?: BorderDef;
    left?: BorderDef;
    right?: BorderDef;
  };
  shading?: {
    fill?: HexColor;
    color?: HexColor;
    pattern?: string;
  };
  keepNext?: boolean;
  keepLines?: boolean;
  pageBreakBefore?: boolean;
  /**
   * Sprint 29：`<w:snapToGrid w:val="0"/>` 顯式關閉時 false；
   * 未設或 val=1 為 true（OOXML §17.3.1.32 預設）。
   * 僅當 section.docGrid.type !== 'default' 時對 line 高度產生影響。
   */
  snapToGrid?: boolean;
  numId?: number;    // 清單編號 ID（來自 numbering.xml）
  ilvl?: number;     // 清單縮排層級（0-based）
  tabs?: Array<{ pos: Pt; align: 'left' | 'right' | 'center' | 'decimal'; leader?: string; }>;
  /**
   * Sprint 134：`<w:textAlignment w:val="..."/>` 文字行內垂直對齊（ECMA-376 §17.3.1.36）。
   *
   *   - 'auto'：依字型 metric 自動（預設）
   *   - 'top'：頂部對齊
   *   - 'center'：垂直置中
   *   - 'baseline'：基線對齊
   *   - 'bottom'：底部對齊
   *
   * 影響行內混合不同字型大小 / 數學符號 / 圖片時 baseline 位置。
   * Layout 階段消費；parser 僅 capture。
   */
  textAlignment?: 'auto' | 'top' | 'center' | 'baseline' | 'bottom';
  /**
   * Sprint 134：`<w:framePr/>` 段落框基礎屬性（ECMA-376 §17.3.1.11）。
   *
   * Word 「位置與大小固定的浮動段落」（如 drop cap、邊欄注釋）。
   * 罕見於 ChienYi 監造文件、但若 fixture 出現需 capture 避免遺失資料。
   *
   * 當前只 capture 主流位置 / 大小 / 環繞屬性；w:dropCap / w:lines / w:anchorLock 等進階 defer。
   */
  framePr?: {
    width?: Pt;
    height?: Pt;
    hRule?: 'auto' | 'atLeast' | 'exact';
    hSpace?: Pt;
    vSpace?: Pt;
    /** w:wrap：around / notBeside / through / tight / none */
    wrap?: 'around' | 'notBeside' | 'through' | 'tight' | 'none';
    /** w:hAnchor：margin / page / text */
    hAnchor?: 'margin' | 'page' | 'text';
    /** w:vAnchor：margin / page / text */
    vAnchor?: 'margin' | 'page' | 'text';
    /** w:xAlign：left / center / right / inside / outside */
    xAlign?: 'left' | 'center' | 'right' | 'inside' | 'outside';
    /** w:yAlign：top / center / bottom / inside / outside / inline */
    yAlign?: 'top' | 'center' | 'bottom' | 'inside' | 'outside' | 'inline';
    x?: Pt;   // w:x 絕對位置（與 xAlign 互斥）
    y?: Pt;   // w:y 絕對位置（與 yAlign 互斥）
  };
  /** Sprint 293：`<w:pPrChange>` 段落屬性修訂（OOXML §17.13.5.27）。 */
  pPrChange?: TrackChangeMeta;
}

// ── 文件內嵌元素（Inline Nodes）──────────────────────────────────────────────

/**
 * 超連結資訊（OOXML w:hyperlink 元素的解析結果，ECMA-376 §17.16.22）。
 *
 * 來源組合：
 *   - External URL（rId 透過 .rels 解析為 http(s):// URL）：url 有值
 *   - 文件內 anchor（w:anchor="bookmarkName"）：anchor 有值，url 通常無
 *   - External + anchor 共存：跨文件指定位置（rare 但合法）
 *   - rels 損壞時：url 為 undefined、rId 保留供下游診斷
 *
 * Sprint 126 — 擴充 hyperlink rels 完整覆蓋：
 *   - tgtFrame：HTML 風格 target frame（_blank / _self / _parent / _top / 自訂 frame 名）
 *   - history：是否計入瀏覽歷史（Word 視為「已造訪」）
 *   - docLocation：替代文件位置（早期 Word 跨文件連結）
 */
export interface HyperlinkInfo {
  rId?: string;          // 原始關係 ID（External 連結時有）
  url?: string;          // 從 document.xml.rels 解析的 External URL
  anchor?: string;       // 文件內 bookmark 名稱（w:anchor）
  tooltip?: string;      // w:tooltip 滑鼠提示
  tgtFrame?: string;     // Sprint 126 — w:tgtFrame target 視窗
  history?: boolean;     // Sprint 126 — w:history（"1" / "true" → true，"0" / "false" → false）
  docLocation?: string;  // Sprint 126 — w:docLocation 跨文件位置
}

/** 文字 Run */
export interface RunNode {
  type: 'run';
  text: string;
  props: RunProps;
  metrics?: LineMetrics; // Phase 1 為 undefined，Phase 2 填入
  hyperlink?: HyperlinkInfo; // 此 Run 被 <w:hyperlink> 包裹時填入
  /** Sprint 174：此 Run 被 `<w:ins>` / `<w:del>` 追蹤修訂標記包裹時填入。 */
  revision?: RunRevision;
}

/**
 * Sprint 174（Phase 5.4 追蹤修訂）：run 的追蹤修訂標記
 * （OOXML §17.13.5.18 / §17.13.5.14 / §17.13.5.22 / §17.13.5.25）。
 *
 * - `<w:ins>` 包裹的 run = 插入
 * - `<w:del>` 包裹的 run = 刪除（內含 `<w:delText>`）
 * - Sprint 290 補：`<w:moveFrom>` 包裹的 run = 移動來源（被移走的原文）
 * - Sprint 290 補：`<w:moveTo>` 包裹的 run = 移動目的地（移動後的位置）
 *
 * capture-only —— render（插入底線 / 刪除刪除線 / move 標記）留後續 sprint。
 */
export interface RunRevision {
  /** 'ins' 插入 / 'del' 刪除 / 'moveFrom' 移動來源 / 'moveTo' 移動目的（Sprint 290） */
  type: 'ins' | 'del' | 'moveFrom' | 'moveTo';
  /** `w:author` 修訂者。 */
  author?: string;
  /** `w:date` 修訂時間（ISO 字串、capture raw、未轉 Date）。 */
  date?: string;
  /** `w:id` 修訂編號。 */
  id?: number;
}

/** 欄位（PAGE、DATE、SEQ、TOC 等）*/
export interface FieldNode {
  type: 'field';
  instruction: string;  // 原始 field instruction，例如 " PAGE " 或 " DATE \\@ \"yyyy/MM/dd\" "
  // Sprint 123：擴充 SEQ / TOC / REF / HYPERLINK / STYLEREF 五型（涵蓋規畫書 §11.1 條列）
  fieldType:
    | 'PAGE' | 'NUMPAGES'
    | 'DATE' | 'TIME'
    | 'AUTHOR' | 'FILENAME'
    | 'SEQ' | 'TOC' | 'REF' | 'HYPERLINK' | 'STYLEREF'
    | 'unknown';
  cachedValue?: string; // w:fldSimple 內 / fldChar 複合的 w:t 快取值
}

/** 換行 */
export interface BreakNode {
  type: 'break';
  breakType: 'line' | 'page' | 'column';
}

/**
 * Sprint 40：DrawingML 圖片裁切（`<a:srcRect l="..." t="..." r="..." b="..."/>`）。
 *
 * OOXML §20.1.10.40 ST_PositiveFixedPercentage：原始值 = 千分比 × 1000，
 * 即 `t="4066"` 表示「從 source 上方裁切 4.066%」。
 *
 * 此處統一以 **0–1 分數** 表示（已 ÷ 100000）：
 *   - leftPct + rightPct < 1（otherwise 整張圖被裁光）
 *   - 同理 topPct + bottomPct
 *
 * 缺漏（無 srcRect 或空 `<a:srcRect/>`）→ undefined，視為「不裁切」。
 */
export interface ImageSrcRect {
  leftPct: number;   // 0–1
  topPct: number;
  rightPct: number;
  bottomPct: number;
}

/**
 * Sprint 287：wp:anchor 補充屬性（除 posH/posV/wrapType/behindDoc/allowOverlap
 * 等 Sprint 37 已 capture 之外的常見屬性）。
 *
 * OOXML §20.4.2.3 ST_WordprocessingDrawing：
 *   - distT/distB/distL/distR (EMU)：文字環繞時與圖片邊距，預設 0
 *   - relativeHeight (UInt)：z-order；多 anchor 重疊時數字大者在上
 *   - locked (Bool)：鎖定不能編輯位置/大小
 *   - layoutInCell (Bool)：anchor 在 table cell 內時是否參與 layout（影響 cell height）
 *   - hidden (Bool)：隱藏不渲染
 *
 * 紀律 #21 capture-only：parser 補完整、writer 仍走 Sprint 192「FloatImage 降級
 * 為 inline 輸出」（acceptable lossy by design、explicit decision recorded
 * at OoxmlWriter.ts:1391-1394）。
 */
export interface AnchorMetadata {
  /** 文字環繞與圖片的邊距（EMU → Pt） */
  distT?: Pt;
  distB?: Pt;
  distL?: Pt;
  distR?: Pt;
  /** z-order；多 anchor 重疊時數字大者在上 */
  relativeHeight?: number;
  /** 鎖定不能編輯位置/大小 */
  locked?: boolean;
  /** anchor 在 table cell 內時是否參與 layout（影響 cell height 計算） */
  layoutInCell?: boolean;
  /** 隱藏不渲染 */
  hidden?: boolean;
}

/**
 * Sprint 287：wrap mode 的 wrapText attribute。
 *
 * OOXML §20.4.2.18 ST_WrapText：wrapSquare / wrapTight / wrapThrough /
 * wrapTopAndBottom 都可帶。預設 bothSides（Office 行為）。
 */
export type AnchorWrapText = 'left' | 'right' | 'largest' | 'bothSides';

/**
 * Sprint 289：wp:wrapPolygon 點（OOXML §20.4.2.17 ST_Coordinate / §20.4.2.10）。
 *
 * 座標單位：drawing coordinates（不直接是 EMU）。Office 慣例 21600 ≈ 圖片全寬/高，
 * 但實際數值由 Word 與圖片 extent 對應；caller 應視為 raw integer，render 時
 * 配合 image extent 縮放（render 端未實作為 Phase 3.4 完整 wrapTight 範圍）。
 */
export interface WrapPolygonPoint {
  x: number;
  y: number;
}

/**
 * Sprint 289：wp:wrapPolygon — 不規則多邊形繞排輪廓。
 *
 * 僅出現於 `<wp:wrapTight>` / `<wp:wrapThrough>`。OOXML §20.4.2.10：
 *   - `<wp:start x y/>` 起點
 *   - `<wp:lineTo x y/>` 多點線段（順時針或反時針都合法）
 *   - 通常閉合：最後 lineTo 回到 start（render 不強制要求）
 *   - `edited` 屬性：user 在 Word 內手動編輯過輪廓為 "1" / true
 *
 * 紀律 #18 scope-down：Sprint 289 為 capture-only；render 端 layout 走真實
 * polygon clip 為 Phase 3.4 完整 wrapTight 範圍（未實作、留 future cluster）。
 */
export interface WrapPolygon {
  edited?: boolean;
  start: WrapPolygonPoint;
  lineTo: WrapPolygonPoint[];
}

/**
 * Sprint 286：DrawingML `<wp:effectExtent l/t/r/b>` 陰影/光暈外擴。
 *
 * OOXML §20.4.2.6：四向 EMU 值，表示效果範圍超出 `<wp:extent>` 的外擴量。
 * Word 對含陰影/光暈的圖片必須宣告 effectExtent 才會在 layout 時保留空間，
 * 否則文字可能與效果重疊。多數無效果的圖片是 `l=0 t=0 r=0 b=0`。
 *
 * 統一以 Pt 儲存（caller 已 EMU→Pt 轉換）。全 0 不省略（保留 lossless round-trip）。
 */
export interface EffectExtent {
  left: Pt;
  top: Pt;
  right: Pt;
  bottom: Pt;
}

/** 內嵌圖片（wp:inline）*/
export interface InlineImageNode {
  type: 'inlineImage';
  rId: string;      // 關係 ID，Renderer 解析為 blob URL
  width: Pt;
  height: Pt;
  altText?: string;
  /**
   * Sprint 40：DrawingML `<a:srcRect>` 裁切（如有）。
   * Renderer 將透過 RenderContext.drawImage 第 6 參數傳入做 9-arg drawImage。
   */
  srcRect?: ImageSrcRect;
  /**
   * Sprint 183（Phase 5.2/5.3 render）：DrawingML graphic frame 內嵌的非圖片內容。
   *
   * `<a:graphicData uri>` 指向 SmartArt（diagram）或 Chart 時，圖形本身不內嵌
   * document.xml —— `relId` 指向獨立部件（diagram → `<dgm:relIds r:dm>`、
   * chart → `<c:chart r:id>`）。render 時 ToCanvasEditor 以此 relId 查
   * `DocumentNode.smartArts` / `charts` 做線性文字 fallback（mc:Fallback 壓縮）。
   *
   * 紀律 #21：一般圖片無此欄位（多數 inlineImage 為真實圖片）。
   */
  graphic?: { kind: 'diagram' | 'chart'; relId: string };
  /** Sprint 286：DrawingML `<wp:effectExtent>` 效果外擴（如有） */
  effectExtent?: EffectExtent;
}

/** 浮動圖片（wp:anchor）*/
export interface FloatImageNode {
  type: 'floatImage';
  rId: string;
  width: Pt;
  height: Pt;
  posH: {
    relativeFrom: 'margin' | 'page' | 'column' | 'character'
      | 'leftMargin' | 'rightMargin' | 'insideMargin' | 'outsideMargin';
    align?: 'left' | 'right' | 'center' | 'inside' | 'outside';
    posOffset?: Pt;
  };
  posV: {
    relativeFrom: 'margin' | 'page' | 'paragraph' | 'line'
      | 'topMargin' | 'bottomMargin' | 'insideMargin' | 'outsideMargin';
    align?: 'top' | 'bottom' | 'center' | 'inside' | 'outside';
    posOffset?: Pt;
  };
  wrapType: 'none' | 'square' | 'tight' | 'through' | 'topAndBottom'
    | 'behindText' | 'inFrontOfText';
  behindDoc?: boolean;
  allowOverlap?: boolean;
  altText?: string;
  /** Sprint 40：DrawingML `<a:srcRect>` 裁切（如有）— 與 InlineImageNode 同型別 */
  srcRect?: ImageSrcRect;
  /** Sprint 286：DrawingML `<wp:effectExtent>` 效果外擴（如有） */
  effectExtent?: EffectExtent;
  /** Sprint 287：wp:anchor 補充屬性（dist/relativeHeight/locked/layoutInCell/hidden） */
  anchor?: AnchorMetadata;
  /** Sprint 287：wrap mode 的 wrapText attribute（default bothSides） */
  wrapText?: AnchorWrapText;
  /** Sprint 289：wp:wrapTight/wp:wrapThrough 的 wrapPolygon 輪廓（如有） */
  wrapPolygon?: WrapPolygon;
}

/**
 * Sprint 38：浮動文字框（`<wp:anchor>` 含 `<wps:wsp>/<wps:txbx>`）。
 *
 * 與 FloatImageNode 共用 posH/posV/wrapType 結構，但內容是 paragraphs 而非 rId。
 * 03_complex_table 全套管 fixture 的 "112.12.29" 日期戳印與監造會議記錄等
 * 文檔的位置標籤用此節點型別。
 *
 * 渲染：Layout 端把 textbox 內 paragraphs 走 LineBreaker（lineWidth = textbox.width）
 * 後逐 line 在 abs position fillText。
 */
export interface FloatTextBoxNode {
  type: 'floatTextBox';
  width: Pt;
  height: Pt;
  posH: FloatImageNode['posH'];
  posV: FloatImageNode['posV'];
  wrapType: FloatImageNode['wrapType'];
  behindDoc?: boolean;
  allowOverlap?: boolean;
  /** Text box 內 paragraphs（由 DrawingParser 透過 paragraphFactory callback 解析）*/
  paragraphs: ParagraphNode[];
  /**
   * Sprint 39：`<wps:bodyPr lIns/tIns/rIns/bIns>` text box 內部 padding（EMU → Pt）。
   * OOXML 預設值（Office）：l=91440 EMU=7.2pt、t=45720 EMU=3.6pt、r=91440=7.2pt、b=45720=3.6pt。
   * 未設 → 使用 Office 預設值。
   */
  bodyPr?: {
    leftInset: Pt;
    topInset: Pt;
    rightInset: Pt;
    bottomInset: Pt;
  };
  /**
   * Sprint 39：`<wps:spPr><a:solidFill><a:srgbClr val="RRGGBB"/></a:solidFill>` 背景色。
   * `<a:noFill/>` 或缺漏 → undefined（不畫背景）。
   */
  fill?: HexColor;
  /**
   * Sprint 39：`<wps:spPr><a:ln w="..."><a:solidFill><a:srgbClr val="RRGGBB"/></a:solidFill></a:ln>` 邊框。
   * `<a:noFill/>` 在 `<a:ln>` 內 → undefined（不畫邊框）。
   * width 從 EMU 轉 Pt（1 pt = 12700 EMU）。
   */
  border?: {
    width: Pt;
    color: HexColor;
  };
  /** Sprint 286：DrawingML `<wp:effectExtent>` 效果外擴（如有） */
  effectExtent?: EffectExtent;
  /** Sprint 287：wp:anchor 補充屬性（dist/relativeHeight/locked/layoutInCell/hidden） */
  anchor?: AnchorMetadata;
  /** Sprint 287：wrap mode 的 wrapText attribute */
  wrapText?: AnchorWrapText;
  /** Sprint 289：wp:wrapTight/wp:wrapThrough 的 wrapPolygon 輪廓（如有） */
  wrapPolygon?: WrapPolygon;
}

export type InlineNode = RunNode | FieldNode | BreakNode | InlineImageNode | FloatImageNode | FloatTextBoxNode | FootnoteReferenceNode | RubyNode;

/**
 * Sprint 282 — Phase 1 optional bucket 第 1 項：`<w:ruby>` 注音/振假名標記
 * （OOXML §17.3.3.25）。
 *
 * 結構：
 * ```xml
 * <w:r>
 *   <w:ruby>
 *     <w:rubyPr>
 *       <w:rubyAlign w:val="distributeSpace"/>
 *       <w:hps w:val="14"/>            <!-- ruby font size half-points -->
 *       <w:hpsRaise w:val="36"/>       <!-- raise above baseline half-points -->
 *       <w:hpsBaseText w:val="28"/>    <!-- base text font size half-points -->
 *       <w:lid w:val="zh-TW"/>         <!-- language ID -->
 *       <w:dirty w:val="0"/>           <!-- needs refresh -->
 *     </w:rubyPr>
 *     <w:rt><w:r>...</w:r></w:rt>      <!-- annotation 注音 / 振假名 -->
 *     <w:rubyBase><w:r>...</w:r></w:rubyBase>  <!-- 被注的文字 -->
 *   </w:ruby>
 * </w:r>
 * ```
 *
 * Sprint 282 範圍 = capture-only：parser 把 ruby 結構讀進 AST、不 render（
 * canvas-editor 無 ruby 概念、Phase 6 自寫 Layout 才能顯示）；writer round-trip
 * 留 follow-up sprint。
 *
 * 紀律 #21：與 Sprint 145-153 capture-only 9 連同模式（先讀進 AST、render /
 * writer 後續再補）。
 */
export interface RubyNode {
  type: 'ruby';
  /** 注音 / 振假名 runs（`<w:rt>` 內、顯示在 base 上方或旁邊） */
  annotationRuns: RunNode[];
  /** Base text runs（`<w:rubyBase>` 內、被注的文字） */
  baseRuns: RunNode[];
  /** Ruby 展示屬性（OOXML §17.3.3.25.10 等） */
  props?: RubyProps;
}

/** OOXML §17.3.3.25.10 ruby 對齊與字級。 */
export interface RubyProps {
  /**
   * `<w:rubyAlign>` 對齊（OOXML §17.18.78 ST_RubyAlign）。
   * 預設 `center`；`distributeSpace` 為日文振假名常用。
   */
  align?: 'center' | 'distributeLetter' | 'distributeSpace' | 'left' | 'right' | 'rightVertical';
  /** `<w:hps>` ruby font size（half-points、OOXML raw、未除 2） */
  hps?: number;
  /** `<w:hpsRaise>` raise above baseline（half-points） */
  hpsRaise?: number;
  /** `<w:hpsBaseText>` base text font size（half-points） */
  hpsBaseText?: number;
  /** `<w:lid>` 語言 ID（BCP 47-ish，如 "zh-TW" / "ja-JP"） */
  lid?: string;
  /** `<w:dirty>` 需要 refresh 標記 */
  dirty?: boolean;
}

/**
 * Sprint 242 — Phase 1 optional 第二批升級：`<w:footnoteReference>` /
 * `<w:endnoteReference>` 在 run 內的引用標記（OOXML §17.11.14 / §17.11.18）。
 *
 * Sprint 145 parser capture-only / Sprint 165 標為 Phase 1 optional；Sprint
 * 239 writer 補 footnotes.xml/endnotes.xml emit 後、本 sprint 補上 doc.xml
 * 內 inline reference capture + writer emit、閉合 doc.xml ↔ footnotes.xml
 * 引用迴路。
 *
 * 結構：`<w:r><w:footnoteReference w:id="N"/></w:r>`、id 對應
 * `DocumentNode.footnotes` Map 的 key。
 */
export interface FootnoteReferenceNode {
  type: 'footnoteRef';
  /** 'footnote' = `<w:footnoteReference>`、'endnote' = `<w:endnoteReference>`。 */
  noteType: 'footnote' | 'endnote';
  /** `w:id` 引用 footnotes/endnotes Map 的 key。 */
  id: number;
}

/**
 * Sprint 179（Phase 5.1 OMML 數學公式）：OMML 元素樹的通用節點（capture-only）。
 *
 * OMML（Office Math Markup Language、ECMA-376 §22.1）以 `m:` 命名空間描述數學公式
 * （分數 `m:f` / 根號 `m:rad` / n 元運算 `m:nary` / 上下標 `m:sSub` 等 / 矩陣 `m:m`）。
 *
 * capture-only 階段以遞迴通用樹保留完整結構 —— 不解語意、不轉 MathML / KaTeX。
 * 渲染（OMML → KaTeX）留 Sprint 180。
 */
export interface OmmlNode {
  /** OOXML 標籤 localName（去 `m:` 前綴），例如 'f'（分數）/ 'rad'（根號）/ 'r'（math run）/ 't'（文字）。 */
  tag: string;
  /** 文字內容（僅 `m:t` 有值；其餘結構元素無）。 */
  text?: string;
  /**
   * Sprint 180：元素屬性 localName → 值（去 `m:` 前綴）。
   * n 元運算子 `<m:chr m:val="∑">`、分數型別 `<m:type m:val="bar">` 等的語意載於屬性，
   * 渲染（linearize）需用。無屬性時不掛 key（紀律 #21）。
   */
  attrs?: Record<string, string>;
  /** 子節點（遞迴）；無子節點時不掛 key（紀律 #21）。 */
  children?: OmmlNode[];
}

/**
 * Sprint 179：段落內一段數學公式（`<m:oMath>`、ECMA-376 §22.1.2.77）。
 *
 * 來源兩種：
 *   - `<m:oMathPara>` 包裹的獨立置中公式（display math）→ display = true
 *   - 段落直屬 `<m:oMath>`（行內公式、inline math）→ display = false
 */
export interface MathNode {
  /** display = true：`<m:oMathPara>` 包裹的獨立公式；false：行內公式。 */
  display: boolean;
  /** `<m:oMath>` 子元素解析出的 OMML 樹。 */
  omml: OmmlNode[];
}

/** 段落 */
export interface ParagraphNode {
  type: 'paragraph';
  props: ParagraphProps;
  runs: InlineNode[];
  styleId?: string;   // w:pStyle 參照的樣式 ID
  /**
   * Sprint 125 — 此段落內 `<w:bookmarkStart w:name="...">` 收集的名稱列表（去重）。
   * 包含：段落直屬 bookmarkStart + 段落內任一 w:r 內含的 bookmarkStart。
   * 用於：未來 hyperlink `w:anchor="..."` 反向查詢段落定位（規畫書 §1.9）、
   * REF field 解析、PDF 內部跳轉錨點。
   * Word 自動生成的 `_GoBack` 也會被捕捉、屬正常行為（不影響 render）。
   */
  bookmarks?: string[];
  /**
   * Sprint 177（Phase 5.5 註解錨點）— 此段落引用的註解 id 列表（去重、升序）。
   * 來源：段落內 `<w:commentRangeStart w:id>` + 任一 w:r 內 `<w:commentReference w:id>`。
   * 對應 `DocumentNode.comments` 的 key；用於把註解內容定位到文件位置。
   */
  commentRefs?: number[];
  /**
   * Sprint 179（Phase 5.1 OMML）— 此段落內的數學公式列表（capture-only）。
   * 來源：段落直屬 `<m:oMath>`（行內）+ `<m:oMathPara>` 包裹的 `<m:oMath>`（display）。
   * capture-only —— layout / render 不消費；非空才掛 key（紀律 #21）。
   * 渲染（OMML → KaTeX）+ 行內位置 wire-up 留 Sprint 180。
   */
  math?: MathNode[];
}

// ── 表格 ──────────────────────────────────────────────────────────────────────

export interface CellNode {
  type: 'cell';

  // ── Grid 位置（由 GridResolver 預計算，不可直接使用陣列索引）──
  gridCol: number;         // 0-based，此格起始的 grid column
  gridSpan: number;        // 橫向佔據的 grid column 數
  rowSpan: number;         // 縱向佔據的 row 數（由 vMerge 鏈推算）

  // ── 跨頁 vMerge 處理 ──────────────────────────────────────────────────────
  // isContinuation = true：此格是上方 vMerge 的延續
  //   Renderer 跳過繪製內容，但必須記錄此格以供跨頁邊框抑制判斷：
  //   當 vMerge 跨分頁邊界時，第一頁底部省略 Cell 下邊框、
  //   第二頁頂部省略 Cell 上邊框，形成視覺連通效果。
  isContinuation: boolean;

  /**
   * Cell 內容。Sprint 5 起改為 BlockNode[]（= ParagraphNode | TableNode），
   * 支援巢狀表格。Sprint 4 之前限定 ParagraphNode[]。
   *
   * 大多數 fixture 仍只是 ParagraphNode 序列；只有少數監造文件會有
   * 「cell 內又有小表格」的設計。Renderer / Layout 必須逐一檢查 type。
   */
  content: BlockNode[];
  props: {
    width?: Pt;
    borders?: CellBorders;
    shading?: { fill?: HexColor; color?: HexColor; pattern?: string; };
    margins?: { top?: Pt; bottom?: Pt; left?: Pt; right?: Pt; };
    vAlign?: 'top' | 'center' | 'bottom';
    noWrap?: boolean;
    fitText?: boolean;
    // OOXML §17.18.93 ST_TextDirection 完整 6 種：
    //   水平：lrTb (default)
    //   垂直但 glyph 不轉：tbRl, btLr（少用）
    //   垂直 + glyph 旋轉（V suffix）：lrTbV / tbRlV / tbLrV — Sprint 34 加入
    //   tbRlV 最常見（中文表單第一欄直書「工程名稱」「抽查地點」）
    textDirection?: 'lrTb' | 'tbRl' | 'btLr' | 'lrTbV' | 'tbRlV' | 'tbLrV';
    /** Sprint 293：`<w:cellIns>` cell 插入修訂（OOXML §17.13.5.3）。 */
    cellIns?: TrackChangeMeta;
    /** Sprint 293：`<w:cellDel>` cell 刪除修訂（OOXML §17.13.5.2）。 */
    cellDel?: TrackChangeMeta;
    /**
     * Sprint 293：`<w:cellMerge>` cell 合併/拆分修訂（OOXML §17.13.5.1）。
     *
     * `w:val="vert"` 或 `"rest"` 表示縱向合併變更；`w:vMerge="rest"|"cont"|"start"`
     * 為原 vmerge 屬性、不在此 capture。
     */
    cellMerge?: TrackChangeMeta & { val?: 'vert' | 'rest' | 'cont'; vMerge?: 'cont' | 'rest' };
  };
}

export interface RowNode {
  type: 'row';
  cells: CellNode[];
  props: {
    height?: Pt;
    heightRule?: 'auto' | 'atLeast' | 'exact';
    isHeader: boolean;   // w:tblHeader — 換頁後重複標題列
    cantSplit: boolean;  // w:cantSplit — 此列不可跨頁斷裂
  };
}

export interface TableNode {
  type: 'table';
  grid: Pt[];             // 每個 grid column 的寬度，長度 = 總 grid column 數
  rows: RowNode[];
  styleId?: string;       // w:tblStyle
  props: {
    width?: Pt;
    widthType?: 'auto' | 'dxa' | 'pct' | 'nil';
    alignment?: 'left' | 'center' | 'right';
    indent?: Pt;
    cellMargins?: { top?: Pt; bottom?: Pt; left?: Pt; right?: Pt; };
    borders?: CellBorders;
    look?: string;        // w:tblLook hex flags（控制預設樣式套用範圍）
  };
}

export type BlockNode = ParagraphNode | TableNode;

// ── 節（Section）─────────────────────────────────────────────────────────────

export interface SectionNode {
  type: 'section';
  page: {
    width: Pt;
    height: Pt;
    orientation: 'portrait' | 'landscape';
  };
  margins: {
    top: Pt;
    bottom: Pt;
    left: Pt;
    right: Pt;
    header: Pt;   // 頁首距頁面頂端
    footer: Pt;   // 頁尾距頁面底端
    gutter?: Pt;  // 裝訂邊距
  };
  columns?: {
    count: number;
    space?: Pt;
    equalWidth?: boolean;
    /**
     * Sprint 6：個別欄寬（Pt 為單位）。
     *
     * 來自 OOXML `<w:cols><w:col w:w="..." w:space="..."/>...</w:cols>`。
     * 只有當 `equalWidth=false` 且至少一個 `<w:col>` 帶 `w:w` 時填入。
     * 長度應 = `count`。Paginator 使用此陣列覆寫等寬計算。
     */
    colWidths?: Pt[];
    /** 個別欄之間的間距（colWidths 對應）；length = count - 1 */
    colSpaces?: Pt[];
    /**
     * Sprint 10：欄分隔線（OOXML `<w:cols w:sep="true"/>`）。
     *
     * true 時 Renderer 在欄之間 colSpace 中央畫一條垂直線（黑色細線）。
     * 預設 false / undefined 不畫。
     */
    separator?: boolean;
  };
  headerRefs: {
    default?: string;  // rId → word/headerN.xml
    first?: string;
    even?: string;
  };
  footerRefs: {
    default?: string;
    first?: string;
    even?: string;
  };
  titlePage: boolean;            // w:titlePg
  evenAndOddHeaders: boolean;    // 來自 w:settings 的文件層級設定
  body: BlockNode[];             // 此節在 sectPr 之前的所有段落與表格
  /**
   * Section break 類型（OOXML w:type val）。
   *
   * Sprint 4 起 SectionParser 抓出此欄位；
   * undefined 視為預設 'nextPage'（OOXML 規格）。
   *
   * 影響 Paginator 在多 section 文件中如何銜接下一節：
   *   - nextPage  : 跳到下一頁（預設）
   *   - continuous: 在當前頁繼續（不換頁）
   *   - evenPage  : 跳到下一個偶數頁（必要時插入空白頁）
   *   - oddPage   : 跳到下一個奇數頁
   */
  sectionBreakType?: 'nextPage' | 'continuous' | 'evenPage' | 'oddPage';
  /**
   * Document grid（OOXML §17.6.5 w:docGrid）。
   *
   * Sprint 29 引入：中文文件常用 `<w:docGrid w:type="lines" w:linePitch="364"/>`
   * 強制每行 baseline 對齊 grid，line height 因此被 ceil 到 linePitch 的整數倍。
   *
   * - type='lines'：line baseline 落 grid（vertical only）
   * - type='linesAndChars' / 'snapToChars'：暫只用 lines 行為（chars 部分不影響行高）
   * - type='default'：無 grid（不 snap）
   *
   * linePitch 為 Pt（已從 twip 轉換）；未設或為 0 時不 snap。
   */
  docGrid?: {
    type: 'lines' | 'linesAndChars' | 'snapToChars' | 'default';
    linePitch: Pt;
  };
}

// ── 頁首 / 頁尾內容 ───────────────────────────────────────────────────────────

export interface HeaderFooterContent {
  rId: string;
  content: BlockNode[];
}

// ── Web 設定（Sprint 148、word/webSettings.xml capture-only）─────────────────

/**
 * Web 設定(OOXML §17.16、word/webSettings.xml)。
 *
 * Sprint 148 capture-only:
 *   - 42/42 fixture 都有 webSettings.xml(Word 預設骨架)
 *   - 主要是 docx 匯出 HTML 時的 hint、import / layout / render **完全不用**
 *   - 結束 Phase 1 part 三連 cluster(Sprint 145-148)的儀式性 capture
 *   - 留 hook 給將來 Phase 6 docx export 對稱性(import-export round-trip equality)
 *
 * 解析範圍(簡化):
 *   - 4 個 toggle 元素 boolean
 *   - hasDivs:是否含 w:divs(HTML div 結構提示、深層巢狀、本 sprint 不深入)
 *
 * 紀律 #18:scope 限縮、不解析 divs 內部結構(屬 Phase 6 docx export 範疇)。
 */
export interface DocumentWebSettings {
  /** w:optimizeForBrowser:HTML 匯出時針對特定瀏覽器最佳化 */
  optimizeForBrowser?: boolean;
  /** w:allowPNG:允許 HTML 匯出時用 PNG 圖片格式 */
  allowPNG?: boolean;
  /** w:saveSmartTagsAsXml:Smart Tags 是否以 XML 形式儲存 */
  saveSmartTagsAsXml?: boolean;
  /** w:doNotSaveAsSingleFile:HTML 匯出不另存為單一檔案(預設拆分多檔)*/
  doNotSaveAsSingleFile?: boolean;
  /** w:divs 存在性:是否含 HTML div 結構提示(本 sprint 不深入內容)*/
  hasDivs?: boolean;
}

// ── 字型表（Sprint 147、word/fontTable.xml capture-only）─────────────────────

/**
 * 字型 family 列舉(OOXML §17.18.46):
 * - 'auto':預設、由 reader 決定
 * - 'decorative':裝飾性字型
 * - 'modern':等寬字型(Courier 類)
 * - 'roman':襯線字型(Times 類)
 * - 'script':手寫風格(楷體類)
 * - 'swiss':無襯線字型(Arial / 黑體類)
 */
export type FontFamily = 'auto' | 'decorative' | 'modern' | 'roman' | 'script' | 'swiss';

/**
 * 字型 pitch 列舉(OOXML §17.18.51):
 * - 'fixed':等寬
 * - 'variable':可變寬
 * - 'default':預設(由 family 推斷)
 */
export type FontPitch = 'fixed' | 'variable' | 'default';

/**
 * 字型 Unicode 子集 + Code Page 簽章(OOXML §17.8.3.10 + §17.8.3.4)。
 *
 * usb0-usb3:Unicode Subset Bitfields(4 × 32-bit hex string)
 * csb0-csb1:Code Page Bitfields(2 × 32-bit hex string)
 *
 * 用途:wire-up 時可判定字型支援哪些 Unicode 區段(如「CJK 漢字」、
 * 「拉丁擴展 A」、「希臘文」等)、避免用不支援的字型 render fallback character。
 *
 * 紀律 #21:全空時(整 sig 無屬性)不掛 key。
 */
export interface FontSignature {
  usb0?: string;
  usb1?: string;
  usb2?: string;
  usb3?: string;
  csb0?: string;
  csb1?: string;
}

/**
 * 單一字型條目(對應 word/fontTable.xml 中的 `<w:font w:name="...">` 子元素)。
 *
 * Sprint 147 capture-only:42/42 fixture 都有 fontTable.xml、平均 ~20-30 fonts/file。
 * Wire-up 候選(留將來 sprint):
 * - altName:替代字型 fallback chain(已知字型缺失時用)
 * - family + pitch:字型分類顯示(UI)、metric 選擇 hint
 * - panose1 / sig:精確 fallback 匹配(同 family + Unicode 支援度)
 */
export interface FontEntry {
  /** w:font/@w:name:字型名稱(主 key、必填)*/
  name: string;
  /** w:altName/@w:val:替代字型名稱(無 main 字型時 Word 自動用 alt)*/
  altName?: string;
  /** w:charset/@w:val:字元集 ID(hex 字串,如 '88' = ChineseBIG5)*/
  charset?: string;
  /** w:family/@w:val:字型 family 列舉(未知值降級為 undefined)*/
  family?: FontFamily;
  /** w:pitch/@w:val:字型 pitch 列舉 */
  pitch?: FontPitch;
  /** w:panose1/@w:val:10-byte Panose 識別碼(hex 字串)*/
  panose1?: string;
  /** w:sig:Unicode + Code Page 支援簽章(紀律 #21 全空不掛 key)*/
  sig?: FontSignature;
}

/**
 * 文件字型表(Sprint 147、word/fontTable.xml capture-only)。
 *
 * 以字型名稱為 key 的 Map、保留 fontTable.xml 內的順序資訊由 caller 自行記錄。
 * 空 Map 代表「無 fontTable.xml part」或「fontTable.xml 內 0 font」。
 */
export type FontTable = Map<string, FontEntry>;

// ── 文件設定（Sprint 146、word/settings.xml capture-only）────────────────────

/**
 * 文件級設定（OOXML §17.15 settings.xml）。
 *
 * Sprint 146 capture-only:42/42 fixture 都有 settings.xml、但 layout/render 端
 * 暫時不消費。為將來 wire-up（如 defaultTabStop 用於 tab stop 排版、zoom 用於
 * UI 預設縮放、compat 用於 Word 版本相容）鋪路。
 *
 * 欄位皆 optional;capture-only 階段不掛 key 的欄位由 caller 用 `??` 提供 fallback。
 */
export interface DocumentSettings {
  /** w:zoom w:percent：UI 預設縮放百分比（如 100 = 100%）*/
  zoomPercent?: number;
  /** w:defaultTabStop w:val：預設 tab stop 距離（pt、來自 twip 轉換）*/
  defaultTabStop?: Pt;
  /**
   * w:characterSpacingControl w:val:字距控制策略
   *
   * - 'doNotCompress':西文預設、不壓縮標點
   * - 'compressPunctuation':中日韓文預設、壓縮全形標點
   * - 'compressPunctuationAndJapaneseKana':中日韓進階、額外壓縮日文假名
   */
  characterSpacingControl?:
    | 'doNotCompress'
    | 'compressPunctuation'
    | 'compressPunctuationAndJapaneseKana';
  /** w:autoHyphenation:自動斷字開啟 */
  autoHyphenation?: boolean;
  /** w:evenAndOddHeaders:奇偶頁 header/footer 差異化 */
  evenAndOddHeaders?: boolean;
  /** w:trackChanges:追蹤修訂模式啟用 */
  trackChanges?: boolean;
  /** w:proofState:拼字 / 文法檢查狀態 */
  proofState?: {
    spelling?: 'clean' | 'dirty';
    grammar?: 'clean' | 'dirty';
  };
  /** w:footnotePr:footnote 編號 / 位置設定 */
  footnotePr?: {
    /** numRestart:eachPage / eachSect / continuous（未設）*/
    numRestart?: 'continuous' | 'eachPage' | 'eachSect';
    /** numFmt:decimal / lowerLetter / lowerRoman 等 */
    numFmt?: string;
    /** position:pageBottom / beneathText / sectEnd / docEnd */
    position?: 'pageBottom' | 'beneathText' | 'sectEnd' | 'docEnd';
    /** numStart:起始序號（預設 1）*/
    numStart?: number;
  };
  /** w:endnotePr:endnote 編號 / 位置設定（結構同 footnotePr）*/
  endnotePr?: {
    numRestart?: 'continuous' | 'eachPage' | 'eachSect';
    numFmt?: string;
    position?: 'sectEnd' | 'docEnd';
    numStart?: number;
  };
  /**
   * w:compat:相容性設定子元素的名稱列表（如 'spaceForUL' / 'balanceSingleByteDoubleByteWidth'）
   *
   * 不解析每個子元素的詳細參數、僅記錄存在;對應 OOXML §17.15.1.x 各 compat 元素。
   * Wire-up 時 caller 用 `settings.compat?.includes('xxx')` 判定。
   */
  compat?: string[];
}

// ── 註腳 / 尾註內容（Sprint 145、Phase 3.6 capture-only）──────────────────────

/**
 * 單一 footnote / endnote 條目。
 *
 * - id:OOXML w:id 整數(-1 = separator、0 = continuationSeparator、1+ = 普通內容)
 * - type:undefined = 普通 footnote(被 footnoteReference 引用)
 *        'separator' / 'continuationSeparator' / 'continuationNotice' = 預設裝飾
 * - content:footnote 內部段落 + 表格(重用 BlockNode、與 header/footer 結構相同)
 *
 * 本 sprint(145)只做 capture、不 wire-up:42 fixture footnoteReference 0 出現,
 * VR 視覺收益 = 0;留 hook 給 user 提供含 footnoteReference 的 fixture 後 wire-up。
 */
export interface FootnoteContent {
  id: number;
  type?: 'separator' | 'continuationSeparator' | 'continuationNotice';
  content: BlockNode[];
}

/**
 * Sprint 176（Phase 5.5 註解）：單則註解內容（OOXML §17.13.4、word/comments.xml）。
 *
 * `<w:comment w:id w:author w:date w:initials>` 內含段落 / 表格（同 body 結構）。
 * document.xml 以 `<w:commentRangeStart/End w:id>` + `<w:commentReference w:id>` 引用。
 */
export interface CommentContent {
  /** `w:id` 註解編號（與 `<w:commentReference>` 對應）。 */
  id: number;
  /** `w:author` 註解作者。 */
  author?: string;
  /** `w:date` 註解時間（ISO 字串、capture raw）。 */
  date?: string;
  /** `w:initials` 作者縮寫。 */
  initials?: string;
  /** 註解內容（段落 / 表格、同 body 結構）。 */
  content: BlockNode[];
}

// ── 清單編號（Numbering）─────────────────────────────────────────────────────

export interface NumberingLevel {
  ilvl: number;
  numFmt: string;       // 'decimal' | 'bullet' | 'lowerLetter' | 'upperLetter'
                        // | 'lowerRoman' | 'upperRoman' | 'chineseCounting' | ...
  text: string;         // w:lvlText val，例如 "%1." 或 "•"
  start: number;        // w:start val
  lvlRestart?: number;  // w:lvlRestart：0 = 不重啟，N = 遇到 ilvl < N 時重啟
  indent?: { left?: Pt; hanging?: Pt; };
  runProps?: RunProps;
  pProps?: Partial<ParagraphProps>;
  isLegal?: boolean;    // w:isLgl：強制所有層級以十進位顯示
}

export interface AbstractNumbering {
  abstractNumId: number;
  levels: NumberingLevel[];  // index = ilvl（0–8）
}

// ── 樣式 / 編號索引表 ─────────────────────────────────────────────────────────

/**
 * 表格條件樣式 type（OOXML §17.7.6 w:tblStylePr 的 w:type 列舉，共 13–15 種）。
 *
 * 用於 `<w:tblStylePr w:type="firstRow">` 等：套用條件依列/欄位置決定。
 */
export type TableConditionalType =
  | 'wholeTable'
  | 'firstRow' | 'lastRow'
  | 'firstCol' | 'lastCol'
  | 'band1Vert' | 'band2Vert'
  | 'band1Horz' | 'band2Horz'
  | 'neCell' | 'nwCell' | 'seCell' | 'swCell'
  | string;

export interface StyleEntry {
  pProps?: ParagraphProps;
  rProps?: RunProps;
  basedOn?: string;   // 父樣式 ID，繼承鏈由 StyleResolver 展開後不再需要追蹤
  /**
   * 表格條件樣式（type → { pProps, rProps, cProps }）。
   *
   * 僅 `<w:style w:type="table">` 的 entry 會有此欄位。
   * 由 Renderer/Layout Engine 依列/欄位位置選擇套用。
   * StyleResolver 不對其做 basedOn flatten — 條件樣式內容直接保留。
   *
   * Sprint 131：新增 `cProps`（cell-level conditional props）。
   *   subset of CellNode['props']：當前支援 `shading` + `vAlign`（最常用的兩個）。
   *   borders / margins / textDirection 需 BorderConflictResolver 整合、defer 未來 sprint。
   */
  conditional?: Map<
    TableConditionalType,
    {
      pProps?: ParagraphProps;
      rProps?: RunProps;
      cProps?: TableConditionalCellProps;
    }
  >;
}

/**
 * Sprint 131 + Sprint 284：tblStylePr 的 w:tcPr 內可套用的 cell-level 條件 props 子集。
 *
 * 目前實作的 OOXML §17.7.6.4 (tblStylePr) 子元素：
 *   - `w:shd` → shading（header row 背景填色最常見）
 *   - `w:vAlign` → 垂直對齊（標題列置中常用）
 *   - **`w:tcBorders` → borders（Sprint 284、firstRow/lastRow/bandHorz 條件邊框、user 指定）**
 *
 * 暫不實作（defer to future sprint）：
 *   - `w:tcMar`（margins）
 *   - `w:noWrap` / `w:textDirection`（罕見於條件樣式）
 *
 * Sprint 284 borders 設計決策：
 *   - 與 explicit cell borders 衝突時 → explicit 優先（同 shading/vAlign 規則）
 *   - per-side undefined 才補入 conditional（top/bottom/left/right/insideH/insideV 各自獨立）
 *   - BorderConflictResolver 後續 pass 不變、條件 borders 視為 cell explicit 進入解析
 */
export interface TableConditionalCellProps {
  shading?: { fill?: HexColor; color?: HexColor; pattern?: string };
  vAlign?: 'top' | 'center' | 'bottom';
  /** Sprint 284：`<w:tcBorders>` 條件邊框（OOXML §17.4.66） */
  borders?: CellBorders;
}

export type StyleMap = Map<string, StyleEntry>;

export type NumberingMap = Map<number, AbstractNumbering>; // numId → resolved abstract numbering

// ── 文件根節點 ────────────────────────────────────────────────────────────────

/**
 * Sprint 181（Phase 5.2 SmartArt、mc:Fallback 壓縮、capture-only）：
 * 單一 SmartArt 圖表（Word「插入 → SmartArt」）。
 *
 * SmartArt 在 document.xml 以 `<w:drawing>` 內 `<a:graphicData uri=".../diagram">`
 * 表示，圖本身不內嵌於 document.xml —— `<dgm:relIds r:dm r:lo r:qs r:cs>` 以 rId
 * 指向獨立部件：data（資料模型）/ layout / quickStyle / colors。
 *
 * 本 capture 取 **資料模型**（`diagrams/dataN.xml`、`<dgm:dataModel>`）的文字內容。
 * mc:Fallback 壓縮策略（user 2026-05-21 拍板）：接受降級保真度 —— 不重建圖形版面
 * 與連接線，僅保留語意文字（degraded fidelity，對應 OMML 的線性文字 fallback）。
 */
export interface SmartArtNode {
  /** 對應的 diagramData 關係 rId（document.xml.rels 內 type=diagramData）。 */
  rId: string;
  /**
   * 版面類型識別碼（`<dgm:pt type="doc"><dgm:prSet loTypeId>`），例如
   * `urn:microsoft.com/office/officeart/2008/layout/VerticalCircleList`。
   * 無此屬性時不掛 key（紀律 #21）；render wire-up 時用於選版面策略。
   */
  layoutType?: string;
  /**
   * 圖內文字節點（依 `<dgm:ptLst>` 內容點順序）。
   * 已過濾 presentation 點（type=pres/parTrans/sibTrans/doc）與空白文字。
   */
  texts: string[];
}

/**
 * Sprint 182（Phase 5.3 Charts、mc:Fallback 壓縮、capture-only）：圖表內單一資料數列。
 */
export interface ChartSeries {
  /** 數列名稱（`<c:ser><c:tx>` 快取文字）；無則省略（紀律 #21）。 */
  name?: string;
  /** 類別軸標籤（`<c:cat>` 快取，依 `<c:pt idx>` 對位、缺漏點為空字串）。 */
  categories: string[];
  /** 數值（`<c:val>` numCache，依 `<c:pt idx>` 對位、缺漏點為 null）。 */
  values: (number | null)[];
}

/**
 * Sprint 182（Phase 5.3 Charts、mc:Fallback 壓縮、capture-only）：單一圖表。
 *
 * Chart 在 document.xml 以 `<w:drawing>` 內 `<a:graphicData uri=".../chart">`
 * 表示，圖本身不內嵌 —— `<c:chart r:id>` 以 rId 指向獨立的 `charts/chartN.xml`
 * （`<c:chartSpace>` root）。
 *
 * 本 capture 取 `chartN.xml` 內嵌的**數值快取**（`<c:numCache>` / `<c:strCache>`，
 * Word 為離線顯示而存的資料副本）。mc:Fallback 壓縮策略（user 2026-05-21 拍板）：
 * 不重繪座標軸與圖形，僅保留型別 + 數列資料（degraded fidelity）。
 */
export interface ChartNode {
  /** 對應的 chart 關係 rId（document.xml.rels 內 type=chart）。 */
  rId: string;
  /** 圖表型別（`<c:plotArea>` 內首個 `*Chart` 元素 localName，例如 barChart / bar3DChart / pieChart / lineChart）。 */
  chartType: string;
  /** 圖表標題（`<c:title>` 內文字）；無則省略（紀律 #21）。 */
  title?: string;
  /** 資料數列（依 `<c:ser>` 出現順序）。 */
  series: ChartSeries[];
}

export interface DocumentNode {
  type: 'document';
  sections: SectionNode[];
  headers: Map<string, HeaderFooterContent>;  // rId → 內容
  footers: Map<string, HeaderFooterContent>;  // rId → 內容
  /** Sprint 145：footnotes.xml 解析結果（id → 內容）；fixture 0 覆蓋時為空 Map */
  footnotes: Map<number, FootnoteContent>;
  /** Sprint 145：endnotes.xml 解析結果（id → 內容）；fixture 0 覆蓋時為空 Map */
  endnotes: Map<number, FootnoteContent>;
  /** Sprint 176：comments.xml 解析結果（id → 註解內容）；無 comments.xml 時為空 Map */
  comments: Map<number, CommentContent>;
  /** Sprint 146：settings.xml 解析結果（capture-only、欄位皆 optional、空物件代表「無設定 part」）*/
  settings: DocumentSettings;
  /** Sprint 147：fontTable.xml 解析結果（capture-only、空 Map 代表「無 fontTable.xml」）*/
  fontTable: FontTable;
  /** Sprint 148：webSettings.xml 解析結果（capture-only、layout/render 不用、留 Phase 6 export）*/
  webSettings: DocumentWebSettings;
  styles: StyleMap;
  numbering: NumberingMap;
  media: Map<string, string>;  // rId → blob URL 或 base64 data URL（圖片）
  /**
   * Sprint 13：docProps/core.xml 解析結果。
   *
   * 欄位來源（OOXML §22.2 / Dublin Core + cp namespace）：
   *   - title       ← `<dc:title>`
   *   - creator     ← `<dc:creator>` （第一作者）
   *   - subject     ← `<dc:subject>`
   *   - description ← `<dc:description>`
   *   - keywords    ← `<cp:keywords>`
   *   - lastModifiedBy ← `<cp:lastModifiedBy>`
   *   - created     ← `<dcterms:created>` （ISO datetime）
   *   - modified    ← `<dcterms:modified>`
   *
   * 缺檔 / 解析失敗 → docProps 為空物件 `{}`，欄位 undefined。
   * Layout caller 可把這些值對應到 LayoutOptions.documentMetadata。
   */
  docProps: DocProps;
  /**
   * Sprint 150：docProps/app.xml 解析結果（capture-only、欄位皆 optional、紀律 #21 空集合不掛 key）。
   *
   * OOXML §22.2 + extended-properties namespace：
   *   docProps/app.xml 含 Application / Pages / Words / Company / AppVersion 等
   *   docx 編輯歷史與環境 metadata；layout / render 不消費，留 Phase 6 docx export 用。
   *
   * 42/42 fixture 都有 app.xml（Word/WPS 預設骨架），17 elements 出現頻率 100%。
   *
   * 缺檔 / 解析失敗 → appProps 為空物件 `{}`。
   */
  appProps: DocPropsApp;
  /**
   * Sprint 151：docProps/custom.xml 解析結果（capture-only、空 Map 代表「無 customProps 或解析失敗」）。
   *
   * OOXML §22.3 + custom-properties namespace：
   *   docProps/custom.xml 含 `<property fmtid="..." pid="N" name="X">vt:value</property>`
   *   是 author/app 自訂的鍵值對(KSOProductBuildVer / GrammarlyDocumentId 等)。
   *
   * 25/42 fixture 有 custom.xml(WPS / Grammarly 等 SaaS app stamp)、其他 17 fixture 無此 part。
   *
   * Key 為 `name` 屬性、value 為 type-discriminated CustomPropertyValue。
   */
  customProps: DocPropsCustom;
  /**
   * Sprint 152：[Content_Types].xml 解析結果（capture-only、readonly、空 Map 代表「未解析或無 part」）。
   *
   * OOXML §10.2.2 / OPC §3.2：
   *   每個 OOXML package 必有 [Content_Types].xml、告訴 reader 每個 part 的 MIME type。
   *   `defaults` 以 Extension(小寫) 為 key、`overrides` 以 part path(無前導 "/") 為 key。
   *
   * 為 Phase 6 docx export 對稱性鋪路(import 端讀進來、export 端要原樣寫回);
   * 本 capture 階段 layout/render 不消費。
   *
   * 42/42 fixture 都有此 part(spec 強制)、單 fixture 平均 ~13 entries
   * (2-3 defaults + 10-15 overrides)。
   */
  contentTypes: DocContentTypes;
  /**
   * Sprint 153：styles.xml `<w:latentStyles>` 解析結果（capture-only、空物件代表「無 latentStyles」）。
   *
   * OOXML §17.7.4.6 latentStyles:
   *   Word 內建 latent style 列表(預設不展開為 StyleEntry、節省 styles.xml 體積)、
   *   含 root 級 defaults(defLockedState / defUIPriority / defSemiHidden /
   *   defUnhideWhenUsed / defQFormat / count)與 0..N 個 `<w:lsdException>`
   *   exception(per-style override:locked / uiPriority / semiHidden /
   *   unhideWhenUsed / qFormat)。
   *
   * 41/42 fixture 都有 latentStyles(平均 ~147 lsdException entries、Word 預設骨架)。
   * Layout / render 不消費(latent styles 是 Word UI 'Style Gallery' 顯示用)、
   * 為將來 Phase 6 docx export 對稱性鋪路。
   *
   * 缺檔 / 解析失敗 → latentStyles 為空物件 `{}`、欄位 undefined。
   */
  latentStyles: DocumentLatentStyles;
  /**
   * Sprint 171（Phase 5.6 浮水印 + 背景）：`<w:background>` 文件頁面背景（OOXML §17.2.1）。
   *
   * `<w:background>` 是 `<w:document>` 的直接子元素（`<w:body>` 的 sibling）、描述頁面
   * 背景色 —— Word「設計 → 頁面色彩」的儲存位置。
   *
   * 紀律 #21：optional —— 無 `<w:background>` 或無有效屬性 → 此欄位 undefined（多數
   * docx 無此元素）。CanvasRenderer 以 `pageBackgroundColor` 選項消費 `color`。
   */
  background?: DocumentBackground;
  /**
   * Sprint 172（Phase 5.6 浮水印 + 背景）：文件浮水印（Word「設計 → 浮水印」）。
   *
   * Word 浮水印實作為 header part 內的 VML `<v:shape>`（文字 WordArt 或圖片）。
   * 本欄位 capture 自任一 header 找到的第一個浮水印 shape。
   *
   * 紀律 #21：optional —— 無浮水印 → undefined（多數 docx 無浮水印）。
   * Sprint 172 為 capture-only；render wire-up（每頁繪旋轉浮水印）留 Sprint 173。
   */
  watermark?: DocumentWatermark;
  /**
   * Sprint 181（Phase 5.2 SmartArt、mc:Fallback 壓縮）：文件內所有 SmartArt 圖表。
   *
   * 收集自 document.xml.rels 內 type=diagramData 的關係（每個 SmartArt 一筆），
   * 依 rels 順序排列。capture-only —— render wire-up（線性文字 fallback）留後續 sprint。
   *
   * 紀律 #21：optional —— 文件無 SmartArt 時 undefined（多數 docx 無 SmartArt）。
   */
  smartArts?: SmartArtNode[];
  /**
   * Sprint 182（Phase 5.3 Charts、mc:Fallback 壓縮）：文件內所有圖表。
   *
   * 收集自 document.xml.rels 內 type=chart 的關係（每個圖表一筆），依 rels 順序
   * 排列。capture-only —— render wire-up 留後續 sprint。
   *
   * 紀律 #21：optional —— 文件無圖表時 undefined（多數 docx 無圖表）。
   */
  charts?: ChartNode[];
  /**
   * Sprint 262（Phase 6 第十八層 byte-identical 對稱矩陣）：
   * `word/theme/theme1.xml` 解析結果（紀律 #21 optional）。
   *
   * OOXML §20.1.6（DrawingML themeElements）：
   *   theme1.xml 含 colorScheme（12 色）+ fontScheme（major/minor × latin/ea/cs）
   *   + fmtScheme（線條/填色/效果樣式）+ objectDefaults + extraClrSchemeLst。
   *
   * 本 capture 取 colorScheme + fontScheme（render 用、StyleResolver/ParagraphParser
   *   eager resolve themeColor → hex）；fmtScheme/objectDefaults/extraClrSchemeLst
   *   不消費、不 capture（紀律 #18 scope-down、mc:Fallback 同等概念）。
   *
   * 缺檔 / 解析失敗 → theme 為 undefined（紀律 #21 optional、render fallback 用
   *   DEFAULT_THEME_MAP）。
   *
   * 為 Phase 6 docx export 對稱性鋪路（import 端讀進來、export 端要原樣寫回）；
   * writer 端僅 emit colorScheme + fontScheme、reparse 端對位、保證 round-trip
   * byte-identical。
   */
  theme?: import('../styles/ThemeResolver').ThemeMap;
}

/** Sprint 171：`<w:background>` 文件頁面背景（OOXML §17.2.1）。 */
export interface DocumentBackground {
  /** `w:color` 背景色 6-hex（大寫）；`"auto"` 或缺 / 非法 → undefined。 */
  color?: string;
  /**
   * `w:themeColor` 主題色名（capture raw、Sprint 171 scope-down 不解析為 hex）。
   * render wire-up 用 `color`；只有 themeColor 時 render 退回預設白底。
   */
  themeColor?: string;
}

/**
 * Sprint 172：文件浮水印（header 內 VML `<v:shape>` capture-only）。
 *
 * Word 浮水印 = header part 的 `<w:pict>` 內一個 VML `<v:shape>`：
 *   - 文字浮水印：`type="#_x0000_t136"` WordArt、含 `<v:textpath string="...">`
 *   - 圖片浮水印：shape id 含 "watermark"、含 `<v:imagedata r:id="...">`
 */
export interface DocumentWatermark {
  /** 'text' = WordArt 文字浮水印；'image' = 圖片浮水印。 */
  kind: 'text' | 'image';
  /** 文字浮水印文字內容（kind='text'、來自 `<v:textpath string="...">`）。 */
  text?: string;
  /** 文字浮水印字型（`<v:textpath>` style 的 font-family、去引號）。 */
  font?: string;
  /** 圖片浮水印的 image relationship Id（kind='image'）。 */
  imageRId?: string;
  /** 旋轉角度（度、來自 `<v:shape>` style 的 rotation；浮水印常見 315）。 */
  rotation?: number;
}

/**
 * [Content_Types].xml 解析結果(Sprint 152 capture-only、readonly)。
 *
 * 與 `package/PackageReader.ts` 的 `PackageContentTypes` 結構相同、本 alias
 * 對外置於 `core/ooxml/ast/types`、避免外部消費端 import package 子目錄。
 */
/**
 * 單一 latent style exception(對應 styles.xml 中的 `<w:lsdException>`)。
 *
 * Sprint 153 capture-only:欄位皆 optional、紀律 #21 空集合不掛 key。
 * `name` 由父 Map 的 key 持有、本介面不重複帶 name。
 */
export interface LatentStyleException {
  locked?: boolean;
  uiPriority?: number;
  semiHidden?: boolean;
  unhideWhenUsed?: boolean;
  qFormat?: boolean;
}

/**
 * 文件 latent styles(Sprint 153、styles.xml `<w:latentStyles>` capture-only)。
 *
 * 結構:
 *   - defaults:root 級 default attributes(5 toggles/integer + count)
 *   - exceptions:Map<name, LatentStyleException>(per-style override)
 *
 * 紀律 #21:defaults 欄位不存在 → undefined、exceptions 為空時為空 Map。
 */
export interface DocumentLatentStyles {
  defLockedState?: boolean;
  defUIPriority?: number;
  defSemiHidden?: boolean;
  defUnhideWhenUsed?: boolean;
  defQFormat?: boolean;
  /** Word 內建 latent style 總數(用於 export 對稱性、不限制 exceptions size)*/
  count?: number;
  exceptions?: Map<string, LatentStyleException>;
}

export interface DocContentTypes {
  /** Default Extension(小寫) → ContentType(MIME) */
  defaults: ReadonlyMap<string, string>;
  /** Override PartName(無前導 "/") → ContentType */
  overrides: ReadonlyMap<string, string>;
}

export interface DocProps {
  title?: string;
  creator?: string;
  subject?: string;
  description?: string;
  keywords?: string;
  lastModifiedBy?: string;
  created?: string;   // ISO datetime
  modified?: string;  // ISO datetime
}

/**
 * 文件 extended properties（OOXML §22.2、docProps/app.xml）。
 *
 * Sprint 150 capture-only：欄位皆 optional、紀律 #21 空集合不掛 key。
 *
 * 來源元素（namespace = extended-properties）：
 *   - Template / Application / AppVersion / Company：字串
 *   - Pages / Words / Characters / Lines / Paragraphs / CharactersWithSpaces /
 *     TotalTime / DocSecurity：整數
 *   - ScaleCrop / LinksUpToDate / SharedDoc / HyperlinksChanged：布林（"true"/"false"）
 *
 * 注意：DocSecurity 是 enum（0=None / 1=PasswordProtected / 2=ReadOnly /
 *      4=LockedForAnnotation / 8=LockedForReview），本 capture 階段以整數保留。
 */
/**
 * 自訂屬性值（OOXML §22.4 vt:variant 子集）。
 *
 * Sprint 151 capture-only:scope-down 至 5 個常見 variant 型別、其他未知 variant
 * 用 `kind: 'unknown'` 配 raw 字串保留(紀律 #18、不為 closure 而擴充)。
 *
 * 觀察:42 fixture 中只有 vt:lpwstr 出現(25 entries)、但 spec 允許更多
 * variant 型別(vt:lpstr / vt:bool / vt:i4 / vt:filetime / vt:r8 / vt:cy 等)、
 * 本 capture 對前 5 個常見 variant 解析、其他降級為 unknown。
 */
export type CustomPropertyValue =
  | { kind: 'string'; value: string }       // vt:lpwstr / vt:lpstr / vt:bstr
  | { kind: 'int'; value: number }          // vt:i4 / vt:i8 / vt:int / vt:uint
  | { kind: 'bool'; value: boolean }        // vt:bool
  | { kind: 'real'; value: number }         // vt:r4 / vt:r8 / vt:decimal
  | { kind: 'filetime'; value: string }     // vt:filetime / vt:date(原 ISO 字串)
  | { kind: 'unknown'; raw: string };       // 其他 variant、保留原 textContent

/**
 * 自訂屬性表(Sprint 151、docProps/custom.xml capture-only)。
 *
 * Map<name, CustomPropertyValue>;空 Map 代表「無 customProps part」或「解析失敗」。
 * 保留 OOXML <property> 元素 `name` 屬性為 key、`fmtid` / `pid` 暫不保留(紀律 #18)。
 */
export type DocPropsCustom = Map<string, CustomPropertyValue>;

export interface DocPropsApp {
  template?: string;
  application?: string;
  appVersion?: string;
  company?: string;
  totalTime?: number;       // minutes
  pages?: number;
  words?: number;
  characters?: number;
  charactersWithSpaces?: number;
  lines?: number;
  paragraphs?: number;
  docSecurity?: number;     // §22.2.2.6 enum
  scaleCrop?: boolean;
  linksUpToDate?: boolean;
  sharedDoc?: boolean;
  hyperlinksChanged?: boolean;
}
