/**
 * Sprint 305 — ④ deeper：RevisionReviewSession 狀態機。
 *
 * Sprint 300 補 pure-fn accept/reject helpers；本 sprint 補 UI-agnostic
 * 「逐筆 review」session。
 *
 * 紀律 #18 scope-down：caller bind 到 OWL / vanilla JS UI 為 future。
 */
import { describe, expect, it } from 'vitest';

import { RevisionReviewSession } from '../../static/src/core/ooxml/revision';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
  RunRevision,
} from '../../static/src/core/ooxml/ast/types';

// ── fixture builders ─────────────────────────────────────────────────────

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

// ── 基本游標推進 ──────────────────────────────────────────────────────────

describe('Sprint 305 — cursor 推進', () => {
  it('current() / isDone() / stats()', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('A', { type: 'ins', author: 'X', id: 1 }),
        mkRun('B', { type: 'del', author: 'X', id: 2 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    expect(session.stats().total).toBe(2);
    expect(session.isDone()).toBe(false);
    expect(session.current()?.meta.id).toBe(1);
    session.skipCurrent();
    expect(session.current()?.meta.id).toBe(2);
    session.skipCurrent();
    expect(session.isDone()).toBe(true);
    expect(session.current()).toBeNull();
  });

  it('isDone() 時 acceptCurrent / rejectCurrent throw', () => {
    const doc = mkDoc([mkParagraph([])]); // 無 revision
    const session = new RevisionReviewSession(doc);
    expect(session.isDone()).toBe(true);
    expect(() => session.acceptCurrent()).toThrow(/no current/);
    expect(() => session.rejectCurrent()).toThrow(/no current/);
  });
});

// ── accept / reject 套用到 doc ────────────────────────────────────────────

describe('Sprint 305 — accept / reject 累積套用', () => {
  it('acceptCurrent → ins run 保留、del run 移除', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('keep ', { type: 'ins', author: 'X', id: 1 }),
        mkRun('del', { type: 'del', author: 'X', id: 2 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    session.acceptCurrent(); // 接受 ins（id=1）
    session.acceptCurrent(); // 接受 del（id=2、del run 被移除）
    const finalDoc = session.getDocument();
    expect(flatText(finalDoc.sections[0].body[0] as ParagraphNode)).toBe('keep ');
  });

  it('rejectCurrent → ins run 移除、del run 留', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('orig ', { type: 'del', author: 'X', id: 1 }),
        mkRun('new', { type: 'ins', author: 'X', id: 2 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    session.rejectCurrent(); // reject del → run 留
    session.rejectCurrent(); // reject ins → run 移除
    expect(flatText(session.getDocument().sections[0].body[0] as ParagraphNode)).toBe('orig ');
  });

  it('mixed accept / reject / skip', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1 }),
        mkRun('b', { type: 'ins', author: 'X', id: 2 }),
        mkRun('c', { type: 'ins', author: 'X', id: 3 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    session.acceptCurrent(); // id=1 → keep
    session.skipCurrent();   // id=2 → keep revision metadata
    session.rejectCurrent(); // id=3 → remove run
    const s = session.stats();
    expect(s.accepted).toBe(1);
    expect(s.rejected).toBe(1);
    expect(s.skipped).toBe(1);
    expect(s.remaining).toBe(0);
    const p = session.getDocument().sections[0].body[0] as ParagraphNode;
    // 'a' accepted（kept）, 'b' skipped（still has revision but kept）, 'c' rejected（removed）
    expect(flatText(p)).toBe('ab');
  });
});

// ── id-based predicate 精準對位 ───────────────────────────────────────────

describe('Sprint 305 — id-based predicate 精準對位', () => {
  it('多筆同 type 不同 id：accept 一筆只影響該 id', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('x ', { type: 'ins', author: 'X', id: 10 }),
        mkRun('y', { type: 'ins', author: 'Y', id: 20 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    session.acceptCurrent(); // accept id=10
    const p = session.getDocument().sections[0].body[0] as ParagraphNode;
    // 'x ' 的 revision 應已 drop，'y' 的 revision 應仍在
    const runs = p.runs.filter((r): r is RunNode => r.type === 'run');
    expect(runs[0].revision).toBeUndefined();
    expect(runs[1].revision).toBeDefined();
    expect(runs[1].revision?.id).toBe(20);
  });
});

// ── resetCursor ─────────────────────────────────────────────────────────

describe('Sprint 305 — resetCursor', () => {
  it('reset 後 cursor 回 0、stats 計數清零、但 doc 已 applied 修訂不還原', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('A', { type: 'ins', author: 'X', id: 1 })]),
    ]);
    const session = new RevisionReviewSession(doc);
    session.acceptCurrent();
    expect(session.isDone()).toBe(true);
    session.resetCursor();
    expect(session.isDone()).toBe(false); // 1 筆 revision 仍在 queue
    // 但 doc 已被 accept、revision metadata 已 drop
    const p = session.getDocument().sections[0].body[0] as ParagraphNode;
    expect((p.runs[0] as RunNode).revision).toBeUndefined();
    expect(session.stats().accepted).toBe(0);
  });
});

// ── all() / 空 doc ───────────────────────────────────────────────────────

describe('Sprint 305 — 邊界', () => {
  it('空 doc → isDone true、stats.total=0', () => {
    const session = new RevisionReviewSession(mkDoc([]));
    expect(session.isDone()).toBe(true);
    expect(session.stats()).toEqual({ total: 0, accepted: 0, rejected: 0, skipped: 0, remaining: 0 });
    expect(session.all()).toEqual([]);
  });

  it('all() 列舉所有 entries', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1 }),
        mkRun('b', { type: 'del', author: 'X', id: 2 }),
      ]),
    ]);
    const session = new RevisionReviewSession(doc);
    expect(session.all().length).toBe(2);
  });
});
