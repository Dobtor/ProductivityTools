/**
 * Sprint 341 — ⑤ deeper¹⁰：OverlayAccessibilityAnnotator。
 *
 * Selection state / command → ARIA attribute / screen reader announcement。
 *
 * 紀律 #18：pure-fn；caller 自負 i18n；不接 DOM；不接 doc_editor.js real path。
 */
import { describe, expect, it } from 'vitest';

import {
  ariaForSelection,
  ariaForItem,
  announcementForCommand,
  summarizeSelectionA11y,
} from '../../static/src/components/doc_editor/OverlayAccessibilityAnnotator';

// ── ariaForSelection ───────────────────────────────────────────────

describe('Sprint 341 — ariaForSelection', () => {
  it('空 → application + No selection', () => {
    expect(ariaForSelection({ selectedItems: [] })).toEqual({
      role: 'application',
      'aria-label': 'No selection',
    });
  });

  it('1 image → role=img + label', () => {
    const a = ariaForSelection({
      selectedItems: [{ id: 'i1', kind: 'image', label: 'Diagram 3' }],
    });
    expect(a.role).toBe('img');
    expect(a['aria-label']).toBe('Diagram 3');
  });

  it('1 image 無 label → label="Image"', () => {
    const a = ariaForSelection({
      selectedItems: [{ id: 'i1', kind: 'image' }],
    });
    expect(a['aria-label']).toBe('Image');
  });

  it('1 text-frame → role=textbox', () => {
    expect(ariaForSelection({
      selectedItems: [{ id: 't1', kind: 'text-frame' }],
    }).role).toBe('textbox');
  });

  it('1 shape → role=figure', () => {
    expect(ariaForSelection({
      selectedItems: [{ id: 's1', kind: 'shape' }],
    }).role).toBe('figure');
  });

  it('1 group → role=group', () => {
    expect(ariaForSelection({
      selectedItems: [{ id: 'g1', kind: 'group' }],
    }).role).toBe('group');
  });

  it('1 unknown → role=application', () => {
    expect(ariaForSelection({
      selectedItems: [{ id: 'u1', kind: 'unknown' }],
    }).role).toBe('application');
  });

  it('多選 → group + 數量', () => {
    const a = ariaForSelection({
      selectedItems: [
        { id: 'a', kind: 'image' },
        { id: 'b', kind: 'shape' },
      ],
    });
    expect(a.role).toBe('group');
    expect(a['aria-label']).toBe('Multiple selection: 2 items');
  });
});

// ── ariaForItem ────────────────────────────────────────────────────

describe('Sprint 341 — ariaForItem', () => {
  it('image label override', () => {
    expect(ariaForItem({ id: 'i1', kind: 'image', label: 'Logo' })).toEqual({
      role: 'img',
      'aria-label': 'Logo',
    });
  });
});

// ── announcementForCommand ────────────────────────────────────────

describe('Sprint 341 — announcementForCommand', () => {
  it('delete', () => {
    expect(announcementForCommand({ kind: 'delete' })).toBe('Deleted selection');
  });
  it('nudge → 帶 dx/dy', () => {
    expect(announcementForCommand({ kind: 'nudge', dx: 5, dy: -3 })).toBe('Moved by 5, -3');
  });
  it('select-all / clear-selection', () => {
    expect(announcementForCommand({ kind: 'select-all' })).toBe('Selected all');
    expect(announcementForCommand({ kind: 'clear-selection' })).toBe('Cleared selection');
  });
  it('copy / cut / paste', () => {
    expect(announcementForCommand({ kind: 'copy' })).toBe('Copied selection');
    expect(announcementForCommand({ kind: 'cut' })).toBe('Cut selection');
    expect(announcementForCommand({ kind: 'paste' })).toBe('Pasted from clipboard');
  });
  it('undo / redo / duplicate', () => {
    expect(announcementForCommand({ kind: 'undo' })).toBe('Undo');
    expect(announcementForCommand({ kind: 'redo' })).toBe('Redo');
    expect(announcementForCommand({ kind: 'duplicate' })).toBe('Duplicated selection');
  });
  it('noop → 空 string', () => {
    expect(announcementForCommand({ kind: 'noop' })).toBe('');
  });
});

// ── summarizeSelectionA11y ─────────────────────────────────────────

describe('Sprint 341 — summarizeSelectionA11y', () => {
  it('空 → No selection', () => {
    const s = summarizeSelectionA11y({ selectedItems: [] });
    expect(s.count).toBe(0);
    expect(s.description).toBe('No selection');
  });

  it('mixed kinds → 描述含 plural', () => {
    const s = summarizeSelectionA11y({
      selectedItems: [
        { id: 'a', kind: 'image' },
        { id: 'b', kind: 'image' },
        { id: 'c', kind: 'text-frame' },
      ],
    });
    expect(s.count).toBe(3);
    expect(s.hasImage).toBe(true);
    expect(s.hasTextFrame).toBe(true);
    expect(s.hasShape).toBe(false);
    expect(s.description).toContain('2 images');
    expect(s.description).toContain('1 text frame');
  });

  it('1 shape 單數', () => {
    const s = summarizeSelectionA11y({
      selectedItems: [{ id: 's1', kind: 'shape' }],
    });
    expect(s.description).toContain('1 shape');
    expect(s.description).not.toContain('shapes');
  });
});
