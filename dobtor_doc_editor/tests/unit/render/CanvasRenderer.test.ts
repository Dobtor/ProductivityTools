/**
 * CanvasRenderer + MockRenderContext — Sprint 8 / Phase 5 起步
 *
 * 涵蓋：
 *   - 走訪 layoutDocument 輸出，每頁有 beginPage/endPage 對稱
 *   - line entry → fillText（per-Box）
 *   - table entry → fillText（cell 內 lines）+ drawLine（4 邊邊框）
 *   - image / floatImage → drawImage
 *   - fillPageBackground 開關
 *   - drawTableBorders 開關
 *   - 邊框 nil/none 不畫
 */

import { describe, expect, it } from 'vitest';
import { CanvasRenderer } from '../../../static/src/core/render/CanvasRenderer';
import { computeAlignmentShift } from '../../../static/src/core/layout/alignmentShift';
import { MockRenderContext } from '../../../static/src/core/render/MockRenderContext';
import { layoutDocument } from '../../../static/src/core/layout/Paginator';
import type {
  SectionNode,
  ParagraphNode,
  RunNode,
  TableNode,
  RowNode,
  CellNode,
  CellBorders,
} from '../../../static/src/core/ooxml/ast/types';

const A4 = { width: 595, height: 842, orientation: 'portrait' as const };
const MARGINS = { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 };

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section',
    page: A4,
    margins: MARGINS,
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function para(text: string, fontSize = 12): ParagraphNode {
  const run: RunNode = { type: 'run', text, props: { fontSize } };
  return { type: 'paragraph', props: {}, runs: [run] };
}

function cellNode(content: CellNode['content'], borders?: CellBorders): CellNode {
  const props: CellNode['props'] = {};
  if (borders) props.borders = borders;
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content,
    props,
  };
}

function rowNode(cells: CellNode[]): RowNode {
  return { type: 'row', cells, props: { isHeader: false, cantSplit: false } };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return { type: 'table', grid, rows, props: {} };
}

const SOLID_BLACK: CellBorders = {
  top: { style: 'single', width: 0.5, color: '000000' },
  bottom: { style: 'single', width: 0.5, color: '000000' },
  left: { style: 'single', width: 0.5, color: '000000' },
  right: { style: 'single', width: 0.5, color: '000000' },
};

