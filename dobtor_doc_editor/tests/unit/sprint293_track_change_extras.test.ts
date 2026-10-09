/**
 * Sprint 293 — Phase 5.4 追蹤修訂剩餘項 capture（pPrChange / rPrChange / cellIns/Del/Merge）。
 *
 * Follow-up to Sprint 290 honest gap:
 *   - Sprint 174: ins/del 已 capture
 *   - Sprint 290: moveFrom/moveTo 已 capture
 *   - 本 sprint 補：屬性級（pPrChange + rPrChange）+ 表格結構級（cellIns + cellDel + cellMerge）
 *
 * Strategy C+ capture-only：parser/AST 補完整、writer/render 不消費。
 *
 * 紀律 #18 scope-down：本 sprint 不解 *Change 內含的 old pPr/rPr 子樹（即 caller
 *   只拿到「誰在何時改了」、不拿到「改前的舊值」）；老舊值的擷取為未來 polish。
 * 紀律 #21 capture-only：不污染 VR pipeline、不影響 layout/render。
 */
import { describe, expect, it } from 'vitest';

import { parseParagraphProps, parseRunProps } from '../../static/src/core/ooxml/document/ParagraphParser';
import { TableParser } from '../../static/src/core/ooxml/table/TableParser';
import { DocumentParser } from '../../static/src/core/ooxml/document/DocumentParser';

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function parsePPr(inner: string) {
  const xml = `<?xml version="1.0"?><w:document ${W_NS}><w:body><w:p><w:pPr>${inner}</w:pPr></w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const pPr = doc.getElementsByTagName('w:pPr')[0];
  return parseParagraphProps(pPr);
}

function parseRPr(inner: string) {
  const xml = `<?xml version="1.0"?><w:document ${W_NS}><w:body><w:p><w:r><w:rPr>${inner}</w:rPr></w:r></w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const rPr = doc.getElementsByTagName('w:rPr')[0];
  return parseRunProps(rPr);
}

describe('Sprint 293 — w:pPrChange capture', () => {
  it('w:pPrChange 完整屬性 → props.pPrChange = { author, date, id }', () => {
    const props = parsePPr(`
      <w:pPrChange w:id="42" w:author="Alice" w:date="2026-05-27T10:00:00Z">
        <w:pPr><w:jc w:val="left"/></w:pPr>
      </w:pPrChange>
    `);
    expect(props.pPrChange).toBeDefined();
    expect(props.pPrChange?.author).toBe('Alice');
    expect(props.pPrChange?.date).toBe('2026-05-27T10:00:00Z');
    expect(props.pPrChange?.id).toBe(42);
  });

  it('w:pPrChange 全缺屬性 → props.pPrChange = {}（仍標記）', () => {
    const props = parsePPr(`<w:pPrChange/>`);
    expect(props.pPrChange).toEqual({});
  });

  it('無 w:pPrChange → props.pPrChange undefined', () => {
    const props = parsePPr(`<w:jc w:val="center"/>`);
    expect(props.pPrChange).toBeUndefined();
  });

  it('w:pPrChange 非數字 id → id undefined、author/date 仍 capture', () => {
    const props = parsePPr(`<w:pPrChange w:id="not-int" w:author="A"/>`);
    expect(props.pPrChange?.id).toBeUndefined();
    expect(props.pPrChange?.author).toBe('A');
  });
});

describe('Sprint 293 — w:rPrChange capture', () => {
  it('w:rPrChange 完整屬性 → props.rPrChange = { author, date, id }', () => {
    const props = parseRPr(`
      <w:rPrChange w:id="7" w:author="Bob" w:date="2026-05-27T11:00:00Z">
        <w:rPr><w:b/></w:rPr>
      </w:rPrChange>
    `);
    expect(props.rPrChange).toBeDefined();
    expect(props.rPrChange?.author).toBe('Bob');
    expect(props.rPrChange?.date).toBe('2026-05-27T11:00:00Z');
    expect(props.rPrChange?.id).toBe(7);
  });

  it('w:rPrChange 與既有 run 屬性並存 → bold + rPrChange 同時 capture', () => {
    const props = parseRPr(`
      <w:b/>
      <w:rPrChange w:id="8" w:author="C">
        <w:rPr/>
      </w:rPrChange>
    `);
    expect(props.bold).toBe(true);
    expect(props.rPrChange?.author).toBe('C');
  });

  it('無 w:rPrChange → props.rPrChange undefined', () => {
    const props = parseRPr(`<w:b/>`);
    expect(props.rPrChange).toBeUndefined();
  });
});

