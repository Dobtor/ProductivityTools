/**
 * Sprint 25 — LineBreaker 套用 OOXML w:spacing line 規則
 *
 * 動機：Sprint 19 診斷 7 個剩 -1 偏差 fixture 時，發現雖然 ParagraphParser
 * 已把 spacing.line / lineRule 解析進 paragraph.props.spacing.line，但 layout
 * 引擎完全沒消費它（只 Paginator 套 spacing.before/after）。
 *
 * 對於 05_header_footer 的 3 個 fixture（人手孔調升降 / 地坪鋪面 / 植筋），
 * 段落多帶 `spacing={'line': '500', 'lineRule': 'exact'}`（每行強制 25pt），但
 * 我們 LineBreaker 仍用字型自然行高（~17pt for 14pt font），每段少 8pt × 多段
 * 累積一頁少 → 整 fixture -1 page。
 *
 * 規格依據 ECMA-376 §17.3.1.33 spacing：
 *   - lineRule="exact"   → w:line 是固定 twip
 *   - lineRule="atLeast" → w:line 是最低 twip
 *   - lineRule="auto"    → w:line 是 240 為基準的倍率
 *
 * ParagraphParser:218 已把 auto 轉成 ratio（line/240），exact/atLeast 轉成 pt
 * （twipToPt = line/20）。LineBreaker 接到的 spacing.line.value 對應這個轉換後的數值。
 */

import { describe, expect, it } from 'vitest';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type { ParagraphNode, RunNode } from '../../../static/src/core/ooxml/ast/types';

function paraOf(text: string, fontSize: number, spacingLine?: { rule: 'exact' | 'atLeast' | 'auto'; value: number }): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  const props: ParagraphNode['props'] = {};
  if (spacingLine) props.spacing = { line: spacingLine };
  return { type: 'paragraph', props, runs: [run] };
}

describe('Sprint 25 — LineBreaker 套用 spacing.line', () => {
  it('lineRule=exact 強制覆寫自然行高（即使比自然小也要套）', () => {
    // 14pt font 自然行高約 16-17pt；exact 25pt 應該蓋掉
    const para = buildParagraph(paraOf('Hello World', 14, { rule: 'exact', value: 25 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    expect(lines[0].height).toBe(25);
    expect(lines[0].baseline).toBeCloseTo(25 * 0.8, 5);
  });

  it('lineRule=exact 也可以低於自然行高（強制壓行）', () => {
    // 24pt font 自然 ~28-29pt；exact 18pt 應該硬壓成 18pt
    const para = buildParagraph(paraOf('Hello', 24, { rule: 'exact', value: 18 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    expect(lines[0].height).toBe(18);
  });

  it('lineRule=atLeast 取自然行高與 value 的較大者（自然高於 value 不變）', () => {
    // 24pt font 自然 ~28-29pt；atLeast 20pt → 保持自然
    const para = buildParagraph(paraOf('Hello', 24, { rule: 'atLeast', value: 20 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    expect(lines[0].height).toBeGreaterThan(20);
  });

  it('lineRule=atLeast 自然行高低於 value 時拉到 value', () => {
    // 10pt font 自然 ~12pt；atLeast 30pt → 拉到 30pt
    const para = buildParagraph(paraOf('Hi', 10, { rule: 'atLeast', value: 30 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    expect(lines[0].height).toBe(30);
  });

  it('lineRule=auto 把自然行高乘以 ratio（ParagraphParser 已轉成 line/240）', () => {
    // ratio = 1.5（單倍 240, 1.5倍 360 → ParagraphParser 轉成 360/240 = 1.5）
    const para = buildParagraph(paraOf('Hello', 12, { rule: 'auto', value: 1.5 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    // 自然 ~14.4pt（12 × 1.2），auto 1.5 倍 → 21.6pt 左右
    const naturalEstimate = 12 * 1.2 * 1.5;
    expect(lines[0].height).toBeCloseTo(naturalEstimate, 0);
  });

  it('無 spacing.line → 維持自然行高（行為不變）', () => {
    const para = buildParagraph(paraOf('Hello', 14), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    // 自然行高 ~17pt（14 × 1.2）；嚴格只比較不為固定 25 / 18
    expect(lines[0].height).toBeGreaterThan(14);
    expect(lines[0].height).toBeLessThan(20);
  });

  it('空段落也套用 spacing.line（exact 25pt → 空行高 25pt）', () => {
    const para = buildParagraph(paraOf('', 14, { rule: 'exact', value: 25 }), 0);
    const lines = breakParagraph(para, { lineWidth: 100 });
    expect(lines.length).toBe(1);
    expect(lines[0].items.length).toBe(0);
    expect(lines[0].height).toBe(25);
  });

  it('05_header_footer 復現：14pt + line=500 lineRule=exact → 25pt（不是字型自然 ~17pt）', () => {
    // 復現 fixture 自主檢查表---人手孔調升降.docx 段落 [3]: sz=28（half-pt=14pt）, line=500, exact
    const para = buildParagraph(paraOf('編號:01', 14, { rule: 'exact', value: 25 }), 0);
    const lines = breakParagraph(para, { lineWidth: 500 });
    expect(lines.length).toBe(1);
    expect(lines[0].height).toBe(25);
  });

  it('多行段落每行都套用 spacing.line', () => {
    // 一段長文本被斷成多行，每行高度都應為 25pt
    const long = '這是一段很長的中文文字會被斷成多行內容包含許多漢字字符以致超過行寬必須換行';
    const para = buildParagraph(paraOf(long, 14, { rule: 'exact', value: 25 }), 0);
    const lines = breakParagraph(para, { lineWidth: 80 });
    expect(lines.length).toBeGreaterThan(1);
    for (const ln of lines) {
      expect(ln.height).toBe(25);
    }
  });

  it('Knuth-Plass 路徑也套用 spacing.line（algorithm=knuth-plass）', () => {
    const long = 'word '.repeat(40);
    const para = buildParagraph(paraOf(long, 12, { rule: 'exact', value: 22 }), 0);
    const lines = breakParagraph(para, { lineWidth: 100, algorithm: 'knuth-plass' });
    expect(lines.length).toBeGreaterThan(1);
    for (const ln of lines) {
      expect(ln.height).toBe(22);
    }
  });
});
