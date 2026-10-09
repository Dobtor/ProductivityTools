/**
 * PackageReader — OOXML ZIP 容器解包
 *
 * 職責：
 *   1. 解開 .docx (ZIP) 取出每份 part（XML / 圖片 / 等）
 *   2. 解析 [Content_Types].xml：建立 path → MIME type 對照
 *      - <Default Extension="xml" ContentType="..."> 預設規則
 *      - <Override PartName="/word/document.xml" ContentType="..."> 覆蓋規則
 *   3. 解析 _rels/.rels 與 <part>/_rels/<part>.rels：建立 rId → target 對照
 *
 * 重要設計：
 *   - 所有 part 路徑統一去除前導 "/"（OOXML 慣例）
 *   - relationship target 解析為「相對於 .rels 所屬 part 的目錄」的絕對路徑
 *   - 不在此處解任何 OOXML 內容語意（document.xml / styles.xml 留給上層 Parser）
 *
 * Sprint 1 實作完成；後續若 ZIP 體積大可改 unzipAsync。
 */

import { unzipSync, strFromU8 } from 'fflate';

export interface PackagePart {
  /** 絕對路徑，無前導 "/"，例：'word/document.xml' */
  path: string;
  /** MIME type，例：'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' */
  contentType: string;
  /** 二進位內容；XML part 可用 toText() 取字串 */
  data: Uint8Array;
}

export interface RelationshipDef {
  /** rId 1, rId 2, ... */
  id: string;
  /** schemas-openxmlformats-org/.../image 等完整 type URI */
  type: string;
  /** 解析後的絕對 part path（已套用相對路徑解析） */
  target: string;
  /** External / Internal — Hyperlinks 通常是 External */
  targetMode: 'Internal' | 'External';
}

/**
 * [Content_Types].xml 解析結果（Sprint 152 暴露至 OoxmlPackage)。
 *
 * OOXML §10.2.2 / OPC §3.2:每個 OOXML package 必有一個 [Content_Types].xml、
 * 它告訴 reader 每個 part 的 MIME type。本介面與 internal ParsedContentTypes 一致、
 * 對外保持 readonly 形式以便為 Phase 6 docx export 對稱性鋪路。
 *
 * Sprint 152 capture-only:capture 但不 wire-up;不消費於 layout/render。
 */
export interface PackageContentTypes {
  /** Default Extension → ContentType (e.g. 'xml' → 'application/xml') */
  defaults: ReadonlyMap<string, string>;
  /** Override PartName(no leading "/") → ContentType */
  overrides: ReadonlyMap<string, string>;
}

export interface OoxmlPackage {
  /** 全部 part 的查找表（key = path） */
  parts: Map<string, PackagePart>;
  /** 每個 part 的關聯（key = part path；root 用空字串 ""） */
  relationships: Map<string, Map<string, RelationshipDef>>;
  /** Sprint 152: [Content_Types].xml 解析結果 (readonly、capture-only) */
  contentTypes: PackageContentTypes;
  /** 取單一 part 的便捷方法 */
  getPart(path: string): PackagePart | undefined;
  /** 取單一 part 的關聯 */
  getRelationships(partPath: string): Map<string, RelationshipDef>;
  /** 把 part 內容轉為 UTF-8 字串（XML 解析用） */
  partAsText(path: string): string | undefined;
  /** 解析 rId 為絕對 part path（用於 image rId、style rId 等） */
  resolveRelationship(partPath: string, rId: string): string | undefined;
}

// 註：[Content_Types].xml 與 .rels 都用「預設命名空間 + 無 prefix」結構，
// 用 getElementsByTagName(localName) 在瀏覽器與 happy-dom 都能正確匹配；
// 而 getElementsByTagNameNS 在 happy-dom 對預設命名空間實作有缺陷（回傳 0）。

