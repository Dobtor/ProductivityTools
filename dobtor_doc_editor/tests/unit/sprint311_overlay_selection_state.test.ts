/**
 * Sprint 311 — ⑤ deeper³：OverlaySelectionState。
 *
 * Sprint 291/295/301/306 overlay 系列第三輪深推。Single + multi selection
 * 狀態機；caller 顯式呼叫 select/clear/replaceAll，emit listener events。
 *
 * 紀律 #18 scope-down：不接 doc_editor.js OWL real path（紀律 #21、同政策）。
 */
import { describe, expect, it, vi } from 'vitest';

import { OverlaySelectionState } from '../../static/src/components/doc_editor/OverlaySelectionState';

// ── 初始狀態 ─────────────────────────────────────────────────────────────

describe('Sprint 311 — 初始狀態', () => {
  it('剛建好 → size 0、hasSelection false、isSingle/isMulti false', () => {
    const sel = new OverlaySelectionState();
    expect(sel.size()).toBe(0);
    expect(sel.hasSelection()).toBe(false);
    expect(sel.isSingle()).toBe(false);
    expect(sel.isMulti()).toBe(false);
    expect(sel.getIds()).toEqual([]);
  });
});

// ── select 各 mode ──────────────────────────────────────────────────────

describe('Sprint 311 — select mode', () => {
  it('replace 取代當前 selection', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'replace');
    sel.select('b', 'replace');
    expect(sel.getIds()).toEqual(['b']);
    expect(sel.isSingle()).toBe(true);
  });

  it('toggle 已選 → 移除；未選 → 加入', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.select('a', 'toggle'); // remove
    expect(sel.has('a')).toBe(false);
    sel.select('a', 'toggle'); // add back
    expect(sel.has('a')).toBe(true);
  });

  it('add 加入（已在不變）', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.select('b', 'add');
    sel.select('a', 'add'); // already there
    expect(sel.size()).toBe(2);
    expect(sel.isMulti()).toBe(true);
  });

  it('remove 移除（不在不變）', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.select('z', 'remove'); // not in selection
    sel.select('a', 'remove');
    expect(sel.size()).toBe(0);
  });
});

// ── replaceAll / addAll / removeAll ─────────────────────────────────────

describe('Sprint 311 — bulk operations', () => {
  it('replaceAll 用一批 id 取代當前 selection', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.replaceAll(['x', 'y', 'z']);
    expect(sel.getIds().sort()).toEqual(['x', 'y', 'z']);
    expect(sel.isMulti()).toBe(true);
  });

  it('addAll 加入一批（保留現有）', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.addAll(['b', 'c']);
    expect(sel.getIds().sort()).toEqual(['a', 'b', 'c']);
  });

  it('removeAll 移除一批', () => {
    const sel = new OverlaySelectionState();
    sel.replaceAll(['a', 'b', 'c']);
    sel.removeAll(['a', 'c']);
    expect(sel.getIds()).toEqual(['b']);
  });
});

// ── clear ───────────────────────────────────────────────────────────────

describe('Sprint 311 — clear', () => {
  it('清空 selection、size 0', () => {
    const sel = new OverlaySelectionState();
    sel.replaceAll(['a', 'b']);
    const change = sel.clear();
    expect(sel.size()).toBe(0);
    expect(change.removed.sort()).toEqual(['a', 'b']);
    expect(change.added).toEqual([]);
  });

  it('清空後 hasSelection false', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    sel.clear();
    expect(sel.hasSelection()).toBe(false);
  });
});

// ── SelectionChange events ──────────────────────────────────────────────

describe('Sprint 311 — SelectionChange 事件', () => {
  it('subscribe listener 收到 added / removed', () => {
    const sel = new OverlaySelectionState();
    const log: Array<{ added: string[]; removed: string[] }> = [];
    sel.subscribe((change) => log.push({ added: [...change.added], removed: [...change.removed] }));
    sel.select('a', 'add');
    sel.select('a', 'toggle'); // remove a
    sel.replaceAll(['x', 'y']);
    expect(log).toEqual([
      { added: ['a'], removed: [] },
      { added: [], removed: ['a'] },
      { added: expect.arrayContaining(['x', 'y']), removed: [] },
    ]);
  });

  it('沒實際變動時不 emit', () => {
    const sel = new OverlaySelectionState();
    sel.select('a', 'add');
    const fn = vi.fn();
    sel.subscribe(fn);
    sel.select('a', 'add'); // 已在 selection、不 emit
    expect(fn).not.toHaveBeenCalled();
  });

  it('unsubscribe 後不再收', () => {
    const sel = new OverlaySelectionState();
    const fn = vi.fn();
    const unsub = sel.subscribe(fn);
    sel.select('a', 'add');
    unsub();
    sel.select('b', 'add');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('listener 拋錯不影響其他 listener', () => {
    const sel = new OverlaySelectionState();
    sel.subscribe(() => { throw new Error('boom'); });
    const good = vi.fn();
    sel.subscribe(good);
    sel.select('a', 'add');
    expect(good).toHaveBeenCalledOnce();
  });
});

// ── 邊界 ───────────────────────────────────────────────────────────────

describe('Sprint 311 — 邊界', () => {
  it('replaceAll([]) → clear-like 行為', () => {
    const sel = new OverlaySelectionState();
    sel.replaceAll(['a', 'b']);
    sel.replaceAll([]);
    expect(sel.size()).toBe(0);
  });

  it('replaceAll 含重複 id → 內部 dedup', () => {
    const sel = new OverlaySelectionState();
    sel.replaceAll(['a', 'a', 'b']);
    expect(sel.size()).toBe(2);
  });
});
