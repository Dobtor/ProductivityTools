/**
 * OverlayAccessibilityAnnotator — Sprint 341。
 *
 * Sprint 291/295/301/306/311/316/321/326/331/336 overlay 系列第十輪深推。
 * 現有 overlay 都是視覺/位置/鍵盤/手勢；本 sprint 補 **a11y annotation**：
 *
 *   - 給定當前 selection state（多選 / 含 image / 含 textbox） → 推 aria-label / role
 *   - 給定 keyboard command → 推 caller-friendly announcement text（screen reader 用）
 *   - 給定 overlay item shape → 推 role + aria-describedby hint
 *
 * 紀律 #18 scope-down：
 *   - 純函式 transform、不接 DOM ARIA attribute（caller 接到 element）
 *   - 不做 i18n（caller 自包 lang）；本 module 純英文 hint
 *   - 不接 doc_editor.js OWL real path（紀律 #21）
 *
 * 紀律 #21：pure-fn；不污染 doc_editor.js / overlay render path。
 */

import type { OverlayCommand } from './OverlayKeyboardCommands';

export type OverlayItemKind = 'text-frame' | 'image' | 'shape' | 'group' | 'unknown';

export interface OverlayItemForA11y {
  id: string;
  kind: OverlayItemKind;
  /** 對使用者顯示的 label（例："Diagram 3", "Image"） */
  label?: string;
}

export interface SelectionStateForA11y {
  selectedItems: ReadonlyArray<OverlayItemForA11y>;
}

export interface AriaAttributes {
  role: string;
  'aria-label': string;
  'aria-describedby'?: string;
}

/**
 * Selection state → overlay container 的 ARIA attribute。
 *
 * 規則：
 *   - 0 selection → role='application'、label = 'No selection'
 *   - 1 selection → role='img'/'figure'/'group'/... 視 kind、label 帶 item label
 *   - 多 selection → role='group'、label = "Multiple selection: N items"
 */
export function ariaForSelection(state: SelectionStateForA11y): AriaAttributes {
  const items = state.selectedItems;
  if (items.length === 0) {
    return { role: 'application', 'aria-label': 'No selection' };
  }
  if (items.length === 1) {
    const it = items[0];
    return {
      role: roleForItemKind(it.kind),
      'aria-label': labelForItem(it),
    };
  }
  return {
    role: 'group',
    'aria-label': `Multiple selection: ${items.length} items`,
  };
}

function roleForItemKind(kind: OverlayItemKind): string {
  switch (kind) {
    case 'image':
      return 'img';
    case 'text-frame':
      return 'textbox';
    case 'shape':
      return 'figure';
    case 'group':
      return 'group';
    default:
      return 'application';
  }
}

function labelForItem(it: OverlayItemForA11y): string {
  if (it.label) return it.label;
  switch (it.kind) {
    case 'image':
      return 'Image';
    case 'text-frame':
      return 'Text frame';
    case 'shape':
      return 'Shape';
    case 'group':
      return 'Group';
    default:
      return 'Item';
  }
}

/**
 * 把 overlay item 自己也加 ARIA（caller 走 forEach item 套到對應 DOM 元素用）。
 */
export function ariaForItem(item: OverlayItemForA11y): AriaAttributes {
  return {
    role: roleForItemKind(item.kind),
    'aria-label': labelForItem(item),
  };
}

/**
 * Keyboard command → screen reader announcement text。
 *
 * 紀律 #18：純文字、caller 自負 i18n。
 */
export function announcementForCommand(command: OverlayCommand): string {
  switch (command.kind) {
    case 'delete':
      return 'Deleted selection';
    case 'nudge':
      return `Moved by ${command.dx}, ${command.dy}`;
    case 'select-all':
      return 'Selected all';
    case 'clear-selection':
      return 'Cleared selection';
    case 'copy':
      return 'Copied selection';
    case 'cut':
      return 'Cut selection';
    case 'paste':
      return 'Pasted from clipboard';
    case 'undo':
      return 'Undo';
    case 'redo':
      return 'Redo';
    case 'duplicate':
      return 'Duplicated selection';
    case 'noop':
      return '';
  }
}

/**
 * 給整批 selection 算 summary（caller 想顯示 live region 用）。
 */
export interface SelectionA11ySummary {
  count: number;
  hasImage: boolean;
  hasTextFrame: boolean;
  hasShape: boolean;
  description: string;
}

export function summarizeSelectionA11y(state: SelectionStateForA11y): SelectionA11ySummary {
  const counts = { image: 0, textFrame: 0, shape: 0, group: 0, unknown: 0 };
  for (const it of state.selectedItems) {
    if (it.kind === 'image') counts.image += 1;
    else if (it.kind === 'text-frame') counts.textFrame += 1;
    else if (it.kind === 'shape') counts.shape += 1;
    else if (it.kind === 'group') counts.group += 1;
    else counts.unknown += 1;
  }
  const parts: string[] = [];
  if (counts.image) parts.push(`${counts.image} image${counts.image > 1 ? 's' : ''}`);
  if (counts.textFrame) parts.push(`${counts.textFrame} text frame${counts.textFrame > 1 ? 's' : ''}`);
  if (counts.shape) parts.push(`${counts.shape} shape${counts.shape > 1 ? 's' : ''}`);
  if (counts.group) parts.push(`${counts.group} group${counts.group > 1 ? 's' : ''}`);
  const description =
    state.selectedItems.length === 0
      ? 'No selection'
      : `Selected: ${parts.join(', ') || `${state.selectedItems.length} items`}`;
  return {
    count: state.selectedItems.length,
    hasImage: counts.image > 0,
    hasTextFrame: counts.textFrame > 0,
    hasShape: counts.shape > 0,
    description,
  };
}
