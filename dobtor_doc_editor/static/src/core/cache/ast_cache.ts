/**
 * Sprint 51 — AST 快取（in-memory LRU）
 *
 * 規劃書 §11.18 路線 A 第二步。Sprint 50 效能基線量測證實 parse 占 60.7% 為瓶頸；
 * 本模組以「docx bytes SHA-256 → DocumentNode」當 key/value 提供 process-lifetime 的
 * LRU 快取，重開未改動文件即可跳過 parse。
 *
 * 範圍：
 *   - 本 sprint 只做 in-memory LRU，先以 cold vs warm 量測證實「parse 可快取」假設成立
 *   - IndexedDB 持久化（跨 page reload / 跨 session）留 Sprint 52
 *
 * 為何 hash 而不直接用「docx 路徑/名稱」當 key：
 *   - 工地現場常見「同名 docx 已被修改」情境，bytes hash 是唯一可靠識別子
 *   - SHA-256 對 docx ~ MB 級檔案在現代瀏覽器 < 10ms（crypto.subtle 走 native）
 *
 * 為何不快取 layout：
 *   - layout 僅占 1.8%（Sprint 50 量測），快取收益不抵 LayoutOptions 變動時的失效風險
 *   - AST 是 docx bytes 的純函數；layout 還受 LayoutOptions 影響
 */

import type { DocumentNode } from '../ooxml/ast/types';

const DEFAULT_MAX_ENTRIES = 8;

/**
 * SHA-256 hex of bytes. 使用 globalThis.crypto.subtle（瀏覽器 + Node 16+）。
 *
 * @param bytes ArrayBuffer 或 Uint8Array（兩者皆接受，避免呼叫端為了型別二次 copy）
 * @returns 64-char lowercase hex 字串
 */
export async function computeDocxHash(bytes: ArrayBuffer | Uint8Array): Promise<string> {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  // crypto.subtle.digest 要 BufferSource；TS lib 對 Uint8Array<ArrayBufferLike> 與 BufferSource
  // 的對齊在 5.x 後較嚴，cast 成 BufferSource 抑制誤報（runtime 兩者等價）
  const digest = await globalThis.crypto.subtle.digest('SHA-256', u8 as unknown as BufferSource);
  const arr = new Uint8Array(digest);
  let hex = '';
  for (let i = 0; i < arr.length; i++) {
    hex += arr[i].toString(16).padStart(2, '0');
  }
  return hex;
}

export interface AstCacheOptions {
  /** Max in-memory entries (LRU). Default 8. */
  maxEntries?: number;
}

interface CacheStats {
  hits: number;
  misses: number;
  size: number;
}

/**
 * In-memory LRU AST cache.
 *
 * LRU 用 Map 的「插入順序 = 訪問順序」性質實作：每次 get/put 命中先 delete 再 set
 * 把該 entry 推到「最新」端；超過 maxEntries 時刪掉迭代器首個（最舊）entry。
 */
export class AstCache {
  private readonly maxEntries: number;
  private readonly map: Map<string, DocumentNode> = new Map();
  private hits = 0;
  private misses = 0;

  constructor(opts: AstCacheOptions = {}) {
    this.maxEntries = opts.maxEntries ?? DEFAULT_MAX_ENTRIES;
    if (!Number.isInteger(this.maxEntries) || this.maxEntries < 1) {
      throw new Error(`AstCache: maxEntries must be positive integer, got ${this.maxEntries}`);
    }
  }

  /**
   * 查 cache。命中時把 entry 推到 LRU 最新端。
   */
  get(hash: string): DocumentNode | undefined {
    const v = this.map.get(hash);
    if (v === undefined) {
      this.misses++;
      return undefined;
    }
    // LRU touch：delete + set 把 entry 移到 Map 尾端（最新）
    this.map.delete(hash);
    this.map.set(hash, v);
    this.hits++;
    return v;
  }

  /**
   * 寫 cache。超過 maxEntries 時 evict 最舊 entry。
   */
  put(hash: string, ast: DocumentNode): void {
    if (this.map.has(hash)) {
      // 既有 entry：touch 到最新端
      this.map.delete(hash);
    } else if (this.map.size >= this.maxEntries) {
      // 滿了：evict 最舊（iterator 首個 key）
      const oldestKey = this.map.keys().next().value;
      if (oldestKey !== undefined) this.map.delete(oldestKey);
    }
    this.map.set(hash, ast);
  }

