/**
 * TableLayout — TableNode → RowLayout[]（cell-level 排版）
 *
 * Sprint 3 範圍：
 *   - 用 grid[] 直接配欄寬（fixed layout 的簡化版）
 *   - 對每個 cell 內 paragraph 跑 LineBreaker → CellLayout.lines
 *   - 算 row 高度 = max(cell heights)
 *   - vMerge：anchor cell 放內容；continuation cell 標 isContinuation
 *   - rowSpan/gridSpan 由 GridResolver 已預先填好（CellNode.gridSpan/rowSpan）
 *
 * 不在本 Sprint 範圍：
 *   - CSS2 auto layout（content-driven 欄寬重新分配）
 *   - 巢狀表格（cell 內又有 table；目前 cell 內 paragraph 有就排，table 跳過）
 *   - 邊框衝突解決（OOXML 17.4.65 8 級優先表 — 留 Renderer 處理）
 *   - 表格浮動（罕見規格）
 */

import type {
  TableNode,
  RowNode,
  CellNode,
  FloatImageNode,
  FloatTextBoxNode,
  ParagraphNode,
  Pt,
  RunNode,
  RunProps,
  NumberingMap,
} from '../ooxml/ast/types';
import type {
  CellBlock,
  CellFloat,
  CellLayout,
  NestedTableInCell,
  RowLayout,
  TextMetrics,
  LayoutOptions,
} from './types';
import { buildParagraph, type NumberingPrefix } from './BoxBuilder';
import { breakParagraph } from './LineBreaker';
import { EstimateMetrics } from './TextMetrics';
import { NumberingCounterState, expandLvlText } from '../ooxml/numbering';

/**
 * Sprint 139：與 Paginator.computeNumberingPrefix 對稱的 helper。
 *
 * 抽出在此模組避免 layout/ → ooxml/ → layout/ 的循環依賴；caller 從 options
 * 拿 NumberingMap + _numberingCounter（後者由 Paginator 注入）後呼叫。
 */
function computeNumberingPrefixForCell(
  para: ParagraphNode,
  numbering: NumberingMap | undefined,
  counter: NumberingCounterState | undefined,
): NumberingPrefix | undefined {
  if (!numbering || !counter || para.props.numId === undefined) return undefined;
  const ilvl = para.props.ilvl ?? 0;
  const abstractNum = numbering.get(para.props.numId);
  const result = counter.advance(para.props.numId, ilvl, abstractNum);
  const text = expandLvlText(result.level.text, result.counters, result.numFmts);
  if (text === '') return undefined;
  const firstRun = para.runs.find((r): r is RunNode => r.type === 'run');
  const baseProps: RunProps = firstRun?.props ?? result.level.runProps ?? {};
  return { text, runProps: baseProps };
}

const DEFAULT_CELL_PADDING_PT = 5; // OOXML 規格預設 100 twips = 5pt（左右）/ 0pt（上下）
const DEFAULT_CELL_PADDING_TOP = 0;

/** 算每欄 grid 的實際 pt 寬（簡化版：直接拿 TableNode.grid）。
 *  若 grid 全部為 0 / undefined（罕見），平均分配 contentWidth。*/
export function allocateColumnWidths(table: TableNode, contentWidth: Pt): Pt[] {
  const grid = table.grid;
  if (!grid || grid.length === 0) return [];
  const sum = grid.reduce((a, b) => a + b, 0);
  if (sum > 0) return grid.slice();
  // fallback：平分
  const w = contentWidth / grid.length;
  return grid.map(() => w);
}

/**
 * 對單一 cell 跑 paragraph layout，回 CellLayout（不算 row height，由 caller 統一處理）。
 *
 * Sprint 34：`rowHeightHint` 給垂直文字 cell（textDirection=V-variant）當 lineWidth 上限。
 * Caller（layoutRow）若知道顯式 `<w:trHeight>` 則傳入；否則 undefined 退化用 10000pt 寬鬆 break。
 */
