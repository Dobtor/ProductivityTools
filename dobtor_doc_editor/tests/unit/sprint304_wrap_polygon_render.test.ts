/**
 * Sprint 304 — ③ deeper：WrapPolygon render helpers。
 *
 * Sprint 296 / 298 補 polygon math + LineBreaker 整合；本 sprint 補 render side：
 *   - polygonToSvgPath
 *   - polygonToCanvasCommands
 *   - applyClipPathToContext（接受最小 ctx interface）
 *   - polygonWithInflate（caller padding for wrap）
 *
 * 紀律 #18 scope-down：不接 production CanvasRenderer 主路徑（紀律 #21）；
 *   even-odd fill rule only（OOXML 慣例）。
 */
import { describe, expect, it, vi } from 'vitest';

import {
  polygonToSvgPath,
  polygonToCanvasCommands,
  applyClipPathToContext,
  polygonWithInflate,
} from '../../static/src/core/ooxml/layout/wrap_polygon_render';
import type { MinimalCanvasContext } from '../../static/src/core/ooxml/layout/wrap_polygon_render';

const SQUARE = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

// ── polygonToSvgPath ─────────────────────────────────────────────────────

describe('Sprint 304 — polygonToSvgPath', () => {
  it('square polygon → 完整 M-L-L-L-Z 路徑', () => {
    expect(polygonToSvgPath(SQUARE)).toBe('M 0 0 L 100 0 L 100 100 L 0 100 Z');
  });

  it('空 polygon → 空字串', () => {
    expect(polygonToSvgPath([])).toBe('');
  });

  it('單點 polygon → "M x y Z"', () => {
    expect(polygonToSvgPath([{ x: 5, y: 7 }])).toBe('M 5 7 Z');
  });

  it('三角形 polygon', () => {
    const tri = [{ x: 0, y: 0 }, { x: 50, y: 100 }, { x: 100, y: 0 }];
    expect(polygonToSvgPath(tri)).toBe('M 0 0 L 50 100 L 100 0 Z');
  });
});

// ── polygonToCanvasCommands ───────────────────────────────────────────────

describe('Sprint 304 — polygonToCanvasCommands', () => {
  it('square polygon → moveTo + 3×lineTo + closePath', () => {
    const cmds = polygonToCanvasCommands(SQUARE);
    expect(cmds).toEqual([
      { op: 'moveTo', x: 0, y: 0 },
      { op: 'lineTo', x: 100, y: 0 },
      { op: 'lineTo', x: 100, y: 100 },
      { op: 'lineTo', x: 0, y: 100 },
      { op: 'closePath' },
    ]);
  });

  it('空 polygon → 空陣列', () => {
    expect(polygonToCanvasCommands([])).toEqual([]);
  });
});

// ── applyClipPathToContext ────────────────────────────────────────────────

describe('Sprint 304 — applyClipPathToContext', () => {
  it('呼叫 ctx 對應方法 + clip(evenodd)', () => {
    const ctx: MinimalCanvasContext = {
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      clip: vi.fn(),
    };
    applyClipPathToContext(ctx, SQUARE);
    expect(ctx.beginPath).toHaveBeenCalledOnce();
    expect(ctx.moveTo).toHaveBeenCalledWith(0, 0);
    expect(ctx.lineTo).toHaveBeenCalledTimes(3);
    expect(ctx.lineTo).toHaveBeenNthCalledWith(1, 100, 0);
    expect(ctx.closePath).toHaveBeenCalledOnce();
    expect(ctx.clip).toHaveBeenCalledWith('evenodd');
  });

  it('空 polygon → 不呼叫任何方法（no-op）', () => {
    const ctx: MinimalCanvasContext = {
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      clip: vi.fn(),
    };
    applyClipPathToContext(ctx, []);
    expect(ctx.beginPath).not.toHaveBeenCalled();
    expect(ctx.clip).not.toHaveBeenCalled();
  });
});

// ── polygonWithInflate ────────────────────────────────────────────────────

describe('Sprint 304 — polygonWithInflate', () => {
  it('delta=0 → 原 polygon copy', () => {
    const out = polygonWithInflate(SQUARE, 0);
    expect(out).toEqual(SQUARE);
    expect(out).not.toBe(SQUARE); // 新陣列
  });

  it('delta>0 → 各 vertex 沿 bbox 中心向外擴', () => {
    // bbox center = (50, 50)；4 vertex 對中心距離 = √(50² + 50²) ≈ 70.71
    const out = polygonWithInflate(SQUARE, 10);
    // 期望 vertex 距離中心變 80.71
    for (const p of out) {
      const d = Math.hypot(p.x - 50, p.y - 50);
      expect(d).toBeCloseTo(80.71, 1);
    }
  });

  it('delta<0 → 內縮', () => {
    const out = polygonWithInflate(SQUARE, -10);
    for (const p of out) {
      const d = Math.hypot(p.x - 50, p.y - 50);
      expect(d).toBeCloseTo(60.71, 1);
    }
  });

  it('空 polygon → 空 polygon', () => {
    expect(polygonWithInflate([], 10)).toEqual([]);
  });

  it('vertex 在 bbox center → 不動（dist=0 跳過 scale）', () => {
    const single = [{ x: 50, y: 50 }];
    expect(polygonWithInflate(single, 10)).toEqual(single);
  });
});
