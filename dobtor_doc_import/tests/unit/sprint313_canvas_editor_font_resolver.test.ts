/**
 * Sprint 313 — ① deeper⁴：CanvasEditorFontResolver。
 *
 * Sprint 303/308 之後第三輪深推。Canvas2D ctx.font 是 CSS shorthand 字串、
 * caller 接管 measureText 時需從中解 family + sizePt 給 bridge。本 sprint 補
 * parser + formatter pure-fn。
 *
 * 紀律 #18 scope-down：輕量 PROBE-grade parser；不對齊 browser native 100%。
 */
import { describe, expect, it } from 'vitest';

import {
  parseCanvasFont,
  formatCanvasFont,
} from '../../static/src/core/ooxml/font/CanvasEditorFontResolver';

// ── 基本 size + family ──────────────────────────────────────────────────

describe('Sprint 313 — 基本解析', () => {
  it('"12pt DejaVu Sans" → family + sizePt', () => {
    expect(parseCanvasFont('12pt DejaVu Sans')).toEqual({
      family: 'DejaVu Sans',
      sizePt: 12,
    });
  });

  it('px → pt 換算（96 dpi）', () => {
    const r = parseCanvasFont('16px Arial');
    // 16px * 72/96 = 12pt
    expect(r.sizePt).toBeCloseTo(12);
    expect(r.family).toBe('Arial');
  });

  it('em / rem 用 baseSizePt 換算', () => {
    const r1 = parseCanvasFont('1.5em "Source Han"', { baseSizePt: 10 });
    expect(r1.sizePt).toBe(15);
    const r2 = parseCanvasFont('2rem Arial', { baseSizePt: 8 });
    expect(r2.sizePt).toBe(16);
  });

  it('% 用 baseSizePt 換算', () => {
    expect(parseCanvasFont('150% Arial', { baseSizePt: 10 }).sizePt).toBe(15);
  });
});

// ── style / weight 前綴 ────────────────────────────────────────────────

describe('Sprint 313 — style / weight 前綴', () => {
  it('"bold 14pt Arial" → weight: bold', () => {
    expect(parseCanvasFont('bold 14pt Arial')).toEqual({
      family: 'Arial',
      sizePt: 14,
      weight: 'bold',
    });
  });

  it('"italic 14pt Arial" → style: italic', () => {
    expect(parseCanvasFont('italic 14pt Arial')).toEqual({
      family: 'Arial',
      sizePt: 14,
      style: 'italic',
    });
  });

  it('"bold italic 16pt Times" → style + weight 一起', () => {
    expect(parseCanvasFont('bold italic 16pt Times')).toEqual({
      family: 'Times',
      sizePt: 16,
      weight: 'bold',
      style: 'italic',
    });
  });

  it('順序可顛倒：italic bold 14pt 也 ok', () => {
    const r = parseCanvasFont('italic bold 14pt Arial');
    expect(r.weight).toBe('bold');
    expect(r.style).toBe('italic');
  });

  it('numeric weight 100-900', () => {
    expect(parseCanvasFont('700 14pt Arial').weight).toBe(700);
  });
});

// ── quoted family ─────────────────────────────────────────────────────

describe('Sprint 313 — quoted family', () => {
  it("'Noto Sans CJK TC' 含空白、用單引號", () => {
    const r = parseCanvasFont(`14pt 'Noto Sans CJK TC'`);
    expect(r.family).toBe('Noto Sans CJK TC');
  });

  it('"Microsoft JhengHei" 用雙引號', () => {
    const r = parseCanvasFont(`14pt "Microsoft JhengHei"`);
    expect(r.family).toBe('Microsoft JhengHei');
  });
});

// ── fallback list ─────────────────────────────────────────────────────

describe('Sprint 313 — fallback list', () => {
  it('comma-separated → fallbacks', () => {
    const r = parseCanvasFont(`12pt "Noto Sans", Arial, sans-serif`);
    expect(r.family).toBe('Noto Sans');
    expect(r.fallbacks).toEqual(['Arial', 'sans-serif']);
  });

  it('單一 family → 無 fallbacks', () => {
    const r = parseCanvasFont('12pt Arial');
    expect(r.fallbacks).toBeUndefined();
  });
});

// ── round-trip ────────────────────────────────────────────────────────

describe('Sprint 313 — formatCanvasFont round-trip', () => {
  it('basic round-trip', () => {
    const orig = { family: 'Arial', sizePt: 14 };
    const formatted = formatCanvasFont(orig);
    expect(formatted).toBe('14pt Arial');
    expect(parseCanvasFont(formatted)).toMatchObject(orig);
  });

  it('with style + weight + fallback', () => {
    const orig = {
      family: 'Noto Sans CJK',
      sizePt: 16,
      style: 'italic' as const,
      weight: 'bold' as const,
      fallbacks: ['sans-serif'],
    };
    const formatted = formatCanvasFont(orig);
    expect(formatted).toBe(`italic bold 16pt 'Noto Sans CJK', sans-serif`);
    const parsed = parseCanvasFont(formatted);
    expect(parsed.family).toBe(orig.family);
    expect(parsed.sizePt).toBe(orig.sizePt);
    expect(parsed.style).toBe(orig.style);
    expect(parsed.weight).toBe(orig.weight);
  });
});

// ── 邊界 / 錯誤 ────────────────────────────────────────────────────────

describe('Sprint 313 — 錯誤處理', () => {
  it('空字串 → throw', () => {
    expect(() => parseCanvasFont('')).toThrow(/empty font/);
  });

  it('無 size → throw', () => {
    expect(() => parseCanvasFont('Arial')).toThrow();
  });

  it('size 後無 family → throw', () => {
    expect(() => parseCanvasFont('12pt')).toThrow(/no family/);
  });

  it('不識別 size unit → throw', () => {
    expect(() => parseCanvasFont('12vw Arial')).toThrow();
  });
});
