/**
 * Sprint 237 — Phase 6 LibreOffice 286 fixture Comments preservation audit (第十層)
 *
 * Sprint 236 ChienYi 42 達標後套用至 LibreOffice 邊緣 corpus。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { CommentContent, BlockNode, DocumentNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_COMMENT_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function extractBlockText(block: BlockNode): string {
  if (block.type === 'paragraph') {
    return (block.runs || []).map((r) => ('text' in r ? r.text : '')).join('');
  }
  if (block.type === 'table') {
    return (block.rows || []).map((row) =>
      (row.cells || []).map((cell) =>
        (cell.content || []).map(extractBlockText).join('\n'),
      ).join('\t'),
    ).join('\n');
  }
  return '';
}

function serializeComment(c: CommentContent): unknown {
  return { id: c.id, author: c.author, date: c.date, initials: c.initials,
    blockCount: c.content.length, text: c.content.map(extractBlockText).join('\n') };
}

function serializeCommentMap(comments: Map<number, CommentContent>): string {
  const ids = Array.from(comments.keys()).sort((a, b) => a - b);
  return deepStableStringify(ids.map((id) => serializeComment(comments.get(id)!)));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

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

describe('Sprint 237 — Phase 6 LibreOffice 286 fixture Comments preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Comments SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_COMMENT_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; commentCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, commentCount: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const exportedBytes = writer.write(originalDoc);
        const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        r.commentCount = originalDoc.comments.size;
        const origSig = serializeCommentMap(originalDoc.comments);
        const reparseSig = serializeCommentMap(reparseDoc.comments);
        r.match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const totalComments = results.reduce((acc, r) => acc + r.commentCount, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; comments: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, comments: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].comments += r.commentCount;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint237] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} comment=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) totalComments=${totalComments}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint237]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} comment ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) comments=${stats.comments}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint237] comment DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint237]   ${r.path} commentCount=${r.commentCount}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_COMMENT_MATCH_RATE_PCT);
  }, 180000);
});
