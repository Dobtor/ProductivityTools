/**
 * Sprint 286 — Phase 1 optional bucket 5/6：`<wp:effectExtent>` 陰影/光暈外擴。
 *
 * 既有：DrawingParser 在 Sprint 38 註明「由 Renderer 處理」、實際完全未解析。
 * 本 sprint = Strategy A（輕量）：parser 補 + AST optional field + writer emit +
 * round-trip 測試。Renderer 端 layout 用途留後續（不變更）。
 *
 * 紀律 #18 scope-down：不把 effectExtent 接入 Layout（chained ShapingEngine /
 * LineBreaker 不需要）；layout 影響在 render 時若需要可再加。
 *
 * OOXML §20.4.2.6：四向 EMU 屬性（l/t/r/b），可全 0、可缺漏。
 *   - 0 EMU = 0 pt
 *   - 9525 EMU = 1 pt（近似；實際 12700 EMU = 1 pt，但 9525 為 OOXML 慣例邊角）
 *   - 914400 EMU = 1 inch = 72 pt
 */
import { describe, expect, it } from 'vitest';
import { unzipSync, strFromU8 } from 'fflate';

import { DrawingParser } from '../../static/src/core/ooxml/drawing/DrawingParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import type {
  DocumentNode,
  InlineImageNode,
  ParagraphNode,
  SectionNode,
} from '../../static/src/core/ooxml/ast/types';

const NS = [
  'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"',
  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"',
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"',
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"',
  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"',
  'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"',
].join(' ');

const BLIP_BLOCK = `
  <a:graphic>
    <a:graphicData>
      <pic:pic>
        <pic:blipFill>
          <a:blip r:embed="rIdImg7"/>
        </pic:blipFill>
      </pic:pic>
    </a:graphicData>
  </a:graphic>
`;

function parseFragment(inner: string): Element {
  const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>${inner}</w:r></w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:drawing')[0];
}

const parser = new DrawingParser();

describe('Sprint 286 — wp:effectExtent parser (DrawingParser)', () => {
  it('wp:inline + effectExtent 全 0 → AST 帶 effectExtent 物件、四向皆 0', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:effectExtent l="0" t="0" r="0" b="0"/>
          <wp:docPr id="1" name="Pic 1"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('inlineImage');
    if (node.type !== 'inlineImage') return;
    expect(node.effectExtent).toBeDefined();
    expect(node.effectExtent?.left).toBe(0);
    expect(node.effectExtent?.top).toBe(0);
    expect(node.effectExtent?.right).toBe(0);
    expect(node.effectExtent?.bottom).toBe(0);
  });

  it('wp:inline + effectExtent 非零 → EMU → Pt 正確（914400 EMU = 72 pt）', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:effectExtent l="914400" t="0" r="457200" b="228600"/>
          <wp:docPr id="1" name="Pic 1"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.effectExtent?.left).toBeCloseTo(72, 1);
    expect(node.effectExtent?.top).toBe(0);
    expect(node.effectExtent?.right).toBeCloseTo(36, 1);
    expect(node.effectExtent?.bottom).toBeCloseTo(18, 1);
  });

  it('wp:inline 缺 effectExtent → AST 無 effectExtent 欄位（undefined）', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:docPr id="1" name="Pic 1"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.effectExtent).toBeUndefined();
  });

  it('wp:inline + effectExtent 缺屬性 → 該屬性視為 0、不 throw', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:effectExtent l="914400" b="228600"/>
          <wp:docPr id="1" name="Pic 1"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.effectExtent?.left).toBeCloseTo(72, 1);
    expect(node.effectExtent?.top).toBe(0);
    expect(node.effectExtent?.right).toBe(0);
    expect(node.effectExtent?.bottom).toBeCloseTo(18, 1);
  });

  it('wp:inline + effectExtent 非數字屬性 → 該軸退化為 0', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:effectExtent l="not-a-number" t="0" r="0" b="0"/>
          <wp:docPr id="1" name="Pic 1"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.effectExtent?.left).toBe(0);
  });

  it('wp:anchor (FloatImage) + effectExtent → 解析到 FloatImageNode', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:anchor behindDoc="0" allowOverlap="1">
          <wp:positionH relativeFrom="margin"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:extent cx="914400" cy="457200"/>
          <wp:effectExtent l="228600" t="228600" r="228600" b="228600"/>
          <wp:wrapSquare wrapText="bothSides"/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('floatImage');
    if (node.type !== 'floatImage') return;
    expect(node.effectExtent?.left).toBeCloseTo(18, 1);
    expect(node.effectExtent?.top).toBeCloseTo(18, 1);
    expect(node.effectExtent?.right).toBeCloseTo(18, 1);
    expect(node.effectExtent?.bottom).toBeCloseTo(18, 1);
  });
});