describe('CanvasRenderer — 頁面框架', () => {
  it('每頁開始/結束指令對稱', () => {
    const sec = makeSection([para('hello'), para('world')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const begins = ctx.filter('beginPage');
    const ends = ctx.filter('endPage');
    expect(begins.length).toBe(ends.length);
    expect(begins.length).toBeGreaterThan(0);

    // 第一個是 beginPage
    expect(ctx.ops[0].kind).toBe('beginPage');
    // 最後一個是 endPage
    expect(ctx.ops[ctx.ops.length - 1].kind).toBe('endPage');
  });

  it('fillPageBackground=true 在每頁開頭加白色 fillRect', () => {
    const sec = makeSection([para('hi')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { fillPageBackground: true }).render(layoutDocument([sec]));

    // beginPage 後的第一個 op 應為 fillRect 白色背景
    const idx = ctx.ops.findIndex((op) => op.kind === 'beginPage');
    expect(idx).toBeGreaterThanOrEqual(0);
    const next = ctx.ops[idx + 1];
    expect(next.kind).toBe('fillRect');
    if (next.kind === 'fillRect') {
      expect(next.color.toUpperCase()).toBe('FFFFFF');
      expect(next.x).toBe(0);
      expect(next.y).toBe(0);
    }
  });

  it('fillPageBackground=false 不畫背景', () => {
    const sec = makeSection([para('hi')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { fillPageBackground: false }).render(layoutDocument([sec]));
    const fills = ctx.filter('fillRect');
    expect(fills.length).toBe(0);
  });

  it('Sprint 171：未傳 pageBackgroundColor → 預設白底（byte-identical）', () => {
    const sec = makeSection([para('hi')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    const idx = ctx.ops.findIndex((op) => op.kind === 'beginPage');
    const next = ctx.ops[idx + 1];
    expect(next.kind).toBe('fillRect');
    if (next.kind === 'fillRect') expect(next.color.toUpperCase()).toBe('FFFFFF');
  });

  it('Sprint 171：pageBackgroundColor 指定 → 頁底色用該色（OOXML <w:background>）', () => {
    const sec = makeSection([para('hi')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { pageBackgroundColor: 'FFFF00' }).render(layoutDocument([sec]));
    const idx = ctx.ops.findIndex((op) => op.kind === 'beginPage');
    const next = ctx.ops[idx + 1];
    expect(next.kind).toBe('fillRect');
    if (next.kind === 'fillRect') {
      expect(next.color.toUpperCase()).toBe('FFFF00');
      expect(next.x).toBe(0);
      expect(next.y).toBe(0);
    }
  });
});

describe('CanvasRenderer — 文字行', () => {
  it('每行至少送出一個 fillText（含 box 內容）', () => {
    const sec = makeSection([para('hello world'), para('second line')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const texts = ctx.filter('fillText');
    expect(texts.length).toBeGreaterThanOrEqual(2);
    // 每個 fillText 的 fontSize 應 = 12（para 預設）
    for (const t of texts) {
      expect(t.style.fontSize).toBe(12);
    }
  });

  it('文字座標在頁面 margin box 內', () => {
    const sec = makeSection([para('content')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const texts = ctx.filter('fillText');
    expect(texts.length).toBeGreaterThan(0);
    for (const t of texts) {
      expect(t.x).toBeGreaterThanOrEqual(MARGINS.left - 1);
      expect(t.x).toBeLessThanOrEqual(A4.width - MARGINS.right + 1);
      expect(t.y).toBeGreaterThan(MARGINS.top - 5);
      expect(t.y).toBeLessThan(A4.height - MARGINS.bottom + 5);
    }
  });

  it('multi-run paragraph 每 box 各送一個 fillText', () => {
    const r1: RunNode = { type: 'run', text: 'foo ', props: { fontSize: 12, bold: true } };
    const r2: RunNode = { type: 'run', text: 'bar', props: { fontSize: 12, italic: true } };
    const p: ParagraphNode = { type: 'paragraph', props: {}, runs: [r1, r2] };
    const sec = makeSection([p]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const texts = ctx.filter('fillText');
    // 兩個 run 至少各 1 個 box
    expect(texts.length).toBeGreaterThanOrEqual(2);
    const hasBold = texts.some((t) => t.style.bold === true);
    const hasItalic = texts.some((t) => t.style.italic === true);
    expect(hasBold).toBe(true);
    expect(hasItalic).toBe(true);
  });
});

describe('CanvasRenderer — 表格', () => {
  it('cell 內文字逐 line 送 fillText', () => {
    const c = cellNode([para('cell content')]);
    const r = rowNode([c]);
    const t = tableNode([200], [r]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const texts = ctx.filter('fillText');
    expect(texts.length).toBeGreaterThan(0);
  });

  it('cell 含 borders 時畫 4 條 drawLine', () => {
    const c = cellNode([para('x')], SOLID_BLACK);
    const r = rowNode([c]);
    const t = tableNode([200], [r]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    const lines = ctx.filter('drawLine');
    // 一個 cell 4 邊
    expect(lines.length).toBe(4);
    // 每條線顏色為黑、寬 0.5
    for (const ln of lines) {
      expect(ln.style.color.toUpperCase()).toBe('000000');
      expect(ln.style.width).toBe(0.5);
    }
  });

  it('drawTableBorders=false 不畫 cell 邊框', () => {
    const c = cellNode([para('x')], SOLID_BLACK);
    const r = rowNode([c]);
    const t = tableNode([200], [r]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { drawTableBorders: false }).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBe(0);
  });

  it('borders.style=nil 不畫', () => {
    const nilBorders: CellBorders = {
      top: { style: 'nil', width: 0, color: '000000' },
      bottom: { style: 'none', width: 0, color: '000000' },
      left: { style: 'single', width: 0.5, color: '000000' },
      right: { style: 'single', width: 0.5, color: '000000' },
    };
    const c = cellNode([para('x')], nilBorders);
    const t = tableNode([200], [rowNode([c])]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    // 只剩 left + right 兩條
    expect(ctx.filter('drawLine').length).toBe(2);
  });

  it('多列表格每列 cell 邊框都畫', () => {
    const r1 = rowNode([cellNode([para('a')], SOLID_BLACK)]);
    const r2 = rowNode([cellNode([para('b')], SOLID_BLACK)]);
    const t = tableNode([200], [r1, r2]);
    const sec = makeSection([t]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    expect(ctx.filter('drawLine').length).toBe(8); // 2 cells × 4 邊
  });
});

describe('CanvasRenderer — Sprint 32 paragraph alignment', () => {
  it('computeAlignmentShift center：留白平均分配到左右', () => {
    expect(computeAlignmentShift('center', 100, 300)).toBe(100);
    expect(computeAlignmentShift('center', 200, 200)).toBe(0);
    expect(computeAlignmentShift('center', 50, 100)).toBe(25);
  });

  it('computeAlignmentShift right：留白推到左側', () => {
    expect(computeAlignmentShift('right', 100, 300)).toBe(200);
    expect(computeAlignmentShift('right', 200, 200)).toBe(0);
  });

  it('computeAlignmentShift left/justify/distribute/undefined：不偏移', () => {
    expect(computeAlignmentShift('left', 100, 300)).toBe(0);
    expect(computeAlignmentShift('justify', 100, 300)).toBe(0);
    expect(computeAlignmentShift('distribute', 100, 300)).toBe(0);
    expect(computeAlignmentShift(undefined, 100, 300)).toBe(0);
  });

  it('computeAlignmentShift overflow 安全網：content > lineWidth 時回傳 0', () => {
    // 圖片或文字超寬時不應推出負偏移把內容推出可視範圍
    expect(computeAlignmentShift('center', 500, 300)).toBe(0);
    expect(computeAlignmentShift('right', 500, 300)).toBe(0);
  });

  it('center 對齊段落：fillText 的 x 比 left 對齊的 x 大（內容置中）', () => {
    // 同一段文字在 left vs center 對齊下，center 的 x 起點應較大（被推到中間）
    const leftPara: ParagraphNode = {
      type: 'paragraph',
      props: { alignment: 'left' },
      runs: [{ type: 'run', text: 'hi', props: { fontSize: 12 } }],
    };
    const centerPara: ParagraphNode = {
      type: 'paragraph',
      props: { alignment: 'center' },
      runs: [{ type: 'run', text: 'hi', props: { fontSize: 12 } }],
    };

    const ctxL = new MockRenderContext();
    new CanvasRenderer(ctxL).render(layoutDocument([makeSection([leftPara])]));
    const ctxC = new MockRenderContext();
    new CanvasRenderer(ctxC).render(layoutDocument([makeSection([centerPara])]));

    const leftFill = ctxL.filter('fillText')[0] as { x: number };
    const centerFill = ctxC.filter('fillText')[0] as { x: number };
    expect(centerFill.x).toBeGreaterThan(leftFill.x);
  });

  it('right 對齊段落：fillText 的 x 比 center 對齊還大（內容貼右）', () => {
    const centerPara: ParagraphNode = {
      type: 'paragraph',
      props: { alignment: 'center' },
      runs: [{ type: 'run', text: 'hi', props: { fontSize: 12 } }],
    };
    const rightPara: ParagraphNode = {
      type: 'paragraph',
      props: { alignment: 'right' },
      runs: [{ type: 'run', text: 'hi', props: { fontSize: 12 } }],
    };

    const ctxC = new MockRenderContext();
    new CanvasRenderer(ctxC).render(layoutDocument([makeSection([centerPara])]));
    const ctxR = new MockRenderContext();
    new CanvasRenderer(ctxR).render(layoutDocument([makeSection([rightPara])]));

    const centerFill = ctxC.filter('fillText')[0] as { x: number };
    const rightFill = ctxR.filter('fillText')[0] as { x: number };
    expect(rightFill.x).toBeGreaterThan(centerFill.x);
  });
});

describe('CanvasRenderer — Sprint 33 vMerge anchor 合併高度', () => {
  function makeRowsWithVMerge(): SectionNode {
    // 2 rows × 3 cols; col 0 是 vMerge anchor 跨 2 列；col 1 是稀疏文字；col 2 是高文字（撐高 row）
    const para = (text: string): ParagraphNode => ({
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text, props: { fontSize: 12 } }],
    });
    // anchor cell（rowSpan = 2，僅出現在 row 0；row 1 同 gridCol 位置放 continuation）
    const anchor: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 2,
      isContinuation: false,
      content: [para('工程名稱：磺港溪')],
      props: { borders: SOLID_BLACK },
    };
    const continuation: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: true,
      content: [],
      props: {},
    };
    const c1r0: CellNode = {
      type: 'cell',
      gridCol: 1,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para('說明a')],
      props: { borders: SOLID_BLACK },
    };
    const c2r0: CellNode = {
      // 撐高 row 0 用：多行文字
      type: 'cell',
      gridCol: 2,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para('A'), para('B'), para('C'), para('D')],
      props: { borders: SOLID_BLACK },
    };
    const c1r1: CellNode = { ...c1r0, content: [para('說明b')] };
    const c2r1: CellNode = { ...c2r0 };
    const rows: RowNode[] = [
      { type: 'row', cells: [anchor, c1r0, c2r0], props: { isHeader: false, cantSplit: false } },
      { type: 'row', cells: [continuation, c1r1, c2r1], props: { isHeader: false, cantSplit: false } },
    ];
    const table = tableNode([100, 100, 200], rows);
    return makeSection([table]);
  }

  it('vMerge anchor cell 的底邊框 y 座標延伸到 row[1] 結尾（不停在 row[0]）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeRowsWithVMerge()]));

    // 取所有 drawLine 找 anchor 那欄（最左邊 x ≈ 72；寬度 100pt）的水平線（y1 === y2）
    const horizLines = ctx.filter('drawLine').filter(
      (op: any) => Math.abs(op.y1 - op.y2) < 0.01,
    ) as Array<{ x1: number; y1: number; y2: number; x2: number }>;

    // anchor cell x 範圍大約 [72, 172]
    const anchorHorizLines = horizLines.filter((op) => op.x1 < 100 && op.x2 < 200);
    expect(anchorHorizLines.length).toBeGreaterThan(0);

    // anchor 的 top 與 bottom 應該分別在 page top margin 與一個明顯較大的 y
    const ys = anchorHorizLines.map((op) => op.y1).sort((a, b) => a - b);
    const top = ys[0];
    const bottom = ys[ys.length - 1];
    // 兩條主邊距離應 ≥ 2 × min row height（row 0 + row 1 而非單 row）
    expect(bottom - top).toBeGreaterThan(50);
  });

  it('vMerge continuation cell 不畫邊框', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeRowsWithVMerge()]));

    // anchor 列 + 2 個獨立 cell × 2 行 = 5 個 cell；每個 cell × 4 邊框 = 20 條 drawLine
    // 若 continuation 也畫 → 24 條
    // 但 anchor 與相鄰 cell 邊框 dedupe 在 drawCellBorders 沒實作，這裡只比相對值
    // 主檢測：continuation cell 的 x 範圍內，row 1 的 y 範圍不應有額外的 top/bottom 線
    // 簡化檢測：drawLine 計數應 ≤ 20（5 個獨立 cell × 4 邊）
    const drawLines = ctx.filter('drawLine').length;
    expect(drawLines).toBeLessThanOrEqual(20);
  });

  it('rowSpan = 1 的 cell 維持單列高度（不被誤套合併邏輯）', () => {
    // 普通 2 列 × 1 cell，無 vMerge
    const para1: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text: 'r0', props: { fontSize: 12 } }],
    };
    const para2: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text: 'r1', props: { fontSize: 12 } }],
    };
    const cellR0 = cellNode([para1], SOLID_BLACK);
    const cellR1 = cellNode([para2], SOLID_BLACK);
    const sec = makeSection([tableNode([300], [rowNode([cellR0]), rowNode([cellR1])])]);

    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));

    // 兩列各畫 4 邊 = 8 條（無 dedupe）
    expect(ctx.filter('drawLine').length).toBe(8);
  });
});

