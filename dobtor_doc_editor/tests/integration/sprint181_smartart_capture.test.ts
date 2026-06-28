/**
 * Sprint 181 整合驗證（Phase 5.2 SmartArt capture-only）
 *
 * 對 08_smartart fixture 的真實 .docx 解析後，確認 OoxmlParser 把 SmartArt
 * 資料模型的文字與版面類型 capture 進 DocumentNode.smartArts。
 *
 * 註：08_smartart fixture 已排除於 04/08/09 baseline 與 VR（PHASE5_FIXTURE_DIRS），
 * 故本檔以專屬 integration test 覆蓋這批 fixture。
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';

function parseFixture(name: string) {
  const buf = readFileSync(resolve(__dirname, '../fixtures/08_smartart/' + name));
  const arr = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new OoxmlParser().parse(arr as ArrayBuffer);
}

describe('Sprint 181 — 真實 docx SmartArt capture', () => {
  it('系統操作介紹(簡略版)：VerticalCircleList、9 段文字', () => {
    const doc = parseFixture('系統操作介紹(簡略版).docx');
    expect(doc.smartArts).toBeDefined();
    expect(doc.smartArts).toHaveLength(1);

    const sa = doc.smartArts![0];
    expect(sa.rId).toBe('rId1');
    expect(sa.layoutType).toBe(
      'urn:microsoft.com/office/officeart/2008/layout/VerticalCircleList',
    );
    expect(sa.texts).toContain('系統功能架構圖');
    expect(sa.texts).toContain('照片管理');
    expect(sa.texts.length).toBeGreaterThanOrEqual(8);
  });

  it('磺港溪C-B中央補助款-V1：LinedList 版面、capture 階層文字', () => {
    const doc = parseFixture('1140831磺港溪C-B中央補助款-V1.docx');
    expect(doc.smartArts).toHaveLength(1);
    const sa = doc.smartArts![0];
    expect(sa.layoutType).toContain('LinedList');
    expect(sa.texts).toContain('監造管理系統');
    expect(sa.texts).toContain('基本資料');
  });

  it('磺港溪C-B中央補助款20250904-V6：chevron2 版面', () => {
    const doc = parseFixture('磺港溪C-B中央補助款20250904-V6.docx');
    expect(doc.smartArts).toHaveLength(1);
    expect(doc.smartArts![0].layoutType).toContain('chevron');
    expect(doc.smartArts![0].texts).toContain('縮短時間');
  });

  it('SmartArt 文字皆非空白（已過濾 presentation 點與空段落）', () => {
    const doc = parseFixture('系統操作介紹(簡略版)_2.docx');
    const sa = doc.smartArts![0];
    expect(sa.texts.length).toBeGreaterThan(0);
    for (const t of sa.texts) {
      expect(t.trim().length).toBeGreaterThan(0);
    }
  });
});
