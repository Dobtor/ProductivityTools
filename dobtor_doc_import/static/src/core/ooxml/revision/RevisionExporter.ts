/**
 * RevisionExporter — Sprint 330。
 *
 * Sprint 300/305/310/315/320/325 revision 系列第七輪深推。把整 doc 內所有
 * revision metadata 匯出為「外部 audit tool」可吃的格式（JSON / CSV）。
 *
 * 場景：
 *   - 法務 / QA 想拿到一份「逐筆修訂清單」做合規檢查、與外部 ticket 比對
 *   - Spreadsheet / 第三方 diff visualizer 想吃 JSON 或 CSV
 *   - revision metadata 散落在 ast 各層、不適合 caller 自己 walk
 *
 * API：
 *   - exportRevisionsAsJson(doc) → JSON-safe object array
 *   - exportRevisionsAsCsv(doc) → CSV string（含 header line）
 *
 * 紀律 #18 scope-down：
 *   - 不接 file system / Buffer / streaming（caller 自負 IO）
 *   - 不做時區轉換（date 原樣輸出）
 *   - 不做 diff inline 還原（caller 想看原文要自己取 RunNode.text）
 *
 * 紀律 #21：純函式、純 transform、不污染 production pipeline。
 */

import type { DocumentNode } from '../ast/types';
import { listRevisions } from './accept_reject';

/**
 * Exporter 內部用的扁平 row 型別（每筆 revision 一列）。
 */
export interface RevisionExportRow {
  /** revision 種類來源 */
  source: 'run-revision' | 'rPrChange' | 'pPrChange' | 'cellIns' | 'cellDel' | 'cellMerge';
  /** run-revision 子型別（ins/del/moveFrom/moveTo）；其他 source 為 'props' */
  subtype: 'ins' | 'del' | 'moveFrom' | 'moveTo' | 'props';
  /** w:author（原樣回；undefined → 空字串） */
  author: string;
  /** w:date（原樣 ISO string；undefined → 空字串） */
  date: string;
  /** w:id；undefined → 空字串 */
  id: string;
}

/**
 * 列舉 doc 內所有 revision、轉成扁平 row 結構。
 */
export function exportRevisionsAsJson(doc: DocumentNode): RevisionExportRow[] {
  const entries = listRevisions(doc);
  const rows: RevisionExportRow[] = [];
  for (const e of entries) {
    let subtype: RevisionExportRow['subtype'];
    if (e.source === 'run-revision') {
      subtype = (e.meta as { type: 'ins' | 'del' | 'moveFrom' | 'moveTo' }).type;
    } else {
      subtype = 'props';
    }
    rows.push({
      source: e.source,
      subtype,
      author: e.meta.author ?? '',
      date: e.meta.date ?? '',
      id: e.meta.id !== undefined ? String(e.meta.id) : '',
    });
  }
  return rows;
}

/**
 * CSV escape 規則（RFC 4180）：
 *   - 含 `,` / `"` / 換行 → 用 `"` 包起
 *   - 內部 `"` 倍寫成 `""`
 */
export function escapeCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/**
 * 匯出 CSV 字串（含 header line）。
 *
 * 欄位順序：source, subtype, author, date, id
 *
 * 空 doc → 只回 header line（caller 依然拿得到 schema）。
 */
export function exportRevisionsAsCsv(doc: DocumentNode): string {
  const header = 'source,subtype,author,date,id';
  const rows = exportRevisionsAsJson(doc);
  if (rows.length === 0) return header;
  const lines = [header];
  for (const r of rows) {
    lines.push(
      [
        escapeCsvField(r.source),
        escapeCsvField(r.subtype),
        escapeCsvField(r.author),
        escapeCsvField(r.date),
        escapeCsvField(r.id),
      ].join(','),
    );
  }
  return lines.join('\n');
}

/**
 * 給 caller / logging 用的簡易計數：總 row / 按 subtype 累計。
 */
export interface ExportSummary {
  totalRows: number;
  bySubtype: {
    ins: number;
    del: number;
    moveFrom: number;
    moveTo: number;
    props: number;
  };
}

export function summarizeExport(rows: ReadonlyArray<RevisionExportRow>): ExportSummary {
  const summary: ExportSummary = {
    totalRows: rows.length,
    bySubtype: { ins: 0, del: 0, moveFrom: 0, moveTo: 0, props: 0 },
  };
  for (const r of rows) {
    summary.bySubtype[r.subtype] += 1;
  }
  return summary;
}
