/**
 * FontMetrics — 用 opentype.js 讀字型 ascender / descender / lineGap
 *
 * 用途：
 *   行高計算 = (ascent + descent + lineGap) * sizePt / unitsPerEm
 *
 *   canvas-editor 內部用 Browser measureText，不接受外部 metrics；
 *   但 Phase 6 自寫 Layout Engine 需要這個函式正確計算行高。
 *
 * 為何分開於 ShapingEngine：
 *   - opentype.js 是純 JS（無 WASM），體積小很多（~80KB）
 *   - 即使 HarfBuzz WASM 整合失敗，metrics-only 路徑仍可用
 *   - opentype.js 用 require()（CJS）載入，避開 ESM/CJS 互通問題
 *
 * Sprint 14：visual_regression IIFE bundle（瀏覽器）會把 'node:module' alias 成 stub
 *   （見 rollup.visual_regression.config.js）。caller 不呼叫 readFontMetrics 即無感；
 *   呼叫到才會 throw，符合「browser 沒有 opentype.js」的事實。
 */

// Sprint 62：改用直接 ESM import 取代 createRequire；
// 讓 visual_regression IIFE bundle 也能把 opentype.js 包進來、Sprint 62 FontMetricsAdapter
// 真實字型 metric 能在瀏覽器內 work（之前 createRequire('opentype.js') 在 rollup stub 下 throw、
// 全部 registerFont silent-fail → adapter 空 → VR 0.074899 = baseline 不變、揭示假性結果）。
//
// opentype.js v1.3.5 在 package.json 有 module: opentype.mjs（ESM）；rollup resolve + commonjs
// 兩 plugin 處理 default export 互通即可。增加 IIFE bundle size ~80KB。
import * as opentypeNs from 'opentype.js';
const opentype = (opentypeNs as { default?: unknown }).default ?? opentypeNs;

/** 字型核心 metrics（pt 為單位需乘以 sizePt / unitsPerEm） */
export interface FontMetricsResult {
  /** 每 em 的設計單位數（OOXML 規格內字型大小用） */
  unitsPerEm: number;
  /** 基線以上高度 */
  ascender: number;
  /** 基線以下深度（正值） */
  descender: number;
  /** 字型建議的額外行距 */
  lineGap: number;
  /** x-height（小寫 x 高度，OOXML 文字渲染未必用得到，但常被排版引擎查） */
  xHeight?: number;
  /** cap-height（大寫高度） */
  capHeight?: number;
  /**
   * Sprint 268：OS/2 sTypoAscender（Word/Apple 推薦行高源；
   * USE_TYPO_METRICS=1 時 Word 用此值而非 hhea.ascender）。
   */
  typoAscender?: number;
  /** Sprint 268：OS/2 sTypoDescender（正值；原值通常負、本欄已取絕對值）。 */
  typoDescender?: number;
  /** Sprint 268：OS/2 sTypoLineGap。 */
  typoLineGap?: number;
  /** Sprint 268：OS/2 usWinAscent（Windows 推薦上界；用於 clip 偵測）。 */
  winAscent?: number;
  /** Sprint 268：OS/2 usWinDescent（Windows 推薦下界；正值）。 */
  winDescent?: number;
  /** Sprint 268：OS/2 fsSelection bit 0 = italic / bit 5 = bold。 */
  italic?: boolean;
  bold?: boolean;
  /** Sprint 268：OS/2 usWeightClass（100/400/700/...）。 */
  weightClass?: number;
  /** Sprint 268：OS/2 usWidthClass（5=normal）。 */
  widthClass?: number;
  /** Sprint 268：head.macStyle bit 1 = italic / bit 0 = bold（與 OS/2 互校）。 */
  macStyleItalic?: boolean;
  macStyleBold?: boolean;
  /** Sprint 268：hhea.advanceWidthMax（全字型 advance 上界）。 */
  advanceWidthMax?: number;
}

