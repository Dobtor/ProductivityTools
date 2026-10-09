/**
 * text_flow_around_polygon — Sprint 329。
 *
 * Sprint 296/298/304/309/314/319/324 polygon 系列第八輪深推。本 sprint 補
 * **integration shim**：把 anchor-resolve → baseline-find → LineBreaker-flow
 * 三層串成 caller-friendly 的 pure-fn pipeline。
 *
 * 場景：
 *   - 既有 wrap_polygon_math（296）、LineBreakerWithPolygon（298）、
 *     wrap_polygon_baseline（314）、wrap_polygon_anchor（324）四套都各自獨立
 *   - caller 想做「我有 anchor + image + paragraph → 給我 positioned lines」
 *     就要手動串四套；本 module 提供 façade、不重實作
 *
 * 紀律 #18 scope-down：
 *   - 仍走 single-polygon 路徑（多 polygon union 用 Sprint 319 自行合）
 *   - 不接 Paginator real path（紀律 #21）
 *   - 不做 ShapingEngine 預熱、caller 自負字型已 load
 *
 * 紀律 #21：純函式整合層、不污染既有 pipeline。
 */

import type { ShapingEngine } from '../font/ShapingEngine';
import type { WrapPolygon, WrapPolygonPoint } from '../ast/types';
import {
  resolveAnchorPolygon,
  type DistMargins,
} from './wrap_polygon_anchor';
import {
  type ImageRect,
  polygonBoundingBox,
  type PolygonBoundingBox,
} from './wrap_polygon_math';
import {
  findSafeBaselineY,
  type LineBox,
  lineBoxFromBaseline,
} from './wrap_polygon_baseline';
import {
  breakParagraphAroundPolygon,
  type LineBreakWithPolygonOptions,
  type LineBreakWithPolygonResult,
} from './LineBreakerWithPolygon';

export interface WrapContextOptions {
  /** drawing 座標系下的 polygon（image-relative） */
  polygon: WrapPolygon;
  /** 圖像置放的 page-Pt rect */
  imageRect: ImageRect;
  /** 4 方距離邊距（Sprint 287 AnchorMetadata） */
  dist?: DistMargins;
}

/**
 * Caller 取得的 wrap context：已 transform + inflate 後的 polygon + 對應 bbox。
 * 之後 baseline-find / paragraph-flow 都吃這個 context。
 */
export interface WrapContext {
  /** Page-Pt 絕對座標的 polygon vertices */
  polygonAbs: readonly WrapPolygonPoint[];
  /** Polygon bbox（pre-cached、避免重算） */
  bbox: PolygonBoundingBox;
  /** 原本傳入的 imageRect copy（caller 之後 debug 用） */
  imageRect: ImageRect;
}

/**
 * 一步把 anchor + dist 解算成 absolute polygon + bbox。
 *
 * 空 polygon（lineTo.length === 0）→ polygonAbs 為空 array；caller 應視同
 * 「沒有 wrap 限制」走 fast path。
 */
export function prepareWrapContext(opts: WrapContextOptions): WrapContext {
  // lineTo 為空 → 視為「無 wrap 限制」、polygonAbs 直接給空 array
  // （transformWrapPolygon 對僅 start 的 polygon 仍會回 1 點、導致 bbox 失準）
  if (opts.polygon.lineTo.length === 0) {
    return {
      polygonAbs: [],
      bbox: { minX: 0, minY: 0, maxX: 0, maxY: 0 },
      imageRect: { ...opts.imageRect },
    };
  }
  const polygonAbs = resolveAnchorPolygon(opts.polygon, opts.imageRect, opts.dist ?? {});
  const bbox = polygonBoundingBox(polygonAbs);
  return { polygonAbs, bbox, imageRect: { ...opts.imageRect } };
}

export interface FlowBaselineOptions {
  lineX: number;
  lineWidth: number;
  ascentPt: number;
  descentPt: number;
  yMin: number;
  yMax: number;
  step?: number;
}

/**
 * 在 wrap context 範圍內找 safe baseline。
 *
 * 空 polygon → 直接回 yMin（不需要 avoid）。
 */
export function findFlowBaseline(
  ctx: WrapContext,
  opts: FlowBaselineOptions,
): number | undefined {
  return findSafeBaselineY({
    polygon: ctx.polygonAbs,
    lineX: opts.lineX,
    lineWidth: opts.lineWidth,
    ascentPt: opts.ascentPt,
    descentPt: opts.descentPt,
    yMin: opts.yMin,
    yMax: opts.yMax,
    step: opts.step,
  });
}

/**
 * 既有 baseline + ascent/descent → LineBox（純 re-export 包裝、避免 caller 重 import）。
 */
export function flowLineBox(baselineY: number, ascentPt: number, descentPt: number): LineBox {
  return lineBoxFromBaseline(baselineY, ascentPt, descentPt);
}

/**
 * Wrap context + paragraph opts → positioned lines。
 *
 * 透傳給 Sprint 298 breakParagraphAroundPolygon、把 polygonAbs 從 context 帶入。
 * 該 inner fn 為 async（ShapingEngine 預熱）；本 façade 同樣 async。
 */
export function flowParagraphAroundWrapCtx(
  ctx: WrapContext,
  engine: ShapingEngine,
  opts: Omit<LineBreakWithPolygonOptions, 'polygonAbs'>,
): Promise<LineBreakWithPolygonResult> {
  return breakParagraphAroundPolygon(engine, {
    ...opts,
    polygonAbs: ctx.polygonAbs,
  });
}

/**
 * Caller 想知道 polygon 在 Y 範圍內是否會擋到（不需要做完整 flow 的 fast check）。
 *
 * 空 polygon → 永遠 false。
 */
export function isYRangeBlockedByWrap(ctx: WrapContext, yMin: number, yMax: number): boolean {
  if (ctx.polygonAbs.length === 0) return false;
  // 用 bbox 做 cheap check（與 Sprint 309 paginator 同政策）
  return ctx.bbox.maxY >= yMin && ctx.bbox.minY <= yMax;
}
