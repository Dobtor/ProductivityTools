/**
 * PackageReader 單元測試
 *
 * 用真實 fixture .docx 驗證解包與 relationship 解析正確。
 * 不依賴特定文件內容，只驗證 OOXML 套件結構保證。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PackageReader } from '../../static/src/core/ooxml/package/PackageReader';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function loadFixture(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  // Buffer → ArrayBuffer（複製，避免共用底層 buffer）
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

describe('PackageReader.parse', () => {
  const reader = new PackageReader();

  it('解開簡單監造會議記錄 .docx', () => {
    const buf = loadFixture('01_simple/03.1120815-監造會議記錄.docx');
    const pkg = reader.parse(buf);

    // 必備 part
    expect(pkg.getPart('word/document.xml')).toBeDefined();
    expect(pkg.getPart('word/styles.xml')).toBeDefined();

    // document.xml 的 contentType 必須是 wordprocessingml.document.main
    const doc = pkg.getPart('word/document.xml')!;
    expect(doc.contentType).toContain('wordprocessingml.document.main');

    // 用 partAsText 取得內容應為合法 XML 開頭
    const xml = pkg.partAsText('word/document.xml')!;
    expect(xml).toMatch(/^<\?xml/);
    expect(xml).toContain('<w:document');
  });

  it('解析 root relationships (_rels/.rels) 並指向 word/document.xml', () => {
    const buf = loadFixture('01_simple/03.1120815-監造會議記錄.docx');
    const pkg = reader.parse(buf);

    // root rels 用空字串作 key
    const rootRels = pkg.getRelationships('');
    expect(rootRels.size).toBeGreaterThan(0);

    // 至少一個 relationship 指向 word/document.xml（officeDocument 關係）
    const officeDocRel = [...rootRels.values()].find((r) =>
      r.type.endsWith('/officeDocument'),
    );
    expect(officeDocRel).toBeDefined();
    expect(officeDocRel!.target).toBe('word/document.xml');
    expect(officeDocRel!.targetMode).toBe('Internal');
  });

  it('解析 document.xml.rels 並能 resolve rId → 絕對 path', () => {
    const buf = loadFixture('01_simple/03.1120815-監造會議記錄.docx');
    const pkg = reader.parse(buf);

    const docRels = pkg.getRelationships('word/document.xml');
    expect(docRels.size).toBeGreaterThan(0);

    // 每個 rId 都能 resolve
    for (const [rId, def] of docRels) {
      const resolved = pkg.resolveRelationship('word/document.xml', rId);
      expect(resolved).toBe(def.target);
      // 內部關係的 target 不應有前導 "/"
      if (def.targetMode === 'Internal') {
        expect(def.target.startsWith('/')).toBe(false);
      }
    }

    // styles 關係必須存在
    const stylesRel = [...docRels.values()].find((r) => r.type.endsWith('/styles'));
    expect(stylesRel).toBeDefined();
    expect(stylesRel!.target).toBe('word/styles.xml');
  });

  it('複雜表格 fixture 仍能解包，含媒體檔', () => {
    const buf = loadFixture('03_complex_table/1121229-全套管基樁混凝土查驗(共1).docx');
    const pkg = reader.parse(buf);

    // 解包成功
    expect(pkg.parts.size).toBeGreaterThan(2);
    expect(pkg.getPart('word/document.xml')).toBeDefined();

    // 不該有 [Content_Types].xml 出現在 parts 中
    expect(pkg.parts.has('[Content_Types].xml')).toBe(false);

    // .rels 檔案不該出現在 parts（應該在 relationships）
    for (const path of pkg.parts.keys()) {
      expect(path.endsWith('.rels')).toBe(false);
    }
  });

  it('壞 ZIP buffer 必須丟錯', () => {
    const garbage = new Uint8Array([1, 2, 3, 4, 5]).buffer;
    expect(() => reader.parse(garbage)).toThrow();
  });
});