export function layoutCell(
  cell: CellNode,
  cellWidth: Pt,
  cellIndex: number,
  table: TableNode,
  options: LayoutOptions = {},
  rowHeightHint?: Pt,
): CellLayout {
  const metrics = options.metrics ?? new EstimateMetrics();
  const tablePadding = table.props.cellMargins ?? {};
  const padding = {
    top: cell.props.margins?.top ?? tablePadding.top ?? DEFAULT_CELL_PADDING_TOP,
    bottom: cell.props.margins?.bottom ?? tablePadding.bottom ?? DEFAULT_CELL_PADDING_TOP,
    left: cell.props.margins?.left ?? tablePadding.left ?? DEFAULT_CELL_PADDING_PT,
    right: cell.props.margins?.right ?? tablePadding.right ?? DEFAULT_CELL_PADDING_PT,
  };
  const innerWidth = Math.max(cellWidth - padding.left - padding.right, 1);
  // Sprint 34：textDirection 從 cell.props 透傳到 CellLayout（為未來 vertical render 預留）
  // 但 layout 演算法本身**回退到水平流程**（Sprint 34 確認 canvas rotate ≠ CJK 直書，
  // 正確 CJK 字符正向 + 垂直排列實作要 char-level render，留 Sprint 35+ 處理）
  const td = cell.props.textDirection;
  void rowHeightHint; // 暫不使用，避免 unused 警告；保留參數為將來 vertical render 用

  // vMerge continuation：不排內容，只占位
  if (cell.isContinuation) {
    return {
      cellIndex,
      gridCol: cell.gridCol,
      gridSpan: cell.gridSpan,
      rowSpan: cell.rowSpan,
      isContinuation: true,
      width: cellWidth,
      height: 0, // 由 anchor cell 決定
      lines: [],
      blocks: [],
      padding,
      vAlign: cell.props.vAlign ?? 'top',
      contentHeight: 0, // Sprint 42
      contentHeightUnsnapped: 0, // Sprint 47
      ...(cell.props.borders ? { borders: cell.props.borders } : {}),
      ...(cell.props.shading ? { shading: cell.props.shading } : {}),
    };
  }

  // Sprint 6：cell.content 為 BlockNode[]，blocks 按 source order 排列
  // - paragraph：跑 LineBreaker → CellBlock kind='lines'
  // - table：遞迴 layoutTable → CellBlock kind='table'
  // 保留 Sprint 5 的 lines / nestedTables 為向下相容平面欄位
  const blocks: CellBlock[] = [];
  const flatLines: CellLayout['lines'] = [];
  const flatNested: NestedTableInCell[] = [];
  // Sprint 37：cell-internal floatImage（wp:anchor）— 每 paragraph 處理前先 filter；
  // 累積到 cellFloats 內，xRel/yRel 用 cell 左上原點 + padding 算（cell 左上 = (0,0)）。
  // 排除這段 simplification 之前 BoxBuilder L52 把 floatImage 當 inline Box 推進段內，
  // 是 Sprint 36 grid analysis 找到的 03 全套管 5 fixture × 0.30 真根因。
  const cellFloats: CellFloat[] = [];
  let contentHeight = 0;
  // Sprint 47：未經 docGrid snap 的內容高（val-as-min 比較基準）
  let contentHeightUnsnapped = 0;

  for (let pi = 0; pi < cell.content.length; pi++) {
    const block = cell.content[pi];
    if (block.type === 'paragraph') {
      // Sprint 37/38：把 floatImage / floatTextBox 從 paragraph.runs 提取出來，
      // 剩下走原本 inline flow；floats 走 cell-relative abs position
      const { paraWithoutFloats, floats } = extractFloats(block);
      // 段落起始 y（cell-relative）= 目前已累積 content + padding.top
      // 注意：cell 是 [0, cell.width] × [0, cell.height] 的 local 座標
      //       padding.top 是內容區起始；contentHeight 是已排版 block 高度
      const paraStartYRel = padding.top + contentHeight;
      const indentLeft = block.props.indent?.left ?? 0;
      const indentRight = block.props.indent?.right ?? 0;
      const lineWidth = Math.max(innerWidth - indentLeft - indentRight, 1);
      const prefix = computeNumberingPrefixForCell(
        paraWithoutFloats,
        options.numbering,
        options._numberingCounter,
      );
      const input = buildParagraph(paraWithoutFloats, pi, metrics, prefix);
      const lines = breakParagraph(input, {
        lineWidth,
        firstLineIndent: block.props.indent?.firstLine,
        metrics,
        docGridLinePitch: options.docGridLinePitch,
        defaultTabStop: options.defaultTabStop,
      });
      let h = 0;
      let hUnsnapped = 0;
      for (const l of lines) {
        h += l.height;
        hUnsnapped += l.heightUnsnapped ?? l.height;
      }
      blocks.push({ kind: 'lines', sourceIndex: pi, lines, height: h });
      flatLines.push(...lines);
      contentHeight += h;
      contentHeightUnsnapped += hUnsnapped;

      // Sprint 37：把這段的 floatImage 解析為 cell-relative 位置
      for (const fi of floats) {
        cellFloats.push(resolveCellFloat(fi, padding, innerWidth, paraStartYRel));
      }
    } else if (block.type === 'table') {
      const inner = layoutTable(block, innerWidth, options);
      const innerHeight = inner.rows.reduce((s, r) => s + r.height, 0);
      const nested: NestedTableInCell = {
        columnWidths: inner.columnWidths,
        rows: inner.rows,
        height: innerHeight,
        blockIndex: pi,
      };
      blocks.push({ kind: 'table', sourceIndex: pi, table: nested });
      flatNested.push(nested);
      contentHeight += innerHeight;
      // 巢狀表格不經 docGrid snap（row 高度已是最終值）→ unsnapped = snapped
      contentHeightUnsnapped += innerHeight;
    }
  }

  const totalHeight = contentHeight + padding.top + padding.bottom;

  const out: CellLayout = {
    cellIndex,
    gridCol: cell.gridCol,
    gridSpan: cell.gridSpan,
    rowSpan: cell.rowSpan,
    isContinuation: false,
    width: cellWidth,
    height: totalHeight,
    lines: flatLines,
    blocks,
    padding,
    vAlign: cell.props.vAlign ?? 'top',
    contentHeight, // Sprint 42：renderCell 依 vAlign 計算 yCursor 起點用
    contentHeightUnsnapped, // Sprint 47：val-as-min 比較基準
  };
  if (flatNested.length > 0) out.nestedTables = flatNested;
  if (cell.props.borders) out.borders = cell.props.borders;
  if (cell.props.shading) out.shading = cell.props.shading;
  if (td) out.textDirection = td;
  if (cellFloats.length > 0) out.floats = cellFloats;
  return out;
}

