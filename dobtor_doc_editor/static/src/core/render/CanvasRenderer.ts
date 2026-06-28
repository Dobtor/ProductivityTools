/**
 * CanvasRenderer — Layout Engine 輸出 → RenderContext 指令的轉譯器
 *
 * Sprint 8（起步）：
 *   - 走訪 DocumentLayout.pages
 *   - line entry：取 line.items 中的 box（文字）逐 box 送 fillText
 *   - table entry：對每 cell 送 fillText（cell 內 lines）+ drawLine（4 邊邊框）
 *   - image / floatImage：送 drawImage
 *
 * Sprint 9（本檔升級）：
 *   - 升級走訪 cell.blocks（保留巢狀表格混排視覺順序），不再用 flat cell.lines
 *   - 巢狀表格遞迴渲染（NestedTableInCell.rows 用同樣的 row/cell 流程）
 *   - 新增 cell shading（cell.shading.fill → fillRect 全 cell）
 *   - 新增 paragraph shading（Line.paragraphProps.shading.fill → fillRect 該 line 範圍）
 *   - 新增 highlight（Box.runProps.highlight → fillRect 文字背景）
 *   - 新增 underline / strike（Box 上下加 drawLine）
 *
 * 仍保留的 Sprint 8 簡化：
 *   - 相鄰 cell 邊重畫（drawLine ×4 per cell，不 dedupe）
 *   - 雙線/浪線等 style 透傳；由 RenderContext 端詮釋
 */

import type {
  DocumentLayout,
  Page,
  PageEntry,
  Line,
  TableLayoutEntry,
  RowLayout,
  CellLayout,
  CellBlock,
  NestedTableInCell,
  FloatImageEntry,
  ImagePageEntry,
  LinePageEntry,
} from '../layout/types';
import type { Box } from '../layout/types';
import type { Pt, BorderDef, CellBorders, RunProps, DocumentWatermark } from '../ooxml/ast/types';
import type { RenderContext, RenderStrokeStyle, RenderTextStyle } from './types';
import { computeAlignmentShift } from '../layout/alignmentShift';
import { computeVerticalAlignShift } from '../layout/verticalAlignShift';
import { buildParagraph } from '../layout/BoxBuilder';
import { breakParagraph } from '../layout/LineBreaker';
import { EstimateMetrics } from '../layout/TextMetrics';

export interface CanvasRenderOptions {
  /** 是否畫頁面白色背景；false 讓 Context 端自行決定（如 PDF 透明） */
  fillPageBackground?: boolean;
  /** 是否畫表格邊框（Sprint 9 仍只支援 single/double/dashed/dotted） */
  drawTableBorders?: boolean;
  /** 是否畫 cell / paragraph / run 背景（shading / highlight） */
  drawShading?: boolean;
  /** 是否畫文字裝飾（底線 / 刪除線） */
  drawTextDecorations?: boolean;
  /** 預設文字色；RunProps.color 未指定時用 */
  defaultColor?: string;
  /**
   * Sprint 171：頁面背景色（6-hex、不含 '#'）。
   *
   * `fillPageBackground` 為 true 時、整頁以此色填底。預設 `'FFFFFF'`（白）
   * → caller 不傳 → 與 Sprint 0-170 byte-identical。caller 讀
   * `DocumentNode.background?.color`（OOXML `<w:background>`）傳入即生效。
   */
  pageBackgroundColor?: string;
  /**
   * Sprint 173：文件浮水印（`DocumentNode.watermark`、OOXML header VML shape）。
   *
   * 提供後、每頁於背景之上、內容之下繪浮水印（文字浮水印：旋轉淺灰文字）。
   * caller 不傳 → 不繪 → 與 Sprint 0-172 byte-identical。
   * Sprint 173 只繪文字浮水印（kind='text'）；圖片浮水印需 shape 尺寸、留後續。
   */
  watermark?: DocumentWatermark;
}

