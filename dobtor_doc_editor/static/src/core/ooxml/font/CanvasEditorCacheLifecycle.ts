/**
 * CanvasEditorCacheLifecycle — Sprint 333。
 *
 * Sprint 302 TextMeasureProxy（FIFO eviction）/ Sprint 328 CacheSnapshot 之後
 * 深推。Caller 想要更精緻的 eviction：
 *
 *   - LRU：丟最久沒用的（access order tracking）
 *   - TTL：超過 N ms 自動失效
 *   - invalidation：caller 主動指定 key prefix / predicate 失效
 *
 * 紀律 #18 scope-down：
 *   - 純記憶體 K/V cache、由 caller 自行決定 value type（generic）
 *   - 不接 production canvas-editor real path（紀律 #21）
 *   - 不做 LFU（frequency 已由 Sprint 323 PrewarmStrategy 處理）
 *   - 不做 disk spill / 分散式快取
 *
 * 紀律 #21：純資料 transformation；caller 自行 wire 進 Sprint 318 pipeline。
 */

export interface CacheEntry<V> {
  value: V;
  /** 寫入時間（ms epoch / performance.now、由 caller now() 注入） */
  insertedAtMs: number;
  /** 最近 access 時間 */
  lastAccessedAtMs: number;
}

export interface CanvasEditorCacheLifecycleOptions {
  /** LRU 上限筆數；超過丟最久沒用的；預設 256 */
  maxEntries?: number;
  /** TTL（ms）；entry 自寫入經過 N ms 後 get/has 為 miss；undefined → 無 TTL */
  ttlMs?: number;
  /** Caller 注入 now() 給可測試的時鐘；缺省 Date.now */
  now?: () => number;
}

export class CanvasEditorCacheLifecycle<V> {
  private readonly maxEntries: number;
  private readonly ttlMs: number | undefined;
  private readonly now: () => number;
  /**
   * 用 Map（保留插入順序）+ 每次 get 後 delete + set 來模擬 LRU。
   */
  private readonly store = new Map<string, CacheEntry<V>>();
  private hits = 0;
  private misses = 0;
  private ttlEvictions = 0;
  private lruEvictions = 0;

  constructor(opts: CanvasEditorCacheLifecycleOptions = {}) {
    this.maxEntries = opts.maxEntries ?? 256;
    if (this.maxEntries <= 0) {
      throw new Error('[CanvasEditorCacheLifecycle] maxEntries must be > 0');
    }
    if (opts.ttlMs !== undefined && opts.ttlMs <= 0) {
      throw new Error('[CanvasEditorCacheLifecycle] ttlMs must be > 0');
    }
    this.ttlMs = opts.ttlMs;
    this.now = opts.now ?? (() => Date.now());
  }

  set(key: string, value: V): void {
    const now = this.now();
    // 已存在 → 移除舊位置確保 reorder
    if (this.store.has(key)) {
      this.store.delete(key);
    }
    this.store.set(key, { value, insertedAtMs: now, lastAccessedAtMs: now });
    // LRU eviction：超過 maxEntries 丟最舊（Map 的第一個 key）
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (oldest === undefined) break;
      this.store.delete(oldest);
      this.lruEvictions += 1;
    }
  }

  /**
   * 取值；TTL 過期視為 miss（並順手刪除過期 entry）。
   * 命中時 reorder 至 Map 尾端（LRU 更新）。
   */
  get(key: string): V | undefined {
    const entry = this.store.get(key);
    if (!entry) {
      this.misses += 1;
      return undefined;
    }
    const now = this.now();
    if (this.ttlMs !== undefined && now - entry.insertedAtMs >= this.ttlMs) {
      this.store.delete(key);
      this.ttlEvictions += 1;
      this.misses += 1;
      return undefined;
    }
    // LRU reorder
    this.store.delete(key);
    entry.lastAccessedAtMs = now;
    this.store.set(key, entry);
    this.hits += 1;
    return entry.value;
  }

  has(key: string): boolean {
    return this.get(key) !== undefined;
  }

  /** 主動失效單一 key；不影響 hit/miss 計數。 */
  invalidate(key: string): boolean {
    return this.store.delete(key);
  }

  /**
   * 用 predicate 失效一批 key。回失效的 key 數。
   */
  invalidateWhere(pred: (key: string, value: V) => boolean): number {
    let count = 0;
    for (const [k, e] of this.store) {
      if (pred(k, e.value)) {
        this.store.delete(k);
        count += 1;
      }
    }
    return count;
  }

  /** 用 prefix 失效（caller 常見場景：font family 變更時清掉所有同 family 的 cache）。 */
  invalidateByPrefix(prefix: string): number {
    return this.invalidateWhere((k) => k.startsWith(prefix));
  }

  clear(): void {
    this.store.clear();
  }

  size(): number {
    return this.store.size;
  }

  getStats(): CacheLifecycleStats {
    return {
      size: this.store.size,
      hits: this.hits,
      misses: this.misses,
      hitRate: this.hits + this.misses === 0 ? 0 : this.hits / (this.hits + this.misses),
      ttlEvictions: this.ttlEvictions,
      lruEvictions: this.lruEvictions,
    };
  }

  /** 主動掃描 TTL 過期、回清掉的數量。caller 想做 idle-time cleanup 用。 */
  purgeExpired(): number {
    if (this.ttlMs === undefined) return 0;
    const now = this.now();
    let count = 0;
    for (const [k, e] of this.store) {
      if (now - e.insertedAtMs >= this.ttlMs) {
        this.store.delete(k);
        this.ttlEvictions += 1;
        count += 1;
      }
    }
    return count;
  }
}

export interface CacheLifecycleStats {
  size: number;
  hits: number;
  misses: number;
  hitRate: number;
  ttlEvictions: number;
  lruEvictions: number;
}
