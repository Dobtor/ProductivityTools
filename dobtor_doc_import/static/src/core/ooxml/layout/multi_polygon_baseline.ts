/**
 * multi_polygon_baseline — Sprint 344。
 *
 * Sprint 314 wrap_polygon_baseline（single polygon 安全 baseline）+ Sprint 334
 * multi_polygon_flow（多 cluster）之後深推。本 sprint 補：
 * 一行可能同時撞到 **多個 cluster polygon**、要找一條 baseline 同時避開全部。
 *
 * 場景：頁面上下兩張圖、文字夾在中間；一行 line box 不能撞任一張圖的 wrap 區。
 *
 * 紀律 #18 scope-down：
 *   - 不接 Paginator real path（紀律 #21）
 *   - 不做「行內穿插多 polygon 間隙」精細排版（只找完整 line box 安全 baseline）
 *   - 多 polygon 用 OR 邏輯（撞任一 = 不安全）；caller 想 union 可先用 Sprint 334
 *
 * 紀律 #21：純函式整合層、不污染既有 pipeline。
 */

import type { WrapPolygonPoint } from '../ast/types';
import { rectIntersectsPolygon, type ImageRect } from './wrap_polygon_math';
import { lineBoxFromBaseline } from './wrap_polygon_baseline';

export interface MultiBaselineOptions {
  lineX: number;
  lineWidth: number;
  ascentPt: number;
  descentPt: number;
  yMin: number;
  yMax: number;
  step?: number;
  /** 多個 cluster polygon（絕對座標）；撞任一即視為不安全 */
  polygons: ReadonlyArray<readonly WrapPolygonPoint[]>;
}

/**
 * 某 baseline 對應的 line box 是否撞到任一 polygon。
 */
export function lineBoxHitsAnyPolygon(
  baselineY: number,
  opts: Pick<MultiBaselineOptions, 'lineX' | 'lineWidth' | 'ascentPt' | 'descentPt' | 'polygons'>,
): boolean {
  const box = lineBoxFromBaseline(baselineY, opts.ascentPt, opts.descentPt);
  const rect: ImageRect = {
    x: opts.lineX,
    y: box.top,
    width: opts.lineWidth,
    height: box.height,
  };
  for (const poly of opts.polygons) {
    if (poly.length === 0) continue;
    if (rectIntersectsPolygon(rect, poly)) return true;
  }
  return false;
}

/**
 * 在 [yMin, yMax] 範圍找一條 baseline、line box 不撞任一 polygon。
 *
 * - 全空 polygons（或都是 empty）→ 直接回 yMin
 * - 範圍內找不到 → undefined
 */
export function findSafeBaselineMulti(opts: MultiBaselineOptions): number | undefined {
  const step = opts.step ?? 1;
  if (step <= 0) throw new Error('[multi_polygon_baseline] step must be > 0');
  const nonEmpty = opts.polygons.filter((p) => p.length > 0);
  if (nonEmpty.length === 0) return opts.yMin;

  for (let baselineY = opts.yMin; baselineY <= opts.yMax; baselineY += step) {
    if (!lineBoxHitsAnyPolygon(baselineY, { ...opts, polygons: nonEmpty })) {
      return baselineY;
    }
  }
  return undefined;
}

/**
 * 找出 [yMin, yMax] 範圍內「所有」可放 line 的 baseline 區段。
 *
 * 回連續安全區段 list（每段 [startY, endY]）。caller 想知道「圖之間有幾條
 * 可寫的空檔」用。
 *
 * 紀律 #18：以 step 為解析度、回的是離散安全帶的合併區間。
 */
export interface SafeBand {
  startY: number;
  endY: number;
}

export function findSafeBands(opts: MultiBaselineOptions): SafeBand[] {
  const step = opts.step ?? 1;
  if (step <= 0) throw new Error('[multi_polygon_baseline] step must be > 0');
  const nonEmpty = opts.polygons.filter((p) => p.length > 0);
  if (nonEmpty.length === 0) {
    return [{ startY: opts.yMin, endY: opts.yMax }];
  }

  const bands: SafeBand[] = [];
  let bandStart: number | null = null;
  let lastSafe = opts.yMin;
  for (let y = opts.yMin; y <= opts.yMax; y += step) {
    const safe = !lineBoxHitsAnyPolygon(y, { ...opts, polygons: nonEmpty });
    if (safe) {
      if (bandStart === null) bandStart = y;
      lastSafe = y;
    } else if (bandStart !== null) {
      bands.push({ startY: bandStart, endY: lastSafe });
      bandStart = null;
    }
  }
  if (bandStart !== null) bands.push({ startY: bandStart, endY: lastSafe });
  return bands;
}

/**
 * 計算給定行高下、安全帶能放幾行（caller 估算頁面可容納行數用）。
 *
 * lineHeightPt <= 0 → 0。
 */
export function countFittableLines(bands: ReadonlyArray<SafeBand>, lineHeightPt: number): number {
  if (lineHeightPt <= 0) return 0;
  let total = 0;
  for (const b of bands) {
    const span = b.endY - b.startY;
    if (span < 0) continue;
    total += Math.floor(span / lineHeightPt) + 1;
  }
  return total;
}
