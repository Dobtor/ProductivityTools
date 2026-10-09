/**
 * Sprint 169：`<w:framePr>` 浮動段落框 —— 框段落偵測與分組（純函式）
 *
 * ECMA-376 §17.3.1.11：連續且 framePr 完全相同的段落由 Word 合併為**單一 frame**。
 * 本模組提供 Paginator 在 body block 走訪時辨識框段落、把連續同 framePr 段落歸為
 * 一組所需的純判別函式。layout / 定位由 Paginator.layFramedParagraphs 負責。
 *
 * 對映 Sprint 167 `verticalAlignShift.ts`、Sprint 161 `resolveTabStops` —— 把可獨立
 * 測試的判別邏輯抽成純函式、與 Paginator 的有狀態流程分離。
 */

import type { ParagraphNode, ParagraphProps } from '../ooxml/ast/types';
import type { SectionNode } from '../ooxml/ast/types';

type FramePr = NonNullable<ParagraphProps['framePr']>;
type Block = SectionNode['body'][number];

/** framePr 結構相等比較用的欄位清單（= ParagraphProps.framePr 全欄位）。 */
const FRAME_PR_KEYS: ReadonlyArray<keyof FramePr> = [
  'width', 'height', 'hRule', 'hSpace', 'vSpace', 'wrap',
  'hAnchor', 'vAnchor', 'xAlign', 'yAlign', 'x', 'y',
];

/** block 是否為帶 `framePr` 的段落（type narrowing 至 ParagraphNode）。 */
export function isFramedParagraph(block: Block): block is ParagraphNode {
  return block.type === 'paragraph' && block.props.framePr !== undefined;
}

/**
 * 兩個 framePr 是否結構相等 —— 用於判斷相鄰框段落是否屬同一 frame。
 * 兩者皆 undefined 視為相等；單邊 undefined 視為不等。
 */
export function framePrEqual(a: FramePr | undefined, b: FramePr | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return FRAME_PR_KEYS.every((k) => a[k] === b[k]);
}

/**
 * 從 body 的 `startIdx` 起算、回傳連續且 framePr 相等的框段落數量（≥ 1）。
 * `startIdx` 必須已是框段落（呼叫端先以 isFramedParagraph 確認）；否則回傳 0。
 */
export function frameGroupLength(body: ReadonlyArray<Block>, startIdx: number): number {
  const first = body[startIdx];
  if (!first || !isFramedParagraph(first)) return 0;
  const firstFrame = first.props.framePr;
  let n = 1;
  for (let i = startIdx + 1; i < body.length; i++) {
    const b = body[i];
    if (!isFramedParagraph(b) || !framePrEqual(b.props.framePr, firstFrame)) break;
    n++;
  }
  return n;
}
