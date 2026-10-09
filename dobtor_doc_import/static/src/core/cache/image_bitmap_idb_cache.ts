/**
 * Sprint 56 — ImageBitmap + IndexedDB 跨 page persistence
 *
 * 規劃書 §11.23 Sprint 56 候選。Sprint 55 量測證實 warm path 87.3% 為 renderMs，
 * cache 無法繞過 render — 但若能讓 cross-tab / cross-session 重開時跳過「image decode + bitmap 上傳」
 * 這一段，仍能對 image-heavy 文件首頁可見時間（FCP-like）有實質助益。
 *
 * 設計：
 *   - L1 = in-memory Map<dataUrl, ImageBitmap>；同 session 命中 ~0ms
 *   - L2 = IndexedDB store；存 Blob（image bytes）而非 ImageBitmap（後者跨 page reload 不保證結構化複製）
 *   - get：L1 miss → L2 read（hash(dataUrl) 為 key）→ createImageBitmap(blob) → promote 回 L1
 *   - put：L1 寫；dataURL → Blob → IDB 寫；hash key 由 SHA-256(dataUrl bytes) 計算
 *   - 失敗策略：IDB 不可用 / createImageBitmap 不存在 → 靜默降級為 L1-only
 *
 * 與 [[Sprint 54 ImageDecodeCache]]（純 L1 HTMLImageElement）的差異：
 *   1. 跨 page 持久化（Sprint 54 重開即失效；本 cache 重開仍命中 Blob）
 *   2. 用 ImageBitmap 而非 HTMLImageElement → drawImage 走 GPU fast path（理論 +1.05-1.15× render）
 *   3. 多一層 dataURL → Blob → ImageBitmap 轉換成本（首次寫入時，後續 L1 命中無此成本）
 *
 * 為何 Blob 而非直接存 ImageBitmap：
 *   - ImageBitmap 是 transferable 但 IDB 的 structuredClone 是否支援 ImageBitmap 在 Chrome/Firefox/Safari
 *     行為不一致（spec 允許、實作有差異）；Blob 是 IDB 一等公民、最可靠
 *   - Blob 解碼成 ImageBitmap 是 async GPU op，比從 dataURL 重新 base64-decode + image format decode 快
 */

const DEFAULT_MEMORY_ENTRIES = 50;
const DEFAULT_IDB_ENTRIES = 200;
const DEFAULT_DB_NAME = 'dobtor-image-bitmap-cache';
const DEFAULT_STORE_NAME = 'bitmaps';
const DB_VERSION = 1;
const LRU_INDEX_NAME = 'lastAccessed';

export interface ImageBitmapIdbCacheOptions {
  /** L1 (memory) max entries. Default 50. */
  maxMemoryEntries?: number;
  /** L2 (IDB) max entries. Default 200. */
  maxIdbEntries?: number;
  dbName?: string;
  storeName?: string;
}

export interface ImageBitmapCacheStats {
  l1Hits: number;
  l2Hits: number;
  misses: number;
  l1Size: number;
}

interface IdbBitmapRecord {
  hash: string;
  blob: Blob;
  createdAt: number;
  lastAccessed: number;
}

/**
 * dataURL → SHA-256 hex（IDB key）。
 * 用 TextEncoder 比直接 hash base64 字節安全（一致 UTF-8 編碼）。
 */
async function hashDataUrl(dataUrl: string): Promise<string> {
  const bytes = new TextEncoder().encode(dataUrl);
  // crypto.subtle.digest 要 BufferSource；TS lib 對 Uint8Array<ArrayBufferLike> 與 BufferSource 對齊較嚴
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes as unknown as BufferSource);
  const arr = new Uint8Array(digest);
  let hex = '';
  for (let i = 0; i < arr.length; i++) {
    hex += arr[i].toString(16).padStart(2, '0');
  }
  return hex;
}

/**
 * dataURL → Blob。
 * 用 fetch(dataUrl).blob() 是現代瀏覽器最簡潔的轉換；fake-indexeddb 環境也支援。
 */
async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return res.blob();
}

/**
 * ImageBitmap 跨 page 持久化 cache。
 *
 * 注意：
 *   - 對外 API 全 async（IDB 操作）；caller 端永遠 `await`
 *   - createImageBitmap 不存在時（jsdom/node 環境）→ L2 降級為「只存 Blob、不回 ImageBitmap」
 *     vitest 測試用 sentinel Blob 來檢驗 LRU 行為，不依賴 createImageBitmap
 */
export class ImageBitmapIdbCache {
  private readonly maxMemoryEntries: number;
  private readonly maxIdbEntries: number;
  private readonly dbName: string;
  private readonly storeName: string;
  private readonly l1: Map<string, ImageBitmap> = new Map();
  private dbPromise: Promise<IDBDatabase> | null = null;
  private l1Hits = 0;
  private l2Hits = 0;
  private misses = 0;

