/**
 * Sprint 236 — Phase 6 ChienYi 42 fixture Comments preservation audit (第十層)
 *
 * 規畫書對應 §6 黃金測試第十層 Comments（document.comments map / comments.xml）。
 * writer Sprint 194 emit comments.xml；audit 驗 id / author / date / initials
 * + content 段落文字 round-trip 一致。空 Map 為 trivially match。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { CommentContent, BlockNode } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;
const MIN_COMMENT_MATCH_RATE_PCT = 90;

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
  return {
    id: c.id,
    author: c.author,
    date: c.date,
    initials: c.initials,
    blockCount: c.content.length,
    text: c.content.map(extractBlockText).join('\n'),
  };
}

function serializeCommentMap(comments: Map<number, CommentContent>): string {
  const ids = Array.from(comments.keys()).sort((a, b) => a - b);
  return deepStableStringify(ids.map((id) => serializeComment(comments.get(id)!)));
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

interface Fixture { category: string; path: string; abspath: string; }
function collectFixtures(): Fixture[] {
  const out: Fixture[] = [];
  for (const cat of CHIENYI_CATEGORIES) {
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

describe('Sprint 236 — Phase 6 ChienYi 42 fixture Comments preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`Comments SHA-256 對照：${EXPECTED_FIXTURE_COUNT} fixture 保留率 ≥ ${MIN_COMMENT_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; commentCount: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origSig = serializeCommentMap(originalDoc.comments);
      const reparseSig = serializeCommentMap(reparseDoc.comments);
      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({ path: f.path, category: f.category, commentCount: originalDoc.comments.size, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const totalComments = results.reduce((acc, r) => acc + r.commentCount, 0);
    const byCategory: Record<string, { total: number; match: number; comments: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, comments: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].comments += r.commentCount;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint236] total=${total} comment match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalComments=${totalComments}`);
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint236]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) comments=${stats.comments}`);
    }
    for (const r of results.filter((x) => !x.match)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint236]   DIFF ${r.path}: commentCount=${r.commentCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_COMMENT_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
