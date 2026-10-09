/**
 * RevisionReviewSession — Sprint 305。
 *
 * Sprint 300 補了 accept/reject pure-fn helpers；本 sprint 補 UI-agnostic
 * 「逐筆審 revision」狀態機，介於 pure-fn 與真實 UI binding 之間：
 *
 *   Caller flow:
 *     const session = new RevisionReviewSession(doc);
 *     while (!session.isDone()) {
 *       const cur = session.current();      // 看當前修訂
 *       const choice = await uiAskUser(cur);
 *       if (choice === 'accept') session.acceptCurrent();
 *       else if (choice === 'reject') session.rejectCurrent();
 *       else session.skipCurrent();
 *     }
 *     const finalDoc = session.getDocument();
 *
 * 紀律 #18 scope-down：
 *   - UI binding 留 future sprint（OWL component / vanilla JS / React 都可消費此 session）
 *   - 不支援「一鍵 accept-all」的 batch operation（caller 自行 loop；或直接呼叫
 *     Sprint 300 acceptRevisions）；session 為「逐筆 review」模式
 *   - 不支援 undo / redo（caller wrap session 自管歷史）
 *
 * 紀律 #21：純 stateful class、不污染既有 production 路徑、caller 顯式建立才生效。
 */

import type { DocumentNode } from '../ast/types';
import {
  acceptRevisions,
  rejectRevisions,
  listRevisions,
  type RevisionListEntry,
  type AcceptRejectOptions,
} from './accept_reject';

export type ReviewChoice = 'accept' | 'reject' | 'skip';

export interface ReviewSessionStats {
  total: number;
  accepted: number;
  rejected: number;
  skipped: number;
  /** 還剩多少 revision 未審 */
  remaining: number;
}

/**
 * 逐筆審 revision 狀態機。
 *
 * - `current()`：當前待審 revision；isDone() 時回 null
 * - `acceptCurrent()` / `rejectCurrent()` / `skipCurrent()`：分別處理當前 + 推進游標
 * - `getDocument()`：拿回累積 accept / reject 處理後的新 DocumentNode
 */
export class RevisionReviewSession {
  private doc: DocumentNode;
  private readonly entries: RevisionListEntry[];
  private cursor = 0;
  private acceptedIds = new Set<number>();
  private rejectedIds = new Set<number>();
  private skippedIds = new Set<number>();

  constructor(doc: DocumentNode) {
    this.doc = doc;
    this.entries = listRevisions(doc);
  }

  /** 當前 cursor 指向的 revision entry；isDone() 時回 null。 */
  current(): RevisionListEntry | null {
    if (this.isDone()) return null;
    return this.entries[this.cursor];
  }

  /** 完整 review queue（不變動）。 */
  all(): readonly RevisionListEntry[] {
    return this.entries;
  }

  /** 是否所有 revision 都已處理完（accept/reject/skip 任一動作即推進 cursor）。 */
  isDone(): boolean {
    return this.cursor >= this.entries.length;
  }

  /**
   * 接受當前 revision、apply 到 doc、推進 cursor。
   *
   * 若 entry.meta.id 已知（多數 revision 帶 id）→ 用 id predicate 精準 apply。
   * 若 entry.meta.id 為 undefined → fallback by reference（apply 全部 type 相符
   * 但 id 為 undefined 的 metadata；極少 fixture 走此路徑）。
   */
  acceptCurrent(): void {
    const entry = this.requireCurrent();
    this.doc = acceptRevisions(this.doc, this.buildPredicateOpts(entry));
    if (entry.meta.id !== undefined) this.acceptedIds.add(entry.meta.id);
    this.cursor++;
  }

  rejectCurrent(): void {
    const entry = this.requireCurrent();
    this.doc = rejectRevisions(this.doc, this.buildPredicateOpts(entry));
    if (entry.meta.id !== undefined) this.rejectedIds.add(entry.meta.id);
    this.cursor++;
  }

  /** 跳過當前 revision、不改 doc、推進 cursor。 */
  skipCurrent(): void {
    const entry = this.requireCurrent();
    if (entry.meta.id !== undefined) this.skippedIds.add(entry.meta.id);
    this.cursor++;
  }

  /** 累積 accept / reject 後的最終 DocumentNode。 */
  getDocument(): DocumentNode {
    return this.doc;
  }

  /** 統計：總筆數、已 accept / reject / skip、剩餘。 */
  stats(): ReviewSessionStats {
    return {
      total: this.entries.length,
      accepted: this.acceptedIds.size,
      rejected: this.rejectedIds.size,
      skipped: this.skippedIds.size,
      remaining: Math.max(0, this.entries.length - this.cursor),
    };
  }

  /** Reset cursor 與計數（測試 / re-review 用）；不還原 doc 已 applied 的修訂。 */
  resetCursor(): void {
    this.cursor = 0;
    this.acceptedIds.clear();
    this.rejectedIds.clear();
    this.skippedIds.clear();
  }

  private requireCurrent(): RevisionListEntry {
    if (this.isDone()) {
      throw new Error('[RevisionReviewSession] no current revision; session done');
    }
    return this.entries[this.cursor];
  }

  private buildPredicateOpts(entry: RevisionListEntry): AcceptRejectOptions {
    const targetId = entry.meta.id;
    return {
      predicate: (meta) => {
        // by id 精準對位（多數 fixture 走此路徑）
        if (targetId !== undefined && meta.id === targetId) return true;
        // id 為 undefined 時 fallback：只 apply 完全相符 reference
        if (targetId === undefined && meta === entry.meta) return true;
        return false;
      },
    };
  }
}
