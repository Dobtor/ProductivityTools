/**
 * TableLayout — cell-level 表格排版單元測試（Sprint 3）
 */

import { describe, expect, it } from 'vitest';
import {
  allocateColumnWidths,
  layoutCell,
  layoutRow,
  layoutTable,
  splitRowAtPageBreak,
} from '../../../static/src/core/layout/TableLayout';
import type {
  TableNode,
  RowNode,
  CellNode,
  ParagraphNode,
} from '../../../static/src/core/ooxml/ast/types';

function paraNode(text: string, fontSize = 12): ParagraphNode {
  return {
    type: 'paragraph',
    props: {},
    runs: [{ type: 'run', text, props: { fontSize } }],
  };
}

function cellNode(
  text: string,
  opts: Partial<CellNode> = {},
): CellNode {
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content: [paraNode(text)],
    props: {},
    ...opts,
  };
}

function rowNode(
  cells: CellNode[],
  opts: Partial<RowNode['props']> = {},
): RowNode {
  return {
    type: 'row',
    cells,
    props: { isHeader: false, cantSplit: false, ...opts },
  };
}

function tableNode(grid: number[], rows: RowNode[]): TableNode {
  return {
    type: 'table',
    grid,
    rows,
    props: {},
  };
}

describe('allocateColumnWidths', () => {
  it('grid 直接 copy', () => {
    const t = tableNode([100, 200, 300], []);
    expect(allocateColumnWidths(t, 1000)).toEqual([100, 200, 300]);
  });

  it('grid 全 0 時平均分配 contentWidth', () => {
    const t = tableNode([0, 0, 0, 0], []);
    expect(allocateColumnWidths(t, 400)).toEqual([100, 100, 100, 100]);
  });

  it('空 grid 回空陣列', () => {
    const t = tableNode([], []);
    expect(allocateColumnWidths(t, 500)).toEqual([]);
  });
});

describe('layoutCell', () => {
  it('基本 cell：寬度 = 給定 cellWidth，高度 > 0', () => {
    const cell = cellNode('hello', { gridSpan: 1 });
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.width).toBe(100);
    expect(out.height).toBeGreaterThan(0);
    expect(out.lines.length).toBeGreaterThanOrEqual(1);
  });

  it('isContinuation cell：高度 0、無 lines', () => {
    const cell = cellNode('x', { isContinuation: true });
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.height).toBe(0);
    expect(out.lines.length).toBe(0);
    expect(out.isContinuation).toBe(true);
  });

  it('長文本會在 cell 內斷行（多 line）', () => {
    const cell = cellNode('一二三四五六七八九十一二三四五六', { gridSpan: 1 });
    // cellWidth = 60pt，padding 各 5pt，innerWidth = 50pt → 4 字一行
    const out = layoutCell(cell, 60, 0, tableNode([60], []));
    expect(out.lines.length).toBeGreaterThan(1);
  });

  it('vAlign 從 cell.props 帶通', () => {
    const cell = cellNode('x', { props: { vAlign: 'center' } });
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.vAlign).toBe('center');
  });

  it('cell padding 預設 OOXML 規格 left/right=5pt、top/bottom=0pt', () => {
    const cell = cellNode('x');
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.padding.left).toBe(5);
    expect(out.padding.right).toBe(5);
    expect(out.padding.top).toBe(0);
  });
});

