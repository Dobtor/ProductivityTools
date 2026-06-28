/**
 * RevisionMerger — Sprint 335。
 *
 * Sprint 300/305/310/315/320/325/330 revision 系列第八輪深推。Sprint 330
 * RevisionExporter 可匯出單一 doc 內所有 revision；本 sprint 補：
 * **合併不同 source（multiple docs / sessions / branches）的 revision rows**、
 * 處理重複（同 id+author）、保留時間排序、回 summary。
 *
 * 場景：
 *   - 兩個 reviewer 各自離線 review 同一 doc、匯出 export rows、再合併回中央
 *   - 兩個版本分支 merge 前需要看「合計變動數 / 衝突 row」
 *   - 給合規/法務 audit：列舉 N 個 session 的 revision 全集 + 去重
 *
 * API：
 *   - mergeRevisionRows(sources)：聯集 + 去重（同 id+author+subtype 視為同筆）
 *   - sortByDate(rows)：ISO string 字典序排序
 *   - groupByAuthor(rows)：Map<author, RevisionExportRow[]>
 *
 * 紀律 #18 scope-down：
 *   - 純 array transform；不接 file system / network / git merge
 *   - 不解決真正的「衝突」（同 id 不同 author/date 就回兩筆）
 *   - 不轉時區（date 原樣比較）
 *
 * 紀律 #21：純函式、不污染 production pipeline。
 */

import type { RevisionExportRow } from './RevisionExporter';

/**
 * 合併多個 source 的 revision rows、去除重複。
 *
 * 去重 key：`source + subtype + author + date + id`。完全相同的 row 視為同筆。
 *
 * 順序：保留第一次出現的 row（caller 看到的 source 順序為主）。
 */
export function mergeRevisionRows(
  sources: ReadonlyArray<ReadonlyArray<RevisionExportRow>>,
): RevisionExportRow[] {
  const seen = new Set<string>();
  const out: RevisionExportRow[] = [];
  for (const src of sources) {
    for (const r of src) {
      const key = `${r.source}|${r.subtype}|${r.author}|${r.date}|${r.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(r);
    }
  }
  return out;
}

/**
 * 用 ISO string 字典序排 date。empty date 視為「最早」、排在最前。
 *
 * 紀律 #18：不轉 Date 物件、不處理時區、ISO 字串字典序對齊 lexicographic == chronological。
 */
export function sortByDate(
  rows: ReadonlyArray<RevisionExportRow>,
  order: 'asc' | 'desc' = 'asc',
): RevisionExportRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    if (a.date === b.date) return 0;
    if (a.date === '') return order === 'asc' ? -1 : 1;
    if (b.date === '') return order === 'asc' ? 1 : -1;
    const cmp = a.date < b.date ? -1 : 1;
    return order === 'asc' ? cmp : -cmp;
  });
  return copy;
}

/**
 * 依 author 分組。empty author 歸到 'Unknown' bucket。
 */
export function groupByAuthor(
  rows: ReadonlyArray<RevisionExportRow>,
): Map<string, RevisionExportRow[]> {
  const map = new Map<string, RevisionExportRow[]>();
  for (const r of rows) {
    const key = r.author === '' ? 'Unknown' : r.author;
    let bucket = map.get(key);
    if (!bucket) {
      bucket = [];
      map.set(key, bucket);
    }
    bucket.push(r);
  }
  return map;
}

/**
 * 同 author + 同 id 但 subtype 不同的「潛在衝突 rows」報告。
 *
 * 用途：multi-source merge 後 caller 想知道「有沒有同一 revision id 在不同 source
 * 標成不同 subtype」（例如一邊 ins、一邊 del）。
 */
export interface MergeConflict {
  author: string;
  id: string;
  subtypes: string[];
}

export function detectMergeConflicts(
  rows: ReadonlyArray<RevisionExportRow>,
): MergeConflict[] {
  // key = author + id；value = Set<subtype>
  const map = new Map<string, Set<string>>();
  for (const r of rows) {
    if (r.id === '') continue; // 無 id 不視為可衝突
    const key = `${r.author}|${r.id}`;
    let s = map.get(key);
    if (!s) {
      s = new Set();
      map.set(key, s);
    }
    s.add(r.subtype);
  }
  const out: MergeConflict[] = [];
  for (const [key, subtypes] of map) {
    if (subtypes.size > 1) {
      const [author, id] = key.split('|');
      out.push({ author, id, subtypes: [...subtypes].sort() });
    }
  }
  return out;
}

/**
 * Merge summary：總筆數、去重後筆數、各 author 計數、conflict 計數。
 */
export interface MergeSummary {
  totalInputRows: number;
  mergedRows: number;
  duplicatesRemoved: number;
  authorCount: number;
  conflictCount: number;
}

export function summarizeMerge(
  sources: ReadonlyArray<ReadonlyArray<RevisionExportRow>>,
): MergeSummary {
  const totalInputRows = sources.reduce((acc, s) => acc + s.length, 0);
  const merged = mergeRevisionRows(sources);
  const authors = groupByAuthor(merged);
  const conflicts = detectMergeConflicts(merged);
  return {
    totalInputRows,
    mergedRows: merged.length,
    duplicatesRemoved: totalInputRows - merged.length,
    authorCount: authors.size,
    conflictCount: conflicts.length,
  };
}