/** watermark 由 class 另存（無預設值、不進 Required<> defaulting）。 */
type DefaultedRenderOptions = Required<Omit<CanvasRenderOptions, 'watermark'>>;

const DEFAULTS: DefaultedRenderOptions = {
  fillPageBackground: true,
  drawTableBorders: true,
  drawShading: true,
  drawTextDecorations: true,
  defaultColor: '000000',
  pageBackgroundColor: 'FFFFFF',
};

/** 文字裝飾線寬：底線 / 刪除線預設 0.5pt（Word 預設 1px @96dpi 約 0.75pt，取近似） */
const DECORATION_WIDTH_PT = 0.5;

/** Sprint 173：浮水印淺灰色（Word washout 風格；RenderContext 無 alpha、以淺灰近似）。 */
const WATERMARK_COLOR = 'C8C8C8';
/** 浮水印文字目標寬度佔頁寬比例。 */
const WATERMARK_WIDTH_RATIO = 0.7;
/** 浮水印字寬量測參考字級（pt）。 */
const WATERMARK_REF_FONT_SIZE = 100;
/** 浮水印字級上限（pt）。 */
const WATERMARK_MAX_FONT_SIZE = 130;

export class CanvasRenderer {
  private opts: DefaultedRenderOptions;
  private watermark?: DocumentWatermark;

  constructor(private ctx: RenderContext, opts: CanvasRenderOptions = {}) {
    this.opts = { ...DEFAULTS, ...opts };
    this.watermark = opts.watermark;
  }

  /** 走訪整份 layout，逐頁送指令到 RenderContext。 */
  render(layout: DocumentLayout): void {
    for (const page of layout.pages) {
      this.renderPage(page);
    }
  }

  private renderPage(page: Page): void {
    this.ctx.beginPage(page.pageNumber, page.width, page.height);
    if (this.opts.fillPageBackground) {
      // Sprint 171：頁底色 = pageBackgroundColor（預設 'FFFFFF'、OOXML <w:background> 來源）
      this.ctx.fillRect(0, 0, page.width, page.height, this.opts.pageBackgroundColor);
    }
    // Sprint 173：浮水印繪於背景之上、內容之下
    this.renderWatermark(page);
    for (const entry of page.entries) {
      this.renderEntry(entry);
    }
    // Sprint 10：欄分隔線（多欄頁面 + columns.separator=true）
    if (page.columnLayout?.separator) {
      this.renderColumnSeparators(page);
    }
    this.ctx.endPage();
  }

  /**
   * Sprint 173：繪文件浮水印（kind='text'）—— 旋轉淺灰文字置中於頁面。
   *
   * 字級由文字寬度反推（目標寬約佔頁寬 70%、上限 130pt）；以 save/translate/rotate
   * 把原點移到頁心、依 `rotation`（度）旋轉、再以 baseline 校正繪文字。
   * 無浮水印 / 非文字浮水印 → no-op（圖片浮水印需 shape 尺寸、留後續 sprint）。
   */
  private renderWatermark(page: Page): void {
    const wm = this.watermark;
    if (!wm || wm.kind !== 'text' || !wm.text) return;

    const metrics = new EstimateMetrics();
    const refWidth = metrics.measureWidth(wm.text, {
      fontSize: WATERMARK_REF_FONT_SIZE,
      fontFamily: wm.font,
    });
    if (!(refWidth > 0)) return;

    const target = page.width * WATERMARK_WIDTH_RATIO;
    const fontSize = Math.min(
      WATERMARK_MAX_FONT_SIZE,
      (WATERMARK_REF_FONT_SIZE * target) / refWidth,
    );
    const props: RunProps = { fontSize, fontFamily: wm.font, color: WATERMARK_COLOR };
    const textWidth = metrics.measureWidth(wm.text, props);

    this.ctx.save();
    this.ctx.translate(page.width / 2, page.height / 2);
    if (wm.rotation) {
      this.ctx.rotate((wm.rotation * Math.PI) / 180);
    }
    // 原點在頁心：x 往左推半個文字寬置中；y 加 fontSize×0.35 把視覺中心對齊基線
    this.ctx.fillText(wm.text, -textWidth / 2, fontSize * 0.35, runStyle(props, WATERMARK_COLOR));
    this.ctx.restore();
  }

