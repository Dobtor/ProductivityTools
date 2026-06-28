/**
 * 對齊輔助線視覺渲染 — Sprint 295。
 *
 * 把 Sprint 291 `overlay_geometry.ts` 的 `AlignGuide` 計算結果轉成「可渲染」的
 * 樣式資料（純資料、無 DOM 依賴），caller 可在 OWL / React / vanilla HTML 內
 * 用對應方式繪製。
 *
 * 紀律 #18 scope-down：本 sprint 純 utility extraction + tests；不接 doc_editor.js
 *   OWL Component（避免破 13 Playwright E2E、紀律 #21 不污染既有 UI 行為）。
 *   未來 polish sprint 才 wire 進 doc_editor.js（opt-in feature flag）。
 *
 * 紀律 #21：純資料 transformation、無 side effect、不入 VR pipeline。
 */

import type { AlignGuide, Bounds } from './overlay_geometry';

/**
 * 一條輔助線的渲染樣式資料。
 *
 * caller 可直接 spread 為 inline `style` 屬性，或映射為 className：
 *
 * ```tsx
 * <div
 *   style={{ position: 'absolute', left: s.left, top: s.top, width: s.width, height: s.height }}
 *   className={`align-guide ${s.className}`}
 * />
 * ```
 */
export interface GuideStyle {
  /** 來源 guide.axis */
  axis: 'x' | 'y';
  /** absolute position 起點 X（pt 或 px、與 caller bounds 同單位） */
  left: number;
  /** absolute position 起點 Y */
  top: number;
  /** 輔助線寬度（X 軸 guide = lineThickness、Y 軸 = bounds.width） */
  width: number;
  /** 輔助線高度（X 軸 guide = bounds.height、Y 軸 = lineThickness） */
  height: number;
  /** className 提示（caller 用於 CSS 著色：reason-page / reason-sibling） */
  className: string;
  /** 命中該 guide 的 sibling rect 索引；page guide 為 undefined */
  siblingIndex?: number;
}

export interface BuildGuideStylesOptions {
  /** 線條粗細，預設 1 */
  lineThickness?: number;
  /** page 對齊（page-edge / page-center）給的 className 前綴；預設 'guide-page' */
  pageClassName?: string;
  /** sibling 對齊給的 className 前綴；預設 'guide-sibling' */
  siblingClassName?: string;
}

/**
 * 把多條 AlignGuide 轉成可渲染樣式陣列。
 *
 * - X 軸 guide → 垂直線：寬度 = lineThickness、高度 = pageBounds.height
 * - Y 軸 guide → 水平線：寬度 = pageBounds.width、高度 = lineThickness
 * - **去重**：相同 axis + 相同 value 視為同一條（reason 不同也合併、避免重畫）
 * - className 區分 page guide 與 sibling guide（caller 可用不同顏色）
 *
 * 不對 guides 做任何 threshold / snap 篩選（那是 `computeAlignGuides` 的職責）；
 * 本函式只負責「拿到的 guides 全部視覺化」。
 */
export function buildGuideStyles(
  guides: readonly AlignGuide[],
  pageBounds: Bounds,
  opts: BuildGuideStylesOptions = {},
): GuideStyle[] {
  const lineThickness = opts.lineThickness ?? 1;
  const pageClass = opts.pageClassName ?? 'guide-page';
  const siblingClass = opts.siblingClassName ?? 'guide-sibling';

  const seen = new Set<string>();
  const out: GuideStyle[] = [];
  for (const g of guides) {
    const key = `${g.axis}:${g.value}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const isPageReason = g.reason.startsWith('page-');
    const className = isPageReason ? pageClass : siblingClass;
    if (g.axis === 'x') {
      out.push({
        axis: 'x',
        left: g.value,
        top: 0,
        width: lineThickness,
        height: pageBounds.height,
        className,
        siblingIndex: g.siblingIndex,
      });
    } else {
      out.push({
        axis: 'y',
        left: 0,
        top: g.value,
        width: pageBounds.width,
        height: lineThickness,
        className,
        siblingIndex: g.siblingIndex,
      });
    }
  }
  return out;
}

/**
 * 計算 snap 後 moving rect 的最終位置（套用 pickSnapTargets 的結果）。
 *
 * 給 caller 在 drag mousemove 時 inline 用：
 * ```typescript
 * const guides = computeAlignGuides(moving, siblings, page, 5);
 * const { snapX, snapY } = pickSnapTargets(moving, guides);
 * const snapped = applySnapToRect(moving, snapX, snapY);
 * setRectPosition(snapped.x, snapped.y);
 * ```
 *
 * snapX / snapY 為 undefined 時對應軸不變。
 */
export function applySnapToRect(
  rect: { x: number; y: number },
  snapX?: AlignGuide,
  snapY?: AlignGuide,
): { x: number; y: number } {
  return {
    x: snapX?.axis === 'x' ? snapX.value : rect.x,
    y: snapY?.axis === 'y' ? snapY.value : rect.y,
  };
}
