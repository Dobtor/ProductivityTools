/**
 * Sprint 291 — ⑤ Phase 8.2.2 overlay 幾何工具 unit tests。
 *
 * User 指令「繼續執行 1-6」cluster ⑤ — explicit OVERRIDE。原 ADR-022 條件啟動項
 * 已於 Sprint D（2026-05-23）MVP 落地；本 sprint 抽 pure-fn 幾何工具為未來
 * polish sprint（resize boundary 完善 + 對齊輔助線）鋪基礎。
 *
 * Strategy C+ extraction：utility module pure functions + 25 unit tests，
 * 不動 doc_editor.js 既有 clamp inline 邏輯（紀律 #21 不污染現行 OWL 行為）；
 * 未來 polish sprint 才接此 utility refactor doc_editor.js。
 */
import { describe, expect, it } from 'vitest';

import {
  clampPosToBounds,
  clampSizeToBounds,
  computeAlignGuides,
  pickSnapTargets,
} from '../../static/src/components/doc_editor/overlay_geometry';
import type { Rect, AlignGuide } from '../../static/src/components/doc_editor/overlay_geometry';

const PAGE = { width: 595, height: 842 };

describe('Sprint 291 — clampPosToBounds', () => {
  it('rect 在內部 → 不變', () => {
    const r: Rect = { x: 100, y: 200, width: 50, height: 30 };
    expect(clampPosToBounds(r, PAGE)).toEqual({ x: 100, y: 200 });
  });
  it('rect 負座標 → clamp 到 0', () => {
    const r: Rect = { x: -10, y: -20, width: 50, height: 30 };
    expect(clampPosToBounds(r, PAGE)).toEqual({ x: 0, y: 0 });
  });
  it('rect 超出右下 → clamp 到 max', () => {
    const r: Rect = { x: 600, y: 900, width: 50, height: 30 };
    expect(clampPosToBounds(r, PAGE)).toEqual({ x: 545, y: 812 });
  });
  it('rect 寬高 > bounds → clamp x/y 到 0（位置）', () => {
    const r: Rect = { x: 100, y: 100, width: 700, height: 1000 };
    expect(clampPosToBounds(r, PAGE)).toEqual({ x: 0, y: 0 });
  });
});

describe('Sprint 291 — clampSizeToBounds', () => {
  it('size 不超界 → 取 min/max 限制後不變', () => {
    const r: Rect = { x: 100, y: 200, width: 50, height: 30 };
    expect(clampSizeToBounds(r, PAGE, 40, 20)).toEqual({ width: 50, height: 30 });
  });
  it('size 超界 → cap 到 (bounds - position)', () => {
    const r: Rect = { x: 500, y: 800, width: 200, height: 200 };
    expect(clampSizeToBounds(r, PAGE, 40, 20)).toEqual({ width: 95, height: 42 });
  });
  it('size < min → 提升到 min', () => {
    const r: Rect = { x: 100, y: 100, width: 10, height: 5 };
    expect(clampSizeToBounds(r, PAGE, 40, 20)).toEqual({ width: 40, height: 20 });
  });
  it('剩餘空間 < min → 退化為剩餘空間（無法達 min）', () => {
    const r: Rect = { x: 585, y: 835, width: 100, height: 50 };
    // bounds.width - x = 10 < min 40 → 退化為 10
    expect(clampSizeToBounds(r, PAGE, 40, 20)).toEqual({ width: 10, height: 7 });
  });
});

describe('Sprint 291 — computeAlignGuides page edges', () => {
  it('moving 靠近 page 左緣（x=2、threshold=5）→ guide page-edge-start', () => {
    const moving: Rect = { x: 2, y: 100, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [], PAGE, 5);
    expect(guides.some((g) => g.axis === 'x' && g.reason === 'page-edge-start' && g.value === 0)).toBe(true);
  });
  it('moving 靠近 page 中線（x = (page.w - moving.w)/2 ± threshold）→ guide page-center', () => {
    const moving: Rect = { x: (PAGE.width - 50) / 2 + 3, y: 100, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [], PAGE, 5);
    expect(guides.some((g) => g.axis === 'x' && g.reason === 'page-center')).toBe(true);
  });
  it('moving 遠離所有 guide → 回空陣列', () => {
    const moving: Rect = { x: 100, y: 200, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [], PAGE, 5);
    expect(guides).toHaveLength(0);
  });
});