describe('layoutRow', () => {
  it('row 高度 = max(cell heights)', () => {
    const cells: CellNode[] = [
      cellNode('a', { gridCol: 0 }),
      cellNode('一二三四五六七八九十', { gridCol: 1 }),
    ];
    const row = rowNode(cells);
    const out = layoutRow(row, 0, tableNode([60, 60], [row]), [60, 60]);
    expect(out.cells.length).toBe(2);
    // 第二格因內容多應比第一格高
    expect(out.height).toBeGreaterThanOrEqual(out.cells[0].height);
    expect(out.height).toBeGreaterThanOrEqual(out.cells[1].height);
  });

  it('isHeader 與 cantSplit 透傳到 RowLayout', () => {
    const row = rowNode([cellNode('h')], { isHeader: true, cantSplit: true });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.isHeader).toBe(true);
    expect(out.cantSplit).toBe(true);
  });

  it('rowSpan > 1 cell 不支配本列高度（由 anchor row 決定）', () => {
    const cell = cellNode('long content text here', { rowSpan: 3 });
    const row = rowNode([cell]);
    const out = layoutRow(row, 0, tableNode([200], [row]), [200]);
    // rowSpan=3 cell 不算 height，row 退回 fallback (14pt)
    expect(out.height).toBe(14);
  });

  it('heightRule="atLeast" + height：最終 height >= 規定值', () => {
    const row = rowNode([cellNode('x')], { height: 50, heightRule: 'atLeast' });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBeGreaterThanOrEqual(50);
  });

  it('heightRule="exact" + height：直接用規定值', () => {
    const row = rowNode([cellNode('x')], { height: 50, heightRule: 'exact' });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBe(50);
  });

  // Sprint 26：OOXML `<w:trHeight w:val="X"/>` 不帶 hRule 時預設 auto
  // 規格說「auto = content 決定」，但 Word 對 sparse form row 仍以 val 為下限
  // 啟發式：val > natural × 3 才視為 sparse form row
  it('heightRule="auto" + val 顯著大於 natural（ratio>3）：把 val 當下限', () => {
    // 'x' 自然 ~14.4pt，val 60pt，ratio 60/14.4 = 4.17 > 3 → 套 val-as-min
    const row = rowNode([cellNode('x')], { height: 60, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBe(60);
  });

  // Sprint 45：取代 Sprint 26 的 ratio>3 magic number——無 image 的 sparse 表單列
  // 只要 val > natural 即套 val-as-min（ratio<3 也套）。
  // 原 Sprint 26 此處斷言「ratio 1.74 → 取自然」，已被 golden 04 環清表 row 2/3
  // （ratio ~1.67、golden 落在 val）證偽；保護 autosave-cache 的責任移交給「含 image」分支。
  it('Sprint 45：無 image row + val 略大於 natural（ratio<3）→ 套 val-as-min', () => {
    // 'x' 自然 ~14.4pt，val 25pt，ratio 1.74；無 image → 套 val
    const row = rowNode([cellNode('x')], { height: 25, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBe(25);
  });

  it('heightRule="auto" + content > val：取自然高度（不被 val 壓低）', () => {
    const longContent = '這是一段非常長的中文文字會被斷成多行內容包含許多漢字字符以致超過行寬必須換行多次來模擬高 cell';
    const row = rowNode(
      [cellNode(longContent)],
      { height: 30, heightRule: 'auto' },
    );
    const out = layoutRow(row, 0, tableNode([60], [row]), [60]);
    // 多行 cell 內容自然高度應 > 30pt → ratio < 3 條件不成立、val 不套
    expect(out.height).toBeGreaterThan(30);
  });

  it('heightRule undefined + val ratio>3：與 auto+ratio>3 同行為（套 val-as-min）', () => {
    // 模擬 docx `<w:trHeight w:val="X"/>`（無 w:hRule）；TableParser 會解析成 heightRule='auto'
    const row = rowNode([cellNode('y')], { height: 60 });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBe(60);
  });

  it('Sprint 26 reproduce：自主檢查表 sparse row（val=57.2pt / natural=14.4pt）→ inflate to 57.2pt', () => {
    // 復現 05_header_footer/自主檢查表---人手孔調升降.docx row 7 等：val 1144 twips=57.2pt，cell 單段落
    const row = rowNode([cellNode('施工前', 12)], { height: 57.2, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.height).toBe(57.2);
  });

  // ── Sprint 47：val-as-min 比較基準改用 naturalUnsnapped（prep tests，第七層紀律）──
  // Sprint 46 診斷：exact 行被 docGrid snap 上推（20pt → 36pt），使 snapped natural
  // 撐過 trHeight val、卡住 `val > natural` 判斷。修法 = 比較基準改用未 snap 的內容高。
  function exactLineCell(lineValuePt: number, paraCount: number): CellNode {
    return {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: Array.from({ length: paraCount }, () => ({
        type: 'paragraph' as const,
        props: { spacing: { line: { rule: 'exact' as const, value: lineValuePt } } },
        runs: [{ type: 'run' as const, text: '監造單位', props: { fontSize: 12 } }],
      })),
      props: {},
    };
  }

  it('Sprint 47：exact 行被 snap 撐高，val-as-min 仍以未 snap 高判斷 → 套 val', () => {
    // 復現監造會議記錄 row4：2 段 line=400 twip exact = 2×20pt = 40pt（未 snap），
    // docGridLinePitch=18 → snap 成 2×36 = 72pt；trHeight val 44.9pt。
    // 修法前：val(44.9) > snapped(72) = false → 不套 → row 72pt（過高）。
    // 修法後：val(44.9) > unsnapped(40) = true → 套 val → row 44.9pt。
    const row = rowNode([exactLineCell(20, 2)], { height: 44.9, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120], { docGridLinePitch: 18 });
    expect(out.height).toBeCloseTo(44.9, 1);
    // 且 cell 內容已重排為未 snap 版（contentHeight ≈ 40pt 而非 72pt）
    expect(out.cells[0].contentHeight).toBeLessThan(50);
  });

  it('Sprint 47：val < 未 snap 高 → 不套 val（維持 snapped natural，不誤傷環清表 row 0 型）', () => {
    // 復現環清表 row 0：trHeight val 17pt，2 段 exact-16pt 行（未 snap 32pt / snap 36pt）。
    // val(17) < unsnapped(32) → 不套 val → row 維持 snapped natural（不被 Sprint 47 重排）。
    const row = rowNode([exactLineCell(16, 2)], { height: 17, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120], { docGridLinePitch: 18 });
    // 不套 val → row = snapped natural（2×18 + padding）> 17
    expect(out.height).toBeGreaterThan(17);
    // 內容維持 snapped（未被重排）
    expect(out.cells[0].contentHeight).toBeGreaterThan(34);
  });

  // ── Sprint 48：含 image row 的 val-as-min（移除 Sprint 45 的 image 區分）──────
  // Pillow 實測 golden 03 全套管 photo 列同樣 honors trHeight val；Sprint 26 的
  // autosave-cache 顧慮已由 Sprint 47 naturalUnsnapped 基準化解（val 真的 > 內容才套）。
  it('Sprint 48：含 image row + val > naturalUnsnapped → 套 val（與無 image 同規則）', () => {
    // 復現 03 全套管 row：image 60pt + trHeight val 90pt → val > natural → 套 val。
    // Sprint 45 此處原斷言「不套」（保留 ratio>3），Sprint 48 改為套用。
    const imgCell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [
        {
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'imgX', width: 80, height: 60 }],
        },
      ],
      props: {},
    };
    const row = rowNode([imgCell], { height: 90, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120]);
    expect(out.height).toBeCloseTo(90, 1);
    expect(out.containsImage).toBe(true);
  });

  it('Sprint 48：含 image row + val 顯著大於 natural → 套 val-as-min', () => {
    const imgCell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [
        {
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'imgX', width: 20, height: 15 }],
        },
      ],
      props: {},
    };
    const row = rowNode([imgCell], { height: 200, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120]);
    expect(out.height).toBe(200);
  });

  it('Sprint 48：含 image row + val ≤ naturalUnsnapped（autosave 快取型）→ 不套 val', () => {
    // autosave-cache val ≈ natural：val 不嚴格大於內容 → 不觸發 val-as-min（取自然高度）。
    // 這是 Sprint 26 autosave-cache 顧慮的正解——不靠 image 區分，靠 naturalUnsnapped 基準。
    const imgCell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [
        {
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'imgX', width: 80, height: 100 }],
        },
      ],
      props: {},
    };
    // image 100pt，val 95pt < natural → 不套，取自然高度
    const row = rowNode([imgCell], { height: 95, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120]);
    expect(out.height).toBeGreaterThan(95);
  });

  // Sprint 27：cell-level keepNext → row 視為 cantSplit（R6 近似）
  it('Sprint 27：cell 內段落 keepNext=true → row.cantSplit 自動為 true', () => {
    const paraKeepNext: ParagraphNode = {
      type: 'paragraph',
      props: { keepNext: true },
      runs: [{ type: 'run', text: '保留', props: { fontSize: 12 } }],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraKeepNext],
      props: {},
    };
    const row = rowNode([cell], { cantSplit: false });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.cantSplit).toBe(true);
  });

  it('Sprint 27：cell 內段落都沒 keepNext → row.cantSplit 維持原值（false）', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text: '一般', props: { fontSize: 12 } }],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para],
      props: {},
    };
    const row = rowNode([cell], { cantSplit: false });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.cantSplit).toBe(false);
  });

  it('Sprint 27：cell 已是 cantSplit=true，不被 keepNext heuristic 影響（仍為 true）', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: { keepNext: true },
      runs: [{ type: 'run', text: 'kn', props: { fontSize: 12 } }],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [para],
      props: {},
    };
    const row = rowNode([cell], { cantSplit: true });
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.cantSplit).toBe(true);
  });

  it('Sprint 27：多 cell 中只要 1 cell 有 keepNext 段落 → row 即 cantSplit', () => {
    const ordinary: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [{ type: 'paragraph', props: {}, runs: [{ type: 'run', text: 'a', props: { fontSize: 12 } }] }],
      props: {},
    };
    const keepNextCell: CellNode = {
      type: 'cell',
      gridCol: 1,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [{ type: 'paragraph', props: { keepNext: true }, runs: [{ type: 'run', text: 'b', props: { fontSize: 12 } }] }],
      props: {},
    };
    const row = rowNode([ordinary, keepNextCell], { cantSplit: false });
    const out = layoutRow(row, 0, tableNode([100, 100], [row]), [100, 100]);
    expect(out.cantSplit).toBe(true);
  });

  it('Sprint 48：含 image 的全套管 row（val > natural）→ honors trHeight val', () => {
    // 模擬 1121229-全套管 row 結構：cell 含 inline image（混凝土施工抽查照片）+ 文字段落。
    // Pillow 實測 golden 全套管 photo 列 honors trHeight val（row trHeight 266.8/278.45pt），
    // render 用 natural ~226.8pt → 列偏矮 40pt。Sprint 48 移除 image 區分後，val > natural
    // 即套 val-as-min（與無 image 同規則）。原 Sprint 26/45「不 inflate」斷言已被 golden 證偽。
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [
        {
          type: 'paragraph',
          props: {},
          runs: [{ type: 'inlineImage', rId: 'imgX', width: 90, height: 70 }],
        },
        paraNode('段落內容', 12),
      ],
      props: {},
    };
    // natural ~70pt（image）+ ~14.4pt 文字 ≈ 84pt，val 100pt > natural → 套 val-as-min
    const row = rowNode([cell], { height: 100, heightRule: 'auto' });
    const out = layoutRow(row, 0, tableNode([120], [row]), [120]);
    expect(out.height).toBeCloseTo(100, 1);
  });
});

