/**
 * LineBreaker — 貪婪斷行（First-fit）+ 中文避頭尾規則
 *
 * Sprint 2 用貪婪算法。Knuth-Plass 留 Sprint 4-5（需要 box/glue/penalty 已具備
 * stretch/shrink，當前已建模型，未來切換不必動 BoxBuilder）。
 *
 * 算法：
 *   1. 走訪 items，累積到 currentLine
 *   2. 遇到 Glue 或 Penalty 時記為「候選斷點」
 *   3. 加入下一個 Box 後超過 lineWidth 就在「最後候選斷點」斷
 *   4. 斷行後丟棄行首 glue（trim leading whitespace）
 *   5. 套用避頭尾：若行首是禁止字符，把上一個 Box 推到本行
 *
 * 中文避頭尾：
 *   - 行首禁止字符：。、，；：！？」』）】》．,.;:!?
 *   - 行尾禁止字符：「『（【《
 *
 * 不在本期範圍：
 *   - 連字符（Latin hyphenation）
 *   - 雙向文字 RTL
 *   - 字距精細調整（justify 用 stretch/shrink 但 Sprint 2 不做精算）
 */

import type { Pt } from '../ooxml/ast/types';
import type { Box, Glue, LayoutItem, Line, ParagraphInput, TextMetrics } from './types';
import { EstimateMetrics } from './TextMetrics';

const PROHIBITED_LINE_START = '。、，；：！？」』）】》．,.;:!?)]';
const PROHIBITED_LINE_END = '「『（【《([';

export interface LineBreakOptions {
  /** 行寬（含縮排已扣除）*/
  lineWidth: Pt;
  /** 段落首行縮排 / 懸掛縮排（pt，正值 = 縮、負值 = 懸掛）*/
  firstLineIndent?: Pt;
  /** TextMetrics（line height fallback 用）*/
  metrics?: TextMetrics;
  /**
   * Sprint 6：per-line 行寬 callback（wrapSquare 用）。
   *
   * 給定 (lineIndex, accumulatedHeight) 回此行可用寬度。
   * 若提供，覆蓋 `lineWidth`（但 `firstLineIndent` 仍套用到 line 0）。
   *
   * accumulatedHeight = 段落起點到該行頂端的垂直位移（pt）；
   * caller（Paginator）用此值轉成絕對 y 查 floatImage 排除區。
   */
  getLineWidth?: (lineIndex: number, accumulatedHeight: Pt) => Pt;
  /**
   * Sprint 6：per-line X 偏移 callback（wrapSquare 用）。
   *
   * 給定 (lineIndex, accumulatedHeight) 回此行該往右推多少 pt（避開左 float）。
   * 預設 0。Paginator 在 LinePageEntry.x 時會把這個 offset 加到 columnX。
   */
  getLineXOffset?: (lineIndex: number, accumulatedHeight: Pt) => Pt;
  /**
   * Sprint 13：斷行演算法選擇。
   *
   * - `'greedy'`（預設）：first-fit 貪婪 + 中文避頭尾，O(n)，與 Sprint 2-12 行為一致
   * - `'knuth-plass'`：K-P 動態規劃尋最佳斷行序列，O(n²)，西文 justify / 長段落較順
   *
   * K-P 不支援 `getLineWidth` callback（per-line lineWidth 動態變化會破壞 DP 性質）；
   * 若同時指定 `getLineWidth` + `algorithm='knuth-plass'`，自動 fallback 到 greedy。
   *
   * 預設 greedy 是為了讓 Sprint 2-12 的所有 fixture / fingerprint snapshot 維持穩定；
   * caller 想用 K-P 時須顯式 opt-in。
   */
  algorithm?: 'greedy' | 'knuth-plass';
  /**
   * Sprint 29：document grid line pitch（pt，OOXML §17.6.5 docGrid linePitch）。
   *
   * - 0 / undefined：不對齊 grid（純自然 / spacing 規則）
   * - > 0：當前段落 `snapToGrid != false` 時，每行 height 套以下規則：
   *     · 任何 spacing 規則計算後的 height 都 ceil 到 linePitch 的整數倍
   *
   * 注意：本參數由 Paginator 從 section.docGrid 帶入；caller 直接呼叫 breakParagraph
   * 而未提供時等同關閉。
   */
  docGridLinePitch?: Pt;
  /**
   * Sprint 161：預設 tab stop 間距（pt，OOXML §17.15.1.25 `w:defaultTabStop`、
   * Word 預設 720 twip = 36pt）。
   *
   * - undefined / 0：不解析 tab stop，isTab glue 維持 BoxBuilder 給的空白寬度
   *   （行為與 Sprint 0-160 完全一致 — Strategy C 預設路徑、baseline byte-identical）
   * - > 0：每行 isTab glue 寬度重算為「推進到下一個 tab stop」；段落顯式
   *   `props.tabs`（left 對齊）優先、否則落 default 間距整數倍
   *
   * 由 caller（Paginator、從 `DocumentSettings.defaultTabStop` 帶入）opt-in；
   * VR pipeline 不傳 → 預設路徑不變。
   */
  defaultTabStop?: Pt;
}