  /** 是否含此 hash（不影響 LRU 順序、不計 hit/miss）。 */
  has(hash: string): boolean {
    return this.map.has(hash);
  }

  /** 清空（測試用 / 強制冷啟動量測用）。 */
  clear(): void {
    this.map.clear();
    this.hits = 0;
    this.misses = 0;
  }

  stats(): CacheStats {
    return { hits: this.hits, misses: this.misses, size: this.map.size };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Sprint 52 — IndexedDB-backed two-tier AST cache
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Sprint 52：跨 page reload / tab close 的 AST 持久化層。
 *
 * 設計：
 *   - L1 = in-memory LRU（複用 AstCache，避免重複實作）；同 session 命中 ~0ms
 *   - L2 = IndexedDB；跨 reload/tab/session 命中（同 origin 範圍）
 *   - get：L1 miss → L2 read（含 lastAccessed update for IDB-side LRU）→ promote 回 L1
 *   - put：同時寫 L1 + L2；put 後 evict L2 過量 entries
 *   - 失敗策略：IDB 拋錯（quota / private mode）時靜默降級為 in-memory-only（不破壞 caller）
 *
 * 為何不直接修改 AstCache 介面變 async：
 *   Sprint 51 的 AstCache 是純 in-memory、不需 async；改變介面會破壞既有 11 個 vitest。
 *   pipeline 端用 `await cache.get(...)`，無論回傳同步值或 Promise 都正確（await sync 值是 no-op）。
 *
 * 失效：本 sprint 不做 schema migration —— DB_VERSION 任何升版時清空 store（AST 結構變動的話，
 *   舊快取一概作廢，避免 deserialize 時欄位 mismatch）。
 */

const DB_VERSION = 1;
const DEFAULT_DB_NAME = 'dobtor-ast-cache';
const DEFAULT_STORE_NAME = 'asts';
const DEFAULT_MAX_IDB_ENTRIES = 32;
const LRU_INDEX_NAME = 'lastAccessed';

export interface IdbAstCacheOptions {
  /** L1 (memory) LRU max entries. Default 8. */
  maxMemoryEntries?: number;
  /** L2 (IDB) max entries. Default 32. Eviction via lastAccessed LRU. */
  maxIdbEntries?: number;
  dbName?: string;
  storeName?: string;
}

interface IdbAstRecord {
  hash: string; // primary key (matches store keyPath)
  ast: DocumentNode;
  createdAt: number;
  lastAccessed: number;
}

export interface IdbCacheStats {
  l1Hits: number;
  l2Hits: number;
  misses: number;
  l1Size: number;
}

/**
 * Two-tier AST cache：in-memory L1 (LRU) + IndexedDB L2 (LRU)。
 * 對 pipeline 的 API 是 async，相容於 AstCache（sync）— pipeline 端 `await` 兩者皆可。
 */
export class IdbAstCache {
  private readonly l1: AstCache;
  private readonly maxIdbEntries: number;
  private readonly dbName: string;
  private readonly storeName: string;
  private dbPromise: Promise<IDBDatabase> | null = null;
  private l1Hits = 0;
  private l2Hits = 0;
  private misses = 0;

  constructor(opts: IdbAstCacheOptions = {}) {
    this.l1 = new AstCache({ maxEntries: opts.maxMemoryEntries ?? 8 });
    this.maxIdbEntries = opts.maxIdbEntries ?? DEFAULT_MAX_IDB_ENTRIES;
    this.dbName = opts.dbName ?? DEFAULT_DB_NAME;
    this.storeName = opts.storeName ?? DEFAULT_STORE_NAME;
    if (!Number.isInteger(this.maxIdbEntries) || this.maxIdbEntries < 1) {
      throw new Error(`IdbAstCache: maxIdbEntries must be positive integer, got ${this.maxIdbEntries}`);
    }
  }

  /**
   * Lazy open + 快取 DB connection promise。同一實例所有 get/put 共用。
   */
  private openDb(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;
    this.dbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('indexedDB not available in this environment'));
        return;
      }
      const req = indexedDB.open(this.dbName, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        // schema migration 策略 = 任何 version 升 → drop store 重建（AST 結構升版時舊資料一概作廢）
        if (db.objectStoreNames.contains(this.storeName)) {
          db.deleteObjectStore(this.storeName);
        }
        const store = db.createObjectStore(this.storeName, { keyPath: 'hash' });
        store.createIndex(LRU_INDEX_NAME, 'lastAccessed', { unique: false });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error ?? new Error('IDB open failed'));
      req.onblocked = () => reject(new Error('IDB open blocked'));
    });
    // 失敗時下次再試（避免一次失敗整個 session 都掛）
    this.dbPromise.catch(() => {
      this.dbPromise = null;
    });
    return this.dbPromise;
  }

  async get(hash: string): Promise<DocumentNode | undefined> {
    // L1（同步 / process-lifetime）
    const fromMem = this.l1.get(hash);
    if (fromMem) {
      this.l1Hits++;
      return fromMem;
    }
    // L2（async / cross-session）
    try {
      const db = await this.openDb();
      const rec = await new Promise<IdbAstRecord | undefined>((resolve, reject) => {
        const tx = db.transaction(this.storeName, 'readwrite');
        const store = tx.objectStore(this.storeName);
        const getReq = store.get(hash);
        getReq.onsuccess = () => {
          const v = getReq.result as IdbAstRecord | undefined;
          if (v) {
            v.lastAccessed = Date.now();
            store.put(v); // update lastAccessed → IDB-side LRU 觸發
          }
          resolve(v);
        };
        getReq.onerror = () => reject(getReq.error);
      });
      if (rec) {
        this.l2Hits++;
        this.l1.put(hash, rec.ast); // promote L2 → L1
        return rec.ast;
      }
      this.misses++;
      return undefined;
    } catch {
      // IDB 失敗（private mode / quota / corruption） → 視同 miss、不破壞 caller
      this.misses++;
      return undefined;
    }
  }

  async put(hash: string, ast: DocumentNode): Promise<void> {
    this.l1.put(hash, ast);
    try {
      const db = await this.openDb();
      const now = Date.now();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(this.storeName, 'readwrite');
        const store = tx.objectStore(this.storeName);
        store.put({ hash, ast, createdAt: now, lastAccessed: now });
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
      await this.evictIfNeeded();
    } catch {
      // IDB 失敗時降級為 in-memory only — caller 仍能用 L1
    }
  }

  /** L2 entries 超過 maxIdbEntries 時，按 lastAccessed 升序刪最舊。 */
  private async evictIfNeeded(): Promise<void> {
    const db = await this.openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readwrite');
      const store = tx.objectStore(this.storeName);
      const countReq = store.count();
      countReq.onsuccess = () => {
        const n = countReq.result;
        if (n <= this.maxIdbEntries) {
          resolve();
          return;
        }
        const toEvict = n - this.maxIdbEntries;
        const index = store.index(LRU_INDEX_NAME);
        const cursorReq = index.openCursor();
        let evicted = 0;
        cursorReq.onsuccess = () => {
          const cursor = cursorReq.result;
          if (cursor && evicted < toEvict) {
            cursor.delete();
            evicted++;
            cursor.continue();
          } else {
            resolve();
          }
        };
        cursorReq.onerror = () => reject(cursorReq.error);
      };
      countReq.onerror = () => reject(countReq.error);
    });
  }

  async clear(): Promise<void> {
    this.l1.clear();
    this.l1Hits = 0;
    this.l2Hits = 0;
    this.misses = 0;
    try {
      const db = await this.openDb();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(this.storeName, 'readwrite');
        tx.objectStore(this.storeName).clear();
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    } catch {
      // 視同空 cache
    }
  }

  stats(): IdbCacheStats {
    return {
      l1Hits: this.l1Hits,
      l2Hits: this.l2Hits,
      misses: this.misses,
      l1Size: this.l1.stats().size,
    };
  }
}

/**
 * pipeline 接受的 cache shape：sync (AstCache) 或 async (IdbAstCache) 皆可。
 * pipeline 端統一 `await cache.get/put(...)` — await 同步值是 no-op，async 值正常 unwrap。
 */
export interface PipelineAstCache {
  get(hash: string): DocumentNode | undefined | Promise<DocumentNode | undefined>;
  put(hash: string, ast: DocumentNode): void | Promise<void>;
}
