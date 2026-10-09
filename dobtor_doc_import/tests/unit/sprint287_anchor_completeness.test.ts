/**
 * Sprint 287 — Phase 1 optional bucket 6/6（最後一項）：`<wp:anchor>` 完整 capture。
 *
 * 既有：Sprint 37/38 capture posH/posV/wrapType/behindDoc/allowOverlap，Sprint 286
 * 補 effectExtent。本 sprint 補剩下：
 *   - distT / distB / distL / distR（文字環繞時與圖片邊距，EMU → Pt）
 *   - relativeHeight（z-order）
 *   - locked / layoutInCell / hidden（Boolean）
 *   - wrap mode 的 wrapText 屬性（left / right / largest / bothSides）
 *
 * Strategy C+ capture-only：parser 補完整、AST 帶 optional fields；writer 仍走
 * Sprint 192「FloatImage 降級為 inline 輸出」(acceptable lossy by design，
 * explicit decision at OoxmlWriter.ts:1391-1394)。紀律 #18 scope-down：不重寫
 * Sprint 192 writer 策略；anchor round-trip 為 deferred。
 *
 * Phase 3.4 wrapTight 多邊形（wp:wrapPolygon）為 user option ③ 獨立 cluster、
 * 不在本 sprint scope。
 */
import { describe, expect, it } from 'vitest';

import { DrawingParser } from '../../static/src/core/ooxml/drawing/DrawingParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { FloatImageNode } from '../../static/src/core/ooxml/ast/types';
import { unzipSync, strFromU8 } from 'fflate';
import type {
  DocumentNode,
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

function parseAnchorDrawing(anchorAttrs: string, wrapInner: string): FloatImageNode {
  const xml = `<?xml version="1.0"?>
    <w:document ${NS}>
      <w:body>
        <w:p>
          <w:r>
            <w:drawing>
              <wp:anchor ${anchorAttrs}>
                <wp:positionH relativeFrom="margin"><wp:posOffset>0</wp:posOffset></wp:positionH>
                <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
                <wp:extent cx="914400" cy="457200"/>
                ${wrapInner}
                ${BLIP_BLOCK}
              </wp:anchor>
            </w:drawing>
          </w:r>
        </w:p>
      </w:body>
    </w:document>
  `;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const drawing = doc.getElementsByTagName('w:drawing')[0];
  const node = new DrawingParser().parse(drawing);
  if (node.type !== 'floatImage') throw new Error(`expected floatImage, got ${node.type}`);
  return node;
}

describe('Sprint 287 — wp:anchor dist* attributes', () => {
  it('distT/distB/distL/distR 四向 EMU → Pt 正確（914400 EMU = 72 pt）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" distT="914400" distB="457200" distL="228600" distR="114300"',
      '<wp:wrapSquare wrapText="bothSides"/>',
    );
    expect(node.anchor).toBeDefined();
    expect(node.anchor?.distT).toBeCloseTo(72, 1);
    expect(node.anchor?.distB).toBeCloseTo(36, 1);
    expect(node.anchor?.distL).toBeCloseTo(18, 1);
    expect(node.anchor?.distR).toBeCloseTo(9, 1);
  });

  it('全缺 dist* → node.anchor 該屬性為 undefined（不偽造預設）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapSquare wrapText="bothSides"/>',
    );
    expect(node.anchor?.distT).toBeUndefined();
    expect(node.anchor?.distB).toBeUndefined();
    expect(node.anchor?.distL).toBeUndefined();
    expect(node.anchor?.distR).toBeUndefined();
  });

  it('部分 dist* 屬性（只 distT/distL）→ 只該屬性掛上', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" distT="914400" distL="228600"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.distT).toBeCloseTo(72, 1);
    expect(node.anchor?.distL).toBeCloseTo(18, 1);
    expect(node.anchor?.distB).toBeUndefined();
    expect(node.anchor?.distR).toBeUndefined();
  });

  it('dist* 非數字屬性 → 該軸退化為 undefined（不 throw）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" distT="not-a-number"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.distT).toBeUndefined();
  });
});

describe('Sprint 287 — wp:anchor relativeHeight (z-order)', () => {
  it('relativeHeight=251658240 → 解析為 251658240（Word 標準 anchor 預設值）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" relativeHeight="251658240"',
      '<wp:wrapSquare wrapText="bothSides"/>',
    );
    expect(node.anchor?.relativeHeight).toBe(251658240);
  });

  it('relativeHeight 負值 → 拒絕（OOXML UInt 不接受負數）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" relativeHeight="-100"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.relativeHeight).toBeUndefined();
  });

  it('relativeHeight 缺漏 → undefined', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.relativeHeight).toBeUndefined();
  });
});

