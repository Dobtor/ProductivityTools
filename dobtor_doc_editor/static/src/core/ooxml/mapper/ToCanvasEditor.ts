/**
 * ToCanvasEditor — 把 DocumentNode 轉成 @hufe921/canvas-editor 的 IElement[] 格式
 *
 * canvas-editor 的輸入是「扁平 IElement 陣列」：
 *   - 每個字 / 字元 = 一個 IElement（type=text，value=char）
 *   - 段落結束 = 一個 IElement（value='\n'）
 *   - 圖片 = 一個 IElement（type=image，value=dataURL，width/height）
 *   - 表格 = 一個 IElement（type=table，colgroup + trList，內部 td.value 也是 IElement[]）
 *   - 超連結 = 一個 IElement（type=hyperlink，url + valueList = 子 IElement[]）
 *   - 分頁符 = 一個 IElement（type=pageBreak）
 *
 * 樣式（font / size / bold / color / italic / underline / strikeout / rowFlex / rowMargin）
 *   套用在每個字元 IElement 上；段落樣式（alignment / spacing）會被「複製」到該段所有 IElement。
 *
 * 範圍（Phase D.1）：
 *   ✅ Run 文字 + RunProps（font / size / bold / italic / underline / strike / color / highlight）
 *   ✅ 段落對齊（rowFlex）+ 段距（rowMargin）+ 段落結束 \n
 *   ✅ Break：line / page / column → \n（line）/ pageBreak（page/column 暫降級）
 *   ✅ Inline image：rId 透過 media map 解析成 dataURL → type=image
 *   ✅ Float image：暫降級為 inline image（canvas-editor 對浮動繞排支援有限，Phase 6+ 補）
 *   ✅ Hyperlink：type=hyperlink + url + valueList
 *   ✅ Table：colgroup + trList（gridSpan→colspan、vMerge anchor.rowSpan→rowspan、isContinuation cell 跳過）
 *   ✅ 段落間 page break（不同 section 之間插 pageBreak）
 *   ⚠️ Tab stops（pPr.tabs）：canvas-editor 的 type=tab 不接受位置陣列，只能放 '\t' 字元
 *   ⚠️ 列表編號（numId/ilvl）：canvas-editor 用獨立 listType/listStyle 系統，Phase D.1 暫不映射
 *   ⚠️ 字型 fallback（hAnsi/cs）：canvas-editor 只用單一 font，目前優先 fontFamilyEastAsia ?? fontFamily
 *
 * Phase D.2 / D.3：HarfBuzz metrics 整合 / pixelmatch e2e diff
 */

import type {
  Alignment,
  AnchorMetadata,
  AnchorWrapText,
  BlockNode,
  CellNode,
  ChartNode,
  CommentContent,
  DocumentNode,
  FieldNode,
  FloatImageNode,
  FloatTextBoxNode,
  InlineImageNode,
  InlineNode,
  NumberingMap,
  ParagraphNode,
  RowNode,
  RunNode,
  RunProps,
  SmartArtNode,
  TableNode,
} from '../ast/types';
import { NumberingCounterState, expandLvlText } from '../numbering';
import { ommlToLinearText } from '../omml';
import { smartArtToText } from '../diagram';
import { renderSmartArtSvg } from '../diagram/SmartArtSvgRenderer';
import { chartToText } from '../chart';
import { renderChartSvg, svgToDataUrl } from '../chart/ChartSvgRenderer';
import { commentToText } from '../comments/CommentsParser';