// ── Round-trip via OoxmlWriter + OoxmlParser ─────────────────────────────────

function makeDoc(body: SectionNode['body']): DocumentNode {
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

function makeImageParagraph(img: InlineImageNode): ParagraphNode {
  return { type: 'paragraph', runs: [img], props: {} };
}

describe('Sprint 286 — wp:effectExtent writer + round-trip', () => {
  it('AST 帶 effectExtent → writer emit `<wp:effectExtent>`、EMU 正確', () => {
    const img: InlineImageNode = {
      type: 'inlineImage',
      rId: 'rIdImg1',
      width: 72,
      height: 36,
      effectExtent: { left: 18, top: 0, right: 36, bottom: 9 },
    };
    const doc = makeDoc([makeImageParagraph(img)]);
    const bytes = new OoxmlWriter().write(doc);
    const xml = strFromU8(unzipSync(bytes)['word/document.xml']);
    // 18 pt × 12700 EMU/pt = 228600；36 → 457200；9 → 114300
    expect(xml).toContain('<wp:effectExtent l="228600" t="0" r="457200" b="114300"/>');
  });

  it('AST 無 effectExtent → writer 不 emit（既有行為保留）', () => {
    const img: InlineImageNode = {
      type: 'inlineImage',
      rId: 'rIdImg1',
      width: 72,
      height: 36,
    };
    const doc = makeDoc([makeImageParagraph(img)]);
    const bytes = new OoxmlWriter().write(doc);
    const xml = strFromU8(unzipSync(bytes)['word/document.xml']);
    expect(xml).not.toContain('<wp:effectExtent');
  });

  it('Round-trip：AST(effectExtent) → write → re-parse → AST 仍帶相同 effectExtent', async () => {
    const original: InlineImageNode = {
      type: 'inlineImage',
      rId: 'rIdImg1',
      width: 72,
      height: 36,
      effectExtent: { left: 18, top: 0, right: 36, bottom: 9 },
    };
    const doc = makeDoc([makeImageParagraph(original)]);
    const bytes = new OoxmlWriter().write(doc);
    const reParsed = await new OoxmlParser().parse(bytes);

    const section = reParsed.sections[0];
    const para = section.body[0] as ParagraphNode;
    const inline = para.runs.find((r) => r.type === 'inlineImage') as InlineImageNode | undefined;
    expect(inline).toBeDefined();
    expect(inline?.effectExtent).toBeDefined();
    expect(inline?.effectExtent?.left).toBeCloseTo(18, 1);
    expect(inline?.effectExtent?.top).toBe(0);
    expect(inline?.effectExtent?.right).toBeCloseTo(36, 1);
    expect(inline?.effectExtent?.bottom).toBeCloseTo(9, 1);
  });

  it('Round-trip：全 0 effectExtent 也保留（lossless：不被 collapse 成 undefined）', async () => {
    const original: InlineImageNode = {
      type: 'inlineImage',
      rId: 'rIdImg1',
      width: 72,
      height: 36,
      effectExtent: { left: 0, top: 0, right: 0, bottom: 0 },
    };
    const doc = makeDoc([makeImageParagraph(original)]);
    const bytes = new OoxmlWriter().write(doc);
    const reParsed = await new OoxmlParser().parse(bytes);

    const section = reParsed.sections[0];
    const para = section.body[0] as ParagraphNode;
    const inline = para.runs.find((r) => r.type === 'inlineImage') as InlineImageNode | undefined;
    expect(inline?.effectExtent).toBeDefined();
    expect(inline?.effectExtent?.left).toBe(0);
    expect(inline?.effectExtent?.right).toBe(0);
  });
});
