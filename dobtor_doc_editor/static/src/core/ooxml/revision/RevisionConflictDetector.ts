/**
 * RevisionConflictDetector — Sprint 315。
 *
 * Sprint 300/305/310 之後第四輪深推。偵測 revision 之間的潛在衝突：
 *
 *   - **Same-paragraph conflict**：同一段落內、不同 author 的 ins/del 交錯
 *     （Alice 在某 run 加字、Bob 刪同位置的 run）
 *   - **Move pair mismatch**：moveFrom 與 moveTo 配對 id 但 author 不同
 *   - **PropsChange double-modify**：同 run 同時有 rPrChange 與 revision、可能是
 *     多人在同欄位的修訂（pPrChange 同理）
 *
 * 用途：UI 顯示 warning「以下 N 處 revision 涉及衝突、建議逐筆 review」、
 *   或自動批准前的 safety net。
 *
 * 範圍（pure-fn）：
 *   - `detectConflicts(doc)` → ConflictReport[]
 *   - `summarizeConflicts(report)` → human-readable summary
 *
 * 紀律 #18 scope-down：
 *   - 不做語意級衝突（同段落兩 author 改不同地方但語意衝突 → 不解）
 *   - 不主動建議解法（caller 自決 accept/reject）
 *   - moveFrom/moveTo pair 比對只看 id 與 author，不看 content 一致性
 *
 * 紀律 #21：pure-fn、不污染既有 production。
 */

import type {
  DocumentNode,
  ParagraphNode,
  TableNode,
  CellNode,
  BlockNode,
  RunNode,
  RunRevision,
  TrackChangeMeta,
} from '../ast/types';

export type ConflictKind =
  | 'mixed-author-in-paragraph'
  | 'move-pair-author-mismatch'
  | 'move-pair-orphan'
  | 'run-props-and-revision-coexist'
  | 'paragraph-pPrChange-and-runs-revision';

export interface ConflictReport {
  kind: ConflictKind;
  /** 一句描述 */
  message: string;
  /** 牽涉到的 author（去重） */
  authors: string[];
  /** 牽涉到的 revision id（去重、升序） */
  revisionIds: number[];
}

/**
 * 偵測整 doc 內所有 conflict。
 *
 * 不變動 doc；caller 拿 ConflictReport[] 後可以：
 *   - 顯示 UI warning
 *   - 拒絕 auto-accept
 *   - 把報告寫進 review log
 */
export function detectConflicts(doc: DocumentNode): ConflictReport[] {
  const reports: ConflictReport[] = [];

  // 全域：moveFrom/moveTo pair 對照
  const moveFromById = new Map<number, { author: string; runs: RunNode[] }>();
  const moveToById = new Map<number, { author: string; runs: RunNode[] }>();

  for (const section of doc.sections) {
    for (const block of section.body) {
      walkBlock(block, reports, moveFromById, moveToById);
    }
  }

  // Move pair 完整性檢查
  const allIds = new Set<number>([...moveFromById.keys(), ...moveToById.keys()]);
  for (const id of allIds) {
    const f = moveFromById.get(id);
    const t = moveToById.get(id);
    if (f && t) {
      if (f.author !== t.author) {
        reports.push({
          kind: 'move-pair-author-mismatch',
          message: `move pair id=${id} 的 from author "${f.author}" 與 to author "${t.author}" 不一致`,
          authors: dedup([f.author, t.author]),
          revisionIds: [id],
        });
      }
    } else if (f && !t) {
      reports.push({
        kind: 'move-pair-orphan',
        message: `moveFrom id=${id}（${f.author}）找不到對應 moveTo`,
        authors: [f.author],
        revisionIds: [id],
      });
    } else if (!f && t) {
      reports.push({
        kind: 'move-pair-orphan',
        message: `moveTo id=${id}（${t.author}）找不到對應 moveFrom`,
        authors: [t.author],
        revisionIds: [id],
      });
    }
  }

  return reports;
}

function walkBlock(
  block: BlockNode,
  reports: ConflictReport[],
  moveFromById: Map<number, { author: string; runs: RunNode[] }>,
  moveToById: Map<number, { author: string; runs: RunNode[] }>,
): void {
  if (block.type === 'paragraph') {
    walkParagraph(block, reports, moveFromById, moveToById);
  } else {
    walkTable(block, reports, moveFromById, moveToById);
  }
}

function walkTable(
  t: TableNode,
  reports: ConflictReport[],
  moveFromById: Map<number, { author: string; runs: RunNode[] }>,
  moveToById: Map<number, { author: string; runs: RunNode[] }>,
): void {
  for (const row of t.rows) {
    for (const cell of row.cells) {
      walkCell(cell, reports, moveFromById, moveToById);
    }
  }
}

