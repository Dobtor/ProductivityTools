/**
 * OmmlParser — 解析 OMML 數學公式（`m:` 命名空間、ECMA-376 §22.1、Phase 5.1）
 *
 * Sprint 179（capture）：
 *   Word 數學公式（「插入 → 方程式」）以 OMML（Office Math Markup Language）儲存，
 *   內嵌於 document.xml 的段落中：
 *     - 段落直屬 `<m:oMath>`                    → 行內公式（inline math）
 *     - 段落直屬 `<m:oMathPara><m:oMath>...`     → 獨立置中公式（display math）
 *
 *   OMML 結構元素（部分）：
 *     <m:f>   分數（<m:num> 分子 / <m:den> 分母）
 *     <m:rad> 根號（<m:deg> 次數 / <m:e> 被開方數）
 *     <m:nary> n 元運算子（求和 / 積分；<m:sub> 下限 / <m:sup> 上限 / <m:e> 主體）
 *     <m:sSub> / <m:sSup> / <m:sSubSup>  下標 / 上標 / 上下標
 *     <m:d>   括號分隔符（delimiter）
 *     <m:m>   矩陣（<m:mr> 列 / <m:e> 格）
 *     <m:r>   math run（含 <m:t> 文字）
 *
 * Sprint 179 以遞迴通用樹（OmmlNode）保留完整結構；Sprint 180 補 attrs 捕捉 +
 * `ommlToLinearText` 線性文字 fallback render（OMML → KaTeX 全保真留未來 optional）。
 *
 * 防禦：undefined / 無子元素 → 回空陣列 / 空字串（不 throw）。
 */

import type { OmmlNode } from '../ast/types';
import { directChildren } from '../utils/dom';

/** OMML 命名空間前綴。 */
const MATH_NS_PREFIX = 'm:';
/** OMML 文字葉節點標籤（去前綴後）。 */
const MATH_TEXT_TAG = 't';
/** OOXML §22.1.2.70：`<m:nary>` 的 `m:chr` 屬性預設值（積分符號 U+222B）。 */
const NARY_DEFAULT_CHAR = '∫';
/** `<m:d>` delimiter 的預設左右括號（OOXML §22.1.2.21/§22.1.2.36）。 */
const DELIM_DEFAULT_BEG = '(';
const DELIM_DEFAULT_END = ')';

/**
 * 把 OOXML 標籤名 / 屬性名去掉 `m:` 命名空間前綴，回傳 localName。
 * 無前綴則原樣回傳。
 */
function stripMathPrefix(name: string): string {
  return name.startsWith(MATH_NS_PREFIX) ? name.slice(MATH_NS_PREFIX.length) : name;
}

/**
 * 收集元素的屬性 → Record（key 去 `m:` 前綴）。無屬性回 undefined（紀律 #21）。
 */
function collectAttrs(el: Element): Record<string, string> | undefined {
  const attrs: Record<string, string> = {};
  let has = false;
  const list = el.attributes;
  for (let i = 0; i < list.length; i++) {
    const a = list[i];
    if (a.name.startsWith('xmlns')) continue; // 跳過命名空間宣告
    attrs[stripMathPrefix(a.name)] = a.value;
    has = true;
  }
  return has ? attrs : undefined;
}

/**
 * 遞迴解析 OMML 元素的子節點為 OmmlNode 樹。
 *
 * @param el `<m:oMath>` 或任一 OMML 結構元素
 * @returns 子節點的 OmmlNode 陣列；無元素子節點 → 空陣列
 */
export function parseOmmlChildren(el: Element | undefined | null): OmmlNode[] {
  if (!el) return [];
  const out: OmmlNode[] = [];
  for (const child of directChildren(el)) {
    const tag = stripMathPrefix(child.tagName);
    const node: OmmlNode = { tag };
    const attrs = collectAttrs(child);
    if (attrs) node.attrs = attrs;
    if (tag === MATH_TEXT_TAG) {
      // `<m:t>` 為文字葉節點（OOXML §22.1.2.116）
      node.text = child.textContent ?? '';
    } else {
      const kids = parseOmmlChildren(child);
      // 紀律 #21：無子節點不掛 key、避免 AST diff noise
      if (kids.length > 0) node.children = kids;
    }
    out.push(node);
  }
  return out;
}

