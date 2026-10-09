/**
 * RevisionFilter — Sprint 320。
 *
 * Sprint 300/305/310/315 revision 系列第五輪深推。本 sprint 補：
 * **預覽 view**——caller 想看「如果只接受 Alice 的修訂、會長什麼樣？」
 * 但不真實 apply。
 *
 * 跟 Sprint 300 acceptRevisions 不同：
 *   - acceptRevisions 是 mutation snapshot（產出新 DocumentNode、永久變動）
 *   - filterView 是 preview-only（不變動 doc、只 mark 哪些 revision 該顯示為
 *     accepted / rejected / pending）
 *
 * 用途：
 *   - UI side-by-side 比較「全 accept Alice」vs「全 accept Bob」結果
 *   - PR-style diff 顯示（每個 revision 加上 status：will-accept / will-reject / pending）
 *
 * 範圍：
 *   - `filterView(doc, predicate)` → 列舉 revision + 標 status
 *   - `previewAccepted(doc, predicate)` → 直接呼叫 acceptRevisions、只 apply 命中的
 *
 * 紀律 #18 scope-down：
 *   - filterView 不展開 inline diff（caller 自管 UI 渲染）
 *   - 不做「partial accept」（某 run 一半 accept 一半 reject）
 */

import type { DocumentNode } from '../ast/types';
import { acceptRevisions, listRevisions, type RevisionListEntry, type RevisionPredicate } from './accept_reject';

export type RevisionFilterStatus = 'will-accept' | 'will-reject' | 'pending';

export interface FilteredRevisionEntry extends RevisionListEntry {
  status: RevisionFilterStatus;
}

export interface FilterViewOptions {
  /** 命中此 predicate 的 revision 標 'will-accept'，否則 'pending'。 */
  acceptIf?: RevisionPredicate;
  /** 命中此 predicate 的 revision 標 'will-reject'，否則保持原 status。 */
  rejectIf?: RevisionPredicate;
}

/**
 * 不變動 doc、把每個 revision 標 status：
 *
 *   - acceptIf 命中 → 'will-accept'
 *   - rejectIf 命中（且不在 acceptIf）→ 'will-reject'
 *   - 都不命中 → 'pending'
 *
 * 兩 predicate 都沒給 → 全部 'pending'。
 */
export function filterView(doc: DocumentNode, opts: FilterViewOptions = {}): FilteredRevisionEntry[] {
  const entries = listRevisions(doc);
  return entries.map((entry) => {
    if (opts.acceptIf && opts.acceptIf(entry.meta)) {
      return { ...entry, status: 'will-accept' };
    }
    if (opts.rejectIf && opts.rejectIf(entry.meta)) {
      return { ...entry, status: 'will-reject' };
    }
    return { ...entry, status: 'pending' };
  });
}

/**
 * 統計 filtered view 的 status 分佈。
 */
export interface FilterStats {
  total: number;
  willAccept: number;
  willReject: number;
  pending: number;
}

export function summarizeFilterView(entries: ReadonlyArray<FilteredRevisionEntry>): FilterStats {
  let willAccept = 0;
  let willReject = 0;
  let pending = 0;
  for (const e of entries) {
    if (e.status === 'will-accept') willAccept++;
    else if (e.status === 'will-reject') willReject++;
    else pending++;
  }
  return { total: entries.length, willAccept, willReject, pending };
}

/**
 * 直接套用 filter → 產出新 DocumentNode（acceptRevisions wrap、只 apply 命中的）。
 *
 * 比 acceptRevisions 多一層 caller-friendly API：傳 predicate、不需要 wrap 在 options。
 */
export function previewAccepted(doc: DocumentNode, predicate: RevisionPredicate): DocumentNode {
  return acceptRevisions(doc, { predicate });
}

/**
 * 常用 predicate 工廠：「只 accept 此 author 的修訂」。
 */
export function predicateByAuthor(author: string): RevisionPredicate {
  return (meta) => meta.author === author;
}

/**
 * 常用 predicate 工廠：「只 accept id 在此集合內的修訂」。
 */
export function predicateByIds(ids: ReadonlyArray<number>): RevisionPredicate {
  const set = new Set(ids);
  return (meta) => meta.id !== undefined && set.has(meta.id);
}

/**
 * 常用 predicate 工廠：「只 accept id 小於閾值的修訂」（如：accept 老的、留新的待看）。
 */
export function predicateIdBefore(threshold: number): RevisionPredicate {
  return (meta) => meta.id !== undefined && meta.id < threshold;
}
