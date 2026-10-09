/**
 * Sprint 340 — ④ deeper¹⁰：RevisionBatchAction。
 *
 * Sprint 300 accept/reject 之上做 dry-run plan + predicate composition + summary。
 *
 * 紀律 #18：純函式 batch planner；不接 OWL UI。
 */
import { describe, expect, it } from 'vitest';

import {
  planBatch,
  applyBatch,
  andP,
  orP,
  notP,
  byAuthor,
  byId,
  byIdSet,
  byRunType,
  summarizePlan,
} from '../../static/src/core/ooxml/revision/RevisionBatchAction';
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

// ── planBatch ──────────────────────────────────────────────────────

describe('Sprint 340 — planBatch', () => {
  it('全 doc → totalAffected = 全 list', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'A', id: 1 }),
        mkRun('b', { type: 'del', author: 'B', id: 2 }),
      ]),
    ]);
    const plan = planBatch(doc, 'accept');
    expect(plan.totalAffected).toBe(2);
    expect(plan.bySource['run-revision']).toBe(2);
  });

  it('predicate 過濾 → 只命中匹配', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'ins', author: 'Bob', id: 2 }),
      ]),
    ]);
    const plan = planBatch(doc, 'accept', byAuthor('Alice'));
    expect(plan.totalAffected).toBe(1);
  });

  it('空 doc → totalAffected = 0', () => {
    const doc = mkDoc([mkParagraph([mkRun('hi')])]);
    const plan = planBatch(doc, 'accept');
    expect(plan.totalAffected).toBe(0);
  });
});

// ── applyBatch ─────────────────────────────────────────────────────

describe('Sprint 340 — applyBatch', () => {
  it('accept ins → 保留 run、移除 revision metadata', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    const next = applyBatch(doc, 'accept');
    const p = next.sections[0].body[0] as ParagraphNode;
    expect(p.runs).toHaveLength(1);
    const r = p.runs[0] as RunNode;
    expect(r.revision).toBeUndefined();
  });

  it('reject del → 保留 run、移除 revision metadata', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'del', author: 'A', id: 1 })]),
    ]);
    const next = applyBatch(doc, 'reject');
    const p = next.sections[0].body[0] as ParagraphNode;
    expect(p.runs).toHaveLength(1);
  });

  it('predicate 過濾 → 只套到符合的 revision', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'ins', author: 'Bob', id: 2 }),
      ]),
    ]);
    const next = applyBatch(doc, 'accept', byAuthor('Alice'));
    const p = next.sections[0].body[0] as ParagraphNode;
    const aliceRun = (p.runs[0] as RunNode);
    const bobRun = (p.runs[1] as RunNode);
    expect(aliceRun.revision).toBeUndefined();
    expect(bobRun.revision).toBeDefined();
  });
});

// ── predicate composition ─────────────────────────────────────────

describe('Sprint 340 — andP / orP / notP', () => {
  const doc = mkDoc([
    mkParagraph([
      mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
      mkRun('b', { type: 'del', author: 'Alice', id: 2 }),
      mkRun('c', { type: 'ins', author: 'Bob', id: 3 }),
    ]),
  ]);

  it('andP：Alice + ins → 只命中 1', () => {
    expect(
      planBatch(doc, 'accept', andP(byAuthor('Alice'), byRunType('ins'))).totalAffected,
    ).toBe(1);
  });

  it('orP：Alice 或 Bob → 全命中', () => {
    expect(
      planBatch(doc, 'accept', orP(byAuthor('Alice'), byAuthor('Bob'))).totalAffected,
    ).toBe(3);
  });

  it('notP：非 Alice → 只命中 Bob', () => {
    expect(planBatch(doc, 'accept', notP(byAuthor('Alice'))).totalAffected).toBe(1);
  });

  it('byId / byIdSet', () => {
    expect(planBatch(doc, 'accept', byId(1)).totalAffected).toBe(1);
    expect(planBatch(doc, 'accept', byIdSet([1, 3])).totalAffected).toBe(2);
  });

  it('byRunType moveFrom → 不命中（doc 內無）', () => {
    expect(planBatch(doc, 'accept', byRunType('moveFrom')).totalAffected).toBe(0);
  });
});

// ── summarizePlan ─────────────────────────────────────────────────

describe('Sprint 340 — summarizePlan', () => {
  it('回 hasRunRevisions / hasPropChanges / hasCellRevisions', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'A', id: 1 })]),
    ]);
    const plan = planBatch(doc, 'accept');
    const sum = summarizePlan(plan);
    expect(sum.totalAffected).toBe(1);
    expect(sum.hasRunRevisions).toBe(true);
    expect(sum.hasPropChanges).toBe(false);
    expect(sum.hasCellRevisions).toBe(false);
  });

  it('pPrChange → hasPropChanges=true', () => {
    const doc = mkDoc([
      {
        type: 'paragraph',
        props: { pPrChange: { author: 'A', id: 1 } },
        runs: [mkRun('x')],
      },
    ]);
    const plan = planBatch(doc, 'accept');
    expect(summarizePlan(plan).hasPropChanges).toBe(true);
  });
});
