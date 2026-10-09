/**
 * Sprint 59 — BrowserCanvasRenderContext path coalescing 單元測試
 *
 * 驗證重點：
 *   1. 連續同 style drawLine → 單一 beginPath + stroke（segments 加在同一 path）
 *   2. style 變化（color/width/dash）→ 強制 flush，再開新 path
 *   3. fillRect / fillText / drawImage / save / restore / translate / rotate / beginPage / endPage → 強制 flush
 *   4. endPage 是最終 flush 點（避免 last drawLine 漏畫）
 *   5. explicit flush() public method 也有效
 *
 * 用 spy canvas 計數 stroke() / moveTo() / lineTo() / beginPath() 次數。
 */

import { describe, expect, it } from 'vitest';
import {
  BrowserCanvasRenderContext,
  type BrowserCanvas2D,
} from '../../static/src/core/render/BrowserCanvasRenderContext';

function makeSpyCanvas() {
  const counts = {
    fillStyleSet: 0,
    strokeStyleSet: 0,
    fontSet: 0,
    lineWidthSet: 0,
    setLineDashCalled: 0,
    saveCalled: 0,
    restoreCalled: 0,
    fillRectCalled: 0,
    fillTextCalled: 0,
    beginPathCalled: 0,
    moveToCalled: 0,
    lineToCalled: 0,
    strokeCalled: 0,
    clearRectCalled: 0,
    translateCalled: 0,
    rotateCalled: 0,
  };
  const canvas: BrowserCanvas2D = {
    get fillStyle() {
      return '';
    },
    set fillStyle(_v: string) {
      counts.fillStyleSet++;
    },
    get strokeStyle() {
      return '';
    },
    set strokeStyle(_v: string) {
      counts.strokeStyleSet++;
    },
    get font() {
      return '';
    },
    set font(_v: string) {
      counts.fontSet++;
    },
    get lineWidth() {
      return 0;
    },
    set lineWidth(_v: number) {
      counts.lineWidthSet++;
    },
    get textBaseline() {
      return 'alphabetic' as const;
    },
    set textBaseline(_v: BrowserCanvas2D['textBaseline']) {},
    get textAlign() {
      return 'start' as const;
    },
    set textAlign(_v: BrowserCanvas2D['textAlign']) {},
    setLineDash: () => {
      counts.setLineDashCalled++;
    },
    fillRect: () => {
      counts.fillRectCalled++;
    },
    strokeRect: () => {},
    fillText: () => {
      counts.fillTextCalled++;
    },
    beginPath: () => {
      counts.beginPathCalled++;
    },
    moveTo: () => {
      counts.moveToCalled++;
    },
    lineTo: () => {
      counts.lineToCalled++;
    },
    stroke: () => {
      counts.strokeCalled++;
    },
    clearRect: () => {
      counts.clearRectCalled++;
    },
    drawImage: () => {},
    save: () => {
      counts.saveCalled++;
    },
    restore: () => {
      counts.restoreCalled++;
    },
    translate: () => {
      counts.translateCalled++;
    },
    rotate: () => {
      counts.rotateCalled++;
    },
  } as BrowserCanvas2D;
  return { canvas, counts };
}

