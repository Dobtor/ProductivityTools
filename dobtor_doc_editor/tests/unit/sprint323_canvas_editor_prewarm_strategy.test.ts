/**
 * Sprint 323 — ① deeper⁶：CanvasEditorPrewarmStrategy。
 *
 * Sprint 303/318 之後深推。Heuristic 選 prewarm 子集（top N / whitelist / charset）。
 *
 * 紀律 #18 scope-down：caller 顯式選擇 strategy；不做自動 ML。
 */
import { describe, expect, it } from 'vitest';

import {
  collectPrewarmCandidates,
  classifyCharset,
  byTopFrequency,
  byFontFamilyWhitelist,
  byCharsetClassification,
  type PrewarmEntryWithMeta,
} from '../../static/src/core/ooxml/font/CanvasEditorPrewarmStrategy';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
} from '../../static/src/core/ooxml/ast/types';

function mkRun(text: string, family?: string, fontSize?: number): RunNode {
  const props: { fontFamily?: string; fontSize?: number } = {};
  if (family !== undefined) props.fontFamily = family;
  if (fontSize !== undefined) props.fontSize = fontSize;
  return { type: 'run', text, props };
}

function mkParagraph(runs: RunNode[]): ParagraphNode {
  return { type: 'paragraph', props: {}, runs };
}

function mkSection(blocks: Array<ParagraphNode | TableNode>): SectionNode {
  return {
    type: 'section',
    page: { width: 595, height: 842, orientation: 'portrait' },
    margins: { top: 72, bottom: 72, left: 72, right: 72, header: 36, footer: 36 },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body: blocks,
  };
}

function mkDoc(blocks: Array<ParagraphNode | TableNode>): DocumentNode {
  return {
    type: 'document',
    sections: [mkSection(blocks)],
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
  } as DocumentNode;
}

// ── classifyCharset ──────────────────────────────────────────────────

describe('Sprint 323 — classifyCharset', () => {
  it('純 CJK → cjk', () => {
    expect(classifyCharset('中文文字')).toBe('cjk');
  });

  it('純 Latin → latin', () => {
    expect(classifyCharset('Hello World')).toBe('latin');
  });

  it('混合 CJK+Latin → mixed', () => {
    expect(classifyCharset('中文 + English')).toBe('mixed');
  });

  it('空字串 → empty', () => {
    expect(classifyCharset('')).toBe('empty');
  });

  it('非 ASCII 非 CJK → mixed', () => {
    expect(classifyCharset('שלום')).toBe('mixed'); // Hebrew
  });
});

// ── collectPrewarmCandidates ────────────────────────────────────────

describe('Sprint 323 — collectPrewarmCandidates', () => {
  it('累積 frequency', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('hi', 'F', 12), mkRun('hi', 'F', 12)]),
      mkParagraph([mkRun('hi', 'F', 12)]),
    ]);
    const out = collectPrewarmCandidates(doc, 'F', 12);
    expect(out).toHaveLength(1);
    expect(out[0].frequency).toBe(3);
  });

  it('不同 family/size 各自 bucket', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('x', 'F1', 12), mkRun('x', 'F2', 12), mkRun('x', 'F1', 14)]),
    ]);
    const out = collectPrewarmCandidates(doc, 'F1', 12);
    expect(out).toHaveLength(3);
  });

  it('未指定 family/size → default fallback', () => {
    const doc = mkDoc([mkParagraph([mkRun('NoFont')])]);
    const out = collectPrewarmCandidates(doc, 'DefFont', 14);
    expect(out[0].family).toBe('DefFont');
    expect(out[0].sizePt).toBe(14);
  });

  it('charset 推測進 meta', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('中文', 'F', 12), mkRun('Hello', 'F', 12), mkRun('混 mix', 'F', 12)]),
    ]);
    const out = collectPrewarmCandidates(doc, 'F', 12);
    const m = new Map(out.map((c) => [c.text, c.charset]));
    expect(m.get('中文')).toBe('cjk');
    expect(m.get('Hello')).toBe('latin');
    expect(m.get('混 mix')).toBe('mixed');
  });
});

// ── byTopFrequency ────────────────────────────────────────────────

describe('Sprint 323 — byTopFrequency', () => {
  const candidates: PrewarmEntryWithMeta[] = [
    { text: 'a', family: 'F', sizePt: 12, frequency: 1, charset: 'latin' },
    { text: 'b', family: 'F', sizePt: 12, frequency: 5, charset: 'latin' },
    { text: 'c', family: 'F', sizePt: 12, frequency: 3, charset: 'latin' },
  ];

  it('降序排序、取 top n', () => {
    const out = byTopFrequency(candidates, 2);
    expect(out.map((c) => c.text)).toEqual(['b', 'c']);
  });

  it('n undefined → 全部回（降序）', () => {
    const out = byTopFrequency(candidates);
    expect(out.map((c) => c.text)).toEqual(['b', 'c', 'a']);
  });

  it('n <= 0 → 空', () => {
    expect(byTopFrequency(candidates, 0)).toEqual([]);
    expect(byTopFrequency(candidates, -1)).toEqual([]);
  });
});

// ── byFontFamilyWhitelist ──────────────────────────────────────────

describe('Sprint 323 — byFontFamilyWhitelist', () => {
  const candidates: PrewarmEntryWithMeta[] = [
    { text: 'a', family: 'F1', sizePt: 12, frequency: 1 },
    { text: 'b', family: 'F2', sizePt: 12, frequency: 1 },
    { text: 'c', family: 'F3', sizePt: 12, frequency: 1 },
  ];

  it('過濾 family 在 whitelist 內', () => {
    const out = byFontFamilyWhitelist(candidates, ['F1', 'F3']);
    expect(out.map((c) => c.family).sort()).toEqual(['F1', 'F3']);
  });

  it('空 whitelist → 空', () => {
    expect(byFontFamilyWhitelist(candidates, [])).toEqual([]);
  });
});

// ── byCharsetClassification ──────────────────────────────────────

describe('Sprint 323 — byCharsetClassification', () => {
  const candidates: PrewarmEntryWithMeta[] = [
    { text: '中', family: 'F', sizePt: 12, frequency: 1, charset: 'cjk' },
    { text: 'A', family: 'F', sizePt: 12, frequency: 1, charset: 'latin' },
    { text: '混 m', family: 'F', sizePt: 12, frequency: 1, charset: 'mixed' },
  ];

  it('過濾 charset 在指定集內', () => {
    expect(byCharsetClassification(candidates, ['cjk']).map((c) => c.charset)).toEqual(['cjk']);
    expect(byCharsetClassification(candidates, ['latin', 'mixed']).map((c) => c.charset).sort())
      .toEqual(['latin', 'mixed']);
  });

  it('空 charsets → 空', () => {
    expect(byCharsetClassification(candidates, [])).toEqual([]);
  });
});