describe('layoutTable', () => {
  it('整張表 layout：rows 數正確、columnWidths 正確', () => {
    const t = tableNode(
      [50, 50, 50],
      [
        rowNode([
          cellNode('a', { gridCol: 0 }),
          cellNode('b', { gridCol: 1 }),
          cellNode('c', { gridCol: 2 }),
        ]),
        rowNode([
          cellNode('d', { gridCol: 0 }),
          cellNode('e', { gridCol: 1 }),
          cellNode('f', { gridCol: 2 }),
        ]),
      ],
    );
    const out = layoutTable(t, 150);
    expect(out.columnWidths).toEqual([50, 50, 50]);
    expect(out.rows.length).toBe(2);
    expect(out.rows[0].rowIndex).toBe(0);
    expect(out.rows[1].rowIndex).toBe(1);
  });

  it('gridSpan：cell 寬度 = 對應 grid 範圍寬度總和', () => {
    const t = tableNode(
      [50, 50, 50],
      [rowNode([cellNode('wide', { gridCol: 0, gridSpan: 2 })])],
    );
    const out = layoutTable(t, 150);
    expect(out.rows[0].cells[0].width).toBe(100);
  });
});

// ── Sprint 17：containsImage 旗標 ────────────────────────────────────────────

describe('Sprint 17 — RowLayout.containsImage', () => {
  function paraWithImage(rId: string, w = 100, h = 100): ParagraphNode {
    return {
      type: 'paragraph',
      props: {},
      runs: [{ type: 'inlineImage', rId, width: w, height: h }],
    };
  }
  function imageCell(rId: string, w = 100, h = 100): CellNode {
    return {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraWithImage(rId, w, h)],
      props: {},
    };
  }

  it('純文字 row：containsImage = false', () => {
    const row = rowNode([cellNode('hello'), cellNode('world')]);
    const out = layoutRow(row, 0, tableNode([100, 100], [row]), [100, 100]);
    expect(out.containsImage).toBe(false);
  });

  it('含 inline image 的 row：containsImage = true', () => {
    const row = rowNode([cellNode('text'), imageCell('rId7', 80, 60)]);
    const out = layoutRow(row, 0, tableNode([100, 100], [row]), [100, 100]);
    expect(out.containsImage).toBe(true);
  });

  it('巢狀表格內含 image：外層 row containsImage 仍為 true', () => {
    const innerTable: TableNode = {
      type: 'table',
      grid: [50],
      rows: [rowNode([imageCell('rIdInner', 40, 40)])],
      props: {},
    };
    const outerCell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [innerTable],
      props: {},
    };
    const row = rowNode([outerCell]);
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.containsImage).toBe(true);
  });

  it('isContinuation cell（vMerge）：自身不貢獻 image 旗標', () => {
    const contCell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: true,
      content: [],
      props: {},
    };
    const row = rowNode([contCell]);
    const out = layoutRow(row, 0, tableNode([100], [row]), [100]);
    expect(out.containsImage).toBe(false);
  });

  it('layoutTable：所有 row 都有 containsImage 欄位', () => {
    const t = tableNode(
      [100, 100],
      [
        rowNode([cellNode('header A'), cellNode('header B')]),
        rowNode([cellNode('data'), imageCell('rId1', 60, 60)]),
      ],
    );
    const out = layoutTable(t, 200);
    expect(out.rows[0].containsImage).toBe(false);
    expect(out.rows[1].containsImage).toBe(true);
  });
});

