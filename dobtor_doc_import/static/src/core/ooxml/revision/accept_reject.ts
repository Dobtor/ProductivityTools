/**
 * AST 追蹤修訂 accept/reject pure-fn helpers — Sprint 300。
 *
 * Follow-up to Sprint 290（moveFrom/moveTo capture）+ Sprint 293（pPrChange /
 * rPrChange / cellIns / cellDel / cellMerge capture）的 honest gap：
 *
 *   「UI accept/reject 面板 未做」
 *
 * 本 sprint 為 pure-fn layer：caller 給一棵 DocumentNode、回傳新樹（immutable
 * transform），把指定 revision 全部 accept 或 reject。UI 面板（accept-all /
 * accept-selected / reject-all / reject-selected 按鈕）為 future sprint，本層
 * 為 UI 與 production save 都可消費的 building block。
 *
 * 範圍（Sprint 300）：
 *   - RunRevision（ins/del/moveFrom/moveTo）：完整 accept/reject 邏輯
 *   - TrackChangeMeta on rPrChange/pPrChange：accept 丟棄 metadata、
 *     reject 也僅丟棄 metadata（completeness scope-down，理由見下）
 *   - cellIns / cellDel / cellMerge：accept 丟棄 metadata、reject 同上 scope-down
 *
 * 紀律 #18 scope-down — props *Change reject 為何只丟 metadata：
 *
 *   完整 reject 需「還原 previous-state pPr/rPr」內容，但目前 parser 只 capture
 *   *Change 的 author/date/id（不展開 previous-state 內容；OOXML 規格中
 *   `<w:pPrChange>` 內含一份 previous `<w:pPr>`、`<w:rPrChange>` 內含一份
 *   previous `<w:rPr>`，但 parser 未保存）。完整還原為 future sprint（要先擴
 *   AST 把 previous state 也存進來，再寫對應 reject 路徑）。
 *
 *   Accept 直接 drop metadata 不需要 previous state、邏輯完整無 scope-down。
 *
 * 紀律 #21：pure-fn、不污染既有 parser/layout/render；caller 顯式呼叫才生效。
 *
 * Predicate API（caller 可選擇性 accept/reject）：
 *   const accepted = acceptRevisions(doc, { predicate: (meta) => meta.id === 5 });
 *
 * 不帶 predicate 時 = accept/reject ALL。
 */

import type {
  DocumentNode,
  SectionNode,
  BlockNode,
  ParagraphNode,
  TableNode,
  RowNode,
  CellNode,
  RunNode,
  InlineNode,
  RunRevision,
  TrackChangeMeta,
} from '../ast/types';

/**
 * Caller-supplied predicate；回傳 true 才 accept/reject 該 revision。
 *
 * 接收 RunRevision 或 TrackChangeMeta（共用 author/date/id 三欄）；
 * caller 可依 id 過濾「只 accept Alice 的修訂」或「accept id <= 100」等場景。
 */
export type RevisionPredicate = (meta: RunRevision | TrackChangeMeta) => boolean;

export interface AcceptRejectOptions {
  /** 過濾哪些 revision 要被 accept/reject；缺省 = 全部 */
  predicate?: RevisionPredicate;
}

// ── Run-level revision 行為矩陣 ──────────────────────────────────────────────
//
//                ┌─────────┬──────────┐
//                │ accept  │ reject   │
//   ┌───────────┼─────────┼──────────┤
//   │ ins       │ KEEP    │ REMOVE   │
//   │ del       │ REMOVE  │ KEEP     │
//   │ moveFrom  │ REMOVE  │ KEEP     │
//   │ moveTo    │ KEEP    │ REMOVE   │
//   └───────────┴─────────┴──────────┘
//
// KEEP = 保留 run，移除 revision metadata；REMOVE = 從 runs[] 移除整個 run。