// ── Cell 追蹤修訂測試 ────────────────────────────────────────────────────────

function parseTableRow(rowInner: string) {
  const xml = `<?xml version="1.0"?>
    <w:document ${W_NS}>
      <w:body>
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid>
          <w:tr>${rowInner}</w:tr>
        </w:tbl>
      </w:body>
    </w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const tbl = doc.getElementsByTagName('w:tbl')[0];
  const docParser = new DocumentParser();
  const parser = new TableParser(docParser);
  return parser.parse(tbl);
}

describe('Sprint 293 — w:cellIns capture', () => {
  it('w:cellIns 完整屬性 → cell.props.cellIns = { author, date, id }', () => {
    const table = parseTableRow(`
      <w:tc>
        <w:tcPr><w:cellIns w:id="5" w:author="Alice" w:date="2026-05-27T12:00:00Z"/></w:tcPr>
        <w:p/>
      </w:tc>
    `);
    const cell = table.rows[0].cells[0];
    expect(cell.props.cellIns).toEqual({
      author: 'Alice',
      date: '2026-05-27T12:00:00Z',
      id: 5,
    });
  });

  it('無 w:cellIns → cell.props.cellIns undefined', () => {
    const table = parseTableRow(`<w:tc><w:tcPr/><w:p/></w:tc>`);
    expect(table.rows[0].cells[0].props.cellIns).toBeUndefined();
  });
});

describe('Sprint 293 — w:cellDel capture', () => {
  it('w:cellDel 完整屬性 → cell.props.cellDel = { author, date, id }', () => {
    const table = parseTableRow(`
      <w:tc>
        <w:tcPr><w:cellDel w:id="6" w:author="Bob"/></w:tcPr>
        <w:p/>
      </w:tc>
    `);
    const cell = table.rows[0].cells[0];
    expect(cell.props.cellDel?.author).toBe('Bob');
    expect(cell.props.cellDel?.id).toBe(6);
  });
});

describe('Sprint 293 — w:cellMerge capture', () => {
  it('w:cellMerge val="vert" → cell.props.cellMerge.val === "vert"', () => {
    const table = parseTableRow(`
      <w:tc>
        <w:tcPr><w:cellMerge w:id="9" w:author="C" w:val="vert" w:vMerge="cont"/></w:tcPr>
        <w:p/>
      </w:tc>
    `);
    const cell = table.rows[0].cells[0];
    expect(cell.props.cellMerge?.author).toBe('C');
    expect(cell.props.cellMerge?.id).toBe(9);
    expect(cell.props.cellMerge?.val).toBe('vert');
    expect(cell.props.cellMerge?.vMerge).toBe('cont');
  });

  it('w:cellMerge val="invalid" → val undefined（不接受非規格值）', () => {
    const table = parseTableRow(`
      <w:tc>
        <w:tcPr><w:cellMerge w:id="10" w:val="invalid"/></w:tcPr>
        <w:p/>
      </w:tc>
    `);
    expect(table.rows[0].cells[0].props.cellMerge?.val).toBeUndefined();
    expect(table.rows[0].cells[0].props.cellMerge?.id).toBe(10);
  });

  it('w:cellMerge 全缺 val/vMerge → val/vMerge undefined、author/date/id 仍可', () => {
    const table = parseTableRow(`
      <w:tc>
        <w:tcPr><w:cellMerge w:author="Dave"/></w:tcPr>
        <w:p/>
      </w:tc>
    `);
    const m = table.rows[0].cells[0].props.cellMerge;
    expect(m?.author).toBe('Dave');
    expect(m?.val).toBeUndefined();
    expect(m?.vMerge).toBeUndefined();
  });
});

describe('Sprint 293 — 三 cell 修訂並存', () => {
  it('多 cell 各自掛不同 tracked change 不互相干擾', () => {
    const table = parseTableRow(`
      <w:tc><w:tcPr><w:cellIns w:id="1" w:author="A"/></w:tcPr><w:p/></w:tc>
      <w:tc><w:tcPr><w:cellDel w:id="2" w:author="B"/></w:tcPr><w:p/></w:tc>
    `);
    const cells = table.rows[0].cells;
    expect(cells[0].props.cellIns?.author).toBe('A');
    expect(cells[0].props.cellDel).toBeUndefined();
    expect(cells[1].props.cellDel?.author).toBe('B');
    expect(cells[1].props.cellIns).toBeUndefined();
  });
});