/** Sprint 358-359：ToCanvasEditor 行為選項。 */
export interface ToCanvasEditorOptions {
  /**
   * 把 SmartArt / Chart graphic frame 渲染成 SVG image（取代線性文字 fallback）。
   * 預設 false：維持 Sprint 183 既有純文字輸出 + VR byte-identical 不變。
   */
  renderGraphicsAsSvg?: boolean;
  /**
   * 把被註解段落改用 `groupIds` 標記範圍（取代 `[註解 作者: 內容]` inline 文字 fallback）。
   * 真正的 Word 風格右側註解 panel 由 doc_editor.js 消費，這裡只負責插槽。
   * 預設 false：維持 Sprint 184 既有 inline 文字輸出 + VR byte-identical 不變。
   */
  renderCommentsAsGroups?: boolean;
  /**
   * Sprint Y58：把 FloatTextBoxNode 內 paragraphs 展平到 inline stream。
   * Parser（Sprint 38）已經抽出 textbox 內容，但 Phase D.1 mapper 直接 drop —
   * 25/25 ChienYi 監造文件含 wp:anchor + w:txbxContent（頁碼/機關識別/日期戳印），
   * 預設行為 = 文字遺失。Opt-in 後展平讓內容可被 canvas-editor 正常顯示。
   * 預設 false：維持既有 drop 行為 + VR byte-identical 不變。
   */
  renderFloatTextBox?: boolean;
  /**
   * Sprint Y58：把 wp:anchor AnchorMetadata（dist / position / wrap / behindDoc / ...）
   * 透傳到 IElement extension props（`anchor` 欄位），讓前端 / 排版 / round-trip
   * 階段能取得原始 anchor 屬性。對 FloatImageNode 與 FloatTextBoxNode 同時生效。
   * 預設 false：IElement 不含 extension props + VR byte-identical 不變。
   */
  preserveAnchorMetadata?: boolean;
}

/**
 * 註解錨點（render-time 收集，給前端 panel 消費）。
 *
 * `groupId` 對應 IElement.groupIds 內的字串（commentId 轉字串），
 * 前端可 `editor.command.executeLocationGroup(groupId)` 跳到該範圍。
 */
export interface CommentAnchor {
  groupId: string;
  id: number;
  author: string;
  body: string;
  date?: string;
}

// ── canvas-editor 介面（僅必要欄位的本地宣告，避免依賴它的 d.ts 路徑）─────

/** 對齊（對應 canvas-editor RowFlex）*/
type CERowFlex = 'left' | 'center' | 'right' | 'alignment' | 'justify';

/** 元素類型（對應 canvas-editor ElementType；text 為預設可省略）*/
type CEElementType =
  | 'text'
  | 'image'
  | 'table'
  | 'hyperlink'
  | 'separator'
  | 'pageBreak'
  | 'tab'
  | 'superscript'
  | 'subscript';

/** 表格 colgroup 與 td/tr（對應 canvas-editor IColgroup/ITr/ITd）*/
interface CEColgroup {
  width: number;
}
interface CETd {
  colspan: number;
  rowspan: number;
  value: CEElement[];
  /** 背景色（hex 或 rgba），對應 canvas-editor td.backgroundColor */
  backgroundColor?: string;
  /** 縱向對齊（top/middle/bottom）— canvas-editor VerticalAlign */
  verticalAlign?: 'top' | 'middle' | 'bottom';
}
interface CETr {
  height: number;
  tdList: CETd[];
}

/**
 * canvas-editor IElement 的最小子集（只列我們會輸出的欄位）。
 *
 * 完整型別在 node_modules/@hufe921/canvas-editor/dist/src/editor/interface/Element.d.ts；
 * 此 type 只是 mapper 的 output 介面，不依賴 canvas-editor 的 import 路徑。
 */
export interface CEElement {
  type?: CEElementType;
  value: string;
  // ── 字型樣式 ─────────────────────────────────────────────────────────────
  font?: string;
  size?: number; // pt
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikeout?: boolean;
  color?: string;
  highlight?: string;
  // ── 段落樣式（每個 IElement 都帶；canvas-editor 用 rowFlex 推 row 對齊）───
  rowFlex?: CERowFlex;
  rowMargin?: number; // 段前/後距（pt）
  letterSpacing?: number; // 字距（pt）
  // ── image ───────────────────────────────────────────────────────────────
  width?: number;
  height?: number;
  // ── hyperlink ───────────────────────────────────────────────────────────
  url?: string;
  valueList?: CEElement[];
  // ── table ───────────────────────────────────────────────────────────────
  colgroup?: CEColgroup[];
  trList?: CETr[];
  // ── group（canvas-editor IGroup 範圍標記，註解 panel 用）─────────────────
  groupIds?: string[];
  // ── Sprint Y58: wp:anchor metadata 透傳 ──────────────────────────────────
  /**
   * 來自 wp:anchor 的浮動定位資訊（floatImage / floatTextBox）。
   * 只在 `options.preserveAnchorMetadata = true` 時 emit；canvas-editor 不消費
   * 此欄位 — 前端 plugin / round-trip writer / 排版 layer 才需要。
   * Sprint Y58 為 capture-only：mapper 透傳、canvas-editor 端視覺仍是 inline 降級。
   */
  anchor?: AnchorExtension;
}

// ── Sprint Y58: anchor metadata 透傳 schema ─────────────────────────────────

