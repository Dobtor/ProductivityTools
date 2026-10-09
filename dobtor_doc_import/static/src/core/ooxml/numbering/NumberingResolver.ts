/**
 * NumberingResolver — word/numbering.xml 多層次清單編號
 *
 * 解析鏈：
 *   <w:num numId="N"> → <w:abstractNumId w:val="M"> → <w:abstractNum abstractNumId="M">
 *
 * 演算法：
 *   1. 第一遍走訪 <w:abstractNum> 收集 levels（ilvl 0–8）
 *   2. 第二遍走訪 <w:num>：解析 abstractNumId 與 lvlOverride
 *      - 把對應 abstractNum 的 levels copy 一份
 *      - 套用 lvlOverride（可能改 startOverride 或整層 lvl 內容）
 *   3. 產出 NumberingMap = Map<numId, AbstractNumbering>
 *
 * 注意：
 *   - 缺失的 abstractNumId 視為空 levels（不 throw）
 *   - 缺失的 ilvl 對應 level 視為 placeholder（numFmt='none', text='', start=1）
 *   - <w:lvlText val="%1.%2."> 模板字串原樣保留，由 Renderer 在 Layout 階段展開
 *
 * Phase B.2 範圍 — 全 numFmt 支援：decimal / lowerLetter / upperLetter /
 *   lowerRoman / upperRoman / bullet / chineseCounting / japaneseCounting / ordinal /
 *   ordinalText / cardinalText / iroha / aiueo / taiwaneseCounting / ideographDigital /
 *   chineseLegalSimplified（透傳，由 Renderer 解碼為實際數字）
 */

import type {
  AbstractNumbering,
  NumberingLevel,
  NumberingMap,
  ParagraphProps,
  Pt,
  RunProps,
} from '../ast/types';
import { parseParagraphProps, parseRunProps } from '../document/ParagraphParser';
// twip → pt 轉換已由 parseParagraphProps 內部處理，本檔不直接呼叫

interface RawLvlOverride {
  ilvl: number;
  /** 整層 lvl 內容覆蓋（如果 lvlOverride 內含 <w:lvl>）*/
  level?: NumberingLevel;
  /** 僅覆蓋起始值 */
  startOverride?: number;
}

interface RawNum {
  numId: number;
  abstractNumId: number;
  overrides: RawLvlOverride[];
}

export class NumberingResolver {
  /**
   * 解析 numbering.xml 字串為 NumberingMap。
   *
   * @param xml word/numbering.xml 內容；undefined 時回空 Map
   */
  resolve(xml: string | undefined): NumberingMap {
    if (!xml) return new Map();
    const doc = parseXml(xml);
    const root = doc.documentElement;
    if (!root) return new Map();

    // Step 1：abstractNum
    const abstractByM = new Map<number, AbstractNumbering>();
    const abstractEls = root.getElementsByTagName('w:abstractNum');
    for (let i = 0; i < abstractEls.length; i++) {
      const an = parseAbstractNum(abstractEls[i]);
      if (an) abstractByM.set(an.abstractNumId, an);
    }

    // Step 2：num（含 lvlOverride）
    const out: NumberingMap = new Map();
    const numEls = root.getElementsByTagName('w:num');
    for (let i = 0; i < numEls.length; i++) {
      const raw = parseRawNum(numEls[i]);
      if (!raw) continue;
      const baseAbstract = abstractByM.get(raw.abstractNumId);
      const resolved = applyOverrides(raw, baseAbstract);
      out.set(raw.numId, resolved);
    }
    return out;
  }
}

// ── <w:abstractNum> 解析 ─────────────────────────────────────────────────────

function parseAbstractNum(el: Element): AbstractNumbering | undefined {
  const idRaw = el.getAttribute('w:abstractNumId');
  if (!idRaw) return undefined;
  const abstractNumId = parseInt(idRaw, 10);
  if (!Number.isFinite(abstractNumId)) return undefined;

  const levels: NumberingLevel[] = [];
  const lvlEls = el.getElementsByTagName('w:lvl');
  for (let i = 0; i < lvlEls.length; i++) {
    // 注意：abstractNum > lvl 是直接子；不會在 lvlOverride 內嵌套（那走另一個 path）
    // 用 parentNode 判斷是否為直接 lvl
    const parent = lvlEls[i].parentNode as Element | null;
    if (!parent || parent.tagName !== 'w:abstractNum') continue;
    const level = parseLvl(lvlEls[i]);
    if (level) levels.push(level);
  }

  // 確保 ilvl 索引正確排序
  levels.sort((a, b) => a.ilvl - b.ilvl);

  return { abstractNumId, levels };
}

// ── <w:lvl> 解析 ─────────────────────────────────────────────────────────────

