/**
 * Sprint Y58 — FloatTextBox + AnchorMetadata 透傳測試
 *
 * 規格（從 Sprint Y57 真實 gap 驗證落定的決策）：
 *   1. parser 早就把 wp:anchor + w:txbxContent 抽成 FloatTextBoxNode（Sprint 38），
 *      但 mapper Phase D.1 直接 drop → 25/25 ChienYi 監造文件文字遺失。
 *   2. Sprint Y58 mapper 加 case，並以兩個 options flag 控制（預設 false、VR byte-identical）：
 *        - renderFloatTextBox       展平 textbox paragraphs 到 IElement stream
 *        - preserveAnchorMetadata   把 wp:anchor 屬性透傳成 IElement.anchor
 *   3. 對 FloatImageNode 同樣 anchor 透傳（既有降級 inline 行為不變）。
 *
 * 本檔測試矩陣：
 *   A. 預設 options    → textbox drop（與 Sprint 38 以來行為 byte-identical）
 *   B. renderFloatTextBox=true → textbox 文字展平到 IElement
 *   C. preserveAnchorMetadata=true（FloatTextBox） → 第一個 IElement 帶 anchor 透傳
 *   D. preserveAnchorMetadata=true（FloatImage）   → image IElement 帶 anchor 透傳
 *   E. 空 textbox（無 paragraphs）→ 即使 flag=true 也 emit 0 個 element
 *   F. 兩 flag 都開 + 多 paragraph textbox → 每個 paragraph 有段尾 \n、anchor 只掛第一個
 */

import { describe, expect, it } from 'vitest';
import { ToCanvasEditor } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';
import type { CEElement } from '../../static/src/core/ooxml/mapper/ToCanvasEditor';
import type {
  AnchorMetadata,
  DocumentNode,
  FloatImageNode,
  FloatTextBoxNode,
  ParagraphNode,
  RunNode,
  SectionNode,
} from '../../static/src/core/ooxml/ast/types';

// ── fixture helpers ─────────────────────────────────────────────────────────

function makeRun(text: string): RunNode {
  return { type: 'run', text, props: {} };
}

function makeParagraph(runs: ParagraphNode['runs']): ParagraphNode {
  return { type: 'paragraph', runs, props: {} };
}

