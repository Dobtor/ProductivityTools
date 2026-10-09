/**
 * CanvasEditorPipeline — Sprint 318。
 *
 * Sprint 313 CanvasEditorFontResolver + Sprint 303 CanvasEditorMeasureBridge +
 * Sprint 308 CanvasEditorPatchProbe 三者整合層。提供 **單一 API**:
 *
 *   pipeline.measureWithCtxFont(ctx, text)
 *     → 自動 parse ctx.font → 查 bridge cache → cache miss fallback native
 *
 * 用途：caller 接管 canvas-editor 內部的 ctx.measureText 時不再需要：
 *   1. 自己拆 ctx.font 字串
 *   2. 自己決定 bridge family + sizePt
 *   3. 自己處理 cache miss fallback
 *
 * 全部由 pipeline 一次包好。
 *
 * 紀律 #18 scope-down：
 *   - 仍是 PROBE / caller 顯式呼叫才生效（不污染 prototype、不接 real path）
 *   - 不快取 ctx.font 解析結果（每次 measure 重 parse；caller 自管 ctx.font 不頻繁變動時的 cache）
 *   - 不支援 font.style / font.weight 影響 bridge cache key（紀律 #18 簡化）
 *
 * 紀律 #21：composes existing modules、不改既有行為；caller 想用才用。
 */

import type { TextMeasureProxy } from './TextMeasureProxy';
import { CanvasEditorMeasureBridge, type TextMetricsLike } from './CanvasEditorMeasureBridge';
import type { MeasureRunFn } from './TextMeasureProxy';
import { parseCanvasFont, type ResolvedFont } from './CanvasEditorFontResolver';

export interface CanvasEditorPipelineOptions {
  /** 解析 ctx.font 時 fallback baseline；缺省 12pt */
  fallbackSizePt?: number;
  /** font 字串解析失敗時的 family；缺省 'sans-serif' */
  fallbackFamily?: string;
  /** dpi（用於 px → pt 換算）；缺省 96 */
  dpi?: number;
  /** 缺省為 true：cache miss 退化 native ctx.measureText */
  fallbackToNative?: boolean;
}

export interface PipelineStats {
  /** ctx.font 成功 parse 次數 */
  fontParseSuccess: number;
  /** ctx.font parse 失敗（語法錯誤等）退化次數 */
  fontParseFailure: number;
  /** bridge cache hit */
  bridgeHits: number;
  /** bridge cache miss + fallback native */
  nativeFallbacks: number;
}

/**
 * 最小化 Canvas2D context 介面：本 pipeline 只需 `.font` 與 `.measureText`。
 */
export interface CanvasContextForPipeline {
  font: string;
  measureText(text: string): TextMetricsLike;
}

/**
 * 整合 pipeline。Caller 用法：
 *
 *   const pipeline = new CanvasEditorPipeline(engine.measureRun.bind(engine));
 *   await pipeline.prewarmFromAst(doc, 'DejaVu Sans', 12);
 *   ctx.font = "14pt 'Noto Sans CJK TC', sans-serif";
 *   const m = pipeline.measureWithCtxFont(ctx, 'Hello');
 *   // → parse ctx.font, look up bridge cache, fall back to native if miss
 */
export class CanvasEditorPipeline {
  private readonly bridge: CanvasEditorMeasureBridge;
  private readonly fallbackSizePt: number;
  private readonly fallbackFamily: string;
  private readonly dpi: number;
  private readonly fallbackToNative: boolean;
  private stats: PipelineStats = {
    fontParseSuccess: 0,
    fontParseFailure: 0,
    bridgeHits: 0,
    nativeFallbacks: 0,
  };

  constructor(measureRun: MeasureRunFn, opts: CanvasEditorPipelineOptions = {}) {
    this.fallbackSizePt = opts.fallbackSizePt ?? 12;
    this.fallbackFamily = opts.fallbackFamily ?? 'sans-serif';
    this.dpi = opts.dpi ?? 96;
    this.fallbackToNative = opts.fallbackToNative ?? true;
    this.bridge = new CanvasEditorMeasureBridge(measureRun, { dpi: this.dpi });
  }

  /**
   * 解析 ctx.font + 查 bridge cache + fallback native。
   *
   * - ctx.font parse 成功 → 用 parsed family/sizePt 查 bridge
   * - parse 失敗（語法錯）→ 用 fallbackFamily/fallbackSizePt 查 bridge
   * - bridge cache miss + fallbackToNative=true → ctx.measureText
   * - bridge cache miss + fallbackToNative=false → { width: 0 }
   */
  measureWithCtxFont(ctx: CanvasContextForPipeline, text: string): TextMetricsLike {
    const resolved = this.resolveFont(ctx.font);
    const m = this.bridge.measureText(text, resolved.family, resolved.sizePt);
    if (m) {
      this.stats.bridgeHits++;
      return m;
    }
    if (this.fallbackToNative) {
      this.stats.nativeFallbacks++;
      return ctx.measureText(text);
    }
    return { width: 0 };
  }

  /** Sync measure（caller 已知 family/sizePt 時用、繞過 ctx.font parse）。 */
  measureSync(text: string, family: string, sizePt: number): TextMetricsLike | null {
    return this.bridge.measureText(text, family, sizePt);
  }

  /** Async measure（caller 沒先 prewarm 也能直接取）。 */
  async measureAsync(text: string, family: string, sizePt: number): Promise<TextMetricsLike> {
    return this.bridge.measureTextAsync(text, family, sizePt);
  }

  /** Prewarm 整 AST（透過 bridge）。 */
  prewarmFromAst(...args: Parameters<CanvasEditorMeasureBridge['prewarmFromAst']>): Promise<number> {
    return this.bridge.prewarmFromAst(...args);
  }

  /** Underlying bridge proxy（caller 想直接調用底層 proxy 時拿）。 */
  getBridge(): CanvasEditorMeasureBridge {
    return this.bridge;
  }

  /** Pipeline stats（含 font parse 成功率 + bridge hit/miss）。 */
  getStats(): PipelineStats & { bridgeStats: ReturnType<TextMeasureProxy['stats']> } {
    return {
      ...this.stats,
      bridgeStats: this.bridge.stats(),
    };
  }

  clear(): void {
    this.bridge.clear();
    this.stats = { fontParseSuccess: 0, fontParseFailure: 0, bridgeHits: 0, nativeFallbacks: 0 };
  }

  private resolveFont(fontStr: string): ResolvedFont {
    try {
      const parsed = parseCanvasFont(fontStr, { dpi: this.dpi });
      this.stats.fontParseSuccess++;
      return parsed;
    } catch {
      this.stats.fontParseFailure++;
      return { family: this.fallbackFamily, sizePt: this.fallbackSizePt };
    }
  }
}
