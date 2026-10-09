/**
 * TableStyleApplicator — 套用 w:tblStyle 與 w:tblStylePr 條件樣式到 TableNode（Phase 4.2）
 *
 * 流程：
 *   1. base = styleEntry.pProps + rProps（基底樣式，從 wholeTable conditional 補強）
 *   2. 對每一 row 判斷其位置（firstRow / lastRow / 偶/奇 band）
 *   3. 對每一 cell 判斷其位置（firstCol / lastCol / 偶/奇 band / corner）
 *   4. 依 ECMA-376 §17.7.6 套用順序合併條件樣式
 *   5. 最終 effective props 寫回 cell.content 內每段 paragraph + run（explicit 屬性優先）
 *
 * 套用順序（後者覆蓋前者，但 explicit 永遠最優先）：
 *   1. wholeTable
 *   2. band1Horz / band2Horz（依 row band index）
 *   3. band1Vert / band2Vert（依 col band index）
 *   4. firstRow / lastRow（若 tblLook 啟用）
 *   5. firstCol / lastCol（若 tblLook 啟用）
 *   6. nwCell / neCell / swCell / seCell（角落，僅 firstRow×firstCol 等同時啟用）
 *   7. cell-level explicit pPr/rPr（para.props / run.props 已有值）→ 覆蓋上述
 *
 * 設計決策：
 *   - **mutation**：直接修改 cell.content 的 paragraph.props 與 run.props
 *     避免在 AST 加 effectiveProps 欄位讓 mapper / renderer 多一層查詢
 *   - **explicit wins**：para.props / run.props 已有值的 key 不被覆寫，符合 Word 行為
 *   - **isContinuation 跳過**：vMerge 連續 cell 不渲染，無需套用
 */

import type {
  TableNode,
  StyleEntry,
  ParagraphProps,
  RunProps,
  TableConditionalType,
  TableConditionalCellProps,
  CellNode,
} from '../ast/types';

/** w:tblLook 解析後的旗標 */
export interface TblLook {
  /** w:firstRow="1" — 啟用 firstRow conditional + 角 nwCell/neCell */
  firstRow: boolean;
  /** w:lastRow="1" — 啟用 lastRow conditional + 角 swCell/seCell */
  lastRow: boolean;
  /** w:firstColumn="1" — 啟用 firstCol conditional + 角 nwCell/swCell */
  firstColumn: boolean;
  /** w:lastColumn="1" — 啟用 lastColumn conditional + 角 neCell/seCell */
  lastColumn: boolean;
  /** w:noHBand="1" — 停用橫向 band1Horz/band2Horz */
  noHBand: boolean;
  /** w:noVBand="1" — 停用縱向 band1Vert/band2Vert */
  noVBand: boolean;
}

/**
 * Word 預設 tblLook（規格 §17.7.6.16 default 值）：
 *   firstRow=1, firstColumn=1, noVBand=1（即啟用首列首欄、停用縱向 banding）
 */
export const DEFAULT_TBL_LOOK: TblLook = {
  firstRow: true,
  lastRow: false,
  firstColumn: true,
  lastColumn: false,
  noHBand: false,
  noVBand: true,
};

/**
 * 解析 w:tblLook val hex（如 "04A0" / "0420"）為旗標。
 *
 * Hex bit 對應（ECMA-376 §17.7.6.16）：
 *   0x0020 = firstRow
 *   0x0040 = lastRow
 *   0x0080 = firstColumn
 *   0x0100 = lastColumn
 *   0x0200 = noHBand
 *   0x0400 = noVBand
 *
 * 缺值 / 無效時回 DEFAULT_TBL_LOOK。
 */
export function parseTblLook(hex: string | undefined): TblLook {
  if (!hex) return { ...DEFAULT_TBL_LOOK };
  const v = parseInt(hex, 16);
  if (Number.isNaN(v)) return { ...DEFAULT_TBL_LOOK };
  return {
    firstRow: !!(v & 0x0020),
    lastRow: !!(v & 0x0040),
    firstColumn: !!(v & 0x0080),
    lastColumn: !!(v & 0x0100),
    noHBand: !!(v & 0x0200),
    noVBand: !!(v & 0x0400),
  };
}

/**
 * 套用 tblStyle 與 tblStylePr 條件樣式到 TableNode。
 *
 * 副作用：mutates table.rows[*].cells[*].content[*].props 與 .runs[*].props
 *
 * @param table       要套用的 TableNode（將被 mutation）
 * @param styleEntry  StyleResolver 已 flatten 的 style entry（含 conditional Map）
 * @param tblLook     w:tblLook 解析結果（控制哪些 conditional types 會被套用）
 */
