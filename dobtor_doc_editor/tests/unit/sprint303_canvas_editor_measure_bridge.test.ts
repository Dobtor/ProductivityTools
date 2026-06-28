/**
 * Sprint 303 — ① deeper：CanvasEditorMeasureBridge。
 *
 * Sprint 302 PROBE 第二輪。Sprint 302 TextMeasureProxy 提供 sync/async bridge；
 * 本 sprint 補：
 *   - Canvas-shape `measureText(text) → { width }`（pt → px 換算）
 *   - prewarmFromAst：walks DocumentNode 自動收集 unique (text, family, sizePt)
 *   - dpi 可覆寫（96 / 192 Retina 等）
 *
 * 紀律 #18 scope-down：不接 canvas-editor real path（紀律 #21）；只回 width
 *   （actualBoundingBox* 屬性 caller 真用到再 follow-up extend）。
 */
import { describe, expect, it } from 'vitest';

import { CanvasEditorMeasureBridge } from '../../static/src/core/ooxml/font/CanvasEditorMeasureBridge';
import type { RunMetrics } from '../../static/src/core/ooxml/font/ShapingEngine';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
  RowNode,
  CellNode,
} from '../../static/src/core/ooxml/ast/types';

function fakeMeasureRun(text: string, _family: string, sizePt: number): Promise<RunMetrics> {
  return Promise.resolve({
    widthPt: text.length * sizePt * 0.5,
    heightPt: sizePt,
    glyphCount: text.length,
    advancesPt: text.split('').map(() => sizePt * 0.5),
    glyphs: [],
  });
}

// ── pt → px 轉換 ───────────────────────────────────────────────────────────

describe('Sprint 303 — pt → px 換算', () => {
  it('96 dpi（預設）：1pt = 4/3 px', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const m = await bridge.measureTextAsync('Hi', 'F', 12); // widthPt = 12
    // 12pt * 4/3 = 16px
    expect(m.width).toBeCloseTo(16);
  });

  it('192 dpi：1pt = 8/3 px', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun, { dpi: 192 });
    const m = await bridge.measureTextAsync('Hi', 'F', 12); // widthPt = 12
    // 12 * 4/3 * (192/96) = 32px
    expect(m.width).toBeCloseTo(32);
  });

  it('72 dpi：1pt = 1 px', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun, { dpi: 72 });
    const m = await bridge.measureTextAsync('Hi', 'F', 12); // widthPt = 12
    expect(m.width).toBeCloseTo(12);
  });
});

// ── sync measureText cache hit / miss ──────────────────────────────────────

describe('Sprint 303 — sync measureText', () => {
  it('未 prewarm → 回 null', () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    expect(bridge.measureText('Hi', 'F', 12)).toBeNull();
  });

  it('prewarmFromAst 後 sync measureText 回 cache px width', async () => {
    const doc = mkDoc([mkParagraph([mkRun('Hello', 'F', 12)])]);
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const n = await bridge.prewarmFromAst(doc, 'F', 12);
    expect(n).toBe(1);
    const m = bridge.measureText('Hello', 'F', 12);
    expect(m).not.toBeNull();
    expect(m!.width).toBeCloseTo(5 * 12 * 0.5 * (4 / 3));
  });
});

// ── prewarmFromAst dedup + AST walk ────────────────────────────────────────

describe('Sprint 303 — prewarmFromAst', () => {
  it('dedup unique tuples（同 text/family/size 只 measure 一次）', async () => {
    let called = 0;
    const counting: typeof fakeMeasureRun = (t, f, s) => {
      called++;
      return fakeMeasureRun(t, f, s);
    };
    const doc = mkDoc([
      mkParagraph([mkRun('A', 'F', 12), mkRun('A', 'F', 12)]),
      mkParagraph([mkRun('A', 'F', 12)]),
    ]);
    const bridge = new CanvasEditorMeasureBridge(counting);
    const n = await bridge.prewarmFromAst(doc, 'F', 12);
    expect(n).toBe(1);
    expect(called).toBe(1);
  });

  it('遞迴進 table cell content', async () => {
    const doc = mkDoc([
      mkTable([
        [mkCell([mkParagraph([mkRun('inside', 'F', 14)])])],
      ]),
    ]);
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const n = await bridge.prewarmFromAst(doc, 'F', 14);
    expect(n).toBe(1);
    expect(bridge.measureText('inside', 'F', 14)).not.toBeNull();
  });

  it('defaultFamily / defaultSizePt fallback when RunProps 缺欄位', async () => {
    const doc = mkDoc([mkParagraph([mkRun('NoFont', undefined, undefined)])]);
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    await bridge.prewarmFromAst(doc, 'DefaultFont', 11);
    expect(bridge.measureText('NoFont', 'DefaultFont', 11)).not.toBeNull();
  });

  it('空字串 run 跳過', async () => {
    const doc = mkDoc([mkParagraph([mkRun('', 'F', 12)])]);
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const n = await bridge.prewarmFromAst(doc, 'F', 12);
    expect(n).toBe(0);
  });
});

// ── stats / clear passthrough ──────────────────────────────────────────────

describe('Sprint 303 — stats / clear passthrough', () => {
  it('stats 反映 underlying proxy', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    const doc = mkDoc([mkParagraph([mkRun('X', 'F', 12)])]);
    await bridge.prewarmFromAst(doc, 'F', 12);
    bridge.measureText('X', 'F', 12); // hit
    bridge.measureText('Y', 'F', 12); // miss
    const s = bridge.stats();
    expect(s.size).toBe(1);
    expect(s.hits).toBe(1);
    expect(s.misses).toBe(1);
  });

  it('clear 後 cache 空', async () => {
    const bridge = new CanvasEditorMeasureBridge(fakeMeasureRun);
    await bridge.measureTextAsync('X', 'F', 12);
    bridge.clear();
    expect(bridge.measureText('X', 'F', 12)).toBeNull();
  });
});

// ── 測試 fixture builders ─────────────────────────────────────────────────

function mkRun(text: string, family: string | undefined, fontSize: number | undefined): RunNode {
  const props: { fontFamily?: string; fontSize?: number } = {};
  if (family !== undefined) props.fontFamily = family;
  if (fontSize !== undefined) props.fontSize = fontSize;
  return { type: 'run', text, props };
}

function mkParagraph(runs: RunNode[]): ParagraphNode {
  return { type: 'paragraph', props: {}, runs };
}

function mkCell(blocks: Array<ParagraphNode | TableNode>): CellNode {
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content: blocks,
    props: {},
  };
}

function mkTable(rows: Array<CellNode[]>): TableNode {
  const rowNodes: RowNode[] = rows.map((cells) => ({
    type: 'row',
    cells,
    props: { isHeader: false, cantSplit: false },
  }));
  return { type: 'table', grid: [100], rows: rowNodes, props: {} };
}

function mkSection(blocks: Array<ParagraphNode | TableNode>): SectionNode {
  return {
    type: 'section',
    page: { width: 595, height: 842, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body: blocks,
  };
}

function mkDoc(blocks: Array<ParagraphNode | TableNode>): DocumentNode {
  return {
    type: 'document',
    sections: [mkSection(blocks)],
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    comments: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering: new Map(),
    media: new Map(),
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  } as DocumentNode;
}
