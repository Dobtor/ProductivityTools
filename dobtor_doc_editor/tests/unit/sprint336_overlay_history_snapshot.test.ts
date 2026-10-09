/**
 * Sprint 336 — ⑤ deeper⁹：OverlayHistorySnapshot。
 *
 * Sprint 321 OverlayHistoryStack 之後深推。JSON-safe snapshot for cross-session
 * 持久化 / cross-tab sync / audit 使用。
 *
 * 紀律 #18：純資料 transform；payload generic、caller 自負 serializer。
 */
import { describe, expect, it } from 'vitest';

import {
  OVERLAY_HISTORY_SNAPSHOT_SCHEMA_VERSION,
  toHistorySnapshot,
  fromHistorySnapshot,
  truncateHistorySnapshot,
  countUndoable,
  countRedoable,
  summarizeHistorySnapshot,
} from '../../static/src/components/doc_editor/OverlayHistorySnapshot';

interface DemoPayload {
  kind: string;
  ids: string[];
}

const entry = (kind: string, label?: string) => ({
  payload: { kind, ids: ['x'] } as DemoPayload,
  ...(label !== undefined ? { label } : {}),
});

// ── toHistorySnapshot ─────────────────────────────────────────────

describe('Sprint 336 — toHistorySnapshot', () => {
  it('包成 v1 + caller now()', () => {
    const s = toHistorySnapshot([entry('move')], 1, {
      now: () => '2026-05-28T00:00:00.000Z',
    });
    expect(s.schemaVersion).toBe(OVERLAY_HISTORY_SNAPSHOT_SCHEMA_VERSION);
    expect(s.createdAt).toBe('2026-05-28T00:00:00.000Z');
    expect(s.entries).toHaveLength(1);
    expect(s.cursor).toBe(1);
  });

  it('未注入 now → ISO string', () => {
    const s = toHistorySnapshot([], 0);
    expect(s.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('cursor 超界 → clamp 到 [0, entries.length]', () => {
    const e = [entry('a'), entry('b')];
    expect(toHistorySnapshot(e, -5).cursor).toBe(0);
    expect(toHistorySnapshot(e, 99).cursor).toBe(2);
  });
});

// ── fromHistorySnapshot ───────────────────────────────────────────

describe('Sprint 336 — fromHistorySnapshot', () => {
  it('valid v1 → 原樣回', () => {
    const orig = toHistorySnapshot([entry('a', 'label')], 1, {
      now: () => '2026-05-28T00:00:00.000Z',
    });
    const parsed = fromHistorySnapshot<DemoPayload>(
      JSON.parse(JSON.stringify(orig)),
    );
    expect(parsed?.cursor).toBe(1);
    expect(parsed?.entries[0].label).toBe('label');
  });

  it('null / primitive → null', () => {
    expect(fromHistorySnapshot(null)).toBeNull();
    expect(fromHistorySnapshot(42)).toBeNull();
  });

  it('schemaVersion 不符 → null', () => {
    expect(
      fromHistorySnapshot({ schemaVersion: 2, createdAt: 'x', entries: [], cursor: 0 }),
    ).toBeNull();
  });

  it('entries 非 array → null', () => {
    expect(
      fromHistorySnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        cursor: 0,
        entries: 'oops',
      }),
    ).toBeNull();
  });

  it('cursor NaN / 負 / 超界 → null', () => {
    const mk = (cursor: unknown) => ({
      schemaVersion: 1,
      createdAt: 'x',
      cursor,
      entries: [{ payload: {} }],
    });
    expect(fromHistorySnapshot(mk(NaN))).toBeNull();
    expect(fromHistorySnapshot(mk(-1))).toBeNull();
    expect(fromHistorySnapshot(mk(5))).toBeNull();
  });

  it('entry 缺 payload → null', () => {
    expect(
      fromHistorySnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        cursor: 0,
        entries: [{ label: 'no payload' }],
      }),
    ).toBeNull();
  });

  it('entry label 非 string → null', () => {
    expect(
      fromHistorySnapshot({
        schemaVersion: 1,
        createdAt: 'x',
        cursor: 0,
        entries: [{ payload: {}, label: 42 }],
      }),
    ).toBeNull();
  });

  it('caller validator 失敗 → null', () => {
    const isDemo = (p: unknown): p is DemoPayload =>
      !!p && typeof p === 'object' && 'kind' in (p as object);
    const valid = {
      schemaVersion: 1,
      createdAt: 'x',
      cursor: 1,
      entries: [{ payload: { kind: 'move', ids: [] } }],
    };
    expect(fromHistorySnapshot<DemoPayload>(valid, isDemo)).not.toBeNull();

    const invalid = {
      schemaVersion: 1,
      createdAt: 'x',
      cursor: 1,
      entries: [{ payload: 'oops' }],
    };
    expect(fromHistorySnapshot<DemoPayload>(invalid, isDemo)).toBeNull();
  });
});

// ── truncateHistorySnapshot ───────────────────────────────────────

describe('Sprint 336 — truncateHistorySnapshot', () => {
  it('未超 max → 原樣回', () => {
    const s = toHistorySnapshot([entry('a'), entry('b')], 2);
    expect(truncateHistorySnapshot(s, 5).entries).toHaveLength(2);
  });

  it('超 max → 丟最舊、cursor 對齊前移', () => {
    const s = toHistorySnapshot([entry('a'), entry('b'), entry('c')], 3);
    const t = truncateHistorySnapshot(s, 2);
    expect(t.entries).toHaveLength(2);
    expect(t.entries[0].payload.kind).toBe('b');
    expect(t.cursor).toBe(2); // 3 - 1 dropped
  });

  it('cursor 不會 < 0', () => {
    const s = toHistorySnapshot([entry('a'), entry('b'), entry('c')], 1);
    const t = truncateHistorySnapshot(s, 2);
    expect(t.cursor).toBe(0);
  });

  it('maxEntries <= 0 throw', () => {
    const s = toHistorySnapshot([entry('a')], 1);
    expect(() => truncateHistorySnapshot(s, 0)).toThrow();
  });
});

// ── countUndoable / countRedoable ──────────────────────────────────

describe('Sprint 336 — count helpers', () => {
  it('cursor=2 → undoable=2、redoable=1', () => {
    const s = toHistorySnapshot([entry('a'), entry('b'), entry('c')], 2);
    expect(countUndoable(s)).toBe(2);
    expect(countRedoable(s)).toBe(1);
  });

  it('cursor=0 → 全 redoable', () => {
    const s = toHistorySnapshot([entry('a'), entry('b')], 0);
    expect(countUndoable(s)).toBe(0);
    expect(countRedoable(s)).toBe(2);
  });
});

// ── summarize ──────────────────────────────────────────────────────

describe('Sprint 336 — summarizeHistorySnapshot', () => {
  it('回 labels + undoable/redoable', () => {
    const s = toHistorySnapshot(
      [entry('a', 'Move'), entry('b', 'Delete'), entry('c')],
      2,
    );
    const sum = summarizeHistorySnapshot(s);
    expect(sum.totalEntries).toBe(3);
    expect(sum.undoable).toBe(2);
    expect(sum.redoable).toBe(1);
    expect(sum.labels).toEqual(['Move', 'Delete', '']);
  });
});
