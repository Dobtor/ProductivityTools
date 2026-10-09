/**
 * Phase 2.1-2.3 整合 façade — Sprint 288。
 *
 * 把 Sprint 277 LineBreaker + Sprint 265-268 ShapingEngine + Sprint 268 FontMetrics
 * + Sprint 280 ShapingFontChain 接成單一 production-grade 入口，給 Phase 6 自寫
 * Layout 消費。
 *
 * 設計：
 *   - 純函式 façade、無內部全域狀態（caller 自管 engine lifecycle、避免泄漏）
 *   - 兩個 entry：
 *       1. `layoutParagraph` — 拿已 loaded font 的 engine + family → lines + metrics
 *       2. `layoutParagraphWithFontChain` — 拿 fontChain（primary + fallbacks）+ url builder
 *          → 自動 fetch、loadFont、layoutParagraph
 *
 * 紀律 #18 scope-down：不接 canvas-editor、不取代 ctx.measureText（與 Sprint 277
 * LineBreaker 一致；production canvas-editor 整合屬 Phase 6 完整 Layout 範圍）。
 *
 * 紀律 #21：本 façade 為 read-only 量測 API、無 side effect、不污染 VR pipeline。
 *
 * Phase 6 完整 Layout 才會擴充：mixed run / kerning / Knuth-Plass / hyphenation /
 * CJK justification / bidi（LineBreaker 既有 scope-down 同步沿用）。
 */

import { breakParagraph } from './LineBreaker';
import type { BrokenLine } from './LineBreaker';
import type { ShapingEngine } from '../font/ShapingEngine';
import {
  readFontMetrics,
  resolveOoxmlLineHeight,
  baselineOffsetPt,
} from '../font/FontMetrics';
import type {
  FontMetricsResult,
  OoxmlLineHeightResult,
} from '../font/FontMetrics';
import { loadShapingFontWithChain } from '../font/ShapingFontChain';
import type {
  ShapingFontChainEntry,
  LoadShapingFontResult,
} from '../font/ShapingFontChain';

/**
 * 整合 layout 結果：lines（已換行）+ 行高/基線（給上層排版器 vertical advance 用）。
 */
export interface ParagraphLayoutResult {
  /** 換行後的 lines（每行含 text/widthPt/words） */
  lines: BrokenLine[];
  /** 最大 line 寬度（pt、空輸入時 0） */
  maxLineWidthPt: number;
  /** 行數別名 */
  totalLines: number;
  /** OOXML 規則套用後的最終行高（pt） */
  lineHeightPt: number;
  /** Sprint 267 行高解析詳情（含 rule / naturalHeightPt / lineValue） */
  lineHeight: OoxmlLineHeightResult;
  /** 基線從 line top 算下的 pt 偏移 */
  baselineOffsetPt: number;
  /** 字型 metrics（caller 若需 ascent/descent 細節可直接取） */
  fontMetrics: FontMetricsResult;
}

/** layoutParagraph 輸入。 */
export interface LayoutParagraphOptions {
  /** 段落原始字串 */
  text: string;
  /** 可用換行寬度（pt） */
  availableWidthPt: number;
  /** 字型家族（必須與 engine 已 loadFont 註冊的 family 名一致） */
  fontFamily: string;
  /** 字級（pt） */
  sizePt: number;
  /** 字型 bytes（給 FontMetrics 讀 metrics；caller 通常與餵給 engine 的同來源） */
  fontBytes: Uint8Array | ArrayBuffer;
  /** OOXML w:line rule（auto / exact / atLeast；缺省為 'natural' = 純字型 metrics） */
  lineRule?: 'auto' | 'exact' | 'atLeast';
  /**
   * OOXML w:line value（auto = multiplier；exact/atLeast = pt）。
   * lineRule 給但 lineValue 缺 → 回 natural（與 resolveOoxmlLineHeight 規格一致）。
   */
  lineValue?: number;
  /**
   * 可選：space 字元寬度（pt）。給已知 metrics 注入避免 await wasm shape；
   * 不給則由 LineBreaker 用 engine.measureRun(' ') 即時取。
   */
  spaceWidthPt?: number;
}

