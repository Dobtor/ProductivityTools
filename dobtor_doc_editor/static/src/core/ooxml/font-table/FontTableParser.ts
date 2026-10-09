/**
 * FontTableParser — 解析 word/fontTable.xml(OOXML §17.8)
 *
 * Sprint 147(capture-only):
 *   - 42/42 fixture 都有 fontTable.xml、平均 ~20-30 fonts/file
 *   - 同 Sprint 145/146 capture-only 模式、不 wire-up
 *   - 為將來 wire-up 鋪路:
 *     - altName fallback chain(主字型缺失時 Word 自動用 alt)
 *     - family + pitch metric 選擇 hint
 *     - sig usb/csb Unicode 支援度精確 fallback 匹配
 *
 * 解析範圍:
 *   - <w:font w:name="..."> 主 key
 *   - <w:altName w:val="..."> 替代字型
 *   - <w:charset w:val="..."> hex 字串(如 '88' = BIG5)
 *   - <w:family w:val="..."> 列舉降級(auto/decorative/modern/roman/script/swiss)
 *   - <w:pitch w:val="..."> 列舉降級(fixed/variable/default)
 *   - <w:panose1 w:val="..."> 10-byte hex 字串
 *   - <w:sig w:usb0 ... w:csb1> 6 hex 屬性(紀律 #21 全空不掛 key)
 *
 * 與 FontMetricsAdapter(Sprint 60-65)的關係:
 *   - FontMetricsAdapter 走 opentype.js 量真實字型 metric;
 *   - 本 sprint capture fontTable.xml 是 docx 自帶的 font 表、不依賴 opentype.js;
 *   - 兩者互補:fontTable 提供 fallback hint、FontMetricsAdapter 提供精確 metric。
 *
 * 防禦:undefined / 空 / XML 失敗 → 回空 Map(不阻塞 OoxmlParser)。
 */

import type { FontEntry, FontFamily, FontPitch, FontSignature, FontTable } from '../ast/types';

export class FontTableParser {
  /**
   * 解析 word/fontTable.xml 字串為 FontTable(Map<name, FontEntry>)。
   *
   * @param xml fontTable.xml 完整字串;undefined / 空 → 回空 Map
   */
  parse(xml: string | undefined): FontTable {
    const out: FontTable = new Map();
    if (!xml) return out;

    let doc: Document;
    try {
      doc = parseXml(xml);
    } catch {
      return out;
    }

    const root = doc.documentElement;
    if (!root) return out;

    // 收集所有 <w:font> 直接子元素
    const fontEls = directChildren(root).filter((el) => el.tagName === 'w:font');
    for (const fontEl of fontEls) {
      const name = fontEl.getAttribute('w:name');
      if (!name) continue; // 缺 name → 跳過此條目

      const entry: FontEntry = { name };

      for (const sub of directChildren(fontEl)) {
        switch (sub.tagName) {
          case 'w:altName': {
            const v = sub.getAttribute('w:val');
            if (v) entry.altName = v;
            break;
          }
          case 'w:charset': {
            const v = sub.getAttribute('w:val');
            if (v) entry.charset = v;
            break;
          }
          case 'w:family': {
            const v = sub.getAttribute('w:val');
            const family = normalizeFamily(v);
            if (family !== undefined) entry.family = family;
            break;
          }
          case 'w:pitch': {
            const v = sub.getAttribute('w:val');
            const pitch = normalizePitch(v);
            if (pitch !== undefined) entry.pitch = pitch;
            break;
          }
          case 'w:panose1': {
            const v = sub.getAttribute('w:val');
            if (v) entry.panose1 = v;
            break;
          }
          case 'w:sig': {
            const sig = parseSig(sub);
            // 紀律 #21:全空時不掛 key
            if (Object.keys(sig).length > 0) entry.sig = sig;
            break;
          }
        }
      }

      out.set(name, entry);
    }

    return out;
  }
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

function normalizeFamily(v: string | null): FontFamily | undefined {
  if (v === null) return undefined;
  switch (v) {
    case 'auto':
    case 'decorative':
    case 'modern':
    case 'roman':
    case 'script':
    case 'swiss':
      return v;
    default:
      return undefined;
  }
}

function normalizePitch(v: string | null): FontPitch | undefined {
  if (v === null) return undefined;
  switch (v) {
    case 'fixed':
    case 'variable':
    case 'default':
      return v;
    default:
      return undefined;
  }
}

function parseSig(el: Element): FontSignature {
  const sig: FontSignature = {};
  const usb0 = el.getAttribute('w:usb0');
  const usb1 = el.getAttribute('w:usb1');
  const usb2 = el.getAttribute('w:usb2');
  const usb3 = el.getAttribute('w:usb3');
  const csb0 = el.getAttribute('w:csb0');
  const csb1 = el.getAttribute('w:csb1');
  if (usb0) sig.usb0 = usb0;
  if (usb1) sig.usb1 = usb1;
  if (usb2) sig.usb2 = usb2;
  if (usb3) sig.usb3 = usb3;
  if (csb0) sig.csb0 = csb0;
  if (csb1) sig.csb1 = csb1;
  return sig;
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
      'FontTableParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`FontTableParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
