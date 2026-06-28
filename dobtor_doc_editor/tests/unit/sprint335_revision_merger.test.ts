/**
 * Sprint 335 — ④ deeper⁹：RevisionMerger。
 *
 * Sprint 330 RevisionExporter 之後深推。Multi-source merge + 去重 + sort + group。
 *
 * 紀律 #18：純 array transform；不接 file system / git merge；無時區轉換。
 */
import { describe, expect, it } from 'vitest';

import {
  mergeRevisionRows,
  sortByDate,
  groupByAuthor,
  detectMergeConflicts,
  summarizeMerge,
} from '../../static/src/core/ooxml/revision/RevisionMerger';
import type { RevisionExportRow } from '../../static/src/core/ooxml/revision/RevisionExporter';

const row = (
  source: RevisionExportRow['source'],
  subtype: RevisionExportRow['subtype'],
  author: string,
  date: string,
  id: string,
): RevisionExportRow => ({ source, subtype, author, date, id });

// ── mergeRevisionRows ─────────────────────────────────────────────

describe('Sprint 335 — mergeRevisionRows', () => {
  it('空 sources → 空 array', () => {
    expect(mergeRevisionRows([])).toEqual([]);
    expect(mergeRevisionRows([[], []])).toEqual([]);
  });

  it('無重複 → 全留', () => {
    const a = [row('run-revision', 'ins', 'A', '2026-05-01', '1')];
    const b = [row('run-revision', 'ins', 'B', '2026-05-02', '2')];
    expect(mergeRevisionRows([a, b])).toHaveLength(2);
  });

  it('完全相同 row → 去重', () => {
    const r = row('run-revision', 'ins', 'A', '2026-05-01', '1');
    expect(mergeRevisionRows([[r], [r]])).toHaveLength(1);
  });

  it('同 author 同 id 不同 subtype → 兩筆都留', () => {
    const a = [row('run-revision', 'ins', 'A', '2026-05-01', '1')];
    const b = [row('run-revision', 'del', 'A', '2026-05-01', '1')];
    expect(mergeRevisionRows([a, b])).toHaveLength(2);
  });

  it('保留第一次出現的順序', () => {
    const a = [row('run-revision', 'ins', 'A', '2026-05-01', '1')];
    const b = [
      row('run-revision', 'ins', 'B', '2026-05-02', '2'),
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
    ];
    const merged = mergeRevisionRows([a, b]);
    expect(merged[0].author).toBe('A');
    expect(merged[1].author).toBe('B');
  });
});

// ── sortByDate ────────────────────────────────────────────────────

describe('Sprint 335 — sortByDate', () => {
  const rows = [
    row('run-revision', 'ins', 'A', '2026-05-03', '1'),
    row('run-revision', 'ins', 'B', '2026-05-01', '2'),
    row('run-revision', 'ins', 'C', '2026-05-02', '3'),
  ];

  it('asc 排序', () => {
    const sorted = sortByDate(rows, 'asc');
    expect(sorted.map((r) => r.date)).toEqual(['2026-05-01', '2026-05-02', '2026-05-03']);
  });

  it('desc 排序', () => {
    const sorted = sortByDate(rows, 'desc');
    expect(sorted.map((r) => r.date)).toEqual(['2026-05-03', '2026-05-02', '2026-05-01']);
  });

  it('預設 asc', () => {
    const sorted = sortByDate(rows);
    expect(sorted[0].date).toBe('2026-05-01');
  });

  it('empty date asc 排最前', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'ins', 'B', '', '2'),
    ];
    expect(sortByDate(r, 'asc')[0].date).toBe('');
  });

  it('empty date desc 排最後', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'ins', 'B', '', '2'),
    ];
    expect(sortByDate(r, 'desc')[1].date).toBe('');
  });

  it('不 mutate 原 array', () => {
    const orig = [...rows];
    sortByDate(rows, 'desc');
    expect(rows).toEqual(orig);
  });
});

// ── groupByAuthor ─────────────────────────────────────────────────

describe('Sprint 335 — groupByAuthor', () => {
  it('依 author 分群', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'ins', 'A', '2026-05-02', '2'),
      row('run-revision', 'ins', 'B', '2026-05-03', '3'),
    ];
    const g = groupByAuthor(r);
    expect(g.get('A')).toHaveLength(2);
    expect(g.get('B')).toHaveLength(1);
  });

  it('空 author → Unknown bucket', () => {
    const r = [row('run-revision', 'ins', '', '2026-05-01', '1')];
    const g = groupByAuthor(r);
    expect(g.get('Unknown')).toHaveLength(1);
  });
});

// ── detectMergeConflicts ──────────────────────────────────────────

describe('Sprint 335 — detectMergeConflicts', () => {
  it('同 author + id + 不同 subtype → conflict', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'del', 'A', '2026-05-01', '1'),
    ];
    const c = detectMergeConflicts(r);
    expect(c).toHaveLength(1);
    expect(c[0].subtypes).toEqual(['del', 'ins']);
  });

  it('同 author + id + 同 subtype → 無 conflict', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'ins', 'A', '2026-05-02', '1'),
    ];
    expect(detectMergeConflicts(r)).toEqual([]);
  });

  it('無 id 不算 conflict', () => {
    const r = [
      row('run-revision', 'ins', 'A', '2026-05-01', ''),
      row('run-revision', 'del', 'A', '2026-05-02', ''),
    ];
    expect(detectMergeConflicts(r)).toEqual([]);
  });
});

// ── summarizeMerge ────────────────────────────────────────────────

describe('Sprint 335 — summarizeMerge', () => {
  it('累計 + 去重 + author 數 + conflict 數', () => {
    const a = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'),
      row('run-revision', 'del', 'B', '2026-05-02', '2'),
    ];
    const b = [
      row('run-revision', 'ins', 'A', '2026-05-01', '1'), // dup
      row('run-revision', 'ins', 'B', '2026-05-02', '2'), // conflict with del
    ];
    const s = summarizeMerge([a, b]);
    expect(s.totalInputRows).toBe(4);
    expect(s.duplicatesRemoved).toBe(1);
    expect(s.mergedRows).toBe(3);
    expect(s.authorCount).toBe(2);
    expect(s.conflictCount).toBe(1);
  });

  it('空 sources → 全 0', () => {
    const s = summarizeMerge([]);
    expect(s.totalInputRows).toBe(0);
    expect(s.mergedRows).toBe(0);
  });
});
