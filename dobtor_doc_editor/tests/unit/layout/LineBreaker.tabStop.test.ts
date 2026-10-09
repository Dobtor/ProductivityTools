/**
 * Sprint 161 — LineBreaker tab stop 解析（settings.defaultTabStop wire-up）
 *
 * 驗證：
 *   - BoxBuilder 把 `\t` glue 標記 isTab（寬度仍為空白寬 — baseline 不變）
 *   - breakParagraph 未傳 defaultTabStop → tab glue 維持空白寬度（Strategy C 預設路徑）
 *   - 傳 defaultTabStop → tab glue 寬度重算為「推進到下一個 tab stop」
 *   - 段落顯式 props.tabs（left 對齊）優先於 default 間距
 *   - 多個 tab 連續推進
 */

import { describe, expect, it } from 'vitest';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type { ParagraphNode, ParagraphProps, RunNode } from '../../../static/src/core/ooxml/ast/types';
import type { Glue, LayoutItem } from '../../../static/src/core/layout/types';

const DEFAULT_TAB_STOP_PT = 36; // OOXML 預設 720 twip = 36pt

function paraOf(text: string, props: ParagraphProps = {}, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props, runs: [run] };
}

/** 走一行 items、回傳每個 isTab glue 的 {寬度, 解析後累積 x（tab 結束位置）}。 */
function tabSpans(items: LayoutItem[]): Array<{ width: number; xAfter: number }> {
  const out: Array<{ width: number; xAfter: number }> = [];
  let x = 0;
  for (const it of items) {
    if (it.kind === 'glue' && (it as Glue).isTab) {
      x += it.width;
      out.push({ width: it.width, xAfter: x });
    } else if (it.kind !== 'penalty') {
      x += it.width;
    }
  }
  return out;
}

describe('Sprint 161 — BoxBuilder tab 標記', () => {
  it('`\\t` 產生標記 isTab 的 glue、寬度為空白寬（baseline 不變）', () => {
    const para = buildParagraph(paraOf('a\tb'), 0);
    const tabGlues = para.items.filter(
      (it): it is Glue => it.kind === 'glue' && (it as Glue).isTab === true,
    );
    expect(tabGlues.length).toBe(1);
    // BoxBuilder 階段：tab glue 寬度 = 空白寬度（> 0、未解析）
    expect(tabGlues[0].width).toBeGreaterThan(0);
  });

  it('一般空白 glue 不帶 isTab', () => {
    const para = buildParagraph(paraOf('a b'), 0);
    const spaceGlues = para.items.filter((it) => it.kind === 'glue');
    expect(spaceGlues.length).toBeGreaterThan(0);
    expect(spaceGlues.every((g) => (g as Glue).isTab !== true)).toBe(true);
  });
});

describe('Sprint 161 — breakParagraph 未傳 defaultTabStop（Strategy C 預設路徑）', () => {
  it('tab glue 維持 BoxBuilder 空白寬度、不解析', () => {
    const para = buildParagraph(paraOf('a\tb'), 0);
    const baselineTabWidth = (para.items.find(
      (it) => it.kind === 'glue' && (it as Glue).isTab,
    ) as Glue).width;

    const lines = breakParagraph(para, { lineWidth: 500 });
    const spans = tabSpans(lines[0].items);
    expect(spans.length).toBe(1);
    expect(spans[0].width).toBeCloseTo(baselineTabWidth, 5);
  });

  it('defaultTabStop = 0 等同未傳', () => {
    const para = buildParagraph(paraOf('a\tb'), 0);
    const lines = breakParagraph(para, { lineWidth: 500, defaultTabStop: 0 });
    const spans = tabSpans(lines[0].items);
    const baselineTabWidth = (para.items.find(
      (it) => it.kind === 'glue' && (it as Glue).isTab,
    ) as Glue).width;
    expect(spans[0].width).toBeCloseTo(baselineTabWidth, 5);
  });
});

describe('Sprint 161 — breakParagraph 傳 defaultTabStop（tab stop 解析）', () => {
  it('行首 tab → 推進到第一個 default stop（36pt）', () => {
    const para = buildParagraph(paraOf('\tabc'), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    expect(spans.length).toBe(1);
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
  });

  it('短標籤後 tab → tab 結束位置 = 第一個 default stop 整數倍', () => {
    const para = buildParagraph(paraOf('a\tb'), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    // 'a' 寬度 < 36 → tab 推進到 36
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
    // tab glue 寬度 = 36 - width('a') > 0
    expect(spans[0].width).toBeGreaterThan(0);
  });

  it('連續兩個 tab → 推進到 36 再到 72', () => {
    const para = buildParagraph(paraOf('a\tb\tc'), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    expect(spans.length).toBe(2);
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
    expect(spans[1].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT * 2, 5);
  });

  it('tab 結束位置永遠落在 default stop 整數倍上', () => {
    const para = buildParagraph(paraOf('hello\tworld'), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    const ratio = spans[0].xAfter / DEFAULT_TAB_STOP_PT;
    expect(ratio).toBeCloseTo(Math.round(ratio), 5);
    expect(spans[0].width).toBeGreaterThan(0);
  });
});

describe('Sprint 161 — 段落顯式 tab stop（props.tabs）優先', () => {
  it('left 對齊顯式 stop（pos=100）→ tab 推進到 100', () => {
    const props: ParagraphProps = { tabs: [{ pos: 100, align: 'left' }] };
    const para = buildParagraph(paraOf('a\tb', props), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    expect(spans[0].xAfter).toBeCloseTo(100, 5);
  });

  it('x 已超過顯式 stop → 回落 default 間距整數倍', () => {
    // 顯式 stop pos=2（極小、'a' 寬度必 > 2）→ 第一個 tab 找不到 > x 的顯式 stop
    const props: ParagraphProps = { tabs: [{ pos: 2, align: 'left' }] };
    const para = buildParagraph(paraOf('a\tb', props), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
  });

  it('center / right 對齊 stop 不參與解析（本 sprint scope-down）', () => {
    const props: ParagraphProps = { tabs: [{ pos: 100, align: 'center' }] };
    const para = buildParagraph(paraOf('a\tb', props), 0);
    const lines = breakParagraph(para, {
      lineWidth: 500, defaultTabStop: DEFAULT_TAB_STOP_PT,
    });
    const spans = tabSpans(lines[0].items);
    // center stop 被忽略 → 回落 default 36
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
  });
});
