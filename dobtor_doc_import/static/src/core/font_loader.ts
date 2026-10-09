/**
 * Sprint 64b — FontLoader（lazy load + IDB cache + register to FontMetricsAdapter）
 *
 * 規劃書 §11.32 Sprint 64b 之 Strategy B：portal/canvas-editor 端 lazy load + IDB cache。
 *
 * 流程：
 *   1. caller 給 family list（e.g. ['標楷體', 'Times New Roman']）
 *   2. 對每個 family：
 *      a. IDB lookup（key = family、value = ArrayBuffer）
 *      b. miss → fetch `/dobtor/fonts/<encodeURIComponent(family)>` → save IDB
 *      c. hit → 直接用
 *   3. 把 ArrayBuffer registerFont 到 FontMetricsAdapter
 *   4. 回 adapter 給 pipeline.render({ fontAdapter })
 *
 * Sprint 157 — fontTable.altName fallback wire-up:
 *   - 對應規畫書 Phase 2 §2.2「從 fontTable.xml 讀字型名稱」+「字型載入器」
 *   - 接續 Sprint 147 FontTableParser capture
 *   - 主 family fetch 失敗（404 / network error / IDB miss）且 fontTable[family].altName 存在
 *     → 對 altName 走完整 IDB-lookup → fetch 流程（同邏輯、不無限遞迴）
 *   - 主 + alt 都失敗 → silent fallback（adapter 未註冊、pipeline 自動 fallback EstimateMetrics）
 *   - 不傳 fontTable → 行為與 Sprint 64b 完全一致（backward compat、不破 baseline）
 *
 * **重要定位（Sprint 64b 誠實註記、Sprint 157 unchanged）**：
 *   - 目前 production 走 canvas-editor、未直接使用此 module
 *   - 此 module 是「未來 migrate 自家 pipeline 時 caller-side 載 fonts 的標準介面」infrastructure
 *   - VR pipeline 自己有獨立的 font load 路徑（visual_regression_v14.mjs 直接 readFileSync）、不經此 module
 *
 * 設計取捨：
 *   - IDB schema 與 [[ast_cache]] 分離（不同 store name）；font bytes 變動少、用簡單 key=family
 *   - 任何錯誤（IDB unavailable / fetch 失敗 / opentype.js 解析失敗）→ silent fallback（adapter 該 family 未註冊、pipeline 自動 fallback EstimateMetrics）
 *   - 不做 batch fetch：每個 family 一個 request，便於 Cache-Control 命中
 *   - Sprint 157:altName fallback 只試一層（不遞迴 altName-of-altName）；OOXML §17.8 spec 不定義巢狀 altName
 *
 * Sprint 166 — CJK fallback chain wire-up:
 *   - 對應規畫書 Phase 2 §2.2「CJK fallback 鏈：原字型 → 思源黑體 / 微軟正黑體 → 新細明體 → 預設字型」
 *   - 主 family + altName 都取不到、且該 family 經 fontTable.charset 判定為 CJK 字型時、
 *     依序試一條通用 CJK fallback chain
 *   - 拉丁字型（charset '00' = ANSI）不會誤套 CJK 字型
 *   - chain 任一成功 → 用「主 family」name 註冊（同 Sprint 157、caller 仍以原 family 查詢）
 *   - chain 全失敗 → silent fallback（adapter 未註冊、pipeline 自動 fallback EstimateMetrics）
 *   - 不傳 fontTable / family 非 CJK → 行為與 Sprint 157 完全一致（backward compat、不破 baseline）
 */

import { FontMetricsAdapter } from './layout/FontMetricsAdapter';
import type { FontTable, FontEntry } from './ooxml/ast/types';

const DB_NAME = 'dobtor-font-cache';
const DB_VERSION = 1;
const STORE = 'fonts';
const DEFAULT_ENDPOINT = '/dobtor/fonts';

/**
 * Sprint 166 — CJK fallback chain（規畫書 Phase 2 §2.2）。
 *
 * 主 family + altName 都取不到、且該 family 經 fontTable.charset 判定為 CJK 字型時、
 * 依序試這條通用 CJK fallback chain。對應規畫書 §2.2「原字型 → 思源黑體 / 微軟正黑體
 * → 新細明體 → 預設字型」（「預設字型」= 整條 chain 失敗後的 silent fallback）。
 */
const CJK_FALLBACK_CHAIN: readonly string[] = ['思源黑體', '微軟正黑體', '新細明體'];

/**
 * OOXML `w:charset` 值（hex 字串）對應 CJK 語系的子集：
 *   '80' = ShiftJIS（日文）、'81' = Hangul（韓文）、
 *   '86' = GB2312（簡中）、'88' = ChineseBig5（繁中）。
 * 只有 fontTable 該 family 的 charset 落在此集合、才套用 CJK fallback chain
 * （拉丁字型 charset '00' = ANSI 不會誤套思源黑體）。
 */
const CJK_CHARSETS: ReadonlySet<string> = new Set(['80', '81', '86', '88']);

