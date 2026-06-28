/**
 * CanvasEditorCacheNamespace — Sprint 353。
 *
 * Sprint 333 lifecycle + Sprint 348 key codec 之後深推。多份 doc 共用一個
 * lifecycle cache 時，不同 doc 的 (family, sizePt, text) 度量其實相同、可共享；
 * 但 caller 有時想做 **per-doc 隔離**（例如關閉 doc A 時只清 A 的 entries、
 * 或統計每 doc cache 佔用）。
 *
 * 本 sprint 提供 namespace 包裝：在 codec key 前綴加 `ns::`，並提供：
 *   - nsKey(namespace, parts)：產生 namespaced 完整 key
 *   - parseNsKey(key)：反解 namespace + parts
 *   - invalidateNamespace(cache, namespace)：清掉某 ns 全部
 *   - namespaceStats(cache, namespaces)：caller 指定 ns 算各自筆數（需 caller 給 key 列表）
 *
 * 紀律 #18 scope-down：
 *   - namespace 名稱不可含 `::`（caller 自負；本 module 用簡單分隔不 escape ns）
 *   - 不接 production canvas-editor real path（紀律 #21）
 *   - cache 內部不列舉 key，invalidateNamespace 走 lifecycle 的 prefix 失效
 *
 * 紀律 #21：純函式 + 組合既有 module；不污染既有 pipeline。
 */

import { CanvasEditorCacheLifecycle } from './CanvasEditorCacheLifecycle';
import { encodeCacheKey, decodeCacheKey, type CacheKeyParts } from './CanvasEditorCacheKeyCodec';

const NS_SEP = '::';

/**
 * 產生 namespaced key：`namespace::<encoded parts>`。
 *
 * namespace 含 `::` → throw（避免 parse 歧異）。
 */
export function nsKey(namespace: string, parts: CacheKeyParts): string {
  if (namespace.includes(NS_SEP)) {
    throw new Error(`[CacheNamespace] namespace must not contain "${NS_SEP}"`);
  }
  return `${namespace}${NS_SEP}${encodeCacheKey(parts)}`;
}

export interface ParsedNsKey {
  namespace: string;
  parts: CacheKeyParts;
}

/**
 * 反解 namespaced key。
 *
 * - 無 `::` → null
 * - parts 部分 decode 失敗 → null
 */
export function parseNsKey(key: string): ParsedNsKey | null {
  const idx = key.indexOf(NS_SEP);
  if (idx < 0) return null;
  const namespace = key.slice(0, idx);
  const encoded = key.slice(idx + NS_SEP.length);
  const parts = decodeCacheKey(encoded);
  if (!parts) return null;
  return { namespace, parts };
}

/**
 * namespace 的 prefix（給 lifecycle.invalidateByPrefix 用）。
 */
export function namespacePrefix(namespace: string): string {
  return `${namespace}${NS_SEP}`;
}

/**
 * 清掉某 namespace 全部 entry（透過 lifecycle prefix 失效）。回清掉筆數。
 */
export function invalidateNamespace<V>(
  cache: CanvasEditorCacheLifecycle<V>,
  namespace: string,
): number {
  return cache.invalidateByPrefix(namespacePrefix(namespace));
}

/**
 * 設值便利包裝：以 namespace + parts 寫入 cache。
 */
export function nsSet<V>(
  cache: CanvasEditorCacheLifecycle<V>,
  namespace: string,
  parts: CacheKeyParts,
  value: V,
): void {
  cache.set(nsKey(namespace, parts), value);
}

/**
 * 取值便利包裝。
 */
export function nsGet<V>(
  cache: CanvasEditorCacheLifecycle<V>,
  namespace: string,
  parts: CacheKeyParts,
): V | undefined {
  return cache.get(nsKey(namespace, parts));
}

/**
 * 給 caller 一組 key（caller 自己保存的 key 集合）→ 依 namespace 分組計數。
 *
 * 紀律 #18：lifecycle 不外露 key 列舉、所以 caller 必須提供它知道的 key 集合。
 */
export function groupKeysByNamespace(keys: ReadonlyArray<string>): Map<string, number> {
  const counts = new Map<string, number>();
  for (const k of keys) {
    const parsed = parseNsKey(k);
    if (!parsed) continue;
    counts.set(parsed.namespace, (counts.get(parsed.namespace) ?? 0) + 1);
  }
  return counts;
}
