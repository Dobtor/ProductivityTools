/**
 * borderShading — 共用的 `<w:bdr>` / `<w:tcBorders>` / `<w:tblBorders>` / `<w:pBdr>`
 * 邊框解析 + `<w:shd>` 陰影解析 utility（Sprint 133 從 TableParser 抽出）。
 *
 * 由 TableParser（cell/table borders + cell shading）、ParagraphParser（pBdr + shd）、
 * 未來 BorderConflictResolver 共用。集中後 BorderDef shape 變更只需一處同步。
 *
 * 參考：
 *   - ECMA-376 Part 1 §17.4.65 (tblBorders) / §17.4.66 (tcBorders) / §17.3.1.24 (pBdr)
 *   - ECMA-376 Part 1 §17.18.97 (shd)
 *   - 單位：w:sz 為 1/8 pt（eighthPointToPt）；w:space 為 pt 整數
 */

import type { BorderDef, BorderStyle, HexColor } from '../ast/types';
import { eighthPointToPt } from '../units/units';

/**
 * 解析單一邊 `<w:top>` / `<w:bottom>` / `<w:left>` / `<w:right>` / `<w:insideH>` / ... 為 BorderDef。
 *
 * - `w:val` 缺則回 undefined（OOXML 規範：無 val 視為「不指定」）
 * - `w:sz` 缺則 width = 0（仍視為合法 border，由 caller 判斷是否渲染）
 * - `w:color="auto"` 保留為字面值 'auto'、不轉成具體 hex（caller 決定 default）
 * - `w:space` 缺則回 undefined（不掛 key）
 *
 * @param el 邊框子元素（`<w:top>` 等）
 * @returns BorderDef 或 undefined（無 val）
 */
export function parseBorderDef(el: Element): BorderDef | undefined {
  const valRaw = el.getAttribute('w:val');
  if (!valRaw) return undefined;
  const style: BorderStyle = valRaw;

  let width = 0;
  const szRaw = el.getAttribute('w:sz');
  if (szRaw !== null) {
    const n = parseInt(szRaw, 10);
    if (Number.isFinite(n)) width = eighthPointToPt(n);
  }
  const colorRaw = el.getAttribute('w:color');
  const color: HexColor = colorRaw ?? 'auto';
  const out: BorderDef = { style, width, color };

  const spaceRaw = el.getAttribute('w:space');
  if (spaceRaw !== null) {
    const n = parseInt(spaceRaw, 10);
    if (Number.isFinite(n)) out.space = n;
  }
  return out;
}

/**
 * 解析 `<w:shd w:val="clear" w:fill="DEEAF6" w:color="auto"/>` 為 shading 物件。
 *
 * - 三屬性都缺則 caller 拿到空物件、自行決定是否視為「無 shading」
 * - 'auto' 保留為字面值（與 parseBorderDef 一致）
 *
 * @param el `<w:shd>` 元素
 * @returns shading 物件（含 fill / color / pattern，缺則該 key 不掛）
 */
export function parseShading(el: Element): {
  fill?: HexColor;
  color?: HexColor;
  pattern?: string;
} {
  const out: { fill?: HexColor; color?: HexColor; pattern?: string } = {};
  const fill = el.getAttribute('w:fill');
  const color = el.getAttribute('w:color');
  const pattern = el.getAttribute('w:val');
  if (fill) out.fill = fill;
  if (color) out.color = color;
  if (pattern) out.pattern = pattern;
  return out;
}

/**
 * 解析段落邊框 `<w:pBdr>` 為 ParagraphProps.borders 子集（top / bottom / left / right）。
 *
 * Sprint 133 起 ParagraphParser 用此 helper；
 * 與 cell/table borders 共用 parseBorderDef 但段落邊框只有 4 邊（無 insideH/insideV）。
 *
 * @param pBdr `<w:pBdr>` 元素
 * @returns borders 物件（缺邊則該 key 不掛；全空回 undefined）
 */
export function parseParagraphBorders(
  pBdr: Element,
): { top?: BorderDef; bottom?: BorderDef; left?: BorderDef; right?: BorderDef } | undefined {
  const out: {
    top?: BorderDef;
    bottom?: BorderDef;
    left?: BorderDef;
    right?: BorderDef;
  } = {};
  for (const child of directChildren(pBdr)) {
    const def = parseBorderDef(child);
    if (!def) continue;
    switch (child.tagName) {
      case 'w:top':
        out.top = def;
        break;
      case 'w:bottom':
        out.bottom = def;
        break;
      case 'w:left':
      case 'w:start':
        out.left = def;
        break;
      case 'w:right':
      case 'w:end':
        out.right = def;
        break;
      // 注意：段落 w:pBdr 也可包 between / bar，但這兩種屬「段落間 / 邊欄」
      // 不對應 ParagraphProps.borders 4 邊；defer 未來 sprint
    }
  }
  if (!out.top && !out.bottom && !out.left && !out.right) return undefined;
  return out;
}

/** 內部：直接子節點（Element）走訪。獨立於 dom.ts 避免 cross-layer dependency */
function directChildren(el: Element): Element[] {
  const out: Element[] = [];
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}
