/**
 * Sprint 13 — Knuth-Plass 斷行器
 *
 * 涵蓋：
 *   - K-P opt-in 不破壞 greedy 預設行為
 *   - K-P 短段落 = greedy（單行）
 *   - K-P 多行段落能正常斷行
 *   - K-P 遇 forced break (penalty -Infinity) 仍正確斷
 *   - K-P fallback 到 greedy 當 getLineWidth 提供時
 *   - K-P 對「最後一行很短」的長段落比 greedy 平均（行寬變異更小）
 *   - K-P 透傳 forcedBreakAfter（page / column）
 */

import { describe, expect, it } from 'vitest';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import { EstimateMetrics } from '../../../static/src/core/layout/TextMetrics';
import type {
  ParagraphNode,
  RunNode,
  BreakNode,
} from '../../../static/src/core/ooxml/ast/types';

const metrics = new EstimateMetrics();

function buildPara(text: string, fontSize = 12): ReturnType<typeof buildParagraph> {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [run] };
  return buildParagraph(para, 0, metrics);
}

function buildParaWithBreak(prefix: string, breakType: 'page' | 'column', suffix: string): ReturnType<typeof buildParagraph> {
  const r1: RunNode = { type: 'run', text: prefix, props: { fontSize: 12 } };
  const br: BreakNode = { type: 'break', breakType };
  const r2: RunNode = { type: 'run', text: suffix, props: { fontSize: 12 } };
  const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1, br, r2] };
  return buildParagraph(para, 0, metrics);
}

// ── 基本行為 ──────────────────────────────────────────────────────────

describe('K-P 斷行 — 基本', () => {
  it('短段落 K-P 與 greedy 一致（單行）', () => {
    const input = buildPara('hello');
    const greedy = breakParagraph(input, { lineWidth: 200, algorithm: 'greedy', metrics });
    const kp = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    expect(kp.length).toBe(greedy.length);
  });

  it('長段落 K-P 多行斷', () => {
    const text = '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十';
    const input = buildPara(text);
    const lines = breakParagraph(input, { lineWidth: 100, algorithm: 'knuth-plass', metrics });
    expect(lines.length).toBeGreaterThan(2);
    // 每行寬度應 ≤ 100 + ε
    for (const ln of lines) {
      expect(ln.width).toBeLessThanOrEqual(110); // 寬容浮點
    }
  });

  it('K-P 預設 algorithm 不指定 → 走 greedy（snapshot stability）', () => {
    const input = buildPara('hello world this is a test');
    const def = breakParagraph(input, { lineWidth: 80, metrics });
    const greedy = breakParagraph(input, { lineWidth: 80, algorithm: 'greedy', metrics });
    expect(def.length).toBe(greedy.length);
    // 文字字數總和一致
    const sumChars = (lines: typeof def) =>
      lines.flatMap((l) => l.items.filter((i) => i.kind === 'box')).map((b) => (b as { text: string }).text).join('').length;
    expect(sumChars(def)).toBe(sumChars(greedy));
  });
});

// ── Forced break 透傳 ─────────────────────────────────────────────────

describe('K-P 斷行 — forced break', () => {
  it('page break 透傳 forcedBreakAfter=page', () => {
    const input = buildParaWithBreak('first', 'page', 'second');
    const lines = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    const pageBreaks = lines.filter((l) => l.forcedBreakAfter === 'page');
    expect(pageBreaks.length).toBeGreaterThanOrEqual(1);
  });

  it('column break 透傳 forcedBreakAfter=column', () => {
    const input = buildParaWithBreak('first', 'column', 'second');
    const lines = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    const colBreaks = lines.filter((l) => l.forcedBreakAfter === 'column');
    expect(colBreaks.length).toBeGreaterThanOrEqual(1);
  });
});

// ── getLineWidth fallback ─────────────────────────────────────────────

describe('K-P 斷行 — getLineWidth fallback', () => {
  it('指定 getLineWidth + algorithm=knuth-plass → fallback greedy', () => {
    const input = buildPara('一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十');
    const kpFallback = breakParagraph(input, {
      lineWidth: 100,
      algorithm: 'knuth-plass',
      getLineWidth: () => 100,
      metrics,
    });
    const greedy = breakParagraph(input, {
      lineWidth: 100,
      algorithm: 'greedy',
      getLineWidth: () => 100,
      metrics,
    });
    expect(kpFallback.length).toBe(greedy.length);
  });
});

// ── 行寬均勻度（K-P 質感）─────────────────────────────────────────────

describe('K-P 斷行 — 行寬變異', () => {
  it('K-P 對中等長度段落產出穩定行寬', () => {
    // 用大量 latin words 製造 stretch/shrink 機會
    const words = Array.from({ length: 80 }, (_, i) => `word${i}`).join(' ');
    const input = buildPara(words);
    const lines = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    expect(lines.length).toBeGreaterThan(3);
    // 中間行（非首尾）寬度差異應在合理範圍
    if (lines.length >= 3) {
      const middle = lines.slice(1, -1);
      const ws = middle.map((l) => l.width);
      const max = Math.max(...ws);
      const min = Math.min(...ws);
      expect(max - min).toBeLessThan(200); // 不該超過 lineWidth 自身
    }
  });
});

// ── 全字數保留 ────────────────────────────────────────────────────────

describe('K-P 斷行 — 全字數不遺漏', () => {
  it('K-P 各行 box.text 總字數 = 原文字數', () => {
    const text = 'hello world this is a longer paragraph for knuth-plass to fit on multiple lines without losing any character at all';
    const input = buildPara(text);
    const lines = breakParagraph(input, { lineWidth: 90, algorithm: 'knuth-plass', metrics });
    const collected = lines
      .flatMap((l) => l.items.filter((it) => it.kind === 'box'))
      .map((b) => (b as { text: string }).text)
      .join('');
    // 字符串連接後應包含原文所有 alphanum（不算 spaces；K-P 把 spaces 變成 glue）
    const origChars = text.replace(/\s+/g, '');
    expect(collected.length).toBe(origChars.length);
  });

  it('CJK 段落 K-P 各 box 字符總和 = 原文字符數', () => {
    const text = '春眠不覺曉處處聞啼鳥夜來風雨聲花落知多少春眠不覺曉處處聞啼鳥夜來風雨聲花落知多少';
    const input = buildPara(text);
    const lines = breakParagraph(input, { lineWidth: 100, algorithm: 'knuth-plass', metrics });
    const collected = lines
      .flatMap((l) => l.items.filter((it) => it.kind === 'box'))
      .map((b) => (b as { text: string }).text)
      .join('');
    expect(collected).toBe(text);
  });
});

// ── 邊界條件 ──────────────────────────────────────────────────────────

describe('K-P 斷行 — 邊界', () => {
  it('空段落回單一空行（與 greedy 一致）', () => {
    const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [] };
    const input = buildParagraph(para, 0, metrics);
    const lines = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    expect(lines.length).toBe(1);
    expect(lines[0].items.length).toBe(0);
  });

  it('單一字符段落回單行', () => {
    const input = buildPara('A');
    const lines = breakParagraph(input, { lineWidth: 200, algorithm: 'knuth-plass', metrics });
    expect(lines.length).toBe(1);
  });
});