  /** Sprint 10：在多欄頁面相鄰欄之間畫垂直分隔線。 */
  private renderColumnSeparators(page: Page): void {
    const cl = page.columnLayout;
    if (!cl || cl.count <= 1) return;
    const yTop = page.margins.top;
    const yBottom = page.height - page.margins.bottom;
    for (let i = 0; i < cl.count - 1; i++) {
      const colEnd = cl.startX[i] + cl.widths[i];
      const nextStart = cl.startX[i + 1];
      const xMid = (colEnd + nextStart) / 2;
      this.ctx.drawLine(xMid, yTop, xMid, yBottom, {
        color: '000000', width: 0.5, style: 'single',
      });
    }
  }

  private renderEntry(entry: PageEntry): void {
    switch (entry.kind) {
      case 'line':
        this.renderLineEntry(entry);
        return;
      case 'table':
        this.renderTableEntry(entry);
        return;
      case 'image':
        this.renderImageEntry(entry);
        return;
      case 'floatImage':
        this.renderFloatImage(entry);
        return;
      case 'table-placeholder':
        // Sprint 2 fallback：不繪內容，僅占位
        return;
    }
  }

  private renderLineEntry(entry: LinePageEntry): void {
    // page-level paragraph shading：覆蓋整個 line 寬度
    if (this.opts.drawShading) {
      const shadingFill = entry.line.paragraphProps?.shading?.fill;
      if (shadingFill) {
        this.ctx.fillRect(entry.x, entry.y, entry.width, entry.height, shadingFill);
      }
    }
    this.renderLine(entry.line, entry.x, entry.y, entry.width);
  }

  /**
   * 渲染一條 Line：對 line.items 走訪 box 逐個送 fillText。
   *
   * 座標：
   *   - x 起點 = baseX + line.xOffset
   *     （wrapSquare 推右；page-level 對齊 shift 由 Paginator 預先加到 entry.x；
   *      cell-level 對齊 shift 由 renderCellBlock 處理）
   *   - 每 box 走完 advance（box.width + 任何 glue 的 width）
   *   - y baseline = baseY + line.baseline
   *   - Sprint 167：`<w:textAlignment>` 非 baseline 時、各 box 依與行內最高
   *     box 的高度差額外 y 位移（等高行位移恆 0 → byte-identical）
   */
  private renderLine(line: Line, baseX: Pt, baseY: Pt, _lineWidth: Pt): void {
    const yBaseline = baseY + line.baseline;
    let cursor = baseX + (line.xOffset ?? 0);
    // Sprint 167：textAlignment 非 baseline 時才計算行內最高 box（其餘走預設路徑、零成本）
    const textAlignment = line.paragraphProps?.textAlignment;
    let maxBoxHeight = 0;
    if (textAlignment && textAlignment !== 'baseline' && textAlignment !== 'auto') {
      for (const it of line.items) {
        if (it.kind === 'box' && it.height > maxBoxHeight) maxBoxHeight = it.height;
      }
    }
    for (const item of line.items) {
      if (item.kind === 'box') {
        const box = item as Box;
        const yShift = maxBoxHeight > 0
          ? computeVerticalAlignShift(textAlignment, box.height, maxBoxHeight)
          : 0;
        const yBox = yBaseline + yShift;
        if (box.text && !box.isImage) {
          this.renderBox(box, cursor, yBox, line.height);
        } else if (box.isImage && box.imageRId) {
          // Sprint 40：傳 imageSrcRect（如有）給 RenderContext.drawImage 做 source crop
          this.ctx.drawImage(box.imageRId, cursor, yBox - box.height, box.width, box.height, box.imageSrcRect);
        }
        cursor += box.width;
      } else if (item.kind === 'glue') {
        cursor += item.width;
      }
      // penalty：不影響 cursor（width 通常為 0）
    }
  }

