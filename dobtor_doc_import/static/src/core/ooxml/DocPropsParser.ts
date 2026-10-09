/**
 * DocPropsParser — 解析 docProps/core.xml（Sprint 13）
 *
 * OOXML §22.2 + Dublin Core + Open Packaging Conventions：
 *   docProps/core.xml 內含文件 metadata，root = `<cp:coreProperties>`。
 *
 * 範例：
 *   <cp:coreProperties xmlns:cp="..." xmlns:dc="..." xmlns:dcterms="...">
 *     <dc:title>監造日誌</dc:title>
 *     <dc:creator>張三</dc:creator>
 *     <cp:lastModifiedBy>李四</cp:lastModifiedBy>
 *     <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-15T08:30:00Z</dcterms:created>
 *     <dcterms:modified>2026-05-08T10:00:00Z</dcterms:modified>
 *   </cp:coreProperties>
 *
 * 取值規則：
 *   - 找不到 docProps/core.xml → 空 docProps {}
 *   - XML 解析失敗 → 空 docProps（不 throw）
 *   - 欄位空字串 → undefined
 *
 * 為何不在 OoxmlParser.parse 內 inline：
 *   - 邏輯獨立：純 XML lookup，沒有 cross-part 依賴
 *   - 易於 mock / unit test
 *   - 未來擴展 docProps/app.xml（Application / Pages / Words 等）時加同檔即可
 */

import type { DocProps } from './ast/types';
import type { OoxmlPackage } from './package/PackageReader';

// 慣例：使用 global DOMParser（瀏覽器原生；vitest 由 tests/setup.ts 注入 @xmldom/xmldom）
// 避免直接 import @xmldom/xmldom 造成 Element 型別與 DOM lib 衝突

const REL_TYPE_CORE_PROPERTIES =
  'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties';

/**
 * 從 OoxmlPackage 讀 docProps/core.xml（透過 root .rels 找路徑），回傳結構化 DocProps。
 *
 * 找不到 part 或解析失敗皆回 `{}`（不 throw）。
 */
export function parseDocProps(pkg: OoxmlPackage): DocProps {
  const corePath = findCorePropertiesPath(pkg);
  if (!corePath) return {};
  const xml = pkg.partAsText(corePath);
  if (!xml) return {};
  try {
    return parseDocPropsXml(xml);
  } catch {
    return {};
  }
}

/** 純 XML 字串解析版本（測試用，不依賴 OoxmlPackage）。 */
export function parseDocPropsXml(xml: string): DocProps {
  if (!xml || !xml.trim()) return {};
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'DocPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  let doc: Document | null;
  try {
    doc = new DOMParser().parseFromString(xml, 'text/xml');
  } catch {
    return {};
  }
  if (!doc || !doc.documentElement) return {};
  const root = doc.documentElement;

  const out: DocProps = {};
  const title = pickText(root, ['dc:title', 'title']);
  if (title) out.title = title;
  const creator = pickText(root, ['dc:creator', 'creator']);
  if (creator) out.creator = creator;
  const subject = pickText(root, ['dc:subject', 'subject']);
  if (subject) out.subject = subject;
  const description = pickText(root, ['dc:description', 'description']);
  if (description) out.description = description;
  const keywords = pickText(root, ['cp:keywords', 'keywords']);
  if (keywords) out.keywords = keywords;
  const lastModifiedBy = pickText(root, ['cp:lastModifiedBy', 'lastModifiedBy']);
  if (lastModifiedBy) out.lastModifiedBy = lastModifiedBy;
  const created = pickText(root, ['dcterms:created', 'created']);
  if (created) out.created = created;
  const modified = pickText(root, ['dcterms:modified', 'modified']);
  if (modified) out.modified = modified;
  return out;
}

/**
 * 從 root .rels 中找 core-properties 關聯的 part path。
 *
 * Conventions：core.xml 通常在 `docProps/core.xml`，但 spec 不強制路徑，
 * 必須走 .rels 解析；若 rels 沒列就 fallback 慣例路徑。
 */
function findCorePropertiesPath(pkg: OoxmlPackage): string | undefined {
  const rootRels = pkg.relationships.get('') ?? new Map();
  for (const rel of rootRels.values()) {
    if (rel.type === REL_TYPE_CORE_PROPERTIES && rel.targetMode === 'Internal') {
      return rel.target;
    }
  }
  // fallback 慣例路徑
  if (pkg.parts.has('docProps/core.xml')) return 'docProps/core.xml';
  return undefined;
}

/** 在 root 內找指定 tag（依序 try 多個候選名稱），回 trim 後文字內容。 */
function pickText(root: Element, candidates: string[]): string {
  for (const name of candidates) {
    // 先試 qualified name（含 prefix），再試 localName
    const els = root.getElementsByTagName(name);
    if (els.length > 0 && els[0].textContent) {
      return els[0].textContent.trim();
    }
  }
  return '';
}