/**
 * Sprint 37/38：把 ParagraphNode.runs 中的 floatImage / floatTextBox 取出，
 * 回 paragraph copy（runs 已剝掉）+ floats list。
 *
 * 與 Paginator.layParagraph 同樣的 pattern，但 layoutCell 不走 layParagraph
 * 因此需要在 TableLayout 自己 filter 一次。
 */
type AnyFloat = FloatImageNode | FloatTextBoxNode;

function extractFloats(
  block: ParagraphNode,
): { paraWithoutFloats: ParagraphNode; floats: AnyFloat[] } {
  const floats: AnyFloat[] = [];
  const filtered: ParagraphNode['runs'] = [];
  for (const r of block.runs) {
    if (r.type === 'floatImage' || r.type === 'floatTextBox') {
      floats.push(r);
    } else {
      filtered.push(r);
    }
  }
  if (floats.length === 0) return { paraWithoutFloats: block, floats: [] };
  return { paraWithoutFloats: { ...block, runs: filtered }, floats };
}

/**
 * Sprint 37：把 FloatImageNode 解析為 cell-relative xRel / yRel。
 *
 * posH.relativeFrom 處理：
 *   - 'column' / 'margin' / 'page' / undefined：cell 內 column 視為 cell content area
 *     起點 = padding.left；用 posOffset 為相對距離
 *   - 其他 relativeFrom（page / character 等）：簡化為同上（足夠 03 全套管 fixture 用）
 * posV.relativeFrom 處理：
 *   - 'paragraph'：起點 = paraStartYRel（段落上緣）+ posOffset
 *   - 'margin'：起點 = padding.top + posOffset
 *   - 'page'：簡化為同 margin（cell 內 page 絕對位置難算，留 Sprint 38+）
 *
 * align（left/right/center 等）對 cell-internal float 用得很少，先不實作；
 * 03 全套管所有 anchor 都用 posOffset。
 */