  /** 單一 Box 文字 + 裝飾 + highlight 的繪製。座標 = (x, baseline)。 */
  private renderBox(box: Box, x: Pt, yBaseline: Pt, lineHeight: Pt): void {
    const fontSize = box.runProps.fontSize ?? 10.5;
    // highlight：在文字前畫底色矩形（從 baseline 上推 ascender 約 0.85 × fontSize）
    if (this.opts.drawShading && box.runProps.highlight) {
      const ascent = fontSize * 0.85;
      this.ctx.fillRect(x, yBaseline - ascent, box.width, lineHeight, box.runProps.highlight);
    }
    // 文字本體
    this.ctx.fillText(box.text, x, yBaseline, runStyle(box.runProps, this.opts.defaultColor));
    // 裝飾線
    if (this.opts.drawTextDecorations) {
      const color = box.runProps.color ?? this.opts.defaultColor;
      if (box.runProps.underline && box.runProps.underline !== 'none') {
        const yU = yBaseline + fontSize * 0.15;
        this.ctx.drawLine(x, yU, x + box.width, yU, {
          color, width: DECORATION_WIDTH_PT, style: 'single',
        });
        if (box.runProps.underline === 'double') {
          const yU2 = yU + fontSize * 0.1;
          this.ctx.drawLine(x, yU2, x + box.width, yU2, {
            color, width: DECORATION_WIDTH_PT, style: 'single',
          });
        }
      }
      if (box.runProps.strike) {
        const yS = yBaseline - fontSize * 0.3;
        this.ctx.drawLine(x, yS, x + box.width, yS, {
          color, width: DECORATION_WIDTH_PT, style: 'single',
        });
      }
      // Sprint 175：追蹤修訂標記 —— `<w:ins>` 插入畫底線、`<w:del>` 刪除畫刪除線
      //   （run 本身已有對應裝飾時不重畫、避免雙線）
      if (box.revision?.type === 'ins'
        && !(box.runProps.underline && box.runProps.underline !== 'none')) {
        const yU = yBaseline + fontSize * 0.15;
        this.ctx.drawLine(x, yU, x + box.width, yU, {
          color, width: DECORATION_WIDTH_PT, style: 'single',
        });
      }
      if (box.revision?.type === 'del' && !box.runProps.strike) {
        const yS = yBaseline - fontSize * 0.3;
        this.ctx.drawLine(x, yS, x + box.width, yS, {
          color, width: DECORATION_WIDTH_PT, style: 'single',
        });
      }
    }
  }

  private renderTableEntry(entry: TableLayoutEntry): void {
    this.renderRows(entry.rows, entry.x, entry.y);
  }

  /**
   * 共用：渲染一組 RowLayout（同樣邏輯給頂層 table 與巢狀 table 用）。
   *
   * Sprint 33：vMerge anchor cell（rowSpan > 1）需用「合併高度」渲染，
   * 否則 shading / 底邊框 / 4 邊框會停在 row[0].height，造成被合併區域中間出現
   * 一條水平邊（c0 的 bottom border 提前在 row0 結束、row1 對應位置空白）。
   * 修正 03_complex_table 全套管系列 5 fixture page 1 的「合併儲存格被切」問題。
   *
   * 計算規則：對 `cell.rowSpan > 1` 的 anchor cell 累加從當前 row 起 rowSpan 個 row.height
   * （超出 rows 長度時截斷；rowSpan 1 退化為原行為）。
   */
  private renderRows(rows: RowLayout[], baseX: Pt, baseY: Pt): void {
    let yCursor = baseY;
    for (let ri = 0; ri < rows.length; ri++) {
      const row = rows[ri];
      let xCursor = baseX;
      for (const cell of row.cells) {
        if (!cell.isContinuation) {
          const cellHeight = this.computeMergedCellHeight(rows, ri, cell.rowSpan, row.height);
          this.renderCell(cell, xCursor, yCursor, cellHeight);
        }
        xCursor += cell.width;
      }
      yCursor += row.height;
    }
  }

