/**
 * AppPropsParser — 解析 docProps/app.xml(OOXML §22.2、extended-properties)
 *
 * Sprint 150(capture-only、autonomous-friendly §11.2 backlog):
 *   - 42/42 fixture 都有 app.xml(Word/WPS 預設骨架)、17 elements 出現頻率 100%
 *   - layout / render 不消費、為將來 Phase 6 docx export 對稱性鋪路
 *   - 沿用 Sprint 145-148 capture-only 9-step archetype
 *
 * 解析範圍(17 elements):
 *   字串:Template / Application / AppVersion / Company
 *   整數:Pages / Words / Characters / Lines / Paragraphs / TotalTime /
 *         CharactersWithSpaces / DocSecurity(enum、capture 階段以整數保留)
 *   布林:ScaleCrop / LinksUpToDate / SharedDoc / HyperlinksChanged
 *
 * 設計決策:
 *   - 與 DocPropsParser(core.xml)平行架構、不合併成同檔避免擴大 PR
 *   - 紀律 #21:空字串 / 0 long / 非數字 字串 → undefined(不掛 key)
 *   - 布林採嚴格 "true"/"false" 字串比對(不接受 "1"/"0"、依規格)
 *   - 與 ext-properties namespace 共存,但只認元素 local-name(忽略 ns prefix)
 *
 * 防禦:undefined / 空 / XML 失敗 → 回 {}(不阻塞 OoxmlParser)。
 */

import type { DocPropsApp } from '../ast/types';
import type { OoxmlPackage } from '../package/PackageReader';

const REL_TYPE_EXTENDED_PROPERTIES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties';

/**
 * 從 OoxmlPackage 讀 docProps/app.xml(透過 root .rels 找路徑),回傳結構化 DocPropsApp。
 *
 * 找不到 part 或解析失敗皆回 `{}`(不 throw、紀律 #21)。
 */
export function parseAppProps(pkg: OoxmlPackage): DocPropsApp {
  const path = findAppPropertiesPath(pkg);
  if (!path) return {};
  const xml = pkg.partAsText(path);
  if (!xml) return {};
  try {
    return parseAppPropsXml(xml);
  } catch {
    return {};
  }
}

/** 純 XML 字串解析版本(測試用、不依賴 OoxmlPackage)。 */
export function parseAppPropsXml(xml: string): DocPropsApp {
  if (!xml || !xml.trim()) return {};
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'AppPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xml, 'application/xml');
  } catch {
    return {};
  }
  if (!doc || !doc.documentElement) return {};

  // pParse 失敗:某些 DOMParser 不 throw、而是回傳含 parsererror 的 doc
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) return {};

  const root = doc.documentElement;
  const out: DocPropsApp = {};

  for (let i = 0; i < root.childNodes.length; i++) {
    const n = root.childNodes[i];
    if (n.nodeType !== 1) continue;
    const el = n as Element;
    const tag = localName(el);
    switch (tag) {
      case 'Template':
        assignString(out, 'template', el);
        break;
      case 'Application':
        assignString(out, 'application', el);
        break;
      case 'AppVersion':
        assignString(out, 'appVersion', el);
        break;
      case 'Company':
        assignString(out, 'company', el);
        break;
      case 'TotalTime':
        assignInt(out, 'totalTime', el);
        break;
      case 'Pages':
        assignInt(out, 'pages', el);
        break;
      case 'Words':
        assignInt(out, 'words', el);
        break;
      case 'Characters':
        assignInt(out, 'characters', el);
        break;
      case 'CharactersWithSpaces':
        assignInt(out, 'charactersWithSpaces', el);
        break;
      case 'Lines':
        assignInt(out, 'lines', el);
        break;
      case 'Paragraphs':
        assignInt(out, 'paragraphs', el);
        break;
      case 'DocSecurity':
        assignInt(out, 'docSecurity', el);
        break;
      case 'ScaleCrop':
        assignBool(out, 'scaleCrop', el);
        break;
      case 'LinksUpToDate':
        assignBool(out, 'linksUpToDate', el);
        break;
      case 'SharedDoc':
        assignBool(out, 'sharedDoc', el);
        break;
      case 'HyperlinksChanged':
        assignBool(out, 'hyperlinksChanged', el);
        break;
    }
  }

  return out;
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

/**
 * 從 root .rels 中找 extended-properties 關聯的 part path。
 *
 * Conventions:app.xml 通常在 `docProps/app.xml`、但 spec 不強制路徑、
 * 必須走 .rels 解析;若 rels 沒列就 fallback 慣例路徑。
 */
function findAppPropertiesPath(pkg: OoxmlPackage): string | undefined {
  const rootRels = pkg.relationships.get('') ?? new Map();
  for (const rel of rootRels.values()) {
    if (rel.type === REL_TYPE_EXTENDED_PROPERTIES && rel.targetMode === 'Internal') {
      return rel.target;
    }
  }
  // fallback 慣例路徑
  if (pkg.parts.has('docProps/app.xml')) return 'docProps/app.xml';
  return undefined;
}

/** 取元素 local-name(忽略 namespace prefix);xmldom 部分版本 localName 為空字串 */
function localName(el: Element): string {
  const ln = el.localName;
  if (ln) return ln;
  const tag = el.tagName;
  const colon = tag.indexOf(':');
  return colon >= 0 ? tag.substring(colon + 1) : tag;
}

function assignString(out: DocPropsApp, key: keyof DocPropsApp, el: Element): void {
  const text = (el.textContent || '').trim();
  if (!text) return;  // 紀律 #21
  (out as Record<string, unknown>)[key] = text;
}

function assignInt(out: DocPropsApp, key: keyof DocPropsApp, el: Element): void {
  const text = (el.textContent || '').trim();
  if (!text) return;
  // 嚴格整數;不接受小數、不接受非數字字元
  if (!/^-?\d+$/.test(text)) return;
  const n = parseInt(text, 10);
  if (!Number.isFinite(n)) return;
  (out as Record<string, unknown>)[key] = n;
}

function assignBool(out: DocPropsApp, key: keyof DocPropsApp, el: Element): void {
  const text = (el.textContent || '').trim().toLowerCase();
  if (text === 'true') {
    (out as Record<string, unknown>)[key] = true;
  } else if (text === 'false') {
    (out as Record<string, unknown>)[key] = false;
  }
  // 其他值(包含空字串)不掛 key、紀律 #21
}
