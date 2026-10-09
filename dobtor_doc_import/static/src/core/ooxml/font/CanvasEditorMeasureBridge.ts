/**
 * CanvasEditorMeasureBridge — Sprint 303。
 *
 * Follow-up to Sprint 302 PROBE 第三輪深推。Sprint 302 提供 TextMeasureProxy
 * sync/async bridge 解 ctx.measureText sync 與 measureRun async 不相容問題；
 * 本 sprint 補：
 *
 *   1. Canvas-shape API：`measureText(text) → TextMetricsLike`（不是 `{ widthPt }`），
 *      caller 拿到的形狀與 Browser native `ctx.measureText` 相容、可以 drop-in
 *      取代 canvas-editor 內部 measureText 呼叫
 *
 *   2. pt → px 轉換：caller 拿 `ctx.fillText` / `ctx.measureText` 都是 px、
 *      ShapingEngine.measureRun 回 pt；bridge 統一在此換算
 *
 *   3. `prewarmFromAst(doc)` helper：遍歷 DocumentNode 收集 unique (text, family,
 *      sizePt) tuples、給 caller 一次 batch prewarm（取代 caller 自己 walk AST）
 *
 * 紀律 #18 scope-down：
 *   - 不接 canvas-editor real path（紀律 #21、同 Sprint 302）
 *   - 不支援 letter-spacing / 變寬字型 axis settings 等進階屬性
 *   - TextMetricsLike 只回 width（不模擬完整 TextMetrics 物件 actualBoundingBox*
 *     等屬性—canvas-editor 不消費這些；caller 真用到時 follow-up extend）
 *
 * 紀律 #21：pure-fn / class、不污染既有 canvas-editor / parser 路徑。
 */

import { TextMeasureProxy } from './TextMeasureProxy';
import type { MeasureRunFn, TextMeasureProxyOptions } from './TextMeasureProxy';
import type {
  DocumentNode,
  ParagraphNode,
  TableNode,
  BlockNode,
  RunNode,
} from '../ast/types';

/**
 * 96 dpi 下 1pt = 1/72 inch、1px = 1/96 inch → 1pt = 96/72 = 4/3 px。
 * caller 可在 constructor 覆寫 dpi 對應到別的設備。
 */
const PT_TO_PX_AT_96DPI = 4 / 3;

/**
 * Canvas-shape TextMetrics 子集（只回 width）。
 *
 * 與 browser native `TextMetrics` 同形狀；canvas-editor / ctx.measureText 主要
 * 消費 `.width`，故本 PROBE 只回此欄位。caller 真用到 actualBoundingBox* 時
 * 可 follow-up extend。
 */
export interface TextMetricsLike {
  /** width in **px**（不是 pt） */
  width: number;
}

export interface CanvasEditorMeasureBridgeOptions {
  /**
   * caller 可指定 dpi 覆寫 96。Sprint 297 audit 顯示 canvas-editor 預設用 96 dpi、
   * 但 Retina / 高 dpi 螢幕 caller 可能想用 192。
   */
  dpi?: number;
  /** TextMeasureProxy options（cache 容量等）passthrough */
  proxyOptions?: TextMeasureProxyOptions;
}

/**
 * AST walker collects unique (text, family, sizePt) tuples for prewarm。
 *
 * 同 family + sizePt + text 的 cache key 不重複；不同段落同字串只 measure 一次。
 */
function collectMeasureRequests(
  doc: DocumentNode,
  defaultFamily: string,
  defaultSizePt: number,
): Array<{ text: string; family: string; sizePt: number }> {
  const seen = new Set<string>();
  const out: Array<{ text: string; family: string; sizePt: number }> = [];
  for (const s of doc.sections) {
    for (const b of s.body) {
      collectFromBlock(b, defaultFamily, defaultSizePt, seen, out);
    }
  }
  return out;
}

function collectFromBlock(
  b: BlockNode,
  defaultFamily: string,
  defaultSizePt: number,
  seen: Set<string>,
  out: Array<{ text: string; family: string; sizePt: number }>,
): void {
  if (b.type === 'paragraph') {
    collectFromParagraph(b, defaultFamily, defaultSizePt, seen, out);
  } else {
    for (const row of b.rows) {
      for (const cell of row.cells) {
        for (const inner of cell.content) {
          collectFromBlock(inner, defaultFamily, defaultSizePt, seen, out);
        }
      }
    }
  }
}

function collectFromParagraph(
  p: ParagraphNode,
  defaultFamily: string,
  defaultSizePt: number,
  seen: Set<string>,
  out: Array<{ text: string; family: string; sizePt: number }>,
): void {
  for (const r of p.runs) {
    if (r.type !== 'run') continue;
    const run = r as RunNode;
    if (!run.text) continue;
    const family = run.props.fontFamily ?? defaultFamily;
    const sizePt = run.props.fontSize ?? defaultSizePt;
    const key = `${family}|${sizePt}|${run.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ text: run.text, family, sizePt });
  }
}

/**
 * Canvas-shape adapter on top of TextMeasureProxy。
 *
 * 用法：
 *   const engine = new ShapingEngine();
 *   const bridge = new CanvasEditorMeasureBridge(engine.measureRun.bind(engine));
 *   await bridge.prewarmFromAst(doc, 'DejaVuSans', 12);
 *   const m = bridge.measureText('Hello', 'DejaVuSans', 12);
 *   ctx.fillText('Hello', m.width, 0);
 */
export class CanvasEditorMeasureBridge {
  private readonly proxy: TextMeasureProxy;
  private readonly ptToPx: number;

  constructor(measureRun: MeasureRunFn, opts: CanvasEditorMeasureBridgeOptions = {}) {
    this.proxy = new TextMeasureProxy(measureRun, opts.proxyOptions);
    const dpi = opts.dpi ?? 96;
    this.ptToPx = (PT_TO_PX_AT_96DPI * dpi) / 96;
  }

  /**
   * Canvas-shape sync measure。cache hit 回 px width；cache miss 回 null
   * （caller 自行 fallback ctx.measureText）。
   */
  measureText(text: string, family: string, sizePt: number): TextMetricsLike | null {
    const entry = this.proxy.measureSync(text, family, sizePt);
    if (!entry) return null;
    return { width: entry.widthPt * this.ptToPx };
  }

  /** Async：caller 沒先 prewarm 也能直接 await 取結果。 */
  async measureTextAsync(text: string, family: string, sizePt: number): Promise<TextMetricsLike> {
    const entry = await this.proxy.measureAsync(text, family, sizePt);
    return { width: entry.widthPt * this.ptToPx };
  }

  /**
   * 遍歷整份 DocumentNode、收集 unique (text, family, sizePt) 並 batch prewarm。
   *
   * defaultFamily / defaultSizePt：當 RunNode.props.fontFamily / sizePt 未指定時
   * 套用的 fallback（caller 應與 LayoutPipeline 一致、否則 measure cache 與 layout
   * 不命中）。
   */
  async prewarmFromAst(doc: DocumentNode, defaultFamily: string, defaultSizePt: number): Promise<number> {
    const requests = collectMeasureRequests(doc, defaultFamily, defaultSizePt);
    await this.proxy.prewarm(requests);
    return requests.length;
  }

  /** Stats passthrough（hit / miss / hitRate / size）。 */
  stats(): { size: number; hits: number; misses: number; hitRate: number } {
    return this.proxy.stats();
  }

  /** Clear（字型熱更新或測試重置）。 */
  clear(): void {
    this.proxy.clear();
  }
}
