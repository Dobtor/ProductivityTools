/**
 * Sprint 315 — ④ deeper⁴：RevisionConflictDetector。
 *
 * Sprint 300/305/310 之後深推。偵測 mixed-author / move-pair-mismatch /
 * orphan move / pProps+run revision 共存等衝突。
 *
 * 紀律 #18 scope-down：不做語意衝突；不主動建議解法。
 */
import { describe, expect, it } from 'vitest';

import {
  detectConflicts,
  detectConflictsInParagraph,
  summarizeConflicts,
} from '../../static/src/core/ooxml/revision';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
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

// ── mixed-author-in-paragraph ───────────────────────────────────────────

describe('Sprint 315 — mixed-author-in-paragraph', () => {
  it('同段落多 author → conflict 報告', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('alice', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('bob', { type: 'ins', author: 'Bob', id: 2 }),
      ]),
    ]);
    const reports = detectConflicts(doc);
    const mixed = reports.find((r) => r.kind === 'mixed-author-in-paragraph');
    expect(mixed).toBeDefined();
    expect(mixed?.authors.sort()).toEqual(['Alice', 'Bob']);
    expect(mixed?.revisionIds).toEqual([1, 2]);
  });

  it('同段落單一 author → 無 mixed-author conflict', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1 }),
        mkRun('b', { type: 'del', author: 'Alice', id: 2 }),
      ]),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'mixed-author-in-paragraph')).toBeUndefined();
  });
});

// ── move-pair-author-mismatch ──────────────────────────────────────────

describe('Sprint 315 — move-pair-author-mismatch', () => {
  it('moveFrom 與 moveTo author 不一致 → conflict', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('A', { type: 'moveFrom', author: 'Alice', id: 5 })]),
      mkParagraph([mkRun('A', { type: 'moveTo', author: 'Bob', id: 5 })]),
    ]);
    const reports = detectConflicts(doc);
    const mismatch = reports.find((r) => r.kind === 'move-pair-author-mismatch');
    expect(mismatch).toBeDefined();
    expect(mismatch?.authors.sort()).toEqual(['Alice', 'Bob']);
  });

  it('moveFrom/moveTo author 一致 → 無 conflict', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('A', { type: 'moveFrom', author: 'Alice', id: 5 })]),
      mkParagraph([mkRun('A', { type: 'moveTo', author: 'Alice', id: 5 })]),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'move-pair-author-mismatch')).toBeUndefined();
  });
});

// ── move-pair-orphan ────────────────────────────────────────────────────

describe('Sprint 315 — move-pair-orphan', () => {
  it('只有 moveFrom 沒 moveTo → orphan', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('A', { type: 'moveFrom', author: 'X', id: 5 })]),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'move-pair-orphan')).toBeDefined();
  });

  it('只有 moveTo 沒 moveFrom → orphan', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('A', { type: 'moveTo', author: 'X', id: 5 })]),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'move-pair-orphan')).toBeDefined();
  });
});

// ── run-props-and-revision-coexist ────────────────────────────────────

describe('Sprint 315 — run-props-and-revision-coexist', () => {
  it('同 run 同時帶 revision + rPrChange → conflict', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('x', { type: 'ins', author: 'A', id: 1 }, { author: 'B', id: 2 }),
      ]),
    ]);
    const reports = detectConflicts(doc);
    const coexist = reports.find((r) => r.kind === 'run-props-and-revision-coexist');
    expect(coexist).toBeDefined();
    expect(coexist?.authors.sort()).toEqual(['A', 'B']);
  });
});

// ── paragraph-pPrChange-and-runs-revision ────────────────────────────

describe('Sprint 315 — paragraph-pPrChange-and-runs-revision', () => {
  it('段落 pPrChange + 內部 run revision 共存', () => {
    const doc = mkDoc([
      mkParagraph(
        [mkRun('x', { type: 'ins', author: 'B', id: 2 })],
        { author: 'A', id: 1 },
      ),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'paragraph-pPrChange-and-runs-revision')).toBeDefined();
  });

  it('只有 pPrChange 沒 run revision → 不算', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('x')], { author: 'A', id: 1 }),
    ]);
    const reports = detectConflicts(doc);
    expect(reports.find((r) => r.kind === 'paragraph-pPrChange-and-runs-revision')).toBeUndefined();
  });
});

// ── summarizeConflicts ────────────────────────────────────────────────

describe('Sprint 315 — summarizeConflicts', () => {
  it('無衝突 → "無偵測到 revision 衝突。"', () => {
    expect(summarizeConflicts([])).toContain('無偵測到');
  });

  it('多衝突 → 計次每 kind', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'A', id: 1 }),
        mkRun('b', { type: 'ins', author: 'B', id: 2 }),
        mkRun('c', { type: 'moveFrom', author: 'A', id: 3 }),
      ]),
    ]);
    const reports = detectConflicts(doc);
    const summary = summarizeConflicts(reports);
    expect(summary).toContain('mixed-author-in-paragraph');
    expect(summary).toContain('move-pair-orphan');
  });
});

// ── detectConflictsInParagraph ────────────────────────────────────────

describe('Sprint 315 — detectConflictsInParagraph 增量 API', () => {
  it('單一段落掃描', () => {
    const p = mkParagraph([
      mkRun('a', { type: 'ins', author: 'A', id: 1 }),
      mkRun('b', { type: 'ins', author: 'B', id: 2 }),
    ]);
    const reports = detectConflictsInParagraph(p);
    expect(reports.length).toBeGreaterThan(0);
    expect(reports[0].kind).toBe('mixed-author-in-paragraph');
  });
});

// ── 邊界 / 空 doc ─────────────────────────────────────────────────────

describe('Sprint 315 — 邊界', () => {
  it('空 doc → 空 reports', () => {
    expect(detectConflicts(mkDoc([]))).toEqual([]);
  });

  it('段落內無 revision → 空 reports', () => {
    const doc = mkDoc([mkParagraph([mkRun('hello')])]);
    expect(detectConflicts(doc)).toEqual([]);
  });
});
