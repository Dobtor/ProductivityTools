/**
 * LineBreakerWithPolygon — Sprint 298。
 *
 * Phase 3.4 wrapTight 整合：在既有 Sprint 277 LineBreaker greedy break 之上，
 * 加上「避開 wrapPolygon 區域」的換行邏輯，把 Sprint 296 的 polygon 數學工具
 * 接進 Layout。
 *
 * 策略：
 *   1. 對每個 line，先計算「line box rect」=（curX, curY, lineHeight）
 *   2. 用 rectIntersectsPolygon 檢查 line box 是否撞 polygon
 *   3. 撞：將 line break point 推進到 polygon 右邊（找下一個 free slot）
 *   4. 不撞：與 Sprint 277 行為一致
 *
 * 紀律 #18 scope-down：
 *   - 單一 polygon（多 polygon overlap 場景留 future）
 *   - 簡化的 free-slot 演算法：rect-polygon 相交 → 整行 advance 至 polygon 右邊；
 *     不做「polygon 內部空隙穿插」精細處理
 *   - 與 LineBreaker MVP 相容：fontFamily / sizePt 不變、availableWidthPt 固定
 *
 * 紀律 #21：純函式 + 純資料、不污染既有 VR pipeline；caller opt-in 才使用。
 */

import type { ShapingEngine } from '../font/ShapingEngine';
import type { BrokenLine } from './LineBreaker';
import type { WrapPolygonPoint } from '../ast/types';
import { polygonBoundingBox, rectIntersectsPolygon } from './wrap_polygon_math';
import type { ImageRect } from './wrap_polygon_math';

export interface LineBreakWithPolygonOptions {
  /** 原始段落字串 */
  text: string;
  /** 段落 X 起點（pt、預設 0） */
  startX?: number;
  /** 段落 Y 起點（pt） */
  startY: number;
  /** 行高（pt、用於決定 line box 高度 + Y 推進） */
  lineHeightPt: number;
  /** 可換行寬度上限（pt） */
  availableWidthPt: number;
  /** 字型家族（engine 已 loadFont） */
  fontFamily: string;
  /** 字級（pt） */
  sizePt: number;
  /** 已 transform 為絕對 pt 座標的 polygon（用 transformWrapPolygon 先算好） */
  polygonAbs: readonly WrapPolygonPoint[];
  /** Space 字元寬度（pt、預設由 engine.measureRun(' ') 取得） */
  spaceWidthPt?: number;
  /** 安全 buffer（pt、line box 與 polygon 多預留的距離、預設 2） */
  bufferPt?: number;
}

export interface PositionedLine extends BrokenLine {
  /** Line box 起點 X（pt） */
  x: number;
  /** Line box 起點 Y（pt） */
  y: number;
}

export interface LineBreakWithPolygonResult {
  lines: PositionedLine[];
  /** 最大 line 物理寬度 */
  maxLineWidthPt: number;
  /** 行數 */
  totalLines: number;
  /** Y 結尾（最後一行 y + lineHeight、用於後續段落起點） */
  endY: number;
}

/**
 * 段落換行 + 避開 polygon。
 *
 * 演算法：
 *   1. tokenize words；逐字測寬
 *   2. 對每個 line：
 *      a. line box rect = (x, y, availableWidthAtY, lineHeightPt)
 *      b. 用 rectIntersectsPolygon 檢查
 *      c. 撞：advance x 到 polygon.maxX + buffer；availableWidth 重算
 *      d. 不撞：累積 word 至 availableWidth 上限
 *   3. 換行：y += lineHeightPt；reset x = startX
 *
 * caller 須先呼叫 transformWrapPolygon 把 polygon 轉成絕對 pt 座標。
 */
