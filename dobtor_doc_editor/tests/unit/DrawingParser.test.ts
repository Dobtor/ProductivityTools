/**
 * DrawingParser 單元測試 (Phase B.7)
 *
 * 驗證：
 *   - wp:inline → InlineImageNode（rId / width / height / altText）
 *   - wp:anchor → FloatImageNode（posH / posV / wrapType / behindDoc / allowOverlap）
 *   - <a:blip r:embed> 正確找到
 *   - <wp:extent> EMU 換算為 pt
 *   - 5 種 wrap 模式
 */

import { describe, expect, it } from 'vitest';
import { DrawingParser } from '../../static/src/core/ooxml/drawing/DrawingParser';

const NS = [
  'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"',
  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"',
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"',
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"',
  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"',
].join(' ');

const parser = new DrawingParser();

function parseFragment(inner: string): Element {
  const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>${inner}</w:r></w:p></w:body></w:document>`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  return doc.getElementsByTagName('w:drawing')[0];
}

const BLIP_BLOCK = `
  <a:graphic>
    <a:graphicData>
      <pic:pic>
        <pic:blipFill>
          <a:blip r:embed="rId99"/>
        </pic:blipFill>
      </pic:pic>
    </a:graphicData>
  </a:graphic>
`;

describe('DrawingParser — wp:inline', () => {
  it('解析 rId / width / height（EMU → pt）', () => {
    // 914400 EMU = 1 inch = 72 pt
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <wp:docPr id="1" name="Pic 1" descr="封面圖"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('inlineImage');
    expect(node.rId).toBe('rId99');
    expect(node.width).toBeCloseTo(72, 1);
    expect(node.height).toBeCloseTo(36, 1);
    if (node.type === 'inlineImage') expect(node.altText).toBe('封面圖');
  });

  it('沒有 blip rId 時 rId 回空字串', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.rId).toBe('');
  });
});

describe('DrawingParser — wp:anchor', () => {
  it('完整 posH / posV / wrap', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:anchor behindDoc="0" allowOverlap="1">
          <wp:positionH relativeFrom="margin">
            <wp:posOffset>914400</wp:posOffset>
          </wp:positionH>
          <wp:positionV relativeFrom="paragraph">
            <wp:align>top</wp:align>
          </wp:positionV>
          <wp:extent cx="2743200" cy="1828800"/>
          <wp:wrapSquare wrapText="bothSides"/>
          <wp:docPr id="2" name="Float Pic"/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('floatImage');
    if (node.type !== 'floatImage') return;
    expect(node.rId).toBe('rId99');
    expect(node.width).toBeCloseTo(216, 1); // 2743200 EMU / 12700 = 216pt
    expect(node.height).toBeCloseTo(144, 1);
    expect(node.posH.relativeFrom).toBe('margin');
    expect(node.posH.posOffset).toBeCloseTo(72, 1);
    expect(node.posV.relativeFrom).toBe('paragraph');
    expect(node.posV.align).toBe('top');
    expect(node.wrapType).toBe('square');
    expect(node.allowOverlap).toBe(true);
  });

  const wrapMap = [
    { tag: 'wp:wrapNone', expected: 'none' },
    { tag: 'wp:wrapSquare', expected: 'square' },
    { tag: 'wp:wrapTight', expected: 'tight' },
    { tag: 'wp:wrapThrough', expected: 'through' },
    { tag: 'wp:wrapTopAndBottom', expected: 'topAndBottom' },
  ];

  it.each(wrapMap)('wrap type 偵測 — %s', ({ tag, expected }) => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:anchor>
          <wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:extent cx="100" cy="100"/>
          <${tag}/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'floatImage') throw new Error('expected floatImage');
    expect(node.wrapType).toBe(expected);
  });

  it('沒指定 wrap 時預設 square', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:anchor>
          <wp:positionH relativeFrom="margin"/>
          <wp:positionV relativeFrom="paragraph"/>
          <wp:extent cx="100" cy="100"/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'floatImage') throw new Error('expected floatImage');
    expect(node.wrapType).toBe('square');
  });

  it('behindDoc=1 設 behindDoc=true', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:anchor behindDoc="1">
          <wp:positionH relativeFrom="margin"/>
          <wp:positionV relativeFrom="paragraph"/>
          <wp:extent cx="100" cy="100"/>
          <wp:wrapNone/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type !== 'floatImage') throw new Error('expected floatImage');
    expect(node.behindDoc).toBe(true);
  });
});

describe('DrawingParser — fallback', () => {
  it('既無 inline 又無 anchor 回 fallback inline image（rId=空）', () => {
    const drawing = parseFragment('<w:drawing/>');
    const node = parser.parse(drawing);
    expect(node.type).toBe('inlineImage');
    expect(node.rId).toBe('');
    expect(node.width).toBe(0);
    expect(node.height).toBe(0);
  });
});

describe('DrawingParser — Sprint 38 wp:anchor + wps:txbx → FloatTextBoxNode', () => {
  const TXBX_NS = [
    NS,
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"',
  ].join(' ');

  function parseFragmentTxbx(inner: string): Element {
    const xml = `<?xml version="1.0"?><w:document ${TXBX_NS}><w:body><w:p><w:r>${inner}</w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.getElementsByTagName('w:drawing')[0];
  }

  it('偵測 anchor 內 wps:txbx 為 text box 路徑（type=floatTextBox）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wp:wsp><wps:wsp><wps:txbx><w:txbxContent><w:p><w:r><w:t>112.12.29</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp></wp:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph',
      props: {},
      runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    expect(node.type).toBe('floatTextBox');
    if (node.type !== 'floatTextBox') throw new Error('unreachable');
    expect(node.width).toBeCloseTo(72, 4); // 914400 EMU = 72 pt
    expect(node.height).toBeCloseTo(22.5, 1); // 285750 EMU ≈ 22.5 pt
    expect(node.wrapType).toBe('none');
  });

  it('解析 txbxContent 內 paragraph（呼叫 paragraphFactory callback）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <w:txbxContent><w:p><w:r><w:t>HELLO</w:t></w:r></w:p></w:txbxContent>
        </wp:anchor>
      </w:drawing>
    `);
    let factoryCalls = 0;
    const node = parser.parse(drawing, (p) => {
      factoryCalls++;
      return {
        type: 'paragraph',
        props: {},
        runs: [{ type: 'run', text: p.textContent || '', props: {} }],
      };
    });
    expect(factoryCalls).toBe(1);
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.paragraphs.length).toBe(1);
    expect(node.paragraphs[0].runs[0]).toMatchObject({ type: 'run', text: 'HELLO' });
  });

  it('無 paragraphFactory：paragraphs 為空陣列（不 crash）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing); // 沒傳 factory
    expect(node.type).toBe('floatTextBox');
    if (node.type !== 'floatTextBox') throw new Error('unreachable');
    expect(node.paragraphs.length).toBe(0);
  });

  it('anchor 內無 wps:txbx 仍走原 image 路徑（type=floatImage）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="914400"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          ${BLIP_BLOCK}
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('floatImage');
    if (node.type !== 'floatImage') throw new Error('unreachable');
    expect(node.rId).toBe('rId99');
  });

  it('posH / posV / behindDoc 同樣 propagate 到 FloatTextBoxNode', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor behindDoc="1">
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="margin"><wp:posOffset>457200</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="line"><wp:posOffset>228600</wp:posOffset></wp:positionV>
          <wp:wrapSquare/>
          <w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.posH.relativeFrom).toBe('margin');
    expect(node.posH.posOffset).toBeCloseTo(36, 4); // 457200 EMU = 36 pt
    expect(node.posV.relativeFrom).toBe('line');
    expect(node.posV.posOffset).toBeCloseTo(18, 4); // 228600 EMU = 18 pt
    expect(node.wrapType).toBe('square');
    expect(node.behindDoc).toBe(true);
  });
});

describe('DrawingParser — Sprint 39 wps:bodyPr / wps:spPr 解析', () => {
  const TXBX_NS = [
    NS,
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"',
  ].join(' ');

  function parseFragmentTxbx(inner: string): Element {
    const xml = `<?xml version="1.0"?><w:document ${TXBX_NS}><w:body><w:p><w:r>${inner}</w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    return doc.getElementsByTagName('w:drawing')[0];
  }

  it('解析 wps:bodyPr lIns/tIns/rIns/bIns 為 padding（EMU → Pt）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
            <wps:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.bodyPr).toBeDefined();
    expect(node.bodyPr!.leftInset).toBeCloseTo(7.2, 2);
    expect(node.bodyPr!.topInset).toBeCloseTo(3.6, 2);
    expect(node.bodyPr!.rightInset).toBeCloseTo(7.2, 2);
    expect(node.bodyPr!.bottomInset).toBeCloseTo(3.6, 2);
  });

  it('bodyPr 缺漏屬性套 OOXML 預設值（L/R=7.2pt、T/B=3.6pt）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
            <wps:bodyPr/>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.bodyPr!.leftInset).toBeCloseTo(7.2, 2);
    expect(node.bodyPr!.topInset).toBeCloseTo(3.6, 2);
  });

  it('解析 wps:spPr 內 a:solidFill / a:srgbClr 為背景色', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:spPr><a:solidFill><a:srgbClr val="FFFF00"/></a:solidFill></wps:spPr>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.fill).toBe('FFFF00');
  });

  it('wps:spPr 內 a:noFill 視為無背景色', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:spPr><a:noFill/></wps:spPr>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.fill).toBeUndefined();
  });

  it('解析 wps:spPr 內 a:ln w + solidFill 為邊框', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:spPr><a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln></wps:spPr>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.border).toBeDefined();
    expect(node.border!.color).toBe('000000');
    expect(node.border!.width).toBeCloseTo(1, 4); // 12700 EMU = 1 pt
  });

  it('Sprint 40 — wp:inline 內 a:srcRect 解析為 ImageSrcRect（OOXML 千分比 → 0–1 分數）', () => {
    // 不能用 parseFragmentTxbx 因為 xmlns:a 重複，用 NS-only
    const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>
      <w:drawing>
        <wp:inline>
          <wp:extent cx="3600000" cy="2700000"/>
          ${BLIP_BLOCK}
          <a:srcRect t="4066" b="4066"/>
        </wp:inline>
      </w:drawing>
    </w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const drawing = doc.getElementsByTagName('w:drawing')[0];
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.srcRect).toBeDefined();
    expect(node.srcRect!.topPct).toBeCloseTo(0.04066, 5);
    expect(node.srcRect!.bottomPct).toBeCloseTo(0.04066, 5);
    expect(node.srcRect!.leftPct).toBe(0);
    expect(node.srcRect!.rightPct).toBe(0);
  });

  it('Sprint 40 — 缺漏 a:srcRect → srcRect undefined（與 06 fixture 一致）', () => {
    const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>
      <w:drawing>
        <wp:inline>
          <wp:extent cx="3600000" cy="2700000"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    </w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const drawing = doc.getElementsByTagName('w:drawing')[0];
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.srcRect).toBeUndefined();
  });

  it('Sprint 40 — 空 a:srcRect / 全零 → srcRect undefined（與 6.環清表 fixture 一致）', () => {
    const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>
      <w:drawing>
        <wp:inline>
          <wp:extent cx="3600000" cy="2700000"/>
          ${BLIP_BLOCK}
          <a:srcRect/>
        </wp:inline>
      </w:drawing>
    </w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const drawing = doc.getElementsByTagName('w:drawing')[0];
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.srcRect).toBeUndefined();
  });

  it('Sprint 40 — srcRect 整張裁光（l+r >= 1）→ 視為不裁切（fallback 安全）', () => {
    const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>
      <w:drawing>
        <wp:inline>
          <wp:extent cx="3600000" cy="2700000"/>
          ${BLIP_BLOCK}
          <a:srcRect l="60000" r="50000"/>
        </wp:inline>
      </w:drawing>
    </w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const drawing = doc.getElementsByTagName('w:drawing')[0];
    const node = parser.parse(drawing);
    if (node.type !== 'inlineImage') throw new Error('expected inlineImage');
    expect(node.srcRect).toBeUndefined();
  });

  it('Sprint 40 — wp:anchor 內 a:srcRect 也解析（FloatImageNode）', () => {
    const xml = `<?xml version="1.0"?><w:document ${NS}><w:body><w:p><w:r>
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="3600000" cy="2700000"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          ${BLIP_BLOCK}
          <a:srcRect l="5000" t="10000" r="5000" b="10000"/>
        </wp:anchor>
      </w:drawing>
    </w:r></w:p></w:body></w:document>`;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const drawing = doc.getElementsByTagName('w:drawing')[0];
    const node = parser.parse(drawing);
    if (node.type !== 'floatImage') throw new Error('expected floatImage');
    expect(node.srcRect).toBeDefined();
    expect(node.srcRect!.leftPct).toBeCloseTo(0.05, 4);
    expect(node.srcRect!.topPct).toBeCloseTo(0.10, 4);
  });

  it('a:ln 內 a:noFill 視為無邊框（與 03 fixture 一致）', () => {
    const drawing = parseFragmentTxbx(`
      <w:drawing>
        <wp:anchor>
          <wp:extent cx="914400" cy="285750"/>
          <wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>
          <wp:wrapNone/>
          <wps:wsp>
            <wps:spPr><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>
            <wps:txbx><w:txbxContent><w:p><w:r><w:t>X</w:t></w:r></w:p></w:txbxContent></wps:txbx>
          </wps:wsp>
        </wp:anchor>
      </w:drawing>
    `);
    const node = parser.parse(drawing, (p) => ({
      type: 'paragraph', props: {}, runs: [{ type: 'run', text: p.textContent || '', props: {} }],
    }));
    if (node.type !== 'floatTextBox') throw new Error('expected floatTextBox');
    expect(node.fill).toBeUndefined();
    expect(node.border).toBeUndefined();
  });
});