export function applyTableStyle(
  table: TableNode,
  styleEntry: StyleEntry,
  tblLook: TblLook,
): void {
  const baseP = styleEntry.pProps;
  const baseR = styleEntry.rProps;
  const cond = styleEntry.conditional;

  const totalRows = table.rows.length;
  const totalCols = table.grid.length;

  for (let r = 0; r < totalRows; r++) {
    const row = table.rows[r];
    const isFirstRow = r === 0 || row.props.isHeader;
    const isLastRow = r === totalRows - 1;
    const horzBand = computeHorzBand(r, totalRows, tblLook);

    for (const cell of row.cells) {
      if (cell.isContinuation) continue;

      const isFirstCol = cell.gridCol === 0;
      const cellLastGrid = cell.gridCol + cell.gridSpan - 1;
      const isLastCol = cellLastGrid === totalCols - 1;
      const vertBand = computeVertBand(cell.gridCol, totalCols, tblLook);

      let effP: ParagraphProps = baseP ? { ...baseP } : {};
      let effR: RunProps = baseR ? { ...baseR } : {};
      // Sprint 131：累積條件樣式的 cell-level props（shading + vAlign）
      let effC: TableConditionalCellProps = {};

      // 1. wholeTable
      const ct = (k: TableConditionalType) => cond?.get(k);
      const apply = (
        entry:
          | { pProps?: ParagraphProps; rProps?: RunProps; cProps?: TableConditionalCellProps }
          | undefined,
      ) => {
        if (!entry) return;
        effP = mergeProps(effP, entry.pProps);
        effR = mergeProps(effR, entry.rProps);
        if (entry.cProps) effC = mergeCellConditionalProps(effC, entry.cProps);
      };

      apply(ct('wholeTable'));

      // 2. Horizontal banding
      if (horzBand === 1) apply(ct('band1Horz'));
      else if (horzBand === 2) apply(ct('band2Horz'));

      // 3. Vertical banding
      if (vertBand === 1) apply(ct('band1Vert'));
      else if (vertBand === 2) apply(ct('band2Vert'));

      // 4. First / Last row（受 tblLook 開關）
      if (isFirstRow && tblLook.firstRow) apply(ct('firstRow'));
      if (isLastRow && tblLook.lastRow) apply(ct('lastRow'));

      // 5. First / Last column（受 tblLook 開關）
      if (isFirstCol && tblLook.firstColumn) apply(ct('firstCol'));
      if (isLastCol && tblLook.lastColumn) apply(ct('lastCol'));

      // 6. Corner cells（最高優先級，僅相關 row/col 旗標都啟用時）
      if (isFirstRow && isFirstCol && tblLook.firstRow && tblLook.firstColumn) {
        apply(ct('nwCell'));
      }
      if (isFirstRow && isLastCol && tblLook.firstRow && tblLook.lastColumn) {
        apply(ct('neCell'));
      }
      if (isLastRow && isFirstCol && tblLook.lastRow && tblLook.firstColumn) {
        apply(ct('swCell'));
      }
      if (isLastRow && isLastCol && tblLook.lastRow && tblLook.lastColumn) {
        apply(ct('seCell'));
      }

      // 7a. Sprint 131 + 284：把 effective cell-level conditional props 寫回 cell.props
      //     explicit cell.props（TableParser 已 set）優先；空欄位才補入 conditional
      //     Sprint 284 加入 borders（per-side 補入）
      if (effC.shading || effC.vAlign || effC.borders) {
        applyConditionalCellProps(cell, effC);
      }

      // 7. 把 effective props 寫回 cell 內每段段落 + run（explicit 永遠優先）
      // Sprint 7：cell.content 內 TableNode 也遞迴套用同一 styleEntry + tblLook
      // （巢狀表格繼承外層樣式；若巢狀表本身有 styleId，由 TableParser 階段已 apply 自己的樣式）
      for (const block of cell.content) {
        if (block.type === 'paragraph') {
          block.props = mergeProps(effP, block.props);
          for (const node of block.runs) {
            if (node.type === 'run') {
              node.props = mergeProps(effR, node.props);
            }
          }
        } else if (block.type === 'table') {
          // 遞迴套用：用外層 effective props 為 base，避免巢狀表完全遺失外層樣式
          // 若巢狀表已有自己的 styleId（TableParser 應已 apply 過），不重套
          if (!block.styleId) {
            applyTableStyle(
              block,
              { pProps: effP, rProps: effR } as StyleEntry,
              DEFAULT_TBL_LOOK,
            );
          }
        }
      }
    }
  }
}