function resolveCellFloat(
  node: AnyFloat,
  padding: { top: Pt; bottom: Pt; left: Pt; right: Pt },
  _innerWidth: Pt,
  paraStartYRel: Pt,
): CellFloat {
  const offH = node.posH.posOffset ?? 0;
  const offV = node.posV.posOffset ?? 0;

  // X：column / margin / page → cell content left = padding.left
  const xRel = padding.left + offH;

  // Y：paragraph 用段落上緣；margin / page 用 cell content top = padding.top
  let yRel = padding.top;
  if (node.posV.relativeFrom === 'paragraph' || node.posV.relativeFrom === 'line') {
    yRel = paraStartYRel + offV;
  } else {
    yRel = padding.top + offV;
  }
  // Type-safe union narrowing：根據 node.type 回對應的 CellFloat 變體
  if (node.type === 'floatImage') return { node, xRel, yRel };
  return { node, xRel, yRel };
}

/** 對單一 row 跑 layout，回 RowLayout。 */
export function layoutRow(
  row: RowNode,
  rowIndex: number,
  table: TableNode,
  columnWidths: Pt[],
  options: LayoutOptions = {},
): RowLayout {
  let cells: CellLayout[] = [];
  // Sprint 34：把 row 顯式 trHeight（若有）傳給 layoutCell 作為垂直 cell 的 lineWidth 上限
  const rowHeightHint = row.props.height;
  for (let ci = 0; ci < row.cells.length; ci++) {
    const cell = row.cells[ci];
    const cellWidth = sumWidthsInRange(columnWidths, cell.gridCol, cell.gridSpan);
    cells.push(layoutCell(cell, cellWidth, ci, table, options, rowHeightHint));
  }

  // row height = max(cell heights)，但要忽略 isContinuation cell（它高度為 0）
  // 也要注意 rowSpan > 1 的 cell 不該支配本列高（它跨多列）
  let rowHeight = 0;
  // Sprint 47：同步算「未經 docGrid snap」的 row 高，作為 val-as-min 比較基準。
  let rowHeightUnsnapped = 0;
  for (const c of cells) {
    if (c.isContinuation) continue;
    if (c.rowSpan > 1) continue; // 跨列 cell 由 anchor row 決定基礎高度
    if (c.height > rowHeight) rowHeight = c.height;
    const cUnsnapped = c.contentHeightUnsnapped + c.padding.top + c.padding.bottom;
    if (cUnsnapped > rowHeightUnsnapped) rowHeightUnsnapped = cUnsnapped;
  }
  // 若一整列全是 isContinuation 或 rowSpan > 1，取最低 fallback：fontSize × 1.2
  if (rowHeight === 0) {
    rowHeight = Math.max(row.props.height ?? 0, 14);
  }
  if (rowHeightUnsnapped === 0) rowHeightUnsnapped = rowHeight;
  // OOXML row height 規格 vs Word 實作（ECMA-376 §17.4.81）：
  //   - exact   → row.height = val（強制，忽略內容）
  //   - atLeast → row.height = max(natural, val)
  //   - auto / 未指定 hRule → 規格純看 content
  //
  // Word 實作行為：對於 sparse「表單格式」row（val 顯著大於內容自然高），Word 把 val
  // 當下限渲染——這對 04 / 05 自主檢查表系列 fixture 很關鍵：21 個 cantSplit row 中
  // 約 9 個 row val=1106-1144 twips（55-57pt）、自然內容只 14.4pt（單行），Word 把它們
  // 渲染成 ~57pt 高，總 table 從 19.4in 變 ~24in，section 跨 3 頁。
  //
  // 但對「val 是 Word autosave 快取」的 fixture（如 1121229-全套管 row val ~250pt /
  // natural ~250pt 比例 ~1.07），val 與 natural 接近，套 val-as-min 反而會把 row
  // 略微撐高引發過分頁。
  //
  // Sprint 26 啟發式（**ratio > 3** 才視 val 為下限）：
  //   - 自主檢查表 sparse row：57.2/14.4=3.97 ✓ 套用
  //   - 監造會議記錄 row：67.65/30=2.26 ✗ 不套用（避免退化）
  //   - 1121229-全套管 row：266.8/249.5=1.07 ✗ 不套用
  //   - 監造會議記錄/06-8估驗計價 等 ratio<3 的 fixture 不被影響
  // ratio>3 在直觀上代表「val 是 form 設計高度 vs content 是稀疏」，與「val 是 autosave
  // 快取」明顯區分。固定值會讓 layout 對齊 Word 實際渲染（goldens 的來源）。
  // Sprint 45：判斷 row 是否含 image，作為 omitted/auto hRule 的 val-as-min 二分依據。
  const rowHasImage = cellsContainImage(cells);
  // Sprint 47：val-as-min 是否套用——比較基準改用 rowHeightUnsnapped（未經 docGrid snap），
  // 避免 exact 行被 snap 上推後撐過 trHeight val、卡住判斷（Sprint 46 診斷的監造會議記錄
  // 過分頁真根因：row4 `2×line=400 exact`=40pt 被 snap 成 72pt > val 44.9 → val-as-min
  // 失效）。
  let applyValAsMin = false;
  if (row.props.heightRule === 'exact' && row.props.height) {
    rowHeight = row.props.height;
  } else if (row.props.heightRule === 'atLeast' && row.props.height) {
    rowHeight = Math.max(rowHeight, row.props.height);
  } else if (row.props.height && rowHeightUnsnapped > 0) {
    // omitted / auto hRule：ECMA-376 規格說 auto = content 決定，但 Word 實作對 trHeight
    // val 仍以「下限」渲染。
    //
    // 演進史：
    //   - Sprint 26：用 `val > natural × 3` magic number 防 autosave-cache val 撐高。
    //   - Sprint 45：改「row 是否含 image」二分（無 image → val > natural；含 image →
    //     仍 ratio>3），因當時擔心 03 全套管 image 列 val 是 autosave 快取。
    //   - Sprint 47：val-as-min 比較基準改 rowHeightUnsnapped（未經 docGrid snap）。
    //   - Sprint 48：**移除 image 區分**。Pillow 實測 golden 03 全套管 photo 列同樣
    //     honors trHeight val（row trHeight 266.8/278.45pt，golden 渲染剛好落在 val；
    //     render 用 natural ~226.8pt ≈ 僅照片高度 → 列偏矮 40pt、照片過高無間隔 →
    //     29% VR diff）。Sprint 26 的 autosave-cache 顧慮，在 Sprint 47 naturalUnsnapped
    //     基準下已自然化解——`val > naturalUnsnapped` 只在 val 真的大於內容時才套，
    //     autosave 快取 val ≈ natural 時不觸發。
    if (row.props.height > rowHeightUnsnapped) {
      applyValAsMin = true;
    }
  }
  if (applyValAsMin && row.props.height) {
    // Sprint 47：val 勝出 → row 高度 = val，且 cell 內容改用「未 snap」版重排。
    // 原因：snapped 內容（如 72pt）可能 > val（如 44.9pt），直接設 rowHeight=val 會讓
    // 內容溢出比 row 矮。重排（docGridLinePitch=0）讓 cell 內 line 回到 exact 值
    // （如 2×20pt=40pt < 44.9pt 可容）。
    // 與 Sprint 46 全域 unsnap 翻車的差異：這裡**只重排 val 勝出的 row**，val 不勝出的
    // row（如環清表 row 0 val 17 < natural 32）完全不動 → 環清表主體 snapped 行為不變。
    rowHeight = row.props.height;
    const unsnappedOpts: LayoutOptions = { ...options, docGridLinePitch: 0 };
    cells = [];
    for (let ci = 0; ci < row.cells.length; ci++) {
      const cell = row.cells[ci];
      const cellWidth = sumWidthsInRange(columnWidths, cell.gridCol, cell.gridSpan);
      cells.push(layoutCell(cell, cellWidth, ci, table, unsnappedOpts, rowHeightHint));
    }
  }

  // Sprint 27：cell-level keepNext heuristic（對齊 Word 規則 R6）
  //
  // OOXML w:keepNext 規格 §17.3.1.15：「該段落應與下一段落同頁顯示」。當 keepNext 出現
  // 在 table cell 內的段落上時，Word 實作會把「該 row 視為不可拆」處理（因為 cell 內段
  // 落 keep with next 在 row 內已自動成立；跨 row 則需要把 row 黏在一起，最簡近似 = 不
  // 拆該 row）。
  //
  // Sprint 19 §6 留下的觀察：03_complex_table 06-8估驗計價 ×2 fixture 共 43 個 cell-
  // level keepNext，分布於 12-row 表的 row 2-9。我們 Paginator 在這些 row 上 mid-row
  // break 使整表壓縮在 1 頁；Word 不拆 → 2 頁。Sprint 19 留待 Sprint 25+ 個別擊破。
  //
  // 全 42 fixture 掃過後確認**只有這 2 個 fixture 有 cell-level keepNext**，零退化風險。
  const cantSplitFromKeepNext = !row.props.cantSplit && hasCellKeepNext(cells);

  return {
    rowIndex,
    height: rowHeight,
    isHeader: row.props.isHeader,
    cantSplit: row.props.cantSplit || cantSplitFromKeepNext,
    cells,
    containsImage: rowHasImage,
  };
}