interface OpentypeGlyph {
  advanceWidth?: number;
  unicode?: number;
  index: number;
  name?: string;
}

interface OpentypeGlyphSet {
  length: number;
  get: (index: number) => OpentypeGlyph;
}

interface OpentypeFont {
  unitsPerEm: number;
  ascender: number;
  descender: number;
  tables?: {
    os2?: {
      sxHeight?: number;
      sCapHeight?: number;
      sTypoLineGap?: number;
      sTypoAscender?: number;
      sTypoDescender?: number;
      usWinAscent?: number;
      usWinDescent?: number;
      fsSelection?: number;
      usWeightClass?: number;
      usWidthClass?: number;
    };
    hhea?: { lineGap?: number; advanceWidthMax?: number };
    head?: { macStyle?: number };
  };
  /** Sprint 268：依字元（string、單字元）取 glyph index（無 ligature / 無 substitution）。 */
  charToGlyphIndex: (ch: string) => number;
  /** Sprint 268：依 glyph index 取 Glyph 物件（含 advanceWidth）。 */
  glyphs: OpentypeGlyphSet;
}

interface OpentypeModule {
  parse: (buffer: ArrayBuffer | Uint8Array) => OpentypeFont;
}

function getOpentype(): OpentypeModule {
  // Sprint 62：opentype.js 已透過 ESM static import 取得；module 可能 default-exported 或 namespace
  return opentype as OpentypeModule;
}

/**
 * 解析字型 byte buffer，回傳核心 metrics。
 *
 * lineGap 取值優先順序：
 *   OS/2 table sTypoLineGap > hhea table lineGap > 0
 *
 * @param fontBytes TTF / OTF 位元組（Uint8Array 或 ArrayBuffer）
 * @returns FontMetricsResult；解析失敗時 throw
 */
export function readFontMetrics(fontBytes: Uint8Array | ArrayBuffer): FontMetricsResult {
  const ot = getOpentype();
  // opentype.js 接受 ArrayBuffer；Uint8Array → 取其 underlying buffer 切片
  // 注意：buffer.slice 在 SharedArrayBuffer 時回 SharedArrayBuffer，需強制視為 ArrayBuffer
  const buffer: ArrayBuffer =
    fontBytes instanceof Uint8Array
      ? (fontBytes.buffer.slice(
          fontBytes.byteOffset,
          fontBytes.byteOffset + fontBytes.byteLength,
        ) as ArrayBuffer)
      : fontBytes;
  const font = ot.parse(buffer);

  const out: FontMetricsResult = {
    unitsPerEm: font.unitsPerEm,
    ascender: font.ascender,
    descender: Math.abs(font.descender), // descender 通常為負，取絕對值
    lineGap:
      font.tables?.os2?.sTypoLineGap ??
      font.tables?.hhea?.lineGap ??
      0,
  };
  if (font.tables?.os2?.sxHeight) out.xHeight = font.tables.os2.sxHeight;
  if (font.tables?.os2?.sCapHeight) out.capHeight = font.tables.os2.sCapHeight;
  // Sprint 268：extended metrics（typo / win / italic / weight / advanceWidthMax）
  const os2 = font.tables?.os2;
  if (os2 !== undefined) {
    if (os2.sTypoAscender !== undefined) out.typoAscender = os2.sTypoAscender;
    if (os2.sTypoDescender !== undefined) out.typoDescender = Math.abs(os2.sTypoDescender);
    if (os2.sTypoLineGap !== undefined) out.typoLineGap = os2.sTypoLineGap;
    if (os2.usWinAscent !== undefined) out.winAscent = os2.usWinAscent;
    if (os2.usWinDescent !== undefined) out.winDescent = os2.usWinDescent;
    if (os2.fsSelection !== undefined) {
      // OS/2 §3.7：bit 0 = italic、bit 5 = bold
      out.italic = (os2.fsSelection & 0x01) !== 0;
      out.bold = (os2.fsSelection & 0x20) !== 0;
    }
    if (os2.usWeightClass !== undefined) out.weightClass = os2.usWeightClass;
    if (os2.usWidthClass !== undefined) out.widthClass = os2.usWidthClass;
  }
  const head = font.tables?.head;
  if (head?.macStyle !== undefined) {
    // head §6.3.1：bit 0 = bold、bit 1 = italic
    out.macStyleBold = (head.macStyle & 0x01) !== 0;
    out.macStyleItalic = (head.macStyle & 0x02) !== 0;
  }
  const hhea = font.tables?.hhea;
  if (hhea?.advanceWidthMax !== undefined) out.advanceWidthMax = hhea.advanceWidthMax;
  return out;
}

