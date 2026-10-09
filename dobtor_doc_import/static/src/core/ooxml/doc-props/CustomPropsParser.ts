/**
 * CustomPropsParser — 解析 docProps/custom.xml(OOXML §22.3、custom-properties)
 *
 * Sprint 151(capture-only、Sprint 150 doc-props 子目錄延續):
 *   - 25/42 fixture 有 custom.xml(WPS KSOProductBuildVer × 24 + Grammarly × 14)
 *   - 17 fixture 無此 part(無 SaaS app stamp、純 Word 預設)
 *   - 沿用 Sprint 150 doc-props 子目錄、結構單純(property bag)
 *
 * 解析結構:
 *   <Properties xmlns="...custom-properties" xmlns:vt="...docPropsVTypes">
 *     <property fmtid="..." pid="2" name="KSOProductBuildVer">
 *       <vt:lpwstr>1028-10.8.0.6003</vt:lpwstr>
 *     </property>
 *   </Properties>
 *
 * 支援 variant(scope-down、紀律 #18):
 *   - vt:lpwstr / vt:lpstr / vt:bstr → kind: 'string'
 *   - vt:i4 / vt:i8 / vt:int / vt:uint → kind: 'int'
 *   - vt:bool → kind: 'bool'
 *   - vt:r4 / vt:r8 / vt:decimal → kind: 'real'
 *   - vt:filetime / vt:date → kind: 'filetime'(原 ISO 字串、不轉 Date)
 *   - 其他 variant → kind: 'unknown'(保留 raw textContent)
 *
 * 設計決策:
 *   - fmtid / pid 不保留(紀律 #18 scope-down、name 已足以作為 key)
 *   - name 重複(理論上不該發生)時後者覆蓋前者(Map.set 行為)
 *   - 缺 name 屬性或 name 為空字串 → 跳過該 property(不掛 key、紀律 #21)
 *
 * 防禦:undefined / 空 / XML 失敗 → 回空 Map(不阻塞 OoxmlParser)。
 */

import type { CustomPropertyValue, DocPropsCustom } from '../ast/types';
import type { OoxmlPackage } from '../package/PackageReader';

const REL_TYPE_CUSTOM_PROPERTIES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties';

/**
 * 從 OoxmlPackage 讀 docProps/custom.xml(透過 root .rels 找路徑),回傳結構化 DocPropsCustom。
 *
 * 找不到 part 或解析失敗皆回空 Map(不 throw)。
 */
export function parseCustomProps(pkg: OoxmlPackage): DocPropsCustom {
  const path = findCustomPropertiesPath(pkg);
  if (!path) return new Map();
  const xml = pkg.partAsText(path);
  if (!xml) return new Map();
  try {
    return parseCustomPropsXml(xml);
  } catch {
    return new Map();
  }
}

/** 純 XML 字串解析版本(測試用、不依賴 OoxmlPackage)。 */
export function parseCustomPropsXml(xml: string): DocPropsCustom {
  const out: DocPropsCustom = new Map();
  if (!xml || !xml.trim()) return out;
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'CustomPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xml, 'application/xml');
  } catch {
    return out;
  }
  if (!doc || !doc.documentElement) return out;

  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) return out;

  const root = doc.documentElement;

  for (let i = 0; i < root.childNodes.length; i++) {
    const n = root.childNodes[i];
    if (n.nodeType !== 1) continue;
    const el = n as Element;
    if (localName(el) !== 'property') continue;

    const name = (el.getAttribute('name') || '').trim();
    if (!name) continue;  // 紀律 #21:無 name 跳過

    const variant = firstElementChild(el);
    if (!variant) continue;  // 無 value 跳過

    const value = parseVariant(variant);
    if (value === null) continue;

    out.set(name, value);
  }

  return out;
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

/**
 * 從 root .rels 中找 custom-properties 關聯的 part path。
 *
 * 與 app.xml 同模式:走 root .rels、fallback 慣例路徑。
 */
function findCustomPropertiesPath(pkg: OoxmlPackage): string | undefined {
  const rootRels = pkg.relationships.get('') ?? new Map();
  for (const rel of rootRels.values()) {
    if (rel.type === REL_TYPE_CUSTOM_PROPERTIES && rel.targetMode === 'Internal') {
      return rel.target;
    }
  }
  // fallback 慣例路徑
  if (pkg.parts.has('docProps/custom.xml')) return 'docProps/custom.xml';
  return undefined;
}

/** 把 vt:* 子元素解析為 CustomPropertyValue。 */
function parseVariant(el: Element): CustomPropertyValue | null {
  const tag = localName(el);
  const text = (el.textContent || '').trim();

  switch (tag) {
    case 'lpwstr':
    case 'lpstr':
    case 'bstr':
      // 字串:空字串合法(允許「顯式設為空」、非紀律 #21 範圍)
      return { kind: 'string', value: text };
    case 'i4':
    case 'i8':
    case 'int':
    case 'uint': {
      if (!/^-?\d+$/.test(text)) return null;
      const n = parseInt(text, 10);
      return Number.isFinite(n) ? { kind: 'int', value: n } : null;
    }
    case 'bool': {
      const lc = text.toLowerCase();
      if (lc === 'true' || lc === '1') return { kind: 'bool', value: true };
      if (lc === 'false' || lc === '0') return { kind: 'bool', value: false };
      return null;
    }
    case 'r4':
    case 'r8':
    case 'decimal': {
      const n = parseFloat(text);
      return Number.isFinite(n) ? { kind: 'real', value: n } : null;
    }
    case 'filetime':
    case 'date':
      // 保留原 ISO 字串(紀律 #18 不轉 Date、避免 timezone 副作用)
      return text ? { kind: 'filetime', value: text } : null;
    default:
      // 其他 variant(vt:vector / vt:cy / vt:storage 等)降級保留 raw
      return { kind: 'unknown', raw: text };
  }
}

/** 取元素 local-name(忽略 namespace prefix);xmldom 部分版本 localName 為空 */
function localName(el: Element): string {
  const ln = el.localName;
  if (ln) return ln;
  const tag = el.tagName;
  const colon = tag.indexOf(':');
  return colon >= 0 ? tag.substring(colon + 1) : tag;
}

/** 取第一個 Element 子節點(忽略 text node 與註解)。 */
function firstElementChild(el: Element): Element | null {
  for (let i = 0; i < el.childNodes.length; i++) {
    const n = el.childNodes[i];
    if (n.nodeType === 1) return n as Element;
  }
  return null;
}