// ── Sprint 18：splitRowAtPageBreak（cell-internal page break）────────────────

describe('Sprint 18 — splitRowAtPageBreak', () => {
  function paraWithBreak(textBefore: string, textAfter: string): ParagraphNode {
    // 段落內含 page break：<run text> + <break page> + <run text>
    return {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: textBefore, props: { fontSize: 12 } },
        { type: 'break', breakType: 'page' },
        { type: 'run', text: textAfter, props: { fontSize: 12 } },
      ],
    };
  }
  function cellWithBreak(textBefore: string, textAfter: string): CellNode {
    return {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraWithBreak(textBefore, textAfter)],
      props: {},
    };
  }

  it('row 內無 page break：回 null', () => {
    const row = rowNode([cellNode('plain text')]);
    const layout = layoutRow(row, 0, tableNode([200], [row]), [200]);
    expect(splitRowAtPageBreak(layout)).toBeNull();
  });

  it('row 內單一 cell 含 page break：切成 first / second', () => {
    const row = rowNode([cellWithBreak('before', 'after')]);
    const layout = layoutRow(row, 0, tableNode([200], [row]), [200]);
    const split = splitRowAtPageBreak(layout);
    expect(split).not.toBeNull();
    if (!split) return;
    // first 半含 break 之前的 line（含 emptyLine_pageBreak）
    // second 半含 break 之後的 content line
    expect(split.first.cells.length).toBe(1);
    expect(split.second.cells.length).toBe(1);
    // second isHeader 必為 false（避免無限重複）
    expect(split.second.isHeader).toBe(false);
  });

  it('row 多 cell：含 break 的 cell 被切，無 break 的 cell first 完整 / second 空', () => {
    const row: RowNode = {
      type: 'row',
      cells: [
        cellNode('plain'),
        cellWithBreak('left', 'right'),
      ],
      props: { isHeader: false, cantSplit: false },
    };
    const layout = layoutRow(row, 0, tableNode([100, 100], [row]), [100, 100]);
    const split = splitRowAtPageBreak(layout);
    expect(split).not.toBeNull();
    if (!split) return;
    // first 半的 cell 0 有完整內容（'plain'），cell 1 有 'left'
    expect(split.first.cells[0].blocks.length).toBeGreaterThan(0);
    // second 半的 cell 0 為空 placeholder，cell 1 有 'right'
    expect(split.second.cells[0].blocks.length).toBe(0);
    expect(split.second.cells[1].blocks.length).toBeGreaterThan(0);
  });

  it('巢狀表 cell：page break 在 lines 內仍可被偵測', () => {
    // 注意：splitRowAtPageBreak 只看 cell.blocks 中 kind='lines' 的 lines
    // 巢狀 table block 的 break 不會被本函式偵測（屬於更深層遞迴範圍）
    const row = rowNode([cellWithBreak('a', 'b')]);
    const layout = layoutRow(row, 0, tableNode([200], [row]), [200]);
    const split = splitRowAtPageBreak(layout);
    expect(split).not.toBeNull();
  });

  it('split.first / split.second 的 containsImage 旗標各自重新計算', () => {
    const row = rowNode([cellWithBreak('text1', 'text2')]);
    const layout = layoutRow(row, 0, tableNode([200], [row]), [200]);
    const split = splitRowAtPageBreak(layout);
    expect(split).not.toBeNull();
    if (!split) return;
    expect(typeof split.first.containsImage).toBe('boolean');
    expect(typeof split.second.containsImage).toBe('boolean');
  });
});

