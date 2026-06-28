/**
 * Phase A Smoke — OoxmlParser orchestrator 端到端煙霧測試
 *
 * 對所有 fixture .docx 全跑一次 OoxmlParser.parse()，要求：
 *   - 不 throw（任何 fixture 解析失敗都應視為 regression）
 *   - 回傳 DocumentNode 結構完整：sections / headers / footers / styles / numbering / media
 *   - 至少有 1 個 section（即便所有 sectPr 都沒給，SectionParser 會用 A4 預設）
 *
 * Phase A 不檢查內容深度（那是 Phase B 各 sub-Parser 的單元測試 + 整合驗收）。
 * 此測試的價值在於：「OoxmlParser.parse() 是 build 鏈通電的最終 Smoke」。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');

function listFixtures(): string[] {
  const out: string[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catDir = resolve(FIXTURE_ROOT, cat);
    if (!statSync(catDir).isDirectory()) continue;
    for (const f of readdirSync(catDir)) {
      if (f.endsWith('.docx')) {
        out.push(`${cat}/${f}`);
      }
    }
  }
  return out;
}

function loadDocxAsBuffer(relativePath: string): ArrayBuffer {
  const buf = readFileSync(resolve(FIXTURE_ROOT, relativePath));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const FIXTURES = listFixtures();
const parser = new OoxmlParser();

describe('Phase A Smoke — OoxmlParser.parse() 對全 fixture 不 throw', () => {
  it('fixture 列表不為空（要至少有 1 份 .docx 才是有意義的 smoke）', () => {
    expect(FIXTURES.length).toBeGreaterThan(0);
  });

  it.each(FIXTURES)('解析 %s 不 throw 且 DocumentNode 結構完整', (relativePath) => {
    const buffer = loadDocxAsBuffer(relativePath);
    const doc = parser.parse(buffer);

    expect(doc.type).toBe('document');

    // 至少 1 個 section（即便沒 sectPr，SectionParser 會用 A4 預設）
    expect(doc.sections.length).toBeGreaterThanOrEqual(1);

    // 每個 section 必須有合法 page + margins
    for (const sec of doc.sections) {
      expect(sec.type).toBe('section');
      expect(sec.page.width).toBeGreaterThan(0);
      expect(sec.page.height).toBeGreaterThan(0);
      expect(['portrait', 'landscape']).toContain(sec.page.orientation);
      expect(sec.margins.top).toBeGreaterThanOrEqual(0);
      expect(sec.margins.bottom).toBeGreaterThanOrEqual(0);
      expect(Array.isArray(sec.body)).toBe(true);
    }

    // metadata Map 都應存在（即便空）
    expect(doc.headers).toBeInstanceOf(Map);
    expect(doc.footers).toBeInstanceOf(Map);
    expect(doc.styles).toBeInstanceOf(Map);
    expect(doc.numbering).toBeInstanceOf(Map);
    expect(doc.media).toBeInstanceOf(Map);
  });
});

describe('Phase A Smoke — fixture 內容抽樣驗證', () => {
  it('01_simple 監造會議記錄第一份至少有 1 個段落', () => {
    const buffer = loadDocxAsBuffer(
      '01_simple/03.1120210-監造會議記錄-1120801.docx',
    );
    const doc = parser.parse(buffer);
    const blocks = doc.sections.flatMap((s) => s.body);
    expect(blocks.length).toBeGreaterThan(0);
    // 至少一個段落
    const paragraphs = blocks.filter((b) => b.type === 'paragraph');
    expect(paragraphs.length).toBeGreaterThan(0);
  });

  it('02_std_table 週報含表格', () => {
    const buffer = loadDocxAsBuffer(
      '02_std_table/1120928-磺港溪再造C段護岸及步道整建工程(延壽橋至三合橋)週報.docx',
    );
    const doc = parser.parse(buffer);
    const tables = doc.sections.flatMap((s) => s.body).filter((b) => b.type === 'table');
    expect(tables.length).toBeGreaterThan(0);
  });

  it('01_simple 監造會議記錄含 header/footer relationships', () => {
    // 注意：05_header_footer/ 目錄下的「自主檢查表」實際上沒有 <w:headerReference>
    // （headers 是用表格 + 邊框模擬的）；真正有 header/footer rels 的 fixture
    // 在 01_simple/ 下的監造會議記錄。
    const buffer = loadDocxAsBuffer(
      '01_simple/03.1120210-監造會議記錄-1120801.docx',
    );
    const doc = parser.parse(buffer);
    const hasHeaderOrFooter = doc.headers.size > 0 || doc.footers.size > 0;
    expect(hasHeaderOrFooter).toBe(true);

    // header/footer 內容應已解析為 BlockNode[]（即便為空陣列也合法 — 例如奇偶頁差異時某種類型可能空）
    for (const hf of [...doc.headers.values(), ...doc.footers.values()]) {
      expect(typeof hf.rId).toBe('string');
      expect(Array.isArray(hf.content)).toBe(true);
    }
  });

  it('04_with_image 監造會議照片含 media 條目', () => {
    const buffer = loadDocxAsBuffer(
      '04_with_image/05.112磺港溪監造會議照片.docx',
    );
    const doc = parser.parse(buffer);
    expect(doc.media.size).toBeGreaterThan(0);
    // 每個 media 值應是 data URL 字串
    for (const url of doc.media.values()) {
      expect(url).toMatch(/^data:image\//);
    }
  });
});
