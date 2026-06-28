/**
 * RevisionTimelineBuilder — Sprint 325。
 *
 * Sprint 300/305/310/315/320 revision 系列第六輪深推。本 sprint 補：
 * 把 revision 按時間軸分群，產出 UI 友善的 timeline buckets。
 *
 * 用途：
 *   - UI 顯示「2026-05-15 Alice 添加了 5 處...」
 *   - PR-style 顯示 revision history（依日期降冪）
 *   - 報表匯出：依日期合併同 author 的相關修訂
 *
 * 範圍：
 *   - `buildTimeline(doc, opts)` → TimelineBucket[]（依 dateGranularity 分群）
 *   - 三種 granularity：'day' / 'hour' / 'author-day'
 *   - 缺 date 的 revision 歸 'unknown' bucket
 *
 * 紀律 #18 scope-down：
 *   - 不展開 inline diff、不顯示具體內容（caller 自管）
 *   - 不做 sliding 時間窗（caller 用 buckets 自己 filter）
 *   - date 直接以 ISO string 比較（Sprint 290 capture raw、不轉 Date）
 *
 * 紀律 #21：pure-fn、不污染既有 production。
 */

import type { DocumentNode } from '../ast/types';
import { listRevisions, type RevisionListEntry } from './accept_reject';

export type TimelineGranularity = 'day' | 'hour' | 'author-day';

export interface TimelineBucket {
  /** Bucket key（如 '2026-05-15' / '2026-05-15T14' / '2026-05-15|Alice'） */
  key: string;
  /** 顯示用 label */
  label: string;
  /** 日期部分（YYYY-MM-DD）；'unknown' 為缺日期項 */
  date: string;
  /** 小時部分（granularity=hour 才有） */
  hour?: number;
  /** Author（granularity=author-day 才有） */
  author?: string;
  /** 該 bucket 內 revision 數量 */
  count: number;
  /** 該 bucket 內 revision entries */
  entries: RevisionListEntry[];
}

export interface BuildTimelineOptions {
  /** 分群粒度；預設 'day' */
  granularity?: TimelineGranularity;
  /** 排序方向；預設 'desc'（最新在前） */
  order?: 'asc' | 'desc';
}

/**
 * 取 doc 的所有 revision、依時間軸分群。
 *
 * date 缺失時歸入 'unknown' bucket（排序時放最後）。
 */
export function buildTimeline(doc: DocumentNode, opts: BuildTimelineOptions = {}): TimelineBucket[] {
  const granularity = opts.granularity ?? 'day';
  const order = opts.order ?? 'desc';
  const entries = listRevisions(doc);

  const buckets = new Map<string, TimelineBucket>();
  for (const entry of entries) {
    const { key, date, hour, author, label } = computeBucketKey(entry, granularity);
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { key, label, date, count: 0, entries: [] };
      if (hour !== undefined) bucket.hour = hour;
      if (author !== undefined) bucket.author = author;
      buckets.set(key, bucket);
    }
    bucket.count++;
    bucket.entries.push(entry);
  }

  const result = [...buckets.values()];
  result.sort((a, b) => {
    // 'unknown' 永遠在最後
    if (a.date === 'unknown' && b.date !== 'unknown') return 1;
    if (b.date === 'unknown' && a.date !== 'unknown') return -1;
    const cmp = a.key.localeCompare(b.key);
    return order === 'desc' ? -cmp : cmp;
  });
  return result;
}

function computeBucketKey(
  entry: RevisionListEntry,
  granularity: TimelineGranularity,
): { key: string; date: string; hour?: number; author?: string; label: string } {
  const rawDate = entry.meta.date;
  const author = entry.meta.author && entry.meta.author.trim() ? entry.meta.author : undefined;

  if (!rawDate) {
    if (granularity === 'author-day') {
      const a = author ?? 'Unknown';
      return {
        key: `unknown|${a}`,
        date: 'unknown',
        author: a,
        label: `(未知日期) ${a}`,
      };
    }
    return { key: 'unknown', date: 'unknown', label: '(未知日期)' };
  }

  // 從 ISO string 取 date / hour（不轉 Date 物件、避免時區歧異）
  // 預期格式：YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SSZ
  const dateMatch = /^(\d{4}-\d{2}-\d{2})(?:T(\d{2}))?/.exec(rawDate);
  if (!dateMatch) {
    return { key: 'unknown', date: 'unknown', label: '(未知日期)' };
  }
  const date = dateMatch[1];
  const hour = dateMatch[2] !== undefined ? parseInt(dateMatch[2], 10) : undefined;

  switch (granularity) {
    case 'day':
      return { key: date, date, label: date };
    case 'hour':
      if (hour === undefined) return { key: date, date, label: date };
      return {
        key: `${date}T${String(hour).padStart(2, '0')}`,
        date,
        hour,
        label: `${date} ${String(hour).padStart(2, '0')}:00`,
      };
    case 'author-day': {
      const a = author ?? 'Unknown';
      return {
        key: `${date}|${a}`,
        date,
        author: a,
        label: `${date} · ${a}`,
      };
    }
  }
}

/** Stats：總 bucket 數 / 含 unknown bucket / 有效日期最早最晚。 */
export interface TimelineStats {
  totalBuckets: number;
  hasUnknown: boolean;
  earliestDate?: string;
  latestDate?: string;
}

export function summarizeTimeline(buckets: ReadonlyArray<TimelineBucket>): TimelineStats {
  let earliestDate: string | undefined;
  let latestDate: string | undefined;
  let hasUnknown = false;
  for (const b of buckets) {
    if (b.date === 'unknown') {
      hasUnknown = true;
      continue;
    }
    if (earliestDate === undefined || b.date < earliestDate) earliestDate = b.date;
    if (latestDate === undefined || b.date > latestDate) latestDate = b.date;
  }
  return {
    totalBuckets: buckets.length,
    hasUnknown,
    ...(earliestDate ? { earliestDate } : {}),
    ...(latestDate ? { latestDate } : {}),
  };
}
