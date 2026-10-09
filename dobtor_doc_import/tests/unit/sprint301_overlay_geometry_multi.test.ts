/**
 * Sprint 301 — ⑤ deeper：overlay_geometry multi-select / resize-by-handle 工具。
 *
 * Follow-up to Sprint 291 honest gap「doc_editor.js 未 refactor 接 utility」+
 *「alignment guide visual indicator 未做」第二輪。本 sprint 補：
 *
 *   - resizeRectByHandle：8 handle resize
 *   - computeMultiSelectBounds + translateMultiSelect：群組移動
 *   - alignMultiSelect / distributeMultiSelect：群組對齊與分佈
 *
 * 紀律 #18 scope-down：pure-fn + tests；doc_editor.js 不動避免破 13 Playwright E2E
 * （同 Sprint 291 政策）。
 */
import { describe, expect, it } from 'vitest';

import {
  resizeRectByHandle,
  computeMultiSelectBounds,
  translateMultiSelect,
  alignMultiSelect,
  distributeMultiSelect,
} from '../../static/src/components/doc_editor/overlay_geometry_multi';
import type { Rect } from '../../static/src/components/doc_editor/overlay_geometry';

const RECT = (x: number, y: number, w: number, h: number): Rect => ({ x, y, width: w, height: h });

// ── resizeRectByHandle ────────────────────────────────────────────────────

describe('Sprint 301 — resizeRectByHandle 8 handle', () => {
  const origin = RECT(100, 100, 200, 150);
  const opts = { minW: 10, minH: 10 };

  it('e handle 拉右、寬增加', () => {
    const r = resizeRectByHandle(origin, 'e', 50, 0, opts);
    expect(r).toEqual({ x: 100, y: 100, width: 250, height: 150 });
  });

  it('w handle 拉左、x 變、寬增加', () => {
    const r = resizeRectByHandle(origin, 'w', -30, 0, opts);
    expect(r).toEqual({ x: 70, y: 100, width: 230, height: 150 });
  });

  it('s handle 拉下、高增加', () => {
    const r = resizeRectByHandle(origin, 's', 0, 40, opts);
    expect(r).toEqual({ x: 100, y: 100, width: 200, height: 190 });
  });

  it('nw handle 拉左上、x/y 變、寬高增加', () => {
    const r = resizeRectByHandle(origin, 'nw', -20, -10, opts);
    expect(r).toEqual({ x: 80, y: 90, width: 220, height: 160 });
  });

  it('se handle 拉右下、寬高增加', () => {
    const r = resizeRectByHandle(origin, 'se', 30, 20, opts);
    expect(r).toEqual({ x: 100, y: 100, width: 230, height: 170 });
  });

  it('minW / minH 套用 + anchor 修正：w handle 縮過頭、x 對應修正', () => {
    const r = resizeRectByHandle(origin, 'w', 500, 0, { minW: 50, minH: 10 });
    // origin.x + origin.width = 300（anchor 右邊），最終 width=50 → x = 300 - 50 = 250
    expect(r.x).toBe(250);
    expect(r.width).toBe(50);
  });

  it('preserveAspect：水平 drag 主導、高度按 aspect 計算', () => {
    const r = resizeRectByHandle(RECT(0, 0, 200, 100), 'e', 100, 5, { minW: 10, minH: 10, preserveAspect: true });
    // aspect = 200/100 = 2，新 width = 300，新 height = 150
    expect(r.width).toBe(300);
    expect(r.height).toBe(150);
  });

  it('bounds 套用：resize 結果不超出 page', () => {
    const r = resizeRectByHandle(RECT(50, 50, 100, 100), 'se', 999, 999, { minW: 10, minH: 10, bounds: { width: 300, height: 200 } });
    expect(r.x + r.width).toBeLessThanOrEqual(300);
    expect(r.y + r.height).toBeLessThanOrEqual(200);
  });
});

// ── computeMultiSelectBounds + translateMultiSelect ────────────────────────

describe('Sprint 301 — computeMultiSelectBounds', () => {
  it('N rect 群組 bbox', () => {
    const bbox = computeMultiSelectBounds([RECT(10, 20, 100, 50), RECT(200, 80, 60, 40)]);
    expect(bbox).toEqual({ x: 10, y: 20, width: 250, height: 100 });
  });

  it('空陣列 → null', () => {
    expect(computeMultiSelectBounds([])).toBeNull();
  });

  it('單一 rect → 等於該 rect', () => {
    const r = RECT(5, 5, 20, 30);
    expect(computeMultiSelectBounds([r])).toEqual(r);
  });
});

