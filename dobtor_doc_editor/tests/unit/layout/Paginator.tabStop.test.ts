/**
 * Sprint 162 — Paginator / TableLayout 透傳 LayoutOptions.defaultTabStop
 *
 * 驗證 layoutDocument 端到端：
 *   - 未傳 defaultTabStop → tab glue 維持空白寬度（Strategy C 預設路徑、baseline 不變）
 *   - 傳 defaultTabStop → body 段落 tab 解析為「推進到下一個 tab stop」
 *   - 表格 cell 內段落的 tab 同樣被解析（TableLayout 路徑）
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  TableNode,
  RowNode,
  CellNode,
  RunNode,
} from '../../../static/src/core/ooxml/ast/types';
import type { Glue, LayoutItem, Line } from '../../../static/src/core/layout/types';

const DEFAULT_TAB_STOP_PT = 36; // OOXML 預設 720 twip = 36pt

const A4_PORTRAIT = { width: 595, height: 842, orientation: 'portrait' as const };
const STD_MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section',
    page: A4_PORTRAIT,
    margins: STD_MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function paraNode(text: string): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function tableWithTab(): TableNode {
  const cell: CellNode = {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content: [paraNode('a\tb')],
    props: {},
  };
  const row: RowNode = {
    type: 'row',
    cells: [cell],
    props: { isHeader: false, cantSplit: false },
  };
  return {
    type: 'table',
    rows: [row],
    grid: [400],
    props: {},
  } as TableNode;
}

/** 收集整份 layout 所有 line 的 items（依出現順序）。 */
function allLines(sections: SectionNode[], opts: Parameters<typeof layoutDocument>[1]): Line[] {
  const layout = layoutDocument(sections, opts);
  const lines: Line[] = [];
  for (const page of layout.pages) {
    for (const e of page.entries) {
      if (e.kind === 'line') lines.push(e.line);
      else if (e.kind === 'table') {
        for (const row of e.rows) {
          for (const cell of row.cells) {
            for (const block of cell.blocks) {
              if (block.kind === 'lines') lines.push(...block.lines);
            }
          }
        }
      }
    }
  }
  return lines;
}

/** 回傳每個 isTab glue 的 {寬度, 解析後 tab 結束 x}。 */
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

describe('Sprint 162 — Paginator 未傳 defaultTabStop（Strategy C 預設路徑）', () => {
  it('body 段落 tab glue 維持空白寬度', () => {
    const lines = allLines([makeSection([paraNode('a\tb')])], {});
    const spans = lines.flatMap((l) => tabSpans(l.items));
    expect(spans.length).toBe(1);
    // 未解析 → tab 寬度 = 空白寬度（小、遠小於 36pt）
    expect(spans[0].width).toBeLessThan(DEFAULT_TAB_STOP_PT / 2);
  });
});

describe('Sprint 162 — Paginator 傳 defaultTabStop（body 段落）', () => {
  it('tab 解析為推進到下一個 default stop', () => {
    const lines = allLines(
      [makeSection([paraNode('a\tb')])],
      { defaultTabStop: DEFAULT_TAB_STOP_PT },
    );
    const spans = lines.flatMap((l) => tabSpans(l.items));
    expect(spans.length).toBe(1);
    // 'a' 寬度 < 36 → tab 結束於第一個 default stop
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
    expect(spans[0].width).toBeGreaterThan(0);
  });

  it('行首 tab → 推進到 36pt', () => {
    const lines = allLines(
      [makeSection([paraNode('\tabc')])],
      { defaultTabStop: DEFAULT_TAB_STOP_PT },
    );
    const spans = lines.flatMap((l) => tabSpans(l.items));
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
  });
});

describe('Sprint 162 — TableLayout 透傳 defaultTabStop（cell 內段落）', () => {
  it('表格 cell 內段落 tab 同樣被解析', () => {
    const lines = allLines(
      [makeSection([tableWithTab()])],
      { defaultTabStop: DEFAULT_TAB_STOP_PT },
    );
    const spans = lines.flatMap((l) => tabSpans(l.items));
    expect(spans.length).toBe(1);
    expect(spans[0].xAfter).toBeCloseTo(DEFAULT_TAB_STOP_PT, 5);
  });

  it('cell 內段落未傳 defaultTabStop → tab 維持空白寬度', () => {
    const lines = allLines([makeSection([tableWithTab()])], {});
    const spans = lines.flatMap((l) => tabSpans(l.items));
    expect(spans.length).toBe(1);
    expect(spans[0].width).toBeLessThan(DEFAULT_TAB_STOP_PT / 2);
  });
});
