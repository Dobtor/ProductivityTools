/**
 * RevisionSessionizer — Sprint 355。
 *
 * Sprint 325 RevisionTimelineBuilder（依固定 granularity 分 bucket）+ Sprint 345
 * RevisionStatistics 之後深推。本 sprint 補 **edit session 分群**：把同一 author
 * 連續、時間間隔小於 threshold 的 revision 視為一次「編輯 session」。
 *
 * 用途：UI 顯示「Alice 在 10:00-10:15 做了 12 處修改」、而非逐筆列。
 *
 * 演算法：
 *   1. 依 author 分組
 *   2. 每組依 date 排序（ISO 字串字典序）
 *   3. 相鄰兩筆時間差 > gapMs → 切新 session
 *
 * 紀律 #18 scope-down：
 *   - date 轉成 epoch ms 比較（需 parseable ISO；不可解析 → 歸 'undated' session）
 *   - 不接 doc walk（caller 先用 exportRevisionsAsJson）
 *   - 不跨 author 合併 session
 *
 * 紀律 #21：純函式分群、不污染 production pipeline。
 */

import type { RevisionExportRow } from './RevisionExporter';

export interface EditSession {
  author: string;
  /** session 內 row（依時間排序） */
  rows: RevisionExportRow[];
  /** 最早 / 最晚 date（ISO 字串）；undated session 為 undefined */
  startDate?: string;
  endDate?: string;
  /** session 內 row 數 */
  count: number;
}

export interface SessionizeOptions {
  /** 相鄰修訂間隔超過此毫秒數 → 切新 session；預設 5 分鐘 */
  gapMs?: number;
}

/** 把 ISO date 字串轉 epoch ms；不可解析 → null。 */
function parseMs(date: string): number | null {
  if (date === '') return null;
  const t = Date.parse(date);
  return Number.isNaN(t) ? null : t;
}

/**
 * 把 rows 分成 edit sessions。
 *
 * - 同 author 連續、gap <= gapMs → 同 session
 * - 不可解析 date 的 row → 各 author 一個 'undated' session（合在一起）
 * - empty author → 'Unknown'
 */
export function sessionize(
  rows: ReadonlyArray<RevisionExportRow>,
  opts: SessionizeOptions = {},
): EditSession[] {
  const gapMs = opts.gapMs ?? 5 * 60 * 1000;

  // 依 author 分組
  const byAuthor = new Map<string, RevisionExportRow[]>();
  for (const r of rows) {
    const author = r.author === '' ? 'Unknown' : r.author;
    let arr = byAuthor.get(author);
    if (!arr) {
      arr = [];
      byAuthor.set(author, arr);
    }
    arr.push(r);
  }

  const sessions: EditSession[] = [];
  for (const [author, authorRows] of byAuthor) {
    const dated: Array<{ row: RevisionExportRow; ms: number }> = [];
    const undated: RevisionExportRow[] = [];
    for (const r of authorRows) {
      const ms = parseMs(r.date);
      if (ms === null) undated.push(r);
      else dated.push({ row: r, ms });
    }
    dated.sort((a, b) => a.ms - b.ms);

    let current: EditSession | null = null;
    let lastMs = -Infinity;
    for (const { row, ms } of dated) {
      if (current === null || ms - lastMs > gapMs) {
        current = {
          author,
          rows: [row],
          startDate: row.date,
          endDate: row.date,
          count: 1,
        };
        sessions.push(current);
      } else {
        current.rows.push(row);
        current.endDate = row.date;
        current.count += 1;
      }
      lastMs = ms;
    }

    if (undated.length > 0) {
      sessions.push({
        author,
        rows: undated,
        count: undated.length,
      });
    }
  }

  return sessions;
}

export interface SessionizeSummary {
  totalSessions: number;
  totalRows: number;
  /** 各 author 的 session 數 */
  sessionsPerAuthor: Map<string, number>;
  /** 最大 session 的 row 數 */
  largestSessionSize: number;
}

export function summarizeSessions(sessions: ReadonlyArray<EditSession>): SessionizeSummary {
  const sessionsPerAuthor = new Map<string, number>();
  let totalRows = 0;
  let largest = 0;
  for (const s of sessions) {
    sessionsPerAuthor.set(s.author, (sessionsPerAuthor.get(s.author) ?? 0) + 1);
    totalRows += s.count;
    if (s.count > largest) largest = s.count;
  }
  return {
    totalSessions: sessions.length,
    totalRows,
    sessionsPerAuthor,
    largestSessionSize: largest,
  };
}
