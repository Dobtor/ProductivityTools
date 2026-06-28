/**
 * Sprint 310 — ④ deeper³：RevisionDiffSummary。
 *
 * Sprint 300/305 後第三輪深推。人類可讀 by author / by type 統計 + markdown 輸出。
 *
 * 紀律 #18 scope-down：不展開具體文字、不做 i18n、不做 trend over time。
 */
import { describe, expect, it } from 'vitest';

import {
  summarizeByAuthor,
  summarizeByType,
  formatSummaryMarkdown,
} from '../../static/src/core/ooxml/revision';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
  RowNode,
  CellNode,
  RunRevision,
} from '../../static/src/core/ooxml/ast/types';

function mkRun(text: string, revision?: RunRevision, rPrChange?: { author?: string; id?: number }): RunNode {
  return {
    type: 'run',
    text,
    props: rPrChange ? { rPrChange } : {},
    ...(revision ? { revision } : {}),
  };
}

function mkParagraph(runs: RunNode[], pPrChange?: { author?: string; id?: number }): ParagraphNode {
  return { type: 'paragraph', props: pPrChange ? { pPrChange } : {}, runs };
}

function mkCell(blocks: Array<ParagraphNode | TableNode>, cellMeta?: { cellIns?: { author?: string; id: number } }): CellNode {
  return {
    type: 'cell',
    gridCol: 0,
    gridSpan: 1,
    rowSpan: 1,
    isContinuation: false,
    content: blocks,
    props: { ...(cellMeta ?? {}) },
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

// ── summarizeByAuthor ────────────────────────────────────────────────────

describe('Sprint 310 — summarizeByAuthor', () => {
  it('多 author 分桶、依 total 降序', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'ins', author: 'Alice', id: 2 }),
        mkRun('c', { type: 'del', author: 'Alice', id: 3 }),
        mkRun('d', { type: 'ins', author: 'Bob', id: 4 }),
      ]),
    ]);
    const out = summarizeByAuthor(doc);
    expect(out).toHaveLength(2);
    expect(out[0].author).toBe('Alice');
    expect(out[0].total).toBe(3);
    expect(out[0].byType).toEqual({ ins: 2, del: 1 });
    expect(out[1].author).toBe('Bob');
    expect(out[1].total).toBe(1);
  });

  it('author 缺失 → "Unknown" bucket', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('x', { type: 'ins', id: 1 })]),  // 無 author
    ]);
    const out = summarizeByAuthor(doc);
    expect(out).toHaveLength(1);
    expect(out[0].author).toBe('Unknown');
  });

  it('空 doc → 空陣列', () => {
    expect(summarizeByAuthor(mkDoc([]))).toEqual([]);
  });

  it('包含 *Change 與 cellIns 等其他 type', () => {
    const cell = mkCell([mkParagraph([])], { cellIns: { author: 'X', id: 1 } });
    const doc = mkDoc([
      mkParagraph(
        [mkRun('a', undefined, { author: 'X', id: 2 })],
        { author: 'X', id: 3 },
      ),
      mkTable([[cell]]),
    ]);
    const out = summarizeByAuthor(doc);
    expect(out).toHaveLength(1);
    expect(out[0].byType).toEqual({ pPrChange: 1, rPrChange: 1, cellIns: 1 });
    expect(out[0].total).toBe(3);
  });
});

// ── summarizeByType ─────────────────────────────────────────────────────

describe('Sprint 310 — summarizeByType', () => {
  it('依 type 統計、降序排序', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'A', id: 1 }),
        mkRun('b', { type: 'ins', author: 'A', id: 2 }),
        mkRun('c', { type: 'del', author: 'A', id: 3 }),
      ]),
    ]);
    const out = summarizeByType(doc);
    expect(out).toEqual([{ type: 'ins', count: 2 }, { type: 'del', count: 1 }]);
  });

  it('混合 source（ins / rPrChange / cellIns）', () => {
    const cell = mkCell([mkParagraph([])], { cellIns: { author: 'X', id: 1 } });
    const doc = mkDoc([
      mkParagraph([mkRun('a', undefined, { author: 'X', id: 2 })]),
      mkTable([[cell]]),
    ]);
    const out = summarizeByType(doc);
    const types = out.map((t) => t.type).sort();
    expect(types).toEqual(['cellIns', 'rPrChange']);
  });
});

// ── formatSummaryMarkdown ───────────────────────────────────────────────

describe('Sprint 310 — formatSummaryMarkdown', () => {
  it('產出含 Total + By Author + By Type 三段', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'del', author: 'Bob', id: 2 }),
      ]),
    ]);
    const md = formatSummaryMarkdown(doc);
    expect(md).toContain('## Revision Summary');
    expect(md).toContain('**Total: 2 revisions**');
    expect(md).toContain('### By Author');
    expect(md).toContain('| Alice | 1 | ins×1 |');
    expect(md).toContain('| Bob | 1 | del×1 |');
    expect(md).toContain('### By Type');
  });

  it('空 doc → 只有標頭與 Total: 0', () => {
    const md = formatSummaryMarkdown(mkDoc([]));
    expect(md).toContain('**Total: 0 revisions**');
    expect(md).not.toContain('### By Author');
    expect(md).not.toContain('### By Type');
  });

  it('單一 revision 用單數 "revision"', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    const md = formatSummaryMarkdown(doc);
    expect(md).toContain('**Total: 1 revision**');
    expect(md).not.toContain('1 revisions');
  });
});
