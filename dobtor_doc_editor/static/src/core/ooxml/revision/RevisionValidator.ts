/**
 * RevisionValidator — Sprint 350。
 *
 * Sprint 300/305/310/315/320/325/330/335/340/345 revision 系列第十一輪深推。
 * 前面都在「使用」revision；本 sprint 補 **integrity 驗證**：
 *
 *   - orphan move：moveFrom 沒有對應 moveTo（或反之）— OOXML §17.13.5.x 要求成對
 *   - duplicate id：同 author + 同 id 出現多次但 subtype 不一致（潛在資料損壞）
 *   - missing fields：缺 author / 缺 date（依 caller 嚴格度回 warning）
 *
 * 吃 Sprint 330 RevisionExportRow[]、純驗證。
 *
 * 紀律 #18 scope-down：
 *   - 純驗證、不修復（caller 依結果決定）
 *   - move 配對只比對 id（OOXML 用 w:id 配 moveFrom/moveTo）
 *   - 不接 doc walk（caller 先用 exportRevisionsAsJson）
 *
 * 紀律 #21：純函式 validator、不污染 production pipeline。
 */

import type { RevisionExportRow } from './RevisionExporter';

export type ValidationSeverity = 'error' | 'warning';

export interface ValidationIssue {
  severity: ValidationSeverity;
  kind: 'orphan-move' | 'duplicate-id' | 'missing-author' | 'missing-date';
  message: string;
  /** 相關的 row（debug 用） */
  rows: RevisionExportRow[];
}

export interface ValidateOptions {
  /** 是否把缺 author 視為 issue（預設 false） */
  requireAuthor?: boolean;
  /** 是否把缺 date 視為 issue（預設 false） */
  requireDate?: boolean;
}

/**
 * 偵測 orphan move：moveFrom / moveTo 必須成對（依 id 配對）。
 *
 * - 無 id 的 move row → 無法配對、視為 orphan（error）
 * - 同 id 有 moveFrom 無 moveTo（或反之）→ orphan（error）
 */
function detectOrphanMoves(rows: ReadonlyArray<RevisionExportRow>): ValidationIssue[] {
  const moveFromById = new Map<string, RevisionExportRow[]>();
  const moveToById = new Map<string, RevisionExportRow[]>();
  const noId: RevisionExportRow[] = [];

  for (const r of rows) {
    if (r.subtype !== 'moveFrom' && r.subtype !== 'moveTo') continue;
    if (r.id === '') {
      noId.push(r);
      continue;
    }
    const map = r.subtype === 'moveFrom' ? moveFromById : moveToById;
    let arr = map.get(r.id);
    if (!arr) {
      arr = [];
      map.set(r.id, arr);
    }
    arr.push(r);
  }

  const issues: ValidationIssue[] = [];
  for (const r of noId) {
    issues.push({
      severity: 'error',
      kind: 'orphan-move',
      message: `${r.subtype} without w:id cannot be paired`,
      rows: [r],
    });
  }
  const allIds = new Set([...moveFromById.keys(), ...moveToById.keys()]);
  for (const id of allIds) {
    const froms = moveFromById.get(id) ?? [];
    const tos = moveToById.get(id) ?? [];
    if (froms.length === 0 || tos.length === 0) {
      issues.push({
        severity: 'error',
        kind: 'orphan-move',
        message: `move id=${id} unpaired (moveFrom=${froms.length}, moveTo=${tos.length})`,
        rows: [...froms, ...tos],
      });
    }
  }
  return issues;
}

/**
 * 偵測 duplicate id：同 author+id 但 subtype 不一致（資料損壞 / merge 衝突殘留）。
 *
 * 注意：moveFrom / moveTo **刻意** 共用同一 w:id 形成配對（OOXML §17.13.5.x），
 * 由 detectOrphanMoves 專門驗證、不該被當成 duplicate；故此處排除 move subtype。
 */
function detectDuplicateIds(rows: ReadonlyArray<RevisionExportRow>): ValidationIssue[] {
  const map = new Map<string, RevisionExportRow[]>();
  for (const r of rows) {
    if (r.id === '') continue;
    if (r.subtype === 'moveFrom' || r.subtype === 'moveTo') continue;
    const key = `${r.author}|${r.id}`;
    let arr = map.get(key);
    if (!arr) {
      arr = [];
      map.set(key, arr);
    }
    arr.push(r);
  }
  const issues: ValidationIssue[] = [];
  for (const [key, group] of map) {
    const subtypes = new Set(group.map((g) => g.subtype));
    if (subtypes.size > 1) {
      const [author, id] = key.split('|');
      issues.push({
        severity: 'error',
        kind: 'duplicate-id',
        message: `author=${author} id=${id} has conflicting subtypes: ${[...subtypes].sort().join(', ')}`,
        rows: group,
      });
    }
  }
  return issues;
}

/**
 * 完整驗證、回 issue list。
 */
export function validateRevisions(
  rows: ReadonlyArray<RevisionExportRow>,
  opts: ValidateOptions = {},
): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  issues.push(...detectOrphanMoves(rows));
  issues.push(...detectDuplicateIds(rows));

  if (opts.requireAuthor) {
    const missing = rows.filter((r) => r.author === '');
    if (missing.length > 0) {
      issues.push({
        severity: 'warning',
        kind: 'missing-author',
        message: `${missing.length} revision(s) missing author`,
        rows: missing,
      });
    }
  }
  if (opts.requireDate) {
    const missing = rows.filter((r) => r.date === '');
    if (missing.length > 0) {
      issues.push({
        severity: 'warning',
        kind: 'missing-date',
        message: `${missing.length} revision(s) missing date`,
        rows: missing,
      });
    }
  }
  return issues;
}

export interface ValidationReport {
  valid: boolean;
  errorCount: number;
  warningCount: number;
  issues: ValidationIssue[];
}

/**
 * 包成 report：valid = 無 error（warning 不影響 valid）。
 */
export function buildValidationReport(
  rows: ReadonlyArray<RevisionExportRow>,
  opts: ValidateOptions = {},
): ValidationReport {
  const issues = validateRevisions(rows, opts);
  const errorCount = issues.filter((i) => i.severity === 'error').length;
  const warningCount = issues.filter((i) => i.severity === 'warning').length;
  return { valid: errorCount === 0, errorCount, warningCount, issues };
}
