/**
 * Sprint 345 — ④ deeper¹¹：RevisionStatistics。
 *
 * Sprint 330 RevisionExportRow 之上算 churn / net change / type dist / activity span。
 *
 * 紀律 #18：純 array reduce；不接 doc walk；無時區轉換。
 */
import { describe, expect, it } from 'vitest';

import {
  computeNetChange,
  computeAuthorChurn,
  computeTypeDistribution,
  computeActivitySpan,
  buildStatisticsReport,
} from '../../static/src/core/ooxml/revision/RevisionStatistics';
import type { RevisionExportRow } from '../../static/src/core/ooxml/revision/RevisionExporter';

const row = (
  subtype: RevisionExportRow['subtype'],
  author: string,
  date: string,
  source: RevisionExportRow['source'] = 'run-revision',
  id = '1',
): RevisionExportRow => ({ source, subtype, author, date, id });

// ── computeNetChange ───────────────────────────────────────────────

describe('Sprint 345 — computeNetChange', () => {
  it('ins - del = net', () => {
    const rows = [
      row('ins', 'A', '2026-05-01'),
      row('ins', 'A', '2026-05-02'),
      row('del', 'B', '2026-05-03'),
    ];
    const nc = computeNetChange(rows);
    expect(nc.insertions).toBe(2);
    expect(nc.deletions).toBe(1);
    expect(nc.net).toBe(1);
  });

  it('moveFrom/moveTo → moves', () => {
    const rows = [row('moveFrom', 'A', ''), row('moveTo', 'A', '')];
    expect(computeNetChange(rows).moves).toBe(2);
  });

  it('props → propChanges', () => {
    const rows = [row('props', 'A', '', 'pPrChange')];
    expect(computeNetChange(rows).propChanges).toBe(1);
  });

  it('空 → 全 0', () => {
    expect(computeNetChange([])).toEqual({
      insertions: 0,
      deletions: 0,
      moves: 0,
      propChanges: 0,
      net: 0,
    });
  });
});

// ── computeAuthorChurn ─────────────────────────────────────────────

describe('Sprint 345 — computeAuthorChurn', () => {
  it('每作者各計 + total 降序', () => {
    const rows = [
      row('ins', 'Alice', '2026-05-01'),
      row('ins', 'Alice', '2026-05-02'),
      row('del', 'Alice', '2026-05-03'),
      row('ins', 'Bob', '2026-05-04'),
    ];
    const churn = computeAuthorChurn(rows);
    expect(churn[0].author).toBe('Alice');
    expect(churn[0].total).toBe(3);
    expect(churn[0].insertions).toBe(2);
    expect(churn[0].deletions).toBe(1);
    expect(churn[1].author).toBe('Bob');
  });

  it('empty author → Unknown', () => {
    const churn = computeAuthorChurn([row('ins', '', '2026-05-01')]);
    expect(churn[0].author).toBe('Unknown');
  });

  it('空 → 空 array', () => {
    expect(computeAuthorChurn([])).toEqual([]);
  });
});

// ── computeTypeDistribution ───────────────────────────────────────

describe('Sprint 345 — computeTypeDistribution', () => {
  it('計數 + 佔比', () => {
    const rows = [
      row('ins', 'A', ''),
      row('ins', 'A', ''),
      row('del', 'A', ''),
      row('del', 'A', ''),
    ];
    const dist = computeTypeDistribution(rows);
    expect(dist.total).toBe(4);
    expect(dist.counts.ins).toBe(2);
    expect(dist.fractions.ins).toBeCloseTo(0.5);
    expect(dist.fractions.del).toBeCloseTo(0.5);
  });

  it('空 → total=0、fractions 全空', () => {
    const dist = computeTypeDistribution([]);
    expect(dist.total).toBe(0);
    expect(Object.keys(dist.fractions)).toHaveLength(0);
  });
});

// ── computeActivitySpan ────────────────────────────────────────────

describe('Sprint 345 — computeActivitySpan', () => {
  it('最早 / 最晚 date', () => {
    const rows = [
      row('ins', 'A', '2026-05-03'),
      row('ins', 'A', '2026-05-01'),
      row('ins', 'A', '2026-05-02'),
    ];
    const span = computeActivitySpan(rows);
    expect(span.earliest).toBe('2026-05-01');
    expect(span.latest).toBe('2026-05-03');
    expect(span.datedCount).toBe(3);
  });

  it('忽略 empty date', () => {
    const rows = [row('ins', 'A', ''), row('ins', 'A', '2026-05-01')];
    const span = computeActivitySpan(rows);
    expect(span.earliest).toBe('2026-05-01');
    expect(span.datedCount).toBe(1);
  });

  it('全無 date → undefined', () => {
    const span = computeActivitySpan([row('ins', 'A', '')]);
    expect(span.earliest).toBeUndefined();
    expect(span.latest).toBeUndefined();
    expect(span.datedCount).toBe(0);
  });
});

// ── buildStatisticsReport ─────────────────────────────────────────

describe('Sprint 345 — buildStatisticsReport', () => {
  it('一次算齊四項', () => {
    const rows = [
      row('ins', 'Alice', '2026-05-01'),
      row('del', 'Bob', '2026-05-02'),
    ];
    const report = buildStatisticsReport(rows);
    expect(report.netChange.net).toBe(0);
    expect(report.authorChurn).toHaveLength(2);
    expect(report.typeDistribution.total).toBe(2);
    expect(report.activitySpan.earliest).toBe('2026-05-01');
  });
});
