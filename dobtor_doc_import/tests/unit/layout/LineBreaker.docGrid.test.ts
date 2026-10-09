/**
 * Sprint 29 — LineBreaker 套用 OOXML §17.6.5 docGrid + §17.3.1.32 snapToGrid
 *
 * 中文 docx 常設 `<w:docGrid w:type="lines" w:linePitch="364"/>` 強制 paragraph
 * baseline 對齊 grid（linePitch=364 twip = 18.2pt）。Sprint 29 之前我們完全沒
 * 處理此規則 → 三個 -1 fixture（02_std_table/1140206 取樣 / 03_complex_table/06-8
 * 估驗計價 ×2）內容剛好被 docGrid 撐到下一頁，但我們算成單頁。
 *
 * Sprint 29 規則（保守版，避免大量誤觸）：
 *   - linePitch <= 0 → 不 snap
 *   - paragraph 顯式 `snapToGrid="0"` → 不 snap
 *   - paragraph 沒設任何 `w:spacing` 的 line → 不 snap
 *     （Word 對「無顯式 spacing.line」段落不做 grid snap；
 *      實測 1121229-全套管 / 1130516-共月橋 fixture 確認）
 *   - 否則 height = ceil(declared_height / linePitch) × linePitch
 */

import { describe, expect, it } from 'vitest';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type { ParagraphNode, RunNode } from '../../../static/src/core/ooxml/ast/types';

type SpacingLine = { rule: 'exact' | 'atLeast' | 'auto'; value: number };

function paraOf(
  text: string,
  fontSize: number,
  spacingLine?: SpacingLine,
  snapToGrid?: boolean,
): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  const props: ParagraphNode['props'] = {};
  if (spacingLine) props.spacing = { line: spacingLine };
  if (snapToGrid !== undefined) props.snapToGrid = snapToGrid;
  return { type: 'paragraph', props, runs: [run] };
}

describe('Sprint 29 — LineBreaker docGrid snap', () => {
  it('linePitch=0 → 不 snap', () => {
    const para = buildParagraph(paraOf('hello', 14, { rule: 'exact', value: 25 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 0 });
    expect(lines[0].height).toBe(25);
  });

  it('linePitch=18.2 + exact 30pt → ceil(30/18.2) × 18.2 = 36.4pt', () => {
    // 對應 1140206 取樣紀錄 P5-P8 的實況（line=600 exact = 30pt）
    const para = buildParagraph(paraOf('取樣時間', 16, { rule: 'exact', value: 30 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.2 });
    expect(lines[0].height).toBeCloseTo(36.4, 4);
  });

  it('linePitch=19.25 + auto 1.15 → natural × 1.15 ceil 到 grid', () => {
    // 對應 06-8 估驗計價 P1 標題（line=276 auto ≈ 1.15）+ linePitch=385 twip=19.25pt
    // 18pt 字 natural = 18 × 1.2 = 21.6pt；× 1.15 = 24.84pt；ceil(24.84/19.25) = 2 × 19.25 = 38.5pt
    const para = buildParagraph(paraOf('估驗計價標題', 18, { rule: 'auto', value: 1.15 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 19.25 });
    expect(lines[0].height).toBeCloseTo(38.5, 4);
  });

  it('paragraph snapToGrid=false → 即使 docGrid 開啟也不 snap', () => {
    // 對應 1140206 P9-P11（清單段落1 explicit snapToGrid="0"）
    const para = buildParagraph(
      paraOf('任泰技術顧問', 16, { rule: 'exact', value: 30 }, false),
      0,
    );
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.2 });
    expect(lines[0].height).toBe(30); // 不被推到 36.4
  });

  it('段落無 spacing.line → 即使 docGrid 開啟也不 snap', () => {
    // 對應 1121229-全套管基樁混凝土查驗 系列 cell 內 paragraph（無 spacing.line）
    // 若不加此例外，會把每行 12.6pt 推到 18pt → 過度 over-paginate（regression）
    const para = buildParagraph(paraOf('hello', 10.5), 0); // 無 spacing.line
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.0 });
    // natural lineHeight = 10.5 × 1.2 = 12.6pt；不 snap → 仍 12.6
    expect(lines[0].height).toBeCloseTo(12.6, 2);
  });

  it('空段落 + 有 spacing.line + docGrid → snap 空行高度', () => {
    // 對應 1140206 P2-P3 行為（auto 1.25 空段落 → grid 對齊）
    // 14pt natural × 1.25 = 21pt；ceil(21/18.2) = 2 × 18.2 = 36.4pt
    const para: ParagraphNode = {
      type: 'paragraph',
      props: { spacing: { line: { rule: 'auto', value: 1.25 } } },
      runs: [],
    };
    const input = buildParagraph(para, 0);
    const lines = breakParagraph(input, {
      lineWidth: 500,
      docGridLinePitch: 18.2,
    });
    expect(lines.length).toBe(1);
    // 空段落 defaultFontSize fallback = 10.5pt，natural lineHeight = 12.6
    // × 1.25 = 15.75；ceil(15.75/18.2) = 1 × 18.2 = 18.2
    expect(lines[0].height).toBeCloseTo(18.2, 4);
  });

  it('linePitch 大於 exact value → ceil(1) × linePitch（向上補一格）', () => {
    // 小字（exact 14pt）+ 大 grid（20pt）→ 一行佔一格 20pt
    const para = buildParagraph(paraOf('hello', 10, { rule: 'exact', value: 14 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 20 });
    expect(lines[0].height).toBe(20);
  });

  it('多行段落都一致地 snap（greedy 斷行路徑）', () => {
    // 中文 10 字（@ 12pt CJK 1.15 em 寬 = 13.8pt/字 = 138pt），width=80 → 2 行
    const para = buildParagraph(
      paraOf('一二三四五六七八九十', 12, { rule: 'exact', value: 30 }),
      0,
    );
    const lines = breakParagraph(para, { lineWidth: 80, docGridLinePitch: 18.2 });
    expect(lines.length).toBeGreaterThanOrEqual(2);
    for (const ln of lines) {
      expect(ln.height).toBeCloseTo(36.4, 4); // 每行都 snap 到 36.4
    }
  });
});