// ── Sprint 180：線性文字 fallback render ─────────────────────────────────────

/** 找第一個 tag 相符的子節點。 */
function childByTag(node: OmmlNode, tag: string): OmmlNode | undefined {
  return node.children?.find((c) => c.tag === tag);
}

/** 取某子節點（依 tag）的線性文字；無此子節點回空字串。 */
function tagText(node: OmmlNode, tag: string): string {
  const c = childByTag(node, tag);
  return c ? linearizeNode(c) : '';
}

/**
 * 把單一 OmmlNode 遞迴轉為線性文字。
 *
 * capture-only fallback：不做版面排版，僅以線性符號近似（分數 a/b、根號 √(x)、
 * 上下標 x_(n)^(2)、矩陣 [a, b; c, d]）。全保真排版需 KaTeX、留未來 optional sprint。
 */
function linearizeNode(node: OmmlNode): string {
  switch (node.tag) {
    case 't':
      return node.text ?? '';
    case 'r': // math run：拼接內部 <m:t>
    case 'e': // 通用 element 容器
    case 'num':
    case 'den':
    case 'deg':
    case 'sub':
    case 'sup':
    case 'oMath':
      return linearizeChildren(node);
    case 'f': // 分數 num/den
      return `${tagText(node, 'num')}/${tagText(node, 'den')}`;
    case 'rad': { // 根號（deg 可選）
      const deg = tagText(node, 'deg');
      return `${deg}√(${tagText(node, 'e')})`;
    }
    case 'nary': { // n 元運算子（求和 / 積分）
      const chr = childByTag(node, 'naryPr')
        ? naryChar(childByTag(node, 'naryPr') as OmmlNode)
        : NARY_DEFAULT_CHAR;
      const sub = tagText(node, 'sub');
      const sup = tagText(node, 'sup');
      const body = tagText(node, 'e');
      return `${chr}${sub ? `_(${sub})` : ''}${sup ? `^(${sup})` : ''}(${body})`;
    }
    case 'sSub':
      return `${tagText(node, 'e')}_(${tagText(node, 'sub')})`;
    case 'sSup':
      return `${tagText(node, 'e')}^(${tagText(node, 'sup')})`;
    case 'sSubSup':
      return `${tagText(node, 'e')}_(${tagText(node, 'sub')})^(${tagText(node, 'sup')})`;
    case 'd': { // delimiter 括號
      const pr = childByTag(node, 'dPr');
      const beg = pr?.attrs?.begChr ?? DELIM_DEFAULT_BEG;
      const end = pr?.attrs?.endChr ?? DELIM_DEFAULT_END;
      return `${beg}${linearizeChildren(node)}${end}`;
    }
    case 'm': { // 矩陣：mr 列以 ; 分隔、e 格以 , 分隔
      const rows = (node.children ?? [])
        .filter((c) => c.tag === 'mr')
        .map((mr) =>
          (mr.children ?? [])
            .filter((c) => c.tag === 'e')
            .map((e) => linearizeNode(e))
            .join(', '),
        );
      return `[${rows.join('; ')}]`;
    }
    case 'rPr':
    case 'ctrlPr':
    case 'naryPr':
    case 'fPr':
    case 'dPr':
    case 'radPr':
    case 'mPr':
      return ''; // 屬性容器、不產生文字
    default:
      // 未明列的結構元素 → 遞迴拼接子節點（盡力 fallback）
      return linearizeChildren(node);
  }
}

/** 從 `<m:naryPr>` 取運算子字元（`<m:chr m:val>`），缺則用預設積分符號。 */
function naryChar(naryPr: OmmlNode): string {
  return childByTag(naryPr, 'chr')?.attrs?.val ?? NARY_DEFAULT_CHAR;
}

/** 拼接一節點所有子節點的線性文字。 */
function linearizeChildren(node: OmmlNode): string {
  return (node.children ?? []).map((c) => linearizeNode(c)).join('');
}

/**
 * 把 `<m:oMath>` 的 OmmlNode 樹轉為線性文字 fallback。
 *
 * @param omml `MathNode.omml`（`<m:oMath>` 子元素樹）
 * @returns 線性文字近似；空樹 → 空字串
 */
export function ommlToLinearText(omml: OmmlNode[]): string {
  return omml.map((n) => linearizeNode(n)).join('');
}