describe('Sprint 287 — wp:anchor locked / layoutInCell / hidden flags', () => {
  it('locked="1" / layoutInCell="1" / hidden="1" → 全 true', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" locked="1" layoutInCell="1" hidden="1"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.locked).toBe(true);
    expect(node.anchor?.layoutInCell).toBe(true);
    expect(node.anchor?.hidden).toBe(true);
  });

  it('false 值不掛欄位（與 srcRect 對稱、不污染預設行為）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0" locked="0" layoutInCell="0" hidden="false"',
      '<wp:wrapNone/>',
    );
    expect(node.anchor?.locked).toBeUndefined();
    expect(node.anchor?.layoutInCell).toBeUndefined();
    expect(node.anchor?.hidden).toBeUndefined();
  });
});

describe('Sprint 287 — wrap mode wrapText attribute', () => {
  it('wrapSquare wrapText="left" → AST.wrapText="left"', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapSquare wrapText="left"/>',
    );
    expect(node.wrapText).toBe('left');
  });

  it('wrapTight wrapText="largest" → AST.wrapText="largest"', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapTight wrapText="largest"/>',
    );
    expect(node.wrapText).toBe('largest');
  });

  it('wrapSquare 無 wrapText 屬性 → undefined（不偽造 bothSides 預設）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapSquare/>',
    );
    expect(node.wrapText).toBeUndefined();
  });

  it('wrapNone（無繞排）→ wrapText undefined', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapNone/>',
    );
    expect(node.wrapText).toBeUndefined();
  });

  it('wrapText 無效值（例如 "invalid"）→ undefined（不 throw）', () => {
    const node = parseAnchorDrawing(
      'behindDoc="0"',
      '<wp:wrapSquare wrapText="invalid"/>',
    );
    expect(node.wrapText).toBeUndefined();
  });
});

describe('Sprint 287 — 整合 capture：完整 anchor 一次抓所有屬性', () => {
  it('真實 Word 風格 anchor → posH/posV/wrapType/anchor/wrapText/effectExtent 全 capture', () => {
    const node = parseAnchorDrawing(
      [
        'behindDoc="0"',
        'allowOverlap="1"',
        'distT="91440"',
        'distB="91440"',
        'distL="114300"',
        'distR="114300"',
        'relativeHeight="251658240"',
        'layoutInCell="1"',
      ].join(' '),
      `
        <wp:effectExtent l="0" t="0" r="0" b="0"/>
        <wp:wrapSquare wrapText="bothSides"/>
      `,
    );
    expect(node.behindDoc).toBeUndefined(); // behindDoc="0" → undefined
    expect(node.allowOverlap).toBe(true);
    expect(node.wrapType).toBe('square');
    expect(node.wrapText).toBe('bothSides');
    expect(node.anchor?.distT).toBeCloseTo(7.2, 1);
    expect(node.anchor?.distL).toBeCloseTo(9, 1);
    expect(node.anchor?.relativeHeight).toBe(251658240);
    expect(node.anchor?.layoutInCell).toBe(true);
    expect(node.anchor?.locked).toBeUndefined();
    expect(node.anchor?.hidden).toBeUndefined();
    expect(node.effectExtent?.left).toBe(0);
  });
});

// ── Honest gap: writer 仍走 Sprint 192 降級為 inline 輸出 ─────────────────────

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

describe('Sprint 287 — Honest gap: writer 仍走 Sprint 192 inline 降級（不在本 sprint scope）', () => {
  it('FloatImage 帶 anchor/wrapText 寫出 → writer 仍 emit <wp:inline>（acceptable lossy by design）', () => {
    const floatImg: FloatImageNode = {
      type: 'floatImage',
      rId: 'rIdImg1',
      width: 72,
      height: 36,
      posH: { relativeFrom: 'margin', posOffset: 100 },
      posV: { relativeFrom: 'paragraph', posOffset: 200 },
      wrapType: 'square',
      anchor: { distT: 7.2, relativeHeight: 251658240, layoutInCell: true },
      wrapText: 'bothSides',
    };
    const para: ParagraphNode = { type: 'paragraph', runs: [floatImg], props: {} };
    const doc = makeDoc([para]);
    const bytes = new OoxmlWriter().write(doc);
    const xml = strFromU8(unzipSync(bytes)['word/document.xml']);

    // Sprint 192 acceptable lossy：寫出仍是 wp:inline、不是 wp:anchor
    expect(xml).toContain('<wp:inline');
    expect(xml).not.toContain('<wp:anchor');
    // anchor metadata 沒有 emit（writer 不知道也不在意）
    expect(xml).not.toContain('relativeHeight');
    expect(xml).not.toContain('layoutInCell');
  });
});