/**
 * 把一個段落 break 成 Line[]。
 *
 * 注意：lineWidth 應由 caller（Paginator / LayoutEngine）扣除 indent.left/right 後傳入。
 */
export function breakParagraph(
  para: ParagraphInput,
  opts: LineBreakOptions,
): Line[] {
  const metrics = opts.metrics ?? new EstimateMetrics();
  const baseLineWidth = opts.lineWidth;
  const firstLineIndent = opts.firstLineIndent ?? 0;
  const getLineWidth = opts.getLineWidth;
  const getLineXOffset = opts.getLineXOffset;
  const docGridLinePitch = opts.docGridLinePitch ?? 0;
  const defaultTabStop = opts.defaultTabStop ?? 0;

  // 完全空段落：產出一行空行（高度 = defaultFontSize × 1.2）
  if (para.items.length === 0) {
    const lineHeight = metrics.measureLineHeight({ fontSize: para.defaultFontSize });
    return [
      makeEmptyLine(lineHeight, para, docGridLinePitch),
    ];
  }

  // Sprint 13：K-P opt-in（不支援 per-line lineWidth callback 時才走）
  if (opts.algorithm === 'knuth-plass' && !getLineWidth) {
    return breakParagraphKP(
      para, baseLineWidth, firstLineIndent, getLineXOffset, docGridLinePitch, defaultTabStop,
    );
  }

  const lines: Line[] = [];
  let buf: LayoutItem[] = [];
  let bufWidth = 0;
  let lastBreakIdx = -1; // 在 buf 內最後一個合法斷點的 index
  let isFirstLine = true;

  const items = para.items;

  // Sprint 6：當前行的累加高度（從段落起點起算）
  let accumulatedHeight = 0;
  // 當前行的 lineIndex（0-based）
  let lineIndex = 0;

  /** Sprint 6：取目前行的可用寬度。 */
  const lineWidthFor = (firstLine: boolean): Pt => {
    const base = getLineWidth
      ? getLineWidth(lineIndex, accumulatedHeight)
      : baseLineWidth;
    return firstLine ? base - firstLineIndent : base;
  };

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const allowedLineWidth = lineWidthFor(isFirstLine);

    if (item.kind === 'penalty' && item.cost === -Infinity) {
      // 強制斷行：把 buf flush（不含 penalty）
      const ln = makeLine(buf, para, false, docGridLinePitch, defaultTabStop);
      ln.xOffset = getLineXOffset?.(lineIndex, accumulatedHeight) ?? 0;
      // Sprint 7：page / column break 透傳到 Line
      if (item.flagged && item.breakKind) {
        ln.forcedBreakAfter = item.breakKind;
      }
      lines.push(ln);
      accumulatedHeight += ln.height;
      lineIndex++;
      buf = [];
      bufWidth = 0;
      lastBreakIdx = -1;
      isFirstLine = false;
      continue;
    }

    // 嘗試加入 item
    const itemWidth = item.kind === 'penalty' ? 0 : item.width;
    if (bufWidth + itemWidth > allowedLineWidth && buf.length > 0) {
      // 超寬：在 lastBreakIdx 處斷
      let cutAt = lastBreakIdx >= 0 ? lastBreakIdx : buf.length;
      // 避頭尾：檢查 cut 後本行尾 / 下行首
      cutAt = applyKinsoku(buf, cutAt);

      const lineItems = trimTrailingGlue(buf.slice(0, cutAt));
      const ln = makeLine(lineItems, para, false, docGridLinePitch, defaultTabStop);
      ln.xOffset = getLineXOffset?.(lineIndex, accumulatedHeight) ?? 0;
      lines.push(ln);
      accumulatedHeight += ln.height;
      lineIndex++;

      // remainder 變新 buf
      const remainder = trimLeadingGlue(buf.slice(cutAt));
      buf = remainder;
      bufWidth = sumWidth(buf);
      lastBreakIdx = lastBreakableIdx(buf);
      isFirstLine = false;
    }

    buf.push(item);
    bufWidth += itemWidth;
    if (isBreakable(item)) {
      lastBreakIdx = buf.length; // 斷在這個 item 後面
    }
  }

  // 收尾：buf 內剩下的成最後一行
  if (buf.length > 0 || lines.length === 0) {
    const ln = makeLine(trimTrailingGlue(buf), para, true, docGridLinePitch, defaultTabStop);
    ln.xOffset = getLineXOffset?.(lineIndex, accumulatedHeight) ?? 0;
    lines.push(ln);
  } else if (lines.length > 0) {
    // 把最後一行標記為 isLastLine
    const last = lines[lines.length - 1];
    lines[lines.length - 1] = { ...last, isLastLine: true };
  }

  return lines;
}