// ── Sprint 268：per-glyph advance widths（opentype.js、無 HarfBuzz 依賴） ──

/** Sprint 268：opentype.js advance 結果（每 glyph + 總寬，pt）。 */
export interface OpentypeAdvanceResult {
  /** 整段文字水平 advance 總和（pt） */
  widthPt: number;
  /** 每 glyph 的 advance（pt、依 stringToGlyphs 結果順序） */
  advancesPt: number[];
  /** Glyph 數（無 ligature shaping → 通常等於 codepoint count） */
  glyphCount: number;
}

/**
 * Sprint 268：用 opentype.js 計算 per-glyph advance widths（pt）。
 *
 * 與 ShapingEngine.measureRun 差異：
 *   - opentype.js 不做 ligature shaping、不做 complex script shaping
 *   - 只走 cmap codepoint → glyph index → glyph.advanceWidth
 *   - kerning 仍會被 getAdvanceWidth 套用（kern table、若字型有）
 *   - 不需 WASM、~80KB bundle vs HarfBuzz ~200KB
 *   - 適合 fallback / quick measure 場景；複雜文字（Arabic / Indic）走 HarfBuzz
 *
 * @param fontBytes 字型檔位元組
 * @param text 要量測的文字
 * @param sizePt 字級（pt）
 */
export function readOpentypeAdvances(
  fontBytes: Uint8Array | ArrayBuffer,
  text: string,
  sizePt: number,
): OpentypeAdvanceResult {
  const ot = getOpentype();
  const buffer: ArrayBuffer =
    fontBytes instanceof Uint8Array
      ? (fontBytes.buffer.slice(
          fontBytes.byteOffset,
          fontBytes.byteOffset + fontBytes.byteLength,
        ) as ArrayBuffer)
      : fontBytes;
  const font = ot.parse(buffer);
  const unitsPerEm = font.unitsPerEm;
  const scale = sizePt / unitsPerEm;
  // Sprint 268 root cause：opentype.js stringToGlyphs 走 Bidi/feature 路徑
  //   對 substFormat 2 子型替換尚未支援會 throw（DejaVuSans 觸發）。改走低階
  //   charToGlyphIndex + glyphs.get(idx)、繞過 Bidi/feature 處理（紀律 #18
  //   scope-down：無 ligature shaping、複雜文字走 HarfBuzz ShapingEngine）。
  const advancesPt: number[] = [];
  for (const ch of text) {
    const idx = font.charToGlyphIndex(ch);
    const g = font.glyphs.get(idx);
    advancesPt.push((g.advanceWidth ?? 0) * scale);
  }
  const widthPt = advancesPt.reduce((a, b) => a + b, 0);
  return { widthPt, advancesPt, glyphCount: advancesPt.length };
}

/**
 * 計算單行的高度（pt）。
 *
 * Phase 6 Layout Engine 排版時用：每行的高度 = ascent + descent + lineGap
 * （皆已換算為 pt）。
 *
 * @param metrics 由 readFontMetrics 取得
 * @param sizePt 字級（點 pt）
 */
