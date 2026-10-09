/**
 * Sprint 325 — ④ deeper⁶：RevisionTimelineBuilder。
 *
 * Sprint 300/305/310/315/320 之後深推。Timeline 分群（day / hour / author-day）。
 *
 * 紀律 #18 scope-down：不展開 inline diff、不做 sliding window；date 用 ISO string 比較。
 */
import { describe, expect, it } from 'vitest';

import {
  buildTimeline,
  summarizeTimeline,
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

// ── day granularity ──────────────────────────────────────────────────

describe('Sprint 325 — buildTimeline day granularity', () => {
  it('同日多 revision 同一 bucket', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-15T10:00:00Z' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2, date: '2026-05-15T14:00:00Z' }),
      ]),
    ]);
    const buckets = buildTimeline(doc);
    expect(buckets).toHaveLength(1);
    expect(buckets[0].date).toBe('2026-05-15');
    expect(buckets[0].count).toBe(2);
  });

  it('不同日各自 bucket、降冪排序', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-10T10:00:00Z' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2, date: '2026-05-20T10:00:00Z' }),
        mkRun('c', { type: 'ins', author: 'X', id: 3, date: '2026-05-15T10:00:00Z' }),
      ]),
    ]);
    const buckets = buildTimeline(doc);
    expect(buckets.map((b) => b.date)).toEqual(['2026-05-20', '2026-05-15', '2026-05-10']);
  });

  it('asc order', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-10' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2, date: '2026-05-20' }),
      ]),
    ]);
    const buckets = buildTimeline(doc, { order: 'asc' });
    expect(buckets.map((b) => b.date)).toEqual(['2026-05-10', '2026-05-20']);
  });
});

// ── hour granularity ─────────────────────────────────────────────────

describe('Sprint 325 — hour granularity', () => {
  it('同日不同小時 → 不同 bucket', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-15T10:30:00Z' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2, date: '2026-05-15T14:30:00Z' }),
      ]),
    ]);
    const buckets = buildTimeline(doc, { granularity: 'hour' });
    expect(buckets).toHaveLength(2);
    const hours = buckets.map((b) => b.hour).sort();
    expect(hours).toEqual([10, 14]);
  });

  it('date 不含 hour → fallback 為 day key', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-15' })]),
    ]);
    const buckets = buildTimeline(doc, { granularity: 'hour' });
    expect(buckets[0].hour).toBeUndefined();
    expect(buckets[0].key).toBe('2026-05-15');
  });
});

// ── author-day granularity ──────────────────────────────────────────

describe('Sprint 325 — author-day granularity', () => {
  it('同日不同 author → 不同 bucket', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'Alice', id: 1, date: '2026-05-15T10:00:00Z' }),
        mkRun('b', { type: 'ins', author: 'Bob', id: 2, date: '2026-05-15T11:00:00Z' }),
      ]),
    ]);
    const buckets = buildTimeline(doc, { granularity: 'author-day' });
    expect(buckets).toHaveLength(2);
    expect(buckets.map((b) => b.author).sort()).toEqual(['Alice', 'Bob']);
  });

  it('author 缺失 → "Unknown"', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', id: 1, date: '2026-05-15' })]),
    ]);
    const buckets = buildTimeline(doc, { granularity: 'author-day' });
    expect(buckets[0].author).toBe('Unknown');
  });
});

// ── unknown date ────────────────────────────────────────────────────

describe('Sprint 325 — unknown date', () => {
  it('缺 date → unknown bucket、永遠最後', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-15' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2 }), // 無 date
        mkRun('c', { type: 'ins', author: 'X', id: 3, date: '2026-05-10' }),
      ]),
    ]);
    const buckets = buildTimeline(doc);
    expect(buckets[buckets.length - 1].date).toBe('unknown');
  });

  it('解析不合法 date → unknown', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('a', { type: 'ins', author: 'X', id: 1, date: 'garbage' })]),
    ]);
    const buckets = buildTimeline(doc);
    expect(buckets[0].date).toBe('unknown');
  });
});

// ── 空 doc / 無 revision ──────────────────────────────────────────

describe('Sprint 325 — 邊界', () => {
  it('空 doc → 空 buckets', () => {
    expect(buildTimeline(mkDoc([]))).toEqual([]);
  });
});

// ── summarizeTimeline ─────────────────────────────────────────────

describe('Sprint 325 — summarizeTimeline', () => {
  it('回 earliest / latest / hasUnknown / totalBuckets', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1, date: '2026-05-10' }),
        mkRun('b', { type: 'ins', author: 'X', id: 2, date: '2026-05-25' }),
        mkRun('c', { type: 'ins', author: 'X', id: 3 }),
      ]),
    ]);
    const buckets = buildTimeline(doc);
    const s = summarizeTimeline(buckets);
    expect(s.totalBuckets).toBe(3);
    expect(s.hasUnknown).toBe(true);
    expect(s.earliestDate).toBe('2026-05-10');
    expect(s.latestDate).toBe('2026-05-25');
  });

  it('空 buckets → totalBuckets=0, hasUnknown=false', () => {
    const s = summarizeTimeline([]);
    expect(s).toEqual({ totalBuckets: 0, hasUnknown: false });
  });
});