describe('CanvasRenderer — Sprint 35 char-level CJK 直書渲染', () => {
  // Sprint 35：實作 char-level 垂直渲染（OOXML §17.18.93 V-suffix）。
  // 每字符正向 fillText（不 rotate），垂直堆疊；多 paragraph = 多列；
  // 列方向 tbRlV：右→左；tbLrV / lrTbV：左→右。

  function makeVerticalCellSection(
    tdVal: 'tbRlV' | 'lrTbV' | 'tbLrV' | undefined,
    paragraphs: string[] = ['工程名稱'],
    cellWidth = 100,
    rowHeight = 200,
    fontSize = 12,
  ): SectionNode {
    const paras: ParagraphNode[] = paragraphs.map((text) => ({
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text, props: { fontSize } }],
    }));
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: paras,
      props: { borders: SOLID_BLACK, ...(tdVal ? { textDirection: tdVal } : {}) },
    };
    const row: RowNode = {
      type: 'row',
      cells: [cell],
      props: { isHeader: false, cantSplit: false, height: rowHeight },
    };
    return makeSection([tableNode([cellWidth], [row])]);
  }

  it('tbRlV：每字符獨立 fillText（不呼叫 ctx.rotate）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeVerticalCellSection('tbRlV')]));

    // 不旋轉（V-suffix = glyph orientation preserved）
    expect(ctx.filter('rotate').length).toBe(0);

    // 「工程名稱」4 字 → 4 個 fillText
    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    expect(fillTexts.length).toBe(4);
    expect(fillTexts.map((op) => op.text)).toEqual(['工', '程', '名', '稱']);
  });

  it('tbRlV：字符 Y 座標單調遞增（由上往下垂直堆疊）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeVerticalCellSection('tbRlV')]));

    const fillTexts = ctx.filter('fillText') as Array<{ x: number; y: number }>;
    for (let i = 1; i < fillTexts.length; i++) {
      expect(fillTexts[i].y).toBeGreaterThan(fillTexts[i - 1].y);
    }
    // 同列的 X 不變
    for (let i = 1; i < fillTexts.length; i++) {
      expect(Math.abs(fillTexts[i].x - fillTexts[0].x)).toBeLessThan(0.001);
    }
  });

  it('多 paragraph tbRlV：每段 = 一列；列從右→左', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([
      makeVerticalCellSection('tbRlV', ['工程', '監造'], 80, 200, 12),
    ]));

    const fillTexts = ctx.filter('fillText') as Array<{ text: string; x: number }>;
    // 4 字（兩段各 2 字）
    expect(fillTexts.length).toBe(4);

    // 「工」「程」屬第 1 列（右側）；「監」「造」屬第 2 列（左側）
    const col1X = fillTexts.find((op) => op.text === '工')!.x;
    const col2X = fillTexts.find((op) => op.text === '監')!.x;
    expect(col1X).toBeGreaterThan(col2X); // 右列在更右
  });

  it('多 paragraph tbLrV / lrTbV：列從左→右', () => {
    for (const td of ['tbLrV', 'lrTbV'] as const) {
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layoutDocument([
        makeVerticalCellSection(td, ['工程', '監造'], 80, 200, 12),
      ]));

      const fillTexts = ctx.filter('fillText') as Array<{ text: string; x: number }>;
      const col1X = fillTexts.find((op) => op.text === '工')!.x;
      const col2X = fillTexts.find((op) => op.text === '監')!.x;
      expect(col1X).toBeLessThan(col2X); // 第 1 列在更左
    }
  });

  it('混入 Latin 字符：每個 codepoint 一格（Array.from grapheme split）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([
      makeVerticalCellSection('tbRlV', ['工A程']),
    ]));

    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    expect(fillTexts.length).toBe(3);
    expect(fillTexts.map((op) => op.text)).toEqual(['工', 'A', '程']);
  });

  it('空 cell：不送任何 fillText（不畫空字符）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([
      makeVerticalCellSection('tbRlV', ['']),
    ]));
    expect(ctx.filter('fillText').length).toBe(0);
  });

  it('水平 cell（無 textDirection）：字符 X 遞增、Y 相同（水平流，非垂直堆疊）', () => {
    // 注意：CJK 文字在 BoxBuilder 階段已拆字（避頭尾換行用），所以水平路徑也是逐字 fillText。
    // Sprint 35 vs Sprint 34 的差別不在「fillText count」而在「排列方向」：
    //   水平 → 字符 X 遞增、Y 相同（同一行）
    //   垂直 V-variant → 字符 Y 遞增、X 相同（同一列）
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([
      makeVerticalCellSection(undefined, ['工程名稱']),
    ]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string; x: number; y: number }>;
    expect(fillTexts.length).toBeGreaterThan(1);
    // X 遞增
    for (let i = 1; i < fillTexts.length; i++) {
      expect(fillTexts[i].x).toBeGreaterThanOrEqual(fillTexts[i - 1].x);
    }
    // Y 在同一行（相差 < fontSize × 0.5）
    const y0 = fillTexts[0].y;
    for (const op of fillTexts) {
      expect(Math.abs(op.y - y0)).toBeLessThan(6); // fontSize=12 × 0.5
    }
  });

  it('save / restore 數量永遠相等（Sprint 35 不引入未平衡的 canvas state）', () => {
    for (const variant of [undefined, 'tbRlV', 'lrTbV', 'tbLrV'] as const) {
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layoutDocument([makeVerticalCellSection(variant)]));
      expect(ctx.filter('save').length).toBe(ctx.filter('restore').length);
    }
  });

  it('cell 容量截斷：fontSize × charCount 超過 cell height 時剩餘字符不繪', () => {
    // cell rowHeight=40, padding 0/5/0/5, fontSize=12 → 可容納 ~3 字
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([
      makeVerticalCellSection('tbRlV', ['一二三四五六七'], 80, 40, 12),
    ]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    // 應該被截斷（< 7 字）
    expect(fillTexts.length).toBeLessThan(7);
    expect(fillTexts.length).toBeGreaterThan(0);
  });
});

