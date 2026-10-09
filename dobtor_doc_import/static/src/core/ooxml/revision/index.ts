/**
 * Revision module — Sprint 300。
 *
 * AST 追蹤修訂 accept/reject pure-fn helpers。詳見 accept_reject.ts 檔頭。
 */
export {
  acceptRevisions,
  rejectRevisions,
  acceptParagraphRevisions,
  rejectParagraphRevisions,
  listRevisions,
} from './accept_reject';
export type {
  AcceptRejectOptions,
  RevisionPredicate,
  RevisionListEntry,
} from './accept_reject';

// Sprint 305：逐筆審 revision 狀態機（UI-agnostic）
export { RevisionReviewSession } from './RevisionReviewSession';
export type { ReviewChoice, ReviewSessionStats } from './RevisionReviewSession';

// Sprint 310：人類可讀 revision diff summary（by author / by type / markdown）
export {
  summarizeByAuthor,
  summarizeByType,
  formatSummaryMarkdown,
} from './RevisionDiffSummary';
export type { AuthorSummary, TypeSummary } from './RevisionDiffSummary';

// Sprint 315：revision 衝突偵測
export {
  detectConflicts,
  detectConflictsInParagraph,
  summarizeConflicts,
} from './RevisionConflictDetector';
export type { ConflictKind, ConflictReport } from './RevisionConflictDetector';

// Sprint 320：filtered preview view + predicate factories
export {
  filterView,
  summarizeFilterView,
  previewAccepted,
  predicateByAuthor,
  predicateByIds,
  predicateIdBefore,
} from './RevisionFilter';
export type {
  RevisionFilterStatus,
  FilteredRevisionEntry,
  FilterViewOptions,
  FilterStats,
} from './RevisionFilter';

// Sprint 325：revision timeline buckets
export {
  buildTimeline,
  summarizeTimeline,
} from './RevisionTimelineBuilder';
export type {
  TimelineGranularity,
  TimelineBucket,
  BuildTimelineOptions,
  TimelineStats,
} from './RevisionTimelineBuilder';

// Sprint 330：JSON/CSV exporter for external audit tools
export {
  exportRevisionsAsJson,
  exportRevisionsAsCsv,
  escapeCsvField,
  summarizeExport,
} from './RevisionExporter';
export type {
  RevisionExportRow,
  ExportSummary,
} from './RevisionExporter';

// Sprint 335：multi-source merger + 去重 + sort + group + conflict
export {
  mergeRevisionRows,
  sortByDate,
  groupByAuthor,
  detectMergeConflicts,
  summarizeMerge,
} from './RevisionMerger';
export type { MergeConflict, MergeSummary } from './RevisionMerger';

// Sprint 340：batch action planner（dry-run + predicate composition）
export {
  planBatch,
  applyBatch,
  andP,
  orP,
  notP,
  byAuthor,
  byId,
  byIdSet,
  byRunType,
  summarizePlan,
} from './RevisionBatchAction';
export type { BatchMode, BatchPlan, PlanSummary } from './RevisionBatchAction';

// Sprint 345：churn / net change / type distribution / activity span 統計
export {
  computeNetChange,
  computeAuthorChurn,
  computeTypeDistribution,
  computeActivitySpan,
  buildStatisticsReport,
} from './RevisionStatistics';
export type {
  NetChange,
  AuthorChurn,
  TypeDistribution,
  ActivitySpan,
  RevisionStatisticsReport,
} from './RevisionStatistics';

// Sprint 350：integrity validator（orphan move / dup id / missing fields）
export {
  validateRevisions,
  buildValidationReport,
} from './RevisionValidator';
export type {
  ValidationSeverity,
  ValidationIssue,
  ValidateOptions,
  ValidationReport,
} from './RevisionValidator';

// Sprint 355：edit session 分群（author + time-gap）
export {
  sessionize,
  summarizeSessions,
} from './RevisionSessionizer';
export type {
  EditSession,
  SessionizeOptions,
  SessionizeSummary,
} from './RevisionSessionizer';
