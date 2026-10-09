/**
 * GridResolver — vMerge 兩 pass 演算法
 *
 * Pass 1（已在 TableParser.materializeRow 完成）：
 *   依 gridSpan 累計 cell.gridCol；vMerge=continue 的格子標記 isContinuation=true。
 *
 * Pass 2（本檔）：
 *   對每個 isContinuation 格子，往上掃同 gridCol 的非 continue 格子（= anchor），
 *   把 anchor.rowSpan 提升為 (continueRow - anchorRow + 1)。
 *
 * 邊界情況：
 *   - 連續 continue：每個 continue 都會獨立更新 anchor.rowSpan，最後 anchor 取得最大值
 *   - 找不到 anchor（孤兒 continue）：忽略，不 throw（OOXML spec：應由 Renderer 把孤兒當 restart）
 *   - 跨 gridSpan 不同的 vMerge 鏈：本演算法用「精確 gridCol 匹配」，
 *     不同 gridSpan 的鏈會被視為獨立鏈（少見且非規格保證情況）
 *   - 列高混合 atLeast/exact/auto：rowSpan 計算與列高無關，僅 Renderer 處理拉伸
 *
 * Renderer 使用 rowSpan + isContinuation：
 *   - rowSpan > 1：anchor 格子需繪製跨多列
 *   - isContinuation = true：跳過繪製內容；若跨頁，第一頁底邊框 omit、第二頁頂邊框 omit
 */

import type { RowNode } from '../ast/types';

export class GridResolver {
  /**
   * 解析 vMerge 鏈，**就地改寫** rows 的 anchor cell 的 rowSpan。
   *
   * @param rows TableParser 產出的 RowNode[]，每個 cell 已有正確的 gridCol / gridSpan / isContinuation
   * @returns 同一份 rows（mutated in place），方便鏈式呼叫
   */
  resolve(rows: RowNode[]): RowNode[] {
    for (let r = 0; r < rows.length; r++) {
      for (const cell of rows[r].cells) {
        if (!cell.isContinuation) continue;

        // 往上找 anchor：同 gridCol 的第一個非 continue cell
        for (let rUp = r - 1; rUp >= 0; rUp--) {
          const anchor = rows[rUp].cells.find((c) => c.gridCol === cell.gridCol);
          if (!anchor) {
            // 此列沒有對齊 gridCol 的 cell — 跳過繼續往上
            continue;
          }
          if (anchor.isContinuation) {
            // 此 cell 也是 continue — 屬同一鏈，繼續往上找真正的 anchor
            continue;
          }
          // 找到 anchor → 提升 rowSpan
          const span = r - rUp + 1;
          if (span > anchor.rowSpan) {
            anchor.rowSpan = span;
          }
          break;
        }
        // 找不到 anchor 時靜默忽略（孤兒 continue）
      }
    }
    return rows;
  }
}