/**
 * IElement 的 wp:anchor 附加屬性（capture-only schema）。
 *
 * 對 FloatImageNode 與 FloatTextBoxNode 共用，欄位來源見
 * `static/src/core/ooxml/ast/types.ts` 內 `AnchorMetadata` / `FloatImageNode` /
 * `FloatTextBoxNode` 定義。
 */
export interface AnchorExtension {
  /** 來源 InlineNode.type：mapper 是否來自 FloatImageNode vs FloatTextBoxNode */
  source: 'floatImage' | 'floatTextBox';
  /** 浮動框寬高（Pt） */
  width?: number;
  height?: number;
  /** wp:positionH 水平定位 */
  posH?: FloatImageNode['posH'];
  /** wp:positionV 垂直定位 */
  posV?: FloatImageNode['posV'];
  /** wp:anchor wrap mode（none / square / tight / ...） */
  wrapType?: FloatImageNode['wrapType'];
  /** behindDoc / allowOverlap raw attrs */
  behindDoc?: boolean;
  allowOverlap?: boolean;
  /** Sprint 287 補充屬性（distT/distB/distL/distR/relativeHeight/locked/...） */
  metadata?: AnchorMetadata;
  /** wrapText attribute（default bothSides） */
  wrapText?: AnchorWrapText;
}

// ── 對外 Mapper ───────────────────────────────────────────────────────────────

export class ToCanvasEditor {
  /**
   * Sprint 183：SmartArt / Chart relId → 節點查表（render 用）。
   * 每次 `convert()` 開頭依當前 DocumentNode 重建，避免跨文件殘留。
   */
  private smartArtsByRId = new Map<string, SmartArtNode>();
  private chartsByRId = new Map<string, ChartNode>();

  /**
   * Sprint 184：註解 id → 內容查表（render 用）。
   * 每次 `convert()` 開頭依當前 DocumentNode 重設，避免跨文件殘留。
   */
  private comments = new Map<number, CommentContent>();

  /**
   * Sprint 361：本次 convert() 收集到的註解錨點（給前端 panel 消費）。
   * 只在 `options.renderCommentsAsGroups` 開時填，每次 convert() 開頭清空。
   */
  private commentAnchors: CommentAnchor[] = [];

  /** Sprint 358-359：行為選項（SmartArt/Chart SVG 渲染 opt-in）。 */
  private readonly options: ToCanvasEditorOptions;

  constructor(options: ToCanvasEditorOptions = {}) {
    this.options = options;
  }

  /**
   * 把整份 DocumentNode 轉為 IElement[]。
   *
   * @param doc 由 OoxmlParser.parse() 產出的 DocumentNode
   * @returns 可直接傳給 `new Editor(container, elements, options)` 的扁平陣列
   */
  convert(doc: DocumentNode): CEElement[] {
    // Sprint 183：建 SmartArt / Chart 查表（graphic frame relId → 節點）
    this.smartArtsByRId = new Map((doc.smartArts ?? []).map((s) => [s.rId, s]));
    this.chartsByRId = new Map((doc.charts ?? []).map((c) => [c.rId, c]));
    // Sprint 184：註解查表（commentRefs id → 內容）
    this.comments = doc.comments;
    // Sprint 361：每次 convert 清空錨點收集
    this.commentAnchors = [];

    const elements: CEElement[] = [];
    // Sprint 138：跨 section 共用 counter state（OOXML §17.9 預設行為、
    // sectPr 不強制重啟編號；若 fixture 需要可由 future sprint 加 hook）
    const counter = new NumberingCounterState();
    for (let i = 0; i < doc.sections.length; i++) {
      const section = doc.sections[i];
      // section 之間插 pageBreak（除了第一節前不需要）
      if (i > 0) {
        elements.push({ type: 'pageBreak', value: '\n' });
      }
      this.appendBlocks(elements, section.body, doc.media, doc.numbering, counter);
    }
    return elements;
  }

  /**
   * Sprint 361：回傳本次 convert() 收集到的註解錨點（給前端 panel 消費）。
   *
   * 只在 `options.renderCommentsAsGroups` 開時非空；caller 順序為 convert() → getCommentAnchors()。
   */
  getCommentAnchors(): CommentAnchor[] {
    return this.commentAnchors;
  }

  // ── BlockNode[] 走訪 ──────────────────────────────────────────────────────

