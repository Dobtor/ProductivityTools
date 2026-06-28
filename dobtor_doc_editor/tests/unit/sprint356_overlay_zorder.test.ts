/**
 * Sprint 356 — ⑤ deeper¹³：OverlayZOrder。
 *
 * overlay item z-order 管理：bring-to-front / send-to-back / forward / backward。
 *
 * 紀律 #18：純 id 排序 model；caller 對應 relativeHeight；不接 doc_editor.js real path。
 */
import { describe, expect, it } from 'vitest';

import { OverlayZOrder } from '../../static/src/components/doc_editor/OverlayZOrder';

// ── constructor ────────────────────────────────────────────────────

describe('Sprint 356 — constructor', () => {
  it('初始 ids 保留順序', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    expect(z.orderedIds()).toEqual(['a', 'b', 'c']);
  });

  it('去重', () => {
    const z = new OverlayZOrder(['a', 'b', 'a']);
    expect(z.orderedIds()).toEqual(['a', 'b']);
  });

  it('空', () => {
    expect(new OverlayZOrder().size()).toBe(0);
  });
});

// ── add / remove ───────────────────────────────────────────────────

describe('Sprint 356 — add / remove', () => {
  it('add 到頂層', () => {
    const z = new OverlayZOrder(['a']);
    z.add('b');
    expect(z.orderedIds()).toEqual(['a', 'b']);
  });

  it('add 已存在 → no-op', () => {
    const z = new OverlayZOrder(['a', 'b']);
    z.add('a');
    expect(z.orderedIds()).toEqual(['a', 'b']);
  });

  it('remove 存在 → true', () => {
    const z = new OverlayZOrder(['a', 'b']);
    expect(z.remove('a')).toBe(true);
    expect(z.orderedIds()).toEqual(['b']);
  });

  it('remove 不存在 → false', () => {
    expect(new OverlayZOrder(['a']).remove('x')).toBe(false);
  });
});

// ── bringToFront / sendToBack ─────────────────────────────────────

describe('Sprint 356 — bringToFront / sendToBack', () => {
  it('bringToFront → 移到末端', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    z.bringToFront('a');
    expect(z.orderedIds()).toEqual(['b', 'c', 'a']);
  });

  it('sendToBack → 移到首', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    z.sendToBack('c');
    expect(z.orderedIds()).toEqual(['c', 'a', 'b']);
  });

  it('不存在 → false', () => {
    const z = new OverlayZOrder(['a']);
    expect(z.bringToFront('x')).toBe(false);
    expect(z.sendToBack('x')).toBe(false);
  });
});

// ── bringForward / sendBackward ───────────────────────────────────

describe('Sprint 356 — bringForward / sendBackward', () => {
  it('bringForward 上移一層', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    z.bringForward('a');
    expect(z.orderedIds()).toEqual(['b', 'a', 'c']);
  });

  it('bringForward 已在頂 → no-op、回 true', () => {
    const z = new OverlayZOrder(['a', 'b']);
    expect(z.bringForward('b')).toBe(true);
    expect(z.orderedIds()).toEqual(['a', 'b']);
  });

  it('sendBackward 下移一層', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    z.sendBackward('c');
    expect(z.orderedIds()).toEqual(['a', 'c', 'b']);
  });

  it('sendBackward 已在底 → no-op、回 true', () => {
    const z = new OverlayZOrder(['a', 'b']);
    expect(z.sendBackward('a')).toBe(true);
    expect(z.orderedIds()).toEqual(['a', 'b']);
  });

  it('不存在 → false', () => {
    const z = new OverlayZOrder(['a']);
    expect(z.bringForward('x')).toBe(false);
    expect(z.sendBackward('x')).toBe(false);
  });
});

// ── zIndexOf / normalize ──────────────────────────────────────────

describe('Sprint 356 — zIndexOf / normalize', () => {
  it('zIndexOf：0 = 最底', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    expect(z.zIndexOf('a')).toBe(0);
    expect(z.zIndexOf('c')).toBe(2);
  });

  it('zIndexOf 不存在 → -1', () => {
    expect(new OverlayZOrder(['a']).zIndexOf('x')).toBe(-1);
  });

  it('normalize → 0..n-1 連續', () => {
    const z = new OverlayZOrder(['a', 'b', 'c']);
    z.bringToFront('a'); // → b, c, a
    const m = z.normalize();
    expect(m.get('b')).toBe(0);
    expect(m.get('c')).toBe(1);
    expect(m.get('a')).toBe(2);
  });

  it('has', () => {
    const z = new OverlayZOrder(['a']);
    expect(z.has('a')).toBe(true);
    expect(z.has('x')).toBe(false);
  });
});

// ── 連續操作場景 ────────────────────────────────────────────────────

describe('Sprint 356 — 連續操作', () => {
  it('一系列 reorder 後順序正確', () => {
    const z = new OverlayZOrder(['a', 'b', 'c', 'd']);
    z.sendToBack('d'); // d a b c
    z.bringToFront('a'); // d b c a
    z.bringForward('b'); // d c b a
    expect(z.orderedIds()).toEqual(['d', 'c', 'b', 'a']);
  });
});
