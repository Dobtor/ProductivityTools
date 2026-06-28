/**
 * Sprint 329 — ③ deeper⁸：text_flow_around_polygon。
 *
 * Sprint 296/298/304/309/314/319/324 polygon 系列第八輪整合 shim。
 * 紀律 #18：純整合層 façade、不重實作；不接 Paginator real path。
 */
import { describe, expect, it } from 'vitest';

import {
  prepareWrapContext,
  findFlowBaseline,
  flowLineBox,
  flowParagraphAroundWrapCtx,
  isYRangeBlockedByWrap,
} from '../../static/src/core/ooxml/layout/text_flow_around_polygon';
import type { ShapingEngine } from '../../static/src/core/ooxml/font/ShapingEngine';
import type { WrapPolygon } from '../../static/src/core/ooxml/ast/types';

// 用最小 fake ShapingEngine（measureRun positional：text/family/sizePt → widthPt）
function mkFakeEngine(charWidth = 6): ShapingEngine {
  return {
    measureRun: async (text: string) => ({
      widthPt: text.length * charWidth,
      heightPt: 12,
      glyphCount: text.length,
      advancesPt: [],
      glyphs: [],
    }),
  } as unknown as ShapingEngine;
}

// OOXML drawingUnits=21600 scale；imageRect (0,0,100,100) → polygon 占滿 0..100
const square: WrapPolygon = {
  start: { x: 0, y: 0 },
  lineTo: [
    { x: 21600, y: 0 },
    { x: 21600, y: 21600 },
    { x: 0, y: 21600 },
    { x: 0, y: 0 },
  ],
};

const emptyPolygon: WrapPolygon = { start: { x: 0, y: 0 }, lineTo: [] };

// ── prepareWrapContext ─────────────────────────────────────────────

describe('Sprint 329 — prepareWrapContext', () => {
  it('square polygon → polygonAbs 含 vertices + bbox 正確', () => {
    const ctx = prepareWrapContext({
      polygon: square,
      imageRect: { x: 50, y: 50, width: 100, height: 100 },
    });
    expect(ctx.polygonAbs.length).toBeGreaterThan(0);
    expect(ctx.bbox.minX).toBeCloseTo(50);
    expect(ctx.bbox.minY).toBeCloseTo(50);
    expect(ctx.bbox.maxX).toBeCloseTo(150);
    expect(ctx.bbox.maxY).toBeCloseTo(150);
  });

  it('dist margin → bbox 變寬', () => {
    const noMargin = prepareWrapContext({
      polygon: square,
      imageRect: { x: 50, y: 50, width: 100, height: 100 },
    });
    const withMargin = prepareWrapContext({
      polygon: square,
      imageRect: { x: 50, y: 50, width: 100, height: 100 },
      dist: { distL: 5, distR: 5, distT: 3, distB: 3 },
    });
    expect(withMargin.bbox.maxX - withMargin.bbox.minX).toBeGreaterThan(
      noMargin.bbox.maxX - noMargin.bbox.minX,
    );
  });

  it('empty polygon → polygonAbs 空 + bbox 全 0', () => {
    const ctx = prepareWrapContext({
      polygon: emptyPolygon,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    expect(ctx.polygonAbs).toHaveLength(0);
    expect(ctx.bbox.minX).toBe(0);
    expect(ctx.bbox.maxX).toBe(0);
  });
});

// ── findFlowBaseline ───────────────────────────────────────────────

describe('Sprint 329 — findFlowBaseline', () => {
  it('空 polygon → 回 yMin', () => {
    const ctx = prepareWrapContext({
      polygon: emptyPolygon,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    const y = findFlowBaseline(ctx, {
      lineX: 0,
      lineWidth: 100,
      ascentPt: 10,
      descentPt: 2,
      yMin: 0,
      yMax: 100,
    });
    expect(y).toBe(0);
  });

  it('square polygon → 推進到 polygon 下方 + ascent', () => {
    const ctx = prepareWrapContext({
      polygon: square,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    const y = findFlowBaseline(ctx, {
      lineX: 0,
      lineWidth: 100,
      ascentPt: 10,
      descentPt: 2,
      yMin: 0,
      yMax: 200,
    });
    expect(y).not.toBeUndefined();
    expect(y).toBeGreaterThanOrEqual(100); // polygon 下緣
  });

  it('yMax 不足 → undefined', () => {
    const ctx = prepareWrapContext({
      polygon: square,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    const y = findFlowBaseline(ctx, {
      lineX: 0,
      lineWidth: 100,
      ascentPt: 10,
      descentPt: 2,
      yMin: 0,
      yMax: 5,
    });
    expect(y).toBeUndefined();
  });
});

// ── flowLineBox ────────────────────────────────────────────────────

describe('Sprint 329 — flowLineBox', () => {
  it('baseline=50、ascent=10、descent=2 → top=40 bottom=52', () => {
    const box = flowLineBox(50, 10, 2);
    expect(box.top).toBe(40);
    expect(box.bottom).toBe(52);
    expect(box.height).toBe(12);
  });
});

// ── flowParagraphAroundWrapCtx ────────────────────────────────────

describe('Sprint 329 — flowParagraphAroundWrapCtx', () => {
  it('整合 LineBreakerWithPolygon、回 positioned lines', async () => {
    const ctx = prepareWrapContext({
      polygon: emptyPolygon,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    const engine = mkFakeEngine(6);
    const r = await flowParagraphAroundWrapCtx(ctx, engine, {
      text: 'hello world',
      startX: 0,
      startY: 0,
      lineHeightPt: 12,
      availableWidthPt: 200,
      fontFamily: 'Arial',
      sizePt: 10,
    });
    expect(r.totalLines).toBeGreaterThanOrEqual(1);
    expect(r.lines[0].y).toBe(0);
  });
});

// ── isYRangeBlockedByWrap ─────────────────────────────────────────

describe('Sprint 329 — isYRangeBlockedByWrap', () => {
  it('空 polygon → 永遠 false', () => {
    const ctx = prepareWrapContext({
      polygon: emptyPolygon,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    expect(isYRangeBlockedByWrap(ctx, 0, 100)).toBe(false);
  });

  it('polygon bbox 撞 Y 範圍 → true', () => {
    const ctx = prepareWrapContext({
      polygon: square,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    expect(isYRangeBlockedByWrap(ctx, 50, 150)).toBe(true);
  });

  it('polygon bbox 在 Y 範圍下方 → false', () => {
    const ctx = prepareWrapContext({
      polygon: square,
      imageRect: { x: 0, y: 0, width: 100, height: 100 },
    });
    expect(isYRangeBlockedByWrap(ctx, 200, 300)).toBe(false);
  });
});