describe('CanvasRenderer — Sprint 37 cell-internal floatImage（wp:anchor）渲染', () => {
  function makeCellWithFloat(opts: {
    floatRId?: string;
    posHOffset?: number;
    posVOffset?: number;
    floatW?: number;
    floatH?: number;
    behindDoc?: boolean;
  }): SectionNode {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'cell text', props: { fontSize: 12 } },
        {
          type: 'floatImage',
          rId: opts.floatRId ?? 'rId99',
          width: opts.floatW ?? 70,
          height: opts.floatH ?? 22,
          posH: { relativeFrom: 'column', posOffset: opts.posHOffset ?? 100 },
          posV: { relativeFrom: 'paragraph', posOffset: opts.posVOffset ?? 50 },
          wrapType: 'none',
          ...(opts.behindDoc ? { behindDoc: true } : {}),
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para],
      props: { borders: SOLID_BLACK },
    };
    const row: RowNode = {
      type: 'row',
      cells: [cell],
      props: { isHeader: false, cantSplit: false, height: 200 },
    };
    return makeSection([tableNode([300], [row])]);
  }

  it('cell 內 floatImage 被 drawImage（rId / 寬高正確）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithFloat({ floatRId: 'rIdAnchor', floatW: 80, floatH: 25 })]));

    const draws = ctx.filter('drawImage') as Array<{ href: string; width: number; height: number }>;
    const anchor = draws.find((op) => op.href === 'rIdAnchor');
    expect(anchor).toBeDefined();
    expect(anchor!.width).toBeCloseTo(80, 4);
    expect(anchor!.height).toBeCloseTo(25, 4);
  });

  it('cell 內 floatImage X 座標 = cell.x + padding.left + posH.posOffset', () => {
    // cell padding 預設 left = 5pt（OOXML 預設 100 twips）；cell 起始於 page margin.left = 72pt
    // 故 expected X ≈ 72 + 5 + 100 = 177pt
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithFloat({ floatRId: 'rIdX', posHOffset: 100 })]));
    const anchor = (ctx.filter('drawImage') as Array<{ href: string; x: number }>).find((op) => op.href === 'rIdX');
    expect(anchor).toBeDefined();
    expect(anchor!.x).toBeCloseTo(72 + 5 + 100, 4);
  });

  it('cell 內 floatImage 不出現在 lines / 不送出 fillText image:rId 字串', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithFloat({ floatRId: 'rIdNoInline' })]));

    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    for (const op of fillTexts) {
      // 不應出現 image:rIdNoInline 這種文字內容（這是 BoxBuilder 被誤觸發 inline path 的標記）
      expect(op.text).not.toContain('image:rIdNoInline');
    }
  });

  it('cell 含多個 floatImage：drawImage 數量 = float 個數 + inline image 個數', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 't', props: { fontSize: 12 } },
        { type: 'floatImage', rId: 'fA', width: 50, height: 50,
          posH: { relativeFrom: 'column', posOffset: 10 },
          posV: { relativeFrom: 'paragraph', posOffset: 10 }, wrapType: 'none' },
        { type: 'floatImage', rId: 'fB', width: 60, height: 60,
          posH: { relativeFrom: 'column', posOffset: 20 },
          posV: { relativeFrom: 'paragraph', posOffset: 20 }, wrapType: 'none' },
      ],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para],
      props: { borders: SOLID_BLACK },
    };
    const row: RowNode = {
      type: 'row',
      cells: [cell],
      props: { isHeader: false, cantSplit: false, height: 200 },
    };
    const section = makeSection([tableNode([300], [row])]);

    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([section]));
    const draws = ctx.filter('drawImage') as Array<{ href: string }>;
    const rIds = draws.map((op) => op.href);
    expect(rIds).toContain('fA');
    expect(rIds).toContain('fB');
  });

  it('behindDoc=true：float 在 cell 文字之前畫（drawImage 在 fillText 之前）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithFloat({ floatRId: 'rIdBehind', behindDoc: true })]));
    const indexOfDraw = ctx.ops.findIndex((o) => o.kind === 'drawImage' && (o as { href: string }).href === 'rIdBehind');
    const indexOfFirstText = ctx.ops.findIndex((o) => o.kind === 'fillText');
    expect(indexOfDraw).toBeGreaterThanOrEqual(0);
    expect(indexOfFirstText).toBeGreaterThanOrEqual(0);
    expect(indexOfDraw).toBeLessThan(indexOfFirstText);
  });

  it('behindDoc 預設 false：float 在 cell 文字之後畫（drawImage 在 fillText 之後）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithFloat({ floatRId: 'rIdFront' })]));
    const indexOfDraw = ctx.ops.findIndex((o) => o.kind === 'drawImage' && (o as { href: string }).href === 'rIdFront');
    const indexOfLastText = ctx.ops.map((o, i) => ({ o, i })).reverse().find(({ o }) => o.kind === 'fillText')?.i ?? -1;
    expect(indexOfDraw).toBeGreaterThan(indexOfLastText);
  });

  it('無 floatImage 的 cell：drawImage 次數 = 0（不誤畫）', () => {
    const ctx = new MockRenderContext();
    const cellPlain: CellNode = {
      type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [{ type: 'paragraph', props: {}, runs: [{ type: 'run', text: 'plain', props: { fontSize: 12 } }] }],
      props: { borders: SOLID_BLACK },
    };
    const row: RowNode = { type: 'row', cells: [cellPlain], props: { isHeader: false, cantSplit: false, height: 100 } };
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([tableNode([200], [row])])]));
    expect(ctx.filter('drawImage').length).toBe(0);
  });
});

