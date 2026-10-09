/**
 * numberingCounter — 文件走訪時維護「numId × ilvl」清單編號計數器
 *
 * 純函式狀態機（無 side effect 對外、內部 Map 為 state holder）。
 *
 * 用途：
 *   走訪 DocumentNode.sections 時、對每個 paragraph 若帶 numId、
 *   呼叫 `state.advance(numId, ilvl, abstractNumbering)` 取得當前序號字串
 *   與展開後的 counter 序列（給 indent / pPr 套用）。
 *
 * OOXML 規則（ECMA-376 Part 1 §17.9）：
 *   - 每個 numId 維護 levels[ilvl] 0–8 的獨立計數器
 *   - 首次出現某 ilvl：counter = levels[ilvl].start
 *   - 再次出現同 ilvl 同 numId：counter += 1
 *   - 跳到較淺層（ilvl 變小）：保留淺層 counter、reset 所有「深層 ilvl > current」counters
 *     → 下次再出現深層 ilvl 時重新從 start 起算
 *   - `lvlRestart` 屬性：levels[X].lvlRestart = N 表示「遇到 ilvl < N 的段落時、ilvl X 重啟」
 *     - 預設行為 = lvlRestart 等於 ilvl（深層遇淺層自動 reset）
 *     - 顯式 lvlRestart = 0 表示「永不重啟」（編號跨章節連續）
 *
 * 不負責：
 *   - lvlText 模板展開（由 numberingFormatter.expandLvlText 處理）
 *   - bullet 字元產生（bullet numFmt 由 lvlText 直接給字元）
 *   - 縮排計算（由 caller 從 levels[ilvl].indent 取）
 *
 * 紀律 #21（optional 空集合不掛 key）：返回 counters 陣列只含 0..ilvl（不掛深層 undefined）
 */

import type { AbstractNumbering, NumberingLevel } from '../ast/types';

export interface AdvanceResult {
  /** 各 level 當前計數值，counters[i] = ilvl i 的計數（i 在 0..ilvl 範圍內）*/
  counters: number[];
  /** 各 level 的 numFmt（與 counters 同長），供 expandLvlText 使用 */
  numFmts: string[];
  /** 此 ilvl 對應的 NumberingLevel 物件（給 caller 取 lvlText / indent / runProps）*/
  level: NumberingLevel;
}

/**
 * 清單編號計數器狀態 holder。
 *
 * 每個 numId 維護 levels[ilvl] 0–8 的計數值 + 首次出現旗標（用於判定是否套 start）。
 * 跨 numId 的 counter 互相獨立（OOXML 規範）。
 *
 * Lifecycle：
 *   const counter = new NumberingCounterState();
 *   for each paragraph with numId:
 *     const result = counter.advance(numId, ilvl, abstractNum);
 *     // result.counters → expandLvlText(level.text, result.counters, result.numFmts)
 */
export class NumberingCounterState {
  /** numId → counters[ilvl]（-1 = 未初始化、0+ = 已 set 過 counter）*/
  private state = new Map<number, number[]>();

