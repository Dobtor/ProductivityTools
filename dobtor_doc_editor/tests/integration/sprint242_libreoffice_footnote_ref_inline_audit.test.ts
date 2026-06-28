/**
 * Sprint 242 — Phase 1 optional 第二批升級：`<w:footnoteReference>` /
 * `<w:endnoteReference>` inline 引用 round-trip audit。
 *
 * Sprint 145 parser capture-only / Sprint 165 標 Phase 1 optional；
 * Sprint 239 補 writer footnotes.xml/endnotes.xml emit；
 * 本 sprint 補 doc.xml 內 inline reference capture + writer emit、閉合
 * doc.xml ↔ footnotes.xml 引用迴路。
 *
 * 測試方式：對 LibreOffice 286 fixture（含真實 footnote 引用），count run 內
 * footnoteRef / endnoteRef 出現次數、驗 round-trip 保留一致。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { BlockNode, DocumentNode, InlineNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const MIN_REF_MATCH_RATE_PCT = 80;

interface RefCount { footnote: number; endnote: number; }

function countInline(nodes: InlineNode[], c: RefCount): void {
  for (const n of nodes) {
    if (n.type === 'footnoteRef') {
      if (n.noteType === 'footnote') c.footnote++;
      else c.endnote++;
    }
  }
}

function countBlock(block: BlockNode, c: RefCount): void {
  if (block.type === 'paragraph') {
    countInline(block.runs, c);
  } else {
    for (const row of block.rows) {
      for (const cell of row.cells) {
        for (const b of cell.content) countBlock(b, c);
      }
    }
  }
}

function countRefs(doc: DocumentNode): RefCount {
  const c: RefCount = { footnote: 0, endnote: 0 };
  for (const sec of doc.sections) {
    for (const b of sec.body) countBlock(b, c);
  }
  return c;
}

interface Fixture { category: string; path: string; abspath: string; }
function collectFixtures(): Fixture[] {
  const out: Fixture[] = [];
  for (const cat of readdirSync(FIXTURE_ROOT)) {
    const catPath = join(FIXTURE_ROOT, cat);
    let st;
    try { st = statSync(catPath); } catch { continue; }
    if (!st.isDirectory()) continue;
    for (const f of readdirSync(catPath)) {
      if (!f.endsWith('.docx')) continue;
      out.push({ category: cat, path: `${cat}/${f}`, abspath: join(catPath, f) });
    }
  }
  return out;
}
function loadAsArrayBuffer(abspath: string): ArrayBuffer {
  const buf = readFileSync(abspath);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
}

describe('Sprint 242 — LibreOffice 286 footnoteRef/endnoteRef inline round-trip audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`run 內 footnoteRef/endnoteRef 計數 round-trip 一致率 ≥ ${MIN_REF_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; pipelineOk: boolean; origFn: number; origEn: number; reparseFn: number; reparseEn: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, pipelineOk: false, origFn: 0, origEn: 0, reparseFn: 0, reparseEn: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        const o = countRefs(originalDoc);
        const rp = countRefs(reparseDoc);
        r.origFn = o.footnote; r.origEn = o.endnote;
        r.reparseFn = rp.footnote; r.reparseEn = rp.endnote;
        r.match = o.footnote === rp.footnote && o.endnote === rp.endnote;
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalFn = results.reduce((a, r) => a + r.origFn, 0);
    const totalEn = results.reduce((a, r) => a + r.origEn, 0);
    const nonZeroFn = results.filter((r) => r.origFn > 0).length;
    const nonZeroEn = results.filter((r) => r.origEn > 0).length;
    // eslint-disable-next-line no-console
    console.log(`[sprint242] pipelineOk=${pipelineOk} match=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalFnRefs=${totalFn} totalEnRefs=${totalEn} fixturesWithFnRef=${nonZeroFn} fixturesWithEnRef=${nonZeroEn}`);
    for (const r of results.filter((x) => x.pipelineOk && !x.match).slice(0, 10)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint242]   DIFF ${r.path}: orig fn=${r.origFn} en=${r.origEn} | reparse fn=${r.reparseFn} en=${r.reparseEn}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_REF_MATCH_RATE_PCT);
  }, 180000);
});
