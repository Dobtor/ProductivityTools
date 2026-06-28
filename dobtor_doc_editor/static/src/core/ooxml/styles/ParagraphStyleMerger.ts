/**
 * ParagraphStyleMerger — Sprint 19
 *
 * 把 styles.xml 解析後的 StyleEntry.pProps 合併進 ParagraphNode.props。
 *
 * 為什麼：
 *   - ParagraphParser 只解析 inline `<w:pPr>` 內的屬性
 *   - 但 OOXML 規格容許段落只透過 `<w:pStyle w:val="X"/>` 引用 styles.xml 中的
 *     pPr 預設值（如 keepNext / spacing / fontSize 等）
 *   - 沒這層合併，下游 Paginator 看不到 style-defined keepNext，無法做 R6 黏連判斷
 *
 * 合併規則（與 StyleResolver.mergePProps 一致）：
 *   - inline props 覆寫 style props（per-key）
 *   - 巢狀物件 indent / spacing / borders / shading 做淺合併
 *   - 未被 inline 覆寫的 style key 會落到 paragraph.props
 *
 * 範圍：
 *   - 走訪 sections[*].body 與 cell.content（遞迴入 nested table）
 *   - 不處理 header / footer 的段落（HeaderFooterContent.content）— Sprint 19 範圍
 *     先聚焦 main body；header/footer 樣式合併留 Sprint 20+
 */

import type {
  BlockNode,
  DocumentNode,
  ParagraphNode,
  ParagraphProps,
  StyleMap,
} from '../ast/types';

/**
 * 對 DocumentNode 的所有 body 段落 in-place 合併樣式。
 *
 * 特性：
 *   - mutate paragraph.props（不複製整個 AST）
 *   - 沒有 styleId、或對應 style 不存在 → 跳過
 *   - 對應 style.pProps 為 undefined → 跳過
 *
 * @returns 處理過的段落數量（debug 用）
 */
export function mergeParagraphStyles(doc: DocumentNode): number {
  if (doc.styles.size === 0) return 0;
  let count = 0;
  for (const sec of doc.sections) {
    count += mergeBlocks(sec.body, doc.styles);
  }
  return count;
}

function mergeBlocks(blocks: BlockNode[], styles: StyleMap): number {
  let count = 0;
  for (const block of blocks) {
    if (block.type === 'paragraph') {
      if (mergeParagraph(block, styles)) count++;
    } else if (block.type === 'table') {
      for (const row of block.rows) {
        for (const cell of row.cells) {
          if (cell.content) count += mergeBlocks(cell.content, styles);
        }
      }
    }
  }
  return count;
}

/**
 * 對單一段落合併樣式。回 true 表示有實際合併動作。
 *
 * 規則：
 *   - 沒 styleId → 跳過
 *   - 樣式不存在 → 跳過
 *   - 樣式無 pProps → 跳過
 *   - 否則：para.props = mergePProps(stylePProps, para.props)
 */
function mergeParagraph(para: ParagraphNode, styles: StyleMap): boolean {
  if (!para.styleId) return false;
  const styleEntry = styles.get(para.styleId);
  if (!styleEntry || !styleEntry.pProps) return false;
  para.props = mergePProps(styleEntry.pProps, para.props);
  return true;
}

/**
 * pProps merge：override（inline）覆寫 base（style）。
 *
 * 與 StyleResolver.mergePProps 邏輯一致；複製到此檔案避免循環依賴
 * （StyleResolver import ParagraphParser；ParagraphStyleMerger 只 import types）。
 */
export function mergePProps(
  base: ParagraphProps,
  override: ParagraphProps,
): ParagraphProps {
  const out: ParagraphProps = { ...base };
  for (const key of Object.keys(override) as (keyof ParagraphProps)[]) {
    const v = override[key];
    if (v === undefined) continue;
    if (key === 'indent' || key === 'spacing' || key === 'borders' || key === 'shading') {
      const baseSub = (base[key] ?? {}) as Record<string, unknown>;
      const overSub = v as Record<string, unknown>;
      (out[key] as unknown) = { ...baseSub, ...overSub };
    } else {
      (out[key] as unknown) = v;
    }
  }
  return out;
}
