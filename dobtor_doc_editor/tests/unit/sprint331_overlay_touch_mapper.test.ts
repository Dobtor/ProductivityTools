/**
 * Sprint 331 — ⑤ deeper⁸：OverlayTouchMapper。
 *
 * Sprint 291/295/301/306/311/316/321/326 overlay 系列第八輪深推。
 * Touch / pointer gesture → OverlayCommand pure-fn mapping。
 *
 * 紀律 #18：pure-fn、不接 DOM PointerEvent、不接 doc_editor.js real path。
 */
import { describe, expect, it } from 'vitest';

import {
  classifyTap,
  recognizePinch,
  mapGestureToCommand,
  createGestureStats,
  recordGesture,
  type PointerSnapshot,
} from '../../static/src/components/doc_editor/OverlayTouchMapper';

// ── classifyTap ────────────────────────────────────────────────────

describe('Sprint 331 — classifyTap', () => {
  it('短時間、小距離 → tap', () => {
    expect(classifyTap(100, 2)).toBe('tap');
  });

  it('時間長 → long-press', () => {
    expect(classifyTap(700, 2)).toBe('long-press');
  });

  it('移動超過 threshold → drag', () => {
    expect(classifyTap(100, 20)).toBe('drag');
  });

  it('drag 優先於 long-press', () => {
    expect(classifyTap(700, 20)).toBe('drag');
  });

  it('caller-defined longPressMs / dragThreshold', () => {
    expect(classifyTap(300, 2, { longPressMs: 200 })).toBe('long-press');
    expect(classifyTap(100, 5, { dragThreshold: 3 })).toBe('drag');
  });
});

// ── recognizePinch ─────────────────────────────────────────────────

describe('Sprint 331 — recognizePinch', () => {
  const p = (id: number, x: number, y: number): PointerSnapshot => ({ id, x, y, timestamp: 0 });

  it('放大 → scale > 1', () => {
    const start = [p(1, 0, 0), p(2, 10, 0)];
    const end = [p(1, 0, 0), p(2, 20, 0)];
    const r = recognizePinch(start, end);
    expect(r?.scale).toBe(2);
    expect(r?.dx).toBe(5); // center start=(5,0)、end=(10,0)
  });

  it('縮小 → scale < 1', () => {
    const start = [p(1, 0, 0), p(2, 20, 0)];
    const end = [p(1, 0, 0), p(2, 10, 0)];
    const r = recognizePinch(start, end);
    expect(r?.scale).toBe(0.5);
  });

  it('不是 2 指 → null', () => {
    expect(recognizePinch([p(1, 0, 0)], [p(1, 0, 0)])).toBeNull();
    expect(recognizePinch([p(1, 0, 0), p(2, 5, 0), p(3, 10, 0)], [p(1, 0, 0)])).toBeNull();
  });

  it('起始距離 0 → null', () => {
    expect(recognizePinch([p(1, 0, 0), p(2, 0, 0)], [p(1, 0, 0), p(2, 5, 5)])).toBeNull();
  });

  it('中心點漂移 dx/dy 正確', () => {
    const start = [p(1, 0, 0), p(2, 10, 10)];
    const end = [p(1, 10, 10), p(2, 20, 20)];
    const r = recognizePinch(start, end);
    expect(r?.dx).toBe(10);
    expect(r?.dy).toBe(10);
  });
});

// ── mapGestureToCommand ────────────────────────────────────────────

describe('Sprint 331 — mapGestureToCommand', () => {
  it('tap → noop（select-at-point 由 caller 自決）', () => {
    expect(mapGestureToCommand('tap', { hasSelection: true })).toEqual({ kind: 'noop' });
    expect(mapGestureToCommand('tap', { hasSelection: false })).toEqual({ kind: 'noop' });
  });

  it('long-press + hasSelection → duplicate（default）', () => {
    expect(mapGestureToCommand('long-press', { hasSelection: true })).toEqual({
      kind: 'duplicate',
    });
  });

  it('long-press + 無 selection → noop', () => {
    expect(mapGestureToCommand('long-press', { hasSelection: false })).toEqual({ kind: 'noop' });
  });

  it('long-press + copy 設定 → copy', () => {
    expect(
      mapGestureToCommand('long-press', { hasSelection: true, longPressCommand: 'copy' }),
    ).toEqual({ kind: 'copy' });
  });

  it('long-press + noop 設定 → noop', () => {
    expect(
      mapGestureToCommand('long-press', { hasSelection: true, longPressCommand: 'noop' }),
    ).toEqual({ kind: 'noop' });
  });

  it('two-finger-drag + nudge 設定 → nudge', () => {
    expect(
      mapGestureToCommand('two-finger-drag', {
        hasSelection: true,
        twoFingerDragNudge: { dx: 5, dy: -3 },
      }),
    ).toEqual({ kind: 'nudge', dx: 5, dy: -3 });
  });

  it('drag / pinch / unknown → noop（caller 自處理）', () => {
    expect(mapGestureToCommand('drag', { hasSelection: true })).toEqual({ kind: 'noop' });
    expect(mapGestureToCommand('pinch', { hasSelection: true })).toEqual({ kind: 'noop' });
    expect(mapGestureToCommand('unknown', { hasSelection: true })).toEqual({ kind: 'noop' });
  });
});

// ── GestureStats ───────────────────────────────────────────────────

describe('Sprint 331 — gesture stats', () => {
  it('record 各 gesture → 計數累加', () => {
    const s = createGestureStats();
    recordGesture(s, 'tap');
    recordGesture(s, 'tap');
    recordGesture(s, 'long-press');
    recordGesture(s, 'drag');
    recordGesture(s, 'pinch');
    recordGesture(s, 'two-finger-drag');
    expect(s.taps).toBe(2);
    expect(s.longPresses).toBe(1);
    expect(s.drags).toBe(1);
    expect(s.pinches).toBe(1);
    expect(s.twoFingerDrags).toBe(1);
  });

  it('unknown gesture → 不累加', () => {
    const s = createGestureStats();
    recordGesture(s, 'unknown');
    expect(s.taps).toBe(0);
  });
});
