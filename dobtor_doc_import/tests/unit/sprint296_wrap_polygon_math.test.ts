/**
 * Sprint 296 — wrap_polygon_math (Phase 3.4 wrapTight layout math)。
 *
 * Follow-up to Sprint 289 honest gap「wrapPolygon render clip 未做（Phase 3.4
 * 完整 wrapTight 留 future）」。
 *
 * Strategy C+ utility extraction：純函式幾何工具 + 18 tests。
 *
 * 紀律 #18 scope-down：本 sprint 不接 Layout engine（Phase 3.4 完整 wrapTight
 *   需重寫 LineBreaker 換行邏輯、超出單 sprint scope）；未來 polish sprint
 *   才 wire 進 LineBreaker / Paginator。
 * 紀律 #21：純函式、無 side effect、不污染 VR pipeline。
 */
import { describe, expect, it } from 'vitest';

import {
  transformWrapPolygon,
  polygonBoundingBox,
  pointInPolygon,
  rectIntersectsPolygon,
} from '../../static/src/core/ooxml/layout';
import type { WrapPolygon, WrapPolygonPoint } from '../../static/src/core/ooxml/ast/types';

describe('Sprint 296 — transformWrapPolygon', () => {
  it('drawing coords 21600 → 圖片 144×72 pt → 正確比例 scale + 位移', () => {
    const polygon: WrapPolygon = {
      start: { x: 0, y: 0 },
      lineTo: [
        { x: 21600, y: 0 },
        { x: 21600, y: 21600 },
        { x: 0, y: 21600 },
      ],
    };
    const imageRect = { x: 100, y: 200, width: 144, height: 72 };
    const transformed = transformWrapPolygon(polygon, imageRect);
    expect(transformed).toEqual([
      { x: 100, y: 200 },
      { x: 244, y: 200 },
      { x: 244, y: 272 },
      { x: 100, y: 272 },
    ]);
  });

  it('自訂 drawingUnits=100 → scale 直接 = imageRect.width/100', () => {
    const polygon: WrapPolygon = {
      start: { x: 0, y: 0 },
      lineTo: [{ x: 50, y: 100 }],
    };
    const imageRect = { x: 0, y: 0, width: 200, height: 200 };
    const transformed = transformWrapPolygon(polygon, imageRect, 100);
    expect(transformed[1]).toEqual({ x: 100, y: 200 });
  });

  it('image at non-zero origin → 所有點同樣位移', () => {
    const polygon: WrapPolygon = {
      start: { x: 10800, y: 10800 },
      lineTo: [{ x: 21600, y: 21600 }],
    };
    const imageRect = { x: 50, y: 50, width: 100, height: 100 };
    const transformed = transformWrapPolygon(polygon, imageRect);
    expect(transformed[0]).toEqual({ x: 100, y: 100 }); // 50 + 10800*100/21600
    expect(transformed[1]).toEqual({ x: 150, y: 150 });
  });
});

describe('Sprint 296 — polygonBoundingBox', () => {
  it('規則矩形 polygon → 正確 bbox', () => {
    const poly: WrapPolygonPoint[] = [
      { x: 10, y: 20 },
      { x: 50, y: 20 },
      { x: 50, y: 80 },
      { x: 10, y: 80 },
    ];
    expect(polygonBoundingBox(poly)).toEqual({ minX: 10, minY: 20, maxX: 50, maxY: 80 });
  });

  it('不規則多邊形 → bbox 涵蓋所有點', () => {
    const poly: WrapPolygonPoint[] = [
      { x: 5, y: 0 },
      { x: 0, y: 10 },
      { x: 15, y: 5 },
      { x: 8, y: -3 },
    ];
    expect(polygonBoundingBox(poly)).toEqual({ minX: 0, minY: -3, maxX: 15, maxY: 10 });
  });

  it('空 polygon → 0/0/0/0', () => {
    expect(polygonBoundingBox([])).toEqual({ minX: 0, minY: 0, maxX: 0, maxY: 0 });
  });

  it('單點 polygon → minX=maxX、minY=maxY', () => {
    expect(polygonBoundingBox([{ x: 5, y: 7 }])).toEqual({ minX: 5, minY: 7, maxX: 5, maxY: 7 });
  });
});

