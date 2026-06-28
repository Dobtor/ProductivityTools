/**
 * DiagramParser 單元測試（Sprint 181、Phase 5.2 SmartArt capture-only）
 *
 * 用手寫 `diagrams/dataN.xml`（`<dgm:dataModel>`）驗證 DiagramParser 的解析輸出。
 * 不依賴 fixture .docx — 純 OOXML 行為單元測試。
 */

import { describe, expect, it } from 'vitest';
import { DiagramParser, smartArtToText } from '../../static/src/core/ooxml/diagram/DiagramParser';
import type { SmartArtNode } from '../../static/src/core/ooxml/ast/types';

const NS =
  'xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" ' +
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"';

/** 把 `<dgm:ptLst>` 內容包進完整 `<dgm:dataModel>`。 */
function dataModel(ptLstInner: string): string {
  return `<?xml version="1.0"?><dgm:dataModel ${NS}><dgm:ptLst>${ptLstInner}</dgm:ptLst></dgm:dataModel>`;
}

/** 產生一個內容點（無 type 屬性），文字為單段落單 run。 */
function contentPt(text: string): string {
  return `<dgm:pt modelId="{x}"><dgm:t><a:bodyPr/><a:lstStyle/>` +
    `<a:p><a:r><a:t>${text}</a:t></a:r></a:p></dgm:t></dgm:pt>`;
}

const parser = new DiagramParser();

describe('DiagramParser — 防禦與邊界', () => {
  it('undefined / 空字串 → undefined', () => {
    expect(parser.parse(undefined, 'rId1')).toBeUndefined();
    expect(parser.parse('', 'rId1')).toBeUndefined();
  });

  it('XML 解析失敗 → undefined（不 throw）', () => {
    expect(parser.parse('<dgm:dataModel <broken', 'rId1')).toBeUndefined();
  });

  it('root 非 <dgm:dataModel> → undefined', () => {
    expect(parser.parse('<?xml version="1.0"?><foo/>', 'rId1')).toBeUndefined();
  });

  it('空 ptLst → SmartArtNode 但 texts 為空陣列', () => {
    const node = parser.parse(dataModel(''), 'rId1');
    expect(node).toEqual({ rId: 'rId1', texts: [] });
  });

  it('rId 原樣寫入 SmartArtNode', () => {
    const node = parser.parse(dataModel(contentPt('A')), 'rId7');
    expect(node?.rId).toBe('rId7');
  });
});

describe('DiagramParser — 內容點文字捕捉', () => {
  it('單一內容點 → texts 含其文字', () => {
    const node = parser.parse(dataModel(contentPt('系統功能架構圖')), 'rId1');
    expect(node?.texts).toEqual(['系統功能架構圖']);
  });

  it('多個內容點 → 依序保留', () => {
    const xml = dataModel(contentPt('登入系統') + contentPt('切換模組') + contentPt('產出報表'));
    const node = parser.parse(xml, 'rId1');
    expect(node?.texts).toEqual(['登入系統', '切換模組', '產出報表']);
  });

  it('type="node" 顯式內容點 → 一樣捕捉', () => {
    const xml = dataModel('<dgm:pt type="node"><dgm:t><a:p><a:r><a:t>X</a:t></a:r></a:p></dgm:t></dgm:pt>');
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['X']);
  });

  it('同段落多個 <a:t> → 拼接為一條', () => {
    const xml = dataModel(
      '<dgm:pt><dgm:t><a:p><a:r><a:t>登入</a:t></a:r><a:r><a:t>&amp;權限</a:t></a:r></a:p></dgm:t></dgm:pt>',
    );
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['登入&權限']);
  });

  it('多段落 <a:p> → 以換行串接', () => {
    const xml = dataModel(
      '<dgm:pt><dgm:t>' +
      '<a:p><a:r><a:t>第一行</a:t></a:r></a:p>' +
      '<a:p><a:r><a:t>第二行</a:t></a:r></a:p>' +
      '</dgm:t></dgm:pt>',
    );
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['第一行\n第二行']);
  });

  it('空文字內容點 → 跳過（不進 texts）', () => {
    const xml = dataModel(
      '<dgm:pt><dgm:t><a:p><a:endParaRPr/></a:p></dgm:t></dgm:pt>' + contentPt('有字'),
    );
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['有字']);
  });

  it('內容點無 <dgm:t> → 跳過', () => {
    const xml = dataModel('<dgm:pt modelId="{x}"><dgm:spPr/></dgm:pt>' + contentPt('保留'));
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['保留']);
  });
});

describe('DiagramParser — presentation / 結構點跳過', () => {
  it('type=pres / parTrans / sibTrans 點 → 跳過', () => {
    const xml = dataModel(
      '<dgm:pt type="pres"><dgm:t><a:p><a:r><a:t>不要</a:t></a:r></a:p></dgm:t></dgm:pt>' +
      '<dgm:pt type="parTrans"/>' +
      '<dgm:pt type="sibTrans"/>' +
      contentPt('要的'),
    );
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['要的']);
  });

  it('非 <dgm:pt> 的 ptLst 子元素 → 忽略', () => {
    const xml = dataModel('<dgm:other/>' + contentPt('文字'));
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['文字']);
  });
});

describe('DiagramParser — 版面類型（layoutType）', () => {
  const LAYOUT = 'urn:microsoft.com/office/officeart/2008/layout/VerticalCircleList';

  it('doc 點的 loTypeId → layoutType', () => {
    const xml = dataModel(
      `<dgm:pt type="doc"><dgm:prSet loTypeId="${LAYOUT}"/></dgm:pt>` + contentPt('A'),
    );
    const node = parser.parse(xml, 'rId1');
    expect(node?.layoutType).toBe(LAYOUT);
    expect(node?.texts).toEqual(['A']);
  });

  it('doc 點無 prSet / 無 loTypeId → 不掛 layoutType key（紀律 #21）', () => {
    const xml = dataModel('<dgm:pt type="doc"><dgm:spPr/></dgm:pt>' + contentPt('A'));
    const node = parser.parse(xml, 'rId1');
    expect(node).toBeDefined();
    expect('layoutType' in (node as object)).toBe(false);
  });

  it('doc 點不貢獻文字到 texts', () => {
    const xml = dataModel(
      '<dgm:pt type="doc"><dgm:prSet/><dgm:t><a:p><a:r><a:t>標題不算</a:t></a:r></a:p></dgm:t></dgm:pt>' +
      contentPt('內容'),
    );
    expect(parser.parse(xml, 'rId1')?.texts).toEqual(['內容']);
  });
});

describe('DiagramParser — Sprint 183 smartArtToText 線性文字 fallback', () => {
  const make = (texts: string[]): SmartArtNode => ({ rId: 'rId1', texts });

  it('空 texts → 空字串', () => {
    expect(smartArtToText(make([]))).toBe('');
  });

  it('單一節點 → 原文字', () => {
    expect(smartArtToText(make(['系統功能架構圖']))).toBe('系統功能架構圖');
  });

  it('多節點 → 以 " / " 串接', () => {
    expect(smartArtToText(make(['登入', '切換模組', '產出報表'])))
      .toBe('登入 / 切換模組 / 產出報表');
  });
});
