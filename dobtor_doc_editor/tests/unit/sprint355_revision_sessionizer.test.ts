/**
 * Sprint 355 — ④ deeper¹³：RevisionSessionizer。
 *
 * Sprint 325 timeline + Sprint 345 statistics 之後深推。依 author + time-gap
 * 把 revision 分成 edit sessions。
 *
 * 紀律 #18：純函式分群；date 轉 epoch ms；不接 doc walk；不跨 author 合併。
 */
import { describe, expect, it } from 'vitest';

import {
  sessionize,
  summarizeSessions,
} from '../../static/src/core/ooxml/revision/RevisionSessionizer';
import type { RevisionExportRow } from '../../static/src/core/ooxml/revision/RevisionExporter';

const row = (
  author: string,
  date: string,
  id = '1',
  subtype: RevisionExportRow['subtype'] = 'ins',
): RevisionExportRow => ({ source: 'run-revision', subtype, author, date, id });

// ── sessionize ─────────────────────────────────────────────────────

describe('Sprint 355 — sessionize', () => {
  it('間隔小 → 同 session', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T10:02:00Z'),
      row('Alice', '2026-05-28T10:04:00Z'),
    ];
    const sessions = sessionize(rows, { gapMs: 5 * 60 * 1000 });
    expect(sessions).toHaveLength(1);
    expect(sessions[0].count).toBe(3);
    expect(sessions[0].startDate).toBe('2026-05-28T10:00:00Z');
    expect(sessions[0].endDate).toBe('2026-05-28T10:04:00Z');
  });

  it('間隔大 → 切新 session', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T11:00:00Z'), // 1hr gap > 5min
    ];
    const sessions = sessionize(rows, { gapMs: 5 * 60 * 1000 });
    expect(sessions).toHaveLength(2);
  });

  it('不同 author → 各自 session', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Bob', '2026-05-28T10:01:00Z'),
    ];
    const sessions = sessionize(rows);
    expect(sessions).toHaveLength(2);
    const authors = sessions.map((s) => s.author).sort();
    expect(authors).toEqual(['Alice', 'Bob']);
  });

  it('排序：亂序輸入 → session 內依時間排', () => {
    const rows = [
      row('Alice', '2026-05-28T10:04:00Z'),
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T10:02:00Z'),
    ];
    const s = sessionize(rows)[0];
    expect(s.rows.map((r) => r.date)).toEqual([
      '2026-05-28T10:00:00Z',
      '2026-05-28T10:02:00Z',
      '2026-05-28T10:04:00Z',
    ]);
  });

  it('empty author → Unknown', () => {
    const sessions = sessionize([row('', '2026-05-28T10:00:00Z')]);
    expect(sessions[0].author).toBe('Unknown');
  });

  it('undated row → 各 author 一個 undated session', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', ''),
      row('Alice', 'not-a-date'),
    ];
    const sessions = sessionize(rows);
    // 1 dated session + 1 undated session
    expect(sessions).toHaveLength(2);
    const undated = sessions.find((s) => s.startDate === undefined);
    expect(undated?.count).toBe(2);
  });

  it('恰好等於 gap → 同 session（> 才切）', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T10:05:00Z'), // 正好 5min
    ];
    const sessions = sessionize(rows, { gapMs: 5 * 60 * 1000 });
    expect(sessions).toHaveLength(1);
  });

  it('空 rows → 空 sessions', () => {
    expect(sessionize([])).toEqual([]);
  });

  it('預設 gap = 5 分鐘', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T10:06:00Z'), // 6min > 5min default
    ];
    expect(sessionize(rows)).toHaveLength(2);
  });
});

// ── summarizeSessions ──────────────────────────────────────────────

describe('Sprint 355 — summarizeSessions', () => {
  it('總 session / row / per-author / largest', () => {
    const rows = [
      row('Alice', '2026-05-28T10:00:00Z'),
      row('Alice', '2026-05-28T10:02:00Z'),
      row('Alice', '2026-05-28T12:00:00Z'), // 新 session
      row('Bob', '2026-05-28T10:00:00Z'),
    ];
    const sessions = sessionize(rows);
    const sum = summarizeSessions(sessions);
    expect(sum.totalRows).toBe(4);
    expect(sum.totalSessions).toBe(3); // Alice 2 + Bob 1
    expect(sum.sessionsPerAuthor.get('Alice')).toBe(2);
    expect(sum.sessionsPerAuthor.get('Bob')).toBe(1);
    expect(sum.largestSessionSize).toBe(2);
  });

  it('空 → 全 0', () => {
    const sum = summarizeSessions([]);
    expect(sum.totalSessions).toBe(0);
    expect(sum.totalRows).toBe(0);
    expect(sum.largestSessionSize).toBe(0);
  });
});