describe('Sprint 291 — computeAlignGuides sibling alignment', () => {
  const SIB: Rect = { x: 200, y: 300, width: 80, height: 40 };
  it('moving.x 對齊 sibling 左緣 → sibling-edge-start guide', () => {
    const moving: Rect = { x: 201, y: 0, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [SIB], PAGE, 5);
    expect(guides.some((g) => g.axis === 'x' && g.reason === 'sibling-edge-start' && g.value === 200 && g.siblingIndex === 0)).toBe(true);
  });
  it('moving.x 對齊 sibling 右緣（moving.x + moving.w == sibling.x + sibling.w）', () => {
    const moving: Rect = { x: SIB.x + SIB.width - 50 + 2, y: 0, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [SIB], PAGE, 5);
    expect(guides.some((g) => g.axis === 'x' && g.reason === 'sibling-edge-end' && g.siblingIndex === 0)).toBe(true);
  });
  it('moving.y 對齊 sibling 中線', () => {
    const movingY = SIB.y + (SIB.height - 30) / 2 + 1;
    const moving: Rect = { x: 0, y: movingY, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [SIB], PAGE, 5);
    expect(guides.some((g) => g.axis === 'y' && g.reason === 'sibling-center' && g.siblingIndex === 0)).toBe(true);
  });
  it('多 sibling → 各自 siblingIndex 正確', () => {
    const S1: Rect = { x: 100, y: 0, width: 60, height: 40 };
    const S2: Rect = { x: 400, y: 0, width: 60, height: 40 };
    const moving: Rect = { x: 101, y: 0, width: 50, height: 30 };
    const guides = computeAlignGuides(moving, [S1, S2], PAGE, 5);
    const xGuides = guides.filter((g) => g.axis === 'x' && g.reason === 'sibling-edge-start');
    expect(xGuides.length).toBeGreaterThanOrEqual(1);
    expect(xGuides[0].siblingIndex).toBe(0);
  });
});

describe('Sprint 291 — pickSnapTargets', () => {
  it('多 candidate → 各軸選最近一條', () => {
    const moving: Rect = { x: 100, y: 200, width: 50, height: 30 };
    const guides: AlignGuide[] = [
      { axis: 'x', value: 90, reason: 'sibling-edge-start' },
      { axis: 'x', value: 105, reason: 'page-center' },
      { axis: 'y', value: 195, reason: 'sibling-edge-start' },
      { axis: 'y', value: 210, reason: 'page-edge-start' },
    ];
    const { snapX, snapY } = pickSnapTargets(moving, guides);
    // x: |100-105|=5 < |100-90|=10 → 取 105
    expect(snapX?.value).toBe(105);
    // y: |200-195|=5 < |200-210|=10 → 取 195
    expect(snapY?.value).toBe(195);
  });
  it('無 guide → snapX/snapY 都 undefined', () => {
    const moving: Rect = { x: 100, y: 200, width: 50, height: 30 };
    const { snapX, snapY } = pickSnapTargets(moving, []);
    expect(snapX).toBeUndefined();
    expect(snapY).toBeUndefined();
  });
  it('只有 X guide → snapY undefined', () => {
    const moving: Rect = { x: 100, y: 200, width: 50, height: 30 };
    const guides: AlignGuide[] = [{ axis: 'x', value: 100, reason: 'page-edge-start' }];
    const { snapX, snapY } = pickSnapTargets(moving, guides);
    expect(snapX?.value).toBe(100);
    expect(snapY).toBeUndefined();
  });
});

describe('Sprint 291 — 整合場景', () => {
  it('drag 越界 → clamp → align guides 套用都正常運作', () => {
    const dragged: Rect = { x: -50, y: 850, width: 100, height: 60 };
    const clamped = clampPosToBounds(dragged, PAGE);
    expect(clamped).toEqual({ x: 0, y: 782 });
    // 在 clamp 後的位置算 guides — moving 位置已合法、必命中 page-edge-start (x=0)
    const movingClamped: Rect = { ...dragged, ...clamped };
    const guides = computeAlignGuides(movingClamped, [], PAGE, 5);
    expect(guides.some((g) => g.axis === 'x' && g.reason === 'page-edge-start')).toBe(true);
  });
});