  /** Sprint 33：算 vMerge anchor cell 跨 rowSpan 列的合併高度。 */
  private computeMergedCellHeight(
    rows: RowLayout[],
    startRow: number,
    rowSpan: number,
    fallbackHeight: Pt,
  ): Pt {
    if (rowSpan <= 1) return fallbackHeight;
    let h = 0;
    const last = Math.min(startRow + rowSpan, rows.length);
    for (let r = startRow; r < last; r++) {
      h += rows[r].height;
    }
    return h;
  }

  private renderCell(cell: CellLayout, x: Pt, y: Pt, rowHeight: Pt): void {
    // Pass 1：cell 背景
    if (this.opts.drawShading && cell.shading?.fill) {
      this.ctx.fillRect(x, y, cell.width, rowHeight, cell.shading.fill);
    }

    // Sprint 37：cell-internal floats — behindDoc=true 的先畫（在文字之下）
    if (cell.floats) {
      for (const f of cell.floats) {
        if (f.node.behindDoc) this.drawCellFloat(f, x, y);
      }
    }

    // Sprint 35：V-variant（lrTbV / tbRlV / tbLrV）走 char-level CJK 直書路徑。
    // 規格意義（OOXML §17.18.93 ST_TextDirection）：V-suffix = glyph orientation
    // **preserved**（字符保持正向），不是 ctx.rotate(π/2)（Sprint 34 第一輪 revert 教訓）。
    // 實作：每字符獨立 fillText 正向放置；多 paragraph = 多列；列方向：
    //   - tbRlV：列從右→左（CJK 直書最常見）
    //   - tbLrV / lrTbV：列從左→右
    if (isVerticalCellDirection(cell.textDirection)) {
      this.renderCellVertical(cell, x, y, rowHeight);
    } else {
      // Sprint 42：依 cell.vAlign 計算 yCursor 起點（OOXML §17.4.84 w:vAlign）
      //   - top（預設）：padding.top
      //   - center：上下 padding 內均勻分布剩餘空間
      //   - bottom：黏底
      // 注意：當 rowHeight ≤ contentHeight + padding.top + padding.bottom 時 vAlign 無作用（內容已填滿）
      let yCursor = computeVAlignYStart(y, rowHeight, cell.padding, cell.contentHeight, cell.vAlign);
      const innerWidth = Math.max(cell.width - cell.padding.left - cell.padding.right, 1);
      for (const block of cell.blocks) {
        yCursor += this.renderCellBlock(block, x + cell.padding.left, yCursor, innerWidth);
      }
    }

    // Sprint 37：cell-internal floats — behindDoc=false（預設）的在文字後畫（覆蓋於文字之上）
    if (cell.floats) {
      for (const f of cell.floats) {
        if (!f.node.behindDoc) this.drawCellFloat(f, x, y);
      }
    }

    // Pass 3：4 邊邊框（畫在最上層避免被 shading 覆蓋）
    if (this.opts.drawTableBorders && cell.borders) {
      this.drawCellBorders(x, y, cell.width, rowHeight, cell.borders);
    }
  }

  /**
   * Sprint 37：繪製 cell 內 floatImage（wp:anchor）。
   *
   * float.xRel / yRel 已是 cell-relative（cell 左上原點 + padding 為起點累加 posOffset）；
   * 加 cell 起點絕對座標就是 page 絕對座標。
   *
   * 對於 wrapType：
   *   - none / behindText / inFrontOfText：簡單放圖（不影響行排版，已在 layoutCell 不進 items）
   *   - square / tight / through / topAndBottom：cell 內 wrap 處理留 Sprint 38+；
   *     當前一律當 inFront/behind 直接畫（多數 03 全套管 anchor 都用 wrapNone）
   */
  private drawCellFloat(
    f: import('../layout/types').CellFloat,
    cellX: Pt,
    cellY: Pt,
  ): void {
    const x = cellX + f.xRel;
    const y = cellY + f.yRel;
    if (f.node.type === 'floatImage') {
      // Sprint 40：cell-internal float image 也走 srcRect 路徑
      this.ctx.drawImage(f.node.rId, x, y, f.node.width, f.node.height, f.node.srcRect);
      return;
    }
    // Sprint 38：floatTextBox — 對 text box 內每個 paragraph 跑 LineBreaker（lineWidth = textbox.width）
    // 後逐行 fillText 在 abs position
    this.drawCellTextBoxFloat(f.node, x, y);
  }