// Sprint 27：偵測 cell 內段落是否含 keepNext，用以把該 row 視為 cantSplit（R6 近似）
function hasCellKeepNext(cells: CellLayout[]): boolean {
  for (const cell of cells) {
    if (cell.isContinuation) continue;
    for (const block of cell.blocks) {
      if (block.kind !== 'lines') continue;
      // CellBlock kind='lines' 對應一個 source paragraph；keepNext 旗標在 paragraphProps
      // 上（透過 LineBreaker 傳遞），檢查 line.paragraphProps.keepNext
      for (const line of block.lines) {
        if (line.paragraphProps?.keepNext === true) return true;
      }
    }
  }
  return false;
}

/**
 * Sprint 17：判斷一組 cells 內是否含 inline image。
 *
 * 走訪 cell.blocks 中 kind='lines' 的 line.items，找 Box.isImage=true 的存在。
 * 巢狀表格遞迴檢查（罕見但保證正確）。Header / continuation cell 也納入計算
 * （cell.isContinuation=true 時 blocks 為空，自然回 false）。
 */
function cellsContainImage(cells: CellLayout[]): boolean {
  for (const cell of cells) {
    if (cellHasImage(cell)) return true;
  }
  return false;
}

function cellHasImage(cell: CellLayout): boolean {
  for (const block of cell.blocks) {
    if (block.kind === 'lines') {
      for (const line of block.lines) {
        for (const item of line.items) {
          if (item.kind === 'box' && item.isImage) return true;
        }
      }
    } else {
      // 巢狀表格：遞迴檢查 row.cells
      for (const row of block.table.rows) {
        if (cellsContainImage(row.cells)) return true;
      }
    }
  }
  return false;
}