// ── helpers ──────────────────────────────────────────────────────────────

function isBreakable(item: LayoutItem): boolean {
  if (item.kind === 'glue') return true;
  if (item.kind === 'penalty' && item.cost < Infinity) return true;
  return false;
}

function lastBreakableIdx(items: LayoutItem[]): number {
  for (let i = items.length - 1; i >= 0; i--) {
    if (isBreakable(items[i])) return i + 1;
  }
  return -1;
}

function sumWidth(items: LayoutItem[]): Pt {
  let w = 0;
  for (const it of items) {
    if (it.kind === 'penalty') continue;
    w += it.width;
  }
  return w;
}

function trimLeadingGlue(items: LayoutItem[]): LayoutItem[] {
  let i = 0;
  while (i < items.length && items[i].kind === 'glue') i++;
  return items.slice(i);
}

function trimTrailingGlue(items: LayoutItem[]): LayoutItem[] {
  let i = items.length;
  while (i > 0 && items[i - 1].kind === 'glue') i--;
  return items.slice(0, i);
}

/**
 * 避頭尾規則：
 *   - 若 cutAt 之後的第一個 Box 是禁止行首字符，把 cutAt-1 那個 Box 推到下行
 *   - 若 cutAt 之前最後一個 Box 是禁止行尾字符，把它推到下行
 */
function applyKinsoku(items: LayoutItem[], cutAt: number): number {
  // Look forward：本行尾的第一個 box（從 cutAt 開始）
  let nextBox = -1;
  for (let i = cutAt; i < items.length; i++) {
    if (items[i].kind === 'box') {
      nextBox = i;
      break;
    }
  }
  if (nextBox >= 0) {
    const ch = (items[nextBox] as Box).text.charAt(0);
    if (PROHIBITED_LINE_START.includes(ch)) {
      // 禁止行首字符：把上一個 box 推到下行
      let prevBox = -1;
      for (let i = cutAt - 1; i >= 0; i--) {
        if (items[i].kind === 'box') {
          prevBox = i;
          break;
        }
      }
      if (prevBox >= 0) return prevBox;
    }
  }

  // Look backward：本行最後一個 box（從 cutAt-1 倒推）
  let lastBox = -1;
  for (let i = cutAt - 1; i >= 0; i--) {
    if (items[i].kind === 'box') {
      lastBox = i;
      break;
    }
  }
  if (lastBox >= 0) {
    const box = items[lastBox] as Box;
    const lastChar = box.text.charAt(box.text.length - 1);
    if (PROHIBITED_LINE_END.includes(lastChar)) {
      return lastBox;
    }
  }

  return cutAt;
}