  /**
   * Sprint 38 / Sprint 39：渲染 cell-internal `<wp:anchor>` text box 內容。
   *
   * 演算法：
   *   1. （Sprint 39）若 node.fill 有值 → 先 fillRect(textbox 矩形)
   *   2. 對 textbox.paragraphs 逐段跑 BoxBuilder + LineBreaker（lineWidth = textbox.width - padding）
   *   3. 逐行 fillText 在 abs position：每行 y = baseY + cumulative line height + baseline
   *   4. 超出 textbox.height 的行截斷不繪
   *   5. （Sprint 39）若 node.border 有值 → 最後畫 4 邊
   *
   * Padding 使用 node.bodyPr（Sprint 39 解析）→ 沒設用 OOXML 預設值（L/R=7.2pt、T/B=3.6pt）。
   *
   * 用 EstimateMetrics 配合 line break 的字寬估算（與其他 cell text 一致）。
   */
  private drawCellTextBoxFloat(
    node: import('../ooxml/ast/types').FloatTextBoxNode,
    x: Pt,
    y: Pt,
  ): void {
    if (node.paragraphs.length === 0 && !node.fill && !node.border) return;

    // Sprint 39：textbox 背景色（在文字之前畫）
    if (this.opts.drawShading && node.fill) {
      this.ctx.fillRect(x, y, node.width, node.height, node.fill);
    }

    // Sprint 39：bodyPr padding（OOXML 預設值與 Office 一致）
    const DEFAULT_LR_PT = 7.2; // 91440 EMU
    const DEFAULT_TB_PT = 3.6; // 45720 EMU
    const padL = node.bodyPr?.leftInset ?? DEFAULT_LR_PT;
    const padT = node.bodyPr?.topInset ?? DEFAULT_TB_PT;
    const padR = node.bodyPr?.rightInset ?? DEFAULT_LR_PT;
    const padB = node.bodyPr?.bottomInset ?? DEFAULT_TB_PT;

    const innerWidth = Math.max(node.width - padL - padR, 1);
    const innerHeight = Math.max(node.height - padT - padB, 1);

    if (node.paragraphs.length > 0) {
      const metrics = new EstimateMetrics();
      let cursorY = y + padT;
      const limitY = y + padT + innerHeight;
      for (let pi = 0; pi < node.paragraphs.length; pi++) {
        const para = node.paragraphs[pi];
        const input = buildParagraph(para, pi, metrics);
        const lines = breakParagraph(input, {
          lineWidth: innerWidth,
          firstLineIndent: para.props.indent?.firstLine,
          metrics,
        });
        for (const ln of lines) {
          if (cursorY + ln.height > limitY) break;  // 截斷後仍要畫邊框
          this.renderLine(ln, x + padL, cursorY, innerWidth);
          cursorY += ln.height;
        }
      }
    }

    // Sprint 39：textbox 邊框（4 邊）— 在文字之後畫
    if (this.opts.drawTableBorders && node.border) {
      const stroke = {
        color: node.border.color,
        width: node.border.width,
        style: 'single' as const,
      };
      this.ctx.drawLine(x, y, x + node.width, y, stroke);                               // top
      this.ctx.drawLine(x + node.width, y, x + node.width, y + node.height, stroke);    // right
      this.ctx.drawLine(x + node.width, y + node.height, x, y + node.height, stroke);   // bottom
      this.ctx.drawLine(x, y + node.height, x, y, stroke);                              // left
    }
  }