  private appendBlocks(
    out: CEElement[],
    blocks: BlockNode[],
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): void {
    for (const block of blocks) {
      if (block.type === 'paragraph') {
        this.appendParagraph(out, block, media, numbering, counter);
      } else {
        out.push(this.convertTable(block, media, numbering, counter));
        // 表格後仍需段落終止符 \n（canvas-editor 規範）
        out.push({ value: '\n' });
      }
    }
  }

  // ── Paragraph → IElement[]（含段尾 \n）────────────────────────────────────

  private appendParagraph(
    out: CEElement[],
    para: ParagraphNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): void {
    const rowFlex = mapAlignment(para.props.alignment);
    const rowMargin = para.props.spacing?.before ?? para.props.spacing?.after;

    // 段落內 InlineNode → 各別 IElement
    const paraElements: CEElement[] = [];

    // Sprint 138：若 paragraph 有 numId，emit 編號前綴（展開 lvlText + tab 分隔）
    // canvas-editor 無 listType/listStyle 對應、降級為「前綴字串 + tab」嵌入段首
    // - bullet numFmt：lvlText 直接是字元（如「•」）、counter advance 仍需推進避免污染深層
    // - decimal/letter/roman/CN/JP/...：用 expandLvlText 展開 counter 為字串
    // - lvlText='' 的 placeholder：跳過 emit（避免空 prefix）
    if (para.props.numId !== undefined) {
      const ilvl = para.props.ilvl ?? 0;
      const abstractNum = numbering.get(para.props.numId);
      const result = counter.advance(para.props.numId, ilvl, abstractNum);
      const prefix = expandLvlText(result.level.text, result.counters, result.numFmts);
      if (prefix !== '') {
        // 用 paragraph 的 runProps 基底（從 level.runProps fallback）作為前綴樣式
        // 取第一個 run 的 props 當前綴 baseStyle；若無 run、用 level.runProps 或空
        const baseProps: RunProps =
          (para.runs.find((r): r is RunNode => r.type === 'run')?.props) ??
          result.level.runProps ??
          {};
        const baseStyle = mapRunProps(baseProps);
        this.appendChars(paraElements, prefix, baseStyle);
        // 編號與後續文字以 tab 分隔（OOXML 預設 lvlText suffix = tab）
        paraElements.push({ ...baseStyle, type: 'tab', value: '\t' });
      }
    }

    for (const node of para.runs) {
      this.appendInlineNode(paraElements, node, media, numbering, counter);
    }

    // Sprint 180（Phase 5.1 OMML render）：段落內數學公式（`para.math` 側陣列）
    //   以線性文字 fallback 渲染（分數 a/b、根號 √(x)、上下標 x_(n) 等）。
    //   capture-only 階段 math 未保留行內精確位置 → 一律 append 於段落 runs 之後
    //   （多數公式為 math-only 段落、此近似可接受；inline-mixed 精確位置 + KaTeX
    //   全保真排版留未來 optional sprint）。display / inline 皆同樣線性化。
    if (para.math && para.math.length > 0) {
      const mathBaseProps: RunProps =
        (para.runs.find((r): r is RunNode => r.type === 'run')?.props) ?? {};
      const mathStyle = mapRunProps(mathBaseProps);
      for (const mathNode of para.math) {
        const linear = ommlToLinearText(mathNode.omml);
        if (linear !== '') this.appendChars(paraElements, linear, mathStyle);
      }
    }

    // Sprint 184（Phase 5.5 註解 render）：被註解段落（`para.commentRefs` 側陣列）
    //   canvas-editor 無 Word 右側註解 panel 對應 → 線性文字 fallback：在段落 runs
    //   後 append `[註解 作者: 內容]` 標記（mc:Fallback 壓縮、degraded fidelity；
    //   精確錨點範圍 highlight + 互動 panel 留未來 optional sprint）。
    if (para.commentRefs && para.commentRefs.length > 0) {
      if (this.options.renderCommentsAsGroups) {
        // Sprint 361：opt-in 改用 canvas-editor `groupIds` 範圍標記（不 inline 文字）。
        // 把段落內已生成的 IElement 都掛上 groupId；錨點 metadata 收進 commentAnchors。
        for (const id of para.commentRefs) {
          const cmt = this.comments.get(id);
          if (!cmt) continue;
          const groupId = String(id);
          for (const el of paraElements) {
            if (!el.groupIds) el.groupIds = [];
            if (!el.groupIds.includes(groupId)) el.groupIds.push(groupId);
          }
          const anchor: CommentAnchor = {
            groupId,
            id,
            author: cmt.author ?? '',
            body: commentToText(cmt),
          };
          if (cmt.date) anchor.date = cmt.date;
          this.commentAnchors.push(anchor);
        }
      } else {
        // Sprint 184 既有 inline 文字 fallback（VR byte-identical 預設）。
        const cmtBaseProps: RunProps =
          (para.runs.find((r): r is RunNode => r.type === 'run')?.props) ?? {};
        const cmtStyle = mapRunProps(cmtBaseProps);
        for (const id of para.commentRefs) {
          const cmt = this.comments.get(id);
          if (!cmt) continue;
          const body = commentToText(cmt);
          const marker = cmt.author
            ? `[註解 ${cmt.author}: ${body}]`
            : `[註解: ${body}]`;
          this.appendChars(paraElements, marker, cmtStyle);
        }
      }
    }

    // 把 rowFlex / rowMargin 套用到段內所有 IElement（canvas-editor 段落樣式套法）
    if (rowFlex || rowMargin !== undefined) {
      for (const el of paraElements) {
        if (rowFlex) el.rowFlex = rowFlex;
        if (rowMargin !== undefined) el.rowMargin = rowMargin;
      }
    }

    // 段落終止符 \n（也帶段落樣式以確保最後一行對齊正確）
    const terminator: CEElement = { value: '\n' };
    if (rowFlex) terminator.rowFlex = rowFlex;
    if (rowMargin !== undefined) terminator.rowMargin = rowMargin;
    paraElements.push(terminator);

    out.push(...paraElements);
  }

