/**
 * CanvasEditorCacheWarmer — Sprint 338。
 *
 * Sprint 328 CacheSnapshot + Sprint 333 CacheLifecycle 之後深推。Caller 場景：
 *
 *   1. 上次 session 已 prewarm 出 high-frequency entries（snapshot.entries）
 *   2. 這次 session 想用同樣 cache key（family + size + text）seed 進新的
 *      CanvasEditorCacheLifecycle，省下 cold start measure 時間
 *
 * 本 module 提供：
 *   - keyFor(entry)：標準化 cache key（family|sizePt|text）
 *   - warmFromSnapshot(cache, snapshot, valueFactory)：caller 提供 value 工廠、
 *     把 snapshot.entries 灌進 cache
 *   - exportLifecycleAsEntries(cache, keys)：caller 主動指定 keys 反向 dump 成
 *     PrewarmEntryWithMeta 陣列（給 Sprint 328 toSnapshot 用）
 *
 * 紀律 #18 scope-down：
 *   - value 型別 generic、caller 自負 keyFor 與 valueFactory 的對齊
 *   - 不接 production canvas-editor real path（紀律 #21）
 *   - 不做 lazy load（caller 自決是否 warm；過大 snapshot 可先 truncate）
 *
 * 紀律 #21：純資料 transformation；caller 把產生的 cache 接到 318 pipeline。
 */

import { CanvasEditorCacheLifecycle } from './CanvasEditorCacheLifecycle';
import type {
  CacheSnapshotV1,
} from './CanvasEditorCacheSnapshot';
import type { PrewarmEntryWithMeta } from './CanvasEditorPrewarmStrategy';

/** 標準化 cache key：`family|sizePt|text`。 */
export function keyFor(entry: PrewarmEntryWithMeta): string {
  return `${entry.family}|${entry.sizePt}|${entry.text}`;
}

/**
 * 把 snapshot.entries 灌進 lifecycle cache。
 *
 * @param cache caller-provided lifecycle cache
 * @param snapshot Sprint 328 snapshot
 * @param valueFactory caller 給定 (entry) → value（pre-measured 度量 / shaping result）
 * @returns 實際寫入的筆數（不重複）
 *
 * 紀律 #18：若 cache 有 maxEntries，超過部分自然 LRU 驅逐、不另回 error。
 */
export function warmFromSnapshot<V>(
  cache: CanvasEditorCacheLifecycle<V>,
  snapshot: CacheSnapshotV1,
  valueFactory: (entry: PrewarmEntryWithMeta) => V,
): number {
  let written = 0;
  for (const entry of snapshot.entries) {
    cache.set(keyFor(entry), valueFactory(entry));
    written += 1;
  }
  return written;
}

/**
 * 給 caller 指定一組 key + 對應的 (text, family, sizePt) → dump 出
 * PrewarmEntryWithMeta（frequency = 1，charset 由 caller 自決）。
 *
 * 注意：keyFor 是 hash 一向（family|sizePt|text）；caller 想反向必須提供完整
 * entry list（本 fn 不負責解析 key）。
 */
export function exportLifecycleAsEntries<V>(
  _cache: CanvasEditorCacheLifecycle<V>,
  entries: ReadonlyArray<{ text: string; family: string; sizePt: number; charset?: PrewarmEntryWithMeta['charset'] }>,
): PrewarmEntryWithMeta[] {
  return entries.map((e) => ({
    text: e.text,
    family: e.family,
    sizePt: e.sizePt,
    frequency: 1,
    ...(e.charset ? { charset: e.charset } : {}),
  }));
}

/**
 * 給 caller 預估 warmFromSnapshot 後的 cache 占用：
 * - keptCount = min(snapshot.entries.length, cache.maxEntries 假設）
 *
 * 紀律 #18：cache 內部 maxEntries 不外露，本 helper 只看 caller 傳的 max。
 */
export function predictWarmFootprint(
  snapshot: CacheSnapshotV1,
  cacheMaxEntries: number,
): { keptCount: number; droppedCount: number } {
  const total = snapshot.entries.length;
  const kept = Math.min(total, cacheMaxEntries);
  return { keptCount: kept, droppedCount: total - kept };
}
