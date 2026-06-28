/**
 * TextMeasureProxy — Sprint 302 PROBE。
 *
 * Follow-up to Sprint 269/275/297 honest gap「LayoutPipeline 未接 canvas-editor
 * （Phase 6 自寫 Layout 完整範圍）」第二輪深推。
 *
 * 為何要 proxy：
 *   - canvas-editor（與 native Canvas2D）的 `ctx.measureText(text)` 是 **同步**
 *     回 TextMetrics、回 width 用於行內 wrap / cursor 定位 / IME 重繪。
 *   - ShapingEngine.measureRun() 為 **非同步**（HarfBuzz WASM lazy 載入 + async
 *     shape）；無法直接 drop-in 給 canvas-editor 取代 ctx.measureText。
 *
 * 解：兩階段 cache pattern
 *   1. caller pre-warm（async）：proxy.prewarm([(text, family, sizePt), ...])
 *      → 每筆呼叫 engine.measureRun 並寫進內部 Map
 *   2. canvas-editor 同步呼叫：proxy.measureSync(text, family, sizePt)
 *      → cache hit 回 widthPt（轉 px 後可直接給 ctx）
 *      → cache miss 回 null（caller 自行 fallback 到 ctx.measureText）
 *
 * 範圍（PROBE）：
 *   - 不接 canvas-editor 真實 measureText override（caller 顯式呼叫才生效）
 *   - 不取代 ctx.measureText（紀律 #21、避免破現有 canvas-editor 路徑）
 *   - 為 Phase 6 / future canvas-editor patch sprint 探路用
 *
 * 紀律 #18 scope-down：
 *   - LRU evict 簡化為 FIFO（與 Sprint 266 Glyph cache 同政策）
 *   - 不支援字元級 letter-spacing / kerning（measureRun 已包含）
 *   - prewarm 必須 caller 提供完整字串；不嘗試自動拆字（caller 比 proxy 更
 *     懂自己需要 measure 哪些字串）
 */

import type { RunMetrics } from './ShapingEngine';

/** 提供 measureRun 的最小 interface（避免本 module 強耦合 ShapingEngine 全部 API）。 */
export interface MeasureRunFn {
  (text: string, family: string, sizePt: number): Promise<RunMetrics>;
}

export interface TextMeasureProxyOptions {
  /** Cache 容量上限；超過時 FIFO 淘汰最舊項。預設 1024。 */
  maxEntries?: number;
}

export interface TextMeasureCacheEntry {
  widthPt: number;
  heightPt: number;
  glyphCount: number;
}

const DEFAULT_MAX_ENTRIES = 1024;

function makeKey(text: string, family: string, sizePt: number): string {
  return `${family}|${sizePt}|${text}`;
}

/**
 * Sync 介面、由 caller pre-warm 異步 measureRun 後填入。
 *
 * 用法：
 *   const proxy = new TextMeasureProxy(engine.measureRun.bind(engine));
 *   await proxy.prewarm([
 *     { text: 'Hello', family: 'DejaVuSans', sizePt: 12 },
 *     { text: 'World', family: 'DejaVuSans', sizePt: 12 },
 *   ]);
 *   const result = proxy.measureSync('Hello', 'DejaVuSans', 12);
 *   // result = { widthPt: ..., heightPt: ..., glyphCount: ... }
 */
export class TextMeasureProxy {
  private readonly measureRun: MeasureRunFn;
  private readonly cache = new Map<string, TextMeasureCacheEntry>();
  private readonly maxEntries: number;
  private hits = 0;
  private misses = 0;

  constructor(measureRun: MeasureRunFn, opts: TextMeasureProxyOptions = {}) {
    this.measureRun = measureRun;
    this.maxEntries = opts.maxEntries ?? DEFAULT_MAX_ENTRIES;
  }

  /**
   * 同步取 cache、未命中回 null（caller 自行 fallback）。
   *
   * 不副作用、不觸發 async measureRun（同步介面）。
   */
  measureSync(text: string, family: string, sizePt: number): TextMeasureCacheEntry | null {
    const key = makeKey(text, family, sizePt);
    const entry = this.cache.get(key);
    if (entry) {
      this.hits++;
      return entry;
    }
    this.misses++;
    return null;
  }

  /** 異步：caller 顯式 prewarm 一批 (text, family, sizePt) 三元組進 cache。 */
  async prewarm(
    entries: ReadonlyArray<{ text: string; family: string; sizePt: number }>,
  ): Promise<void> {
    for (const { text, family, sizePt } of entries) {
      const key = makeKey(text, family, sizePt);
      if (this.cache.has(key)) continue; // 已存在不重 measure
      const metrics = await this.measureRun(text, family, sizePt);
      this.setEntry(key, {
        widthPt: metrics.widthPt,
        heightPt: metrics.heightPt,
        glyphCount: metrics.glyphCount,
      });
    }
  }

  /** 異步：單字串 measure-or-cache（給 caller 想動態 incremental warm 用）。 */
  async measureAsync(text: string, family: string, sizePt: number): Promise<TextMeasureCacheEntry> {
    const cached = this.measureSync(text, family, sizePt);
    if (cached) return cached;
    const metrics = await this.measureRun(text, family, sizePt);
    const entry: TextMeasureCacheEntry = {
      widthPt: metrics.widthPt,
      heightPt: metrics.heightPt,
      glyphCount: metrics.glyphCount,
    };
    this.setEntry(makeKey(text, family, sizePt), entry);
    return entry;
  }

  /** 清除全部 cache（字型熱更新或單元測試重置用）。 */
  clear(): void {
    this.cache.clear();
    this.hits = 0;
    this.misses = 0;
  }

  /** Stats 介面：caller 觀察 hit / miss 比例（Sprint 269 Phase 2 Exit 量測同政策）。 */
  stats(): { size: number; hits: number; misses: number; hitRate: number } {
    const total = this.hits + this.misses;
    return {
      size: this.cache.size,
      hits: this.hits,
      misses: this.misses,
      hitRate: total === 0 ? 0 : this.hits / total,
    };
  }

  private setEntry(key: string, entry: TextMeasureCacheEntry): void {
    if (this.cache.size >= this.maxEntries) {
      // FIFO evict：Map 保證 insertion order，刪第一個 key
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    this.cache.set(key, entry);
  }
}