export class PackageReader {
  /**
   * 解析 .docx ArrayBuffer 為結構化 OoxmlPackage。
   * @throws Error 如果 ZIP 損壞、缺 [Content_Types].xml、或 XML 解析失敗
   */
  parse(buffer: ArrayBuffer): OoxmlPackage {
    const bytes = new Uint8Array(buffer);
    const entries = unzipSync(bytes);

    const parts = new Map<string, PackagePart>();
    const relationships = new Map<string, Map<string, RelationshipDef>>();

    // Step 1: [Content_Types].xml 必須存在
    const ctRaw = entries['[Content_Types].xml'];
    if (!ctRaw) {
      throw new Error(
        'PackageReader: [Content_Types].xml not found — not a valid OOXML package',
      );
    }
    const contentTypes = parseContentTypes(strFromU8(ctRaw));

    // Step 2: 走訪所有 entry，分類為 part 或 relationship
    for (const [rawPath, data] of Object.entries(entries)) {
      // 跳過 ZIP 目錄項目（fflate 通常已過濾，但保險）
      if (rawPath.endsWith('/')) continue;

      // 標準化路徑：去除前導 "/"
      const path = rawPath.replace(/^\/+/, '');

      // 跳過 [Content_Types].xml 本身（不是 part）
      if (path === '[Content_Types].xml') continue;

      // .rels 檔：解析後存入 relationships map，不放進 parts
      if (path.endsWith('.rels')) {
        const ownerPart = relsOwnerPath(path);
        const xml = strFromU8(data);
        const rels = parseRelationships(xml, ownerPart);
        relationships.set(ownerPart, rels);
        continue;
      }

      // 其他檔案 → part；查 contentType
      const contentType = resolveContentType(path, contentTypes);
      parts.set(path, { path, contentType, data });
    }

    return makePackage(parts, relationships, contentTypes);
  }
}

// ── 內部工具 ──────────────────────────────────────────────────────────────────

interface ParsedContentTypes {
  defaults: Map<string, string>; // ext (lower) → contentType
  overrides: Map<string, string>; // partName (no leading /) → contentType
}

function parseContentTypes(xml: string): ParsedContentTypes {
  const doc = parseXml(xml);
  const defaults = new Map<string, string>();
  const overrides = new Map<string, string>();

  const defaultEls = doc.getElementsByTagName('Default');
  for (let i = 0; i < defaultEls.length; i++) {
    const el = defaultEls[i];
    const ext = el.getAttribute('Extension')?.toLowerCase();
    const ct = el.getAttribute('ContentType');
    if (ext && ct) defaults.set(ext, ct);
  }

  const overrideEls = doc.getElementsByTagName('Override');
  for (let i = 0; i < overrideEls.length; i++) {
    const el = overrideEls[i];
    const partName = el.getAttribute('PartName')?.replace(/^\/+/, '');
    const ct = el.getAttribute('ContentType');
    if (partName && ct) overrides.set(partName, ct);
  }

  return { defaults, overrides };
}

function resolveContentType(path: string, ct: ParsedContentTypes): string {
  // Override 優先於 Default
  const override = ct.overrides.get(path);
  if (override) return override;
  const dotIdx = path.lastIndexOf('.');
  if (dotIdx === -1) return 'application/octet-stream';
  const ext = path.substring(dotIdx + 1).toLowerCase();
  return ct.defaults.get(ext) ?? 'application/octet-stream';
}

/**
 * 從 .rels 路徑反推它所屬 part 的路徑。
 *   "_rels/.rels"                    → ""                  (root)
 *   "word/_rels/document.xml.rels"   → "word/document.xml"
 *   "word/_rels/header1.xml.rels"    → "word/header1.xml"
 */
