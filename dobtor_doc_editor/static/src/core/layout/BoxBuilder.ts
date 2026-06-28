/**
 * BoxBuilder — ParagraphNode → ParagraphInput（LayoutItem[]）
 *
 * 設計：
 *   每個 RunNode 拆成「文字 Box + 中間 Glue」串列：
 *     - 西文：以空白為分割點，產出 "word" Box + space Glue
 *     - CJK：每個字元獨立 Box，前後加 zero-width Glue（可在任何字元間斷行）
 *     - 半形數字 / 連續英文：當作一個 Box（不可拆）
 *
 *   InlineImage 一律當作不可拆的 Box（width = image width）。
 *   Break(line) 轉為強制斷點（Penalty cost = -Infinity）。
 *   Break(page) Sprint 2 暫不支援（LayoutEngine 在段落層級處理）。
 *
 * 不在本 Sprint 範圍：
 *   - hyphenation（連字符斷字）
 *   - 字距 kerning（字型 GPOS table）
 *   - bidi（雙向文字 LTR/RTL 混排）
 */

import type {
  ParagraphNode,
  RunNode,
  RunProps,
  Pt,
  HyperlinkInfo,
  FieldNode,
} from '../ooxml/ast/types';
import type { Box, Glue, LayoutItem, ParagraphInput, TextMetrics } from './types';
import { EstimateMetrics, isCjkChar } from './TextMetrics';

const DEFAULT_FONT_SIZE_PT = 10.5;

/**
 * Sprint 139：numbering 段落前綴規格（caller 用 numberingFormatter 計算後傳入）。
 *
 * `text` 為展開後字串（如「1.」「（一）」「第一章」）；`runProps` 控制字型風格。
 * BoxBuilder 收到後在 items 開頭 push 字元 Box + tab Glue（OOXML 預設 lvlText suffix）。
 *
 * 為什麼設計成 caller 算 prefix：counter state 需跨段落演化，由 caller（Paginator/TableLayout）
 * 持有 NumberingCounterState 較合適；buildParagraph 保持純函式特性。
 */
export interface NumberingPrefix {
  text: string;
  runProps: RunProps;
}

/** 把單一 ParagraphNode 拆成 LayoutItem[]。*/
export function buildParagraph(
  para: ParagraphNode,
  sourceIndex: number,
  metrics: TextMetrics = new EstimateMetrics(),
  numberingPrefix?: NumberingPrefix,
): ParagraphInput {
  const items: LayoutItem[] = [];

  // 段落層級的預設 fontSize（取首個 RunProps 或 default）
  let defaultFontSize = DEFAULT_FONT_SIZE_PT;
  for (const r of para.runs) {
    if (r.type === 'run' && typeof r.props.fontSize === 'number') {
      defaultFontSize = r.props.fontSize;
      break;
    }
  }

  // Sprint 139：在段首 emit numbering 前綴 Box + tab Glue（若有）
  if (numberingPrefix && numberingPrefix.text !== '') {
    pushTextAsBoxes(items, numberingPrefix.text, numberingPrefix.runProps, undefined, undefined, metrics);
    // tab：用 space Glue 佔位（與 BoxBuilder 對 \t 既有處理一致）
    const tabWidth = metrics.measureWidth(' ', numberingPrefix.runProps);
    items.push(spaceGlue(tabWidth));
  }

  for (const run of para.runs) {
    if (run.type === 'run') {
      pushRunItems(items, run, metrics);
    } else if (run.type === 'inlineImage') {
      // Sprint 8：inline 圖片轉成不可斷的 Box
      // Sprint 40：propagate srcRect 到 Box（renderLine 處 dispatch 給 RenderContext.drawImage）
      const box: import('./types').Box = {
        kind: 'box',
        width: run.width,
        height: run.height,
        text: `image:${run.rId}`,
        runProps: { fontSize: defaultFontSize },
        isImage: true,
        imageRId: run.rId,
      };
      if (run.srcRect) box.imageSrcRect = run.srcRect;
      items.push(box);
    } else if (run.type === 'floatImage') {
      // Sprint 37：floatImage 由 caller（Paginator.layParagraph 或 TableLayout.layoutCell）
      // 先 filter 出來、單獨處理 abs position；BoxBuilder 看到時應為 unreachable。
      // 保留 no-op 防呆：若 caller 漏 filter，至少不要把 anchor 當 inline Box 推進段內
      // （Sprint 36 grid analysis 找到的 03 全套管 5 fixture × 0.30 真根因 = 此 silent fall-through）。
    } else if (run.type === 'break') {
      if (run.breakType === 'line') {
        // 強制斷行：penalty cost -Infinity（不換頁/欄）
        items.push({ kind: 'penalty', width: 0, cost: -Infinity });
      } else if (run.breakType === 'page') {
        items.push({
          kind: 'penalty', width: 0, cost: -Infinity, flagged: true, breakKind: 'page',
        });
      } else if (run.breakType === 'column') {
        // Sprint 7：column break 真正觸發 Paginator nextColumnOrPage
        items.push({
          kind: 'penalty', width: 0, cost: -Infinity, flagged: true, breakKind: 'column',
        });
      }
    } else if (run.type === 'field') {
      // 欄位（PAGE / DATE 等）— 整個 field 視為一個不可拆 Box，記錄 fieldType
      // 讓 Paginator post-pass 能精準回填 PAGE / NUMPAGES 真值
      const text = run.cachedValue ?? defaultFieldPlaceholder(run.fieldType);
      const props: RunProps = { fontSize: defaultFontSize };
      const w = metrics.measureWidth(text, props);
      const h = metrics.measureLineHeight(props);
      items.push({
        kind: 'box', text, width: w, height: h, runProps: props,
        fieldType: run.fieldType,
      });
    }
  }

  return {
    items,
    props: para.props,
    defaultFontSize,
    styleId: para.styleId,
    sourceIndex,
  };
}