describe('CanvasRenderer — Sprint 38 cell-internal floatTextBox（wp:anchor + wps:txbx）', () => {
  function makeCellWithTextBox(opts: {
    text?: string;
    posHOffset?: number;
    posVOffset?: number;
    boxW?: number;
    boxH?: number;
  }): SectionNode {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'cell text', props: { fontSize: 12 } },
        {
          type: 'floatTextBox',
          width: opts.boxW ?? 70,
          height: opts.boxH ?? 22,
          posH: { relativeFrom: 'column', posOffset: opts.posHOffset ?? 100 },
          posV: { relativeFrom: 'paragraph', posOffset: opts.posVOffset ?? 50 },
          wrapType: 'none',
          paragraphs: [{
            type: 'paragraph',
            props: {},
            runs: [{ type: 'run', text: opts.text ?? '112.12.29', props: { fontSize: 9 } }],
          }],
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para],
      props: { borders: SOLID_BLACK },
    };
    const row: RowNode = {
      type: 'row',
      cells: [cell],
      props: { isHeader: false, cantSplit: false, height: 200 },
    };
    return makeSection([tableNode([300], [row])]);
  }

  it('floatTextBox 走 fillText 而非 drawImage', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithTextBox({ text: '112.12.29' })]));
    // 不應有 drawImage（floatTextBox 沒 rId）
    expect(ctx.filter('drawImage').length).toBe(0);
    // 應有 fillText（cell text + textbox text 各 fillText 至少一個）
    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    expect(fillTexts.length).toBeGreaterThan(0);
  });

  it('floatTextBox 內文字「112.12.29」被 fillText 繪出', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithTextBox({ text: '112.12.29' })]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    // BoxBuilder 對 CJK / Latin 拆字，combined text 應含 "112.12.29"
    const combined = fillTexts.map((op) => op.text).join('');
    expect(combined).toContain('112.12.29');
  });

  it('floatTextBox 文字 X 起點在 textbox 內部（cellX + padding.left + posHOffset + bodyPr.lIns）', () => {
    // Sprint 39：textbox bodyPr 未設 → 套 OOXML 預設 lIns=7.2pt
    // cellX = 72, padding.left = 5, posHOffset = 80, default bodyPr.lIns = 7.2
    // expected first textbox char x ≈ 72 + 5 + 80 + 7.2 = 164.2
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithTextBox({ text: 'A', posHOffset: 80 })]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string; x: number }>;
    const textboxOp = fillTexts.find((op) => op.text === 'A');
    expect(textboxOp).toBeDefined();
    expect(textboxOp!.x).toBeCloseTo(72 + 5 + 80 + 7.2, 1);
  });

  it('floatTextBox 高度超出：截斷不繪所有 paragraph', () => {
    const ctx = new MockRenderContext();
    // boxH=24 扣掉預設 padTop/padB = 3.6+3.6 = 7.2pt 剩 16.8pt；9pt 字行高 ~10.8pt → 容納 1 行
    new CanvasRenderer(ctx).render(layoutDocument([
      makeCellWithTextBox({ text: '一二三四五六七八九十', boxW: 30, boxH: 24 }),
    ]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string }>;
    const txbxChars = fillTexts.filter((op) => '一二三四五六七八九十'.includes(op.text));
    expect(txbxChars.length).toBeLessThan(10);
  });

  it('多 floatTextBox + floatImage 混合：各自走對應 op', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'x', props: { fontSize: 12 } },
        {
          type: 'floatTextBox', width: 50, height: 30,
          posH: { relativeFrom: 'column', posOffset: 10 },
          posV: { relativeFrom: 'paragraph', posOffset: 10 },
          wrapType: 'none',
          paragraphs: [{ type: 'paragraph', props: {}, runs: [{ type: 'run', text: 'TB', props: { fontSize: 9 } }] }],
        },
        {
          type: 'floatImage', rId: 'imgA', width: 60, height: 30,
          posH: { relativeFrom: 'column', posOffset: 100 },
          posV: { relativeFrom: 'paragraph', posOffset: 10 },
          wrapType: 'none',
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para], props: { borders: SOLID_BLACK },
    };
    const row: RowNode = { type: 'row', cells: [cell], props: { isHeader: false, cantSplit: false, height: 200 } };
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([tableNode([300], [row])])]));

    // drawImage 數 = 1（floatImage imgA）
    expect((ctx.filter('drawImage') as Array<{ href: string }>).map((op) => op.href)).toContain('imgA');
    // fillText 含 'TB'（BoxBuilder Latin 不拆字、CJK 才拆字）
    const texts = (ctx.filter('fillText') as Array<{ text: string }>).map((op) => op.text);
    expect(texts.join('')).toContain('TB');
  });
});

