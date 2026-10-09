/**
 * Phase 6 Layout Engine MVP — Greedy LineBreaker
 *
 * Sprint 277 spike：消費 Sprint 265 ShapingEngine.measureRun() 物理寬度
 * （取代 ctx.measureText），驗證 Sprint 269/275 標的「Phase 2 API ready
 * 銜接 Phase 6 自寫 Layout」聲明。
 *
 * 範圍（紀律 #18 scope-down、MVP only）：
 *   - Greedy break by ASCII space（不做 hyphenation / Knuth-Plass / CJK soft break）
 *   - 單一 font + sizePt（不做 mixed run / inline 字級切換）
 *   - LTR 假設（不做 RTL Arabic / Hebrew bidi）
 *   - Overlong word force-fit（一字超過 availableWidth 自佔一行、不切字）
 *
 * Phase 6 完整 Layout 才會擴充：
 *   - mixed run（字型 / 字級 / 顏色切換）
 *   - kerning across word boundary（OpenType kern feature）
 *   - Knuth-Plass dynamic programming 最佳化換行
 *   - hyphenation dictionary（en-US Liang algorithm）
 *   - CJK justification（中日韓文 fullwidth / halfwidth 平衡）
 *   - bidi (RTL)
 *
 * 此 MVP 純驗證 Phase 2 API contract；不接到 canvas-editor、不取代既有 measureText
 * 流程（Sprint 269 Phase 2 結論「production canvas-editor 未整合、Phase 6 自寫
 * Layout 時消費」之精神）。
 */

import type { ShapingEngine } from '../font/ShapingEngine';

/** 一條換行後的 line（已 join 為 text、含原始 words[] 與 widthPt）。 */
export interface BrokenLine {
  /** Line 內容（words 以單一 ASCII space join） */
  text: string;
  /** Line 實際物理寬度（pt、由 measureRun 累加）*/
  widthPt: number;
  /** Line 內含的單字（保留 tokenize 結果供上層使用） */
  words: string[];
}

/** breakParagraph() 結果。 */
export interface LineBreakResult {
  lines: BrokenLine[];
  /** lines.widthPt 的最大值（pt、空輸入時為 0） */
  maxLineWidthPt: number;
  /** lines.length 別名（便於 caller 讀） */
  totalLines: number;
}

/** breakParagraph() 輸入。 */
export interface LineBreakOptions {
  /** 原始段落字串 */
  text: string;
  /** 可用換行寬度（pt） */
  availableWidthPt: number;
  /** 字型家族（需先 engine.loadFont 過） */
  fontFamily: string;
  /** 字級（pt） */
  sizePt: number;
  /**
   * 可選：space 字元寬度（pt）。省略時由 engine.measureRun(' ') 即時取得；
   * 測試 / 已知字型 metrics 可注入避免每次 await wasm shape。
   */
  spaceWidthPt?: number;
}

/**
 * Greedy line break：tokenize by ASCII space、累積 word.widthPt + space + word
 * 至超過 availableWidthPt 時換行。
 *
 * Overlong word（單字寬度 > availableWidth）force-fit：自佔一行、不切字、不
 * hyphenate（MVP）。Phase 6 完整 Layout 才接 hyphenation dictionary。
 */
export async function breakParagraph(
  engine: ShapingEngine,
  opts: LineBreakOptions,
): Promise<LineBreakResult> {
  const { text, availableWidthPt, fontFamily, sizePt } = opts;
  const words = text.split(' ').filter((w) => w.length > 0);
  if (words.length === 0) {
    return { lines: [], maxLineWidthPt: 0, totalLines: 0 };
  }

  const spaceWidthPt = opts.spaceWidthPt
    ?? (await engine.measureRun(' ', fontFamily, sizePt)).widthPt;

  const lines: BrokenLine[] = [];
  let curWords: string[] = [];
  let curWidth = 0;

  for (const word of words) {
    const { widthPt: wordWidth } = await engine.measureRun(word, fontFamily, sizePt);
    const wouldBe = curWords.length === 0 ? wordWidth : curWidth + spaceWidthPt + wordWidth;

    if (wouldBe <= availableWidthPt || curWords.length === 0) {
      curWords.push(word);
      curWidth = wouldBe;
    } else {
      lines.push({ text: curWords.join(' '), widthPt: curWidth, words: curWords });
      curWords = [word];
      curWidth = wordWidth;
    }
  }
  if (curWords.length > 0) {
    lines.push({ text: curWords.join(' '), widthPt: curWidth, words: curWords });
  }

  const maxLineWidthPt = lines.reduce((m, l) => Math.max(m, l.widthPt), 0);
  return { lines, maxLineWidthPt, totalLines: lines.length };
}