function relsOwnerPath(relsPath: string): string {
  // root rels：_rels/.rels
  if (relsPath === '_rels/.rels') return '';

  // 拆 dir/_rels/file.ext.rels → dir/file.ext
  const match = relsPath.match(/^(.*?)_rels\/(.+)\.rels$/);
  if (!match) {
    // 不符合預期格式，回傳本身去 .rels 後綴（fallback）
    return relsPath.replace(/\.rels$/, '');
  }
  const dir = match[1]; // 含結尾 "/" 或 ""
  const file = match[2];
  return `${dir}${file}`;
}

function parseRelationships(
  xml: string,
  ownerPart: string,
): Map<string, RelationshipDef> {
  const doc = parseXml(xml);
  const out = new Map<string, RelationshipDef>();
  const rels = doc.getElementsByTagName('Relationship');

  for (let i = 0; i < rels.length; i++) {
    const el = rels[i];
    const id = el.getAttribute('Id');
    const type = el.getAttribute('Type');
    const targetRaw = el.getAttribute('Target');
    const targetModeRaw = el.getAttribute('TargetMode');
    if (!id || !type || !targetRaw) continue;

    const targetMode: RelationshipDef['targetMode'] =
      targetModeRaw === 'External' ? 'External' : 'Internal';

    const target =
      targetMode === 'External' ? targetRaw : resolveTarget(ownerPart, targetRaw);

    out.set(id, { id, type, target, targetMode });
  }
  return out;
}

/**
 * 把 relationship target（相對路徑）解析為絕對 part path。
 * ownerPart 為空字串（root rels）時，target 本來就是相對於套件根。
 *
 * 範例：
 *   ownerPart = "word/document.xml", target = "header1.xml"
 *     → "word/header1.xml"
 *   ownerPart = "word/document.xml", target = "media/image1.png"
 *     → "word/media/image1.png"
 *   ownerPart = "word/document.xml", target = "../customXml/item1.xml"
 *     → "customXml/item1.xml"
 *   ownerPart = "", target = "word/document.xml"
 *     → "word/document.xml"
 */
function resolveTarget(ownerPart: string, target: string): string {
  // target 開頭為 "/" 表示絕對路徑
  if (target.startsWith('/')) return target.replace(/^\/+/, '');

  // 取 ownerPart 的目錄（不含檔名）
  const lastSlash = ownerPart.lastIndexOf('/');
  const baseDir = lastSlash === -1 ? '' : ownerPart.substring(0, lastSlash + 1);

  // 拼接後正規化：處理 ".." 與 "."
  const combined = baseDir + target;
  return normalizePath(combined);
}

function normalizePath(path: string): string {
  const parts = path.split('/');
  const stack: string[] = [];
  for (const part of parts) {
    if (part === '' || part === '.') continue;
    if (part === '..') {
      stack.pop();
      continue;
    }
    stack.push(part);
  }
  return stack.join('/');
}

/**
 * 統一 XML 解析入口。優先用 DOMParser（瀏覽器與 happy-dom/jsdom 環境）。
 * 若解析失敗（含 <parsererror>），丟錯。
 */
function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'PackageReader: DOMParser not available — Node tests must use happy-dom environment',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  // DOMParser 不會 throw；錯誤會放在 <parsererror>
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`PackageReader: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}

function makePackage(
  parts: Map<string, PackagePart>,
  relationships: Map<string, Map<string, RelationshipDef>>,
  contentTypes: ParsedContentTypes,
): OoxmlPackage {
  return {
    parts,
    relationships,
    contentTypes: {
      defaults: contentTypes.defaults,
      overrides: contentTypes.overrides,
    },
    getPart(path) {
      return parts.get(path.replace(/^\/+/, ''));
    },
    getRelationships(partPath) {
      return relationships.get(partPath.replace(/^\/+/, '')) ?? new Map();
    },
    partAsText(path) {
      const p = parts.get(path.replace(/^\/+/, ''));
      if (!p) return undefined;
      return strFromU8(p.data);
    },
    resolveRelationship(partPath, rId) {
      const rels = relationships.get(partPath.replace(/^\/+/, ''));
      return rels?.get(rId)?.target;
    },
  };
}
