/**
 * Sprint 280 — ShapingFontChain：browser/Node 通用 fetch + fallback chain
 *
 * 把字型 byte buffer 載入 ShapingEngine 的 caller-side helper。對應規畫書
 * §Phase 2.1 字型載入器（browser 端）需求；與 Sprint 64b font_loader.ts 互補
 * （後者走 canvas-editor 的 FontMetricsAdapter + IDB cache、針對 Odoo 端點
 *  /dobtor/fonts/<family>）。
 *
 * 設計：
 *   - 純 fetch（global.fetch、Node 18+ 與 browser 皆原生支援）
 *   - 不做 IDB cache（caller 可額外包一層；fetch 本身有 HTTP cache）
 *   - Primary fetch 失敗 → 依序試 fallback chain（任何 throw / non-2xx 視為失敗）
 *   - 任一成功 → engine.loadFont(primary.family, bytes) 註冊；caller 仍以原 family 查詢
 *   - 全失敗 → throw FontChainExhaustedError
 *
 * 為何 register under primary.family（不是實際載入成功的 family）：
 *   - shape() caller 端 RunProps.fontFamily 不變、不需知道 fallback 鏈替換
 *   - 與 Sprint 157/166 既有 font_loader.ts 行為一致
 *
 * 紀律 #21：本模組不依賴 OoxmlParser / Layout / Render；純獨立 loader、
 * caller-side wire-up（同 Sprint 64b font_loader.ts 定位）。
 */

import type { ShapingEngine } from './ShapingEngine';

/** Chain 內單一字型 entry。 */
export interface ShapingFontChainEntry {
  /** 字型家族名（shape() 端 RunProps.fontFamily 對應） */
  family: string;
  /** 字型檔 URL（HTTP/HTTPS、fetch 取 ArrayBuffer） */
  url: string;
}

export interface LoadShapingFontWithChainOptions {
  /** Target engine（caller 須已 init、可能含 setHbModuleLoader 注入） */
  engine: ShapingEngine;
  /** 首選字型（chain 首位） */
  primary: ShapingFontChainEntry;
  /** Optional fallback chain（primary fail 後依序試） */
  fallbacks?: readonly ShapingFontChainEntry[];
  /** 單次 fetch 超時（ms），預設 10000 */
  timeoutMs?: number;
  /** 注入 fetch（測試用）；預設用 global.fetch */
  fetchImpl?: typeof fetch;
  /** 注入 console.warn（測試用）；預設用 globalThis.console.warn */
  warn?: (msg: string) => void;
}

export interface LoadShapingFontResult {
  /** 註冊到 engine 的 family（= primary.family、即使實際載入的是 fallback） */
  loadedAs: string;
  /** 實際載入成功的 chain entry */
  loadedFrom: ShapingFontChainEntry;
  /** 載入的字型 byte */
  bytes: Uint8Array;
  /** Chain 中試過的 entry 數（含成功那一個） */
  attemptedCount: number;
}

/** 全 chain 都失敗時拋此 error。 */
export class FontChainExhaustedError extends Error {
  constructor(
    public readonly primary: ShapingFontChainEntry,
    public readonly fallbacks: readonly ShapingFontChainEntry[],
    public readonly errors: readonly Error[],
  ) {
    super(
      `FontChainExhaustedError: primary=${primary.family}(${primary.url}) + ${fallbacks.length} fallback(s) 全部失敗`
    );
    this.name = 'FontChainExhaustedError';
  }
}

/**
 * Fetch primary、若失敗依序 fallback、第一個成功 register 到 engine.loadFont。
 *
 * @throws FontChainExhaustedError 全 chain 失敗時
 */
export async function loadShapingFontWithChain(
  opts: LoadShapingFontWithChainOptions,
): Promise<LoadShapingFontResult> {
  const {
    engine,
    primary,
    fallbacks = [],
    timeoutMs = 10000,
    fetchImpl = globalThis.fetch?.bind(globalThis),
    warn = (msg) => globalThis.console?.warn?.(msg),
  } = opts;
  if (typeof fetchImpl !== 'function') {
    throw new Error('ShapingFontChain: global.fetch unavailable; provide opts.fetchImpl');
  }

  const chain: readonly ShapingFontChainEntry[] = [primary, ...fallbacks];
  const errors: Error[] = [];
  let attempted = 0;
  for (const entry of chain) {
    attempted++;
    try {
      const bytes = await fetchFontBytes(entry.url, timeoutMs, fetchImpl);
      // Register under PRIMARY family name (Sprint 157/166 既有行為)
      engine.loadFont(primary.family, bytes);
      if (entry !== primary) {
        warn(`[ShapingFontChain] primary "${primary.family}"(${primary.url}) 失敗、fallback "${entry.family}"(${entry.url}) 成功、註冊為 "${primary.family}"`);
      }
      return { loadedAs: primary.family, loadedFrom: entry, bytes, attemptedCount: attempted };
    } catch (e) {
      errors.push(e instanceof Error ? e : new Error(String(e)));
      // 繼續試下一個
    }
  }
  throw new FontChainExhaustedError(primary, fallbacks, errors);
}

async function fetchFontBytes(
  url: string,
  timeoutMs: number,
  fetchImpl: typeof fetch,
): Promise<Uint8Array> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetchImpl(url, { signal: controller.signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText} @ ${url}`);
    const ab = await resp.arrayBuffer();
    return new Uint8Array(ab);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Sprint 280：常見 CJK fallback chain（對應 Sprint 166 font_loader.ts
 * CJK_FALLBACK_CHAIN）。
 *
 * 用法：
 * ```ts
 * const chain = getDefaultCjkFallbackChain((family) => `/static/fonts/${family}.ttf`);
 * await loadShapingFontWithChain({ engine, primary: { family: '微軟正黑體', url: 'https://...' }, fallbacks: chain });
 * ```
 *
 * @param urlBuilder 給 family name 回 URL（caller 控 endpoint / encoding）
 */
export function getDefaultCjkFallbackChain(
  urlBuilder: (family: string) => string,
): readonly ShapingFontChainEntry[] {
  const families = ['思源黑體', '微軟正黑體', '新細明體'];
  return families.map((family) => ({ family, url: urlBuilder(family) }));
}