/** 對整張表跑 layout，回 RowLayout[]（不切頁）。 Paginator 取結果分頁。 */
export function layoutTable(
  table: TableNode,
  contentWidth: Pt,
  options: LayoutOptions = {},
): { columnWidths: Pt[]; rows: RowLayout[] } {
  const columnWidths = allocateColumnWidths(table, contentWidth);
  const rows: RowLayout[] = [];
  for (let ri = 0; ri < table.rows.length; ri++) {
    rows.push(layoutRow(table.rows[ri], ri, table, columnWidths, options));
  }
  return { columnWidths, rows };
}

/**
 * Sprint 7：把一 row 在 availableHeight 處切成 firstHalf + secondHalf。
 *
 * 切點落在 cell 內 lines 邊界（不切 line 內部，符合 Word 預設行為）。
 * 巢狀表格與 cell 的 lines 一起按高度切，超過 availableHeight 的留 secondHalf。
 *
 * 回 null 表示無法切（cantSplit=true、或所有 cell 一行都塞不下）。
 *
 * 假設：caller 已確保 row.height > availableHeight 且 !row.cantSplit。
 */
export function splitRowAtHeight(
  row: RowLayout,
  availableHeight: Pt,
): { first: RowLayout; second: RowLayout } | null {
  if (row.cantSplit) return null;

  const firstCells: CellLayout[] = [];
  const secondCells: CellLayout[] = [];
  let canSplitAny = false;

  for (const cell of row.cells) {
    if (cell.isContinuation) {
      // vMerge continuation：兩半都保留 placeholder
      firstCells.push(cell);
      secondCells.push(cell);
      continue;
    }

    const innerAvail = availableHeight - cell.padding.top - cell.padding.bottom;
    if (innerAvail <= 0) {
      // 連 padding 都塞不下：first 放空 cell、second 放完整 cell
      firstCells.push(emptyCellLike(cell, true));
      secondCells.push(cell);
      continue;
    }

    // Walk blocks（Sprint 6 的 ordered list）；找最大可放的高度
    const splitResult = splitCellBlocks(cell, innerAvail);
    if (splitResult.firstBlocks.length === 0) {
      // 連第一塊都不能放：first 空、second 完整
      firstCells.push(emptyCellLike(cell, true));
      secondCells.push(cell);
      continue;
    }
    if (splitResult.secondBlocks.length === 0) {
      // 全部塞下：first 完整、second 空
      firstCells.push(cell);
      secondCells.push(emptyCellLike(cell, true));
      continue;
    }
    canSplitAny = true;
    firstCells.push(makeCellFromBlocks(cell, splitResult.firstBlocks));
    secondCells.push(makeCellFromBlocks(cell, splitResult.secondBlocks));
  }

  if (!canSplitAny) return null;

  const firstHeight = computeRowHeight(firstCells, row);
  const secondHeight = computeRowHeight(secondCells, row);

  return {
    first: { ...row, height: firstHeight, cells: firstCells },
    second: {
      ...row,
      height: secondHeight,
      cells: secondCells,
      // 第二半通常不該再被 isHeader 旗標跨頁重複（避免無限重複）
      isHeader: false,
    },
  };
}

