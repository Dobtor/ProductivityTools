/**
 * CanvasEditorPrewarmStrategy — Sprint 323。
 *
 * Sprint 303 prewarmFromAst + Sprint 318 pipeline 之後深推。問題：整 doc 的所有
 * unique (text, family, sizePt) 三元組可能成千上萬筆；caller 在記憶體 / 啟動延遲
 * 限制下需要 **heuristic** 選 prewarm 子集。
 *
 * 提供三種 strategy：
 *
 *   1. `byTopFrequency`：按 text 出現頻率排序、取 top N
 *   2. `byFontFamilyWhitelist`：caller 給 whitelist、只 prewarm 命中字型
 *   3. `byCharsetClassification`：判斷 text 屬於 CJK / Latin / mixed、依 caller 偏好取子集
 *
 * 紀律 #18 scope-down：
 *   - heuristic 為 caller 顯式選擇、不做自動 ML / Bayesian
 *   - 不接 production canvas-editor real path
 *   - 不快取 strategy 結果（每次 caller 重新算）
 *
 * 紀律 #21：pure-fn、純資料 transformation；不污染既有 pipeline。
 */

import type {
  DocumentNode,
  ParagraphNode,
  TableNode,
  BlockNode,
  RunNode,
} from '../ast/types';

export interface PrewarmEntry {
  text: string;
  family: string;
  sizePt: number;
}

export interface PrewarmEntryWithMeta extends PrewarmEntry {
  /** 該 (text, family, sizePt) 在 doc 出現次數 */
  frequency: number;
  /** Caller-side 推測 charset；charsetClassification 用 */
  charset?: 'cjk' | 'latin' | 'mixed' | 'empty';
}

/**
 * 列舉所有 unique (text, family, sizePt) + 出現次數 + charset 推測。
 *
 * Caller 拿到後可選擇用任一 strategy 過濾。
 */
export function collectPrewarmCandidates(
  doc: DocumentNode,
  defaultFamily: string,
  defaultSizePt: number,
): PrewarmEntryWithMeta[] {
  const buckets = new Map<string, PrewarmEntryWithMeta>();
  for (const section of doc.sections) {
    for (const block of section.body) {
      collectFromBlock(block, defaultFamily, defaultSizePt, buckets);
    }
  }
  return [...buckets.values()];
}

function collectFromBlock(
  b: BlockNode,
  defFam: string,
  defSize: number,
  buckets: Map<string, PrewarmEntryWithMeta>,
): void {
  if (b.type === 'paragraph') {
    collectFromParagraph(b, defFam, defSize, buckets);
  } else {
    for (const row of b.rows) {
      for (const cell of row.cells) {
        for (const inner of cell.content) collectFromBlock(inner, defFam, defSize, buckets);
      }
    }
  }
}

function collectFromParagraph(
  p: ParagraphNode,
  defFam: string,
  defSize: number,
  buckets: Map<string, PrewarmEntryWithMeta>,
): void {
  for (const r of p.runs) {
    if (r.type !== 'run') continue;
    const run = r as RunNode;
    if (!run.text) continue;
    const family = run.props.fontFamily ?? defFam;
    const sizePt = run.props.fontSize ?? defSize;
    const key = `${family}|${sizePt}|${run.text}`;
    const existing = buckets.get(key);
    if (existing) {
      existing.frequency++;
    } else {
      buckets.set(key, {
        text: run.text,
        family,
        sizePt,
        frequency: 1,
        charset: classifyCharset(run.text),
      });
    }
  }
}

/**
 * 簡單 charset 分類：
 *   - 全 CJK 字元（CJK 基本 + 擴展）→ 'cjk'
 *   - 全 Latin（ASCII 0-127）→ 'latin'
 *   - 混合（含 CJK + Latin）→ 'mixed'
 *   - 空字串 → 'empty'
 */
export function classifyCharset(text: string): 'cjk' | 'latin' | 'mixed' | 'empty' {
  if (text.length === 0) return 'empty';
  let hasCjk = false;
  let hasLatin = false;
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (isCjkCodePoint(cp)) hasCjk = true;
    else if (cp >= 0x20 && cp <= 0x7e) hasLatin = true;
  }
  if (hasCjk && hasLatin) return 'mixed';
  if (hasCjk) return 'cjk';
  if (hasLatin) return 'latin';
  return 'mixed';  // 非 ASCII 非 CJK（如阿拉伯、希伯來）視為 mixed
}

function isCjkCodePoint(cp: number): boolean {
  return (
    (cp >= 0x4e00 && cp <= 0x9fff) ||    // CJK Unified Ideographs
    (cp >= 0x3000 && cp <= 0x303f) ||    // CJK Symbols and Punctuation
    (cp >= 0x3400 && cp <= 0x4dbf) ||    // CJK Extension A
    (cp >= 0xff00 && cp <= 0xffef)       // Halfwidth and Fullwidth Forms
  );
}

// ── Strategies ───────────────────────────────────────────────────────────

/**
 * 按 frequency 降序排序、取 top N。
 *
 * - n 為 undefined → 全部回（同 collectPrewarmCandidates 排序後）
 * - n <= 0 → 空陣列
 */
export function byTopFrequency(
  candidates: ReadonlyArray<PrewarmEntryWithMeta>,
  n?: number,
): PrewarmEntryWithMeta[] {
  if (n !== undefined && n <= 0) return [];
  const sorted = [...candidates].sort((a, b) => b.frequency - a.frequency);
  return n === undefined ? sorted : sorted.slice(0, n);
}

/**
 * 取 family 在 whitelist 內的 candidates。
 *
 * - 空 whitelist → 空陣列
 */
export function byFontFamilyWhitelist(
  candidates: ReadonlyArray<PrewarmEntryWithMeta>,
  whitelist: ReadonlyArray<string>,
): PrewarmEntryWithMeta[] {
  if (whitelist.length === 0) return [];
  const set = new Set(whitelist);
  return candidates.filter((c) => set.has(c.family));
}

/**
 * 取符合指定 charset 的 candidates。
 *
 * - charsets 為空 → 空陣列
 * - 含 'mixed' → mixed + empty 都包
 */
export function byCharsetClassification(
  candidates: ReadonlyArray<PrewarmEntryWithMeta>,
  charsets: ReadonlyArray<'cjk' | 'latin' | 'mixed' | 'empty'>,
): PrewarmEntryWithMeta[] {
  if (charsets.length === 0) return [];
  const set = new Set(charsets);
  return candidates.filter((c) => c.charset !== undefined && set.has(c.charset));
}