// ── 內部 helpers ────────────────────────────────────────────────────────

function pushRunItems(
  out: LayoutItem[],
  run: RunNode,
  metrics: TextMetrics,
): void {
  if (!run.text) return;
  pushTextAsBoxes(out, run.text, run.props, run.hyperlink, run.revision, metrics);
}

/**
 * 文字 → Box + Glue 串列。
 *
 * Algorithm:
 *   - 走訪每個字元（含 surrogate pair）
 *   - CJK 字元：直接成 Box，前後插 zero-width glue（可斷點）
 *   - Latin / 數字：累積到 currentToken，遇空白吐出 + 加 space glue
 *   - 全形標點：成 Box，前後 zero-width glue
 */
function pushTextAsBoxes(
  out: LayoutItem[],
  text: string,
  props: RunProps,
  hyperlink: HyperlinkInfo | undefined,
  revision: import('../ooxml/ast/types').RunRevision | undefined,
  metrics: TextMetrics,
): void {
  const fontSize = props.fontSize ?? DEFAULT_FONT_SIZE_PT;
  const lineHeight = metrics.measureLineHeight(props);

  let buffer = ''; // 累積中的西文 token

  const flushBuffer = (): void => {
    if (!buffer) return;
    const w = metrics.measureWidth(buffer, props);
    out.push(boxOf(buffer, w, lineHeight, props, hyperlink, revision));
    buffer = '';
  };

  // 用 Array.from 安全處理 surrogate pair
  const chars = Array.from(text);
  for (const ch of chars) {
    const code = ch.charCodeAt(0);
    if (code === 0x20 || code === 0x09) {
      // 空白 / tab：吐 buffer，加 space glue
      // Sprint 161：tab（0x09）以空白寬度建立但標記 isTab；
      //   寬度於 LineBreaker 在有 defaultTabStop 時才重算（不破 baseline）。
      flushBuffer();
      const spaceWidth = metrics.measureWidth(' ', props);
      const glue = spaceGlue(spaceWidth);
      if (code === 0x09) glue.isTab = true;
      out.push(glue);
    } else if (isCjkChar(ch)) {
      // CJK：吐 buffer，加 zero-width glue（可斷點），插字元 Box，再加一個 zero-width glue
      flushBuffer();
      // 前 glue 由前一個 CJK 提供；這裡只插字元 Box + 後 glue
      const w = metrics.measureWidth(ch, props);
      out.push(boxOf(ch, w, lineHeight, props, hyperlink, revision));
      out.push(cjkBreakGlue());
    } else {
      // Latin / 數字 / 半形標點：累積
      buffer += ch;
    }
  }
  flushBuffer();
}

function boxOf(
  text: string,
  width: Pt,
  height: Pt,
  props: RunProps,
  hyperlink: HyperlinkInfo | undefined,
  revision?: import('../ooxml/ast/types').RunRevision,
): Box {
  const box: Box = { kind: 'box', text, width, height, runProps: props, hyperlink };
  if (revision) box.revision = revision;
  return box;
}

function spaceGlue(width: Pt): Glue {
  // 空白 stretch / shrink 比例：撐到 1.5x、可壓縮到 0.7x
  return { kind: 'glue', width, stretch: width * 0.5, shrink: width * 0.3 };
}

function cjkBreakGlue(): Glue {
  // 中文字間：zero-width，但是合法斷點（LineBreaker 看 isCjkBreak）
  return { kind: 'glue', width: 0, stretch: 0, shrink: 0, isCjkBreak: true };
}

/**
 * Sprint 10：欄位 placeholder 文字（沒有 cachedValue 時用）。
 * Sprint 163：param 型別對齊 AST `FieldNode['fieldType']`（11 型）。
 * SEQ/TOC/REF/HYPERLINK/STYLEREF/unknown 走 default 分支 → `{<type>}`
 * （與 Sprint 0-162 runtime 行為一致、純型別擴展不改輸出）。
 */
function defaultFieldPlaceholder(fieldType: FieldNode['fieldType']): string {
  switch (fieldType) {
    case 'PAGE': return '##';
    case 'NUMPAGES': return '##';
    case 'DATE': return 'YYYY/MM/DD';
    case 'TIME': return 'HH:MM';
    case 'AUTHOR': return 'Author';
    case 'FILENAME': return 'Filename';
    default: return `{${fieldType}}`;
  }
}