  // ── InlineNode → IElement[] ────────────────────────────────────────────────

  private appendInlineNode(
    out: CEElement[],
    node: InlineNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): void {
    switch (node.type) {
      case 'run':
        this.appendRun(out, node);
        break;
      case 'break':
        if (node.breakType === 'line') {
          out.push({ value: '\n' });
        } else {
          // page / column break → canvas-editor 用 type=pageBreak
          out.push({ type: 'pageBreak', value: '\n' });
        }
        break;
      case 'field': {
        // Sprint 160 v2: <w:instrText> 複雜欄位 render 消費
        // fldChar begin/separate/end 三段語意 → parser 產出 FieldNode
        // renderer 根據 fieldType + instrText 決定輸出內容
        const textToRender = node.cachedValue
          ?? this.fieldPlaceholder(node.fieldType, node.instruction);

        for (const ch of textToRender) {
          out.push({ value: ch });
        }
        break;
      }
      case 'inlineImage':
        this.appendImage(out, node, media);
        break;
      case 'floatImage': {
        // Phase D.1：降級為 inline image（canvas-editor 浮動繞排支援不完整）
        const startIdx = out.length;
        this.appendImage(out, node, media);
        // Sprint Y58: opt-in 把 AnchorMetadata 透傳到剛 push 的第一個 IElement
        if (this.options.preserveAnchorMetadata && out.length > startIdx) {
          attachAnchorExtension(out[startIdx], buildFloatImageAnchor(node));
        }
        break;
      }
      case 'floatTextBox': {
        // Sprint Y58: 預設 drop（與 Sprint 38 以來的 mapper 行為 byte-identical）；
        // opt-in 展平 textbox 內 paragraphs 到當前 inline stream。
        if (this.options.renderFloatTextBox) {
          this.appendFloatTextBox(out, node, media, numbering, counter);
        }
        break;
      }
    }
  }

  // ── Sprint Y58: FloatTextBox → IElement 展平 ──────────────────────────────

  /**
   * 把 FloatTextBoxNode 內的 paragraphs 走完整 appendParagraph 流程併入 inline stream。
   *
   * 設計選擇：
   *  - 用獨立 counter（textbox 內若有 numbered list 不該污染外部 counter）
   *  - 不另外插 pageBreak / section break（textbox 是 inline-level 內容、非新 section）
   *  - 預設樣式由各 paragraph runProps 決定；textbox bodyPr padding 不在 IElement 層面表達
   *    （那是 layout 端的責任、Phase D.1 mapper 不消費）
   *  - 空 paragraphs → 仍會 emit 段落終止符 `\n`（appendParagraph 必加），確保下游不會誤接
   *
   * `preserveAnchorMetadata` 開啟時，把 anchor 透傳掛在第一個 push 的 IElement 上。
   */
  private appendFloatTextBox(
    out: CEElement[],
    node: FloatTextBoxNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    _outerCounter: NumberingCounterState,
  ): void {
    const startIdx = out.length;
    const innerCounter = new NumberingCounterState();
    for (const para of node.paragraphs) {
      this.appendParagraph(out, para, media, numbering, innerCounter);
    }
    if (this.options.preserveAnchorMetadata && out.length > startIdx) {
      attachAnchorExtension(out[startIdx], buildFloatTextBoxAnchor(node));
    }
  }

