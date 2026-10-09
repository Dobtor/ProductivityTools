/**
 * RevisionStatistics — Sprint 345。
 *
 * Sprint 300/305/310/315/320/325/330/335/340 revision 系列第十輪深推。Sprint 310
 * RevisionDiffSummary 做了 by-author / by-type 計數；本 sprint 補更完整的
 * **churn 統計**（給 dashboard / report 用）：
 *
 *   - net change：ins - del（淨增刪）
 *   - per-author churn：每作者各做了幾筆 ins/del/move
 *   - type distribution：各 subtype 佔比
 *   - activity span：最早 / 最晚修訂日期（ISO 字串）
 *
 * 吃 Sprint 330 RevisionExportRow[]（已扁平化）、純統計。
 *
 * 紀律 #18 scope-down：
 *   - 純 array reduce；不接 doc walk（caller 先用 exportRevisionsAsJson）
 *   - 不轉時區（date ISO 字典序比較）
 *   - 不做 sliding window / 時序 bucket（用 Sprint 325 timeline）
 *
 * 紀律 #21：純函式統計、不污染 production pipeline。
 */

import type { RevisionExportRow } from './RevisionExporter';

export interface NetChange {
  insertions: number;
  deletions: number;
  moves: number;
  propChanges: number;
  /** insertions - deletions */
  net: number;
}

/**
 * 整體淨增刪統計。
 *
 * subtype 對應：
 *   - ins → insertions
 *   - del → deletions
 *   - moveFrom / moveTo → moves
 *   - props → propChanges
 */
export function computeNetChange(rows: ReadonlyArray<RevisionExportRow>): NetChange {
  let insertions = 0;
  let deletions = 0;
  let moves = 0;
  let propChanges = 0;
  for (const r of rows) {
    switch (r.subtype) {
      case 'ins':
        insertions += 1;
        break;
      case 'del':
        deletions += 1;
        break;
      case 'moveFrom':
      case 'moveTo':
        moves += 1;
        break;
      case 'props':
        propChanges += 1;
        break;
    }
  }
  return { insertions, deletions, moves, propChanges, net: insertions - deletions };
}

export interface AuthorChurn {
  author: string;
  insertions: number;
  deletions: number;
  moves: number;
  propChanges: number;
  total: number;
}

/**
 * 每作者 churn。empty author → 'Unknown'。回 array、依 total 降序。
 */
export function computeAuthorChurn(rows: ReadonlyArray<RevisionExportRow>): AuthorChurn[] {
  const map = new Map<string, AuthorChurn>();
  for (const r of rows) {
    const author = r.author === '' ? 'Unknown' : r.author;
    let c = map.get(author);
    if (!c) {
      c = { author, insertions: 0, deletions: 0, moves: 0, propChanges: 0, total: 0 };
      map.set(author, c);
    }
    switch (r.subtype) {
      case 'ins':
        c.insertions += 1;
        break;
      case 'del':
        c.deletions += 1;
        break;
      case 'moveFrom':
      case 'moveTo':
        c.moves += 1;
        break;
      case 'props':
        c.propChanges += 1;
        break;
    }
    c.total += 1;
  }
  return Array.from(map.values()).sort((a, b) => b.total - a.total);
}

export interface TypeDistribution {
  /** subtype → 佔比（0~1）；total=0 時全 0 */
  fractions: Record<string, number>;
  counts: Record<string, number>;
  total: number;
}

/**
 * 各 subtype 計數 + 佔比。
 */
export function computeTypeDistribution(
  rows: ReadonlyArray<RevisionExportRow>,
): TypeDistribution {
  const counts: Record<string, number> = {};
  for (const r of rows) {
    counts[r.subtype] = (counts[r.subtype] ?? 0) + 1;
  }
  const total = rows.length;
  const fractions: Record<string, number> = {};
  for (const k of Object.keys(counts)) {
    fractions[k] = total === 0 ? 0 : counts[k] / total;
  }
  return { fractions, counts, total };
}

export interface ActivitySpan {
  earliest?: string;
  latest?: string;
  /** 有 date 的 row 數 */
  datedCount: number;
}

/**
 * 最早 / 最晚修訂日期（ISO 字串字典序）。忽略 empty date。
 */
export function computeActivitySpan(rows: ReadonlyArray<RevisionExportRow>): ActivitySpan {
  let earliest: string | undefined;
  let latest: string | undefined;
  let datedCount = 0;
  for (const r of rows) {
    if (r.date === '') continue;
    datedCount += 1;
    if (earliest === undefined || r.date < earliest) earliest = r.date;
    if (latest === undefined || r.date > latest) latest = r.date;
  }
  return { earliest, latest, datedCount };
}

/**
 * 一次算齊全部統計（caller 想一口氣拿 report 用）。
 */
export interface RevisionStatisticsReport {
  netChange: NetChange;
  authorChurn: AuthorChurn[];
  typeDistribution: TypeDistribution;
  activitySpan: ActivitySpan;
}

export function buildStatisticsReport(
  rows: ReadonlyArray<RevisionExportRow>,
): RevisionStatisticsReport {
  return {
    netChange: computeNetChange(rows),
    authorChurn: computeAuthorChurn(rows),
    typeDistribution: computeTypeDistribution(rows),
    activitySpan: computeActivitySpan(rows),
  };
}
