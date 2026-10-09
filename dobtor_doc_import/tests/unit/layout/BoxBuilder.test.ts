/**
 * BoxBuilder — ParagraphNode → ParagraphInput 測試
 */

import { describe, expect, it } from 'vitest';
import { buildParagraph } from '../../../static/src/core/layout/BoxBuilder';
import type { Box, Glue, LayoutItem } from '../../../static/src/core/layout/types';
import type {
  ParagraphNode,
  RunNode,
  InlineImageNode,
  BreakNode,
} from '../../../static/src/core/ooxml/ast/types';

function makePara(runs: ParagraphNode['runs']): ParagraphNode {
  return { type: 'paragraph', props: {}, runs };
}

function run(text: string, fontSize = 12): RunNode {
  return { type: 'run', text, props: { fontSize } };
}

function image(rId: string, w = 100, h = 80): InlineImageNode {
  return { type: 'inlineImage', rId, width: w, height: h };
}

function lineBreak(): BreakNode {
  return { type: 'break', breakType: 'line' };
}

function pageBreak(): BreakNode {
  return { type: 'break', breakType: 'page' };
}

describe('BoxBuilder — 純 CJK', () => {
  it('每字一個 Box，字間穿插 zero-width glue', () => {
    const para = makePara([run('中文')]);
    const out = buildParagraph(para, 0);
    // items = [Box(中), Glue(zero-cjk), Box(文), Glue(zero-cjk)]
    expect(out.items.length).toBe(4);
    expect(out.items[0].kind).toBe('box');
    expect(out.items[1].kind).toBe('glue');
    expect((out.items[1] as Glue).isCjkBreak).toBe(true);
    expect((out.items[1] as Glue).width).toBe(0);
    expect((out.items[0] as Box).text).toBe('中');
    expect((out.items[2] as Box).text).toBe('文');
  });
});

describe('BoxBuilder — 純 Latin', () => {
  it('用空白切 token，每 token 一個 Box，中間 Glue', () => {
    const para = makePara([run('hello world')]);
    const out = buildParagraph(para, 0);
    // items = [Box(hello), Glue(space), Box(world)]
    expect(out.items.length).toBe(3);
    expect((out.items[0] as Box).text).toBe('hello');
    expect((out.items[1] as Glue).width).toBeGreaterThan(0); // 真實 space
    expect((out.items[2] as Box).text).toBe('world');
  });

  it('連續字母不拆，數字也不拆', () => {
    const para = makePara([run('abc 123def')]);
    const out = buildParagraph(para, 0);
    // [Box(abc), Glue, Box(123def)]
    expect(out.items.length).toBe(3);
    expect((out.items[2] as Box).text).toBe('123def');
  });
});

describe('BoxBuilder — Latin + CJK 混排', () => {
  it('Hello 中文 World：正確切換 token 與 CJK 字符', () => {
    const para = makePara([run('Hello 中文 World')]);
    const out = buildParagraph(para, 0);
    const texts = out.items
      .filter((i) => i.kind === 'box')
      .map((b) => (b as Box).text);
    expect(texts).toEqual(['Hello', '中', '文', 'World']);
  });
});

describe('BoxBuilder — InlineImage', () => {
  it('inlineImage 變成 isImage Box', () => {
    const para = makePara([image('rId5', 50, 30)]);
    const out = buildParagraph(para, 0);
    expect(out.items.length).toBe(1);
    const box = out.items[0] as Box;
    expect(box.kind).toBe('box');
    expect(box.isImage).toBe(true);
    expect(box.imageRId).toBe('rId5');
    expect(box.width).toBe(50);
    expect(box.height).toBe(30);
  });
});

describe('BoxBuilder — Break', () => {
  it('line break → cost=-Infinity penalty', () => {
    const para = makePara([run('a'), lineBreak(), run('b')]);
    const out = buildParagraph(para, 0);
    const penalty = out.items.find((i) => i.kind === 'penalty');
    expect(penalty).toBeDefined();
    expect((penalty as { cost: number }).cost).toBe(-Infinity);
  });

  it('page break → flagged penalty', () => {
    const para = makePara([run('a'), pageBreak()]);
    const out = buildParagraph(para, 0);
    const penalty = out.items.find((i) => i.kind === 'penalty');
    expect(penalty).toBeDefined();
    expect((penalty as { cost: number; flagged?: boolean }).flagged).toBe(true);
  });
});

describe('BoxBuilder — 空段落', () => {
  it('runs 為空 → items 為空', () => {
    const para = makePara([]);
    const out = buildParagraph(para, 0);
    expect(out.items.length).toBe(0);
  });
});

