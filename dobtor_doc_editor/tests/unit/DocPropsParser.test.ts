/**
 * DocPropsParser — Sprint 13
 *
 * 涵蓋：
 *   - 標準 OOXML core.xml 解析（dc:* / cp:* / dcterms:*）
 *   - 部分欄位缺漏（不 throw，缺欄位 undefined）
 *   - 空字串欄位視為 undefined
 *   - XML 解析失敗（含破碎標籤、空字串、null）→ {}
 *   - 從 OoxmlPackage 走 .rels 找 core-properties path
 *   - .rels 缺 core 但慣例路徑 docProps/core.xml 存在 → fallback
 */

import { describe, expect, it } from 'vitest';
import { parseDocProps, parseDocPropsXml } from '../../static/src/core/ooxml/DocPropsParser';
import type { OoxmlPackage, PackagePart, RelationshipDef } from '../../static/src/core/ooxml/package/PackageReader';

const FULL_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>監造日誌</dc:title>
  <dc:creator>張三</dc:creator>
  <dc:subject>水利工程</dc:subject>
  <dc:description>磺港溪 C 段</dc:description>
  <cp:keywords>監造,日誌</cp:keywords>
  <cp:lastModifiedBy>李四</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-15T08:30:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-05-08T10:00:00Z</dcterms:modified>
</cp:coreProperties>`;

// ── parseDocPropsXml（純字串）─────────────────────────────────────────────

describe('parseDocPropsXml — 完整 metadata', () => {
  it('全部欄位都填', () => {
    const props = parseDocPropsXml(FULL_XML);
    expect(props.title).toBe('監造日誌');
    expect(props.creator).toBe('張三');
    expect(props.subject).toBe('水利工程');
    expect(props.description).toBe('磺港溪 C 段');
    expect(props.keywords).toBe('監造,日誌');
    expect(props.lastModifiedBy).toBe('李四');
    expect(props.created).toBe('2026-01-15T08:30:00Z');
    expect(props.modified).toBe('2026-05-08T10:00:00Z');
  });
});

describe('parseDocPropsXml — 部分缺漏', () => {
  it('只有 title 與 creator', () => {
    const xml = `<cp:coreProperties xmlns:cp="..." xmlns:dc="...">
      <dc:title>Only Title</dc:title>
      <dc:creator>Only Creator</dc:creator>
    </cp:coreProperties>`;
    const props = parseDocPropsXml(xml);
    expect(props.title).toBe('Only Title');
    expect(props.creator).toBe('Only Creator');
    expect(props.subject).toBeUndefined();
    expect(props.modified).toBeUndefined();
  });

  it('全部空欄位', () => {
    const xml = `<cp:coreProperties xmlns:cp="..." xmlns:dc="...">
      <dc:title></dc:title>
      <dc:creator></dc:creator>
    </cp:coreProperties>`;
    const props = parseDocPropsXml(xml);
    expect(props.title).toBeUndefined();
    expect(props.creator).toBeUndefined();
  });

  it('完全空 root', () => {
    const xml = `<cp:coreProperties xmlns:cp="..." />`;
    const props = parseDocPropsXml(xml);
    expect(Object.keys(props).length).toBe(0);
  });
});

describe('parseDocPropsXml — 錯誤輸入', () => {
  it('破碎 XML 不 throw（DOMParser 可能會解出殘破文件）', () => {
    expect(() => parseDocPropsXml('<not closed>')).not.toThrow();
  });

  it('空字串不 throw', () => {
    expect(() => parseDocPropsXml('')).not.toThrow();
    const out = parseDocPropsXml('');
    expect(Object.keys(out).length).toBe(0);
  });

  it('純文字非 XML 不 throw', () => {
    expect(() => parseDocPropsXml('hello world')).not.toThrow();
  });
});

// ── parseDocProps（從 OoxmlPackage）──────────────────────────────────────

function makePkg(parts: Record<string, string>, rels: RelationshipDef[] = []): OoxmlPackage {
  const partMap = new Map<string, PackagePart>();
  for (const [path, content] of Object.entries(parts)) {
    partMap.set(path, { path, contentType: 'application/xml', data: new TextEncoder().encode(content) });
  }
  const rootRels = new Map<string, RelationshipDef>();
  for (const r of rels) rootRels.set(r.id, r);
  const relMap = new Map<string, Map<string, RelationshipDef>>();
  relMap.set('', rootRels);
  return {
    parts: partMap,
    relationships: relMap,
    getPart: (p) => partMap.get(p),
    getRelationships: (p) => relMap.get(p) ?? new Map(),
    partAsText: (p) => {
      const part = partMap.get(p);
      if (!part) return undefined;
      return new TextDecoder().decode(part.data);
    },
    resolveRelationship: () => undefined,
  };
}

describe('parseDocProps — OoxmlPackage 整合', () => {
  it('從 root .rels 找到 core-properties path', () => {
    const pkg = makePkg(
      { 'docProps/core.xml': FULL_XML },
      [{
        id: 'rId1',
        type: 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties',
        target: 'docProps/core.xml',
        targetMode: 'Internal',
      }],
    );
    const props = parseDocProps(pkg);
    expect(props.title).toBe('監造日誌');
    expect(props.creator).toBe('張三');
  });

  it('rels 沒列 core，但慣例路徑 docProps/core.xml 存在 → fallback', () => {
    const pkg = makePkg({ 'docProps/core.xml': FULL_XML });
    const props = parseDocProps(pkg);
    expect(props.title).toBe('監造日誌');
  });

  it('完全沒有 core.xml → 空 props', () => {
    const pkg = makePkg({});
    const props = parseDocProps(pkg);
    expect(Object.keys(props).length).toBe(0);
  });
});

// ── fixture-level smoke ─────────────────────────────────────────────────

describe('parseDocProps — 真實 fixture smoke', () => {
  it('OoxmlParser.parse 後 documentNode.docProps 已就位', async () => {
    const { readFileSync, readdirSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const { OoxmlParser } = await import('../../static/src/core/ooxml/OoxmlParser');
    const dir = resolve(__dirname, '../fixtures/01_simple');
    const files = readdirSync(dir).filter((f) => f.endsWith('.docx'));
    expect(files.length).toBeGreaterThan(0);
    const buf = readFileSync(resolve(dir, files[0]));
    const doc = new OoxmlParser().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
    expect(doc.docProps).toBeDefined();
    // 真實 fixture 至少有 modified 或 created（Word 自動生成）
    const hasAny =
      !!(doc.docProps.title || doc.docProps.creator || doc.docProps.modified || doc.docProps.created
        || doc.docProps.lastModifiedBy);
    expect(hasAny).toBe(true);
  });
});