  /**
   * Sprint 35：char-level CJK 直書渲染（V-variant cells）。
   *
   * 把 cell.blocks 中所有 paragraph 的 inline text 拆成「列」：
   *   - 每個 lines block（一個 source paragraph）= 一列
   *   - 列內 lines 串接 → 逐字符垂直堆疊
   *
   * 字符位置（每字符正向、不旋轉）：
   *   columnX = 列起始 X（依 textDirection 決定方向）
   *   drawX   = columnX + (colWidth - fontSize) / 2           # 字符居中於列
   *   drawY   = charY + fontSize × 0.8                        # baseline 在字符上緣下推 0.8em
   *   charY  += fontSize × 1.0                                # CJK advance = 1.0 em
   *
   * 列方向：
   *   - tbRlV：起始 columnX = 右側 cell 內側 - colWidth；advance = -colWidth
   *   - tbLrV / lrTbV：起始 columnX = 左 padding；advance = +colWidth
   *
   * 截斷：若 charY + fontSize > innerBottomLimit 則停止本列（避免越界畫到鄰列）。
   */
  private renderCellVertical(cell: CellLayout, x: Pt, y: Pt, rowHeight: Pt): void {
    const padding = cell.padding;
    const innerLeft = x + padding.left;
    const innerRight = x + cell.width - padding.right;
    const innerTop = y + padding.top;
    const innerBottomLimit = y + rowHeight - padding.bottom;

    type CharCell = { ch: string; runProps: RunProps; fontSize: Pt };
    const columns: CharCell[][] = [];
    let maxFont = 0;
    for (const block of cell.blocks) {
      if (block.kind !== 'lines') continue;
      const col: CharCell[] = [];
      for (const ln of block.lines) {
        for (const item of ln.items) {
          if (item.kind !== 'box') continue;
          const box = item as Box;
          if (box.isImage || !box.text) continue;
          const fontSize = box.runProps.fontSize ?? 10.5;
          if (fontSize > maxFont) maxFont = fontSize;
          for (const ch of Array.from(box.text)) {
            col.push({ ch, runProps: box.runProps, fontSize });
          }
        }
      }
      if (col.length > 0) columns.push(col);
    }
    if (columns.length === 0) return;

    const colWidth = Math.max(maxFont, 1);
    const rtl = cell.textDirection === 'tbRlV';

    let columnX = rtl ? innerRight - colWidth : innerLeft;
    const advance = rtl ? -colWidth : colWidth;

    for (const col of columns) {
      let charY = innerTop;
      for (const c of col) {
        if (charY + c.fontSize > innerBottomLimit) break;
        const drawX = columnX + (colWidth - c.fontSize) / 2;
        const drawY = charY + c.fontSize * 0.8;
        this.ctx.fillText(c.ch, drawX, drawY, runStyle(c.runProps, this.opts.defaultColor));
        charY += c.fontSize;
      }
      columnX += advance;
    }
  }

  /** 渲染單一 CellBlock；回傳該 block 高度（caller 用來 advance yCursor）。 */
  private renderCellBlock(block: CellBlock, x: Pt, y: Pt, innerWidth: Pt): Pt {
    if (block.kind === 'lines') {
      let yLine = y;
      for (const ln of block.lines) {
        // Sprint 32：cell-level paragraph alignment（center / right）→ 加到 x 起點
        const alignShift = computeAlignmentShift(ln.alignment, ln.width, innerWidth);
        // Per-paragraph shading（仍以 cell innerWidth 為背景寬，shading 不隨 alignment 偏移）
        if (this.opts.drawShading) {
          const shadingFill = ln.paragraphProps?.shading?.fill;
          if (shadingFill) {
            this.ctx.fillRect(x, yLine, innerWidth, ln.height, shadingFill);
          }
        }
        this.renderLine(ln, x + alignShift, yLine, innerWidth);
        yLine += ln.height;
      }
      return block.height;
    }
    // kind === 'table'
    this.renderNestedTable(block.table, x, y);
    return block.table.height;
  }