describe('BoxBuilder — sourceIndex / styleId 帶通', () => {
  it('傳遞 sourceIndex 與 styleId', () => {
    const para: ParagraphNode = {
      type: 'paragraph',
      props: {},
      runs: [run('x')],
      styleId: 'Heading1',
    };
    const out = buildParagraph(para, 17);
    expect(out.sourceIndex).toBe(17);
    expect(out.styleId).toBe('Heading1');
  });
});

// ── Sprint 139：numberingPrefix 前綴 emission ───────────────────────────────

describe('BoxBuilder — Sprint 139 numberingPrefix', () => {
  it('未傳 prefix：回歸 Sprint 138 之前行為（無前綴）', () => {
    const para = makePara([run('hello')]);
    const out = buildParagraph(para, 0); // 4th arg undefined
    // 西文：[Box(hello)]
    expect(out.items.length).toBe(1);
    expect((out.items[0] as Box).text).toBe('hello');
  });

  it('傳 prefix「1.」：emit「1.」Box + tab Glue + 原文字', () => {
    const para = makePara([run('hello')]);
    const out = buildParagraph(para, 0, undefined, {
      text: '1.',
      runProps: { fontSize: 12 },
    });
    // items: [Box('1.'), Glue(tab), Box('hello')]
    expect(out.items.length).toBe(3);
    expect((out.items[0] as Box).text).toBe('1.');
    expect((out.items[1] as Glue).width).toBeGreaterThan(0);
    expect((out.items[2] as Box).text).toBe('hello');
  });

  it('CJK prefix「第一章」：每字一個 Box + 字間 cjk glue + tab + 後續', () => {
    const para = makePara([run('緒論')]);
    const out = buildParagraph(para, 0, undefined, {
      text: '第一章',
      runProps: { fontSize: 14 },
    });
    // CJK prefix: [Box(第), cjkGlue, Box(一), cjkGlue, Box(章), cjkGlue]
    // tab glue: [Glue(tab)]
    // CJK body: [Box(緒), cjkGlue, Box(論), cjkGlue]
    expect(out.items.length).toBe(11);
    expect((out.items[0] as Box).text).toBe('第');
    expect((out.items[2] as Box).text).toBe('一');
    expect((out.items[4] as Box).text).toBe('章');
    // 第 6 個是 tab glue（width > 0）
    expect((out.items[6] as Glue).width).toBeGreaterThan(0);
    expect((out.items[7] as Box).text).toBe('緒');
  });

  it('空 prefix text：跳過 emit（避免 placeholder 污染）', () => {
    const para = makePara([run('hello')]);
    const out = buildParagraph(para, 0, undefined, {
      text: '',
      runProps: { fontSize: 12 },
    });
    expect(out.items.length).toBe(1);
    expect((out.items[0] as Box).text).toBe('hello');
  });

  it('prefix 套用獨立 fontSize：與第一個 run fontSize 可不同', () => {
    const para = makePara([run('body', 14)]);
    const out = buildParagraph(para, 0, undefined, {
      text: '1.',
      runProps: { fontSize: 18 }, // prefix 18pt、body 14pt
    });
    // Box(1.) 應該套 18pt
    expect((out.items[0] as Box).runProps.fontSize).toBe(18);
    // Box(body) 應該套 14pt
    expect((out.items[2] as Box).runProps.fontSize).toBe(14);
  });
});

describe('BoxBuilder — Sprint 163 欄位 fieldType 型別對齊', () => {
  it('PAGE 欄位無 cachedValue → placeholder "##" + Box.fieldType=PAGE', () => {
    const para = makePara([{ type: 'field', instruction: ' PAGE ', fieldType: 'PAGE' }]);
    const out = buildParagraph(para, 0);
    const box = out.items[0] as Box;
    expect(box.text).toBe('##');
    expect(box.fieldType).toBe('PAGE');
  });

  it('PAGE 欄位有 cachedValue → 用 cachedValue', () => {
    const para = makePara([
      { type: 'field', instruction: ' PAGE ', fieldType: 'PAGE', cachedValue: '7' },
    ]);
    const out = buildParagraph(para, 0);
    expect((out.items[0] as Box).text).toBe('7');
  });

  it('Sprint 123 擴充的 5 型（SEQ/TOC/REF/HYPERLINK/STYLEREF）走 default placeholder', () => {
    for (const ft of ['SEQ', 'TOC', 'REF', 'HYPERLINK', 'STYLEREF'] as const) {
      const para = makePara([{ type: 'field', instruction: ` ${ft} `, fieldType: ft }]);
      const out = buildParagraph(para, 0);
      const box = out.items[0] as Box;
      expect(box.text).toBe(`{${ft}}`);
      expect(box.fieldType).toBe(ft);
    }
  });
});
