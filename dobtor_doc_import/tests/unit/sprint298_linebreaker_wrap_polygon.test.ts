/**
 * Sprint 298 — Phase 3.4 wrapTight LineBreaker integration。
 *
 * Follow-up to Sprint 296（wrap_polygon_math pure-fn helpers）。
 * 把 polygon 數學工具接進 LineBreaker，產出帶位置的 PositionedLine[]。
 *
 * Strategy A integration spike：~150 行新模組 + 11 tests。
 *
 * 紀律 #18 scope-down：單一 polygon；polygon 內部空隙不穿插；caller opt-in
 *   才用此函式（既有 LineBreaker MVP 行為不變）。
 * 紀律 #21：新模組獨立、既有 VR pipeline 不消費、零 regression 風險。
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';
import {
  breakParagraphAroundPolygon,
  transformWrapPolygon,
} from '../../static/src/core/ooxml/layout';
import type { WrapPolygon } from '../../static/src/core/ooxml/ast/types';

const FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT_PATH);

function makeEngine(): ShapingEngine {
  const engine = new ShapingEngine();
  engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH)));
  return engine;
}

describe.skipIf(!HAS_FONT)('Sprint 298 — breakParagraphAroundPolygon basic', () => {
  it('無 polygon 影響的位置（Y 不重疊）→ 與普通 LineBreaker 一致', async () => {
    const engine = makeEngine();
    // polygon 在 y=500 附近，段落在 y=0 → 完全不影響
    const polyAbs = [
      { x: 100, y: 500 },
      { x: 200, y: 500 },
      { x: 200, y: 600 },
      { x: 100, y: 600 },
    ];
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'Hello world this is a test paragraph for layout integration',
      startX: 0,
      startY: 0,
      lineHeightPt: 14,
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
    });
    expect(result.totalLines).toBeGreaterThan(0);
    // 全行起點都在 x=0（無 polygon 卡）
    expect(result.lines.every((l) => l.x === 0)).toBe(true);
    // Y 逐行 +14
    for (let i = 1; i < result.lines.length; i++) {
      expect(result.lines[i].y - result.lines[i - 1].y).toBeCloseTo(14, 5);
    }
  });

  it('段落 Y 範圍與 polygon Y 範圍完全重疊 → 文字被推到 polygon 右邊', async () => {
    const engine = makeEngine();
    // polygon 在 x=[0, 80], y=[0, 50]
    const polyAbs = [
      { x: 0, y: 0 },
      { x: 80, y: 0 },
      { x: 80, y: 50 },
      { x: 0, y: 50 },
    ];
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'short', // 確保不會太長
      startX: 0,
      startY: 10, // 段落 y=10 在 polygon Y 範圍內
      lineHeightPt: 14,
      availableWidthPt: 300,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
      bufferPt: 2,
    });
    // 第一行被 polygon 推到右邊：x 應 > 80
    expect(result.lines[0].x).toBeGreaterThan(80);
    // y 仍 = 10（同一行 advance、不換行）
    expect(result.lines[0].y).toBe(10);
  });

  it('多行段落，前幾行被 polygon 影響、後幾行不受影響', async () => {
    const engine = makeEngine();
    // polygon 在 y=[0, 20]，後面行 y>=20 應無影響
    const polyAbs = [
      { x: 0, y: 0 },
      { x: 60, y: 0 },
      { x: 60, y: 20 },
      { x: 0, y: 20 },
    ];
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'aaa bbb ccc ddd eee fff ggg hhh',
      startX: 0,
      startY: 0,
      lineHeightPt: 14,
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
    });
    // 至少一行被推到 x > 60（y 在 polygon 範圍內）
    const affected = result.lines.filter((l) => l.y < 20);
    expect(affected.every((l) => l.x > 60)).toBe(true);
    // y >= 20 的行不受 polygon 影響
    const unaffected = result.lines.filter((l) => l.y >= 20);
    expect(unaffected.every((l) => l.x === 0)).toBe(true);
  });

  it('空字串 → 回空 lines + endY = startY', async () => {
    const engine = makeEngine();
    const result = await breakParagraphAroundPolygon(engine, {
      text: '',
      startX: 10,
      startY: 50,
      lineHeightPt: 14,
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: [],
    });
    expect(result.lines).toEqual([]);
    expect(result.totalLines).toBe(0);
    expect(result.endY).toBe(50);
  });

  it('endY = 最後一行 y + lineHeight', async () => {
    const engine = makeEngine();
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'aa bb cc dd ee ff gg hh ii jj',
      startX: 0,
      startY: 0,
      lineHeightPt: 14,
      availableWidthPt: 100,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: [],
    });
    const lastLine = result.lines[result.lines.length - 1];
    expect(result.endY).toBeCloseTo(lastLine.y + 14, 5);
  });

  it('spaceWidthPt 注入 → 加速、結果與不注入一致', async () => {
    const engine = makeEngine();
    const polyAbs: { x: number; y: number }[] = [];
    const noInject = await breakParagraphAroundPolygon(engine, {
      text: 'Hello world foo bar',
      startY: 0,
      lineHeightPt: 14,
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
    });
    const spaceWidth = (await engine.measureRun(' ', 'DejaVuSans', 12)).widthPt;
    const withInject = await breakParagraphAroundPolygon(engine, {
      text: 'Hello world foo bar',
      startY: 0,
      lineHeightPt: 14,
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
      spaceWidthPt: spaceWidth,
    });
    expect(withInject.totalLines).toBe(noInject.totalLines);
    expect(withInject.maxLineWidthPt).toBeCloseTo(noInject.maxLineWidthPt, 3);
  });
});

describe.skipIf(!HAS_FONT)('Sprint 298 — transformWrapPolygon 整合場景', () => {
  it('AST WrapPolygon → transformWrapPolygon → breakParagraphAroundPolygon end-to-end', async () => {
    const engine = makeEngine();
    // AST polygon 在 21600 drawing coords
    const polygon: WrapPolygon = {
      start: { x: 0, y: 0 },
      lineTo: [
        { x: 21600, y: 0 },
        { x: 21600, y: 21600 },
        { x: 0, y: 21600 },
      ],
    };
    // 圖片位置 + 尺寸：x=0（無左邊空間）, y=0, 100×30
    const polyAbs = transformWrapPolygon(polygon, {
      x: 0,
      y: 0,
      width: 100,
      height: 30,
    });
    // 預期 transformed = [(0,0), (100,0), (100,30), (0,30)]
    expect(polyAbs[0]).toEqual({ x: 0, y: 0 });
    expect(polyAbs[2]).toEqual({ x: 100, y: 30 });

    const result = await breakParagraphAroundPolygon(engine, {
      text: 'Hello',
      startX: 0,
      startY: 5,
      lineHeightPt: 14,
      availableWidthPt: 300,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
    });
    // 段落 y=5 在 polygon Y 範圍 [0, 30] 內、無左邊空間 → 第一行 x 應 > 100（被推到 polygon 右邊）
    expect(result.lines[0].x).toBeGreaterThan(100);
  });
});

describe.skipIf(!HAS_FONT)('Sprint 298 — startX !== 0 場景', () => {
  it('startX=50（段落本來就在 indent） → polygon 還是相對絕對座標判斷', async () => {
    const engine = makeEngine();
    // polygon 在 x=[10, 60]、y=[0, 20]
    const polyAbs = [
      { x: 10, y: 0 },
      { x: 60, y: 0 },
      { x: 60, y: 20 },
      { x: 10, y: 20 },
    ];
    // 段落 startX=50（已經在 polygon Y 範圍 + X 範圍 right edge 內、被推到右邊）
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'hi',
      startX: 50,
      startY: 5,
      lineHeightPt: 14,
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
    });
    // 因 startX=50 在 polygon X 範圍內、被推到 polygon.maxX + buffer
    expect(result.lines[0].x).toBeGreaterThan(60);
  });
});

describe.skipIf(!HAS_FONT)('Sprint 298 — bufferPt 控制', () => {
  it('bufferPt=10 → polygon 右邊空 10pt 才開始排字', async () => {
    const engine = makeEngine();
    const polyAbs = [
      { x: 0, y: 0 },
      { x: 80, y: 0 },
      { x: 80, y: 50 },
      { x: 0, y: 50 },
    ];
    const result = await breakParagraphAroundPolygon(engine, {
      text: 'hi',
      startX: 0,
      startY: 10,
      lineHeightPt: 14,
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      polygonAbs: polyAbs,
      bufferPt: 10,
    });
    // 80 (polygon right) + 10 (buffer) = 90
    expect(result.lines[0].x).toBeGreaterThanOrEqual(90);
  });
});