function runRevisionVerdict(
  type: RunRevision['type'],
  mode: 'accept' | 'reject',
): 'keep' | 'remove' {
  if (mode === 'accept') {
    return type === 'ins' || type === 'moveTo' ? 'keep' : 'remove';
  }
  return type === 'del' || type === 'moveFrom' ? 'keep' : 'remove';
}

function shouldApply(meta: RunRevision | TrackChangeMeta, opts: AcceptRejectOptions): boolean {
  return !opts.predicate || opts.predicate(meta);
}

function transformRun(run: RunNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): RunNode | null {
  // Step 1：處理 wrap-style revision（ins/del/moveFrom/moveTo）
  if (run.revision && shouldApply(run.revision, opts)) {
    const verdict = runRevisionVerdict(run.revision.type, mode);
    if (verdict === 'remove') return null;
    // keep：移除 revision metadata
    const { revision: _revision, ...rest } = run;
    void _revision;
    run = { ...rest, type: 'run' } as RunNode;
  }
  // Step 2：處理 rPrChange（run props 級）
  if (run.props.rPrChange && shouldApply(run.props.rPrChange, opts)) {
    const { rPrChange: _rPrChange, ...restProps } = run.props;
    void _rPrChange;
    run = { ...run, props: restProps };
  }
  return run;
}

function transformInline(node: InlineNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): InlineNode | null {
  if (node.type === 'run') {
    return transformRun(node, mode, opts);
  }
  // 非 run 的 inline（field/break/image/footnoteRef/ruby）不帶 revision metadata、直接保留。
  return node;
}

function transformParagraph(p: ParagraphNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): ParagraphNode {
  // Runs：逐一 transform，filter null（被移除的 run）
  const newRuns: InlineNode[] = [];
  for (const r of p.runs) {
    const tr = transformInline(r, mode, opts);
    if (tr !== null) newRuns.push(tr);
  }
  let newProps = p.props;
  if (p.props.pPrChange && shouldApply(p.props.pPrChange, opts)) {
    const { pPrChange: _pPrChange, ...rest } = p.props;
    void _pPrChange;
    newProps = rest;
  }
  return { ...p, props: newProps, runs: newRuns };
}

function transformCell(cell: CellNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): CellNode {
  const newContent: BlockNode[] = cell.content.map((b) =>
    b.type === 'paragraph' ? transformParagraph(b, mode, opts) : transformTable(b, mode, opts),
  );
  // cellIns / cellDel / cellMerge：accept/reject 皆 drop metadata（scope-down）
  let newProps = cell.props;
  const { cellIns, cellDel, cellMerge, ...restProps } = newProps;
  const droppedIns = cellIns && shouldApply(cellIns, opts) ? undefined : cellIns;
  const droppedDel = cellDel && shouldApply(cellDel, opts) ? undefined : cellDel;
  const droppedMerge = cellMerge && shouldApply(cellMerge, opts) ? undefined : cellMerge;
  if (droppedIns !== cellIns || droppedDel !== cellDel || droppedMerge !== cellMerge) {
    newProps = {
      ...restProps,
      ...(droppedIns ? { cellIns: droppedIns } : {}),
      ...(droppedDel ? { cellDel: droppedDel } : {}),
      ...(droppedMerge ? { cellMerge: droppedMerge } : {}),
    };
  }
  return { ...cell, content: newContent, props: newProps };
}

function transformRow(row: RowNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): RowNode {
  return { ...row, cells: row.cells.map((c) => transformCell(c, mode, opts)) };
}

function transformTable(t: TableNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): TableNode {
  return { ...t, rows: t.rows.map((r) => transformRow(r, mode, opts)) };
}

function transformBlock(b: BlockNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): BlockNode {
  return b.type === 'paragraph' ? transformParagraph(b, mode, opts) : transformTable(b, mode, opts);
}

function transformSection(s: SectionNode, mode: 'accept' | 'reject', opts: AcceptRejectOptions): SectionNode {
  return { ...s, body: s.body.map((b) => transformBlock(b, mode, opts)) };
}

