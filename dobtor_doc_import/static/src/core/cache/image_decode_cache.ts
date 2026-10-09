/**
 * Sprint 54 — Image decode 結果快取（in-memory LRU）
 *
 * 規劃書 §11.21 路線 A 第五步。Sprint 50 量測 preload 占 cold 8.1%（全 fixture），
 * 但對 04_with_image 系列達 17.9% 且 warm-after-AST-cache 後 preload 仍是固定成本，
 * 每張照片 dataURL → HTMLImageElement onload 都要 browser decode 一次 base64+image format。
 *
 * 設計：
 *   - Key = dataURL 字串本身（內容定址；同樣 bytes → 同樣 dataURL）
 *   - Value = 已解碼的 HTMLImageElement（onload 完成、可直接 drawImage）
 *   - LRU 用 Map 的插入順序（同 AstCache）
 *   - 純 in-memory（IDB 持久化 HTMLImageElement 不可序列化，需先轉 Blob/ImageBitmap，留 Sprint 55+）
 *
 * 用途：
 *   1. AST cache hit 後重開同份文件 → media Map 同 dataURLs → image cache 全 hit、preload ≈ 0ms
 *   2. 跨文件共享同一張圖（如企業 logo）→ image cache 也命中
 *
 * 為何不用 hash 當 key：
 *   - dataURL 已是內容定址（base64 編碼即內容）；hash 多一輪 SubtleCrypto async 開銷
 *   - dataURL 可長達數百 KB，當 Map key 用 V8 string interning 也 OK；對 < 1000 entries 規模沒問題
 */

const DEFAULT_MAX_ENTRIES = 100;

export interface ImageDecodeCacheOptions {
  /** 最大快取項目數（LRU 淘汰）。預設 100。 */
  maxEntries?: number;
}

export interface ImageDecodeCacheStats {
  hits: number;
  misses: number;
  size: number;
}

/**
 * Generic LRU image cache。型別參數 T 預設 HTMLImageElement，便於單元測試以 stub 值替換。
 *
 * 不論 V 是什麼類型，cache 本身只負責 key/value LRU 管理；decode 邏輯由 caller 負責。
 */
export class ImageDecodeCache<V = HTMLImageElement> {
  private readonly maxEntries: number;
  private readonly map: Map<string, V> = new Map();
  private hits = 0;
  private misses = 0;

  constructor(opts: ImageDecodeCacheOptions = {}) {
    this.maxEntries = opts.maxEntries ?? DEFAULT_MAX_ENTRIES;
    if (!Number.isInteger(this.maxEntries) || this.maxEntries < 1) {
      throw new Error(
        `ImageDecodeCache: maxEntries must be positive integer, got ${this.maxEntries}`,
      );
    }
  }

  /** 命中時 LRU touch（delete + set 推到 Map 尾端）+ hits++。 */
  get(key: string): V | undefined {
    const v = this.map.get(key);
    if (v === undefined) {
      this.misses++;
      return undefined;
    }
    this.map.delete(key);
    this.map.set(key, v);
    this.hits++;
    return v;
  }

  /** 寫入 + 超過 maxEntries 時 evict 最舊（Map iterator 首個）。 */
  put(key: string, value: V): void {
    if (this.map.has(key)) {
      this.map.delete(key);
    } else if (this.map.size >= this.maxEntries) {
      const oldestKey = this.map.keys().next().value;
      if (oldestKey !== undefined) this.map.delete(oldestKey);
    }
    this.map.set(key, value);
  }

  /** 是否含此 key（不影響 LRU 順序、不計 hit/miss）。 */
  has(key: string): boolean {
    return this.map.has(key);
  }

  /** 清空（測試 / 強制 cold run 量測用）。 */
  clear(): void {
    this.map.clear();
    this.hits = 0;
    this.misses = 0;
  }

  stats(): ImageDecodeCacheStats {
    return { hits: this.hits, misses: this.misses, size: this.map.size };
  }
}