describe('DrawingParser — Sprint 183 SmartArt / Chart graphic frame', () => {
  const DGM_NS = 'xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"';
  const C_NS = 'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"';

  it('SmartArt graphic frame → graphic.kind=diagram + r:dm relId', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <a:graphic>
            <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">
              <dgm:relIds ${DGM_NS} r:dm="rId7" r:lo="rId8" r:qs="rId9" r:cs="rId10"/>
            </a:graphicData>
          </a:graphic>
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('inlineImage');
    if (node.type === 'inlineImage') {
      expect(node.graphic).toEqual({ kind: 'diagram', relId: 'rId7' });
    }
  });

  it('Chart graphic frame → graphic.kind=chart + r:id relId', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <a:graphic>
            <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">
              <c:chart ${C_NS} r:id="rId5"/>
            </a:graphicData>
          </a:graphic>
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    expect(node.type).toBe('inlineImage');
    if (node.type === 'inlineImage') {
      expect(node.graphic).toEqual({ kind: 'chart', relId: 'rId5' });
    }
  });

  it('一般圖片（pic blip）→ 不掛 graphic key（紀律 #21）', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          ${BLIP_BLOCK}
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type === 'inlineImage') {
      expect('graphic' in node).toBe(false);
    }
  });

  it('未知 graphicData uri → 不掛 graphic key', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <a:graphic><a:graphicData uri="urn:unknown:thing"/></a:graphic>
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type === 'inlineImage') {
      expect('graphic' in node).toBe(false);
    }
  });

  it('diagram graphicData 但缺 r:dm → 不掛 graphic key', () => {
    const drawing = parseFragment(`
      <w:drawing>
        <wp:inline>
          <wp:extent cx="914400" cy="457200"/>
          <a:graphic>
            <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">
              <dgm:relIds ${DGM_NS}/>
            </a:graphicData>
          </a:graphic>
        </wp:inline>
      </w:drawing>
    `);
    const node = parser.parse(drawing);
    if (node.type === 'inlineImage') {
      expect('graphic' in node).toBe(false);
    }
  });
});
