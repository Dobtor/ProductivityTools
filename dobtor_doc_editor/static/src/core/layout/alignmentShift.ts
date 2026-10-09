/**
 * Sprint 32：paragraph alignment → x 起點偏移
 *
 * 既有設計只在 LineBreaker 套用 `line.xOffset`（wrapSquare 推右），
 * 但 `line.alignment === 'center' | 'right'` 不會反映到 x 起點。
 * 這導致 04_with_image 系列「標題應置中卻靠左、圖片應置中卻貼齊 cell 左邊」。
 *
 * 偏移規則：
 *   center  → (lineWidth - line.width) / 2
 *   right   → lineWidth - line.width
 *   left / justify / distribute / undefined → 0
 *
 * 安全網：content > available 時回傳 0，避免把內容推到負座標（image overflow cell 時）。
 */

import type { Pt } from '../ooxml/ast/types';

export type LineAlignment =
  | 'left'
  | 'center'
  | 'right'
  | 'justify'
  | 'distribute'
  | undefined;

export function computeAlignmentShift(
  alignment: LineAlignment,
  contentWidth: Pt,
  availableWidth: Pt,
): Pt {
  if (!alignment) return 0;
  if (contentWidth >= availableWidth) return 0;
  if (alignment === 'center') return (availableWidth - contentWidth) / 2;
  if (alignment === 'right') return availableWidth - contentWidth;
  return 0;
}
