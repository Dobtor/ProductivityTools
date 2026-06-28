/**
 * OverlayHistorySnapshot — Sprint 336。
 *
 * Sprint 291/295/301/306/311/316/321/326/331 overlay 系列第九輪深推。Sprint 321
 * OverlayHistoryStack 是純記憶體；本 sprint 補 JSON-safe snapshot：
 *
 *   - caller 想跨 session 持久化 undo/redo 歷史（refresh / re-open doc 後恢復）
 *   - caller 想跨 tab 同步 history（postMessage payload）
 *   - caller 想 audit 「使用者執行了哪幾步」
 *
 * 紀律 #18 scope-down：
 *   - 純資料（payload 是 generic P、caller 自負 serializer/deserializer）
 *   - 不直接操作 OverlayHistoryStack internal（private cursor / entries）
 *     → caller 從外部組好 entries+cursor、用本 module 包成 JSON-safe
 *   - 不接 storage / postMessage / file system
 *
 * 紀律 #21：純函式 transform；不污染既有 doc_editor.js。
 */

export const OVERLAY_HISTORY_SNAPSHOT_SCHEMA_VERSION = 1;

export interface SerializedHistoryEntry<P> {
  payload: P;
  label?: string;
}

export interface OverlayHistorySnapshotV1<P> {
  schemaVersion: 1;
  /** ISO timestamp（caller 自選 timezone） */
  createdAt: string;
  /** entries 順序 = push 順序、最新的在 array 尾端 */
  entries: ReadonlyArray<SerializedHistoryEntry<P>>;
  /** cursor 指向「下一個要 push 的位置」、與 OverlayHistoryStack 同義 */
  cursor: number;
}

/**
 * 包成 v1 snapshot。createdAt 用 caller 注入 now() 否則用 new Date()。
 */
export function toHistorySnapshot<P>(
  entries: ReadonlyArray<SerializedHistoryEntry<P>>,
  cursor: number,
  options: { now?: () => string } = {},
): OverlayHistorySnapshotV1<P> {
  const safeCursor = Math.max(0, Math.min(cursor, entries.length));
  return {
    schemaVersion: OVERLAY_HISTORY_SNAPSHOT_SCHEMA_VERSION,
    createdAt: options.now ? options.now() : new Date().toISOString(),
    entries,
    cursor: safeCursor,
  };
}

/**
 * Reject 不認識 schema / 缺欄位 / payload 不通過 caller validator。回 null 不 throw。
 *
 * @param raw 任意 JSON.parse 後的值
 * @param isValidPayload caller 提供的 payload 型別檢查；未提供則信任 caller 自負
 */
export function fromHistorySnapshot<P>(
  raw: unknown,
  isValidPayload?: (p: unknown) => p is P,
): OverlayHistorySnapshotV1<P> | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  if (obj.schemaVersion !== OVERLAY_HISTORY_SNAPSHOT_SCHEMA_VERSION) return null;
  if (typeof obj.createdAt !== 'string') return null;
  if (typeof obj.cursor !== 'number' || !Number.isFinite(obj.cursor)) return null;
  if (!Array.isArray(obj.entries)) return null;

  for (const e of obj.entries) {
    if (!e || typeof e !== 'object') return null;
    const ent = e as Record<string, unknown>;
    if (!('payload' in ent)) return null;
    if (isValidPayload && !isValidPayload(ent.payload)) return null;
    if (ent.label !== undefined && typeof ent.label !== 'string') return null;
  }

  // cursor 範圍合理檢查
  const len = obj.entries.length;
  if (obj.cursor < 0 || obj.cursor > len) return null;

  return obj as unknown as OverlayHistorySnapshotV1<P>;
}

/**
 * 在 snapshot 上裁剪超出 maxEntries 的最舊 entry。
 *
 * - 若裁剪 N 筆、cursor 也對應前移（cursor - N、不可 < 0）
 * - 結果是新物件、不 mutate 原 snapshot
 */
export function truncateHistorySnapshot<P>(
  snapshot: OverlayHistorySnapshotV1<P>,
  maxEntries: number,
): OverlayHistorySnapshotV1<P> {
  if (maxEntries <= 0) {
    throw new Error('[OverlayHistorySnapshot] maxEntries must be > 0');
  }
  if (snapshot.entries.length <= maxEntries) return snapshot;
  const dropped = snapshot.entries.length - maxEntries;
  return {
    ...snapshot,
    entries: snapshot.entries.slice(dropped),
    cursor: Math.max(0, snapshot.cursor - dropped),
  };
}

/**
 * Caller 可 undo 的步數（cursor 之前的 entry 數）。
 */
export function countUndoable<P>(snapshot: OverlayHistorySnapshotV1<P>): number {
  return snapshot.cursor;
}

/**
 * Caller 可 redo 的步數（cursor 之後的 entry 數）。
 */
export function countRedoable<P>(snapshot: OverlayHistorySnapshotV1<P>): number {
  return snapshot.entries.length - snapshot.cursor;
}

export interface SnapshotSummary {
  totalEntries: number;
  undoable: number;
  redoable: number;
  labels: string[];
}

export function summarizeHistorySnapshot<P>(
  snapshot: OverlayHistorySnapshotV1<P>,
): SnapshotSummary {
  return {
    totalEntries: snapshot.entries.length,
    undoable: countUndoable(snapshot),
    redoable: countRedoable(snapshot),
    labels: snapshot.entries.map((e) => e.label ?? ''),
  };
}
