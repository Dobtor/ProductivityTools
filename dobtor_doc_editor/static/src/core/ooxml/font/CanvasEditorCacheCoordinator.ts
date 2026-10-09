/**
 * CanvasEditorCacheCoordinator — Sprint 343。
 *
 * Sprint 328 snapshot + Sprint 333 lifecycle + Sprint 338 warmer 第四層整合。
 * 之前三個模組各自獨立；caller 想做完整生命週期要自己串：
 *
 *   restore（load snapshot → warm cache）→ 使用 → persist（dump → toSnapshot）
 *
 * 本 sprint 提供 orchestration class，把三者包成單一 API：
 *   - restore(snapshot, valueFactory)：load + warm 進內部 lifecycle cache
 *   - get / set：透傳給內部 cache（caller 走這個取度量）
 *   - persist(entriesMeta, now?)：把 caller 指定的 entries dump 成新 snapshot
 *   - 內建 dirty tracking：set 後標 dirty、persist 後清 dirty（caller 決定何時存）
 *
 * 紀律 #18 scope-down：
 *   - 不接 storage / file system（caller 拿 snapshot 自存）
 *   - 不接 production canvas-editor real path（紀律 #21）
 *   - persist 需要 caller 提供 entries meta（cache 內部不保存 text/family 反查）
 *
 * 紀律 #21：純 orchestration、組合既有 pure-fn module、不污染 pipeline。
 */

import {
  CanvasEditorCacheLifecycle,
  type CanvasEditorCacheLifecycleOptions,
  type CacheLifecycleStats,
} from './CanvasEditorCacheLifecycle';
import {
  toSnapshot,
  type CacheSnapshotV1,
} from './CanvasEditorCacheSnapshot';
import {
  warmFromSnapshot,
  keyFor,
} from './CanvasEditorCacheWarmer';
import type { PrewarmEntryWithMeta } from './CanvasEditorPrewarmStrategy';

export interface CacheCoordinatorOptions<V> extends CanvasEditorCacheLifecycleOptions {
  /**
   * persist 時呼叫的 ISO timestamp 工廠。
   * 注意：與 lifecycle 的 `now`（number clock、給 TTL 用）刻意分開命名、
   * 避免 string/number 型別衝突。
   */
  snapshotNow?: () => string;
}

export class CanvasEditorCacheCoordinator<V> {
  private readonly cache: CanvasEditorCacheLifecycle<V>;
  private readonly snapshotNow: (() => string) | undefined;
  private dirty = false;
  private restoredCount = 0;
  private persistCount = 0;

  constructor(opts: CacheCoordinatorOptions<V> = {}) {
    const { snapshotNow, ...lifecycleOpts } = opts;
    this.snapshotNow = snapshotNow;
    this.cache = new CanvasEditorCacheLifecycle<V>(lifecycleOpts);
  }

  /**
   * 從 snapshot 還原：把 entries warm 進內部 cache。
   * 回實際寫入筆數。restore 不算 dirty（資料還是 snapshot 同步狀態）。
   */
  restore(
    snapshot: CacheSnapshotV1,
    valueFactory: (entry: PrewarmEntryWithMeta) => V,
  ): number {
    const written = warmFromSnapshot(this.cache, snapshot, valueFactory);
    this.restoredCount += written;
    return written;
  }

  /** 透傳 cache.get。 */
  get(key: string): V | undefined {
    return this.cache.get(key);
  }

  /** 透傳 cache.set + 標 dirty。 */
  set(key: string, value: V): void {
    this.cache.set(key, value);
    this.dirty = true;
  }

  /** 用標準 keyFor 的便利 set（caller 有完整 entry meta 時）。 */
  setByEntry(entry: PrewarmEntryWithMeta, value: V): void {
    this.set(keyFor(entry), value);
  }

  has(key: string): boolean {
    return this.cache.has(key);
  }

  /**
   * persist：把 caller 指定的 entries meta dump 成新 snapshot。
   * 清 dirty flag、累計 persistCount。
   *
   * 紀律 #18：cache 內部不保存 text/family 反查、entriesMeta 必須由 caller 給。
   */
  persist(entriesMeta: ReadonlyArray<PrewarmEntryWithMeta>): CacheSnapshotV1 {
    const snapshot = toSnapshot(
      entriesMeta,
      this.snapshotNow ? { now: this.snapshotNow } : {},
    );
    this.dirty = false;
    this.persistCount += 1;
    return snapshot;
  }

  /** caller 判斷是否需要 persist（避免重複存相同狀態）。 */
  isDirty(): boolean {
    return this.dirty;
  }

  /** 主動清掉過期 TTL（透傳 lifecycle.purgeExpired）。 */
  purgeExpired(): number {
    return this.cache.purgeExpired();
  }

  /** 失效 + 標 dirty。 */
  invalidate(key: string): boolean {
    const removed = this.cache.invalidate(key);
    if (removed) this.dirty = true;
    return removed;
  }

  invalidateByPrefix(prefix: string): number {
    const n = this.cache.invalidateByPrefix(prefix);
    if (n > 0) this.dirty = true;
    return n;
  }

  getStats(): CoordinatorStats {
    return {
      cache: this.cache.getStats(),
      restoredCount: this.restoredCount,
      persistCount: this.persistCount,
      dirty: this.dirty,
    };
  }
}

export interface CoordinatorStats {
  cache: CacheLifecycleStats;
  restoredCount: number;
  persistCount: number;
  dirty: boolean;
}