describe('Sprint 296 — pointInPolygon (ray-casting)', () => {
  // 簡單矩形 polygon：(0,0) → (10,0) → (10,10) → (0,10)
  const SQUARE: WrapPolygonPoint[] = [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
    { x: 0, y: 10 },
  ];

  it('點在矩形正中 → true', () => {
    expect(pointInPolygon({ x: 5, y: 5 }, SQUARE)).toBe(true);
  });

  it('點在矩形外右側 → false', () => {
    expect(pointInPolygon({ x: 15, y: 5 }, SQUARE)).toBe(false);
  });

  it('點在矩形左下 → false', () => {
    expect(pointInPolygon({ x: -1, y: -1 }, SQUARE)).toBe(false);
  });

  it('< 3 點 polygon → 必 false（無法形成多邊形）', () => {
    expect(pointInPolygon({ x: 1, y: 1 }, [])).toBe(false);
    expect(pointInPolygon({ x: 1, y: 1 }, [{ x: 0, y: 0 }])).toBe(false);
    expect(pointInPolygon({ x: 1, y: 1 }, [{ x: 0, y: 0 }, { x: 5, y: 5 }])).toBe(false);
  });

  it('凸多邊形（三角形）→ 內外判定正確', () => {
    const TRI: WrapPolygonPoint[] = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 5, y: 10 }];
    expect(pointInPolygon({ x: 5, y: 3 }, TRI)).toBe(true);
    expect(pointInPolygon({ x: 0, y: 9 }, TRI)).toBe(false); // 左上角外
    expect(pointInPolygon({ x: 5, y: 11 }, TRI)).toBe(false); // 上方外
  });
});

describe('Sprint 296 — rectIntersectsPolygon', () => {
  const SQUARE: WrapPolygonPoint[] = [
    { x: 100, y: 100 },
    { x: 200, y: 100 },
    { x: 200, y: 200 },
    { x: 100, y: 200 },
  ];

  it('rect 完全在 polygon bbox 外 → false', () => {
    expect(rectIntersectsPolygon({ x: 300, y: 300, width: 50, height: 50 }, SQUARE)).toBe(false);
    expect(rectIntersectsPolygon({ x: 0, y: 0, width: 50, height: 50 }, SQUARE)).toBe(false);
  });

  it('rect 完全包住 polygon → true（polygon 頂點在 rect 內）', () => {
    expect(rectIntersectsPolygon({ x: 50, y: 50, width: 200, height: 200 }, SQUARE)).toBe(true);
  });

  it('rect 完全在 polygon 內 → true（rect 角點在 polygon 內）', () => {
    expect(rectIntersectsPolygon({ x: 120, y: 120, width: 30, height: 30 }, SQUARE)).toBe(true);
  });

  it('rect 與 polygon 邊重疊（半交） → true', () => {
    // rect 中心在 polygon 邊界上
    expect(rectIntersectsPolygon({ x: 180, y: 150, width: 50, height: 30 }, SQUARE)).toBe(true);
  });

  it('< 3 點 polygon → 必 false', () => {
    expect(rectIntersectsPolygon(
      { x: 0, y: 0, width: 100, height: 100 },
      [{ x: 50, y: 50 }],
    )).toBe(false);
  });

  it('rect 與 polygon bbox 重疊但不真的相交（凹角空隙）', () => {
    // L 形 polygon：(0,0)→(50,0)→(50,30)→(20,30)→(20,50)→(0,50)
    // rect 位在 L 凹角空隙：(25,35) 30x10 → 不在 polygon 內
    const L: WrapPolygonPoint[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 30 },
      { x: 20, y: 30 },
      { x: 20, y: 50 },
      { x: 0, y: 50 },
    ];
    // rect 完全在凹角內、不碰任何 polygon 邊：
    // rect = (30, 35, 10x5) → 各角點都不在 polygon 內，polygon 各點都不在 rect 內
    expect(rectIntersectsPolygon({ x: 30, y: 35, width: 10, height: 5 }, L)).toBe(false);
  });
});
