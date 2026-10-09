/**
 * Sprint 350 — ④ deeper¹²：RevisionValidator。
 *
 * Sprint 330 RevisionExportRow 之上做 integrity 驗證：orphan move / dup id /
 * missing fields。
 *
 * 紀律 #18：純驗證不修復；move 配對只比 id；不接 doc walk。
 */
import { describe, expect, it } from 'vitest';

import {
  validateRevisions,
  buildValidationReport,
} from '../../static/src/core/ooxml/revision/RevisionValidator';
import type { RevisionExportRow } from '../../static/src/core/ooxml/revision/RevisionExporter';

const row = (
  subtype: RevisionExportRow['subtype'],
  author: string,
  id: string,
  date = '',
  source: RevisionExportRow['source'] = 'run-revision',
): RevisionExportRow => ({ source, subtype, author, date, id });

// ── orphan move ────────────────────────────────────────────────────

describe('Sprint 350 — orphan move', () => {
  it('moveFrom + moveTo 成對 → 無 issue', () => {
    const rows = [row('moveFrom', 'A', '1'), row('moveTo', 'A', '1')];
    expect(validateRevisions(rows)).toEqual([]);
  });

  it('moveFrom 無 moveTo → orphan error', () => {
    const rows = [row('moveFrom', 'A', '1')];
    const issues = validateRevisions(rows);
    expect(issues).toHaveLength(1);
    expect(issues[0].kind).toBe('orphan-move');
    expect(issues[0].severity).toBe('error');
  });

  it('moveTo 無 moveFrom → orphan error', () => {
    const rows = [row('moveTo', 'A', '5')];
    expect(validateRevisions(rows)[0].kind).toBe('orphan-move');
  });

  it('move 無 id → orphan error', () => {
    const rows = [row('moveFrom', 'A', '')];
    const issues = validateRevisions(rows);
    expect(issues[0].kind).toBe('orphan-move');
    expect(issues[0].message).toContain('without w:id');
  });

  it('ins/del 不參與 move 配對', () => {
    const rows = [row('ins', 'A', '1'), row('del', 'A', '2')];
    expect(validateRevisions(rows)).toEqual([]);
  });
});

// ── duplicate id ───────────────────────────────────────────────────

describe('Sprint 350 — duplicate id', () => {
  it('同 author+id 不同 subtype → error', () => {
    const rows = [row('ins', 'A', '1'), row('del', 'A', '1')];
    const issues = validateRevisions(rows);
    const dup = issues.find((i) => i.kind === 'duplicate-id');
    expect(dup).toBeDefined();
    expect(dup?.message).toContain('del, ins');
  });

  it('同 author+id 同 subtype → 無 dup issue', () => {
    const rows = [row('ins', 'A', '1'), row('ins', 'A', '1')];
    expect(validateRevisions(rows).filter((i) => i.kind === 'duplicate-id')).toEqual([]);
  });

  it('不同 author 同 id → 不算 dup', () => {
    const rows = [row('ins', 'A', '1'), row('del', 'B', '1')];
    expect(validateRevisions(rows).filter((i) => i.kind === 'duplicate-id')).toEqual([]);
  });

  it('無 id → 不參與 dup 偵測', () => {
    const rows = [row('ins', 'A', ''), row('del', 'A', '')];
    expect(validateRevisions(rows).filter((i) => i.kind === 'duplicate-id')).toEqual([]);
  });
});

// ── missing fields ─────────────────────────────────────────────────

describe('Sprint 350 — missing fields', () => {
  it('requireAuthor → 缺 author warning', () => {
    const rows = [row('ins', '', '1', '2026-05-01')];
    const issues = validateRevisions(rows, { requireAuthor: true });
    const w = issues.find((i) => i.kind === 'missing-author');
    expect(w?.severity).toBe('warning');
  });

  it('預設不檢查 author', () => {
    const rows = [row('ins', '', '1', '2026-05-01')];
    expect(validateRevisions(rows).filter((i) => i.kind === 'missing-author')).toEqual([]);
  });

  it('requireDate → 缺 date warning', () => {
    const rows = [row('ins', 'A', '1', '')];
    const issues = validateRevisions(rows, { requireDate: true });
    expect(issues.find((i) => i.kind === 'missing-date')?.severity).toBe('warning');
  });
});

// ── buildValidationReport ─────────────────────────────────────────

describe('Sprint 350 — buildValidationReport', () => {
  it('無 error → valid=true', () => {
    const rows = [row('moveFrom', 'A', '1'), row('moveTo', 'A', '1')];
    const report = buildValidationReport(rows);
    expect(report.valid).toBe(true);
    expect(report.errorCount).toBe(0);
  });

  it('有 orphan → valid=false', () => {
    const rows = [row('moveFrom', 'A', '1')];
    const report = buildValidationReport(rows);
    expect(report.valid).toBe(false);
    expect(report.errorCount).toBe(1);
  });

  it('warning 不影響 valid', () => {
    const rows = [row('ins', '', '1', '')];
    const report = buildValidationReport(rows, { requireAuthor: true, requireDate: true });
    expect(report.valid).toBe(true);
    expect(report.warningCount).toBe(2);
  });

  it('混合 error + warning', () => {
    const rows = [row('moveFrom', 'A', ''), row('ins', '', '2', '')];
    const report = buildValidationReport(rows, { requireAuthor: true });
    expect(report.errorCount).toBeGreaterThanOrEqual(1);
    expect(report.warningCount).toBeGreaterThanOrEqual(1);
    expect(report.valid).toBe(false);
  });

  it('空 rows → valid=true', () => {
    expect(buildValidationReport([]).valid).toBe(true);
  });
});