describe('CanvasRenderer — Sprint 39 floatTextBox bodyPr / fill / border', () => {
  function makeTextBoxOnly(opts: {
    bodyPr?: import('../../../static/src/core/ooxml/ast/types').FloatTextBoxNode['bodyPr'];
    fill?: string;
    border?: import('../../../static/src/core/ooxml/ast/types').FloatTextBoxNode['border'];
    boxW?: number;
    boxH?: number;
    text?: string;
    color?: string;
  }): SectionNode {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'x', props: { fontSize: 12 } },
        {
          type: 'floatTextBox',
          width: opts.boxW ?? 80,
          height: opts.boxH ?? 30,
          posH: { relativeFrom: 'column', posOffset: 50 },
          posV: { relativeFrom: 'paragraph', posOffset: 30 },
          wrapType: 'none',
          paragraphs: [{
            type: 'paragraph', props: {},
            runs: [{ type: 'run', text: opts.text ?? 'A', props: { fontSize: 9, color: opts.color } }],
          }],
          ...(opts.bodyPr ? { bodyPr: opts.bodyPr } : {}),
          ...(opts.fill ? { fill: opts.fill } : {}),
          ...(opts.border ? { border: opts.border } : {}),
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para], props: { borders: SOLID_BLACK },
    };
    const row: RowNode = { type: 'row', cells: [cell], props: { isHeader: false, cantSplit: false, height: 200 } };
    return makeSection([tableNode([300], [row])]);
  }

  it('Custom bodyPr 套到文字 X 起點（lIns=10pt → cellX + padding.left + posHOffset + 10）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({
      bodyPr: { leftInset: 10, topInset: 5, rightInset: 10, bottomInset: 5 },
      text: 'A',
    })]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string; x: number }>;
    const textboxOp = fillTexts.find((op) => op.text === 'A');
    expect(textboxOp).toBeDefined();
    // cellX=72, padding.left=5, posHOffset=50, lIns=10 → 137
    expect(textboxOp!.x).toBeCloseTo(72 + 5 + 50 + 10, 1);
  });

  it('node.fill 有值：drawCellTextBoxFloat 開頭送 fillRect 帶該色', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({
      fill: 'FFFF00', boxW: 80, boxH: 30,
    })]));
    // 取 fillRect 中尺寸 = 80x30 的（textbox 背景），其他 fillRect 為 cell shading / page bg
    const fillRects = ctx.filter('fillRect') as Array<{ width: number; height: number; color: string }>;
    const textboxRect = fillRects.find((op) => Math.abs(op.width - 80) < 0.01 && Math.abs(op.height - 30) < 0.01);
    expect(textboxRect).toBeDefined();
    expect(textboxRect!.color).toBe('FFFF00');
  });

  it('node.fill 未設：不送 fillRect 80x30（不畫 textbox 背景）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({ boxW: 80, boxH: 30 })]));
    const fillRects = ctx.filter('fillRect') as Array<{ width: number; height: number }>;
    expect(fillRects.find((op) => Math.abs(op.width - 80) < 0.01 && Math.abs(op.height - 30) < 0.01)).toBeUndefined();
  });

  it('node.border 有值：drawCellTextBoxFloat 結尾送 4 條 drawLine（top/right/bottom/left）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({
      border: { width: 1, color: 'FF00FF' },
      boxW: 80, boxH: 30,
    })]));
    const lines = ctx.filter('drawLine') as Array<{ style: { color: string; width: number } }>;
    const textboxLines = lines.filter((op) => op.style.color === 'FF00FF');
    expect(textboxLines.length).toBe(4);
    for (const ln of textboxLines) {
      expect(ln.style.width).toBeCloseTo(1, 4);
    }
  });

  it('node.border 未設：不畫任何 FF00FF 線（與背景一致）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({ boxW: 80, boxH: 30 })]));
    const lines = ctx.filter('drawLine') as Array<{ style: { color: string } }>;
    expect(lines.filter((op) => op.style.color === 'FF00FF')).toHaveLength(0);
  });

  it('RunProps.color FF0000 propagate：textbox 內 fillText 帶紅色', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeTextBoxOnly({
      text: '1', color: 'FF0000',
    })]));
    const fillTexts = ctx.filter('fillText') as Array<{ text: string; style?: { color?: string } }>;
    const textboxOp = fillTexts.find((op) => op.text === '1');
    expect(textboxOp).toBeDefined();
    expect(textboxOp!.style?.color).toBe('FF0000');
  });
});

describe('CanvasRenderer — Sprint 42 cell.vAlign 三分支實作', () => {
  // 預設 row.props.height (atLeast) 設大值讓 cell rowHeight > contentHeight
  // 文字行高 ~ 14.4pt（12pt × 1.2 leading）；row.height=200 留 >150pt 空間給 vAlign 看出差異
  function makeCellWithVAlign(vAlign: 'top' | 'center' | 'bottom', rowHeight = 200): SectionNode {
    const cellProps: CellNode['props'] = { borders: SOLID_BLACK, vAlign };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para('CELL_TEXT', 12)],
      props: cellProps,
    };
    const row: RowNode = {
      type: 'row',
      cells: [cell],
      props: { isHeader: false, cantSplit: false, height: rowHeight, heightRule: 'atLeast' },
    };
    return makeSection([tableNode([200], [row])]);
  }

  it('vAlign=top（預設）：文字 fillText y 接近 cell 頂部（padding.top 之後）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeCellWithVAlign('top')]));
    const texts = ctx.filter('fillText') as Array<{ text: string; y: number }>;
    const t = texts.find((op) => op.text === 'CELL_TEXT');
    expect(t).toBeDefined();
    // page margin top = 72pt; cell 起點 y = 72; padding.top = 5pt（DEFAULT_CELL_PADDING_PT）
    // 12pt 行 baseline ≈ y + 5 + 14.4 * 0.85 = 89.24
    expect(t!.y).toBeLessThan(95);
  });

  it('vAlign=center：文字 fillText y 比 top 多 (200-14.4)/2 ≈ 92.8pt（rowHeight=200）', () => {
    const ctxTop = new MockRenderContext();
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxTop).render(layoutDocument([makeCellWithVAlign('top')]));
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeCellWithVAlign('center')]));
    const yTop = (ctxTop.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    const yCenter = (ctxCenter.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    // 中央偏移應接近 (200 - 5 - 5 - contentHeight) / 2 ≈ 92pt
    const offset = yCenter - yTop;
    expect(offset).toBeGreaterThan(80);
    expect(offset).toBeLessThan(100);
  });

  it('vAlign=bottom：文字 fillText y 比 top 多接近 rowHeight - contentHeight - padding 全部', () => {
    const ctxTop = new MockRenderContext();
    const ctxBottom = new MockRenderContext();
    new CanvasRenderer(ctxTop).render(layoutDocument([makeCellWithVAlign('top')]));
    new CanvasRenderer(ctxBottom).render(layoutDocument([makeCellWithVAlign('bottom')]));
    const yTop = (ctxTop.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    const yBottom = (ctxBottom.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    // 底部偏移 ≈ 200 - 5 (padding.bottom) - contentHeight ≈ ~180
    const offset = yBottom - yTop;
    expect(offset).toBeGreaterThan(170);
    expect(offset).toBeLessThan(195);
  });

  it('vAlign=center + contentHeight >= availableHeight：退化為 top（無負偏移）', () => {
    // 構造 row.heightRule='exact' + 極小 height < padding 總和，availableHeight 為負或 0
    // 確保 contentHeight >= availableHeight → 走 fallback path
    const makeTinyCell = (vAlign: 'top' | 'center'): SectionNode => {
      const cell: CellNode = {
        type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
        content: [para('CELL_TEXT', 12)],
        props: { borders: SOLID_BLACK, vAlign },
      };
      const row: RowNode = {
        type: 'row',
        cells: [cell],
        props: { isHeader: false, cantSplit: false, height: 8, heightRule: 'exact' },
      };
      return makeSection([tableNode([200], [row])]);
    };
    const ctxTop = new MockRenderContext();
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxTop).render(layoutDocument([makeTinyCell('top')]));
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeTinyCell('center')]));
    const yTop = (ctxTop.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    const yCenter = (ctxCenter.filter('fillText') as Array<{ text: string; y: number }>).find((op) => op.text === 'CELL_TEXT')!.y;
    expect(yCenter).toBeCloseTo(yTop, 1);
  });

  it('vAlign=center 對含 inline image 的 cell：image y 也下移', () => {
    const imgPara: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'inlineImage', rId: 'imgVA', width: 50, height: 30 }],
    };
    const makeImgCell = (vAlign: 'top' | 'center') => {
      const cell: CellNode = {
        type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
        content: [imgPara], props: { borders: SOLID_BLACK, vAlign },
      };
      const row: RowNode = { type: 'row', cells: [cell], props: { isHeader: false, cantSplit: false, height: 200, heightRule: 'atLeast' } };
      return makeSection([tableNode([200], [row])]);
    };
    const ctxTop = new MockRenderContext();
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxTop).render(layoutDocument([makeImgCell('top')]));
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeImgCell('center')]));
    const yImgTop = (ctxTop.filter('drawImage') as Array<{ href: string; y: number }>).find((op) => op.href === 'imgVA')!.y;
    const yImgCenter = (ctxCenter.filter('drawImage') as Array<{ href: string; y: number }>).find((op) => op.href === 'imgVA')!.y;
    expect(yImgCenter - yImgTop).toBeGreaterThan(60); // 200pt row 內 30pt image center 偏移 ≈ 80pt
    expect(yImgCenter - yImgTop).toBeLessThan(100);
  });

  it('vAlign 不影響 cell 邊框與背景座標', () => {
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeCellWithVAlign('center')]));
    // cell 邊框（drawLine 4 條 SOLID_BLACK）位置應仍以 cell 全範圍為準（不被 vAlign 影響）
    const lines = ctxCenter.filter('drawLine') as Array<{ x1: number; y1: number; x2: number; y2: number; style: { color: string } }>;
    const topLine = lines.find((op) => op.style.color === '000000' && op.y1 === op.y2 && op.x1 === 72);
    expect(topLine).toBeDefined();
    expect(topLine!.y1).toBe(72); // cell 頂部 = page margin top
  });
});