/**
 * 計算 row 的 horizontal band index：
 *   - 1 = odd band（套用 band1Horz）
 *   - 2 = even band（套用 band2Horz）
 *   - 0 = no band（跳過所有 banding）
 *
 * 規則：
 *   - tblLook.noHBand → 0（不套）
 *   - 第一列 / 最後一列被 firstRow/lastRow 處理時，banding 跳過
 *   - 其餘 row 從 1 開始計算 band（odd=1, even=2）
 */
function computeHorzBand(rowIndex: number, totalRows: number, tblLook: TblLook): 0 | 1 | 2 {
  if (tblLook.noHBand) return 0;
  const isFirst = rowIndex === 0;
  const isLast = rowIndex === totalRows - 1;
  if (tblLook.firstRow && isFirst) return 0;
  if (tblLook.lastRow && isLast) return 0;
  // 從 firstRow 之後開始算 band，第一個非 firstRow 的列為 band1
  let bandIdx = rowIndex;
  if (tblLook.firstRow) bandIdx -= 1;
  return bandIdx % 2 === 0 ? 1 : 2;
}

function computeVertBand(gridCol: number, totalCols: number, tblLook: TblLook): 0 | 1 | 2 {
  if (tblLook.noVBand) return 0;
  const isFirst = gridCol === 0;
  const isLast = gridCol === totalCols - 1;
  if (tblLook.firstColumn && isFirst) return 0;
  if (tblLook.lastColumn && isLast) return 0;
  let bandIdx = gridCol;
  if (tblLook.firstColumn) bandIdx -= 1;
  return bandIdx % 2 === 0 ? 1 : 2;
}

/**
 * Sprint 131：合併 cell-level conditional props（後者覆蓋前者、shading 巢狀深合併）。
 *
 * shading 物件做 per-key 淺合併（fill/color/pattern 各自獨立覆蓋）；
 * vAlign 是 atomic 整體覆蓋。
 */
function mergeCellConditionalProps(
  base: TableConditionalCellProps,
  overlay: TableConditionalCellProps,
): TableConditionalCellProps {
  const out: TableConditionalCellProps = { ...base };
  if (overlay.shading) {
    out.shading = { ...(base.shading ?? {}), ...overlay.shading };
  }
  if (overlay.vAlign !== undefined) {
    out.vAlign = overlay.vAlign;
  }
  // Sprint 284：borders per-side 合併（top/bottom/left/right/insideH/insideV 各自獨立）
  if (overlay.borders) {
    out.borders = { ...(base.borders ?? {}), ...overlay.borders };
  }
  return out;
}

/**
 * Sprint 131：把 effective conditional cell props 寫回 cell.props，explicit 優先。
 *
 * 規則（與 paragraph/run props 一致）：
 *   - cell.props.shading 已有值 → 條件樣式整體放棄（atomic、避免半填半空）
 *     注意：TableParser 即使遇到 `<w:shd w:val="clear"/>`（無 fill/color）也會
 *     設置 shading={}（pattern only），這時 conditional 會被「卡掉」。
 *     現實中這種空 shading 罕見；shading=undefined 才是常態 fall-through。
 *   - cell.props.vAlign 已有值 → 條件樣式放棄；否則套用
 */
function applyConditionalCellProps(
  cell: CellNode,
  effC: TableConditionalCellProps,
): void {
  if (effC.shading && cell.props.shading === undefined) {
    cell.props.shading = { ...effC.shading };
  }
  if (effC.vAlign !== undefined && cell.props.vAlign === undefined) {
    cell.props.vAlign = effC.vAlign;
  }
  // Sprint 284：borders per-side 寫回（explicit cell border 已存在的 side 不覆蓋）
  if (effC.borders) {
    if (cell.props.borders === undefined) cell.props.borders = {};
    const target = cell.props.borders;
    for (const side of ['top', 'bottom', 'left', 'right', 'insideH', 'insideV'] as const) {
      if (effC.borders[side] && target[side] === undefined) {
        target[side] = { ...effC.borders[side] };
      }
    }
    // 若全沒填（explicit 已佔滿）且原本沒 borders、不留空 object
    if (Object.keys(target).length === 0) {
      delete cell.props.borders;
    }
  }
}

/**
 * 合併兩個 props 物件：overlay 覆蓋 base；undefined keys 不影響。
 *
 * 注意：only shallow merge — 巢狀物件（如 indent.left）若 overlay 有 indent，
 * 整個 indent 會被覆蓋。Phase 4.2 不處理巢狀深層合併（StyleResolver 已對
 * docDefaults → basedOn 做完逐 key 巢狀合併；conditional 階段視為 atomic）。
 */
function mergeProps<T extends object>(
  base: T | undefined,
  overlay: T | undefined,
): T {
  if (!overlay) return base ? { ...base } : ({} as T);
  if (!base) return { ...overlay };
  return { ...base, ...overlay };
}
