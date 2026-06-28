/**
 * serializeOps — 把 RenderOp[] 序列化為 deterministic JSON（Sprint 12）
 *
 * 目的：
 *   把 MockRenderContext 收集到的繪圖指令序列化成穩定 JSON 格式，
 *   方便：
 *     - fixture-level regression（commit 為 golden trace，CI 比對）
 *     - 跨 sprint 觀察 Renderer 輸出變化（哪頁多/少了什麼指令）
 *     - 偵錯：把 ops 重放到 BrowserCanvasRenderContext 即可重現視覺
 *
 * 設計：
 *   - 數字四捨五入到 0.01pt（避免浮點微擾造成 trace diff）
 *   - 每 op 一行 JSON（newline-delimited），diff 友善
 *   - color 統一大寫 HEX
 *   - ops 陣列按 ctx 收集順序保留（不重排）
 *
 * 不在 Sprint 12 範圍：
 *   - PNG diff（仍需要 puppeteer + canvas-editor / BrowserCanvasRenderContext）
 *   - 跨平台字型差異容忍
 */

import type { RenderOp } from './MockRenderContext';

export interface SerializeOpsOptions {
  /** 數字四捨五入位數，預設 2（0.01pt 精度）。傳 0 = 整數。 */
  precision?: number;
}

/**
 * 把 ops 陣列序列化為陣列形式的 JSON-friendly 物件，可直接 JSON.stringify。
 *
 * @returns 結構化 op 陣列（每 op 是 plain object，數字已四捨五入）
 */
export function serializeOps(ops: RenderOp[], opts: SerializeOpsOptions = {}): unknown[] {
  const p = opts.precision ?? 2;
  return ops.map((op) => normalizeOp(op, p));
}

/** 每 op 一行 JSON（newline-delimited）。 */
export function serializeOpsToNdjson(ops: RenderOp[], opts: SerializeOpsOptions = {}): string {
  return serializeOps(ops, opts).map((o) => JSON.stringify(o)).join('\n');
}

/** Pretty print 整體為 JSON（diff 友善的多行格式）。 */
export function serializeOpsToJson(ops: RenderOp[], opts: SerializeOpsOptions = {}): string {
  return JSON.stringify(serializeOps(ops, opts), null, 2);
}

function normalizeOp(op: RenderOp, p: number): Record<string, unknown> {
  const round = (n: number): number => roundTo(n, p);
  switch (op.kind) {
    case 'beginPage':
      return { kind: 'beginPage', pageNumber: op.pageNumber, w: round(op.width), h: round(op.height) };
    case 'endPage':
      return { kind: 'endPage' };
    case 'fillRect':
      return {
        kind: 'fillRect',
        x: round(op.x), y: round(op.y), w: round(op.width), h: round(op.height),
        color: normColor(op.color),
      };
    case 'drawLine':
      return {
        kind: 'drawLine',
        x1: round(op.x1), y1: round(op.y1), x2: round(op.x2), y2: round(op.y2),
        color: normColor(op.style.color),
        width: round(op.style.width),
        ...(op.style.style ? { style: op.style.style } : {}),
      };
    case 'fillText':
      return {
        kind: 'fillText',
        text: op.text,
        x: round(op.x), y: round(op.y),
        fontSize: round(op.style.fontSize),
        ...(op.style.fontFamily ? { fontFamily: op.style.fontFamily } : {}),
        ...(op.style.bold ? { bold: true } : {}),
        ...(op.style.italic ? { italic: true } : {}),
        ...(op.style.color ? { color: normColor(op.style.color) } : {}),
        ...(op.style.underline && op.style.underline !== 'none' ? { underline: op.style.underline } : {}),
        ...(op.style.strike ? { strike: true } : {}),
        ...(op.style.highlight ? { highlight: normColor(op.style.highlight) } : {}),
      };
    case 'drawImage':
      return {
        kind: 'drawImage', href: op.href,
        x: round(op.x), y: round(op.y), w: round(op.width), h: round(op.height),
      };
    case 'save':
      return { kind: 'save' };
    case 'restore':
      return { kind: 'restore' };
    case 'translate':
      return { kind: 'translate', dx: round(op.dx), dy: round(op.dy) };
    case 'rotate':
      return { kind: 'rotate', rad: round(op.rad) };
  }
}

function roundTo(n: number, p: number): number {
  if (!isFinite(n)) return n;
  const f = Math.pow(10, p);
  return Math.round(n * f) / f;
}

function normColor(c: string): string {
  if (!c) return '000000';
  return c.replace(/^#/, '').toUpperCase();
}

/**
 * 計算 ops 的「指紋」：每類 op 的計數 + 文字長度總和。
 *
 * 用於快速比對：fingerprint 不變代表結構穩定（雖細節仍可能變）。
 * Regression 報告用，可以早於完整 diff 之前發出 alert。
 */
export interface OpsFingerprint {
  total: number;
  byKind: Record<RenderOp['kind'], number>;
  textCharCount: number;
  /** 唯一文字內容雜湊（不含位置）— 用 fnv-1a 32bit */
  textHash: string;
}

export function fingerprintOps(ops: RenderOp[]): OpsFingerprint {
  // Sprint 34：byKind 加入 save/restore/translate/rotate（垂直文字 cell 旋轉用）
  const byKind: Record<RenderOp['kind'], number> = {
    beginPage: 0, endPage: 0, fillRect: 0, drawLine: 0, fillText: 0, drawImage: 0,
    save: 0, restore: 0, translate: 0, rotate: 0,
  };
  let textCharCount = 0;
  let h = 0x811c9dc5; // fnv-1a offset basis
  for (const op of ops) {
    byKind[op.kind]++;
    if (op.kind === 'fillText') {
      textCharCount += op.text.length;
      for (let i = 0; i < op.text.length; i++) {
        h ^= op.text.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
      }
    }
  }
  return {
    total: ops.length,
    byKind,
    textCharCount,
    textHash: (h >>> 0).toString(16).padStart(8, '0'),
  };
}