  // ── Run → IElement[] ──────────────────────────────────────────────────────

  private appendRun(out: CEElement[], run: RunNode): void {
    const baseStyle = mapRunProps(run.props);

    if (run.hyperlink && (run.hyperlink.url || run.hyperlink.anchor)) {
      // hyperlink 包裝：產出 valueList 為文字 IElement[]
      const innerElements: CEElement[] = [];
      this.appendChars(innerElements, run.text, baseStyle);
      const linkEl: CEElement = {
        type: 'hyperlink',
        value: '',
        valueList: innerElements,
      };
      if (run.hyperlink.url) linkEl.url = run.hyperlink.url;
      out.push(linkEl);
    } else {
      this.appendChars(out, run.text, baseStyle);
    }
  }

  /**
   * 把字串拆成字元 IElement，每個字元都帶 baseStyle。
   *
   * canvas-editor 規範：每個字（CJK / 西文）都是獨立的 IElement，
   * 樣式重複出現是預期行為（讓 row breaking / 字型 fallback 在 Renderer 內以字為單位）。
   */
  private appendChars(out: CEElement[], text: string, baseStyle: CEElement): void {
    // 處理 \t / \n 特殊字元
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '\t') {
        out.push({ ...baseStyle, type: 'tab', value: '\t' });
      } else if (ch === '\n') {
        out.push({ ...baseStyle, value: '\n' });
      } else {
        // 用 spread 複製樣式（避免不同字元共用同一物件造成意外突變）
        out.push({ ...baseStyle, value: ch });
      }
    }
  }

  // ── Field placeholder ──────────────────────────────────────────────────────

  /**
   * 根據 fieldType 和原始 instruction 產出佔位文字。
   * 無 cachedValue 時呼叫：讓 layout flow 有可見文字而非空白。
   */
  private fieldPlaceholder(
    fieldType: FieldNode['fieldType'],
    instruction: string,
  ): string {
    switch (fieldType) {
      case 'PAGE':      return '[PAGE]';
      case 'NUMPAGES':  return '[NUMPAGES]';
      case 'DATE':      return '[DATE]';
      case 'TIME':      return '[TIME]';
      case 'AUTHOR':    return '[AUTHOR]';
      case 'FILENAME':  return '[FILENAME]';
      case 'SEQ':       return '[SEQ]';
      case 'TOC':       return '[TOC]';
      case 'REF':       return '[REF]';
      case 'STYLEREF':  return '[STYLEREF]';
      case 'HYPERLINK':
        // HYPERLINK 欄位通常有 anchor/url — 回退到 instruction 片段
        return instruction.trim();
      case 'unknown':
      default:
        // 未識別欄位：用 instruction 本身作可見文字
        return instruction.trim() || '[FIELD]';
    }
  }

  // ── Image ─────────────────────────────────────────────────────────────────

  private appendImage(
    out: CEElement[],
    img: InlineImageNode | FloatImageNode,
    media: Map<string, string>,
  ): void {
    // Sprint 183（Phase 5.2/5.3 render）：SmartArt / Chart graphic frame —— 圖形不
    //   內嵌，以線性文字 fallback 取代（mc:Fallback 壓縮、degraded fidelity）。
    if (img.type === 'inlineImage' && img.graphic) {
      // Sprint 358-359：opt-in 時先試 SVG 渲染（圖表/組織圖視覺化），失敗才落文字
      if (this.options.renderGraphicsAsSvg) {
        const svgImg = this.graphicSvgImage(img.graphic, img.width, img.height);
        if (svgImg) {
          out.push(svgImg);
          return;
        }
      }
      const text = this.graphicFallbackText(img.graphic);
      if (text !== undefined) {
        // 查到對應節點：非空 → append 文字；空內容 → 不 emit（SmartArt/Chart 存在但無文字）
        if (text !== '') this.appendChars(out, text, mapRunProps({}));
        return;
      }
      // text === undefined：查無對應 SmartArt/Chart 節點 → 落下方一般圖片路徑
    }

    const dataUrl = img.rId ? media.get(img.rId) : undefined;
    if (!dataUrl) {
      // 找不到圖片：放空 IElement（值=占位文字）避免下游 crash
      out.push({ value: '[圖片缺失]' });
      return;
    }
    out.push({
      type: 'image',
      value: dataUrl,
      width: img.width,
      height: img.height,
    });
  }

  /**
   * Sprint 183：SmartArt / Chart graphic frame 的線性文字 fallback。
   *
   * @returns 線性文字（可能為空字串＝節點存在但無內容）；
   *          undefined＝查無對應 SmartArt/Chart 節點（caller 落一般圖片路徑）
   */
  private graphicFallbackText(
    graphic: { kind: 'diagram' | 'chart'; relId: string },
  ): string | undefined {
    if (graphic.kind === 'diagram') {
      const sa = this.smartArtsByRId.get(graphic.relId);
      return sa ? smartArtToText(sa) : undefined;
    }
    const chart = this.chartsByRId.get(graphic.relId);
    return chart ? chartToText(chart) : undefined;
  }

  /**
   * Sprint 358-359：SmartArt / Chart → SVG image IElement。
   *
   * @returns image CEElement;查無節點 / renderer 不支援該型別 / 無有效數據 → undefined
   *          （caller 落文字 fallback）
   */
  private graphicSvgImage(
    graphic: { kind: 'diagram' | 'chart'; relId: string },
    width?: number,
    height?: number,
  ): CEElement | undefined {
    let svg: string | null = null;
    if (graphic.kind === 'diagram') {
      const sa = this.smartArtsByRId.get(graphic.relId);
      if (!sa) return undefined;
      svg = renderSmartArtSvg(sa);
    } else {
      const chart = this.chartsByRId.get(graphic.relId);
      if (!chart) return undefined;
      svg = renderChartSvg(chart);
    }
    if (!svg) return undefined;
    return {
      type: 'image',
      value: svgToDataUrl(svg),
      ...(width ? { width } : {}),
      ...(height ? { height } : {}),
    };
  }

  // ── Table → IElement (type='table') ───────────────────────────────────────

  private convertTable(
    table: TableNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): CEElement {
    const colgroup: CEColgroup[] = table.grid.map((w) => ({ width: w }));

    const trList: CETr[] = table.rows.map((row) =>
      this.convertRow(row, media, numbering, counter),
    );

    return {
      type: 'table',
      value: '',
      colgroup,
      trList,
    };
  }

  private convertRow(
    row: RowNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): CETr {
    const tdList: CETd[] = [];
    for (const cell of row.cells) {
      // vMerge continue 格子在 canvas-editor 中不出現（被 anchor 的 rowspan 吸收）
      if (cell.isContinuation) continue;
      tdList.push(this.convertCell(cell, media, numbering, counter));
    }
    return {
      height: row.props.height ?? 0,
      tdList,
    };
  }

  private convertCell(
    cell: CellNode,
    media: Map<string, string>,
    numbering: NumberingMap,
    counter: NumberingCounterState,
  ): CETd {
    // Sprint 5：cell.content 改為 BlockNode[]，paragraphs 直接 append；
    // 巢狀 TableNode 暫時降級成「[巢狀表格 N×M]」文字占位
    // （canvas-editor IElement 結構不支援 cell 內又包 type=table，需自寫 Renderer）。
    const value: CEElement[] = [];
    for (const block of cell.content) {
      if (block.type === 'paragraph') {
        this.appendParagraph(value, block, media, numbering, counter);
      } else if (block.type === 'table') {
        const r = block.rows.length;
        const c = block.grid.length;
        value.push({ value: `[巢狀表格 ${r}×${c}]` });
        value.push({ value: '\n' });
      }
    }
    // 空 cell 至少要有一個段落終止符（canvas-editor 規範）
    if (value.length === 0) {
      value.push({ value: '\n' });
    }

    const td: CETd = {
      colspan: cell.gridSpan,
      rowspan: cell.rowSpan,
      value,
    };
    if (cell.props.shading?.fill) {
      td.backgroundColor = '#' + cell.props.shading.fill;
    }
    if (cell.props.vAlign) {
      td.verticalAlign =
        cell.props.vAlign === 'center'
          ? 'middle'
          : (cell.props.vAlign as 'top' | 'bottom');
    }
    return td;
  }
}

