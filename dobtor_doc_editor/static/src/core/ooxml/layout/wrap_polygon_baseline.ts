/**
 * wrap polygon baseline-aware line positioning — Sprint 314。
 *
 * Sprint 296/298/304/309 polygon math + LineBreaker + render + paginator；
 * 本 sprint 補：考慮 polygon 跨 baseline 的 line 高度與基線調整。
 *
 * 場景：
 *   - 行高 = ascent + descent；ctx 繪 text 的「baseline」是 ascent 下方
 *   - polygon 撞到 line box top 與 bottom 不對稱、需要算「合法可繪 baseline Y」
 *   - 行內若 polygon 從上方插入、baseline 要往下推；下方插入、baseline 要往上拉
 *
 * 範圍（pure-fn）：
 *   - `lineBoxFromBaseline`：給 baseline + ascent + descent → 行 box [top, bottom]
 *   - `findSafeBaselineY`：在 [yMin, yMax] 範圍內找一條 baseline、使整行 box
 *     不撞 polygon（若找不到 → undefined）
 *   - `clampBaselineAvoidingPolygon`：給目標 baseline、若撞 polygon 則微調到下一安全位置
 *
 * 紀律 #18 scope-down：
 *   - 不接 Paginator real path（紀律 #21）
 *   - 不解決「polygon 與 line box 局部重疊但 caller 接受小重疊」的軟限制
 *   - 不處理多 polygon（caller 自管 union）
 */

import type { WrapPolygonPoint } from '../ast/types';
import { rectIntersectsPolygon, type ImageRect } from './wrap_polygon_math';

export interface LineBox {
  top: number;
  bottom: number;
  /** 行 height = bottom - top */
  height: number;
}

/**
 * 從 baseline + ascent + descent 算行 box。
 *
 * - top = baseline - ascent
 * - bottom = baseline + descent
 */
export function lineBoxFromBaseline(baselineY: number, ascentPt: number, descentPt: number): LineBox {
  const top = baselineY - ascentPt;
  const bottom = baselineY + descentPt;
  return { top, bottom, height: bottom - top };
}

export interface FindSafeBaselineOptions {
  /** 起始 X / width（line box X 範圍） */
  lineX: number;
  lineWidth: number;
  ascentPt: number;
  descentPt: number;
  /** 搜尋範圍：baseline 從 yMin 開始往下試到 yMax */
  yMin: number;
  yMax: number;
  /** 步進量；預設 1pt */
  step?: number;
  /** Polygon（絕對座標） */
  polygon: readonly WrapPolygonPoint[];
}

/**
 * 在 [yMin, yMax] 範圍找一條 baseline、其對應的 line box 不撞 polygon。
 *
 * 演算法：從 yMin 開始遞增 step、每步用 rectIntersectsPolygon 檢查；
 * 第一條不撞的回。找不到 → undefined（caller 視同「polygon 完全擋住該段」）。
 *
 * 空 polygon → 直接回 yMin（無 polygon、整段都安全）。
 */
export function findSafeBaselineY(opts: FindSafeBaselineOptions): number | undefined {
  const step = opts.step ?? 1;
  if (opts.polygon.length === 0) return opts.yMin;
  if (step <= 0) throw new Error('[wrap_polygon_baseline] step must be > 0');

  for (let baselineY = opts.yMin; baselineY <= opts.yMax; baselineY += step) {
    const box = lineBoxFromBaseline(baselineY, opts.ascentPt, opts.descentPt);
    const rect: ImageRect = { x: opts.lineX, y: box.top, width: opts.lineWidth, height: box.height };
    if (!rectIntersectsPolygon(rect, opts.polygon)) {
      return baselineY;
    }
  }
  return undefined;
}

/**
 * 把目標 baseline clamp 到「不撞 polygon」的位置。
 *
 * - 目標 baseline 對應 line box 不撞 → 回原值
 * - 撞 polygon → 從目標 baseline 開始往下找下一安全 baseline
 * - 範圍內找不到 → undefined
 */
export function clampBaselineAvoidingPolygon(
  desiredBaselineY: number,
  opts: Omit<FindSafeBaselineOptions, 'yMin' | 'yMax'> & { yMax: number },
): number | undefined {
  return findSafeBaselineY({
    ...opts,
    yMin: desiredBaselineY,
    yMax: opts.yMax,
  });
}

/**
 * 給 polygon、回 polygon 在 X 軸投影的「X 範圍對 baseline 影響」摘要。
 *
 * 用於 caller 想看 polygon Y 範圍涵蓋 [yMin, yMax] 時哪些 baselineY 一定撞、
 * 哪些一定安全。
 *
 * 回 { unsafeYStart, unsafeYEnd } 範圍：在此 Y 區間裡任何 baseline 都會撞
 * polygon（line box 高度 = ascent + descent 必交集 polygon Y 範圍）。
 */
export function polygonBaselineUnsafeRange(
  polygon: readonly WrapPolygonPoint[],
  ascentPt: number,
  descentPt: number,
): { unsafeYStart: number; unsafeYEnd: number } | null {
  if (polygon.length === 0) return null;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of polygon) {
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  // baseline Y 與 line box [baseline-ascent, baseline+descent]
  // 不撞 polygon 的條件：line box bottom < polygon.minY 或 line box top > polygon.maxY
  // 即 baseline + descent < polygon.minY → baseline < polygon.minY - descent
  // 或 baseline - ascent > polygon.maxY → baseline > polygon.maxY + ascent
  return {
    unsafeYStart: minY - descentPt,
    unsafeYEnd: maxY + ascentPt,
  };
}
