/**
 * Sprint 235 — Phase 6 Phase 5 (07/08/09) fixture NumberingMap preservation audit
 *
 * 補完三 corpus 九層矩陣末端。
 */

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode, AbstractNumbering, NumberingMap } from '../../static/src/core/ooxml/ast/types';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;
const MIN_NUMBERING_MATCH_RATE_PCT = 90;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeAbstractNumbering(num: AbstractNumbering): unknown {
  const normEmpty = (v: unknown): unknown =>
    v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0 ? undefined : v;
  const normLevel = (lvl: AbstractNumbering['levels'][0]) => ({
    ilvl: lvl.ilvl, numFmt: lvl.numFmt, text: lvl.text, start: lvl.start,
    lvlRestart: lvl.lvlRestart,
    indent: normEmpty(lvl.indent),
    runProps: normEmpty(lvl.runProps),
    pProps: normEmpty(lvl.pProps),
    isLegal: lvl.isLegal,
  });
  return { levels: num.levels.map(normLevel) };
}

function serializeNumberingMap(numbering: NumberingMap): string {
  const ids = Array.from(numbering.keys()).sort((a, b) => a - b);
  const entries = ids.map((id) => ({ id, num: serializeAbstractNumbering(numbering.get(id)!) }));
  return deepStableStringify(entries);
}

function sha256(s: string): string {
  return createHash('sha256').update(s, 'utf8').digest('hex');
}

interface Fixture { category: string; path: string; abspath: string; }

function collectFixtures(): Fixture[] {
  const out: Fixture[] = [];
  for (const cat of PHASE5_CATEGORIES) {
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

describe('Sprint 235 — Phase 6 Phase 5 (07/08/09) fixture NumberingMap preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`NumberingMap SHA-256 對照：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture 保留率 ≥ ${MIN_NUMBERING_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; numCount: number; numMatch: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const origSig = serializeNumberingMap(originalDoc.numbering);
      const reparseSig = serializeNumberingMap(reparseDoc.numbering);
      const match = origSig === reparseSig || sha256(origSig) === sha256(reparseSig);
      results.push({ path: f.path, category: f.category, numCount: originalDoc.numbering.size, numMatch: match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.numMatch).length;
    const matchRate = (matchCount / total) * 100;
    const totalNums = results.reduce((acc, r) => acc + r.numCount, 0);
    const byCategory: Record<string, { total: number; match: number; nums: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, nums: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].nums += r.numCount;
      if (r.numMatch) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint235] total=${total} num match=${matchCount}/${total} (${matchRate.toFixed(1)}%) totalNumberings=${totalNums}`);
    for (const cat of PHASE5_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint235]   ${cat.padEnd(14)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) nums=${stats.nums}`);
    }
    for (const r of results.filter((x) => !x.numMatch)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint235]   DIFF ${r.path}: numCount=${r.numCount}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_NUMBERING_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
