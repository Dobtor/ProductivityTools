/**
 * RevisionDiffSummary — Sprint 310。
 *
 * Sprint 300 accept/reject helpers + Sprint 305 review session 之後第三輪深推。
 * 本 sprint 補：給 caller UI 顯示用的「人類可讀」revision summary。
 *
 * 場景：
 *   - UI 標頭顯示「Alice 添加了 5 處、刪除了 3 處；Bob 修改了 2 處屬性...」
 *   - PR-style review：依 author 群組摘要、依 type 統計
 *   - 報表匯出：JSON / Markdown 形式輸出
 *
 * 範圍（Strategy A pure-fn）：
 *   - `summarizeByAuthor`：依 author 群組統計（accepts ∅ author 為 'Unknown'）
 *   - `summarizeByType`：依 revision type 統計
 *   - `formatSummaryMarkdown`：產出 Markdown 表格摘要（caller 直接餵 UI）
 *
 * 紀律 #18 scope-down：
 *   - 不展開「具體哪段文字被刪」（要 DocumentNode 上下文、由 caller 自做）
 *   - 不做 i18n（caller 自行翻譯 label）；本層只回英文 type name
 *   - 不做 trend over time（單 doc 快照、不分析 author 修訂節奏）
 *
 * 紀律 #21：pure-fn、不污染既有 production；單 doc snapshot input、無 side effect。
 */

import type { DocumentNode } from '../ast/types';
import { listRevisions, type RevisionListEntry } from './accept_reject';

/** 依 author 群組統計。author 為 undefined / 空字串 → 'Unknown' bucket。 */
export interface AuthorSummary {
  author: string;
  total: number;
  byType: Record<string, number>;
}

export function summarizeByAuthor(doc: DocumentNode): AuthorSummary[] {
  const entries = listRevisions(doc);
  const buckets = new Map<string, AuthorSummary>();
  for (const e of entries) {
    const author = (e.meta.author && e.meta.author.trim()) || 'Unknown';
    const typeLabel = revisionTypeLabel(e);
    let bucket = buckets.get(author);
    if (!bucket) {
      bucket = { author, total: 0, byType: {} };
      buckets.set(author, bucket);
    }
    bucket.total++;
    bucket.byType[typeLabel] = (bucket.byType[typeLabel] ?? 0) + 1;
  }
  return [...buckets.values()].sort((a, b) => b.total - a.total);
}

/** 依 revision type 統計。 */
export interface TypeSummary {
  type: string;
  count: number;
}

export function summarizeByType(doc: DocumentNode): TypeSummary[] {
  const entries = listRevisions(doc);
  const counts = new Map<string, number>();
  for (const e of entries) {
    const label = revisionTypeLabel(e);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count);
}

/**
 * 把 entry 對映為 human-readable label。
 *
 * - source = 'run-revision' → 用 entry.meta.type（ins / del / moveFrom / moveTo）
 * - 其他 source → source 本身（rPrChange / pPrChange / cellIns / cellDel / cellMerge）
 */
function revisionTypeLabel(entry: RevisionListEntry): string {
  if (entry.source === 'run-revision') {
    const t = (entry.meta as { type?: string }).type;
    return t ?? 'unknown';
  }
  return entry.source;
}

/**
 * 產出 Markdown 摘要（caller 餵 UI 或 PR comment）。
 *
 * 範例：
 *
 * ```markdown
 * ## Revision Summary
 *
 * **Total: 8 revisions**
 *
 * ### By Author
 * | Author | Total | Breakdown |
 * |---|---|---|
 * | Alice | 5 | ins×3, del×2 |
 * | Bob   | 3 | rPrChange×2, ins×1 |
 *
 * ### By Type
 * | Type | Count |
 * |---|---|
 * | ins | 4 |
 * | del | 2 |
 * | rPrChange | 2 |
 * ```
 */
export function formatSummaryMarkdown(doc: DocumentNode): string {
  const byAuthor = summarizeByAuthor(doc);
  const byType = summarizeByType(doc);
  const total = byType.reduce((acc, t) => acc + t.count, 0);

  const lines: string[] = [];
  lines.push('## Revision Summary');
  lines.push('');
  lines.push(`**Total: ${total} revision${total === 1 ? '' : 's'}**`);
  lines.push('');

  if (byAuthor.length > 0) {
    lines.push('### By Author');
    lines.push('| Author | Total | Breakdown |');
    lines.push('|---|---|---|');
    for (const a of byAuthor) {
      const breakdown = Object.entries(a.byType)
        .sort((x, y) => y[1] - x[1])
        .map(([t, c]) => `${t}×${c}`)
        .join(', ');
      lines.push(`| ${a.author} | ${a.total} | ${breakdown} |`);
    }
    lines.push('');
  }

  if (byType.length > 0) {
    lines.push('### By Type');
    lines.push('| Type | Count |');
    lines.push('|---|---|');
    for (const t of byType) {
      lines.push(`| ${t.type} | ${t.count} |`);
    }
  }

  return lines.join('\n');
}