  private renderNestedTable(t: NestedTableInCell, x: Pt, y: Pt): void {
    // NestedTableInCell.rows 內 cells 的 width 已是 inner column width
    this.renderRows(t.rows, x, y);
  }

  private drawCellBorders(x: Pt, y: Pt, w: Pt, h: Pt, borders: CellBorders): void {
    if (borders.top && isVisibleBorder(borders.top))
      this.ctx.drawLine(x, y, x + w, y, toStroke(borders.top));
    if (borders.bottom && isVisibleBorder(borders.bottom))
      this.ctx.drawLine(x, y + h, x + w, y + h, toStroke(borders.bottom));
    if (borders.left && isVisibleBorder(borders.left))
      this.ctx.drawLine(x, y, x, y + h, toStroke(borders.left));
    if (borders.right && isVisibleBorder(borders.right))
      this.ctx.drawLine(x + w, y, x + w, y + h, toStroke(borders.right));
  }

  private renderImageEntry(entry: ImagePageEntry): void {
    // Sprint 40：傳 srcRect（如有）
    this.ctx.drawImage(entry.rId, entry.x, entry.y, entry.width, entry.height, entry.srcRect);
  }

  private renderFloatImage(f: FloatImageEntry): void {
    // Sprint 40：傳 srcRect（如有）
    this.ctx.drawImage(f.rId, f.x, f.y, f.width, f.height, f.srcRect);
  }
}

/** Sprint 35：判斷 V-variant cell（OOXML §17.18.93 V-suffix = glyph orientation preserved）。 */
function isVerticalCellDirection(td: CellLayout['textDirection']): boolean {
  return td === 'tbRlV' || td === 'lrTbV' || td === 'tbLrV';
}

/**
 * Sprint 42：依 OOXML §17.4.84 w:vAlign 計算 cell 內容區 Y 起點（pt）。
 *
 * @param y           cell 左上角絕對 Y
 * @param rowHeight   cell 視覺高度（已含 padding，rowSpan 合併後值）
 * @param padding     cell 四邊 padding
 * @param contentHeight  TableLayout pass 預算的 cell 內容（blocks）總高
 * @param vAlign      'top' | 'center' | 'bottom'
 *
 * Sanity：當 contentHeight ≥ availableHeight（內容已填滿可用區）時，center/bottom 退化為 top
 * 避免負偏移把 content 推到 cell 外。
 */
function computeVAlignYStart(
  y: Pt,
  rowHeight: Pt,
  padding: { top: Pt; bottom: Pt; left: Pt; right: Pt },
  contentHeight: Pt,
  vAlign: 'top' | 'center' | 'bottom',
): Pt {
  if (vAlign === 'top') return y + padding.top;
  const availableHeight = rowHeight - padding.top - padding.bottom;
  if (contentHeight >= availableHeight) return y + padding.top;
  if (vAlign === 'center') {
    return y + padding.top + (availableHeight - contentHeight) / 2;
  }
  // bottom
  return y + rowHeight - padding.bottom - contentHeight;
}

function isVisibleBorder(b: BorderDef): boolean {
  return b.style !== 'nil' && b.style !== 'none' && b.width > 0;
}

function toStroke(b: BorderDef): RenderStrokeStyle {
  return { color: b.color, width: b.width, style: b.style };
}

function runStyle(rp: RunProps, defaultColor: string): RenderTextStyle {
  const out: RenderTextStyle = {
    fontSize: rp.fontSize ?? 10.5,
    color: rp.color ?? defaultColor,
  };
  if (rp.fontFamily) out.fontFamily = rp.fontFamily;
  if (rp.bold) out.bold = true;
  if (rp.italic) out.italic = true;
  if (rp.underline && rp.underline !== 'none') out.underline = rp.underline;
  if (rp.strike) out.strike = true;
  if (rp.highlight) out.highlight = rp.highlight;
  return out;
}