function makeLine(
  items: LayoutItem[],
  para: ParagraphInput,
  isLastLine: boolean,
  docGridLinePitch: Pt = 0,
  defaultTabStop: Pt = 0,
): Line {
  // Sprint 161：tab stop 解析（僅 defaultTabStop > 0 時；否則 items 原樣回傳）
  items = resolveTabStops(items, para, defaultTabStop);
  const width = sumWidth(items);
  let height = 0;
  // Sprint 44：偵測 image-only line（所有 box 都是 image，無文字 box）。
  // image 無 descender，baseline 應 = height（image 底邊對齊 baseline）；
  // 否則 baseline = height × 0.8 會把 image y_drawn 推到 baseY 上方 0.2h（Sprint 43 診斷）。
  // 注意：line 至少要有一個 image box 才算 image-only（空行不算）。
  let hasBox = false;
  let isImageOnlyLine = true;
  for (const it of items) {
    if (it.kind === 'box') {
      hasBox = true;
      if (it.height > height) height = it.height;
      if (!(it as Box).isImage) isImageOnlyLine = false;
    }
  }
  if (!hasBox) isImageOnlyLine = false;
  if (height === 0) {
    height = (para.defaultFontSize ?? 10.5) * 1.2;
  }
  height = applySpacingLine(height, para);
  // Sprint 47：保留 docGrid snap 前的高度（val-as-min 比較基準用）
  const heightUnsnapped = height;
  // Sprint 29：document grid snap（若 section 有 docGrid 且 paragraph snapToGrid != false）
  height = applyDocGridSnap(height, para, docGridLinePitch);
  // baseline：純文字行取行高 80%（80% baseline drop）；
  // Sprint 44：image-only 行 baseline = height（image 無下緣 descender）
  const baseline = isImageOnlyLine ? height : height * 0.8;
  return {
    items,
    width,
    height,
    heightUnsnapped,
    baseline,
    alignment: para.props.alignment ?? 'left',
    isLastLine,
    paragraphIndex: para.sourceIndex,
    paragraphProps: para.props,
  };
}

/** Sprint 161：tab stop 解析精度容差（pt）—— x 恰落在 stop 上時避免回傳零寬 tab。*/
const TAB_RESOLVE_EPSILON_PT = 0.01;

/**
 * Sprint 161：把一行內的 isTab glue 寬度重算為「推進到下一個 tab stop」。
 *
 * - `defaultTabStop <= 0`：直接回傳原 items（Strategy C 預設路徑、baseline 不變）。
 * - 段落顯式 tab stop（`para.props.tabs`、僅 `left` 對齊）優先於 default 間距。
 * - x 原點 = 行內容起點（不計 firstLineIndent；§18 scope-down、leader tab 情境足夠）。
 * - center / right / decimal 對齊 tab：本 sprint 不解析（罕用、留後續 sprint）。
 * - 解析寬度僅影響 `makeLine` 後的 `Line.width`；貪婪斷行的 buf 累寬仍用 BoxBuilder
 *   的空白寬度（近似 — leader tab 多在行首、影響極小，誠實聲明於 audit doc）。
 */
function resolveTabStops(
  items: LayoutItem[],
  para: ParagraphInput,
  defaultTabStop: Pt,
): LayoutItem[] {
  if (defaultTabStop <= 0) return items;
  if (!items.some((it) => it.kind === 'glue' && (it as Glue).isTab)) return items;

  const explicitStops = (para.props.tabs ?? [])
    .filter((t) => t.align === 'left')
    .map((t) => t.pos)
    .sort((a, b) => a - b);

  let x = 0;
  return items.map((it) => {
    if (it.kind === 'glue' && (it as Glue).isTab) {
      const target = nextTabStop(x, explicitStops, defaultTabStop);
      const resolved: Glue = { ...(it as Glue), width: target - x };
      x = target;
      return resolved;
    }
    if (it.kind !== 'penalty') x += it.width;
    return it;
  });
}

