/**
 * Sprint 326 — ⑤ deeper⁶：OverlayCommandExecutor。
 *
 * Sprint 311 selection + Sprint 316 keyboard + Sprint 321 history 三者整合。
 *
 * 紀律 #18 scope-down：不接 real path（紀律 #21）；caller 自負 apply。
 */
import { describe, expect, it } from 'vitest';

import { OverlayCommandExecutor } from '../../static/src/components/doc_editor/OverlayCommandExecutor';
import { OverlaySelectionState } from '../../static/src/components/doc_editor/OverlaySelectionState';
import { OverlayHistoryStack } from '../../static/src/components/doc_editor/OverlayHistoryStack';

interface MovePayload {
  kind: string;
  ids: string[];
  dx?: number;
  dy?: number;
}

function mkExecutor(opts: {
  preselected?: string[];
  recordPayloads?: boolean;
  platform?: 'mac' | 'pc';
} = {}) {
  const selection = new OverlaySelectionState();
  if (opts.preselected) selection.replaceAll(opts.preselected);
  const history = new OverlayHistoryStack<MovePayload>();
  const platform = opts.platform ?? 'mac';
  const payloadFactory = opts.recordPayloads
    ? (cmd: { kind: string; dx?: number; dy?: number }, ids: readonly string[]) =>
        cmd.kind === 'nudge' || cmd.kind === 'delete' || cmd.kind === 'duplicate'
          ? ({ kind: cmd.kind, ids: [...ids], dx: cmd.dx, dy: cmd.dy })
          : null
    : undefined;
  const executor = new OverlayCommandExecutor<MovePayload>({
    selection, history, platform, payloadFactory,
  });
  return { executor, selection, history };
}

// ── handleKey 基本 dispatch ──────────────────────────────────────────

describe('Sprint 326 — handleKey dispatch', () => {
  it('Backspace + selection → apply delete', () => {
    const { executor } = mkExecutor({ preselected: ['a'] });
    const action = executor.handleKey({ key: 'Backspace' });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.command.kind).toBe('delete');
  });

  it('Backspace 無 selection → noop', () => {
    const { executor } = mkExecutor();
    expect(executor.handleKey({ key: 'Backspace' }).kind).toBe('noop');
  });

  it('Arrow key → apply nudge', () => {
    const { executor } = mkExecutor({ preselected: ['a'] });
    const action = executor.handleKey({ key: 'ArrowRight' });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply' && action.command.kind === 'nudge') {
      expect(action.command.dx).toBe(1);
    }
  });
});

// ── clear-selection 自動處理 SelectionState ─────────────────────────

describe('Sprint 326 — clear-selection 自動執行', () => {
  it('Escape → executor 自動 clear、selection.size=0', () => {
    const { executor, selection } = mkExecutor({ preselected: ['a', 'b'] });
    executor.handleKey({ key: 'Escape' });
    expect(selection.size()).toBe(0);
  });
});

// ── undo / redo autoHandleUndoRedo ─────────────────────────────────

describe('Sprint 326 — undo / redo 自動處理', () => {
  it('Mod+Z + history 有 entry → apply-from-history', () => {
    const { executor, history } = mkExecutor({ preselected: ['a'] });
    history.push({ payload: { kind: 'move', ids: ['a'], dx: 5, dy: 0 } });
    const action = executor.handleKey({ key: 'z', metaKey: true });
    expect(action.kind).toBe('apply-from-history');
    if (action.kind === 'apply-from-history') {
      expect(action.direction).toBe('undo');
      expect(action.entry.payload.ids).toEqual(['a']);
    }
  });

  it('Mod+Z + history 空 → noop', () => {
    const { executor } = mkExecutor({ preselected: ['a'] });
    expect(executor.handleKey({ key: 'z', metaKey: true }).kind).toBe('noop');
  });

  it('Mod+Shift+Z → redo direction', () => {
    const { executor, history } = mkExecutor({ preselected: ['a'] });
    history.push({ payload: { kind: 'move', ids: ['a'] } });
    history.undo();
    const action = executor.handleKey({ key: 'z', metaKey: true, shiftKey: true });
    expect(action.kind).toBe('apply-from-history');
    if (action.kind === 'apply-from-history') expect(action.direction).toBe('redo');
  });
});

// ── payloadFactory 自動 push history ──────────────────────────────

describe('Sprint 326 — payloadFactory 自動 push history', () => {
  it('nudge 有 payloadFactory → recordable=true、history.size 增加', () => {
    const { executor, history } = mkExecutor({ preselected: ['x'], recordPayloads: true });
    const before = history.size();
    const action = executor.handleKey({ key: 'ArrowDown' });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.recordable).toBe(true);
    expect(history.size()).toBe(before + 1);
  });

  it('payloadFactory 回 null → 不 push、recordable=false', () => {
    const selection = new OverlaySelectionState();
    selection.replaceAll(['a']);
    const history = new OverlayHistoryStack<MovePayload>();
    const executor = new OverlayCommandExecutor<MovePayload>({
      selection, history, platform: 'mac',
      payloadFactory: () => null,
    });
    const action = executor.handleKey({ key: 'ArrowLeft' });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.recordable).toBe(false);
    expect(history.size()).toBe(0);
  });

  it('沒 payloadFactory → 不 push', () => {
    const { executor, history } = mkExecutor({ preselected: ['a'], recordPayloads: false });
    executor.handleKey({ key: 'ArrowUp' });
    expect(history.size()).toBe(0);
  });
});

// ── recordToHistory 外部觸發 ─────────────────────────────────────

describe('Sprint 326 — recordToHistory 外部觸發', () => {
  it('caller 直接 push（如滑鼠拖曳完成後）', () => {
    const { executor, history } = mkExecutor();
    executor.recordToHistory({ payload: { kind: 'drag', ids: ['x'] } });
    expect(history.size()).toBe(1);
  });
});

// ── platform 差異 ──────────────────────────────────────────────

describe('Sprint 326 — platform 差異', () => {
  it('Mac Cmd+A → select-all', () => {
    const { executor } = mkExecutor({ platform: 'mac' });
    const action = executor.handleKey({ key: 'a', metaKey: true });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.command.kind).toBe('select-all');
  });

  it('PC Ctrl+A → select-all', () => {
    const { executor } = mkExecutor({ platform: 'pc' });
    const action = executor.handleKey({ key: 'a', ctrlKey: true });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.command.kind).toBe('select-all');
  });

  it('Mac Ctrl+A（Cmd 未按）→ noop', () => {
    const { executor } = mkExecutor({ platform: 'mac' });
    expect(executor.handleKey({ key: 'a', ctrlKey: true }).kind).toBe('noop');
  });
});

// ── autoHandleUndoRedo=false 不自動處理 ──────────────────────────

describe('Sprint 326 — autoHandleUndoRedo=false', () => {
  it('Mod+Z 變成普通 apply command（caller 自己處理）', () => {
    const selection = new OverlaySelectionState();
    selection.replaceAll(['x']);
    const history = new OverlayHistoryStack<MovePayload>();
    history.push({ payload: { kind: 'move', ids: ['x'] } });
    const executor = new OverlayCommandExecutor<MovePayload>({
      selection, history, platform: 'mac',
      autoHandleUndoRedo: false,
    });
    const action = executor.handleKey({ key: 'z', metaKey: true });
    expect(action.kind).toBe('apply');
    if (action.kind === 'apply') expect(action.command.kind).toBe('undo');
    // history cursor 沒動（caller 自管）
    expect(history.position()).toBe(1);
  });
});
