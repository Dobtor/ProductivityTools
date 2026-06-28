/**
 * WrapPolygonPaginator helpers — Sprint 309。
 *
 * Sprint 296 / 298 / 304 polygon math + LineBreaker + render；本 sprint 補
 * **跨頁時** polygon 與 paginator 的對位邏輯。
 *
 * 場景：當段落跨頁、且段落內含浮動 image with wrapPolygon：
 *   - polygon 的 Y 範圍 = imageRect.y + polygon.maxY（絕對座標）
 *   - paginator 第 1 頁繪到 pageBottom、第 2 頁從 pageTop 繪
 *   - polygon 跨頁時必須裁成「第 1 頁部分」+「第 2 頁部分」、各頁套各自 polygon clip
 *   - 同一個 polygon 但 imageRect 的 y 在第 2 頁需相對 pageOffset 重新計算
 *
 * 範圍（Strategy A）：
 *   - `splitPolygonAcrossPages`：給 polygon + pageBoundsY list、回每頁子 polygon
 *     （只裁 polygon 的 Y range；X 不變、本 PROBE 不裁 X、不做 column 分割）
 *   - `shiftPolygonForPage`：把絕對座標 polygon 平移到「頁 local 座標」
 *
 * 紀律 #18 scope-down：
 *   - 不接 Paginator real path（紀律 #21、避免破現有 page 切分行為）
 *   - 只裁 Y range（多欄場景、X 跨 column 切分留 future）
 *   - 不處理「polygon 與 page footer 重疊」（caller 自負）
 */

import type { WrapPolygonPoint } from '../ast/types';

export interface PageYRange {
  /** 該頁起始 Y（絕對座標、第 1 頁 = 0） */
  startY: number;
  /** 該頁結束 Y（排版可用區、不含 footer margin） */
  endY: number;
}

/**
 * 取 polygon + 多頁 Y 範圍 → 每頁子 polygon。
 *
 * 演算法（Sutherland–Hodgman 簡化、只切 Y）：
 *   - 對 polygon 每條邊：若兩端都在頁面 Y 範圍內 → 整條保留
 *   - 若兩端都在外 → 整條捨棄
 *   - 若一進一出 → 算交點、輸出進入點 + 邊頭 / 邊尾
 *
 * 對每個 pageRange 跑一遍、產出 polygons[pageIndex]。
 * 若該頁與 polygon 完全不重疊 → polygons[pageIndex] = []。
 */
export function splitPolygonAcrossPages(
  polygon: readonly WrapPolygonPoint[],
  pages: readonly PageYRange[],
): WrapPolygonPoint[][] {
  return pages.map((page) => clipPolygonToYRange(polygon, page.startY, page.endY));
}

/**
 * Sutherland–Hodgman Y-axis clip：取 polygon、回裁進 [yMin, yMax] 範圍的子 polygon。
 *
 * - polygon 完全在範圍外 → []
 * - polygon 完全在範圍內 → 原 polygon copy
 * - 部分跨界 → 算交點、回新 polygon
 */
export function clipPolygonToYRange(
  polygon: readonly WrapPolygonPoint[],
  yMin: number,
  yMax: number,
): WrapPolygonPoint[] {
  if (polygon.length === 0) return [];
  // 先依 yMin 裁（保留 y >= yMin）
  let result = clipHalfPlane(polygon, (p) => p.y >= yMin, (a, b) => {
    const t = (yMin - a.y) / (b.y - a.y);
    return { x: a.x + (b.x - a.x) * t, y: yMin };
  });
  if (result.length === 0) return [];
  // 再依 yMax 裁（保留 y <= yMax）
  result = clipHalfPlane(result, (p) => p.y <= yMax, (a, b) => {
    const t = (yMax - a.y) / (b.y - a.y);
    return { x: a.x + (b.x - a.x) * t, y: yMax };
  });
  return result;
}

function clipHalfPlane(
  polygon: readonly WrapPolygonPoint[],
  inside: (p: WrapPolygonPoint) => boolean,
  intersect: (a: WrapPolygonPoint, b: WrapPolygonPoint) => WrapPolygonPoint,
): WrapPolygonPoint[] {
  const out: WrapPolygonPoint[] = [];
  for (let i = 0; i < polygon.length; i++) {
    const cur = polygon[i];
    const prev = polygon[(i - 1 + polygon.length) % polygon.length];
    const curIn = inside(cur);
    const prevIn = inside(prev);
    if (curIn) {
      if (!prevIn) out.push(intersect(prev, cur));
      out.push({ ...cur });
    } else if (prevIn) {
      out.push(intersect(prev, cur));
    }
  }
  return out;
}

/**
 * 把絕對座標 polygon 平移到「頁 local 座標」（page.startY 變 0）。
 *
 * Paginator 通常每頁從 y=0 重新繪、polygon 的絕對 Y 需減 page.startY。
 */
export function shiftPolygonForPage(
  polygon: readonly WrapPolygonPoint[],
  pageStartY: number,
): WrapPolygonPoint[] {
  return polygon.map((p) => ({ x: p.x, y: p.y - pageStartY }));
}

/**
 * 同時做 split + shift；caller 拿到每頁「已 clip + 轉本頁座標」的 polygon。
 */
export function preparePolygonForPages(
  polygon: readonly WrapPolygonPoint[],
  pages: readonly PageYRange[],
): WrapPolygonPoint[][] {
  const split = splitPolygonAcrossPages(polygon, pages);
  return split.map((poly, i) => shiftPolygonForPage(poly, pages[i].startY));
}