/**
 * 給定目前 x，回傳下一個 tab stop 的絕對位置（pt）。
 * 顯式 stop（已升序）優先；超過所有顯式 stop 則落 `defaultTabStop` 間距整數倍。
 */
function nextTabStop(x: Pt, explicitStops: Pt[], defaultTabStop: Pt): Pt {
  for (const stop of explicitStops) {
    if (stop > x + TAB_RESOLVE_EPSILON_PT) return stop;
  }
  const n = Math.floor((x + TAB_RESOLVE_EPSILON_PT) / defaultTabStop) + 1;
  return n * defaultTabStop;
}

function makeEmptyLine(
  height: Pt,
  para: ParagraphInput,
  docGridLinePitch: Pt = 0,
): Line {
  const heightUnsnapped = applySpacingLine(height, para);
  const finalHeight = applyDocGridSnap(heightUnsnapped, para, docGridLinePitch);
  return {
    items: [],
    width: 0,
    height: finalHeight,
    heightUnsnapped,
    baseline: finalHeight * 0.8,
    alignment: para.props.alignment ?? 'left',
    isLastLine: true,
    paragraphIndex: para.sourceIndex,
    paragraphProps: para.props,
  };
}

// Sprint 25: 套用 OOXML w:spacing line 規則
//   exact   → height = spacing.line.value（強制，忽略字型自然行高）
//   atLeast → height = max(natural, spacing.line.value)
//   auto    → height = natural × spacing.line.value（240/240 = 1.0；ParagraphParser 已轉成 ratio）
//
// 規格依據 ECMA-376 §17.3.1.33 spacing：
//   - lineRule="exact"   → w:line 是固定 twip
//   - lineRule="atLeast" → w:line 是最低 twip
//   - lineRule="auto"    → w:line 是 240 為基準的倍率（ParagraphParser 已除以 240）
function applySpacingLine(natural: Pt, para: ParagraphInput): Pt {
  const spLine = para.props.spacing?.line;
  if (!spLine) return natural;
  const value = spLine.value;
  if (!Number.isFinite(value) || value <= 0) return natural;
  switch (spLine.rule) {
    case 'exact':
      return value;
    case 'atLeast':
      return natural >= value ? natural : value;
    case 'auto':
      return natural * value;
    default:
      return natural;
  }
}

