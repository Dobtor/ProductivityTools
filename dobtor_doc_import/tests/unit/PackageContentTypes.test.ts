/**
 * PackageContentTypes.test.ts — Sprint 152 (Phase 1 capture-only、[Content_Types].xml)
 *
 * 驗證 OoxmlPackage.contentTypes 暴露:
 *   - 真實 fixture 解析正確(defaults / overrides)
 *   - readonly 形式保證(對外不可變動)
 *   - 與 PackagePart.contentType 一致(Override 優先於 Default)
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PackageReader } from '../../static/src/core/ooxml/package/PackageReader';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function loadFixture(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

describe('PackageContentTypes — defaults', () => {
  const reader = new PackageReader();

  it('包含 rels 與 xml 兩個 Default Extension', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    expect(pkg.contentTypes.defaults.get('rels')).toContain('relationships+xml');
    expect(pkg.contentTypes.defaults.get('xml')).toBe('application/xml');
  });

  it('Default Extension 一律小寫 key', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    for (const ext of pkg.contentTypes.defaults.keys()) {
      expect(ext).toBe(ext.toLowerCase());
    }
  });
});

describe('PackageContentTypes — overrides', () => {
  const reader = new PackageReader();

  it('document.xml 有 Override entry', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    const ct = pkg.contentTypes.overrides.get('word/document.xml');
    expect(ct).toContain('wordprocessingml.document.main');
  });

  it('styles.xml / settings.xml / fontTable.xml 都有 Override', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    expect(pkg.contentTypes.overrides.get('word/styles.xml')).toContain(
      'wordprocessingml.styles',
    );
    expect(pkg.contentTypes.overrides.get('word/settings.xml')).toContain(
      'wordprocessingml.settings',
    );
    expect(pkg.contentTypes.overrides.get('word/fontTable.xml')).toContain(
      'wordprocessingml.fontTable',
    );
  });

  it('PartName 無前導 "/"', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    for (const partName of pkg.contentTypes.overrides.keys()) {
      expect(partName.startsWith('/')).toBe(false);
    }
  });

  it('size > 0 (real Word fixture 必有多個 Override)', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    expect(pkg.contentTypes.overrides.size).toBeGreaterThan(5);
  });
});

describe('PackageContentTypes — 與 PackagePart.contentType 一致性', () => {
  const reader = new PackageReader();

  it('Override 優先於 Default(document.xml 走 Override)', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    const part = pkg.getPart('word/document.xml')!;
    const fromTable = pkg.contentTypes.overrides.get('word/document.xml');
    expect(part.contentType).toBe(fromTable);
  });

  it('純 Default 走 fallback(無 Override 的 .rels 用 Default)', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    // .rels 通常無 Override、走 Default
    const defaultCt = pkg.contentTypes.defaults.get('rels');
    expect(defaultCt).toBeDefined();
    // ※ relationships 不屬 parts、但 fallback 邏輯仍依 Default 表
  });
});

describe('PackageContentTypes — 跨 fixture 通用性', () => {
  const reader = new PackageReader();

  const samples = [
    '01_simple/03.1120815-監造會議記錄.docx',
    '04_with_image/05.112磺港溪監造會議照片.docx',
    '03_complex_table/06-8估驗計價前履約文件查對項目一覽表（112年12月27日修訂）11409.docx',
    '06_template/缺失改善(預設樣板).docx',
  ];

  for (const path of samples) {
    it(`${path} 都有 document.xml Override`, () => {
      const pkg = reader.parse(loadFixture(path));
      expect(pkg.contentTypes.overrides.get('word/document.xml')).toContain(
        'wordprocessingml.document.main',
      );
    });
  }
});

describe('PackageContentTypes — capture-only 性質', () => {
  const reader = new PackageReader();

  it('暴露為 ReadonlyMap (TypeScript 編譯期保證、runtime 仍是 Map 實例)', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    // ReadonlyMap 是 TS 介面、runtime 仍是 Map 實例
    expect(pkg.contentTypes.defaults instanceof Map).toBe(true);
    expect(pkg.contentTypes.overrides instanceof Map).toBe(true);
  });

  it('size 屬性可讀(driver code 可用於 docx export 對稱性檢查)', () => {
    const pkg = reader.parse(loadFixture('01_simple/03.1120815-監造會議記錄.docx'));
    expect(pkg.contentTypes.defaults.size).toBeGreaterThan(0);
    expect(pkg.contentTypes.overrides.size).toBeGreaterThan(0);
  });
});
