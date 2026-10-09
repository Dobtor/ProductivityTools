/**
 * Sprint 58 — Layout 結果快取（in-memory LRU）
 *
 * 規劃書 §11.25 Sprint 58 候選之一。Sprint 55 全 42 fixture full-warm 5.32×、Sprint 57 memoize-only 6.36×；
 * 兩者 warm 階段都還在 layout（~110ms / 7.5% of warm total）— layout 是 documentNode + LayoutOptions 的純函數，
 * 可被安全快取。
 *
 * 為何不沿用 [[ast_cache]] 的型別 / 介面：
 *   - AST cache 用 SHA-256(docx bytes) 當 key；LayoutCache 還要考慮 LayoutOptions（fontMap、defaultPageSize 等）
 *   - Layout 對 LayoutOptions 變動敏感（spacing.line / docGrid snap / paragraph defaultSpacingAfter 等）
 *   - 分開實作 + 共用 LRU pattern 可讀性比 generic 強
 *
 * 為何 layout 值得快取（vs Sprint 51 AST cache 已 0.3% parse）：
 *   - Sprint 51-55 證實 parse 100% cacheable；本 sprint 對 layout 做平行擴展
 *   - warm 路徑中 layout 是僅次於 render 的次大成本
 *   - 與 OffscreenCanvas + Worker render（Sprint 59 候選）的架構配合：layout 快取在主執行緒、render 在 worker
 *
 * 範圍：
 *   - 本 sprint 只做 in-memory L1 LRU（與 Sprint 51 AST cache 同 pattern）
 *   - IDB 持久化（跨 page reload）留 Sprint 59+ 候選；L1 命中率高即可
 *
 * 為何 key = docxHash + optsHash：
 *   - docxHash 已由 [[ast_cache]]/[[computeDocxHash]] 提供
 *   - LayoutOptions 是 small JSON object；stable hash via canonicalize + crypto.subtle.digest
 *   - 兩者 join 用 `|` 分隔（兩段都是 64-hex 不含 |，無歧義）
 */

import type { DocumentLayout, LayoutOptions } from '../layout';

const DEFAULT_MAX_ENTRIES = 8;

/**
 * 對 LayoutOptions 做 stable JSON 序列化（key 排序 + 遞迴）。
 * 為何不直接 JSON.stringify：屬性順序可能因建構方式不同（v8 vs 來源）→ key 不穩定。
 */
export function canonicalizeJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map(canonicalizeJson).join(',')}]`;
  }
  // object：key 排序後遞迴
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  const parts: string[] = [];
  for (const k of keys) {
    const v = obj[k];
    if (v === undefined) continue;
    parts.push(`${JSON.stringify(k)}:${canonicalizeJson(v)}`);
  }
  return `{${parts.join(',')}}`;
}

/**
 * LayoutOptions → SHA-256 hex（穩定 hash）。
 * 用 canonicalizeJson 確保 key 順序穩定。
 */
export async function hashLayoutOptions(opts: LayoutOptions): Promise<string> {
  const json = canonicalizeJson(opts ?? {});
  const bytes = new TextEncoder().encode(json);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes as unknown as BufferSource);
  const arr = new Uint8Array(digest);
  let hex = '';
  for (let i = 0; i < arr.length; i++) hex += arr[i].toString(16).padStart(2, '0');
  return hex;
}

/** Compose docx hash 與 options hash 成 LayoutCache key。 */
export function composeLayoutKey(docxHash: string, optsHash: string): string {
  return `${docxHash}|${optsHash}`;
}

export interface LayoutCacheOptions {
  /** Max in-memory entries (LRU). Default 8. */
  maxEntries?: number;
}

interface LayoutCacheStats {
  hits: number;
  misses: number;
  size: number;
}

/**
 * In-memory LRU layout cache。
 *
 * LRU 同 [[AstCache]] pattern：Map insertion order = access order；
 * get/put 命中時 delete + set 推到「最新」端；超過 maxEntries 時刪 iterator 首個。
 */
export class LayoutCache {
  private readonly maxEntries: number;
  private readonly map: Map<string, DocumentLayout> = new Map();
  private hits = 0;
  private misses = 0;

  constructor(opts: LayoutCacheOptions = {}) {
    this.maxEntries = opts.maxEntries ?? DEFAULT_MAX_ENTRIES;
    if (!Number.isInteger(this.maxEntries) || this.maxEntries < 1) {
      throw new Error(`LayoutCache: maxEntries must be positive integer, got ${this.maxEntries}`);
    }
  }

  get(key: string): DocumentLayout | undefined {
    const v = this.map.get(key);
    if (v === undefined) {
      this.misses++;
      return undefined;
    }
    // LRU touch
    this.map.delete(key);
    this.map.set(key, v);
    this.hits++;
    return v;
  }

  put(key: string, layout: DocumentLayout): void {
    if (this.map.has(key)) {
      this.map.delete(key);
    } else if (this.map.size >= this.maxEntries) {
      const oldestKey = this.map.keys().next().value;
      if (oldestKey !== undefined) this.map.delete(oldestKey);
    }
    this.map.set(key, layout);
  }

  has(key: string): boolean {
    return this.map.has(key);
  }

  clear(): void {
    this.map.clear();
    this.hits = 0;
    this.misses = 0;
  }

  stats(): LayoutCacheStats {
    return { hits: this.hits, misses: this.misses, size: this.map.size };
  }
}