// Sprint 29：套用 OOXML §17.6.5 docGrid + §17.3.1.32 snapToGrid 規則
//
// 中文文件常設 `<w:docGrid w:type="lines" w:linePitch="364"/>`（pitch 18.2pt）
// 強制 paragraph baseline 對齊 grid，效果是每行高度 ceil 到 linePitch 整數倍。
//
// 規則：
//   - linePitch <= 0 → 不 snap（無 grid）
//   - paragraph snapToGrid === false → 不 snap（顯式關閉）
//   - **paragraph 沒有顯式 spacing.line（auto/exact/atLeast 都沒設）→ 不 snap**
//       OOXML 沒明確規定此 case，但實測 fixture（全套管基樁混凝土查驗 系列、
//       磺港溪會議照片）顯示 Word 對「無 spacing.line」的段落不做 grid snap —
//       Sprint 29 對齊此行為避免大量誤觸。
//   - 否則 height = ceil(height / linePitch) × linePitch
//
// 對 lineRule=exact 段落：exact 值可能不是 pitch 整數倍 → 上推到 pitch 整數倍
// 對 lineRule=auto/atLeast：natural × multiplier 後 ceil → grid 對齊
// 對空段落（但有 spacing.line）：natural lineHeight 上推到 pitch 整數倍
//
// Sprint 46 註記：曾試「exact 行不 snap」（依 Sprint 43 §5 假設 A2 + 監造會議記錄
// row1/row4 trace），但 VR 證實**全域災難退化 04_with_image（0.1250 → 0.3236）**——
// 環清表 exact 行 unsnapped 後表變太矮、under-paginate。確認 Sprint 29 對主流 04 案例
// 的 snap-exact 是對的、Sprint 45「A2 證偽」結論正確；已 revert。詳見 docs/sprint46。
//
// Sprint 49 註記：曾試移除「無 spacing.line → 不 snap」guard（Pillow 實測 golden 03
// 全套管 title 段落 snap 到 36pt = 2×pitch），但 VR 證實**全域翻車**：03 -1.22pp 收斂
// 但 02_std_table +3.61pp 退化（Sprint 29 的「大量誤觸」應驗——02 有 no-spacing.line
// 段落不該 snap）、total +0.27pp 淨退化 → 已 revert。確認 Sprint 29 的「無 spacing.line
// → 不 snap」規則對 02 是正確的。詳見 docs/sprint49。
//
// Sprint 135 probe 找到候選判別子 = 「段落是否在 table cell 內」（02 in-cell 主要、
// 03 全套管 body title outside-cell）。Sprint 136 實作（ParagraphInput.isInTableCell
// + Paginator 注入 false / TableLayout 注入 true），但 VR 全 42 fixture 實測**翻車**：
//   - 03 全套管 5 fixture 全 +0.86~1.47pp **退化**（snap 過度推高 body title 塊、
//     photo Y 反 overshoot golden、未命中 Sprint 49 §2 Pillow 量測值）
//   - 04 監造會議照片 -0.51~1.01pp 改善
//   - net aggregate **+0.021pp 淨退化** → revert（applyDocGridSnap byte-identical
//     Sprint 135；isInTableCell 欄位保留為 future sprint 之 scaffold、不再讀取）
// Sprint 137+ 須加更精緻條件（如 fontSize 範圍、linePitch vs natural ratio、
// title block 累積高度差量）才可能命中真實 golden 行為。詳見 docs/sprint136。
function applyDocGridSnap(height: Pt, para: ParagraphInput, linePitch: Pt): Pt {
  if (!Number.isFinite(linePitch) || linePitch <= 0) return height;
  if (para.props.snapToGrid === false) return height;
  if (!para.props.spacing?.line) return height; // 無顯式 spacing.line → 不 snap
  if (!Number.isFinite(height) || height <= 0) return height;
  const grids = Math.ceil(height / linePitch);
  return grids * linePitch;
}

// ── Knuth-Plass 斷行（Sprint 13 opt-in）──────────────────────────────────
//
// 演算法：對 N 個 items 尋找斷行 sequence 使總 demerits 最小。
//
// 1. 預先算 prefix sum：W[i] = sum of widths, Y[i] = sum of stretch, Z[i] = sum of shrink
// 2. 對每個合法斷點 b（glue / penalty 且 cost < +Inf），對所有 active node a 試算：
//      r = adjustment ratio = (target - W) / (Y or Z)
//      r < -1 → 不可行（line 太擠）；移除 a from active
//      badness = 100 * |r|^3
//      demerits = (1 + badness)^2  + flagged_penalty²
//    取 a 使得 a.totalDemerits + demerits 最小，產生新 node b
// 3. 走完所有 items 後，從末端 node 反推 chain，得到 break sequence
//
// 比 greedy 慢 O(n²) 但西文 justify 更順、CJK 也能避免「最後一行只剩 2 字」之類
// 的視覺不平衡。CJK 避頭尾仍 post-pass 套用（與 greedy 一致）。

interface KPNode {
  position: number;     // items index where line breaks AT this position（inclusive）
  prev: KPNode | null;
  totalDemerits: number;
  ratio: number;        // adjustment ratio for the line ENDING here
}