describe('Sprint 59 — path coalescing', () => {
  it('連續 4 條同 style drawLine（cell 4 邊邊框）→ 單一 stroke()，4 對 moveTo+lineTo', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.drawLine(0, 0, 0, 10, style);
    ctx.drawLine(10, 0, 10, 10, style);
    ctx.drawLine(0, 10, 10, 10, style);
    ctx.endPage(); // 觸發 flush
    expect(counts.strokeCalled).toBe(1);
    expect(counts.beginPathCalled).toBe(1);
    expect(counts.moveToCalled).toBe(4);
    expect(counts.lineToCalled).toBe(4);
  });

  it('style 變化（不同 color）→ 強制 flush，2 個 batch = 2 個 stroke', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: 'FF0000', width: 1, style: 'solid' });
    ctx.drawLine(0, 5, 10, 5, { color: 'FF0000', width: 1, style: 'solid' }); // 同 → 同 batch
    ctx.drawLine(0, 10, 10, 10, { color: '0000FF', width: 1, style: 'solid' }); // 不同色 → 新 batch
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
    expect(counts.beginPathCalled).toBe(2);
  });

  it('style 變化（不同 width）→ 強制 flush', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: '000000', width: 1, style: 'solid' });
    ctx.drawLine(0, 5, 10, 5, { color: '000000', width: 2, style: 'solid' }); // 不同 width
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
  });

  it('style 變化（不同 dash）→ 強制 flush', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: '000000', width: 1, style: 'solid' });
    ctx.drawLine(0, 5, 10, 5, { color: '000000', width: 1, style: 'dashed' }); // 不同 dash
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
  });

  it('fillRect 中間插入 → 強制 flush 既有 pending', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.drawLine(0, 5, 10, 5, style); // batched
    ctx.fillRect(0, 0, 10, 10, 'FFFFFF'); // 強制 flush
    ctx.drawLine(0, 10, 10, 10, style); // 新 batch
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
    expect(counts.fillRectCalled).toBe(1);
  });

  it('fillText 中間插入 → 強制 flush', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.fillText('a', 0, 0, { fontSize: 12, fontFamily: 'Arial' });
    ctx.drawLine(0, 10, 10, 10, style);
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
    expect(counts.fillTextCalled).toBe(1);
  });

  it('save/restore 強制 flush（transform 安全）', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.save();
    ctx.drawLine(0, 5, 10, 5, style);
    ctx.restore();
    ctx.drawLine(0, 10, 10, 10, style);
    ctx.endPage();
    // 3 個 batch（save 前 flush / restore 前 flush / endPage flush）
    expect(counts.strokeCalled).toBe(3);
  });

  it('translate / rotate 強制 flush', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.translate(5, 5);
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.rotate(Math.PI / 4);
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.endPage();
    expect(counts.strokeCalled).toBe(3);
  });

  it('beginPage 也 flush pending（避免跨頁殘留）', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: '000000', width: 1, style: 'solid' });
    // 直接 beginPage 不 endPage（極端 case）
    ctx.beginPage(2, 100, 100);
    expect(counts.strokeCalled).toBe(1); // page 1 的 line flushed
  });

  it('endPage 是最終 flush 點（避免漏畫最後 batch）', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: '000000', width: 1, style: 'solid' });
    expect(counts.strokeCalled).toBe(0); // 還在 pending
    ctx.endPage();
    expect(counts.strokeCalled).toBe(1); // 已 flush
  });

  it('explicit flush() public method', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.drawLine(0, 0, 10, 0, { color: '000000', width: 1, style: 'solid' });
    expect(counts.strokeCalled).toBe(0);
    ctx.flush();
    expect(counts.strokeCalled).toBe(1);
  });

  it('空 pending flush 不該 stroke', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 1 });
    ctx.beginPage(1, 100, 100);
    ctx.flush();
    ctx.fillRect(0, 0, 10, 10, 'FFFFFF');
    ctx.endPage();
    expect(counts.strokeCalled).toBe(0);
    expect(counts.beginPathCalled).toBe(0);
  });

  it('drawImage 中間插入 → 強制 flush', () => {
    const { canvas, counts } = makeSpyCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, {
      scale: 1,
      imageResolver: () => ({ width: 10, height: 10 } as unknown),
    });
    ctx.beginPage(1, 100, 100);
    const style = { color: '000000', width: 1, style: 'solid' as const };
    ctx.drawLine(0, 0, 10, 0, style);
    ctx.drawImage('img1', 0, 0, 10, 10);
    ctx.drawLine(0, 10, 10, 10, style);
    ctx.endPage();
    expect(counts.strokeCalled).toBe(2);
  });
});
