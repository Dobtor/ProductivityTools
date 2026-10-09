/**
 * Sprint 320 — ④ deeper⁵：RevisionFilter。
 *
 * Sprint 300/305/310/315 之後深推。Preview view + predicate factory。
 *
 * 紀律 #18 scope-down：filterView 不展開 inline diff；不做 partial accept。
 */
import { describe, expect, it } from 'vitest';

import {
  filterView,
  summarizeFilterView,
  previewAccepted,
  predicateByAuthor,
  predicateByIds,
  predicateIdBefore,
} from '../../static/src/core/ooxml/revision';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
  RunRevision,
} from '../../static/src/core/ooxml/ast/types';

function mkRun(text: string, revision?: RunRevision): RunNode {
  return { type: 'run', text, props: {}, ...(revision ? { revision } : {}) };
}

function mkParagraph(runs: RunNode[]): ParagraphNode {
  return { type: 'paragraph', props: {}, runs };
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

function flatText(p: ParagraphNode): string {
  return p.runs.filter((r): r is RunNode => r.type === 'run').map((r) => r.text).join('');
}

// ── filterView 基本 ──────────────────────────────────────────────────

describe('Sprint 320 — filterView', () => {
  it('無 predicate → 全 pending', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1 }),
        mkRun('b', { type: 'del', author: 'X', id: 2 }),
      ]),
    ]);
    const view = filterView(doc);
    expect(view).toHaveLength(2);
    expect(view.every((e) => e.status === 'pending')).toBe(true);
  });

  it('acceptIf 命中 → will-accept、其餘 pending', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'ins', author: 'Bob', id: 2 }),
      ]),
    ]);
    const view = filterView(doc, { acceptIf: predicateByAuthor('Alice') });
    expect(view.find((e) => e.meta.id === 1)?.status).toBe('will-accept');
    expect(view.find((e) => e.meta.id === 2)?.status).toBe('pending');
  });

  it('rejectIf 命中 → will-reject、acceptIf 優先', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'ins', author: 'Bob', id: 2 }),
      ]),
    ]);
    const view = filterView(doc, {
      acceptIf: predicateByAuthor('Alice'),
      rejectIf: predicateByAuthor('Bob'),
    });
    expect(view.find((e) => e.meta.id === 1)?.status).toBe('will-accept');
    expect(view.find((e) => e.meta.id === 2)?.status).toBe('will-reject');
  });

  it('acceptIf 與 rejectIf 同時命中 → accept 優先', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'X', id: 1 })]),
    ]);
    const view = filterView(doc, {
      acceptIf: () => true,
      rejectIf: () => true,
    });
    expect(view[0].status).toBe('will-accept');
  });
});

// ── summarizeFilterView ────────────────────────────────────────────────

describe('Sprint 320 — summarizeFilterView', () => {
  it('計算各 status 數量', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'A', id: 1 }),
        mkRun('b', { type: 'ins', author: 'B', id: 2 }),
        mkRun('c', { type: 'ins', author: 'C', id: 3 }),
      ]),
    ]);
    const view = filterView(doc, {
      acceptIf: predicateByAuthor('A'),
      rejectIf: predicateByAuthor('B'),
    });
    const stats = summarizeFilterView(view);
    expect(stats).toEqual({ total: 3, willAccept: 1, willReject: 1, pending: 1 });
  });

  it('空 view → 全 0', () => {
    expect(summarizeFilterView([])).toEqual({ total: 0, willAccept: 0, willReject: 0, pending: 0 });
  });
});

// ── previewAccepted ────────────────────────────────────────────────────

describe('Sprint 320 — previewAccepted', () => {
  it('預覽：accept Alice、Bob 的留 pending', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('aliceIns', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('bobDel', { type: 'del', author: 'Bob', id: 2 }),
      ]),
    ]);
    const preview = previewAccepted(doc, predicateByAuthor('Alice'));
    const p = preview.sections[0].body[0] as ParagraphNode;
    // Alice 的 ins accept → 留 'aliceIns' 且 revision metadata 清；Bob 的 del 不變
    expect(flatText(p)).toBe('aliceIns' + 'bobDel');
    const runs = p.runs.filter((r): r is RunNode => r.type === 'run');
    expect(runs[0].revision).toBeUndefined();
    expect(runs[1].revision).toBeDefined();
  });

  it('原 doc 不被 mutate', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('x', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    previewAccepted(doc, predicateByAuthor('A'));
    const p = doc.sections[0].body[0] as ParagraphNode;
    expect((p.runs[0] as RunNode).revision).toBeDefined();
  });
});

// ── predicate factories ───────────────────────────────────────────────

describe('Sprint 320 — predicate factories', () => {
  it('predicateByAuthor', () => {
    const p = predicateByAuthor('Alice');
    expect(p({ author: 'Alice' })).toBe(true);
    expect(p({ author: 'Bob' })).toBe(false);
    expect(p({})).toBe(false);
  });

  it('predicateByIds', () => {
    const p = predicateByIds([1, 3, 5]);
    expect(p({ id: 1 })).toBe(true);
    expect(p({ id: 2 })).toBe(false);
    expect(p({ id: 5 })).toBe(true);
    expect(p({})).toBe(false);
  });

  it('predicateIdBefore', () => {
    const p = predicateIdBefore(10);
    expect(p({ id: 5 })).toBe(true);
    expect(p({ id: 10 })).toBe(false);
    expect(p({ id: 15 })).toBe(false);
    expect(p({})).toBe(false);
  });
});

// ── 邊界 ──────────────────────────────────────────────────────────────

describe('Sprint 320 — 邊界', () => {
  it('空 doc → 空 view', () => {
    expect(filterView(mkDoc([]))).toEqual([]);
  });
});