// ── Sprint 136：isInTableCell 判別子實驗 revert（鎖定 Sprint 29 行為）─────

describe('Sprint 136 — isInTableCell 判別子 revert 鎖定（Sprint 29 行為保留）', () => {
  // Sprint 135 probe 找到候選判別子 = 「段落是否在 table cell 內」，但 Sprint 136
  // 實作（Paginator 注入 false / TableLayout 注入 true、applyDocGridSnap 對 body
  // 段落即使無 spacing.line 也 snap）VR 全 42 fixture 實測**翻車**：03 全套管
  // 5 fixture 全 +0.86~1.47pp 退化（snap 過度推高 body title 塊、photo Y
  // overshoot golden）。net aggregate +0.021pp 淨退化 → revert。
  // 詳見 docs/sprint136。本鎖定 test 確保 Sprint 29 行為穩定（無論 caller
  // 如何呼叫 buildParagraph）。
  it('Sprint 29 行為保留：body 段落（無 spacing.line）即使有 docGrid 也不 snap', () => {
    // Sprint 136 曾試把此段落 snap 到 36pt，但 VR 翻車 → revert 回 Sprint 29 行為
    const para = buildParagraph(paraOf('body title', 22), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.0 });
    expect(lines[0].height).toBeCloseTo(26.4, 2); // 22 × 1.2 = 26.4、未 snap（Sprint 29 行為）
  });

  it('Sprint 29 行為保留：cell 內段落（無 spacing.line）不 snap（不變、且 Sprint 49 已驗）', () => {
    const para = buildParagraph(paraOf('cell content', 14), 0);
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.0 });
    expect(lines[0].height).toBeCloseTo(16.8, 2);
  });

  it('Sprint 29 行為保留：有 spacing.line 的段落仍 snap', () => {
    const para = buildParagraph(
      paraOf('body with spacing', 14, { rule: 'auto', value: 1.2 }),
      0,
    );
    const lines = breakParagraph(para, { lineWidth: 500, docGridLinePitch: 18.0 });
    // 16.8 × 1.2 = 20.16; ceil(20.16/18) × 18 = 36
    expect(lines[0].height).toBeCloseTo(36, 4);
  });
});
