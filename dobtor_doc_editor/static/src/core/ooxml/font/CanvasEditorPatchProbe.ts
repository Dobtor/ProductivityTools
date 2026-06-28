/**
 * CanvasEditorPatchProbe — Sprint 308 PROBE。
 *
 * Sprint 303 CanvasEditorMeasureBridge 第二輪。Sprint 303 提供 Canvas-shape
 * `measureText(text) → { width }`，caller 須顯式呼叫；本 sprint PROBE **如何
 * 把 bridge 接管 caller 的 ctx.measureText**（無需 caller 改 call site）。
 *
 * 三種 patch 策略 PROBE：
 *
 *   1. **Object override**：直接 `ctx.measureText = patched`（簡單、但只影響
 *      該 ctx instance；新建 ctx 不受影響）
 *
 *   2. **Prototype patch**：修改 `CanvasRenderingContext2D.prototype.measureText`
 *      （全 ctx 都接管、但 global side effect 危險）
 *
 *   3. **Wrap factory**：caller 必須過 `wrapCanvasContext(ctx, bridge)` 才生效；
 *      不污染 global、但 caller 須顯式呼叫
 *
 * 紀律 #18 scope-down：
 *   - 紀律 #21：production 路徑不 prototype patch（會破 canvas-editor 主程式）；
 *     本 PROBE 只提供 instance-level wrap factory 為 production-grade 選項
 *   - 不接 canvas-editor real path（與 Sprint 302/303 同政策）
 *   - 不模擬完整 TextMetrics（caller 真用到時 follow-up）
 *
 * 用法（caller 顯式 opt-in）：
 *   const wrapped = wrapCanvasContext(originalCtx, bridge, 'DejaVuSans', 12);
 *   wrapped.measureText('Hello')  → { width: px }
 *     - bridge cache hit → 用 bridge 結果
 *     - bridge cache miss → fallback 到 originalCtx.measureText
 *
 * 紀律 #21：caller 顯式呼叫才生效、不污染 prototype；caller 完全控制接管範圍。
 */

import type { CanvasEditorMeasureBridge, TextMetricsLike } from './CanvasEditorMeasureBridge';

/**
 * 最小化 Canvas2D context interface（避免 import 完整 CanvasRenderingContext2D
 * 型別、減少 module 體積與 typecheck 限制）。
 */
export interface MinimalCanvasContextForPatch {
  measureText(text: string): TextMetricsLike;
  /** 其他屬性 caller 透過 Proxy 透傳；本 patch 不關心 */
  [k: string]: unknown;
}

export interface WrapCanvasContextOptions {
  /**
   * 預設 font family（caller 若沒在 ctx 設定 font 時 fallback 用）。
   * 對應 Sprint 303 prewarmFromAst 的 defaultFamily。
   */
  defaultFamily: string;
  /** 預設 font size pt */
  defaultSizePt: number;
  /**
   * 當 bridge cache miss 時是否 fallback 到 original ctx.measureText。
   * - 預設 true：cache miss 退化 native measureText（行為 unchanged）
   * - false：cache miss 回 { width: 0 }（caller 想偵測 prewarm 漏洞時用）
   */
  fallbackToNative?: boolean;
}

export interface PatchProbeStats {
  /** bridge 命中（用 bridge 結果回） */
  bridgeHits: number;
  /** bridge miss 但 fallback 到 native */
  nativeFallbacks: number;
  /** bridge miss 且不 fallback、回 { width: 0 } */
  zeroFallbacks: number;
}

/**
 * Wrap factory：取 ctx + bridge，回新 ctx-like 物件、其 measureText 走 bridge cache。
 *
 * 不 mutate 原 ctx；caller 拿到的 wrapped object 是 light proxy，其他屬性/方法
 * 都透傳給原 ctx。
 */
export function wrapCanvasContext(
  ctx: MinimalCanvasContextForPatch,
  bridge: CanvasEditorMeasureBridge,
  opts: WrapCanvasContextOptions,
): MinimalCanvasContextForPatch & { __patchProbeStats: PatchProbeStats } {
  const stats: PatchProbeStats = { bridgeHits: 0, nativeFallbacks: 0, zeroFallbacks: 0 };
  const fallbackToNative = opts.fallbackToNative ?? true;

  // 使用 ES Proxy 透傳；非 measureText 的存取都 forward 給原 ctx
  const handler: ProxyHandler<MinimalCanvasContextForPatch> = {
    get(target, prop, receiver) {
      if (prop === '__patchProbeStats') return stats;
      if (prop === 'measureText') {
        return (text: string): TextMetricsLike => {
          const m = bridge.measureText(text, opts.defaultFamily, opts.defaultSizePt);
          if (m) {
            stats.bridgeHits++;
            return m;
          }
          if (fallbackToNative) {
            stats.nativeFallbacks++;
            return target.measureText(text);
          }
          stats.zeroFallbacks++;
          return { width: 0 };
        };
      }
      return Reflect.get(target, prop, receiver);
    },
    set(target, prop, value) {
      // 透傳：caller 對 wrapped ctx 設 fillStyle 等屬性 → 也寫進原 ctx
      return Reflect.set(target, prop, value);
    },
  };
  return new Proxy(ctx, handler) as MinimalCanvasContextForPatch & { __patchProbeStats: PatchProbeStats };
}

/**
 * 偵測「目前環境是否可安全做 prototype patch」。
 *
 * 回 false 時 caller 千萬別走 prototype 路徑：
 *   - Node 環境（沒有 CanvasRenderingContext2D）
 *   - 已被別人 patch 過（measureText 不是 native function）
 *
 * 回 true 也只是「能 patch」、不代表「該 patch」；caller 自負後果。
 */
export function canSafelyPatchPrototype(): boolean {
  const g = globalThis as { CanvasRenderingContext2D?: { prototype: { measureText: unknown } } };
  if (!g.CanvasRenderingContext2D) return false;
  const m = g.CanvasRenderingContext2D.prototype.measureText;
  if (typeof m !== 'function') return false;
  // native function 的 .toString() 通常含 [native code]
  const src = Function.prototype.toString.call(m);
  return src.includes('[native code]');
}