describe('CanvasRenderer — Sprint 40 image srcRect propagation', () => {
  function makeSectionWithInlineImage(srcRect?: import('../../../static/src/core/ooxml/ast/types').ImageSrcRect): SectionNode {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [{
        type: 'inlineImage',
        rId: 'img1',
        width: 100,
        height: 60,
        ...(srcRect ? { srcRect } : {}),
      }],
    };
    return makeSection([para]);
  }

  it('inline image 無 srcRect：drawImage op 無 srcRect 欄位', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSectionWithInlineImage()]));
    const imgs = ctx.filter('drawImage');
    expect(imgs.length).toBe(1);
    expect(imgs[0].srcRect).toBeUndefined();
  });

  it('inline image 帶 srcRect={t:0.04, b:0.04}：drawImage op 攜帶 srcRect', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSectionWithInlineImage({
      leftPct: 0, topPct: 0.04066, rightPct: 0, bottomPct: 0.04066,
    })]));
    const imgs = ctx.filter('drawImage');
    expect(imgs.length).toBe(1);
    expect(imgs[0].srcRect).toBeDefined();
    expect(imgs[0].srcRect!.topPct).toBeCloseTo(0.04066, 5);
    expect(imgs[0].srcRect!.bottomPct).toBeCloseTo(0.04066, 5);
  });

  it('cell-internal floatImage 帶 srcRect：drawImage op 攜帶 srcRect', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'x', props: { fontSize: 12 } },
        {
          type: 'floatImage',
          rId: 'imgFloat',
          width: 80, height: 60,
          posH: { relativeFrom: 'column', posOffset: 10 },
          posV: { relativeFrom: 'paragraph', posOffset: 10 },
          wrapType: 'none',
          srcRect: { leftPct: 0.05, topPct: 0.1, rightPct: 0.05, bottomPct: 0.1 },
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell', gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para], props: { borders: SOLID_BLACK },
    };
    const row: RowNode = { type: 'row', cells: [cell], props: { isHeader: false, cantSplit: false, height: 200 } };
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([tableNode([300], [row])])]));
    const imgs = ctx.filter('drawImage') as Array<{ href: string; srcRect?: { leftPct: number } }>;
    const floatImg = imgs.find((op) => op.href === 'imgFloat');
    expect(floatImg).toBeDefined();
    expect(floatImg!.srcRect).toBeDefined();
    expect(floatImg!.srcRect!.leftPct).toBeCloseTo(0.05, 4);
  });
});

describe('CanvasRenderer — Sprint 167 textAlignment 行內垂直對齊', () => {
  // 同一段落兩 run、字型大小不同 → 同行兩個不同高度 box
  function mixedHeightPara(textAlignment?: ParagraphNode['props']['textAlignment']): ParagraphNode {
    const tall: RunNode = { type: 'run', text: 'A', props: { fontSize: 32 } };
    const short: RunNode = { type: 'run', text: 'b', props: { fontSize: 8 } };
    return { type: 'paragraph', props: textAlignment ? { textAlignment } : {}, runs: [tall, short] };
  }

  it('未設 textAlignment → 兩 box 共用同一 baseline y（既有行為）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([mixedHeightPara()])]));
    const texts = ctx.filter('fillText');
    expect(texts.length).toBe(2);
    expect(texts[0].y).toBe(texts[1].y);
  });

  it("textAlignment='baseline' → 與未設一致（baseline 即預設、byte-identical）", () => {
    const ctxDefault = new MockRenderContext();
    new CanvasRenderer(ctxDefault).render(layoutDocument([makeSection([mixedHeightPara()])]));
    const ctxBaseline = new MockRenderContext();
    new CanvasRenderer(ctxBaseline).render(layoutDocument([makeSection([mixedHeightPara('baseline')])]));
    const a = ctxDefault.filter('fillText');
    const b = ctxBaseline.filter('fillText');
    expect(b.map((t) => t.y)).toEqual(a.map((t) => t.y));
  });

  it("textAlignment='center' → 較矮 box 上移、較高 box 不動", () => {
    const ctxDefault = new MockRenderContext();
    new CanvasRenderer(ctxDefault).render(layoutDocument([makeSection([mixedHeightPara()])]));
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeSection([mixedHeightPara('center')])]));
    const def = ctxDefault.filter('fillText');
    const cen = ctxCenter.filter('fillText');
    // 較高 box（'A' fontSize 32）位移為 0
    const tallDef = def.find((t) => t.text === 'A')!;
    const tallCen = cen.find((t) => t.text === 'A')!;
    expect(tallCen.y).toBe(tallDef.y);
    // 較矮 box（'b' fontSize 8）往上（y 變小）
    const shortDef = def.find((t) => t.text === 'b')!;
    const shortCen = cen.find((t) => t.text === 'b')!;
    expect(shortCen.y).toBeLessThan(shortDef.y);
  });

  it("textAlignment top/center/bottom：較矮 box y 依序遞增", () => {
    const ys: Record<string, number> = {};
    for (const mode of ['top', 'center', 'bottom'] as const) {
      const ctx = new MockRenderContext();
      new CanvasRenderer(ctx).render(layoutDocument([makeSection([mixedHeightPara(mode)])]));
      const short = ctx.filter('fillText').find((t) => t.text === 'b')!;
      ys[mode] = short.y;
    }
    const ctxDef = new MockRenderContext();
    new CanvasRenderer(ctxDef).render(layoutDocument([makeSection([mixedHeightPara()])]));
    const base = ctxDef.filter('fillText').find((t) => t.text === 'b')!.y;
    // top 往上最多、bottom 往下、center 居中
    expect(ys.top).toBeLessThan(ys.center);
    expect(ys.center).toBeLessThan(base);
    expect(ys.bottom).toBeGreaterThan(base);
  });

  it('等高行（單一字型大小）標 center 仍 byte-identical', () => {
    const uniform = (ta?: ParagraphNode['props']['textAlignment']): ParagraphNode => ({
      type: 'paragraph',
      props: ta ? { textAlignment: ta } : {},
      runs: [
        { type: 'run', text: 'foo ', props: { fontSize: 12 } },
        { type: 'run', text: 'bar', props: { fontSize: 12 } },
      ],
    });
    const ctxDefault = new MockRenderContext();
    new CanvasRenderer(ctxDefault).render(layoutDocument([makeSection([uniform()])]));
    const ctxCenter = new MockRenderContext();
    new CanvasRenderer(ctxCenter).render(layoutDocument([makeSection([uniform('center')])]));
    const a = ctxDefault.filter('fillText');
    const c = ctxCenter.filter('fillText');
    expect(c.map((t) => t.y)).toEqual(a.map((t) => t.y));
  });
});

