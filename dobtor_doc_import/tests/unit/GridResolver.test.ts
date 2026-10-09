/**
 * GridResolver 單元測試 (Phase B.6)
 *
 * 驗證 vMerge 兩 pass 演算法：
 *   - 連續 continue 鏈正確設定 anchor.rowSpan
 *   - 多 vMerge 鏈共存（不同 gridCol）互不干擾
 *   - gridSpan + vMerge 組合場景
 *   - 邊界：孤兒 continue / 鏈中斷 / 跨多列
 *
 * 透過 TableParser → 內建 GridResolver 測試端到端流程。
 */

import { describe, expect, it } from 'vitest';
import { TableParser } from '../../static/src/core/ooxml/table/TableParser';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

const parser = new TableParser();

function parseTblFragment(inner: string): Element {
  const xml = `<?xml version="1.0"?><w:document ${W_NS}><w:body>${inner}</w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:tbl')[0];
}

describe('GridResolver — 單一 vMerge 鏈', () => {
  it('3 列 vMerge：anchor.rowSpan = 3', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>anchor</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].rowSpan).toBe(3);
    expect(t.rows[0].cells[0].isContinuation).toBe(false);
    expect(t.rows[1].cells[0].isContinuation).toBe(true);
    expect(t.rows[2].cells[0].isContinuation).toBe(true);
    // continue cell rowSpan 不變（仍為 1）
    expect(t.rows[1].cells[0].rowSpan).toBe(1);
  });

  it('2 列 vMerge：anchor.rowSpan = 2', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].rowSpan).toBe(2);
  });
});

describe('GridResolver — 多 vMerge 鏈共存', () => {
  it('兩條獨立鏈（不同 gridCol）互不干擾', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc>
          <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc>
        </w:tr>
        <w:tr>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
        </w:tr>
        <w:tr>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].rowSpan).toBe(3); // gridCol=0 鏈
    expect(t.rows[0].cells[1].rowSpan).toBe(3); // gridCol=1 鏈
  });

  it('部分欄 vMerge、其餘正常', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>
        </w:tr>
        <w:tr>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].rowSpan).toBe(2); // 欄 0 跨列
    expect(t.rows[0].cells[1].rowSpan).toBe(1); // 欄 1 不跨列
    expect(t.rows[1].cells[1].rowSpan).toBe(1);
  });
});

describe('GridResolver — gridSpan + vMerge 組合', () => {
  it('gridSpan=2 的 anchor 跨多列', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p/></w:tc>
        </w:tr>
        <w:tr>
          <w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    // anchor 在 gridCol 0、gridSpan 2、rowSpan 2
    expect(t.rows[0].cells[0].gridSpan).toBe(2);
    expect(t.rows[0].cells[0].rowSpan).toBe(2);
  });
});

describe('GridResolver — 鏈中斷', () => {
  it('鏈中插入無 vMerge 列：anchor 只到中斷前一列', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:p><w:r><w:t>break</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    // 第一條鏈：列 0-1，rowSpan=2
    expect(t.rows[0].cells[0].rowSpan).toBe(2);
    expect(t.rows[1].cells[0].isContinuation).toBe(true);
    // 列 2 是中斷（normal cell）
    expect(t.rows[2].cells[0].rowSpan).toBe(1);
    expect(t.rows[2].cells[0].isContinuation).toBe(false);
    // 第二條鏈：列 3-4，rowSpan=2
    expect(t.rows[3].cells[0].rowSpan).toBe(2);
    expect(t.rows[4].cells[0].isContinuation).toBe(true);
  });
});

describe('GridResolver — 14 欄送審管制風格（規劃文件痛點）', () => {
  /**
   * 模擬「14 欄送審管制總表」常見結構：
   *   - 第 1 欄「項次」每 2 列垂直合併
   *   - 第 2-3 欄「分類/工項」第一列含整橫 gridSpan=2 標題、後續每列獨立
   *   - 餘下 11 欄為標準資料格
   */
  it('14 欄混合 vMerge / gridSpan 結構正確解析', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid>
          ${Array.from({ length: 14 }, () => '<w:gridCol w:w="500"/>').join('')}
        </w:tblGrid>
        <!-- 標題列：欄 0 vMerge restart；欄 1+2 gridSpan=2 -->
        <w:tr>
          <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>項次</w:t></w:r></w:p></w:tc>
          <w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>分類/工項</w:t></w:r></w:p></w:tc>
          ${Array.from({ length: 11 }, (_, i) => `<w:tc><w:p><w:r><w:t>欄${i + 4}</w:t></w:r></w:p></w:tc>`).join('')}
        </w:tr>
        <!-- 第二列：欄 0 vMerge continue；欄 1, 2 各自獨立 -->
        <w:tr>
          <w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p><w:r><w:t>分類</w:t></w:r></w:p></w:tc>
          <w:tc><w:p><w:r><w:t>工項</w:t></w:r></w:p></w:tc>
          ${Array.from({ length: 11 }, () => '<w:tc><w:p/></w:tc>').join('')}
        </w:tr>
        <!-- 資料列：欄 0 是新 anchor，無 vMerge -->
        <w:tr>
          ${Array.from({ length: 14 }, (_, i) => `<w:tc><w:p><w:r><w:t>row3-${i}</w:t></w:r></w:p></w:tc>`).join('')}
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);

    // grid 寬度 14 欄
    expect(t.grid).toHaveLength(14);

    // 第一列：13 個 cells（gridSpan=2 把欄 1+2 合一）
    expect(t.rows[0].cells).toHaveLength(13);
    expect(t.rows[0].cells[0].gridCol).toBe(0); // 項次
    expect(t.rows[0].cells[0].gridSpan).toBe(1);
    expect(t.rows[0].cells[0].rowSpan).toBe(2); // vMerge anchor
    expect(t.rows[0].cells[1].gridCol).toBe(1); // 分類/工項
    expect(t.rows[0].cells[1].gridSpan).toBe(2);

    // 第二列：14 個 cells（vMerge continue 占欄 0、其餘正常）
    expect(t.rows[1].cells).toHaveLength(14);
    expect(t.rows[1].cells[0].isContinuation).toBe(true); // 項次的 continue
    expect(t.rows[1].cells[0].gridCol).toBe(0);
    expect(t.rows[1].cells[1].gridCol).toBe(1); // 分類
    expect(t.rows[1].cells[2].gridCol).toBe(2); // 工項

    // 第三列：14 個普通格
    expect(t.rows[2].cells).toHaveLength(14);
    expect(t.rows[2].cells.every((c) => !c.isContinuation)).toBe(true);
    expect(t.rows[2].cells[0].rowSpan).toBe(1);
  });
});

describe('GridResolver — 邊界', () => {
  it('孤兒 continue（無 anchor）不 throw', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].isContinuation).toBe(true);
    expect(t.rows[0].cells[0].rowSpan).toBe(1); // 找不到 anchor，rowSpan 維持 1
  });

  it('空表格', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid/>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows).toHaveLength(0);
  });
});