/** 切 cell.blocks：算到 limit 為止，剩下的入 second。 */
function splitCellBlocks(
  cell: CellLayout,
  limit: Pt,
): {
  firstBlocks: typeof cell.blocks;
  secondBlocks: typeof cell.blocks;
} {
  const firstBlocks: typeof cell.blocks = [];
  const secondBlocks: typeof cell.blocks = [];
  let cumH = 0;

  for (let bi = 0; bi < cell.blocks.length; bi++) {
    const block = cell.blocks[bi];
    if (block.kind === 'lines') {
      // 嘗試裝整個 paragraph
      if (cumH + block.height <= limit) {
        firstBlocks.push(block);
        cumH += block.height;
        continue;
      }
      // 部分裝：找最大 N lines 可放
      const lines = block.lines;
      let lineCum = 0;
      let cutAt = 0;
      for (let li = 0; li < lines.length; li++) {
        if (cumH + lineCum + lines[li].height > limit) break;
        lineCum += lines[li].height;
        cutAt = li + 1;
      }
      if (cutAt > 0) {
        firstBlocks.push({
          kind: 'lines',
          sourceIndex: block.sourceIndex,
          lines: lines.slice(0, cutAt),
          height: lineCum,
        });
        cumH += lineCum;
      }
      const rest = lines.slice(cutAt);
      if (rest.length > 0) {
        let restH = 0;
        for (const l of rest) restH += l.height;
        secondBlocks.push({
          kind: 'lines',
          sourceIndex: block.sourceIndex,
          lines: rest,
          height: restH,
        });
      }
      // 後續 blocks 全部進 secondBlocks
      for (let j = bi + 1; j < cell.blocks.length; j++) {
        secondBlocks.push(cell.blocks[j]);
      }
      return { firstBlocks, secondBlocks };
    } else {
      // table block：要嘛全進 first，要嘛全進 second（Sprint 7 不切巢狀表）
      if (cumH + block.table.height <= limit) {
        firstBlocks.push(block);
        cumH += block.table.height;
      } else {
        // 後續 blocks 全部進 secondBlocks
        for (let j = bi; j < cell.blocks.length; j++) {
          secondBlocks.push(cell.blocks[j]);
        }
        return { firstBlocks, secondBlocks };
      }
    }
  }
  return { firstBlocks, secondBlocks };
}

/** 從 blocks 重建 CellLayout（lines/nestedTables 平面欄位同步）。 */
function makeCellFromBlocks(base: CellLayout, blocks: CellLayout['blocks']): CellLayout {
  let h = 0;
  const flatLines: import('./types').Line[] = [];
  const flatNested: import('./types').NestedTableInCell[] = [];
  for (const b of blocks) {
    if (b.kind === 'lines') {
      flatLines.push(...b.lines);
      h += b.height;
    } else {
      flatNested.push(b.table);
      h += b.table.height;
    }
  }
  const out: CellLayout = {
    ...base,
    height: h + base.padding.top + base.padding.bottom,
    blocks,
    lines: flatLines,
  };
  if (flatNested.length > 0) {
    out.nestedTables = flatNested;
  } else {
    delete out.nestedTables;
  }
  return out;
}

/** 構造一個與原 cell 同 metadata、但內容為空的 cell（first 半的占位用）。 */
function emptyCellLike(base: CellLayout, asPlaceholder: boolean): CellLayout {
  void asPlaceholder;
  return {
    ...base,
    height: base.padding.top + base.padding.bottom,
    blocks: [],
    lines: [],
    nestedTables: undefined,
  };
}

