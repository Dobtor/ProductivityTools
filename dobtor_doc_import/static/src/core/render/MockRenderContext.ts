/**
 * MockRenderContext — 測試 / debug 用 RenderContext 實作
 *
 * 把所有繪圖指令存成 op 陣列，方便單測斷言：
 *   - 「這頁有幾個 fillText」
 *   - 「指定座標的 drawLine 寬度等於 N pt」
 *   - 「沒有任何 fillText 落在 page margin 外」
 *
 * 不依賴 DOM / Canvas，可在 vitest Node 環境直接跑。
 */

import type { Pt } from '../ooxml/ast/types';
import type { RenderContext, RenderStrokeStyle, RenderTextStyle } from './types';

export type RenderOp =
  | { kind: 'beginPage'; pageNumber: number; width: Pt; height: Pt }
  | { kind: 'endPage' }
  | { kind: 'fillRect'; x: Pt; y: Pt; width: Pt; height: Pt; color: string }
  | { kind: 'drawLine'; x1: Pt; y1: Pt; x2: Pt; y2: Pt; style: RenderStrokeStyle }
  | { kind: 'fillText'; text: string; x: Pt; y: Pt; style: RenderTextStyle }
  | {
      kind: 'drawImage';
      href: string;
      x: Pt;
      y: Pt;
      width: Pt;
      height: Pt;
      srcRect?: { leftPct: number; topPct: number; rightPct: number; bottomPct: number };
    }
  | { kind: 'save' }
  | { kind: 'restore' }
  | { kind: 'translate'; dx: Pt; dy: Pt }
  | { kind: 'rotate'; rad: number };

export class MockRenderContext implements RenderContext {
  ops: RenderOp[] = [];

  beginPage(pageNumber: number, width: Pt, height: Pt): void {
    this.ops.push({ kind: 'beginPage', pageNumber, width, height });
  }
  endPage(): void {
    this.ops.push({ kind: 'endPage' });
  }
  fillRect(x: Pt, y: Pt, width: Pt, height: Pt, color: string): void {
    this.ops.push({ kind: 'fillRect', x, y, width, height, color });
  }
  drawLine(x1: Pt, y1: Pt, x2: Pt, y2: Pt, style: RenderStrokeStyle): void {
    this.ops.push({ kind: 'drawLine', x1, y1, x2, y2, style });
  }
  fillText(text: string, x: Pt, y: Pt, style: RenderTextStyle): void {
    this.ops.push({ kind: 'fillText', text, x, y, style });
  }
  drawImage(
    href: string,
    x: Pt,
    y: Pt,
    width: Pt,
    height: Pt,
    srcRect?: { leftPct: number; topPct: number; rightPct: number; bottomPct: number },
  ): void {
    const op: Extract<RenderOp, { kind: 'drawImage' }> = { kind: 'drawImage', href, x, y, width, height };
    if (srcRect) op.srcRect = srcRect;
    this.ops.push(op);
  }
  save(): void {
    this.ops.push({ kind: 'save' });
  }
  restore(): void {
    this.ops.push({ kind: 'restore' });
  }
  translate(dx: Pt, dy: Pt): void {
    this.ops.push({ kind: 'translate', dx, dy });
  }
  rotate(rad: number): void {
    this.ops.push({ kind: 'rotate', rad });
  }

  /** 清空 op log（同一個 Mock 想多次測試）。 */
  reset(): void {
    this.ops = [];
  }

  /** 取出所有指定類型的 op（強型別）。 */
  filter<T extends RenderOp['kind']>(kind: T): Extract<RenderOp, { kind: T }>[] {
    return this.ops.filter((op) => op.kind === kind) as Extract<RenderOp, { kind: T }>[];
  }

  /** 統計每種 op 的次數，方便寫快速斷言。 */
  counts(): Record<RenderOp['kind'], number> {
    const out: Record<RenderOp['kind'], number> = {
      beginPage: 0,
      endPage: 0,
      fillRect: 0,
      drawLine: 0,
      fillText: 0,
      drawImage: 0,
      save: 0,
      restore: 0,
      translate: 0,
      rotate: 0,
    };
    for (const op of this.ops) out[op.kind]++;
    return out;
  }
}
