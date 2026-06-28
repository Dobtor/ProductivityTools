/**
 * Sprint 330 — ④ deeper⁸：RevisionExporter。
 *
 * Sprint 300/305/310/315/320/325 之後深推。匯出 revision 為 JSON-safe rows 與
 * CSV string、給外部 audit tool 用。
 *
 * 紀律 #18 scope-down：純 string + object、不接 file system / Buffer。
 */
import { describe, expect, it } from 'vitest';

import {
  exportRevisionsAsJson,
  exportRevisionsAsCsv,
  escapeCsvField,
  summarizeExport,
} from '../../static/src/core/ooxml/revision/RevisionExporter';
import type {
  DocumentNode,
  ParagraphNode,
  RunNode,
  SectionNode,
  TableNode,
  RunRevision,
} from '../../static/src/core/ooxml/ast/types';

function mkRun(text: string, revision?: RunRevision): RunNode {
  return { type: 'run', text, props: {}, ...(revision ? { revision } : {}) };
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

// ── exportRevisionsAsJson ─────────────────────────────────────────

describe('Sprint 330 — exportRevisionsAsJson', () => {
  it('空 doc → 空 array', () => {
    const doc = mkDoc([mkParagraph([mkRun('hello')])]);
    expect(exportRevisionsAsJson(doc)).toEqual([]);
  });

  it('單一 ins → 1 row 含正確欄位', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('hi', { type: 'ins', author: 'Alice', id: 1, date: '2026-05-15T10:00:00Z' }),
      ]),
    ]);
    const rows = exportRevisionsAsJson(doc);
    expect(rows).toHaveLength(1);
    expect(rows[0].source).toBe('run-revision');
    expect(rows[0].subtype).toBe('ins');
    expect(rows[0].author).toBe('Alice');
    expect(rows[0].id).toBe('1');
    expect(rows[0].date).toBe('2026-05-15T10:00:00Z');
  });

  it('缺 author / id → 空字串', () => {
    const doc = mkDoc([mkParagraph([mkRun('hi', { type: 'del' })])]);
    const rows = exportRevisionsAsJson(doc);
    expect(rows[0].author).toBe('');
    expect(rows[0].id).toBe('');
    expect(rows[0].date).toBe('');
    expect(rows[0].subtype).toBe('del');
  });

  it('moveFrom / moveTo subtype 正確', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'moveFrom', author: 'A', id: 1 }),
        mkRun('b', { type: 'moveTo', author: 'A', id: 2 }),
      ]),
    ]);
    const rows = exportRevisionsAsJson(doc);
    expect(rows[0].subtype).toBe('moveFrom');
    expect(rows[1].subtype).toBe('moveTo');
  });

  it('pPrChange / rPrChange → subtype 為 props', () => {
    const paragraph: ParagraphNode = {
      type: 'paragraph',
      props: { pPrChange: { author: 'A', id: 10 } },
      runs: [
        {
          type: 'run',
          text: 'x',
          props: { rPrChange: { author: 'B', id: 11 } },
        },
      ],
    };
    const doc = mkDoc([paragraph]);
    const rows = exportRevisionsAsJson(doc);
    expect(rows.find((r) => r.source === 'pPrChange')?.subtype).toBe('props');
    expect(rows.find((r) => r.source === 'rPrChange')?.subtype).toBe('props');
  });
});

// ── escapeCsvField ─────────────────────────────────────────────────

describe('Sprint 330 — escapeCsvField', () => {
  it('普通字串 → 原樣', () => {
    expect(escapeCsvField('hello')).toBe('hello');
  });

  it('含逗號 → 加引號包', () => {
    expect(escapeCsvField('a,b')).toBe('"a,b"');
  });

  it('含引號 → 倍寫 + 加包', () => {
    expect(escapeCsvField('he said "hi"')).toBe('"he said ""hi"""');
  });

  it('含換行 → 加引號包', () => {
    expect(escapeCsvField('a\nb')).toBe('"a\nb"');
  });

  it('空字串 → 空字串', () => {
    expect(escapeCsvField('')).toBe('');
  });
});

// ── exportRevisionsAsCsv ───────────────────────────────────────────

describe('Sprint 330 — exportRevisionsAsCsv', () => {
  it('空 doc → 只回 header', () => {
    const doc = mkDoc([mkParagraph([mkRun('hi')])]);
    expect(exportRevisionsAsCsv(doc)).toBe('source,subtype,author,date,id');
  });

  it('單筆 revision → header + 1 row', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('hi', { type: 'ins', author: 'Alice', id: 1, date: '2026-05-15' }),
      ]),
    ]);
    const csv = exportRevisionsAsCsv(doc);
    const lines = csv.split('\n');
    expect(lines).toHaveLength(2);
    expect(lines[0]).toBe('source,subtype,author,date,id');
    expect(lines[1]).toBe('run-revision,ins,Alice,2026-05-15,1');
  });

  it('author 含逗號 → CSV escape', () => {
    const doc = mkDoc([
      mkParagraph([mkRun('hi', { type: 'ins', author: 'A, B', id: 1 })]),
    ]);
    const csv = exportRevisionsAsCsv(doc);
    expect(csv.split('\n')[1]).toContain('"A, B"');
  });
});

// ── summarizeExport ────────────────────────────────────────────────

describe('Sprint 330 — summarizeExport', () => {
  it('各 subtype 累加 + totalRows', () => {
    const doc = mkDoc([
      mkParagraph([
        mkRun('a', { type: 'ins', author: 'X', id: 1 }),
        mkRun('b', { type: 'del', author: 'X', id: 2 }),
        mkRun('c', { type: 'moveFrom', author: 'X', id: 3 }),
      ]),
    ]);
    const rows = exportRevisionsAsJson(doc);
    const s = summarizeExport(rows);
    expect(s.totalRows).toBe(3);
    expect(s.bySubtype.ins).toBe(1);
    expect(s.bySubtype.del).toBe(1);
    expect(s.bySubtype.moveFrom).toBe(1);
  });

  it('空 → 全 0', () => {
    const s = summarizeExport([]);
    expect(s.totalRows).toBe(0);
    expect(s.bySubtype.ins).toBe(0);
  });
});
