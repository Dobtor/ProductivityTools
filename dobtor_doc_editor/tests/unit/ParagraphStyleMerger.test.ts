/**
 * Sprint 19 — ParagraphStyleMerger
 */

import { describe, expect, it } from 'vitest';
import {
  mergeParagraphStyles,
  mergePProps,
} from '../../static/src/core/ooxml/styles/ParagraphStyleMerger';
import type {
  DocumentNode,
  ParagraphNode,
  StyleEntry,
  StyleMap,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

function makeDoc(sections: any[]): DocumentNode {
  return {
    type: 'document',
    sections,
    headers: new Map(),
    footers: new Map(),
    footnotes: new Map(),
    endnotes: new Map(),
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
  };
}

function makeSection(body: any[]): any {
  return {
    type: 'section',
    page: { width: 595, height: 842, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

function makePara(opts: { styleId?: string; props?: any; text?: string } = {}): ParagraphNode {
  const p: ParagraphNode = {
    type: 'paragraph',
    props: opts.props ?? {},
    runs: [{ type: 'run', text: opts.text ?? 'x', props: { fontSize: 10 } }],
  };
  if (opts.styleId) p.styleId = opts.styleId;
  return p;
}

describe('mergePProps（純函式）', () => {
  it('override 覆寫 base 的 scalar key', () => {
    const out = mergePProps({ keepNext: false }, { keepNext: true });
    expect(out.keepNext).toBe(true);
  });

  it('未覆寫 key 會保留 base', () => {
    const out = mergePProps({ keepNext: true, keepLines: true }, { alignment: 'center' });
    expect(out.keepNext).toBe(true);
    expect(out.keepLines).toBe(true);
    expect(out.alignment).toBe('center');
  });

  it('巢狀物件做淺合併（spacing per-key 覆寫）', () => {
    const out = mergePProps(
      { spacing: { before: 10, after: 20, lineRule: 'auto' } },
      { spacing: { before: 5 } },
    );
    expect(out.spacing).toEqual({ before: 5, after: 20, lineRule: 'auto' });
  });

  it('override 為 undefined 不影響 base', () => {
    const out = mergePProps({ keepNext: true }, { keepNext: undefined as any });
    expect(out.keepNext).toBe(true);
  });
});

describe('mergeParagraphStyles（document 級走訪）', () => {
  it('空 styles map：不動任何段落', () => {
    const doc = makeDoc([makeSection([makePara({ styleId: 'X' })])]);
    expect(mergeParagraphStyles(doc)).toBe(0);
    expect(doc.sections[0].body[0].props.keepNext).toBeUndefined();
  });

  it('段落有 styleId + style 含 keepNext：props 接收 keepNext=true', () => {
    const styles: StyleMap = new Map([
      ['Heading1', { pProps: { keepNext: true, alignment: 'center' } } as StyleEntry],
    ]);
    const para = makePara({ styleId: 'Heading1' });
    const doc = makeDoc([makeSection([para])]);
    doc.styles = styles;

    const count = mergeParagraphStyles(doc);
    expect(count).toBe(1);
    expect(para.props.keepNext).toBe(true);
    expect(para.props.alignment).toBe('center');
  });

  it('inline props 覆寫 style props', () => {
    const styles: StyleMap = new Map([
      ['Heading1', { pProps: { alignment: 'center', keepNext: true } } as StyleEntry],
    ]);
    const para = makePara({ styleId: 'Heading1', props: { alignment: 'right' } });
    const doc = makeDoc([makeSection([para])]);
    doc.styles = styles;

    mergeParagraphStyles(doc);
    expect(para.props.alignment).toBe('right'); // inline 贏
    expect(para.props.keepNext).toBe(true); // style 補上
  });

  it('沒有 styleId 的段落：不動', () => {
    const styles: StyleMap = new Map([
      ['X', { pProps: { keepNext: true } } as StyleEntry],
    ]);
    const para = makePara();
    const doc = makeDoc([makeSection([para])]);
    doc.styles = styles;

    expect(mergeParagraphStyles(doc)).toBe(0);
    expect(para.props.keepNext).toBeUndefined();
  });

  it('styleId 對應不存在的 style：不動', () => {
    const styles: StyleMap = new Map([
      ['Real', { pProps: { keepNext: true } } as StyleEntry],
    ]);
    const para = makePara({ styleId: 'NonExistent' });
    const doc = makeDoc([makeSection([para])]);
    doc.styles = styles;

    expect(mergeParagraphStyles(doc)).toBe(0);
    expect(para.props.keepNext).toBeUndefined();
  });

  it('遞迴入 table cell 內段落', () => {
    const styles: StyleMap = new Map([
      ['CellPara', { pProps: { keepNext: true } } as StyleEntry],
    ]);
    const innerPara = makePara({ styleId: 'CellPara' });
    const table: TableNode = {
      type: 'table',
      grid: [100],
      rows: [{
        type: 'row',
        cells: [{
          type: 'cell',
          gridCol: 0,
          gridSpan: 1,
          rowSpan: 1,
          isContinuation: false,
          content: [innerPara],
          props: {},
        }],
        props: { isHeader: false, cantSplit: false },
      }],
      props: {},
    };
    const doc = makeDoc([makeSection([table])]);
    doc.styles = styles;

    expect(mergeParagraphStyles(doc)).toBe(1);
    expect(innerPara.props.keepNext).toBe(true);
  });

  it('多 section + 多 cell 走訪數量正確', () => {
    const styles: StyleMap = new Map([
      ['S1', { pProps: { keepNext: true } } as StyleEntry],
    ]);
    const sec1 = makeSection([
      makePara({ styleId: 'S1' }),
      makePara({ styleId: 'S1' }),
      makePara({ styleId: 'NoSuchStyle' }), // 不算
    ]);
    const sec2 = makeSection([
      {
        type: 'table',
        grid: [100],
        rows: [{
          type: 'row',
          cells: [{
            type: 'cell',
            gridCol: 0,
            gridSpan: 1,
            rowSpan: 1,
            isContinuation: false,
            content: [makePara({ styleId: 'S1' })],
            props: {},
          }],
          props: { isHeader: false, cantSplit: false },
        }],
        props: {},
      },
    ]);
    const doc = makeDoc([sec1, sec2]);
    doc.styles = styles;

    expect(mergeParagraphStyles(doc)).toBe(3);
  });
});
