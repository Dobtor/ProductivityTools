/**
 * SettingsParser — 解析 word/settings.xml(OOXML §17.15)
 *
 * Sprint 146(capture-only):
 *   - 42 fixture settings.xml 全覆蓋(100%)、未來 layout/render 端 wire-up 鋪路
 *   - 高覆蓋元素: zoom / defaultTabStop / characterSpacingControl /
 *     footnotePr / endnotePr / compat 全 42/42
 *   - 不 wire-up(同 Sprint 145 Footnotes 模式)、capture 進 AST 供 caller 查詢
 *
 * 解析範圍(對應 DocumentSettings interface):
 *   - w:zoom w:percent → zoomPercent: number
 *   - w:defaultTabStop w:val → defaultTabStop: pt(從 twip 轉)
 *   - w:characterSpacingControl w:val → 列舉
 *   - w:autoHyphenation / w:evenAndOddHeaders / w:trackChanges → boolean(存在即 true)
 *   - w:proofState w:spelling/w:grammar → proofState
 *   - w:footnotePr / w:endnotePr → 結構物件
 *   - w:compat 內所有子元素標籤名 → string[]
 *
 * 紀律 #21:optional 欄位空集合不掛 key — 空物件 {} 代表「無設定」、所有欄位 undefined。
 *
 * 防禦:undefined / 空 / XML 解析失敗 → 回 {}(不阻塞 OoxmlParser)。
 */

import type { DocumentSettings, Pt } from '../ast/types';
import { twipToPt } from '../units/units';

export class SettingsParser {
  /**
   * 解析 word/settings.xml 字串為 DocumentSettings。
   *
   * @param xml settings.xml 完整字串;undefined / 空 → 回 {}
   */
  parse(xml: string | undefined): DocumentSettings {
    if (!xml) return {};

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return {};
    }

    const root = doc.documentElement;
    if (!root) return {};

    const out: DocumentSettings = {};

    for (const child of directChildren(root)) {
      switch (child.tagName) {
        case 'w:zoom': {
          const v = child.getAttribute('w:percent');
          const n = v !== null ? parseInt(v, 10) : NaN;
          if (Number.isFinite(n) && n > 0) out.zoomPercent = n;
          break;
        }
        case 'w:defaultTabStop': {
          const v = child.getAttribute('w:val');
          const n = v !== null ? parseInt(v, 10) : NaN;
          if (Number.isFinite(n) && n > 0) {
            out.defaultTabStop = twipToPt(n) as Pt;
          }
          break;
        }
        case 'w:characterSpacingControl': {
          const v = child.getAttribute('w:val');
          if (
            v === 'doNotCompress' ||
            v === 'compressPunctuation' ||
            v === 'compressPunctuationAndJapaneseKana'
          ) {
            out.characterSpacingControl = v;
          }
          break;
        }
        case 'w:autoHyphenation':
          out.autoHyphenation = readToggle(child);
          break;
        case 'w:evenAndOddHeaders':
          out.evenAndOddHeaders = readToggle(child);
          break;
        case 'w:trackChanges':
          out.trackChanges = readToggle(child);
          break;
        case 'w:proofState': {
          const ps: NonNullable<DocumentSettings['proofState']> = {};
          const sp = child.getAttribute('w:spelling');
          const gr = child.getAttribute('w:grammar');
          if (sp === 'clean' || sp === 'dirty') ps.spelling = sp;
          if (gr === 'clean' || gr === 'dirty') ps.grammar = gr;
          if (Object.keys(ps).length > 0) out.proofState = ps;
          break;
        }
        case 'w:footnotePr':
          out.footnotePr = parseNotePr(child, 'footnote');
          break;
        case 'w:endnotePr':
          out.endnotePr = parseNotePr(child, 'endnote');
          break;
        case 'w:compat': {
          const names: string[] = [];
          for (const sub of directChildren(child)) {
            // 去掉 w: 前綴
            const tag = sub.tagName;
            const local = tag.includes(':') ? tag.split(':')[1] : tag;
            if (local) names.push(local);
          }
          if (names.length > 0) out.compat = names;
          break;
        }
      }
    }

    return out;
  }
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

/**
 * OOXML toggle:`<w:foo/>` 或 `<w:foo w:val="1"/>` 為 true、`w:val="0"` / `"false"` 為 false。
 * 預設(無屬性)= true、與 OOXML §17.17.4 規範對齊。
 */
function readToggle(el: Element): boolean {
  const v = el.getAttribute('w:val');
  if (v === null) return true; // 元素存在 = true
  return v !== '0' && v.toLowerCase() !== 'false';
}

type NotePr = NonNullable<DocumentSettings['footnotePr']>;

function parseNotePr(el: Element, kind: 'footnote' | 'endnote'): NotePr {
  const out: NotePr = {};
  for (const sub of directChildren(el)) {
    switch (sub.tagName) {
      case 'w:numRestart': {
        const v = sub.getAttribute('w:val');
        if (v === 'continuous' || v === 'eachPage' || v === 'eachSect') {
          out.numRestart = v;
        }
        break;
      }
      case 'w:numFmt': {
        const v = sub.getAttribute('w:val');
        if (v) out.numFmt = v;
        break;
      }
      case 'w:pos': {
        const v = sub.getAttribute('w:val');
        // footnote: pageBottom/beneathText/sectEnd/docEnd
        // endnote: sectEnd/docEnd
        const valid =
          kind === 'footnote'
            ? ['pageBottom', 'beneathText', 'sectEnd', 'docEnd']
            : ['sectEnd', 'docEnd'];
        if (v && valid.includes(v)) {
          out.position = v as NotePr['position'];
        }
        break;
      }
      case 'w:numStart': {
        const v = sub.getAttribute('w:val');
        const n = v !== null ? parseInt(v, 10) : NaN;
        if (Number.isFinite(n)) out.numStart = n;
        break;
      }
      // <w:footnote w:id="-1"/> 等 — fixture 中 footnotes 預設 stub 引用、本 sprint 不解析
    }
  }
  return out;
}

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
      'SettingsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`SettingsParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