/**
 * 取 DocumentNode、回傳新樹、所有 ins/moveTo 變正文、所有 del/moveFrom 移除、
 * 所有 *Change metadata 被丟棄（接受該屬性變更）。
 *
 * 不變動：headers/footers/footnotes/endnotes/comments（這些 Map 內容暫不展開
 * 處理 —— follow-up sprint 可擴；多數 fixture 的追蹤修訂落在 body 內、頁首
 * 尾極罕見有 track change）。
 *
 * @param doc 原文件樹
 * @param opts predicate 過濾（缺省 = accept ALL）
 * @returns 新 DocumentNode（原樹不被 mutate）
 */
export function acceptRevisions(doc: DocumentNode, opts: AcceptRejectOptions = {}): DocumentNode {
  return { ...doc, sections: doc.sections.map((s) => transformSection(s, 'accept', opts)) };
}

/**
 * 取 DocumentNode、回傳新樹、所有 ins/moveTo 移除、所有 del/moveFrom 變正文、
 * 所有 *Change metadata 被丟棄（拒絕該屬性變更、但 previous-state 還原為
 * future sprint —— 見檔頭紀律 #18 scope-down 說明）。
 */
export function rejectRevisions(doc: DocumentNode, opts: AcceptRejectOptions = {}): DocumentNode {
  return { ...doc, sections: doc.sections.map((s) => transformSection(s, 'reject', opts)) };
}

// ── 細粒度 helpers（單一 paragraph / 單一 run 也可用） ─────────────────────

/** 對單一段落 accept 所有 revision；caller UI 「accept this paragraph」用。 */
export function acceptParagraphRevisions(p: ParagraphNode, opts: AcceptRejectOptions = {}): ParagraphNode {
  return transformParagraph(p, 'accept', opts);
}

/** 對單一段落 reject 所有 revision。 */
export function rejectParagraphRevisions(p: ParagraphNode, opts: AcceptRejectOptions = {}): ParagraphNode {
  return transformParagraph(p, 'reject', opts);
}

/**
 * 列舉文件內所有 revision metadata（含 ins/del/moveFrom/moveTo + rPrChange +
 * pPrChange + cellIns/Del/Merge）；UI 顯示「文件目前有 N 筆未處理修訂」用。
 *
 * 不去重、按出現順序回傳（caller 想看每筆 author/date/id 用）。
 */
export interface RevisionListEntry {
  source: 'run-revision' | 'rPrChange' | 'pPrChange' | 'cellIns' | 'cellDel' | 'cellMerge';
  meta: RunRevision | TrackChangeMeta;
}

export function listRevisions(doc: DocumentNode): RevisionListEntry[] {
  const out: RevisionListEntry[] = [];
  for (const s of doc.sections) {
    for (const b of s.body) {
      collectFromBlock(b, out);
    }
  }
  return out;
}

function collectFromBlock(b: BlockNode, out: RevisionListEntry[]): void {
  if (b.type === 'paragraph') {
    collectFromParagraph(b, out);
  } else {
    for (const row of b.rows) {
      for (const cell of row.cells) {
        if (cell.props.cellIns) out.push({ source: 'cellIns', meta: cell.props.cellIns });
        if (cell.props.cellDel) out.push({ source: 'cellDel', meta: cell.props.cellDel });
        if (cell.props.cellMerge) out.push({ source: 'cellMerge', meta: cell.props.cellMerge });
        for (const inner of cell.content) collectFromBlock(inner, out);
      }
    }
  }
}

function collectFromParagraph(p: ParagraphNode, out: RevisionListEntry[]): void {
  if (p.props.pPrChange) out.push({ source: 'pPrChange', meta: p.props.pPrChange });
  for (const r of p.runs) {
    if (r.type !== 'run') continue;
    if (r.revision) out.push({ source: 'run-revision', meta: r.revision });
    if (r.props.rPrChange) out.push({ source: 'rPrChange', meta: r.props.rPrChange });
  }
}
