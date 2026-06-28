/**
 * LineBreaker — 貪婪斷行 + 中文避頭尾測試
 */

import { describe, expect, it } from 'vitest';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type { ParagraphNode, RunNode } from '../../../static/src/core/ooxml/ast/types';
import type { Box } from '../../../static/src/core/layout/types';

function paraOf(text: string, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function lineText(line: { items: { kind: string }[] }): string {
  return line.items
    .filter((i) => i.kind === 'box')
    .map((b) => (b as Box).text)
    .join('');
}

describe('LineBreaker — 簡單斷行', () => {
  it('完全空段落 → 1 行空行', () => {
    const para = buildParagraph(paraOf(''), 0);
    const lines = breakParagraph(para, { lineWidth: 100 });
    expect(lines.length).toBe(1);
    expect(lines[0].items.length).toBe(0);
    expect(lines[0].height).toBeGreaterThan(0);
  });

  it('一個短句 → 一行', () => {
    const para = buildParagraph(paraOf('hello'), 0);
    const lines = breakParagraph(para, { lineWidth: 200 });
    expect(lines.length).toBe(1);
    expect(lineText(lines[0])).toBe('hello');
  });

  it('長句超過 lineWidth → 多行', () => {
    const para = buildParagraph(paraOf('alpha beta gamma delta epsilon zeta eta'), 0);
    // 12pt 估算寬：每 token ~30pt + space ~3.2pt
    const lines = breakParagraph(para, { lineWidth: 80 });
    expect(lines.length).toBeGreaterThan(1);
    // 所有 token 都應該被分配到某行
    const allText = lines.map(lineText).join(' ');
    expect(allText).toContain('alpha');
    expect(allText).toContain('eta');
  });
});

describe('LineBreaker — CJK 字元級斷行', () => {
  it('純中文長段：每字可斷，產生多行', () => {
    const text = '一二三四五六七八九十';
    const para = buildParagraph(paraOf(text, 12), 0);
    // 12pt × 1 em × 10 字 = 120pt；lineWidth = 50 → 約 4-5 字一行
    const lines = breakParagraph(para, { lineWidth: 50 });
    expect(lines.length).toBeGreaterThanOrEqual(2);
    expect(lines.length).toBeLessThanOrEqual(5);
    // 全部 10 字仍能合起來（順序不變）
    const merged = lines.map(lineText).join('');
    expect(merged).toBe(text);
  });

  it('isLastLine 標記：最後一行 isLastLine=true，前面 false', () => {
    const para = buildParagraph(paraOf('一二三四五六七八九十', 12), 0);
    const lines = breakParagraph(para, { lineWidth: 50 });
    expect(lines[lines.length - 1].isLastLine).toBe(true);
    if (lines.length > 1) {
      expect(lines[0].isLastLine).toBe(false);
    }
  });
});

describe('LineBreaker — 避頭尾規則', () => {
  it('禁止行首字符（標點）會被推回上一行', () => {
    // Sprint 28：「abc」(18pt) + 「，」(13.8pt 在 1.15 em) = 31.8pt；lineWidth 32 剛好容
    // 但「，」是禁止行首字符，應被推回上一行
    const para = buildParagraph(paraOf('abc，def', 12), 0);
    const lines = breakParagraph(para, { lineWidth: 32 });
    // 預期 line[0] 結尾包含「，」
    if (lines.length >= 2) {
      const first = lineText(lines[0]);
      // 「，」不會落到第二行行首
      expect(lineText(lines[1]).startsWith('，')).toBe(false);
      expect(first).toContain('，');
    }
  });

  it('禁止行尾字符（左括號）會被推到下一行', () => {
    // Sprint 28：1.15 em CJK 寬，調整 lineWidth 以維持原測試語意
    const para = buildParagraph(paraOf('abc（def', 12), 0);
    const lines = breakParagraph(para, { lineWidth: 30 });
    if (lines.length >= 2) {
      const first = lineText(lines[0]);
      expect(first.endsWith('（')).toBe(false);
    }
  });
});

describe('LineBreaker — 強制斷行', () => {
  it('line break penalty 強制斷行', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'a', props: { fontSize: 12 } },
        { type: 'break', breakType: 'line' },
        { type: 'run', text: 'b', props: { fontSize: 12 } },
      ],
    };
    const input = buildParagraph(para, 0);
    const lines = breakParagraph(input, { lineWidth: 200 });
    expect(lines.length).toBe(2);
    expect(lineText(lines[0])).toBe('a');
    expect(lineText(lines[1])).toBe('b');
  });
});

describe('LineBreaker — alignment 透傳', () => {
  it('alignment=center 從段落 props 傳到每行', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: { alignment: 'center' },
      runs: [{ type: 'run', text: 'x', props: { fontSize: 12 } }],
    };
    const input = buildParagraph(para, 0);
    const lines = breakParagraph(input, { lineWidth: 100 });
    expect(lines[0].alignment).toBe('center');
  });
});

