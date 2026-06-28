/**
 * BrowserCanvasRenderContext — Sprint 9
 *
 * 涵蓋：
 *   - pt → px scale 行為（預設 96/72；可覆寫）
 *   - color hex → CSS string（# 自動補；3 位 → 6 位）
 *   - font CSS string（bold / italic / fontSize × scale / family quoting）
 *   - fillRect / drawLine / fillText / drawImage 指令轉發到底層 Canvas2D
 *   - clearRect on beginPage
 *   - onPageEnd callback
 */

import { describe, expect, it, vi } from 'vitest';
import {
  BrowserCanvasRenderContext,
  toCssColor,
  toCssFont,
  type BrowserCanvas2D,
} from '../../../static/src/core/render/BrowserCanvasRenderContext';

/** 模擬 Canvas2D：記錄方法呼叫 + 屬性設定 */
function makeMockCanvas(): { canvas: BrowserCanvas2D; calls: Array<{ name: string; args: unknown[] }>; props: Record<string, unknown[]> } {
  const calls: Array<{ name: string; args: unknown[] }> = [];
  const props: Record<string, unknown[]> = {
    fillStyle: [], strokeStyle: [], lineWidth: [], font: [], textBaseline: [], textAlign: [],
  };
  const record = (name: string) => (...args: unknown[]) => { calls.push({ name, args }); };
  const canvas: BrowserCanvas2D = {
    get fillStyle() { return ''; }, set fillStyle(v: string) { props.fillStyle.push(v); },
    get strokeStyle() { return ''; }, set strokeStyle(v: string) { props.strokeStyle.push(v); },
    get lineWidth() { return 1; }, set lineWidth(v: number) { props.lineWidth.push(v); },
    get font() { return ''; }, set font(v: string) { props.font.push(v); },
    get textBaseline() { return 'alphabetic'; }, set textBaseline(v) { props.textBaseline.push(v); },
    get textAlign() { return 'start'; }, set textAlign(v) { props.textAlign.push(v); },
    setLineDash: record('setLineDash') as (segments: number[]) => void,
    fillRect: record('fillRect') as BrowserCanvas2D['fillRect'],
    strokeRect: record('strokeRect') as BrowserCanvas2D['strokeRect'],
    fillText: record('fillText') as BrowserCanvas2D['fillText'],
    beginPath: record('beginPath') as BrowserCanvas2D['beginPath'],
    moveTo: record('moveTo') as BrowserCanvas2D['moveTo'],
    lineTo: record('lineTo') as BrowserCanvas2D['lineTo'],
    stroke: record('stroke') as BrowserCanvas2D['stroke'],
    clearRect: record('clearRect') as BrowserCanvas2D['clearRect'],
    drawImage: record('drawImage') as BrowserCanvas2D['drawImage'],
    save: record('save') as BrowserCanvas2D['save'],
    restore: record('restore') as BrowserCanvas2D['restore'],
  };
  return { canvas, calls, props };
}

// ── toCssColor / toCssFont ─────────────────────────────────────────────────

describe('BrowserCanvasRenderContext — toCssColor', () => {
  it('6 位 hex 加 # 前綴', () => {
    expect(toCssColor('FF0000')).toBe('#FF0000');
    expect(toCssColor('000000')).toBe('#000000');
  });

  it('已含 # 不重複加', () => {
    expect(toCssColor('#FF0000')).toBe('#FF0000');
  });

  it('3 位 short form 展開為 6 位', () => {
    expect(toCssColor('F00')).toBe('#FF0000');
    expect(toCssColor('0AF')).toBe('#00AAFF');
  });

  it('空字串 fallback 黑色', () => {
    expect(toCssColor('')).toBe('#000000');
  });
});

describe('BrowserCanvasRenderContext — toCssFont', () => {
  it('預設 scale (96/72)：12pt → 16px', () => {
    const f = toCssFont({ fontSize: 12 });
    expect(f).toContain('16.00px');
  });

  it('bold + italic + family', () => {
    const f = toCssFont({ fontSize: 10.5, bold: true, italic: true, fontFamily: 'Arial' });
    expect(f).toBe('italic bold 14.00px Arial');
  });

  it('family 含空白用雙引號包', () => {
    const f = toCssFont({ fontSize: 12, fontFamily: 'Times New Roman' });
    expect(f).toContain('"Times New Roman"');
  });

  it('caller 自訂 scale 影響 px 字級', () => {
    const f = toCssFont({ fontSize: 12 }, 2.0);
    expect(f).toContain('24.00px');
  });

  it('無 fontFamily fallback sans-serif', () => {
    const f = toCssFont({ fontSize: 10 });
    expect(f).toContain('sans-serif');
  });
});

// ── 指令轉發 ───────────────────────────────────────────────────────────────

describe('BrowserCanvasRenderContext — pt → px scale', () => {
  it('預設 scale 96/72：100pt → 133.33px', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.fillRect(0, 0, 100, 50, 'FF0000');
    const fillCall = calls.find((c) => c.name === 'fillRect');
    expect(fillCall).toBeDefined();
    expect(fillCall!.args[2]).toBeCloseTo(133.33, 1);
    expect(fillCall!.args[3]).toBeCloseTo(66.67, 1);
  });

  it('自訂 scale=2.0：100pt → 200px', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { scale: 2.0 });
    ctx.fillRect(0, 0, 100, 50, 'FF0000');
    const fillCall = calls.find((c) => c.name === 'fillRect');
    expect(fillCall!.args[2]).toBe(200);
    expect(fillCall!.args[3]).toBe(100);
  });
});

