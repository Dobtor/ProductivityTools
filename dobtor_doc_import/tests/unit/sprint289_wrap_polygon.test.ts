/**
 * Sprint 289 — ③ Phase 3.4 wrapTight 多邊形 capture。
 *
 * Strategy A capture-only：parser + AST capture wrapPolygon raw coordinates；
 * render 端 layout 走真實 polygon clip 為 Phase 3.4 完整 wrapTight 範圍
 * （紀律 #18 scope-down，留 future cluster）。
 *
 * OOXML §20.4.2.10 wp:wrapPolygon 結構：
 *   - 出現於 wp:wrapTight / wp:wrapThrough 內
 *   - <wp:start x y/> + 1+ <wp:lineTo x y/>
 *   - edited 屬性（user 編輯過為 "1"/true）
 *   - 座標為 drawing coordinates（不直接是 EMU），caller 拿 raw int
 */
import { describe, expect, it } from 'vitest';

import { DrawingParser } from '../../static/src/core/ooxml/drawing/DrawingParser';
import type { FloatImageNode } from '../../static/src/core/ooxml/ast/types';

const NS = [
  'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"',
  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"',
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"',
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"',
  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"',
].join(' ');

const BLIP_BLOCK = `
  <a:graphic>
    <a:graphicData>
      <pic:pic>
        <pic:blipFill>
          <a:blip r:embed="rIdImg8"/>
        </pic:blipFill>
      </pic:pic>
    </a:graphicData>
  </a:graphic>
`;

function parseAnchorWithWrap(wrapInner: string): FloatImageNode {
  const xml = `<?xml version="1.0"?>
    <w:document ${NS}>
      <w:body>
        <w:p>
          <w:r>
            <w:drawing>
              <wp:anchor behindDoc="0">
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

describe('Sprint 289 — wp:wrapPolygon capture (wrapTight)', () => {
  it('wrapTight + 完整四角矩形 polygon → start + 4 lineTo 全 capture', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides">
        <wp:wrapPolygon edited="1">
          <wp:start x="0" y="0"/>
          <wp:lineTo x="21337" y="0"/>
          <wp:lineTo x="21337" y="21472"/>
          <wp:lineTo x="0" y="21472"/>
          <wp:lineTo x="0" y="0"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapType).toBe('tight');
    expect(node.wrapPolygon).toBeDefined();
    expect(node.wrapPolygon?.edited).toBe(true);
    expect(node.wrapPolygon?.start).toEqual({ x: 0, y: 0 });
    expect(node.wrapPolygon?.lineTo).toHaveLength(4);
    expect(node.wrapPolygon?.lineTo[0]).toEqual({ x: 21337, y: 0 });
    expect(node.wrapPolygon?.lineTo[1]).toEqual({ x: 21337, y: 21472 });
    expect(node.wrapPolygon?.lineTo[2]).toEqual({ x: 0, y: 21472 });
    expect(node.wrapPolygon?.lineTo[3]).toEqual({ x: 0, y: 0 });
  });

  it('wrapTight + 不規則多邊形（8 點） → 全部 capture、順序保留', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="largest">
        <wp:wrapPolygon edited="1">
          <wp:start x="5000" y="0"/>
          <wp:lineTo x="15000" y="0"/>
          <wp:lineTo x="21600" y="10000"/>
          <wp:lineTo x="15000" y="21600"/>
          <wp:lineTo x="5000" y="21600"/>
          <wp:lineTo x="0" y="10000"/>
          <wp:lineTo x="5000" y="0"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapPolygon?.lineTo).toHaveLength(6);
    expect(node.wrapPolygon?.start).toEqual({ x: 5000, y: 0 });
    expect(node.wrapPolygon?.lineTo[2]).toEqual({ x: 15000, y: 21600 });
    expect(node.wrapPolygon?.lineTo[5]).toEqual({ x: 5000, y: 0 });
  });

  it('wrapTight 無 edited 屬性 → polygon 存在、edited === undefined', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides">
        <wp:wrapPolygon>
          <wp:start x="0" y="0"/>
          <wp:lineTo x="21600" y="21600"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapPolygon).toBeDefined();
    expect(node.wrapPolygon?.edited).toBeUndefined();
    expect(node.wrapPolygon?.lineTo).toHaveLength(1);
  });

  it('wrapTight 無 wrapPolygon 子元素 → wrapPolygon === undefined', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides"/>
    `);
    expect(node.wrapType).toBe('tight');
    expect(node.wrapPolygon).toBeUndefined();
  });

  it('wrapTight + wrapPolygon 缺 start → undefined（不 throw）', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides">
        <wp:wrapPolygon>
          <wp:lineTo x="100" y="100"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapPolygon).toBeUndefined();
  });

  it('wrapTight + wrapPolygon 有 start 但無 lineTo → undefined（不算合法 polygon）', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides">
        <wp:wrapPolygon>
          <wp:start x="0" y="0"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapPolygon).toBeUndefined();
  });

  it('wrapTight + 點屬性缺/非數字 → 該點略過、其餘保留', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapTight wrapText="bothSides">
        <wp:wrapPolygon>
          <wp:start x="0" y="0"/>
          <wp:lineTo x="100" y="100"/>
          <wp:lineTo x="bad" y="200"/>
          <wp:lineTo x="300"/>
          <wp:lineTo x="400" y="400"/>
        </wp:wrapPolygon>
      </wp:wrapTight>
    `);
    expect(node.wrapPolygon?.lineTo).toHaveLength(2);
    expect(node.wrapPolygon?.lineTo[0]).toEqual({ x: 100, y: 100 });
    expect(node.wrapPolygon?.lineTo[1]).toEqual({ x: 400, y: 400 });
  });
});

describe('Sprint 289 — wp:wrapPolygon capture (wrapThrough)', () => {
  it('wrapThrough + polygon → capture（與 wrapTight 對稱）', () => {
    const node = parseAnchorWithWrap(`
      <wp:wrapThrough wrapText="bothSides">
        <wp:wrapPolygon edited="0">
          <wp:start x="100" y="200"/>
          <wp:lineTo x="500" y="600"/>
          <wp:lineTo x="100" y="200"/>
        </wp:wrapPolygon>
      </wp:wrapThrough>
    `);
    expect(node.wrapType).toBe('through');
    expect(node.wrapPolygon?.edited).toBeUndefined(); // "0" 不 truthy
    expect(node.wrapPolygon?.start).toEqual({ x: 100, y: 200 });
    expect(node.wrapPolygon?.lineTo).toHaveLength(2);
  });
});

describe('Sprint 289 — 其他 wrap mode 不 capture polygon', () => {
  it('wrapSquare → wrapPolygon undefined（規格上不該有）', () => {
    const node = parseAnchorWithWrap(`<wp:wrapSquare wrapText="bothSides"/>`);
    expect(node.wrapPolygon).toBeUndefined();
  });

  it('wrapNone → wrapPolygon undefined', () => {
    const node = parseAnchorWithWrap(`<wp:wrapNone/>`);
    expect(node.wrapPolygon).toBeUndefined();
  });

  it('wrapTopAndBottom → wrapPolygon undefined', () => {
    const node = parseAnchorWithWrap(`<wp:wrapTopAndBottom/>`);
    expect(node.wrapPolygon).toBeUndefined();
  });
});