function walkCell(
  cell: CellNode,
  reports: ConflictReport[],
  moveFromById: Map<number, { author: string; runs: RunNode[] }>,
  moveToById: Map<number, { author: string; runs: RunNode[] }>,
): void {
  for (const inner of cell.content) {
    walkBlock(inner, reports, moveFromById, moveToById);
  }
}

function walkParagraph(
  p: ParagraphNode,
  reports: ConflictReport[],
  moveFromById: Map<number, { author: string; runs: RunNode[] }>,
  moveToById: Map<number, { author: string; runs: RunNode[] }>,
): void {
  const authorsInP = new Set<string>();
  const idsInP = new Set<number>();
  let hasRunRevision = false;

  for (const child of p.runs) {
    if (child.type !== 'run') continue;
    const run = child;
    if (run.revision) {
      hasRunRevision = true;
      const author = run.revision.author ?? '';
      if (author) authorsInP.add(author);
      if (run.revision.id !== undefined) idsInP.add(run.revision.id);
      // 移動配對
      if (run.revision.type === 'moveFrom' && run.revision.id !== undefined) {
        const bucket = moveFromById.get(run.revision.id);
        if (bucket) bucket.runs.push(run);
        else moveFromById.set(run.revision.id, { author, runs: [run] });
      } else if (run.revision.type === 'moveTo' && run.revision.id !== undefined) {
        const bucket = moveToById.get(run.revision.id);
        if (bucket) bucket.runs.push(run);
        else moveToById.set(run.revision.id, { author, runs: [run] });
      }
    }
    // 同 run 同時有 rPrChange + revision
    if (run.revision && run.props.rPrChange) {
      reports.push({
        kind: 'run-props-and-revision-coexist',
        message: `run 同時帶 revision (${run.revision.type}) 與 rPrChange、可能多人修訂`,
        authors: dedup([
          run.revision.author ?? '',
          run.props.rPrChange.author ?? '',
        ].filter(Boolean)),
        revisionIds: dedup([run.revision.id, run.props.rPrChange.id].filter((x): x is number => x !== undefined)),
      });
    }
  }

  // 段落內多 author
  if (authorsInP.size >= 2) {
    reports.push({
      kind: 'mixed-author-in-paragraph',
      message: `同一段落內混合 ${authorsInP.size} 個 author 的 revision`,
      authors: [...authorsInP].sort(),
      revisionIds: [...idsInP].sort((a, b) => a - b),
    });
  }

  // 段落級 pPrChange 與 run 級 revision 共存
  if (p.props.pPrChange && hasRunRevision) {
    reports.push({
      kind: 'paragraph-pPrChange-and-runs-revision',
      message: `段落 pPrChange 與內部 run revision 共存、可能屬性修訂與內容修訂衝突`,
      authors: dedup([p.props.pPrChange.author ?? '', ...authorsInP].filter(Boolean)),
      revisionIds: dedup([p.props.pPrChange.id, ...idsInP].filter((x): x is number => x !== undefined)),
    });
  }
}

function dedup<T>(arr: T[]): T[] {
  return [...new Set(arr)];
}

/** human-readable summary 給 UI / log 顯示。 */
export function summarizeConflicts(reports: readonly ConflictReport[]): string {
  if (reports.length === 0) return '無偵測到 revision 衝突。';
  const byKind = new Map<ConflictKind, number>();
  for (const r of reports) {
    byKind.set(r.kind, (byKind.get(r.kind) ?? 0) + 1);
  }
  const lines: string[] = [`偵測到 ${reports.length} 處 revision 衝突：`];
  for (const [kind, count] of byKind) {
    lines.push(`- ${kind}: ${count} 處`);
  }
  return lines.join('\n');
}

/** 工具型：給單一 paragraph 也能直接掃描（caller 用於增量檢查單段落變更）。 */
export function detectConflictsInParagraph(p: ParagraphNode): ConflictReport[] {
  const reports: ConflictReport[] = [];
  const moveFromById = new Map<number, { author: string; runs: RunNode[] }>();
  const moveToById = new Map<number, { author: string; runs: RunNode[] }>();
  walkParagraph(p, reports, moveFromById, moveToById);
  return reports;
}
// type guards used by walkParagraph
// (referenced TrackChangeMeta to keep type explicit, no runtime use)
void (null as unknown as { _meta?: TrackChangeMeta; _rev?: RunRevision });