/**
 * Phase 2 整合主入口：給 engine（已 loadFont）+ fontBytes（給 FontMetrics）→ 完整 layout。
 *
 * 順序：
 *   1. readFontMetrics(fontBytes) → metrics
 *   2. resolveOoxmlLineHeight(metrics, sizePt, lineRule, lineValue) → lineHeight
 *   3. baselineOffsetPt(metrics, sizePt, lineHeight.heightPt) → baseline
 *   4. breakParagraph(engine, ...) → lines
 *
 * 為何 fontBytes 與 engine 解耦：
 *   - engine.loadFont 把 bytes 餵給 hb-wasm（不會留 ArrayBuffer 副本回傳）；caller
 *     若想 readFontMetrics 仍要原始 bytes、外部傳入較單純
 *   - 也支援「engine 上裝 family A + metrics 用 family B 的 bytes」這種診斷場景
 */
export async function layoutParagraph(
  engine: ShapingEngine,
  opts: LayoutParagraphOptions,
): Promise<ParagraphLayoutResult> {
  const fontMetrics = readFontMetrics(opts.fontBytes);
  const lineHeight = resolveOoxmlLineHeight(
    fontMetrics,
    opts.sizePt,
    opts.lineRule,
    opts.lineValue,
  );
  const baseline = baselineOffsetPt(fontMetrics, opts.sizePt, lineHeight.heightPt);
  const breakResult = await breakParagraph(engine, {
    text: opts.text,
    availableWidthPt: opts.availableWidthPt,
    fontFamily: opts.fontFamily,
    sizePt: opts.sizePt,
    spaceWidthPt: opts.spaceWidthPt,
  });
  return {
    lines: breakResult.lines,
    maxLineWidthPt: breakResult.maxLineWidthPt,
    totalLines: breakResult.totalLines,
    lineHeightPt: lineHeight.heightPt,
    lineHeight,
    baselineOffsetPt: baseline,
    fontMetrics,
  };
}

// ── 進階入口：fontChain（primary + fallbacks）+ URL 自動 fetch ──────────────────

/** layoutParagraphWithFontChain 輸入。 */
export interface LayoutParagraphWithFontChainOptions {
  text: string;
  availableWidthPt: number;
  sizePt: number;
  /** primary font（必填、最終 family 名以此為準） */
  primary: ShapingFontChainEntry;
  /** fallback chain（可空） */
  fallbacks?: readonly ShapingFontChainEntry[];
  /** 全域 fetch；Node 環境 caller 須注入 */
  fetchImpl?: typeof fetch;
  /** fetch timeout（ms、預設 10000） */
  timeoutMs?: number;
  /** warning callback（fallback 觸發時收到 message） */
  warn?: (msg: string) => void;
  lineRule?: 'auto' | 'exact' | 'atLeast';
  lineValue?: number;
  spaceWidthPt?: number;
}

/** layoutParagraphWithFontChain 結果（在 ParagraphLayoutResult 之上加 chain info）。 */
export interface ParagraphLayoutWithChainResult extends ParagraphLayoutResult {
  /** ShapingFontChain 的 load 結果（含 loadedFrom / attemptedCount） */
  fontLoad: LoadShapingFontResult;
}

/**
 * 進階：fontChain + URL fetch 自動化版本。
 *
 * 流程：
 *   1. loadShapingFontWithChain(engine, ...) → 沿 chain 試到第一個 fetch+load 成功的 font
 *   2. 拿 bytes 直接 layoutParagraph(engine, ...)
 *
 * Caller 須先建好 engine（hbModuleLoader 已設或預設 Node 路徑可用）。本函式
 * 不管 engine 生命週期、不 reset。
 */
export async function layoutParagraphWithFontChain(
  engine: ShapingEngine,
  opts: LayoutParagraphWithFontChainOptions,
): Promise<ParagraphLayoutWithChainResult> {
  const fontLoad = await loadShapingFontWithChain({
    engine,
    primary: opts.primary,
    fallbacks: opts.fallbacks ?? [],
    timeoutMs: opts.timeoutMs,
    fetchImpl: opts.fetchImpl,
    warn: opts.warn,
  });
  const layout = await layoutParagraph(engine, {
    text: opts.text,
    availableWidthPt: opts.availableWidthPt,
    fontFamily: fontLoad.loadedAs,
    sizePt: opts.sizePt,
    fontBytes: fontLoad.bytes,
    lineRule: opts.lineRule,
    lineValue: opts.lineValue,
    spaceWidthPt: opts.spaceWidthPt,
  });
  return { ...layout, fontLoad };
}