export async function breakParagraphAroundPolygon(
  engine: ShapingEngine,
  opts: LineBreakWithPolygonOptions,
): Promise<LineBreakWithPolygonResult> {
  const {
    text,
    startX = 0,
    startY,
    lineHeightPt,
    availableWidthPt,
    fontFamily,
    sizePt,
    polygonAbs,
    bufferPt = 2,
  } = opts;

  const words = text.split(' ').filter((w) => w.length > 0);
  if (words.length === 0) {
    return { lines: [], maxLineWidthPt: 0, totalLines: 0, endY: startY };
  }

  const spaceWidthPt =
    opts.spaceWidthPt ?? (await engine.measureRun(' ', fontFamily, sizePt)).widthPt;

  const polyBbox = polygonBoundingBox(polygonAbs);

  /** 拿 line box 在 (x, y) 起點時最大可用寬度（被 polygon 截斷時提前換行）。 */
  function availableWidthAt(x: number, y: number): number {
    const rect: ImageRect = {
      x,
      y,
      width: availableWidthPt - (x - startX),
      height: lineHeightPt,
    };
    // 完全在 polygon 影響範圍外（Y 不重疊）→ 全寬可用
    if (y + lineHeightPt < polyBbox.minY || y > polyBbox.maxY) {
      return rect.width;
    }
    if (rectIntersectsPolygon(rect, polygonAbs)) {
      // 撞：line box 寬度只到 polygon 左緣（或 0 表示要整行 advance 後重試）
      const allowedWidth = Math.max(0, polyBbox.minX - x - bufferPt);
      return allowedWidth;
    }
    return rect.width;
  }

  /** 撞 polygon 後找下一行 X 起點：retry from polygon.maxX + buffer。 */
  function nextXAfterPolygon(): number {
    return Math.min(polyBbox.maxX + bufferPt, startX + availableWidthPt);
  }

  const lines: PositionedLine[] = [];
  let curWords: string[] = [];
  let curWidth = 0;
  let curX = startX;
  let curY = startY;
  let curAvailWidth = availableWidthAt(curX, curY);

  /** 是否需要 advance line（撞 polygon、剩下空間不足放最小字）。 */
  function needAdvanceForPolygon(): boolean {
    return curWords.length === 0 && curAvailWidth <= 0;
  }

  /** 推進到下一行。 */
  function advanceLine(): void {
    if (curWords.length > 0) {
      lines.push({
        text: curWords.join(' '),
        widthPt: curWidth,
        words: curWords,
        x: curX,
        y: curY,
      });
    }
    curY += lineHeightPt;
    curX = startX;
    curWords = [];
    curWidth = 0;
    curAvailWidth = availableWidthAt(curX, curY);
  }

  for (const word of words) {
    const { widthPt: wordWidth } = await engine.measureRun(word, fontFamily, sizePt);

    // 若當前行起點被 polygon 卡到 0 寬，先 advance 到 polygon 右邊（同一行 Y）
    if (needAdvanceForPolygon()) {
      const tryX = nextXAfterPolygon();
      if (tryX > curX && tryX < startX + availableWidthPt) {
        curX = tryX;
        curAvailWidth = availableWidthAt(curX, curY);
      }
      // 還是放不下 → 真正換行
      if (curAvailWidth <= 0) {
        advanceLine();
      }
    }

    const wouldBe =
      curWords.length === 0 ? wordWidth : curWidth + spaceWidthPt + wordWidth;
    if (wouldBe <= curAvailWidth || curWords.length === 0) {
      curWords.push(word);
      curWidth = wouldBe;
    } else {
      // 當行放不下 → push 當前行、新行 retry 同字
      advanceLine();
      // 試 retry：若新行起點被 polygon 卡，先 advance；放得下再加
      if (curAvailWidth <= 0) {
        const tryX = nextXAfterPolygon();
        if (tryX > curX && tryX < startX + availableWidthPt) {
          curX = tryX;
          curAvailWidth = availableWidthAt(curX, curY);
        }
      }
      curWords.push(word);
      curWidth = wordWidth;
    }
  }
  // 收尾
  if (curWords.length > 0) {
    lines.push({
      text: curWords.join(' '),
      widthPt: curWidth,
      words: curWords,
      x: curX,
      y: curY,
    });
    curY += lineHeightPt;
  }

  const maxLineWidthPt = lines.reduce((m, l) => Math.max(m, l.widthPt), 0);
  return { lines, maxLineWidthPt, totalLines: lines.length, endY: curY };
}
