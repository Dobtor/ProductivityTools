/**
 * Sprint 6 — 不等寬欄 + Cell blocks ordered + wrapSquare per-y lineWidth
 */

import { describe, expect, it } from 'vitest';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import { layoutCell } from '../../../static/src/core/layout/TableLayout';
import { breakParagraph } from '../../../static/src/core/layout/LineBreaker';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type {
  SectionNode,
  ParagraphNode,
  TableNode,
  CellNode,
  RowNode,
  RunNode,
  FloatImageNode,
} from '../../../static/src/core/ooxml/ast/types';

const A4_PORTRAIT = { width: 595, height: 842, orientation: 'portrait' as const };
const STD_MARGINS = {
  top: 72, bottom: 72, left: 72, right: 72,
  header: 36, footer: 36,
};

function makeSection(
  body: SectionNode['body'] = [],
  columns?: SectionNode['columns'],
): SectionNode {
  return {
    type: 'section',
    page: A4_PORTRAIT,
    margins: STD_MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
    ...(columns ? { columns } : {}),
  };
}

function paraNode(text: string, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function cellNode(content: CellNode['content']): CellNode {
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content,
    props: {},
  };
}

function rowNode(cells: CellNode[]): RowNode {
  return {
    type: 'row',
    cells,
    props: { isHeader: false, cantSplit: false },
  };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return { type: 'table', grid, rows, props: {} };
}

function floatImg(
  rId: string,
  wrapType: FloatImageNode['wrapType'],
  width: number,
  height: number,
  align: 'left' | 'right' | 'center' = 'left',
): FloatImageNode {
  return {
    type: 'floatImage',
    rId,
    width,
    height,
    posH: { relativeFrom: 'margin', align },
    posV: { relativeFrom: 'margin' },
    wrapType,
  };
}

function paraWithFloat(text: string, img: FloatImageNode): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize: 12 } };
  return { type: 'paragraph', props: {}, runs: [img, run] };
}

// ── 不等寬欄 ─────────────────────────────────────────────────────────────

describe('Sprint 6 — 不等寬欄 colWidths', () => {
  it('colWidths=[100, 300]：兩個 X 不同 + 寬度照給定', () => {
    const fillers = Array.from({ length: 80 }, (_, i) => paraNode(`段${i}`));
    const sec = makeSection(fillers, {
      count: 2,
      space: 20,
      equalWidth: false,
      colWidths: [100, 300],
    });
    const layout = layoutDocument([sec]);
    const lineEntries = layout.pages
      .flatMap((p) => p.entries.filter((e) => e.kind === 'line'));
    // 收集兩欄的不同 x
    const xValues = [...new Set(lineEntries.map((e) => Math.round(e.x)))].sort((a, b) => a - b);
    expect(xValues.length).toBeGreaterThanOrEqual(2);
    // 第二欄 X = marginLeft(72) + 100 + 20 = 192
    expect(xValues[1]).toBe(192);
  });

  it('colWidths 缺值（含 0）時平均分配剩餘空間', () => {
    const fillers = Array.from({ length: 30 }, (_, i) => paraNode(`段${i}`));
    const sec = makeSection(fillers, {
      count: 3,
      space: 18,
      equalWidth: false,
      colWidths: [200, 0, 0], // 第 0 欄 200pt，1/2 欄共享剩餘
    });
    const layout = layoutDocument([sec]);
    expect(layout.pages.length).toBeGreaterThan(0);
    // 沒 throw 即可，行數合理
    const lineCount = layout.pages
      .flatMap((p) => p.entries.filter((e) => e.kind === 'line')).length;
    expect(lineCount).toBe(30);
  });
});

// ── Cell blocks ordered ─────────────────────────────────────────────────

