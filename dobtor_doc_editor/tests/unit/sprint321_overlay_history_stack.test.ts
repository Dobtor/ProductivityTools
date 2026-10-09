/**
 * Sprint 321 — ⑤ deeper⁵：OverlayHistoryStack。
 *
 * Sprint 291/295/301/306/311/316 之後深推。Undo/redo 棧。
 *
 * 紀律 #18 scope-down：不接 doc_editor.js OWL real path（紀律 #21）；不持久化；
 *   不做 transaction batch；payload 為 caller-defined。
 */
import { describe, expect, it, vi } from 'vitest';

import {
  OverlayHistoryStack,
  type HistoryEntry,
  type HistoryEvent,
} from '../../static/src/components/doc_editor/OverlayHistoryStack';

interface MovePayload {
  kind: 'move';
  id: string;
  before: { x: number; y: number };
  after: { x: number; y: number };
}

function mkMove(id: string, fromX: number, fromY: number, toX: number, toY: number): HistoryEntry<MovePayload> {
  return {
    payload: { kind: 'move', id, before: { x: fromX, y: fromY }, after: { x: toX, y: toY } },
    label: `Move ${id}`,
  };
}

// ── 初始狀態 + push ──────────────────────────────────────────────────

describe('Sprint 321 — push 與初始狀態', () => {
  it('初始：canUndo=false canRedo=false size=0', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    expect(stack.canUndo()).toBe(false);
    expect(stack.canRedo()).toBe(false);
    expect(stack.size()).toBe(0);
  });

  it('push 後 canUndo=true canRedo=false', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('img1', 0, 0, 10, 10));
    expect(stack.canUndo()).toBe(true);
    expect(stack.canRedo()).toBe(false);
    expect(stack.size()).toBe(1);
  });
});

// ── undo / redo cycle ──────────────────────────────────────────────

describe('Sprint 321 — undo / redo cycle', () => {
  it('push x 2 → undo → undo → redo', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('a', 0, 0, 5, 5));
    stack.push(mkMove('a', 5, 5, 10, 10));

    const u1 = stack.undo();
    expect(u1?.payload.after).toEqual({ x: 10, y: 10 });
    expect(stack.canUndo()).toBe(true);
    expect(stack.canRedo()).toBe(true);

    const u2 = stack.undo();
    expect(u2?.payload.after).toEqual({ x: 5, y: 5 });
    expect(stack.canUndo()).toBe(false);

    const r1 = stack.redo();
    expect(r1?.payload.after).toEqual({ x: 5, y: 5 });
    expect(stack.canUndo()).toBe(true);
  });

  it('無可 undo → undefined', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    expect(stack.undo()).toBeUndefined();
  });

  it('無可 redo → undefined', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('a', 0, 0, 5, 5));
    expect(stack.redo()).toBeUndefined();
  });
});

// ── push 後 cursor 不在末端 → 丟棄 redo 後段 ────────────────────────

describe('Sprint 321 — push 丟棄 redo 路徑', () => {
  it('undo 後 push → 後續 redo 應為空', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('a', 0, 0, 5, 5));
    stack.push(mkMove('a', 5, 5, 10, 10));
    stack.undo(); // cursor=1, can redo
    stack.push(mkMove('a', 5, 5, 20, 20)); // 丟棄 redo
    expect(stack.canRedo()).toBe(false);
    expect(stack.size()).toBe(2);  // a→(5,5) + a→(20,20)
  });
});

// ── maxEntries eviction ────────────────────────────────────────────

describe('Sprint 321 — maxEntries eviction', () => {
  it('超過 maxEntries → evict 最舊', () => {
    const stack = new OverlayHistoryStack<MovePayload>({ maxEntries: 2 });
    stack.push(mkMove('a', 0, 0, 1, 1));
    stack.push(mkMove('a', 1, 1, 2, 2));
    stack.push(mkMove('a', 2, 2, 3, 3));
    expect(stack.size()).toBe(2);
    // 最舊（a 0→1）已 evict、剩 (1→2) + (2→3)
    const u = stack.undo();
    expect(u?.payload.after).toEqual({ x: 3, y: 3 });
  });
});

// ── peek ──────────────────────────────────────────────────────────

describe('Sprint 321 — peekUndo / peekRedo', () => {
  it('peek 不移動 cursor', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('a', 0, 0, 5, 5));
    stack.push(mkMove('a', 5, 5, 10, 10));
    stack.undo();

    expect(stack.peekUndo()?.payload.after).toEqual({ x: 5, y: 5 });
    expect(stack.peekRedo()?.payload.after).toEqual({ x: 10, y: 10 });
    // cursor 沒動
    expect(stack.canUndo()).toBe(true);
    expect(stack.canRedo()).toBe(true);
  });

  it('peek 空 stack → undefined', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    expect(stack.peekUndo()).toBeUndefined();
    expect(stack.peekRedo()).toBeUndefined();
  });
});

// ── clear ──────────────────────────────────────────────────────────

describe('Sprint 321 — clear', () => {
  it('clear 後 size=0、canUndo/Redo 全 false', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.push(mkMove('a', 0, 0, 5, 5));
    stack.clear();
    expect(stack.size()).toBe(0);
    expect(stack.canUndo()).toBe(false);
    expect(stack.canRedo()).toBe(false);
  });
});

// ── subscribe listener ─────────────────────────────────────────────

describe('Sprint 321 — subscribe events', () => {
  it('push / undo / redo / clear 各 emit 一次', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    const events: HistoryEvent<MovePayload>[] = [];
    stack.subscribe((e) => events.push(e));
    stack.push(mkMove('a', 0, 0, 5, 5));
    stack.undo();
    stack.redo();
    stack.clear();
    expect(events.map((e) => e.kind)).toEqual(['push', 'undo', 'redo', 'clear']);
  });

  it('unsubscribe 後不再收', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    const fn = vi.fn();
    const unsub = stack.subscribe(fn);
    stack.push(mkMove('a', 0, 0, 5, 5));
    unsub();
    stack.push(mkMove('b', 0, 0, 5, 5));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('listener throw 不影響其他', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    stack.subscribe(() => { throw new Error('boom'); });
    const good = vi.fn();
    stack.subscribe(good);
    stack.push(mkMove('a', 0, 0, 5, 5));
    expect(good).toHaveBeenCalledOnce();
  });
});

// ── position ──────────────────────────────────────────────────────

describe('Sprint 321 — position', () => {
  it('cursor 位置反映 push/undo/redo', () => {
    const stack = new OverlayHistoryStack<MovePayload>();
    expect(stack.position()).toBe(0);
    stack.push(mkMove('a', 0, 0, 5, 5));
    expect(stack.position()).toBe(1);
    stack.push(mkMove('a', 5, 5, 10, 10));
    expect(stack.position()).toBe(2);
    stack.undo();
    expect(stack.position()).toBe(1);
    stack.redo();
    expect(stack.position()).toBe(2);
  });
});