describe('BrowserCanvasRenderContext — fillRect', () => {
  it('設 fillStyle 為 CSS color、呼叫 canvas.fillRect', () => {
    const { canvas, calls, props } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.fillRect(10, 20, 30, 40, '0000FF');
    expect(props.fillStyle).toContain('#0000FF');
    expect(calls.some((c) => c.name === 'fillRect')).toBe(true);
    // save/restore 對稱
    const saves = calls.filter((c) => c.name === 'save').length;
    const restores = calls.filter((c) => c.name === 'restore').length;
    expect(saves).toBe(restores);
  });
});

describe('BrowserCanvasRenderContext — drawLine', () => {
  // Sprint 59 path coalescing：drawLine 緩衝到 pendingPath，需 ctx.flush() 或 endPage 才 stroke
  it('呼叫 beginPath / moveTo / lineTo / stroke 完整序列', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.drawLine(0, 0, 100, 0, { color: '000000', width: 0.5 });
    ctx.flush(); // Sprint 59
    const names = calls.map((c) => c.name);
    expect(names).toContain('beginPath');
    expect(names).toContain('moveTo');
    expect(names).toContain('lineTo');
    expect(names).toContain('stroke');
  });

  it('lineWidth 至少 1px（避免細線消失）', () => {
    const { canvas, props } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    // 0.5pt × 96/72 ≈ 0.667px → 應補到 1
    ctx.drawLine(0, 0, 100, 0, { color: '000000', width: 0.5 });
    ctx.flush(); // Sprint 59
    const lws = props.lineWidth as number[];
    expect(lws.length).toBeGreaterThan(0);
    expect(lws[0]).toBeGreaterThanOrEqual(1);
  });

  it('dashed style 套用 setLineDash', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.drawLine(0, 0, 100, 0, { color: '000000', width: 0.5, style: 'dashed' });
    ctx.flush(); // Sprint 59
    const dash = calls.find((c) => c.name === 'setLineDash');
    expect(dash).toBeDefined();
    expect(dash!.args[0]).toEqual([4, 2]);
  });

  it('dotted style 套用 setLineDash 較密', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.drawLine(0, 0, 100, 0, { color: '000000', width: 0.5, style: 'dotted' });
    ctx.flush(); // Sprint 59
    const dash = calls.find((c) => c.name === 'setLineDash');
    expect(dash).toBeDefined();
    expect(dash!.args[0]).toEqual([1, 2]);
  });
});

describe('BrowserCanvasRenderContext — fillText', () => {
  it('設 font / fillStyle / textBaseline 後 fillText', () => {
    const { canvas, calls, props } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.fillText('Hello', 10, 20, { fontSize: 12, bold: true, color: 'FF0000' });
    expect(props.font.length).toBeGreaterThan(0);
    expect((props.font as string[])[0]).toContain('bold');
    expect((props.font as string[])[0]).toContain('16.00px');
    expect(props.fillStyle).toContain('#FF0000');
    expect(props.textBaseline).toContain('alphabetic');
    expect(calls.some((c) => c.name === 'fillText')).toBe(true);
  });

  it('color 預設黑色（未指定）', () => {
    const { canvas, props } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.fillText('x', 10, 20, { fontSize: 12 });
    expect(props.fillStyle).toContain('#000000');
  });
});

describe('BrowserCanvasRenderContext — drawImage', () => {
  it('imageResolver 回 undefined 時跳過（無 throw）', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    expect(() => ctx.drawImage('rId1', 0, 0, 100, 100)).not.toThrow();
    expect(calls.find((c) => c.name === 'drawImage')).toBeUndefined();
  });

  it('imageResolver 回值時 forward 到 canvas.drawImage', () => {
    const { canvas, calls } = makeMockCanvas();
    const fakeImage = { kind: 'image' };
    const ctx = new BrowserCanvasRenderContext(canvas, {
      imageResolver: (rId) => (rId === 'rId1' ? fakeImage : undefined),
    });
    ctx.drawImage('rId1', 10, 20, 100, 50);
    const call = calls.find((c) => c.name === 'drawImage');
    expect(call).toBeDefined();
    expect(call!.args[0]).toBe(fakeImage);
  });
});

describe('BrowserCanvasRenderContext — beginPage / endPage', () => {
  it('預設 clearOnBeginPage=true 在每頁 clearRect', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas);
    ctx.beginPage(1, 595, 842);
    expect(calls.some((c) => c.name === 'clearRect')).toBe(true);
  });

  it('clearOnBeginPage=false 不 clear', () => {
    const { canvas, calls } = makeMockCanvas();
    const ctx = new BrowserCanvasRenderContext(canvas, { clearOnBeginPage: false });
    ctx.beginPage(1, 595, 842);
    expect(calls.some((c) => c.name === 'clearRect')).toBe(false);
  });

  it('endPage 觸發 onPageEnd callback', () => {
    const { canvas } = makeMockCanvas();
    const onPageEnd = vi.fn();
    const ctx = new BrowserCanvasRenderContext(canvas, { onPageEnd });
    ctx.beginPage(3, 595, 842);
    ctx.endPage();
    expect(onPageEnd).toHaveBeenCalledTimes(1);
    expect(onPageEnd).toHaveBeenCalledWith(3, 595, 842);
  });
});