/**
 * Sprint 18：把 row 在「第一個 cell-internal page break」處切成 firstHalf + secondHalf。
 *
 * 觸發場景：cell 內 paragraph 含 `<w:br w:type="page"/>` → BoxBuilder → Penalty 加上
 * `breakKind='page'` → LineBreaker emit Line.forcedBreakAfter='page'。Paginator 的
 * top-level layParagraph 已正確處理；但 row 內 cell 的 lines 之前完全沒被檢視。
 *
 * 算法：
 *   - 對每個 cell：找第一個 forcedBreakAfter='page' 的 line
 *     - 在該 line 之前（含該 line）的 lines 入 firstBlocks
 *     - 之後的 lines 入 secondBlocks（且後續 blocks 全部到 second）
 *   - 沒有 break 的 cell：整 cell 進 first，second 空 placeholder
 *   - 全部 cell 都沒 break → 回 null（caller 應跳過 split）
 *
 * cantSplit row：依然支援（與 splitRowAtHeight 不同，因為這是「explicit user break」）。
 *
 * 回 null 表示無 break 或無內容。
 */
export function splitRowAtPageBreak(
  row: RowLayout,
): { first: RowLayout; second: RowLayout } | null {
  const firstCells: CellLayout[] = [];
  const secondCells: CellLayout[] = [];
  let foundBreak = false;

  for (const cell of row.cells) {
    if (cell.isContinuation) {
      firstCells.push(cell);
      secondCells.push(cell);
      continue;
    }

    const firstBlocks: typeof cell.blocks = [];
    const secondBlocks: typeof cell.blocks = [];
    let foundInThisCell = false;

    for (let bi = 0; bi < cell.blocks.length; bi++) {
      const block = cell.blocks[bi];
      if (foundInThisCell) {
        secondBlocks.push(block);
        continue;
      }
      if (block.kind === 'lines') {
        let cutAt = -1;
        for (let li = 0; li < block.lines.length; li++) {
          if (block.lines[li].forcedBreakAfter === 'page') {
            cutAt = li + 1;
            break;
          }
        }
        if (cutAt < 0) {
          firstBlocks.push(block);
        } else {
          const firstLines = block.lines.slice(0, cutAt);
          const secondLines = block.lines.slice(cutAt);
          let h1 = 0; for (const l of firstLines) h1 += l.height;
          let h2 = 0; for (const l of secondLines) h2 += l.height;
          firstBlocks.push({
            kind: 'lines',
            sourceIndex: block.sourceIndex,
            lines: firstLines,
            height: h1,
          });
          if (secondLines.length > 0) {
            secondBlocks.push({
              kind: 'lines',
              sourceIndex: block.sourceIndex,
              lines: secondLines,
              height: h2,
            });
          }
          foundInThisCell = true;
          foundBreak = true;
        }
      } else {
        // table block：page break 不可能在巢狀表內被本函式偵測（會由更深層遞迴處理）
        firstBlocks.push(block);
      }
    }

    if (foundInThisCell) {
      firstCells.push(makeCellFromBlocks(cell, firstBlocks));
      secondCells.push(makeCellFromBlocks(cell, secondBlocks));
    } else {
      firstCells.push(cell);
      secondCells.push(emptyCellLike(cell, true));
    }
  }

  if (!foundBreak) return null;

  const firstHeight = computeRowHeight(firstCells, row);
  const secondHeight = computeRowHeight(secondCells, row);

  return {
    first: {
      ...row,
      height: firstHeight,
      cells: firstCells,
      containsImage: cellsContainImage(firstCells),
    },
    second: {
      ...row,
      height: secondHeight,
      cells: secondCells,
      isHeader: false,
      containsImage: cellsContainImage(secondCells),
    },
  };
}

/** 計算 row height = max cell height（忽略 continuation 與 rowSpan>1）。 */
function computeRowHeight(cells: CellLayout[], _baseRow: RowLayout): Pt {
  let h = 0;
  for (const c of cells) {
    if (c.isContinuation) continue;
    if (c.rowSpan > 1) continue;
    if (c.height > h) h = c.height;
  }
  return h > 0 ? h : 1; // 至少 1pt 避免 0 高度誤判
}

// ── helpers ──────────────────────────────────────────────────────────────

function sumWidthsInRange(widths: Pt[], start: number, span: number): Pt {
  let s = 0;
  const end = Math.min(start + span, widths.length);
  for (let i = start; i < end; i++) s += widths[i] ?? 0;
  return s;
}