export function lineHeightPt(metrics: FontMetricsResult, sizePt: number): number {
  const { unitsPerEm, ascender, descender, lineGap } = metrics;
  return ((ascender + descender + lineGap) * sizePt) / unitsPerEm;
}

// ── Sprint 267：OOXML w:line + w:lineRule 公式 ───────────────────────────────

/** Sprint 267：OOXML 行高解析結果（公式落地、診斷友善）。 */
export interface OoxmlLineHeightResult {
  /** 最終行高（pt） */
  heightPt: number;
  /** 套用的規則（'natural' = 無 w:line 設定、純字型 metrics） */
  rule: 'natural' | 'auto' | 'exact' | 'atLeast';
  /** 自然行高（pt、僅字型 metrics、未套 OOXML rule 前） */
  naturalHeightPt: number;
  /** 給定 line.value（auto 為 multiplier、exact/atLeast 為 pt 下限） */
  lineValue?: number;
}

/**
 * Sprint 267：依 OOXML §17.3.1.33 w:spacing/w:line + w:lineRule 計算最終行高（pt）。
 *
 * 三種 rule（規格直譯）：
 *   - **auto**：value 是行數 multiplier（在 AST 已 = line / 240、單行 1.0 / 1.5 行 1.5 / 雙行 2.0）。
 *     公式：`heightPt = naturalLineHeight × value`
 *   - **exact**：固定 pt 行高、忽略字型 metrics。公式：`heightPt = value`（pt）。
 *     若 value < natural、文字仍會被 clip；render 端責任、本函式不檢查。
 *   - **atLeast**：下限 pt。公式：`heightPt = max(naturalLineHeight, value)`。
 *
 * @param metrics 由 readFontMetrics 取得（caller 須先確保字型已 parse）
 * @param sizePt 字級（pt）
 * @param lineRule OOXML rule（無 → 'natural'、回傳 naturalHeightPt）
 * @param lineValue 對應規則的 value（auto = multiplier、exact/atLeast = pt）
 */
export function resolveOoxmlLineHeight(
  metrics: FontMetricsResult,
  sizePt: number,
  lineRule?: 'auto' | 'exact' | 'atLeast',
  lineValue?: number,
): OoxmlLineHeightResult {
  const naturalHeightPt = lineHeightPt(metrics, sizePt);
  if (lineRule === undefined || lineValue === undefined) {
    return { heightPt: naturalHeightPt, rule: 'natural', naturalHeightPt };
  }
  switch (lineRule) {
    case 'auto':
      return {
        heightPt: naturalHeightPt * lineValue,
        rule: 'auto',
        naturalHeightPt,
        lineValue,
      };
    case 'exact':
      return {
        heightPt: lineValue,
        rule: 'exact',
        naturalHeightPt,
        lineValue,
      };
    case 'atLeast':
      return {
        heightPt: Math.max(naturalHeightPt, lineValue),
        rule: 'atLeast',
        naturalHeightPt,
        lineValue,
      };
  }
}

/**
 * Sprint 267：分離行內基線位置（pt 偏移、由頂端往下量）。
 *
 * 基線 = ascent + (extraLineGap / 2)。Phase 6 Layout Engine 排基線對齊用。
 *
 * @param metrics 由 readFontMetrics 取得
 * @param sizePt 字級（pt）
 * @param lineHeightPtVal 該行最終行高（resolveOoxmlLineHeight 回傳）
 * @returns 基線 pt 偏移（頂端 0、向下為正）
 */
export function baselineOffsetPt(
  metrics: FontMetricsResult,
  sizePt: number,
  lineHeightPtVal: number,
): number {
  const { unitsPerEm, ascender } = metrics;
  const ascentPt = (ascender * sizePt) / unitsPerEm;
  // 自然 ascent 已含、超過 natural 的多出部分平均分到 top/bottom
  const naturalHeight = lineHeightPt(metrics, sizePt);
  const extra = Math.max(0, lineHeightPtVal - naturalHeight);
  return ascentPt + extra / 2;
}
