/**
 * Sprint 167：`<w:textAlignment>` 行內垂直對齊 → 每 box 的 y 位移
 *
 * 對映 `alignmentShift.ts`（Sprint 32 水平對齊）的垂直版本。
 * ECMA-376 §17.3.1.36 `<w:textAlignment>` 規定一行內不同高度的 run
 * （混排不同字型大小 / 數學符號 / 圖片）如何垂直對齊：
 *
 *   - 'baseline'（預設）：所有 run 共用基線 —— 即引擎 Sprint 0-166 的既有行為
 *   - 'auto'：應用程式自行決定，實務等同 'baseline'
 *   - 'top'：各 run 頂端對齊行內最高 box 的頂端
 *   - 'center'：各 run 垂直中心對齊行內最高 box 的中心
 *   - 'bottom'：各 run 底端對齊行內最高 box 的底端
 *
 * 設計（Strategy C — caller 不觸發 → byte-identical）：
 *   位移量 = f(box.height, maxBoxHeight)，**只與行內 box 高度差有關**。
 *   行內所有 box 等高（maxBoxHeight === box.height）時位移恆為 0 —— 因此
 *   單一字型大小的行（fixture 全數如此）不論標哪種對齊都與 baseline 對齊
 *   逐 pixel 相同。位移只在「真實混合不同高度的 run」時才生效。
 *
 * 參考 box：行內最高的 box（= LineBreaker.makeLine 中 `applySpacingLine` 前的
 * 行高、亦即決定 line.baseline 的 box）。最高 box 位移恆為 0、不被推離基線。
 */

import type { Pt } from '../ooxml/ast/types';

/** 垂直對齊取值（= ParagraphProps.textAlignment）。 */
export type VerticalTextAlignment = 'auto' | 'top' | 'center' | 'baseline' | 'bottom' | undefined;

/**
 * baseline 佔行高的比例 —— 必須與 `LineBreaker.makeLine` 的
 * `baseline = height * 0.8` 一致（純文字行 80% baseline drop）。
 */
const BASELINE_DROP_RATIO = 0.8;

/**
 * 給定垂直對齊模式、單一 box 高度、行內最高 box 高度，
 * 回傳該 box 相對行基線（baseline）需額外位移的 y 量（pt、正值 = 往下）。
 *
 * - baseline / auto / undefined → 0（預設、byte-identical）。
 * - box 等高於行內最高 box → 0（含行內唯一 box、等高行）。
 * - 否則依對齊模式把較矮 box 推離基線、使其頂/中/底對齊最高 box。
 */
export function computeVerticalAlignShift(
  textAlignment: VerticalTextAlignment,
  boxHeight: Pt,
  maxBoxHeight: Pt,
): Pt {
  if (!textAlignment || textAlignment === 'baseline' || textAlignment === 'auto') return 0;
  if (!Number.isFinite(boxHeight) || !Number.isFinite(maxBoxHeight)) return 0;
  // delta ≤ 0：較矮 box 為負、最高 box 為 0。
  const delta = boxHeight - maxBoxHeight;
  if (delta === 0) return 0;
  switch (textAlignment) {
    // 頂端對齊：較矮 box 的頂端（baseline 上方 0.8h）對齊最高 box 頂端 → 往上 0.8·delta。
    case 'top':
      return BASELINE_DROP_RATIO * delta;
    // 底端對齊：較矮 box 的底端（baseline 下方 0.2h）對齊最高 box 底端 → 往下 0.2·(-delta)。
    case 'bottom':
      return -(1 - BASELINE_DROP_RATIO) * delta;
    // 置中：較矮 box 的垂直中心（baseline 上方 0.3h）對齊最高 box 中心 → 0.3·delta。
    case 'center':
      return (BASELINE_DROP_RATIO - 0.5) * delta;
    default:
      return 0;
  }
}