describe('layoutCell — Sprint 37 cell-internal floatImage（wp:anchor）', () => {
  function paraWithFloat(text: string, floatProps: Partial<{
    rId: string;
    width: number;
    height: number;
    posHOffset: number;
    posVOffset: number;
    posVRelativeFrom: 'paragraph' | 'margin' | 'page';
    behindDoc: boolean;
    wrapType: 'none' | 'square';
  }>): ParagraphNode {
    return {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text, props: { fontSize: 12 } },
        {
          type: 'floatImage',
          rId: floatProps.rId ?? 'rId10',
          width: floatProps.width ?? 70,
          height: floatProps.height ?? 22,
          posH: { relativeFrom: 'column', posOffset: floatProps.posHOffset ?? 100 },
          posV: {
            relativeFrom: floatProps.posVRelativeFrom ?? 'paragraph',
            posOffset: floatProps.posVOffset ?? 50,
          },
          wrapType: floatProps.wrapType ?? 'none',
          ...(floatProps.behindDoc ? { behindDoc: true } : {}),
        },
      ],
    };
  }

  it('cell 內 floatImage 被提取到 CellLayout.floats（不進 lines）', () => {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraWithFloat('內文 hello', { rId: 'rIdFloat' })],
      props: {},
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));

    // cell.floats 應有 1 個
    expect(out.floats?.length).toBe(1);
    expect(out.floats?.[0].node.rId).toBe('rIdFloat');
    // floatImage 不應出現在 lines 內部 box（Sprint 36 真根因：原本 floatImage 被當 inline Box）
    for (const ln of out.lines) {
      for (const item of ln.items) {
        if (item.kind === 'box') {
          expect(item.imageRId).not.toBe('rIdFloat');
        }
      }
    }
  });

  it('xRel = padding.left + posH.posOffset（column relativeFrom）', () => {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraWithFloat('hi', { posHOffset: 80 })],
      props: { margins: { top: 0, bottom: 0, left: 5, right: 5 } },
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));
    expect(out.floats?.[0].xRel).toBeCloseTo(5 + 80, 4);
  });

  it('yRel paragraph relativeFrom：起點 = padding.top + 段落 y + posV.posOffset', () => {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      // 兩段：第一段一行內文、第二段含 floatImage
      content: [
        paraNode('first para'),
        paraWithFloat('second', { posVRelativeFrom: 'paragraph', posVOffset: 30 }),
      ],
      props: { margins: { top: 2, bottom: 2, left: 5, right: 5 } },
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));
    // 第一段一行高度 14.4pt（fontSize 12 × 1.2 leading）；第二段起點 = padding.top + 第一段高
    expect(out.floats?.length).toBe(1);
    const firstParaH = out.blocks[0].kind === 'lines' ? out.blocks[0].height : 0;
    expect(out.floats?.[0].yRel).toBeCloseTo(2 + firstParaH + 30, 4);
  });

  it('yRel margin / page relativeFrom：起點 = padding.top + posV.posOffset（忽略段落 y）', () => {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [
        paraNode('first para'),
        paraWithFloat('second', { posVRelativeFrom: 'margin', posVOffset: 40 }),
      ],
      props: { margins: { top: 3, bottom: 3, left: 5, right: 5 } },
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));
    expect(out.floats?.[0].yRel).toBeCloseTo(3 + 40, 4);
  });

  it('多 floatImage：依出現順序加入 cell.floats', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'x', props: { fontSize: 12 } },
        {
          type: 'floatImage', rId: 'a', width: 50, height: 50,
          posH: { relativeFrom: 'column', posOffset: 10 },
          posV: { relativeFrom: 'paragraph', posOffset: 10 },
          wrapType: 'none',
        },
        {
          type: 'floatImage', rId: 'b', width: 60, height: 60,
          posH: { relativeFrom: 'column', posOffset: 20 },
          posV: { relativeFrom: 'paragraph', posOffset: 20 },
          wrapType: 'none',
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
      props: {},
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));
    expect(out.floats?.length).toBe(2);
    expect(out.floats?.map((f) => f.node.rId)).toEqual(['a', 'b']);
  });

  it('cell.height 不被 floatImage 撐高（Sprint 36 真根因：原本 anchor 被當 inline Box 推 cell 變高）', () => {
    const cellWithFloat: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraWithFloat('hi', { width: 200, height: 300 })],
      props: {},
    };
    const cellPlain: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: false,
      content: [paraNode('hi')],
      props: {},
    };
    const outFloat = layoutCell(cellWithFloat, 300, 0, tableNode([300], []));
    const outPlain = layoutCell(cellPlain, 300, 0, tableNode([300], []));
    // float 為 wrapNone，不應佔垂直空間 → cell.height 一致
    expect(outFloat.height).toBeCloseTo(outPlain.height, 4);
  });

  it('cell 完全無 floatImage：floats 欄位為 undefined（不浪費 array 配置）', () => {
    const cell = cellNode('plain');
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.floats).toBeUndefined();
  });

  it('Sprint 38：cell 內 floatTextBox 也被提取（與 floatImage 同邏輯）', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [
        { type: 'run', text: 'hi', props: { fontSize: 12 } },
        {
          type: 'floatTextBox',
          width: 70, height: 22,
          posH: { relativeFrom: 'column', posOffset: 100 },
          posV: { relativeFrom: 'paragraph', posOffset: 30 },
          wrapType: 'none',
          paragraphs: [{
            type: 'paragraph',
            props: {},
            runs: [{ type: 'run', text: '112.12.29', props: { fontSize: 9 } }],
          }],
        },
      ],
    };
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0, gridSpan: 1, rowSpan: 1, isContinuation: false,
      content: [para],
      props: {},
    };
    const out = layoutCell(cell, 300, 0, tableNode([300], []));
    expect(out.floats?.length).toBe(1);
    expect(out.floats?.[0].node.type).toBe('floatTextBox');
    const fNode = out.floats?.[0].node;
    if (fNode?.type === 'floatTextBox') {
      expect(fNode.paragraphs.length).toBe(1);
      expect(fNode.paragraphs[0].runs[0]).toMatchObject({ text: '112.12.29' });
    }
    // floatTextBox 不應出現在 lines 內部
    for (const ln of out.lines) {
      for (const item of ln.items) {
        if (item.kind === 'box') {
          expect(item.text).not.toContain('112.12.29');
        }
      }
    }
  });

  it('isContinuation cell（vMerge 延續）：不解析 floatImage（內容跳過）', () => {
    const cell: CellNode = {
      type: 'cell',
      gridCol: 0,
      gridSpan: 1,
      rowSpan: 1,
      isContinuation: true,
      content: [paraWithFloat('hi', {})],
      props: {},
    };
    const out = layoutCell(cell, 100, 0, tableNode([100], []));
    expect(out.floats).toBeUndefined();
    expect(out.isContinuation).toBe(true);
  });
});