// ── 共用 mapper helper ───────────────────────────────────────────────────────

function mapAlignment(a: Alignment | undefined): CERowFlex | undefined {
  if (!a) return undefined;
  switch (a) {
    case 'left':
      return 'left';
    case 'center':
      return 'center';
    case 'right':
      return 'right';
    case 'justify':
      return 'justify';
    case 'distribute':
      return 'alignment'; // canvas-editor 對應「分散對齊」叫 alignment
    default:
      return undefined;
  }
}

function mapRunProps(props: RunProps): CEElement {
  const out: CEElement = { value: '' };
  // 字型優先序：fontFamilyEastAsia > fontFamily（CJK 文件多）
  // canvas-editor 只接受單一 font，取最具描述性的那個
  const font = props.fontFamilyEastAsia ?? props.fontFamily;
  if (font) out.font = font;
  if (props.fontSize !== undefined) out.size = props.fontSize;
  if (props.bold) out.bold = true;
  if (props.italic) out.italic = true;
  if (props.underline && props.underline !== 'none') out.underline = true;
  if (props.strike) out.strikeout = true;
  if (props.color && props.color !== 'auto') {
    out.color = props.color.startsWith('#') ? props.color : '#' + props.color;
  }
  if (props.highlight) {
    // w:highlight 是具名色（yellow / cyan / lightGray 等），canvas-editor 接受 hex
    // 先做最常見三色映射；其他名稱保留原字（canvas-editor 也接受 css 名）
    out.highlight = mapHighlightColor(props.highlight);
  }
  if (props.spacing !== undefined) out.letterSpacing = props.spacing;
  return out;
}

