/**
 * Sprint 300 — ④ deeper: AST accept/reject revision helpers。
 *
 * Follow-up to Sprint 290 + 293 honest gap「UI accept/reject 面板 未做」。
 *
 * 本 sprint = pure-fn layer：caller 給 DocumentNode、回新樹、所有 revision
 * 按照 accept 或 reject 規則 transform。UI 面板留 future sprint。
 *
 * Test 範圍：
 *   - Run-level ins/del/moveFrom/moveTo accept/reject 行為矩陣
 *   - rPrChange / pPrChange / cellIns / cellDel / cellMerge metadata drop
 *   - predicate 過濾（依 id / author 選擇性 accept/reject）
 *   - immutability（原樹不被 mutate）
 *   - listRevisions 列舉
 *   - 細粒度 helpers（acceptParagraphRevisions）
 */
import { describe, expect, it } from 'vitest';

import {
  acceptRevisions,
  rejectRevisions,
  acceptParagraphRevisions,
  rejectParagraphRevisions,
  listRevisions,
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

// ── 測試 fixture builders ─────────────────────────────────────────────────

function mkRun(text: string, revision?: RunRevision, rPrChange?: { author?: string; date?: string; id?: number }): RunNode {
  return {
    type: 'run',
    text,
    props: rPrChange ? { rPrChange } : {},
    ...(revision ? { revision } : {}),
  };
}

function mkParagraph(runs: RunNode[], pPrChange?: { author?: string; id?: number }): ParagraphNode {
  return {
    type: 'paragraph',
    props: pPrChange ? { pPrChange } : {},
    runs,
  };
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

function mkCell(blocks: Array<ParagraphNode | TableNode>, cellMeta?: { cellIns?: { id: number }; cellDel?: { id: number }; cellMerge?: { id: number; val?: 'rest' } }): CellNode {
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
  return {
    type: 'table',
    grid: [100],
    rows: rowNodes,
    props: {},
  };
}

function flatText(p: ParagraphNode): string {
  return p.runs
    .filter((r): r is RunNode => r.type === 'run')
    .map((r) => r.text)
    .join('');
}

// ── Run-level accept/reject 矩陣 ───────────────────────────────────────────

describe('Sprint 300 — Run-level revision accept', () => {
  it('ins → keep run, drop revision metadata', () => {
    const doc = mkDoc([mkParagraph([mkRun('Inserted text', { type: 'ins', author: 'A', id: 1 })])]);
    const out = acceptRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(p.runs).toHaveLength(1);
    expect((p.runs[0] as RunNode).revision).toBeUndefined();
    expect(flatText(p)).toBe('Inserted text');
  });

  it('del → remove run', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('Keep ', undefined),
        mkRun('DELETE', { type: 'del', author: 'A', id: 2 }),
        mkRun(' tail'),
      ]),
    ]);
    const out = acceptRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(flatText(p)).toBe('Keep  tail');
  });

  it('moveFrom → remove run, moveTo → keep run', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('From-text', { type: 'moveFrom', author: 'A', id: 3 }),
        mkRun(' [middle] '),
        mkRun('To-text', { type: 'moveTo', author: 'A', id: 3 }),
      ]),
    ]);
    const out = acceptRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(flatText(p)).toBe(' [middle] To-text');
  });
});

describe('Sprint 300 — Run-level revision reject', () => {
  it('ins → remove run', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('orig '), mkRun('INSERTED', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    const out = rejectRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(flatText(p)).toBe('orig ');
  });

  it('del → keep run, moveFrom → keep, moveTo → remove', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('From-keep', { type: 'moveFrom', author: 'A', id: 3 }),
        mkRun(' x '),
        mkRun('To-removed', { type: 'moveTo', author: 'A', id: 3 }),
        mkRun(' x '),
        mkRun('Deleted-keep', { type: 'del', author: 'A', id: 4 }),
      ]),
    ]);
    const out = rejectRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(flatText(p)).toBe('From-keep x  x Deleted-keep');
    // revision metadata 全清
    for (const r of p.runs) {
      if (r.type === 'run') expect(r.revision).toBeUndefined();
    }
  });
});

// ── Props *Change metadata drop ────────────────────────────────────────────

describe('Sprint 300 — rPrChange / pPrChange metadata drop', () => {
  it('rPrChange present → accept drops metadata, run kept', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('text', undefined, { author: 'A', id: 7 })]),
    ]);
    const out = acceptRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    const r = p.runs[0] as RunNode;
    expect(r.props.rPrChange).toBeUndefined();
    expect(r.text).toBe('text');
  });

  it('pPrChange present → accept drops metadata, paragraph kept', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('hello')], { author: 'A', id: 8 }),
    ]);
    const out = acceptRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(p.props.pPrChange).toBeUndefined();
    expect(flatText(p)).toBe('hello');
  });

  it('reject 也丟 *Change metadata（scope-down：previous-state 還原為 future）', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('x', undefined, { author: 'A', id: 9 })], { author: 'A', id: 10 }),
    ]);
    const out = rejectRevisions(doc);
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(p.props.pPrChange).toBeUndefined();
    expect((p.runs[0] as RunNode).props.rPrChange).toBeUndefined();
  });
});

