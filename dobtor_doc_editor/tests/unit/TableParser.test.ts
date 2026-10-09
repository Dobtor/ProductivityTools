/**
 * TableParser 單元測試 (Phase B.5)
 *
 * 驗證：
 *   - tblGrid 寬度
 *   - tblPr：tblW / tblInd / jc / tblBorders / tblLook / tblStyle
 *   - tcPr：gridSpan / vMerge / tcW / tcBorders / shd / tcMar / vAlign / noWrap
 *   - trPr：trHeight + hRule / tblHeader / cantSplit
 *   - cell 內容 reuse DocumentParser.parseBodyContent
 *
 * vMerge rowSpan 計算的完整版測試在 GridResolver.test.ts（Phase B.6）。
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

describe('TableParser — tblGrid', () => {
  it('解析 gridCol 寬度為 pt', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid>
          <w:gridCol w:w="1440"/>
          <w:gridCol w:w="2880"/>
          <w:gridCol w:w="720"/>
        </w:tblGrid>
        <w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.grid).toEqual([72, 144, 36]);
  });
});

describe('TableParser — tblPr', () => {
  it('tblStyle / tblW(dxa) / tblInd / jc', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblPr>
          <w:tblStyle w:val="MyTableStyle"/>
          <w:tblW w:w="9000" w:type="dxa"/>
          <w:tblInd w:w="180"/>
          <w:jc w:val="center"/>
        </w:tblPr>
        <w:tblGrid><w:gridCol w:w="9000"/></w:tblGrid>
        <w:tr><w:tc><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.styleId).toBe('MyTableStyle');
    expect(t.props.width).toBe(450); // 9000 twip → 450pt
    expect(t.props.widthType).toBe('dxa');
    expect(t.props.indent).toBe(9); // 180 twip → 9pt
    expect(t.props.alignment).toBe('center');
  });

  it('tblW pct widthType 不轉 width', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblPr><w:tblW w:w="5000" w:type="pct"/></w:tblPr>
        <w:tblGrid/>
        <w:tr><w:tc><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.props.width).toBeUndefined();
    expect(t.props.widthType).toBe('pct');
  });

  it('tblBorders 完整邊框', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblPr>
          <w:tblBorders>
            <w:top w:val="single" w:sz="4" w:color="auto"/>
            <w:bottom w:val="double" w:sz="8" w:color="FF0000"/>
            <w:left w:val="single" w:sz="4"/>
            <w:right w:val="single" w:sz="4"/>
            <w:insideH w:val="dotted" w:sz="2"/>
            <w:insideV w:val="dashed" w:sz="2"/>
          </w:tblBorders>
        </w:tblPr>
        <w:tblGrid/>
        <w:tr><w:tc><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.props.borders?.top?.style).toBe('single');
    expect(t.props.borders?.top?.width).toBeCloseTo(0.5, 2); // 4/8 = 0.5pt
    expect(t.props.borders?.bottom?.style).toBe('double');
    expect(t.props.borders?.bottom?.width).toBeCloseTo(1, 2); // 8/8 = 1pt
    expect(t.props.borders?.bottom?.color).toBe('FF0000');
    expect(t.props.borders?.insideH?.style).toBe('dotted');
    expect(t.props.borders?.insideV?.style).toBe('dashed');
  });
});

describe('TableParser — cell tcPr', () => {
  it('gridSpan / 累計 gridCol', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid>
          <w:gridCol w:w="1000"/><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/>
        </w:tblGrid>
        <w:tr>
          <w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p/></w:tc>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells).toHaveLength(2);
    expect(t.rows[0].cells[0].gridCol).toBe(0);
    expect(t.rows[0].cells[0].gridSpan).toBe(2);
    expect(t.rows[0].cells[1].gridCol).toBe(2);
    expect(t.rows[0].cells[1].gridSpan).toBe(1);
  });

  it('vMerge restart / continue 標記 isContinuation + GridResolver 計算 rowSpan', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    // 第一格 = restart（isContinuation=false）
    expect(t.rows[0].cells[0].isContinuation).toBe(false);
    // 第二、三格 = continue（isContinuation=true）
    expect(t.rows[1].cells[0].isContinuation).toBe(true);
    expect(t.rows[2].cells[0].isContinuation).toBe(true);
    // Phase B.6 GridResolver 整合後：anchor.rowSpan = 3
    expect(t.rows[0].cells[0].rowSpan).toBe(3);
    // continue 格子的 rowSpan 仍為 1（Renderer 跳過繪製）
    expect(t.rows[1].cells[0].rowSpan).toBe(1);
    expect(t.rows[2].cells[0].rowSpan).toBe(1);
  });

  it('tcW dxa 換算', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid>
        <w:tr><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr><w:p/></w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.width).toBe(100); // 2000/20 = 100pt
  });

  it('tcBorders 完整解析', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc>
          <w:tcPr>
            <w:tcBorders>
              <w:top w:val="single" w:sz="8" w:color="000000"/>
              <w:bottom w:val="single" w:sz="8" w:color="000000"/>
            </w:tcBorders>
          </w:tcPr>
          <w:p/>
        </w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.borders?.top?.style).toBe('single');
    expect(t.rows[0].cells[0].props.borders?.top?.color).toBe('000000');
  });

  it('shd fill / color', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc>
          <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="FFFF00"/></w:tcPr>
          <w:p/>
        </w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.shading?.fill).toBe('FFFF00');
    expect(t.rows[0].cells[0].props.shading?.pattern).toBe('clear');
  });

  it('tcMar 邊界', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc>
          <w:tcPr>
            <w:tcMar>
              <w:top w:w="100" w:type="dxa"/>
              <w:bottom w:w="100" w:type="dxa"/>
              <w:left w:w="200" w:type="dxa"/>
              <w:right w:w="200" w:type="dxa"/>
            </w:tcMar>
          </w:tcPr>
          <w:p/>
        </w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.margins?.top).toBe(5); // 100/20 = 5pt
    expect(t.rows[0].cells[0].props.margins?.left).toBe(10);
  });

  it('vAlign / noWrap', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc>
          <w:tcPr>
            <w:vAlign w:val="center"/>
            <w:noWrap/>
          </w:tcPr>
          <w:p/>
        </w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.vAlign).toBe('center');
    expect(t.rows[0].cells[0].props.noWrap).toBe(true);
  });

  // Sprint 34：完整 ST_TextDirection 6 種值（lrTb/tbRl/btLr/lrTbV/tbRlV/tbLrV）
  it.each(['lrTb', 'tbRl', 'btLr', 'lrTbV', 'tbRlV', 'tbLrV'])(
    'textDirection=%s 接受並映射到 cell.props.textDirection',
    (val) => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
          <w:tr><w:tc>
            <w:tcPr>
              <w:textDirection w:val="${val}"/>
            </w:tcPr>
            <w:p/>
          </w:tc></w:tr>
        </w:tbl>
      `);
      const t = parser.parse(tbl);
      expect(t.rows[0].cells[0].props.textDirection).toBe(val);
    },
  );

  it('未知 textDirection 值被忽略（向下相容）', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr><w:tc>
          <w:tcPr>
            <w:textDirection w:val="未知值"/>
          </w:tcPr>
          <w:p/>
        </w:tc></w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].props.textDirection).toBeUndefined();
  });
});

describe('TableParser — trPr', () => {
  it('trHeight w:val 換算 + hRule', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="800" w:hRule="exact"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBe(40); // 800/20 = 40pt
    expect(t.rows[0].props.heightRule).toBe('exact');
  });

  // ─── Sprint 121：進階 row height 邊界 ──────────────────────────
  it('Sprint 121 — trHeight 無 hRule（隱含 auto）保留 height', () => {
    // 真實 fixture 大量出現的 case：<w:trHeight w:val="333"/>
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="600"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBe(30); // 600/20 = 30pt
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — trHeight 顯式 hRule="auto"', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="400" w:hRule="auto"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBe(20);
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — val=0 配 hRule=exact 保留為合法零高度行', () => {
    // Word 會渲染塌陷列；不能 strip
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="0" w:hRule="exact"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBe(0);
    expect(t.rows[0].props.heightRule).toBe('exact');
  });

  it('Sprint 121 — val=0 配 hRule=auto/缺 strip height（auto 0 無下限意義）', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="0"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBeUndefined();
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — 負 val 視為缺 val、hRule=exact 隨之 demote 為 auto', () => {
    // 防御解析：val<0 不合 ECMA-376、視為無 val；exact 沒 val 不能成立
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="-100" w:hRule="exact"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBeUndefined();
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — hRule="atLeast" 無 val 時 demote 為 auto', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:hRule="atLeast"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBeUndefined();
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — 未知 hRule 值 fallback 為 auto（不 throw）', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="500" w:hRule="weirdNewRule"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBe(25);
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — NaN val（非數字）視為缺 val', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:trHeight w:val="abc"/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBeUndefined();
    expect(t.rows[0].props.heightRule).toBe('auto');
  });

  it('Sprint 121 — 完全沒 trHeight 時兩值都 undefined', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:tblHeader/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.height).toBeUndefined();
    expect(t.rows[0].props.heightRule).toBeUndefined();
  });

  it('tblHeader 與 cantSplit', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>
          <w:tc><w:p/></w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].props.isHeader).toBe(true);
    expect(t.rows[0].props.cantSplit).toBe(true);
  });
});

describe('TableParser — cell content', () => {
  it('cell 內多段落保留', () => {
    const tbl = parseTblFragment(`
      <w:tbl>
        <w:tblGrid><w:gridCol w:w="1000"/></w:tblGrid>
        <w:tr>
          <w:tc>
            <w:p><w:r><w:t>line 1</w:t></w:r></w:p>
            <w:p><w:r><w:t>line 2</w:t></w:r></w:p>
            <w:p><w:r><w:t>line 3</w:t></w:r></w:p>
          </w:tc>
        </w:tr>
      </w:tbl>
    `);
    const t = parser.parse(tbl);
    expect(t.rows[0].cells[0].content).toHaveLength(3);
  });
});
