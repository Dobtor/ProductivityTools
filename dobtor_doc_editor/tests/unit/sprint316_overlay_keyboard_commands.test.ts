/**
 * Sprint 316 — ⑤ deeper⁴：OverlayKeyboardCommands。
 *
 * Sprint 291/295/301/306/311 之後第四輪深推。Pure-fn key event → overlay command。
 *
 * 紀律 #18 scope-down：不接 doc_editor.js OWL real path（紀律 #21、同政策）。
 */
import { describe, expect, it } from 'vitest';

import {
  mapKeyToCommand,
  type KeyEventLike,
} from '../../static/src/components/doc_editor/OverlayKeyboardCommands';

const mac = { platform: 'mac' as const };
const pc = { platform: 'pc' as const };
const sel = { hasSelection: true };
const noSel = { hasSelection: false };

// ── delete / backspace ────────────────────────────────────────────────

describe('Sprint 316 — delete', () => {
  it('Backspace + selection → delete', () => {
    expect(mapKeyToCommand({ key: 'Backspace' }, { ...mac, ...sel })).toEqual({ kind: 'delete' });
  });

  it('Delete + selection → delete', () => {
    expect(mapKeyToCommand({ key: 'Delete' }, { ...pc, ...sel })).toEqual({ kind: 'delete' });
  });

  it('Backspace 無 selection → noop', () => {
    expect(mapKeyToCommand({ key: 'Backspace' }, { ...mac, ...noSel })).toEqual({ kind: 'noop' });
  });
});

// ── nudge ────────────────────────────────────────────────────────────

describe('Sprint 316 — nudge', () => {
  it('ArrowLeft → dx=-1', () => {
    expect(mapKeyToCommand({ key: 'ArrowLeft' }, { ...mac, ...sel })).toEqual({ kind: 'nudge', dx: -1, dy: 0 });
  });

  it('ArrowRight + Shift → big step dx=10', () => {
    expect(mapKeyToCommand({ key: 'ArrowRight', shiftKey: true }, { ...mac, ...sel })).toEqual({
      kind: 'nudge', dx: 10, dy: 0,
    });
  });

  it('ArrowUp → dy=-1', () => {
    expect(mapKeyToCommand({ key: 'ArrowUp' }, { ...mac, ...sel })).toEqual({ kind: 'nudge', dx: 0, dy: -1 });
  });

  it('ArrowDown + Shift → dy=10', () => {
    expect(mapKeyToCommand({ key: 'ArrowDown', shiftKey: true }, { ...mac, ...sel })).toEqual({
      kind: 'nudge', dx: 0, dy: 10,
    });
  });

  it('custom step sizes', () => {
    expect(mapKeyToCommand({ key: 'ArrowRight' }, { ...mac, ...sel, nudgeSmall: 2 })).toEqual({
      kind: 'nudge', dx: 2, dy: 0,
    });
    expect(mapKeyToCommand({ key: 'ArrowRight', shiftKey: true }, { ...mac, ...sel, nudgeBig: 50 })).toEqual({
      kind: 'nudge', dx: 50, dy: 0,
    });
  });

  it('Arrow 無 selection → noop', () => {
    expect(mapKeyToCommand({ key: 'ArrowLeft' }, { ...mac, ...noSel })).toEqual({ kind: 'noop' });
  });
});

// ── select-all / escape ──────────────────────────────────────────────

describe('Sprint 316 — select-all / clear-selection', () => {
  it('Mac Cmd+A → select-all', () => {
    expect(mapKeyToCommand({ key: 'a', metaKey: true }, { ...mac, ...noSel })).toEqual({ kind: 'select-all' });
  });

  it('PC Ctrl+A → select-all', () => {
    expect(mapKeyToCommand({ key: 'a', ctrlKey: true }, { ...pc, ...noSel })).toEqual({ kind: 'select-all' });
  });

  it('Mac Ctrl+A（沒按 Cmd）→ noop（不是 Mac modifier）', () => {
    expect(mapKeyToCommand({ key: 'a', ctrlKey: true }, { ...mac, ...noSel })).toEqual({ kind: 'noop' });
  });

  it('Escape → clear-selection', () => {
    expect(mapKeyToCommand({ key: 'Escape' }, { ...mac, ...sel })).toEqual({ kind: 'clear-selection' });
  });
});

// ── copy / cut / paste ───────────────────────────────────────────────

describe('Sprint 316 — copy / cut / paste', () => {
  it('Mod+C + selection → copy', () => {
    expect(mapKeyToCommand({ key: 'c', metaKey: true }, { ...mac, ...sel })).toEqual({ kind: 'copy' });
  });

  it('Mod+X + selection → cut', () => {
    expect(mapKeyToCommand({ key: 'x', ctrlKey: true }, { ...pc, ...sel })).toEqual({ kind: 'cut' });
  });

  it('Mod+V（即使無 selection）→ paste', () => {
    expect(mapKeyToCommand({ key: 'v', metaKey: true }, { ...mac, ...noSel })).toEqual({ kind: 'paste' });
  });

  it('Mod+C 無 selection → noop', () => {
    expect(mapKeyToCommand({ key: 'c', metaKey: true }, { ...mac, ...noSel })).toEqual({ kind: 'noop' });
  });
});

// ── undo / redo / duplicate ──────────────────────────────────────────

describe('Sprint 316 — undo / redo / duplicate', () => {
  it('Mod+Z → undo', () => {
    expect(mapKeyToCommand({ key: 'z', metaKey: true }, { ...mac, ...sel })).toEqual({ kind: 'undo' });
  });

  it('Mod+Shift+Z → redo', () => {
    expect(mapKeyToCommand({ key: 'z', metaKey: true, shiftKey: true }, { ...mac, ...sel })).toEqual({ kind: 'redo' });
  });

  it('Mod+D + selection → duplicate', () => {
    expect(mapKeyToCommand({ key: 'd', metaKey: true }, { ...mac, ...sel })).toEqual({ kind: 'duplicate' });
  });

  it('Mod+D 無 selection → noop', () => {
    expect(mapKeyToCommand({ key: 'd', metaKey: true }, { ...mac, ...noSel })).toEqual({ kind: 'noop' });
  });
});

// ── unknown key ──────────────────────────────────────────────────────

describe('Sprint 316 — unknown key', () => {
  it('普通字母無 Mod → noop', () => {
    expect(mapKeyToCommand({ key: 'q' }, { ...mac, ...sel })).toEqual({ kind: 'noop' });
  });

  it('Mod+不識別字 → noop', () => {
    expect(mapKeyToCommand({ key: 'q', metaKey: true }, { ...mac, ...sel })).toEqual({ kind: 'noop' });
  });
});