function breakParagraphKP(
  para: ParagraphInput,
  lineWidth: Pt,
  firstLineIndent: Pt,
  getLineXOffset: ((idx: number, h: Pt) => Pt) | undefined,
  docGridLinePitch: Pt = 0,
  defaultTabStop: Pt = 0,
): Line[] {
  const items = para.items;
  const N = items.length;

  // prefix sums（i 對應到 items[0..i-1] 的累積值）
  const W: number[] = new Array(N + 1).fill(0);
  const Y: number[] = new Array(N + 1).fill(0);
  const Z: number[] = new Array(N + 1).fill(0);
  for (let i = 0; i < N; i++) {
    const it = items[i];
    let w = 0; let y = 0; let z = 0;
    if (it.kind === 'box') w = it.width;
    else if (it.kind === 'glue') { w = it.width; y = it.stretch; z = it.shrink; }
    // penalty width 通常 0；不加入 W
    W[i + 1] = W[i] + w;
    Y[i + 1] = Y[i] + y;
    Z[i + 1] = Z[i] + z;
  }

  // 起點 node
  const startNode: KPNode = { position: -1, prev: null, totalDemerits: 0, ratio: 0 };
  let active: KPNode[] = [startNode];

  // 對每個位置 b 算「在 b 處斷行」的最小 demerits
  for (let b = 0; b < N; b++) {
    const item = items[b];
    if (!isFeasibleBreak(item, items, b)) continue;

    const isForcedBreak = item.kind === 'penalty' && item.cost === -Infinity;
    let bestNode: KPNode | null = null;
    let bestDemerits = Infinity;
    const newActive: KPNode[] = [];

    for (const a of active) {
      const lineIndex = countLineFromPrev(a) + 1; // 0-indexed line
      const target = lineIndex === 1
        ? lineWidth - firstLineIndent
        : lineWidth;

      // 行寬 = W[b+1] - W[a.position+1]，但 trailing glue 不算
      const lineW = W[b + 1] - W[a.position + 1];
      // 對於尾端是 glue 的情況，把它從 W 扣除（trim trailing whitespace）
      const trailing = items[b].kind === 'glue' ? (items[b] as { width: Pt }).width : 0;
      const effLineW = lineW - trailing;
      const lineY = Y[b + 1] - Y[a.position + 1];
      const lineZ = Z[b + 1] - Z[a.position + 1];

      let r: number;
      if (effLineW < target) {
        r = lineY > 0 ? (target - effLineW) / lineY : Infinity;
      } else if (effLineW > target) {
        r = lineZ > 0 ? (target - effLineW) / lineZ : -Infinity;
      } else {
        r = 0;
      }

      // 強制斷行繞過可行性檢查
      if (!isForcedBreak && (r < -1 || !Number.isFinite(r))) {
        // a 對 b 不可行；保留 a 給後面位置（可能與更後的斷點配對）
        newActive.push(a);
        continue;
      }

      const bad = badness(r);
      const pen = (item.kind === 'penalty' && item.cost > -Infinity) ? Math.max(0, item.cost) : 0;
      // 簡化 demerits：(1 + bad)² + pen²
      const localDemerits = Math.pow(1 + bad, 2) + pen * pen;
      const total = a.totalDemerits + localDemerits;

      if (total < bestDemerits) {
        bestDemerits = total;
        bestNode = { position: b, prev: a, totalDemerits: total, ratio: isForcedBreak ? 0 : r };
      }
      newActive.push(a);
    }

    if (bestNode) {
      newActive.push(bestNode);
    }
    // 強制斷行：清掉所有未觸達 bestNode 的 active（因為強制斷在這之後不能跨）
    if (isForcedBreak && bestNode) {
      active = [bestNode];
    } else {
      active = newActive;
    }
  }

  // 末端：選 totalDemerits 最小的 active node
  let endNode: KPNode | null = null;
  let endDemerits = Infinity;
  for (const a of active) {
    if (a.totalDemerits < endDemerits) {
      endDemerits = a.totalDemerits;
      endNode = a;
    }
  }
  // K-P 可能找不到任何可行斷點（極短/極長段落）→ fallback greedy
  if (!endNode || endNode === startNode) {
    return breakParagraphGreedy(para, lineWidth, firstLineIndent, getLineXOffset);
  }

  // 反推 chain
  const breakChain: number[] = [];
  let cur: KPNode | null = endNode;
  while (cur && cur.position >= 0) {
    breakChain.push(cur.position);
    cur = cur.prev;
  }
  breakChain.reverse();
  // 加入末尾位置（段落結尾）若 endNode 不是最後一個 item
  if (breakChain.length === 0 || breakChain[breakChain.length - 1] !== N - 1) {
    breakChain.push(N - 1);
  }

  // 根據 chain 切 items 為 lines
  const lines: Line[] = [];
  let start = 0;
  let accumulatedHeight = 0;
  for (let li = 0; li < breakChain.length; li++) {
    const breakAt = breakChain[li];
    let cutAt = breakAt + 1;
    // 避頭尾 post-pass（共用 greedy 的 applyKinsoku，但 cutAt 是相對 items 的 absolute index）
    cutAt = applyKinsokuAbs(items, start, cutAt);
    const slice = items.slice(start, cutAt);
    const lineItems = trimTrailingGlue(li === 0 ? slice : trimLeadingGlue(slice));
    const ln = makeLine(
      lineItems, para, li === breakChain.length - 1, docGridLinePitch, defaultTabStop,
    );
    if (getLineXOffset) ln.xOffset = getLineXOffset(li, accumulatedHeight);
    // K-P 也要透傳 forced break kind（page / column）
    const lastItem = items[breakAt];
    if (lastItem && lastItem.kind === 'penalty' && lastItem.flagged && lastItem.breakKind) {
      ln.forcedBreakAfter = lastItem.breakKind;
    }
    lines.push(ln);
    accumulatedHeight += ln.height;
    start = cutAt;
  }
  // 若還有殘留 items（K-P 漏掉末段）
  if (start < N) {
    const ln = makeLine(
      trimTrailingGlue(items.slice(start)), para, true, docGridLinePitch, defaultTabStop,
    );
    if (getLineXOffset) ln.xOffset = getLineXOffset(lines.length, accumulatedHeight);
    lines.push(ln);
  }

  return lines;
}