// ── Cell-level *Change drop ────────────────────────────────────────────────

describe('Sprint 300 — cell-level revision drop', () => {
  it('cellIns / cellDel / cellMerge → accept drops metadata', () => {
    const cell = mkCell([mkParagraph([mkRun('cell text')])], {
      cellIns: { id: 11 },
      cellDel: { id: 12 },
      cellMerge: { id: 13, val: 'rest' },
    });
    const doc = mkDoc([mkTable([[cell]])]);
    const out = acceptRevisions(doc);
    const t = out.sections[0].body[0] as TableNode;
    const c = t.rows[0].cells[0];
    expect(c.props.cellIns).toBeUndefined();
    expect(c.props.cellDel).toBeUndefined();
    expect(c.props.cellMerge).toBeUndefined();
    // cell content 不變
    expect(flatText(c.content[0] as ParagraphNode)).toBe('cell text');
  });
});

// ── Predicate 過濾 ────────────────────────────────────────────────────────

describe('Sprint 300 — predicate 過濾選擇性 accept', () => {
  it('只 accept id=5、id=6 留下', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('alpha ', { type: 'ins', author: 'A', id: 5 }),
        mkRun('beta ', { type: 'ins', author: 'B', id: 6 }),
      ]),
    ]);
    const out = acceptRevisions(doc, { predicate: (m) => m.id === 5 });
    const p = out.sections[0].body[0] as ParagraphNode;
    expect((p.runs[0] as RunNode).revision).toBeUndefined(); // accepted
    expect((p.runs[1] as RunNode).revision).toEqual({ type: 'ins', author: 'B', id: 6 }); // unchanged
  });

  it('只 accept author = Alice', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('alice-ins ', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('bob-del', { type: 'del', author: 'Bob', id: 2 }),
      ]),
    ]);
    const out = acceptRevisions(doc, { predicate: (m) => m.author === 'Alice' });
    const p = out.sections[0].body[0] as ParagraphNode;
    expect(flatText(p)).toBe('alice-ins bob-del');
    expect((p.runs[0] as RunNode).revision).toBeUndefined();
    expect((p.runs[1] as RunNode).revision).toBeDefined(); // bob-del 不變
  });
});

// ── Immutability ──────────────────────────────────────────────────────────

describe('Sprint 300 — immutability', () => {
  it('原 DocumentNode 不被 mutate', () => {
    const original = mkDoc([
      mkParagraph([mkRun('text', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    const originalRevision = ((original.sections[0].body[0] as ParagraphNode).runs[0] as RunNode).revision;
    acceptRevisions(original);
    const after = ((original.sections[0].body[0] as ParagraphNode).runs[0] as RunNode).revision;
    expect(after).toEqual(originalRevision);
    expect(after).toBeDefined();
  });
});

// ── listRevisions 列舉 ────────────────────────────────────────────────────

describe('Sprint 300 — listRevisions', () => {
  it('列舉 run/p/cell 各層 revision', () => {
    const cell = mkCell([mkParagraph([mkRun('cell', { type: 'ins', author: 'X', id: 20 })])], {
      cellIns: { id: 21 },
    });
    const doc = mkDoc([
      mkParagraph(
        [
          mkRun('r1 ', { type: 'del', author: 'A', id: 1 }),
          mkRun('r2 ', undefined, { author: 'B', id: 2 }),
        ],
        { author: 'C', id: 3 },
      ),
      mkTable([[cell]]),
    ]);
    const list = listRevisions(doc);
    const sources = list.map((e) => e.source).sort();
    expect(sources).toEqual(['cellIns', 'pPrChange', 'rPrChange', 'run-revision', 'run-revision']);
  });
});

// ── 細粒度 helpers ────────────────────────────────────────────────────────

describe('Sprint 300 — 細粒度 helpers', () => {
  it('acceptParagraphRevisions / rejectParagraphRevisions 對單一段落運作', () => {
    const p = mkParagraph([
      mkRun('ins ', { type: 'ins', author: 'A', id: 1 }),
      mkRun('del', { type: 'del', author: 'A', id: 2 }),
    ]);
    const accepted = acceptParagraphRevisions(p);
    expect(flatText(accepted)).toBe('ins ');
    const rejected = rejectParagraphRevisions(p);
    expect(flatText(rejected)).toBe('del');
  });
});