function makeSection(body: SectionNode['body']): SectionNode {
  return {
    type: 'section',
    page: { width: 595.3, height: 841.9, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function makeDoc(sections: SectionNode[], media = new Map<string, string>()): DocumentNode {
  return {
    type: 'document',
    sections,
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
    media,
    docProps: {},
    appProps: {},
    customProps: new Map(),
    contentTypes: { defaults: new Map(), overrides: new Map() },
    latentStyles: {},
  };
}

/** 真實 ChienYi 監造會議的 textbox 內容 = 頁碼字串 */
function makeFloatTextBox(textbox: { text?: string; paragraphs?: ParagraphNode[]; anchor?: AnchorMetadata }): FloatTextBoxNode {
  const paragraphs =
    textbox.paragraphs
      ?? (textbox.text === undefined ? [] : [makeParagraph([makeRun(textbox.text)])]);
  const node: FloatTextBoxNode = {
    type: 'floatTextBox',
    width: 100,
    height: 20,
    posH: { relativeFrom: 'page', posOffset: 50 },
    posV: { relativeFrom: 'page', posOffset: 700 },
    wrapType: 'none',
    behindDoc: false,
    allowOverlap: true,
    paragraphs,
  };
  if (textbox.anchor) node.anchor = textbox.anchor;
  return node;
}

function makeFloatImage(rId: string): FloatImageNode {
  return {
    type: 'floatImage',
    rId,
    width: 50,
    height: 50,
    posH: { relativeFrom: 'page', posOffset: 100 },
    posV: { relativeFrom: 'page', posOffset: 100 },
    wrapType: 'square',
    behindDoc: false,
    allowOverlap: true,
    anchor: { distT: 1, distB: 2, distL: 3, distR: 4, relativeHeight: 5 },
  };
}

/** 取段落內 IElement 文字（過濾段落終止符）— 等同產品端遞迴掃 value 的策略 */
function joinText(elements: CEElement[]): string {
  let out = '';
  for (const el of elements) {
    if (el.value && el.value !== '\n') out += el.value;
  }
  return out;
}

// ── A. 預設 options：textbox drop（byte-identical 保證）─────────────────────

describe('Sprint Y58 — 預設 options（VR byte-identical 保證）', () => {
  it('floatTextBox 不展平：textbox 文字不出現在 IElement', () => {
    const mapper = new ToCanvasEditor();
    const doc = makeDoc([
      makeSection([
        makeParagraph([
          makeRun('前文'),
          makeFloatTextBox({ text: '第1頁，共3頁' }),
          makeRun('後文'),
        ]),
      ]),
    ]);
    const elements = mapper.convert(doc);
    const text = joinText(elements);
    expect(text).toBe('前文後文');
    // 不存在 textbox 內字元（即使「第」字也出現在內文時要嚴格 == 'fixture 內容'）
    expect(text).not.toContain('共3頁');
  });

  it('floatImage 仍降級為 inline image（既有行為），未透傳 anchor', () => {
    const mapper = new ToCanvasEditor();
    const media = new Map<string, string>([['rId1', 'data:image/png;base64,AAA']]);
    const doc = makeDoc(
      [makeSection([makeParagraph([makeFloatImage('rId1')])])],
      media,
    );
    const elements = mapper.convert(doc);
    const imageEl = elements.find((e) => e.type === 'image');
    expect(imageEl).toBeDefined();
    expect(imageEl?.anchor).toBeUndefined();
  });
});

// ── B. renderFloatTextBox=true：textbox 展平 ────────────────────────────────

describe('Sprint Y58 — renderFloatTextBox=true', () => {
  it('單行 textbox 文字展平到 inline stream', () => {
    const mapper = new ToCanvasEditor({ renderFloatTextBox: true });
    const doc = makeDoc([
      makeSection([
        makeParagraph([
          makeRun('A'),
          makeFloatTextBox({ text: '第1頁，共3頁' }),
          makeRun('B'),
        ]),
      ]),
    ]);
    const elements = mapper.convert(doc);
    const text = joinText(elements);
    expect(text).toContain('第1頁，共3頁');
    // 順序：前文 A → textbox 內 → 後文 B（mapper 維持 InlineNode 順序）
    expect(text.indexOf('A')).toBeLessThan(text.indexOf('第'));
    expect(text.indexOf('第')).toBeLessThan(text.indexOf('B'));
  });

  it('多 paragraph textbox：每段都有段尾 \\n', () => {
    const mapper = new ToCanvasEditor({ renderFloatTextBox: true });
    const tb = makeFloatTextBox({
      paragraphs: [
        makeParagraph([makeRun('line1')]),
        makeParagraph([makeRun('line2')]),
      ],
    });
    const doc = makeDoc([makeSection([makeParagraph([tb])])]);
    const elements = mapper.convert(doc);
    const newlineCount = elements.filter((e) => e.value === '\n').length;
    // 至少 2 段 textbox \n + 外層 paragraph \n = 3
    expect(newlineCount).toBeGreaterThanOrEqual(3);
    const text = joinText(elements);
    expect(text).toContain('line1');
    expect(text).toContain('line2');
  });

  it('空 paragraphs textbox（真實 fixture anchor[3]）：開 flag 也不 emit 字元', () => {
    const mapper = new ToCanvasEditor({ renderFloatTextBox: true });
    const doc = makeDoc([
      makeSection([
        makeParagraph([
          makeRun('X'),
          makeFloatTextBox({ paragraphs: [] }),
          makeRun('Y'),
        ]),
      ]),
    ]);
    const elements = mapper.convert(doc);
    expect(joinText(elements)).toBe('XY');
  });
});

// ── C. preserveAnchorMetadata（floatTextBox）────────────────────────────────

describe('Sprint Y58 — preserveAnchorMetadata=true（FloatTextBox）', () => {
  it('開啟 flag 後 textbox 的第一個 IElement 帶 anchor.source=floatTextBox', () => {
    const meta: AnchorMetadata = { distT: 1.5, relativeHeight: 251660288 };
    const mapper = new ToCanvasEditor({
      renderFloatTextBox: true,
      preserveAnchorMetadata: true,
    });
    const doc = makeDoc([
      makeSection([
        makeParagraph([
          makeRun('pre'),
          makeFloatTextBox({ text: '第1頁，共3頁', anchor: meta }),
        ]),
      ]),
    ]);
    const elements = mapper.convert(doc);
    // 找含 '第' 的元素 → 它前面那一段（textbox 第一個 emit）應帶 anchor
    const firstAnchored = elements.find((e) => e.anchor);
    expect(firstAnchored).toBeDefined();
    expect(firstAnchored?.anchor?.source).toBe('floatTextBox');
    expect(firstAnchored?.anchor?.posH?.relativeFrom).toBe('page');
    expect(firstAnchored?.anchor?.wrapType).toBe('none');
    expect(firstAnchored?.anchor?.metadata?.distT).toBe(1.5);
    expect(firstAnchored?.anchor?.metadata?.relativeHeight).toBe(251660288);
  });

  it('renderFloatTextBox=false + preserveAnchorMetadata=true → 無 textbox 元素故無 anchor 透傳', () => {
    // 設計約定：metadata 透傳依附在 textbox emit 出來的元素上；textbox 不展平 = 無對應元素 = 無 anchor
    const mapper = new ToCanvasEditor({
      renderFloatTextBox: false,
      preserveAnchorMetadata: true,
    });
    const doc = makeDoc([
      makeSection([
        makeParagraph([makeRun('X'), makeFloatTextBox({ text: '頁碼' }), makeRun('Y')]),
      ]),
    ]);
    const elements = mapper.convert(doc);
    expect(elements.some((e) => e.anchor)).toBe(false);
  });
});

// ── D. preserveAnchorMetadata（floatImage）─────────────────────────────────

describe('Sprint Y58 — preserveAnchorMetadata=true（FloatImage）', () => {
  it('floatImage 仍降級 inline image，但 IElement 帶 anchor.source=floatImage', () => {
    const mapper = new ToCanvasEditor({ preserveAnchorMetadata: true });
    const media = new Map<string, string>([['rId1', 'data:image/png;base64,AAA']]);
    const doc = makeDoc(
      [makeSection([makeParagraph([makeFloatImage('rId1')])])],
      media,
    );
    const elements = mapper.convert(doc);
    const imageEl = elements.find((e) => e.type === 'image');
    expect(imageEl).toBeDefined();
    expect(imageEl?.anchor?.source).toBe('floatImage');
    expect(imageEl?.anchor?.metadata?.distT).toBe(1);
    expect(imageEl?.anchor?.metadata?.relativeHeight).toBe(5);
    expect(imageEl?.anchor?.wrapType).toBe('square');
  });

  it('media 找不到 rId → 用 [圖片缺失] 占位但 anchor 仍透傳', () => {
    const mapper = new ToCanvasEditor({ preserveAnchorMetadata: true });
    const doc = makeDoc([
      makeSection([makeParagraph([makeFloatImage('rId-missing')])]),
    ]);
    const elements = mapper.convert(doc);
    const placeholder = elements.find((e) => e.value === '[圖片缺失]');
    expect(placeholder).toBeDefined();
    expect(placeholder?.anchor?.source).toBe('floatImage');
  });
});