  constructor(opts: ImageBitmapIdbCacheOptions = {}) {
    this.maxMemoryEntries = opts.maxMemoryEntries ?? DEFAULT_MEMORY_ENTRIES;
    this.maxIdbEntries = opts.maxIdbEntries ?? DEFAULT_IDB_ENTRIES;
    this.dbName = opts.dbName ?? DEFAULT_DB_NAME;
    this.storeName = opts.storeName ?? DEFAULT_STORE_NAME;
    if (!Number.isInteger(this.maxMemoryEntries) || this.maxMemoryEntries < 1) {
      throw new Error(
        `ImageBitmapIdbCache: maxMemoryEntries must be positive integer, got ${this.maxMemoryEntries}`,
      );
    }
    if (!Number.isInteger(this.maxIdbEntries) || this.maxIdbEntries < 1) {
      throw new Error(
        `ImageBitmapIdbCache: maxIdbEntries must be positive integer, got ${this.maxIdbEntries}`,
      );
    }
  }

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
        // 任何 version 升級 → drop store 重建（Blob 格式變動的可能性極低，但保險）
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
    this.dbPromise.catch(() => {
      this.dbPromise = null;
    });
    return this.dbPromise;
  }

  /** L1 LRU touch：delete + set 把 entry 推到 Map 尾端。 */
  private touchL1(key: string, value: ImageBitmap): void {
    if (this.l1.has(key)) {
      this.l1.delete(key);
    } else if (this.l1.size >= this.maxMemoryEntries) {
      const oldestKey = this.l1.keys().next().value;
      if (oldestKey !== undefined) this.l1.delete(oldestKey);
    }
    this.l1.set(key, value);
  }

  /**
   * 查 cache。L1 miss 才走 IDB。
   * @returns ImageBitmap（命中）或 undefined（miss）
   */
  async get(dataUrl: string): Promise<ImageBitmap | undefined> {
    // L1 check
    const memHit = this.l1.get(dataUrl);
    if (memHit) {
      // LRU touch（delete + set 推到尾端）
      this.l1.delete(dataUrl);
      this.l1.set(dataUrl, memHit);
      this.l1Hits++;
      return memHit;
    }
    // L2 check
    try {
      const db = await this.openDb();
      const hash = await hashDataUrl(dataUrl);
      const rec = await new Promise<IdbBitmapRecord | undefined>((resolve, reject) => {
        const tx = db.transaction(this.storeName, 'readwrite');
        const store = tx.objectStore(this.storeName);
        const getReq = store.get(hash);
        getReq.onsuccess = () => {
          const v = getReq.result as IdbBitmapRecord | undefined;
          if (v) {
            v.lastAccessed = Date.now();
            store.put(v); // IDB-side LRU 觸發
          }
          resolve(v);
        };
        getReq.onerror = () => reject(getReq.error);
      });
      if (rec) {
        this.l2Hits++;
        // createImageBitmap 不存在（node 環境）→ L2 視同 miss for caller、但 IDB 仍記錄了 lastAccessed
        if (typeof createImageBitmap === 'undefined') {
          return undefined;
        }
        const bitmap = await createImageBitmap(rec.blob);
        this.touchL1(dataUrl, bitmap);
        return bitmap;
      }
      this.misses++;
      return undefined;
    } catch {
      this.misses++;
      return undefined;
    }
  }

  /**
   * 寫 cache。L1 寫入 ImageBitmap；L2 寫入 Blob（dataURL → Blob 轉換）。
   * @param dataUrl 原始 dataURL（內容定址）
   * @param bitmap 已創建的 ImageBitmap（caller 從 createImageBitmap(img) 取得）
   */
  async put(dataUrl: string, bitmap: ImageBitmap): Promise<void> {
    this.touchL1(dataUrl, bitmap);
    try {
      const blob = await dataUrlToBlob(dataUrl);
      const hash = await hashDataUrl(dataUrl);
      const db = await this.openDb();
      const now = Date.now();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(this.storeName, 'readwrite');
        const store = tx.objectStore(this.storeName);
        store.put({ hash, blob, createdAt: now, lastAccessed: now });
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
      await this.evictIfNeeded();
    } catch {
      // IDB / fetch / hashDataUrl 失敗 → L1 仍可用
    }
  }

  /** L2 超過 maxIdbEntries 時，按 lastAccessed 升序刪最舊。 */
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

  stats(): ImageBitmapCacheStats {
    return {
      l1Hits: this.l1Hits,
      l2Hits: this.l2Hits,
      misses: this.misses,
      l1Size: this.l1.size,
    };
  }
}

// Export helpers for testing
export { hashDataUrl, dataUrlToBlob };