describe('LineBreaker — Sprint 44 image-only line baseline', () => {
  // Sprint 43 診斷：image 無 descender，image-only line 的 baseline 應 = height（非 height × 0.8）
  // 否則 image y_drawn = yBaseline - height = baseY - 0.2h（被推到 cell padding 上方）
  function imageParaOf(width: number, height: number): ParagraphNode {
    return {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'inlineImage', rId: 'imgX', width, height }],
    };
  }

  it('image-only line：baseline === line.height（無 descender）', () => {
    const para = buildParagraph(imageParaOf(200, 276), 0);
    const lines = breakParagraph(para, { lineWidth: 400 });
    expect(lines.length).toBe(1);
    const ln = lines[0];
    // 修法後：baseline 應 = height（image bottom 對齊 baseline）
    expect(ln.baseline).toBeCloseTo(ln.height, 3);
    // 連帶驗證 height 反映 image height（含可能的 spacing 修正，至少 ≥ 276）
    expect(ln.height).toBeGreaterThanOrEqual(276);
  });

  it('純文字 line：baseline 仍維持 height × 0.8（不受影響）', () => {
    const para = buildParagraph(paraOf('hello', 12), 0);
    const lines = breakParagraph(para, { lineWidth: 400 });
    expect(lines.length).toBe(1);
    const ln = lines[0];
    expect(ln.baseline).toBeCloseTo(ln.height * 0.8, 3);
  });

  it('image + text 混合 line：視為非 image-only，baseline = height × 0.8', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'inlineImage', rId: 'imgY', width: 50, height: 40 },
        { type: 'run', text: 'caption', props: { fontSize: 12 } },
      ],
    };
    const input = buildParagraph(para, 0);
    const lines = breakParagraph(input, { lineWidth: 400 });
    expect(lines.length).toBe(1);
    const ln = lines[0];
    // 混合行有文字 → 保留 0.8 ratio（文字仍需 descender 空間）
    expect(ln.baseline).toBeCloseTo(ln.height * 0.8, 3);
  });

  it('空行 makeEmptyLine 不受影響（baseline = height × 0.8）', () => {
    const para = buildParagraph(paraOf(''), 0);
    const lines = breakParagraph(para, { lineWidth: 100 });
    expect(lines.length).toBe(1);
    expect(lines[0].baseline).toBeCloseTo(lines[0].height * 0.8, 3);
  });
});

describe('LineBreaker — Sprint 46：exact 行仍 snap 到 docGrid（Sprint 29 行為，已驗證正確）', () => {
  // Sprint 46 曾試「exact 行不 snap」（依 Sprint 43 §5 假設 A2），但 VR 證實全域災難
  // 退化 04_with_image（0.1250 → 0.3236）→ 已 revert。本 test 鎖定「exact 行仍 snap」
  // 是當前正確行為（環清表 exact 行 snapped 才對齊 golden）。
  it('lineRule=exact 行：docGridLinePitch 仍上推到 pitch 整數倍', () => {
    const exactPara: ParagraphNode = {
      type: 'paragraph',
      props: { spacing: { line: { rule: 'exact', value: 23 } } },
      runs: [{ type: 'run', text: '工程名稱', props: { fontSize: 12 } }],
    };
    const para = buildParagraph(exactPara, 0);
    const lines = breakParagraph(para, { lineWidth: 400, docGridLinePitch: 18 });
    expect(lines.length).toBe(1);
    // exact 23pt 被 snap 成 ceil(23/18)*18 = 36pt（Sprint 29 行為，VR 證實對 04 正確）
    expect(lines[0].height).toBeCloseTo(36, 3);
  });

  // Sprint 49：曾試「無 spacing.line 段落也 snap」（Pillow 實測 golden 03 全套管 title
  // 段落 snap 到 36pt），但 VR 證實全域翻車（02_std_table +3.61pp、total +0.27pp）→
  // 已 revert。本 test 鎖定「無 spacing.line → 不 snap」是當前正確行為（Sprint 29）。
  it('Sprint 49：無 spacing.line 段落 → 不 snap（Sprint 29 行為，VR 證實對 02 正確）', () => {
    const para = buildParagraph(paraOf('任泰技術顧問', 22), 0);
    const lines = breakParagraph(para, { lineWidth: 400, docGridLinePitch: 18 });
    expect(lines.length).toBe(1);
    // 無 spacing.line → 維持 natural 26.4pt（不被 snap 成 36pt）
    expect(lines[0].height).toBeCloseTo(26.4, 1);
  });
});

describe('LineBreaker — firstLineIndent', () => {
  it('首行縮排扣減第一行可用寬度（足以擠出多一行）', () => {
    // Sprint 28：5 個 CJK × 12pt × 1.15 em = 69pt；改用 lineWidth 70 容得下 5 字
    const para = buildParagraph(paraOf('一二三四五', 12), 0);
    const noIndent = breakParagraph(para, { lineWidth: 70 });
    // 無縮排：70pt 容 5 字
    expect(noIndent.length).toBe(1);
    const withIndent = breakParagraph(para, { lineWidth: 70, firstLineIndent: 28 });
    // 縮排 28pt → 首行只剩 42pt，~3 字進首行，第二行 ~2 字
    expect(withIndent.length).toBe(2);
  });
});