/** 依 fontTable 的 `charset` 判斷一個 FontEntry 是否為 CJK 字型。 */
function isCjkFont(entry: FontEntry): boolean {
  return entry.charset !== undefined && CJK_CHARSETS.has(entry.charset);
}

export interface FontLoaderOptions {
  /** 字型 list endpoint（預設 /dobtor/fonts/<family>）；可指向其他 origin / mock server */
  endpoint?: string;
  /** 已 build 好的 adapter；不傳 → 自動建。caller 可注入 vitest mock */
  adapter?: FontMetricsAdapter;
  /** fetch 超時（ms），預設 10000；超時則 silent fallback */
  fetchTimeoutMs?: number;
  /**
   * Sprint 157 — 從 docx 帶來的 fontTable（Map<name, FontEntry>）。
   *
   * 用途:當主 family fetch 失敗（404 / network error / 超時）且 fontTable[family].altName 存在時、
   * 自動 retry altName 一次。OOXML §17.8 規定 altName 是「Word 主 family 缺失時的官方建議替代」、
   * 比 caller-side 通用 CJK fallback chain（思源黑體 / 微軟正黑體）更精準。
   *
   * 不傳 → 行為與 Sprint 64b 完全一致（無 altName retry、純 fetch + silent fallback）。
   */
  fontTable?: FontTable;
}

/**
 * 載入指定 family list 並回 adapter。
 *
 * 用法：
 *   const adapter = await loadFontsAndBuildAdapter(['標楷體', 'Times New Roman']);
 *   pipeline.render(buf, container, { fontAdapter: adapter });
 */
export async function loadFontsAndBuildAdapter(
  families: string[],
  opts: FontLoaderOptions = {},
): Promise<FontMetricsAdapter> {
  const adapter = opts.adapter ?? new FontMetricsAdapter();
  const endpoint = opts.endpoint ?? DEFAULT_ENDPOINT;
  const timeout = opts.fetchTimeoutMs ?? 10000;
  const fontTable = opts.fontTable;

  // 並行載入所有 family（IDB lookup + 可能的 fetch + Sprint 157 altName retry）
  await Promise.all(
    families.map(async (family) => {
      try {
        let bytes = await getOrFetchFontBytes(family, endpoint, timeout);

        // Sprint 157:主 family 取不到 → 試 fontTable[family].altName（若存在）
        // 註冊時用「主 family」name、讓 caller 仍以原 family 名查詢
        if (!bytes && fontTable) {
          const entry = fontTable.get(family);
          const altName = entry?.altName;
          if (altName && altName !== family) {
            bytes = await getOrFetchFontBytes(altName, endpoint, timeout);
          }

          // Sprint 166:主 + altName 都失敗、且 family 經 charset 判定為 CJK 字型
          // → 依序試通用 CJK fallback chain（跳過已試過的主 family / altName）
          if (!bytes && entry && isCjkFont(entry)) {
            for (const fallback of CJK_FALLBACK_CHAIN) {
              if (fallback === family || fallback === altName) continue;
              bytes = await getOrFetchFontBytes(fallback, endpoint, timeout);
              if (bytes) break;
            }
          }
        }

        if (bytes) {
          adapter.registerFont(family, new Uint8Array(bytes));
        }
      } catch {
        // silent fallback — adapter 未註冊該 family、pipeline 自動 fallback EstimateMetrics
      }
    }),
  );

  return adapter;
}

/**
 * 從 IDB cache 取或 fetch 後存 IDB 並回 ArrayBuffer。
 * 任一階段失敗回 null。
 */
async function getOrFetchFontBytes(
  family: string,
  endpoint: string,
  timeout: number,
): Promise<ArrayBuffer | null> {
  // 1. IDB lookup
  try {
    const cached = await idbGet(family);
    if (cached) return cached;
  } catch {
    // IDB unavailable（private mode / quota）— 繼續嘗試 fetch、但 fetch 結果存不進 IDB
  }

  // 2. fetch
  try {
    const url = `${endpoint}/${encodeURIComponent(family)}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) return null;
    const buf = await resp.arrayBuffer();
    // 3. 寫 IDB（失敗也不影響本次回傳）
    idbPut(family, buf).catch(() => {});
    return buf;
  } catch {
    return null;
  }
}

// ────────────────────────────────────────────────────────────────────────────
// IDB helpers（簡化版，沒有 LRU；font bytes 變動少、簡單 key=family 即可）
// ────────────────────────────────────────────────────────────────────────────

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IDB not available'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('IDB open failed'));
    req.onblocked = () => reject(new Error('IDB open blocked'));
  });
}

async function idbGet(family: string): Promise<ArrayBuffer | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const req = tx.objectStore(STORE).get(family);
    req.onsuccess = () => resolve((req.result as ArrayBuffer | undefined) ?? null);
    req.onerror = () => reject(req.error);
  });
}

async function idbPut(family: string, bytes: ArrayBuffer): Promise<void> {
  const db = await openDb();
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put(bytes, family);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** 測試 / 強制重新 fetch 用。生產環境通常不會用。 */
export async function clearFontCache(): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // IDB unavailable — clear is no-op
  }
}
