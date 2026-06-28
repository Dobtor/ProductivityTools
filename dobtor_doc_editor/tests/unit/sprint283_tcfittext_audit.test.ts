/**
 * Sprint 283 — Phase 1 optional bucket 2/6：`<w:tcFitText>` audit + tests
 *
 * Status：AST + parser + writer 已 wire-up（fitText?: boolean on TableCellProps），
 * 本 sprint = Strategy C 純 audit 補測試覆蓋。0 production code 變動。
 *
 * OOXML §17.4.65 ST_OnOff：val 缺、"1"、"true" → true；"0"、"false" → false。
 * boolFlag helper（TableParser.ts:517）：缺 val 視為 true（OOXML spec 預設）。
 *
 * 範圍：
 *   - Parser 解 5 種 boolean variant
 *   - Writer 只在 fitText === true 時 emit `<w:tcFitText/>`
 *   - Full docx round-trip：AST(fitText=true) → write → unzip → re-parse → preserved
 */
import { describe, expect, it } from 'vitest';
import { DOMParser } from '@xmldom/xmldom';
import { unzipSync, strFromU8 } from 'fflate';

import { TableParser } from '../../static/src/core/ooxml/table/TableParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type { DocumentNode, TableNode, CellNode, RowNode, ParagraphNode, SectionNode } from '../../static/src/core/ooxml/ast/types';

function makeDocWithSectionBody(body: SectionNode['body']): DocumentNode {
  const section: SectionNode = {
    type: 'section',
    page: { width: 595.3, height: 841.9, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
  return {
    type: 'document',
    sections: [section],
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
    comments: new Map(),
    settings: {},
    fontTable: new Map(),
    webSettings: {},
    styles: new Map(),
    numbering: new Map(),
    media: new Map(),
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  } as unknown as DocumentNode;
}

const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

function parseTblFragment(inner: string): Element {
  const xml = `<?xml version="1.0"?><w:document ${W_NS}><w:body>${inner}</w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:tbl')[0];
}

function firstCell(tbl: TableNode): CellNode {
  const row = tbl.rows[0];
  return row.cells[0];
}

describe('Sprint 283 — w:tcFitText audit (Phase 1 optional bucket 2/6)', () => {
  const parser = new TableParser();

  describe('Parser boolean variants（OOXML ST_OnOff、TableParser.boolFlag 行為）', () => {
    it('w:tcFitText 缺 val → fitText=true（OOXML 預設 1）', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr><w:tcFitText/></w:tcPr><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBe(true);
    });

    it('w:tcFitText val="1" → fitText=true', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr><w:tcFitText w:val="1"/></w:tcPr><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBe(true);
    });

    it('w:tcFitText val="true" → fitText=true', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr><w:tcFitText w:val="true"/></w:tcPr><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBe(true);
    });

    it('w:tcFitText val="0" → fitText 不存在於 AST', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr><w:tcFitText w:val="0"/></w:tcPr><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBeUndefined();
    });

    it('w:tcFitText val="false" → fitText 不存在於 AST', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr><w:tcFitText w:val="false"/></w:tcPr><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBeUndefined();
    });

    it('整個 w:tcFitText 缺 → fitText 不存在', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr><w:tc><w:tcPr/><w:p/></w:tc></w:tr>
        </w:tbl>
      `);
      expect(firstCell(parser.parse(tbl)).props.fitText).toBeUndefined();
    });

    it('混合 row：第一 cell fitText=true、第二 cell 無、AST 對應分流', () => {
      const tbl = parseTblFragment(`
        <w:tbl>
          <w:tblGrid><w:gridCol w:w="2880"/><w:gridCol w:w="2880"/></w:tblGrid>
          <w:tr>
            <w:tc><w:tcPr><w:tcFitText/></w:tcPr><w:p/></w:tc>
            <w:tc><w:tcPr/><w:p/></w:tc>
          </w:tr>
        </w:tbl>
      `);
      const t = parser.parse(tbl);
      expect(t.rows[0].cells[0].props.fitText).toBe(true);
      expect(t.rows[0].cells[1].props.fitText).toBeUndefined();
    });
  });

  describe('Writer audit（OoxmlWriter 只在 fitText === true 時 emit）', () => {
    function makeMinimalDocWithFitTextCell(fitText: boolean | undefined): DocumentNode {
      const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [] };
      const cell: CellNode = {
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        content: [para],
        props: fitText !== undefined ? { fitText } : {},
      };
      const row: RowNode = { type: 'row', props: {}, cells: [cell] };
      const table: TableNode = { type: 'table', grid: [72], rows: [row], props: {} };
      return makeDocWithSectionBody([table]);
    }

    function extractDocumentXml(docBytes: Uint8Array): string {
      const unzipped = unzipSync(docBytes);
      return strFromU8(unzipped['word/document.xml']);
    }

    it('fitText=true → document.xml 含 <w:tcFitText/>', () => {
      const writer = new OoxmlWriter();
      const bytes = writer.write(makeMinimalDocWithFitTextCell(true));
      const xml = extractDocumentXml(bytes);
      expect(xml).toContain('<w:tcFitText/>');
    });

    it('fitText=false → 不 emit <w:tcFitText/>', () => {
      const writer = new OoxmlWriter();
      const bytes = writer.write(makeMinimalDocWithFitTextCell(false));
      const xml = extractDocumentXml(bytes);
      expect(xml).not.toContain('<w:tcFitText');
    });

    it('fitText=undefined（缺 prop）→ 不 emit', () => {
      const writer = new OoxmlWriter();
      const bytes = writer.write(makeMinimalDocWithFitTextCell(undefined));
      const xml = extractDocumentXml(bytes);
      expect(xml).not.toContain('<w:tcFitText');
    });
  });

  describe('Full round-trip（OoxmlWriter → unzipSync → OoxmlParser → AST 保留 fitText）', () => {
    it('AST.fitText=true 經 write → re-parse 後仍為 true', async () => {
      const para: ParagraphNode = { type: 'paragraph', props: {}, runs: [] };
      const cell: CellNode = {
        type: 'cell',
        gridCol: 0,
        gridSpan: 1,
        content: [para],
        props: { fitText: true },
      };
      const row: RowNode = { type: 'row', props: {}, cells: [cell] };
      const table: TableNode = { type: 'table', grid: [72], rows: [row], props: {} };
      const doc = makeDocWithSectionBody([table]);

      const writer = new OoxmlWriter();
      const bytes = writer.write(doc);
      const parser2 = new OoxmlParser();
      const reParsed = await parser2.parse(bytes);

      const reTable = reParsed.sections[0].body.find((b): b is TableNode => b.type === 'table');
      expect(reTable).toBeDefined();
      expect(reTable!.rows[0].cells[0].props.fitText).toBe(true);
    });
  });
});