function mapHighlightColor(name: string): string {
  switch (name.toLowerCase()) {
    case 'yellow':
      return '#FFFF00';
    case 'green':
      return '#00FF00';
    case 'cyan':
      return '#00FFFF';
    case 'magenta':
      return '#FF00FF';
    case 'blue':
      return '#0000FF';
    case 'red':
      return '#FF0000';
    case 'darkblue':
      return '#000080';
    case 'darkcyan':
      return '#008080';
    case 'darkgreen':
      return '#008000';
    case 'darkmagenta':
      return '#800080';
    case 'darkred':
      return '#800000';
    case 'darkyellow':
      return '#808000';
    case 'darkgray':
    case 'darkgrey':
      return '#808080';
    case 'lightgray':
    case 'lightgrey':
      return '#C0C0C0';
    case 'black':
      return '#000000';
    case 'white':
      return '#FFFFFF';
    default:
      return name;
  }
}

// ── Sprint Y58: AnchorExtension helpers ────────────────────────────────────

/**
 * 把 anchor 透傳掛在指定 IElement 上（合併已存在的 anchor 欄位，後者覆蓋前者）。
 * mapper 一次 emit 只會走一次，理論上不會碰撞；defensive merge 保證 hyperlink
 * / table 等已掛 anchor 的元素不被覆寫關鍵欄位。
 */
function attachAnchorExtension(el: CEElement, ext: AnchorExtension): void {
  el.anchor = el.anchor ? { ...el.anchor, ...ext } : ext;
}

function buildFloatImageAnchor(node: FloatImageNode): AnchorExtension {
  const ext: AnchorExtension = {
    source: 'floatImage',
    width: node.width,
    height: node.height,
    posH: node.posH,
    posV: node.posV,
    wrapType: node.wrapType,
  };
  if (node.behindDoc !== undefined) ext.behindDoc = node.behindDoc;
  if (node.allowOverlap !== undefined) ext.allowOverlap = node.allowOverlap;
  if (node.anchor) ext.metadata = node.anchor;
  if (node.wrapText) ext.wrapText = node.wrapText;
  return ext;
}

function buildFloatTextBoxAnchor(node: FloatTextBoxNode): AnchorExtension {
  const ext: AnchorExtension = {
    source: 'floatTextBox',
    width: node.width,
    height: node.height,
    posH: node.posH,
    posV: node.posV,
    wrapType: node.wrapType,
  };
  if (node.behindDoc !== undefined) ext.behindDoc = node.behindDoc;
  if (node.allowOverlap !== undefined) ext.allowOverlap = node.allowOverlap;
  if (node.anchor) ext.metadata = node.anchor;
  if (node.wrapText) ext.wrapText = node.wrapText;
  return ext;
}