function parseLvl(lvlEl: Element): NumberingLevel | undefined {
  const ilvlRaw = lvlEl.getAttribute('w:ilvl');
  if (!ilvlRaw) return undefined;
  const ilvl = parseInt(ilvlRaw, 10);
  if (!Number.isFinite(ilvl)) return undefined;

  let numFmt = 'decimal';
  let text = '';
  let start = 1;
  let lvlRestart: number | undefined;
  let indent: { left?: Pt; hanging?: Pt } | undefined;
  let runProps: RunProps | undefined;
  let pProps: Partial<ParagraphProps> | undefined;
  let isLegal: boolean | undefined;

  for (const child of directChildren(lvlEl)) {
    switch (child.tagName) {
      case 'w:start': {
        const v = child.getAttribute('w:val');
        const n = v ? parseInt(v, 10) : NaN;
        if (Number.isFinite(n)) start = n;
        break;
      }
      case 'w:numFmt': {
        const v = child.getAttribute('w:val');
        if (v) numFmt = v;
        break;
      }
      case 'w:lvlText': {
        const v = child.getAttribute('w:val');
        if (v !== null) text = v;
        break;
      }
      case 'w:lvlRestart': {
        const v = child.getAttribute('w:val');
        const n = v ? parseInt(v, 10) : NaN;
        if (Number.isFinite(n)) lvlRestart = n;
        break;
      }
      case 'w:isLgl': {
        const v = child.getAttribute('w:val');
        isLegal = v === null ? true : v !== '0' && v.toLowerCase() !== 'false';
        break;
      }
      case 'w:pPr': {
        const ppFull = parseParagraphProps(child);
        // 抽出 indent 給專屬欄位，其餘合併到 pProps
        if (ppFull.indent) {
          indent = {};
          if (ppFull.indent.left !== undefined) indent.left = ppFull.indent.left;
          if (ppFull.indent.hanging !== undefined) indent.hanging = ppFull.indent.hanging;
          // firstLine / right 仍保留在 pProps（給段落整體用）
          const { left: _l, hanging: _h, ...rest } = ppFull.indent;
          if (Object.keys(rest).length > 0) {
            pProps = { ...(pProps ?? {}), indent: rest };
          }
        }
        // pPr 其他欄位（jc / spacing 等）合併到 pProps
        const rest = { ...ppFull };
        delete rest.indent;
        if (Object.keys(rest).length > 0) {
          pProps = { ...(pProps ?? {}), ...rest };
        }
        break;
      }
      case 'w:rPr':
        runProps = parseRunProps(child);
        break;
    }
  }

  const out: NumberingLevel = { ilvl, numFmt, text, start };
  if (lvlRestart !== undefined) out.lvlRestart = lvlRestart;
  if (indent && Object.keys(indent).length > 0) out.indent = indent;
  if (runProps) out.runProps = runProps;
  if (pProps && Object.keys(pProps).length > 0) out.pProps = pProps;
  if (isLegal) out.isLegal = isLegal;

  // 將 indent 中 hanging 用 twipToPt 已在 parseParagraphProps 處理過 — 這裡不需再轉
  // （parseParagraphProps 內部呼叫 attrTwip）

  return out;
}

// ── <w:num> 解析（含 lvlOverride）─────────────────────────────────────────────

function parseRawNum(numEl: Element): RawNum | undefined {
  const idRaw = numEl.getAttribute('w:numId');
  if (!idRaw) return undefined;
  const numId = parseInt(idRaw, 10);
  if (!Number.isFinite(numId)) return undefined;

  let abstractNumId = -1;
  const overrides: RawLvlOverride[] = [];

  for (const child of directChildren(numEl)) {
    if (child.tagName === 'w:abstractNumId') {
      const v = child.getAttribute('w:val');
      const n = v ? parseInt(v, 10) : NaN;
      if (Number.isFinite(n)) abstractNumId = n;
    } else if (child.tagName === 'w:lvlOverride') {
      const ov = parseLvlOverride(child);
      if (ov) overrides.push(ov);
    }
  }

  if (abstractNumId < 0) return undefined;
  return { numId, abstractNumId, overrides };
}

function parseLvlOverride(el: Element): RawLvlOverride | undefined {
  const ilvlRaw = el.getAttribute('w:ilvl');
  if (!ilvlRaw) return undefined;
  const ilvl = parseInt(ilvlRaw, 10);
  if (!Number.isFinite(ilvl)) return undefined;

  const out: RawLvlOverride = { ilvl };
  for (const child of directChildren(el)) {
    if (child.tagName === 'w:startOverride') {
      const v = child.getAttribute('w:val');
      const n = v ? parseInt(v, 10) : NaN;
      if (Number.isFinite(n)) out.startOverride = n;
    } else if (child.tagName === 'w:lvl') {
      const lvl = parseLvl(child);
      if (lvl) out.level = lvl;
    }
  }
  return out;
}

// ── 套用 overrides ───────────────────────────────────────────────────────────

function applyOverrides(
  raw: RawNum,
  base: AbstractNumbering | undefined,
): AbstractNumbering {
  // 缺失 abstract 仍輸出空殼
  if (!base) {
    return { abstractNumId: raw.abstractNumId, levels: [] };
  }

  // 拷貝 levels（對 NumberingLevel 做淺 copy 即可，避免污染原 abstract）
  const levels: NumberingLevel[] = base.levels.map((l) => ({ ...l }));

  for (const ov of raw.overrides) {
    if (ov.level) {
      // 整層覆蓋：找到同 ilvl 替換，沒找到就 push
      const idx = levels.findIndex((l) => l.ilvl === ov.ilvl);
      if (idx >= 0) levels[idx] = { ...ov.level };
      else levels.push({ ...ov.level });
    } else if (ov.startOverride !== undefined) {
      const idx = levels.findIndex((l) => l.ilvl === ov.ilvl);
      if (idx >= 0) levels[idx] = { ...levels[idx], start: ov.startOverride };
    }
  }

  levels.sort((a, b) => a.ilvl - b.ilvl);
  return { abstractNumId: raw.abstractNumId, levels };
}

// ── 共用工具 ──────────────────────────────────────────────────────────────────

function directChildren(el: Element | undefined): Element[] {
  if (!el) return [];
  const out: Element[] = [];
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'NumberingResolver: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`NumberingResolver: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