describe('Sprint 6 — Cell blocks ordered', () => {
  it('cell content order: paragraph → table → paragraph 在 blocks 內依序保留', () => {
    const inner = tableNode(
      [50, 50],
      [rowNode([cellNode([paraNode('inner1')]), cellNode([paraNode('inner2')])])],
    );
    const outerCell = cellNode([
      paraNode('before'),
      inner,
      paraNode('after'),
    ]);
    const out = layoutCell(outerCell, 200, 0, tableNode([200], []));
    expect(out.blocks.length).toBe(3);
    expect(out.blocks[0].kind).toBe('lines');
    expect(out.blocks[0].sourceIndex).toBe(0);
    expect(out.blocks[1].kind).toBe('table');
    expect(out.blocks[1].sourceIndex).toBe(1);
    expect(out.blocks[2].kind).toBe('lines');
    expect(out.blocks[2].sourceIndex).toBe(2);
  });

  it('blocks 與 lines/nestedTables 平面欄位內容一致', () => {
    const inner = tableNode([50], [rowNode([cellNode([paraNode('x')])])]);
    const outerCell = cellNode([paraNode('p1'), inner, paraNode('p2')]);
    const out = layoutCell(outerCell, 200, 0, tableNode([200], []));
    // lines 平面（兩個段落）
    expect(out.lines.length).toBeGreaterThanOrEqual(2);
    // nestedTables 平面（一個巢狀）
    expect(out.nestedTables?.length).toBe(1);
    // blocks 反映原始順序
    const linesBlocks = out.blocks.filter((b) => b.kind === 'lines');
    const tableBlocks = out.blocks.filter((b) => b.kind === 'table');
    expect(linesBlocks.length).toBe(2);
    expect(tableBlocks.length).toBe(1);
  });
});

// ── wrapSquare per-y lineWidth ──────────────────────────────────────────

describe('Sprint 6 — wrapSquare per-y lineWidth', () => {
  it('LineBreaker getLineWidth callback：行寬隨 y 變化', () => {
    // 60 字 12pt（總 720pt）；前 2 行 lineWidth=200（容 16 字×2=32），第 3+ 行只剩 50
    // 預期：32 字佔前 2 行，剩 28 字以 50pt 寬切細，共 ~7 行
    const para = buildParagraph(paraNode('一'.repeat(60), 12), 0);
    const lines = breakParagraph(para, {
      lineWidth: 200,
      getLineWidth: (li) => (li >= 2 ? 50 : 200),
    });
    // 前 2 行寬，後面狹窄 → 應 > 4 行
    expect(lines.length).toBeGreaterThan(4);
  });

  it('LineBreaker getLineXOffset callback：line.xOffset 帶通', () => {
    const para = buildParagraph(paraNode('一二三', 12), 0);
    const lines = breakParagraph(para, {
      lineWidth: 200,
      getLineXOffset: (li) => (li === 0 ? 30 : 0),
    });
    expect(lines[0].xOffset).toBe(30);
  });

  it('wrapSquare 左 float：後續 line 的 x 被推右、寬度縮減', () => {
    // 圖 100×100 在頁面左側；段落多行
    const longText = '一'.repeat(50);
    const img = floatImg('rImg', 'square', 100, 100, 'left');
    const sec = makeSection([paraWithFloat(longText, img)]);
    const layout = layoutDocument([sec]);

    // 第一頁 entries 中有 floatImage + 多 line entries
    const page1 = layout.pages[0];
    const lineEntries = page1.entries.filter((e) => e.kind === 'line');
    const floatEntry = page1.entries.find((e) => e.kind === 'floatImage');
    expect(floatEntry).toBeDefined();

    // 頭幾行（與圖片同 y 範圍）的 x 應大於 marginLeft（被左 float 推右）
    if (floatEntry && lineEntries.length > 0) {
      const imgBottom = floatEntry.y + floatEntry.height;
      const overlapLines = lineEntries.filter((e) => e.y < imgBottom);
      expect(overlapLines.length).toBeGreaterThan(0);
      // 至少有一條 overlap line 的 x > marginLeft（72）
      const pushedRight = overlapLines.some((e) => e.x > 72);
      expect(pushedRight).toBe(true);
    }
  });

  it('wrapSquare：圖片下方的 line 恢復原 x（不被 float 影響）', () => {
    // 大量段落讓 line 流到圖片下方
    const img = floatImg('rImg', 'square', 100, 80, 'left');
    const longParas = Array.from({ length: 30 }, () => paraNode('一'.repeat(20)));
    const sec = makeSection([
      paraWithFloat('headline', img),
      ...longParas,
    ]);
    const layout = layoutDocument([sec]);
    const allLines = layout.pages.flatMap((p) => p.entries.filter((e) => e.kind === 'line'));
    // 找到最低的 line（y 最大）
    const maxY = Math.max(...allLines.map((e) => e.y));
    const bottomLines = allLines.filter((e) => e.y === maxY);
    // 底部的 line 的 x 應等於 marginLeft（不被 float 推右）
    expect(bottomLines.every((e) => Math.round(e.x) === 72)).toBe(true);
  });
});