describe('Sprint 301 — translateMultiSelect', () => {
  it('群組移動、各 rect 保持相對位置', () => {
    const rects = [RECT(0, 0, 50, 50), RECT(100, 50, 80, 60)];
    const out = translateMultiSelect(rects, 30, 20);
    expect(out[0]).toEqual({ x: 30, y: 20, width: 50, height: 50 });
    expect(out[1]).toEqual({ x: 130, y: 70, width: 80, height: 60 });
  });

  it('bounds clamp：群組 bbox 不超出 page', () => {
    const rects = [RECT(10, 10, 50, 50), RECT(80, 10, 50, 50)]; // bbox = (10,10,120,50)
    // 試圖往右移 999，bbox 不能超出 200 → group dx = 70 (bounds.width - bbox.maxX = 200 - 130 = 70)
    const out = translateMultiSelect(rects, 999, 0, { width: 200, height: 200 });
    expect(out[0].x).toBe(80);
    expect(out[1].x).toBe(150);
  });
});

// ── alignMultiSelect ──────────────────────────────────────────────────────

describe('Sprint 301 — alignMultiSelect', () => {
  const rects = [RECT(10, 10, 50, 30), RECT(100, 20, 80, 40), RECT(60, 50, 40, 20)];

  it('left → 全部對齊到 bbox 左邊', () => {
    const out = alignMultiSelect(rects, 'left');
    for (const r of out) expect(r.x).toBe(10);
  });

  it('right → 各 rect 右邊對齊到 bbox 右邊', () => {
    const out = alignMultiSelect(rects, 'right');
    // bbox: minX=10, maxX=180 → bbox.width = 170
    for (let i = 0; i < out.length; i++) {
      expect(out[i].x + out[i].width).toBe(180);
    }
  });

  it('center-h → 各 rect 中心對齊到 bbox 中線', () => {
    const out = alignMultiSelect(rects, 'center-h');
    const bboxCenter = (10 + 180) / 2; // 95
    for (let i = 0; i < out.length; i++) {
      expect(out[i].x + out[i].width / 2).toBe(bboxCenter);
    }
  });

  it('top / middle-v / bottom 同理 Y 軸', () => {
    const outTop = alignMultiSelect(rects, 'top');
    for (const r of outTop) expect(r.y).toBe(10);
    const outBottom = alignMultiSelect(rects, 'bottom');
    for (const r of outBottom) expect(r.y + r.height).toBe(70); // bbox maxY = 70
  });

  it('< 2 rect 不對齊', () => {
    expect(alignMultiSelect([RECT(0, 0, 10, 10)], 'left')).toEqual([RECT(0, 0, 10, 10)]);
  });
});

// ── distributeMultiSelect ─────────────────────────────────────────────────

describe('Sprint 301 — distributeMultiSelect', () => {
  it('horizontal：均勻分佈中間 rect、首尾不動', () => {
    // 3 rect 同寬：x=0,50,200 → centers=5,55,205；step=(205-5)/2=100 → 中間 center 應為 105，x = 105-5 = 100
    const out = distributeMultiSelect([RECT(0, 0, 10, 10), RECT(50, 0, 10, 10), RECT(200, 0, 10, 10)], 'horizontal');
    expect(out[0].x).toBe(0);
    expect(out[1].x).toBe(100);
    expect(out[2].x).toBe(200);
  });

  it('vertical：均勻分佈 Y 軸', () => {
    const out = distributeMultiSelect([RECT(0, 0, 10, 10), RECT(0, 100, 10, 10), RECT(0, 50, 10, 10)], 'vertical');
    // sorted by Y center: y=0(c=5), y=50(c=55), y=100(c=105) → step=50 → 中間 center=55，y=50（即原位）
    // 但 distribute 不照原順序：out[i] 對應原陣列順序
    expect(out[0].y).toBe(0);
    expect(out[2].y).toBe(50);  // 原 index 2（y=50）為排序中間
    expect(out[1].y).toBe(100); // 原 index 1（y=100）為排序最後
  });

  it('< 3 rect 直接回原', () => {
    expect(distributeMultiSelect([RECT(0, 0, 10, 10), RECT(50, 0, 10, 10)], 'horizontal')).toEqual([
      RECT(0, 0, 10, 10),
      RECT(50, 0, 10, 10),
    ]);
  });
});
