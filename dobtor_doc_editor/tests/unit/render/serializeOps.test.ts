/**
 * serializeOps + fingerprintOps — Sprint 12
 *
 * 涵蓋：
 *   - 數字四捨五入到指定精度
 *   - color hex 統一大寫無 #
 *   - undefined / 預設值不寫入（diff 友善）
 *   - ndjson / json 雙格式
 *   - fingerprint：counts、textHash、textCharCount
 */

import { describe, expect, it } from 'vitest';
import { MockRenderContext } from '../../../static/src/core/render/MockRenderContext';
import {
  serializeOps,
  serializeOpsToJson,
  serializeOpsToNdjson,
  fingerprintOps,
} from '../../../static/src/core/render/serializeOps';

function makeBasic(): MockRenderContext {
  const ctx = new MockRenderContext();
  ctx.beginPage(1, 595.123456, 842);
  ctx.fillRect(0.123, 0.456, 100, 50, 'ff0000');
  ctx.fillText('Hello', 10, 20.789, { fontSize: 12, bold: true, color: '0000ff' });
  ctx.drawLine(0, 30, 100, 30, { color: '00ff00', width: 0.5, style: 'single' });
  ctx.endPage();
  return ctx;
}

// ── serializeOps ───────────────────────────────────────────────────────────

describe('serializeOps — 基本行為', () => {
  it('預設 precision=2，數字四捨五入到 0.01', () => {
    const ops = makeBasic().ops;
    const out = serializeOps(ops);
    expect(out).toMatchObject([
      { kind: 'beginPage', pageNumber: 1, w: 595.12, h: 842 },
      { kind: 'fillRect', x: 0.12, y: 0.46, w: 100, h: 50, color: 'FF0000' },
      { kind: 'fillText', text: 'Hello', x: 10, y: 20.79, fontSize: 12, bold: true, color: '0000FF' },
      { kind: 'drawLine', x1: 0, y1: 30, x2: 100, y2: 30, color: '00FF00', width: 0.5, style: 'single' },
      { kind: 'endPage' },
    ]);
  });

  it('precision=0 給整數', () => {
    const ops = makeBasic().ops;
    const out = serializeOps(ops, { precision: 0 });
    expect((out[0] as { w: number }).w).toBe(595);
    expect((out[2] as { y: number }).y).toBe(21);
  });

  it('color hex 統一大寫無 #', () => {
    const ctx = new MockRenderContext();
    ctx.fillRect(0, 0, 1, 1, '#abc123');
    const out = serializeOps(ctx.ops);
    expect((out[0] as { color: string }).color).toBe('ABC123');
  });

  it('未設的 optional style 不出現在輸出（diff 友善）', () => {
    const ctx = new MockRenderContext();
    ctx.fillText('plain', 0, 0, { fontSize: 12 });
    const out = serializeOps(ctx.ops);
    const op = out[0] as Record<string, unknown>;
    expect(op.bold).toBeUndefined();
    expect(op.italic).toBeUndefined();
    expect(op.underline).toBeUndefined();
    expect(op.strike).toBeUndefined();
    expect(op.highlight).toBeUndefined();
    expect(op.fontFamily).toBeUndefined();
  });

  it('underline=none 不寫出', () => {
    const ctx = new MockRenderContext();
    ctx.fillText('x', 0, 0, { fontSize: 12, underline: 'none' });
    const out = serializeOps(ctx.ops);
    const op = out[0] as Record<string, unknown>;
    expect(op.underline).toBeUndefined();
  });

  it('underline=single 有寫出', () => {
    const ctx = new MockRenderContext();
    ctx.fillText('x', 0, 0, { fontSize: 12, underline: 'single' });
    const out = serializeOps(ctx.ops);
    const op = out[0] as Record<string, unknown>;
    expect(op.underline).toBe('single');
  });
});

// ── serializeOpsToJson / Ndjson ───────────────────────────────────────────

describe('serializeOps — JSON / NDJSON', () => {
  it('serializeOpsToJson 為 pretty multi-line', () => {
    const json = serializeOpsToJson(makeBasic().ops);
    expect(json).toContain('\n');
    expect(json.split('\n').length).toBeGreaterThan(5);
    // valid JSON
    expect(() => JSON.parse(json)).not.toThrow();
  });

  it('serializeOpsToNdjson 每行一個 op', () => {
    const ndjson = serializeOpsToNdjson(makeBasic().ops);
    const lines = ndjson.split('\n');
    expect(lines.length).toBe(5);
    for (const line of lines) {
      expect(() => JSON.parse(line)).not.toThrow();
    }
  });
});

// ── fingerprintOps ─────────────────────────────────────────────────────────

describe('fingerprintOps', () => {
  it('total / byKind / textCharCount 正確', () => {
    const fp = fingerprintOps(makeBasic().ops);
    expect(fp.total).toBe(5);
    expect(fp.byKind.beginPage).toBe(1);
    expect(fp.byKind.endPage).toBe(1);
    expect(fp.byKind.fillRect).toBe(1);
    expect(fp.byKind.fillText).toBe(1);
    expect(fp.byKind.drawLine).toBe(1);
    expect(fp.byKind.drawImage).toBe(0);
    expect(fp.textCharCount).toBe(5); // 'Hello'
  });

  it('textHash 為 8 位 hex', () => {
    const fp = fingerprintOps(makeBasic().ops);
    expect(fp.textHash).toMatch(/^[0-9a-f]{8}$/);
  });

  it('textHash 受文字內容影響、不受位置影響', () => {
    const ctxA = new MockRenderContext();
    ctxA.fillText('hello', 10, 10, { fontSize: 12 });
    const ctxB = new MockRenderContext();
    ctxB.fillText('hello', 999, 999, { fontSize: 12 });
    expect(fingerprintOps(ctxA.ops).textHash).toBe(fingerprintOps(ctxB.ops).textHash);

    const ctxC = new MockRenderContext();
    ctxC.fillText('world', 10, 10, { fontSize: 12 });
    expect(fingerprintOps(ctxA.ops).textHash).not.toBe(fingerprintOps(ctxC.ops).textHash);
  });

  it('空 ops 也能 fingerprint', () => {
    const fp = fingerprintOps([]);
    expect(fp.total).toBe(0);
    expect(fp.textCharCount).toBe(0);
    expect(fp.textHash).toMatch(/^[0-9a-f]{8}$/);
  });
});