  /**
   * 推進一個 numbered paragraph 的計數器、回傳當前序號狀態。
   *
   * @param numId             paragraph.props.numId
   * @param ilvl              paragraph.props.ilvl（預設 0）
   * @param abstractNumbering NumberingMap.get(numId)；undefined 視為空清單 placeholder
   * @returns                 AdvanceResult；abstractNumbering 缺 ilvl 對應 level 時、
   *                          回傳 placeholder level (numFmt='decimal', text='%1.', start=1)
   */
  advance(
    numId: number,
    ilvl: number,
    abstractNumbering: AbstractNumbering | undefined,
  ): AdvanceResult {
    // 取得或初始化此 numId 的 counters 陣列
    let counters = this.state.get(numId);
    if (!counters) {
      counters = new Array(9).fill(-1); // -1 = 未初始化
      this.state.set(numId, counters);
    }

    // 取得 level 定義（缺失時用 placeholder、不污染 state）
    const level = findLevel(abstractNumbering, ilvl) ?? placeholderLevel(ilvl);

    // 計算 lvlRestart 規則：
    //   - 顯式 lvlRestart = 0 → 永不 reset 深層
    //   - 顯式 lvlRestart = N → 遇 ilvl < N 時 reset 此 level
    //   - 未指定 → 預設行為（深層遇淺層 reset、由本演算法的「reset 深層」step 處理）
    //
    // 本實作的 reset 是「advance 此 ilvl 時、reset 所有 ilvl' > ilvl 的 counter」。
    // 對應 OOXML 預設「深層遇淺層 reset」(lvlRestart undefined 等同於 lvlRestart = ilvl + 1)。
    // 顯式 lvlRestart=0 不影響本 step；要影響「淺層遇深層 reset 自己」需 caller 另查
    // levels[X].lvlRestart 並決定 — 本實作不主動套（避免複雜耦合、留給未來 sprint）。

    // 推進此 ilvl 的 counter
    if (counters[ilvl] < 0) {
      // 首次出現：用 start
      counters[ilvl] = level.start;
    } else {
      // 已出現過：+1
      counters[ilvl] += 1;
    }

    // Reset 所有「ilvl' > ilvl」的深層 counter（下次再出現重新從 start 起算）
    // 例外：顯式 lvlRestart = 0 的 level 不 reset（連續編號跨章節）
    for (let i = ilvl + 1; i < counters.length; i++) {
      if (counters[i] < 0) continue; // 從未出現過、無需 reset
      const deeperLevel = findLevel(abstractNumbering, i);
      if (deeperLevel && deeperLevel.lvlRestart === 0) continue;
      counters[i] = -1;
    }

    // 組裝 counters 結果（只取 0..ilvl、紀律 #21 空集合不掛 key）
    const resultCounters: number[] = [];
    const resultNumFmts: string[] = [];
    for (let i = 0; i <= ilvl; i++) {
      // 較淺層若從未出現過（如直接從 ilvl=2 開始）、視為 start - 1 + 1 = start
      // 不主動 advance 較淺層（OOXML 規範：淺層只在自己被 advance 時才 +1）
      if (counters[i] < 0) {
        const shallow = findLevel(abstractNumbering, i);
        // 用 start 當顯示值（不寫入 state、避免影響後續真正 advance）
        resultCounters.push(shallow?.start ?? 1);
        resultNumFmts.push(shallow?.numFmt ?? 'decimal');
      } else {
        resultCounters.push(counters[i]);
        const shallow = findLevel(abstractNumbering, i);
        resultNumFmts.push(shallow?.numFmt ?? 'decimal');
      }
    }

    return { counters: resultCounters, numFmts: resultNumFmts, level };
  }

  /**
   * 完整重置所有 numId 的計數器（如：開始解析新文件時）。
   */
  reset(): void {
    this.state.clear();
  }

  /**
   * 重置單一 numId 的計數器（如：遇到 sectPr 強制重啟章節）。
   *
   * @param numId 要重置的 numId；未存在時 no-op
   */
  resetNum(numId: number): void {
    this.state.delete(numId);
  }

  /**
   * （debug / test 用）取得目前 state snapshot。
   *
   * 回傳的 Map 是 deep copy、修改不影響內部 state。
   */
  snapshot(): Map<number, number[]> {
    const out = new Map<number, number[]>();
    for (const [k, v] of this.state) {
      out.set(k, [...v]);
    }
    return out;
  }
}

// ── 內部 helper ──────────────────────────────────────────────────────────────

function findLevel(
  abstractNumbering: AbstractNumbering | undefined,
  ilvl: number,
): NumberingLevel | undefined {
  if (!abstractNumbering) return undefined;
  // levels 陣列已由 NumberingResolver 按 ilvl 排序、但允許稀疏（缺中間層）
  return abstractNumbering.levels.find((l) => l.ilvl === ilvl);
}

function placeholderLevel(ilvl: number): NumberingLevel {
  // 缺失 level 的 placeholder：標準 decimal "%1." 編號（不 crash 下游）
  return { ilvl, numFmt: 'decimal', text: '%1.', start: 1 };
}
