/**
 * Sprint 346 — ⑤ deeper¹¹：OverlayClipboard。
 *
 * Sprint 316 keyboard copy/cut/paste command 之後補 clipboard buffer model。
 *
 * 紀律 #18：純記憶體；不接系統 clipboard API；不接 doc_editor.js real path。
 */
import { describe, expect, it } from 'vitest';

import { OverlayClipboard } from '../../static/src/components/doc_editor/OverlayClipboard';

interface Item {
  id: string;
}

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 346 — constructor', () => {
  it('pasteStep < 0 throw', () => {
    expect(() => new OverlayClipboard<Item>({ pasteStep: -1 })).toThrow();
  });
  it('default pasteStep = 10', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    expect(cb.paste()?.offset).toBe(10);
  });
});

// ── copy / paste ───────────────────────────────────────────────────

describe('Sprint 346 — copy / paste', () => {
  it('copy → paste 回 items + offset 遞增', () => {
    const cb = new OverlayClipboard<Item>({ pasteStep: 5 });
    cb.copy([{ id: 'a' }, { id: 'b' }]);
    const p1 = cb.paste();
    expect(p1?.items).toHaveLength(2);
    expect(p1?.pasteIndex).toBe(1);
    expect(p1?.offset).toBe(5);
    const p2 = cb.paste();
    expect(p2?.pasteIndex).toBe(2);
    expect(p2?.offset).toBe(10);
  });

  it('copy 模式 → isFirstCutPaste 永遠 false', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    expect(cb.paste()?.isFirstCutPaste).toBe(false);
    expect(cb.paste()?.isFirstCutPaste).toBe(false);
  });

  it('copy 後 sourceMode=copy', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    expect(cb.paste()?.sourceMode).toBe('copy');
  });

  it('copy 存的是 snapshot（caller 後續改 array 不影響）', () => {
    const cb = new OverlayClipboard<Item>();
    const arr = [{ id: 'a' }];
    cb.copy(arr);
    arr.push({ id: 'b' });
    expect(cb.paste()?.items).toHaveLength(1);
  });
});

// ── cut ────────────────────────────────────────────────────────────

describe('Sprint 346 — cut', () => {
  it('cut 第一次 paste → isFirstCutPaste=true', () => {
    const cb = new OverlayClipboard<Item>();
    cb.cut([{ id: 'a' }]);
    const p1 = cb.paste();
    expect(p1?.sourceMode).toBe('cut');
    expect(p1?.isFirstCutPaste).toBe(true);
  });

  it('cut 第二次 paste → isFirstCutPaste=false', () => {
    const cb = new OverlayClipboard<Item>();
    cb.cut([{ id: 'a' }]);
    cb.paste();
    expect(cb.paste()?.isFirstCutPaste).toBe(false);
  });
});

// ── empty ──────────────────────────────────────────────────────────

describe('Sprint 346 — empty buffer', () => {
  it('無內容 paste → null', () => {
    const cb = new OverlayClipboard<Item>();
    expect(cb.paste()).toBeNull();
  });

  it('hasContent 反映狀態', () => {
    const cb = new OverlayClipboard<Item>();
    expect(cb.hasContent()).toBe(false);
    cb.copy([{ id: 'a' }]);
    expect(cb.hasContent()).toBe(true);
  });
});

// ── peek / clear ───────────────────────────────────────────────────

describe('Sprint 346 — peek / clear', () => {
  it('peek 不影響 pasteCount', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    cb.peek();
    cb.peek();
    expect(cb.getStats().pasteCount).toBe(0);
  });

  it('peek 回 payload', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    expect(cb.peek()?.mode).toBe('copy');
  });

  it('clear → 清空 + paste 回 null', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    cb.clear();
    expect(cb.hasContent()).toBe(false);
    expect(cb.paste()).toBeNull();
  });
});

// ── 重新 copy 重置 pasteCount ──────────────────────────────────────

describe('Sprint 346 — 重新 copy/cut 重置 paste 階梯', () => {
  it('再次 copy → pasteCount 歸零', () => {
    const cb = new OverlayClipboard<Item>({ pasteStep: 10 });
    cb.copy([{ id: 'a' }]);
    cb.paste();
    cb.paste();
    cb.copy([{ id: 'b' }]);
    expect(cb.paste()?.offset).toBe(10); // 重置從 1 開始
  });

  it('cut 後 copy → cutConsumed 重置', () => {
    const cb = new OverlayClipboard<Item>();
    cb.cut([{ id: 'a' }]);
    cb.paste();
    cb.cut([{ id: 'b' }]);
    expect(cb.paste()?.isFirstCutPaste).toBe(true);
  });
});

// ── stats ──────────────────────────────────────────────────────────

describe('Sprint 346 — getStats', () => {
  it('累計 copy/cut/paste ops', () => {
    const cb = new OverlayClipboard<Item>();
    cb.copy([{ id: 'a' }]);
    cb.paste();
    cb.cut([{ id: 'b' }]);
    cb.paste();
    const s = cb.getStats();
    expect(s.copyOps).toBe(1);
    expect(s.cutOps).toBe(1);
    expect(s.pasteOps).toBe(2);
    expect(s.mode).toBe('cut');
    expect(s.itemCount).toBe(1);
  });
});