/** K-P fallback 用的 greedy 包裝（破除 algorithm flag 避免遞迴）。 */
function breakParagraphGreedy(
  para: ParagraphInput,
  lineWidth: Pt,
  firstLineIndent: Pt,
  getLineXOffset: ((idx: number, h: Pt) => Pt) | undefined,
): Line[] {
  return breakParagraph(para, {
    lineWidth,
    firstLineIndent,
    getLineXOffset,
    algorithm: 'greedy',
  });
}

function isFeasibleBreak(item: LayoutItem, items: LayoutItem[], idx: number): boolean {
  if (item.kind === 'penalty') {
    return item.cost < Infinity;
  }
  if (item.kind === 'glue') {
    // glue 必須在 box 之後才能斷
    if (idx === 0) return false;
    const prev = items[idx - 1];
    return prev.kind === 'box';
  }
  return false;
}

function badness(r: number): number {
  if (r < -1) return Infinity;
  const b = 100 * Math.pow(Math.abs(r), 3);
  return Math.min(b, 10000);
}

function countLineFromPrev(node: KPNode): number {
  let c = 0;
  let cur: KPNode | null = node;
  while (cur && cur.prev) {
    c++;
    cur = cur.prev;
  }
  return c;
}

/** applyKinsoku 的 absolute index 版本：cutAt 相對於整個 items 陣列。 */
function applyKinsokuAbs(items: LayoutItem[], lineStart: number, cutAt: number): number {
  // Look forward
  let nextBox = -1;
  for (let i = cutAt; i < items.length; i++) {
    if (items[i].kind === 'box') { nextBox = i; break; }
  }
  if (nextBox >= 0) {
    const ch = (items[nextBox] as Box).text.charAt(0);
    if (PROHIBITED_LINE_START.includes(ch)) {
      let prevBox = -1;
      for (let i = cutAt - 1; i >= lineStart; i--) {
        if (items[i].kind === 'box') { prevBox = i; break; }
      }
      if (prevBox >= 0) return prevBox;
    }
  }
  // Look backward
  let lastBox = -1;
  for (let i = cutAt - 1; i >= lineStart; i--) {
    if (items[i].kind === 'box') { lastBox = i; break; }
  }
  if (lastBox >= 0) {
    const box = items[lastBox] as Box;
    const lastChar = box.text.charAt(box.text.length - 1);
    if (PROHIBITED_LINE_END.includes(lastChar)) {
      return lastBox;
    }
  }
  return cutAt;
}
