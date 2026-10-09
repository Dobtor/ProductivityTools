/**
 * RevisionBatchAction — Sprint 340。
 *
 * Sprint 300/305/310/315/320/325/330/335 revision 系列第九輪深推。Sprint 300
 * accept/reject 是「一次性」執行；本 sprint 補：
 *
 *   - **dry-run plan**：在 apply 前列出「會影響哪幾筆 revision」
 *   - **predicate composition**：合多個 predicate（AND / OR / NOT）
 *   - **apply plan**：把 plan 真正套到 doc 上
 *
 * 場景：UI accept/reject 面板（規畫書 §5.4）的批次操作 + 「請先 review 影響範圍」
 * 介面用。
 *
 * 紀律 #18 scope-down：
 *   - 不接 OWL UI（紀律 #21）
 *   - 不處理 partial apply（plan 算出後一次性套用、失敗 caller 自負）
 *   - 不解 revision conflict（用 Sprint 315 / 335 conflict report 自查）
 *
 * 紀律 #21：純函式 batch planner；caller 自決何時 apply。
 */

import type { DocumentNode, RunRevision, TrackChangeMeta } from '../ast/types';
import {
  acceptRevisions,
  rejectRevisions,
  listRevisions,
  type RevisionPredicate,
  type RevisionListEntry,
} from './accept_reject';

export type BatchMode = 'accept' | 'reject';

export interface BatchPlan {
  mode: BatchMode;
  /** 命中的 revision entries（list 順序） */
  affected: RevisionListEntry[];
  /** 各 subtype 命中數 */
  bySource: {
    'run-revision': number;
    rPrChange: number;
    pPrChange: number;
    cellIns: number;
    cellDel: number;
    cellMerge: number;
  };
  /** 共 N 筆 */
  totalAffected: number;
}

/**
 * 不動 doc、回 plan：哪幾筆 revision 會被 batch accept/reject 影響。
 */
export function planBatch(
  doc: DocumentNode,
  mode: BatchMode,
  predicate?: RevisionPredicate,
): BatchPlan {
  const all = listRevisions(doc);
  const affected = predicate ? all.filter((e) => predicate(e.meta)) : all;
  const bySource: BatchPlan['bySource'] = {
    'run-revision': 0,
    rPrChange: 0,
    pPrChange: 0,
    cellIns: 0,
    cellDel: 0,
    cellMerge: 0,
  };
  for (const e of affected) bySource[e.source] += 1;
  return { mode, affected, bySource, totalAffected: affected.length };
}

/**
 * 套 plan 到 doc。內部呼叫 Sprint 300 acceptRevisions / rejectRevisions。
 *
 * 紀律 #18：plan.predicate 沒被直接保留在 BatchPlan 內、caller 必須把同樣的
 * predicate 也傳給 applyBatch、確保 plan/apply 對齊。
 */
export function applyBatch(
  doc: DocumentNode,
  mode: BatchMode,
  predicate?: RevisionPredicate,
): DocumentNode {
  if (mode === 'accept') {
    return acceptRevisions(doc, predicate ? { predicate } : undefined);
  }
  return rejectRevisions(doc, predicate ? { predicate } : undefined);
}

// ── predicate composition ─────────────────────────────────────────

/** 全部 predicate 都通過才算命中。 */
export function andP(...preds: RevisionPredicate[]): RevisionPredicate {
  return (meta) => preds.every((p) => p(meta));
}

/** 任一 predicate 通過就算命中。 */
export function orP(...preds: RevisionPredicate[]): RevisionPredicate {
  return (meta) => preds.some((p) => p(meta));
}

/** Negate。 */
export function notP(p: RevisionPredicate): RevisionPredicate {
  return (meta) => !p(meta);
}

// ── 常用 predicate factory（與 Sprint 320 對齊概念、本 module 自包裝） ──

export function byAuthor(author: string): RevisionPredicate {
  return (meta) => (meta as TrackChangeMeta).author === author;
}

export function byId(id: number): RevisionPredicate {
  return (meta) => (meta as TrackChangeMeta).id === id;
}

export function byIdSet(ids: ReadonlyArray<number>): RevisionPredicate {
  const set = new Set(ids);
  return (meta) => {
    const i = (meta as TrackChangeMeta).id;
    return i !== undefined && set.has(i);
  };
}

export function byRunType(type: RunRevision['type']): RevisionPredicate {
  return (meta) => (meta as RunRevision).type === type;
}

/**
 * Plan summary 供 caller 顯示「即將影響 N 筆、X 筆 run-revision、Y 筆 prop 變更」。
 */
export interface PlanSummary {
  mode: BatchMode;
  totalAffected: number;
  hasRunRevisions: boolean;
  hasPropChanges: boolean;
  hasCellRevisions: boolean;
}

export function summarizePlan(plan: BatchPlan): PlanSummary {
  return {
    mode: plan.mode,
    totalAffected: plan.totalAffected,
    hasRunRevisions: plan.bySource['run-revision'] > 0,
    hasPropChanges:
      plan.bySource.pPrChange > 0 || plan.bySource.rPrChange > 0,
    hasCellRevisions:
      plan.bySource.cellIns > 0 ||
      plan.bySource.cellDel > 0 ||
      plan.bySource.cellMerge > 0,
  };
}