describe('CanvasRenderer — Sprint 173 浮水印 render', () => {
  it('未傳 watermark → 無 save/translate/rotate（byte-identical）', () => {
    const sec = makeSection([para('內文')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([sec]));
    expect(ctx.filter('save').length).toBe(0);
    expect(ctx.filter('translate').length).toBe(0);
    expect(ctx.filter('rotate').length).toBe(0);
  });

  it("文字浮水印 → save + translate + rotate + fillText(浮水印文字) + restore", () => {
    const sec = makeSection([para('內文')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, {
      watermark: { kind: 'text', text: 'DRAFT', rotation: 315 },
    }).render(layoutDocument([sec]));
    expect(ctx.filter('save').length).toBe(1);
    expect(ctx.filter('restore').length).toBe(1);
    expect(ctx.filter('translate').length).toBe(1);
    expect(ctx.filter('rotate').length).toBe(1);
    const wmText = ctx.filter('fillText').find((t) => t.text === 'DRAFT');
    expect(wmText).toBeDefined();
  });

  it('浮水印繪於內文之前（behind content）', () => {
    const sec = makeSection([para('body')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, {
      watermark: { kind: 'text', text: 'DRAFT' },
    }).render(layoutDocument([sec]));
    const fillTexts = ctx.filter('fillText');
    // 第一個 fillText = 浮水印（繪於內文之前）
    expect(fillTexts.length).toBeGreaterThanOrEqual(2);
    expect(fillTexts[0].text).toBe('DRAFT');
  });

  it('rotation 未設 → 不送 rotate op', () => {
    const sec = makeSection([para('內文')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, {
      watermark: { kind: 'text', text: '機密' },
    }).render(layoutDocument([sec]));
    expect(ctx.filter('rotate').length).toBe(0);
    expect(ctx.filter('fillText').some((t) => t.text === '機密')).toBe(true);
  });

  it('圖片浮水印（kind=image）→ Sprint 173 不繪（no-op）', () => {
    const sec = makeSection([para('內文')]);
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, {
      watermark: { kind: 'image', imageRId: 'rId7' },
    }).render(layoutDocument([sec]));
    expect(ctx.filter('save').length).toBe(0);
    expect(ctx.filter('translate').length).toBe(0);
  });
});

describe('CanvasRenderer — Sprint 175 追蹤修訂 render', () => {
  function revisionPara(text: string, revType: 'ins' | 'del'): ParagraphNode {
    const run: RunNode = {
      type: 'run', text, props: { fontSize: 12 }, revision: { type: revType },
    };
    return { type: 'paragraph', props: {}, runs: [run] };
  }

  it('一般 run（無 revision）→ 無裝飾 drawLine', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([para('plain')])]));
    expect(ctx.filter('drawLine').length).toBe(0);
  });

  it('<w:ins> run → 畫底線（drawLine、水平）', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([revisionPara('added', 'ins')])]));
    const lines = ctx.filter('drawLine');
    expect(lines.length).toBeGreaterThanOrEqual(1);
    expect(lines[0].y1).toBe(lines[0].y2); // 水平線
  });

  it('<w:del> run → 畫刪除線、且刪除文字仍繪出', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx).render(layoutDocument([makeSection([revisionPara('removed', 'del')])]));
    expect(ctx.filter('drawLine').length).toBeGreaterThanOrEqual(1);
    // 刪除文字仍 fillText（markup view：刪除文字加刪除線、不隱藏）
    expect(ctx.filter('fillText').some((t) => t.text === 'removed')).toBe(true);
  });

  it('ins 底線在基線下方、del 刪除線在基線上方', () => {
    const ctxIns = new MockRenderContext();
    new CanvasRenderer(ctxIns).render(layoutDocument([makeSection([revisionPara('x', 'ins')])]));
    const ctxDel = new MockRenderContext();
    new CanvasRenderer(ctxDel).render(layoutDocument([makeSection([revisionPara('x', 'del')])]));
    const insY = ctxIns.filter('drawLine')[0].y1;
    const delY = ctxDel.filter('drawLine')[0].y1;
    // 底線 y 較大（畫面下方）、刪除線 y 較小（畫面上方）
    expect(insY).toBeGreaterThan(delY);
  });

  it('drawTextDecorations=false → 不畫追蹤修訂裝飾', () => {
    const ctx = new MockRenderContext();
    new CanvasRenderer(ctx, { drawTextDecorations: false })
      .render(layoutDocument([makeSection([revisionPara('added', 'ins')])]));
    expect(ctx.filter('drawLine').length).toBe(0);
  });
});

describe('CanvasRenderer — MockRenderContext counts/reset', () => {
  it('counts() 回傳每類 op 計數', () => {
    const ctx = new MockRenderContext();
    ctx.beginPage(1, 100, 100);
    ctx.fillRect(0, 0, 100, 100, 'FFFFFF');
    ctx.fillText('a', 10, 20, { fontSize: 12 });
    ctx.fillText('b', 30, 20, { fontSize: 12 });
    ctx.endPage();
    const c = ctx.counts();
    expect(c.beginPage).toBe(1);
    expect(c.endPage).toBe(1);
    expect(c.fillRect).toBe(1);
    expect(c.fillText).toBe(2);
    expect(c.drawLine).toBe(0);
  });

  it('reset() 清空 ops', () => {
    const ctx = new MockRenderContext();
    ctx.beginPage(1, 100, 100);
    expect(ctx.ops.length).toBe(1);
    ctx.reset();
    expect(ctx.ops.length).toBe(0);
  });
});
