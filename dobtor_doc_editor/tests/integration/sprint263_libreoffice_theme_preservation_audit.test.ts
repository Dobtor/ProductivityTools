/**
 * Sprint 263 — Phase 6 LibreOffice 286 fixture theme.xml 第十八層 audit
 *
 * 對齊 Sprint 262 writer。閾值 80% 對齊既有 LibreOffice audit。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { DocumentNode } from '../../static/src/core/ooxml/ast/types';
import type { ThemeMap } from '../../static/src/core/ooxml/styles/ThemeResolver';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures/10_ooxml_libreoffice');
const EXPECTED_PARSE_OK_BASELINE = 288;
const MIN_THEME_MATCH_RATE_PCT = 80;

function deepStableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(deepStableStringify).join(',') + ']';
  const keys = Object.keys(value as Record<string, unknown>).sort();
  return '{' + keys.map((k) =>
    JSON.stringify(k) + ':' + deepStableStringify((value as Record<string, unknown>)[k]),
  ).join(',') + '}';
}

function serializeTheme(t: ThemeMap | undefined): unknown {
  if (t === undefined) return null;
  return { colorScheme: t.colorScheme, fontScheme: t.fontScheme };
}

function sha256(s: string): string { return createHash('sha256').update(s, 'utf8').digest('hex'); }

function matchTheme(o: { theme?: ThemeMap }, r: { theme?: ThemeMap }): boolean {
  const oS = deepStableStringify(serializeTheme(o.theme));
  const rS = deepStableStringify(serializeTheme(r.theme));
  return oS === rS || sha256(oS) === sha256(rS);
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

describe('Sprint 263 — Phase 6 LibreOffice 286 fixture theme.xml preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`theme SHA-256 對照：${EXPECTED_PARSE_OK_BASELINE} parse-OK fixture 保留率 ≥ ${MIN_THEME_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; parseOk: boolean; pipelineOk: boolean; hasTheme: boolean; colorKeys: number; fontKeys: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const r: Result = { path: f.path, category: f.category, parseOk: false, pipelineOk: false, hasTheme: false, colorKeys: 0, fontKeys: 0, match: false };
      let originalDoc: DocumentNode;
      try { originalDoc = parser.parse(loadAsArrayBuffer(f.abspath)); r.parseOk = true; } catch { results.push(r); continue; }
      try {
        const bytes = writer.write(originalDoc);
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
        const reparseDoc = parser.parse(ab);
        r.pipelineOk = true;
        const t = originalDoc.theme;
        r.hasTheme = t !== undefined;
        r.colorKeys = t ? Object.keys(t.colorScheme).length : 0;
        r.fontKeys = t
          ? Object.keys(t.fontScheme.major).filter((k) => t.fontScheme.major[k as keyof typeof t.fontScheme.major] !== undefined).length +
            Object.keys(t.fontScheme.minor).filter((k) => t.fontScheme.minor[k as keyof typeof t.fontScheme.minor] !== undefined).length
          : 0;
        r.match = matchTheme(originalDoc, reparseDoc);
      } catch { /* pipeline fail */ }
      results.push(r);
    }
    const total = results.length;
    const parseOk = results.filter((x) => x.parseOk).length;
    const pipelineOk = results.filter((x) => x.pipelineOk).length;
    const matchCount = results.filter((x) => x.match).length;
    const matchRate = pipelineOk > 0 ? (matchCount / pipelineOk) * 100 : 0;
    const hasThemeCount = results.filter((x) => x.hasTheme).length;
    const totalColors = results.reduce((a, r) => a + r.colorKeys, 0);
    const totalFonts = results.reduce((a, r) => a + r.fontKeys, 0);
    const byCategory: Record<string, { total: number; pipelineOk: number; match: number; hasTheme: number; colors: number; fonts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, pipelineOk: 0, match: 0, hasTheme: 0, colors: 0, fonts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].colors += r.colorKeys;
      byCategory[r.category].fonts += r.fontKeys;
      if (r.pipelineOk) byCategory[r.category].pipelineOk++;
      if (r.hasTheme) byCategory[r.category].hasTheme++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint263] total=${total} parse=${parseOk}/${total} pipeline=${pipelineOk}/${parseOk} theme=${matchCount}/${pipelineOk} (${matchRate.toFixed(1)}%) hasTheme=${hasThemeCount}/${pipelineOk} totalColors=${totalColors} totalFonts=${totalFonts}`);
    for (const cat of Object.keys(byCategory).sort()) {
      const stats = byCategory[cat];
      const pct = stats.pipelineOk > 0 ? (stats.match / stats.pipelineOk) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint263]   ${cat.padEnd(14)}: pipeline ${stats.pipelineOk}/${stats.total} theme ${stats.match}/${stats.pipelineOk} (${pct.toFixed(1)}%) hasTheme=${stats.hasTheme} colors=${stats.colors} fonts=${stats.fonts}`);
    }
    const failed = results.filter((r) => r.pipelineOk && !r.match);
    if (failed.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[sprint263] theme DIFF count=${failed.length}, sample (first 10):`);
      for (const r of failed.slice(0, 10)) {
        // eslint-disable-next-line no-console
        console.log(`[sprint263]   ${r.path} hasTheme=${r.hasTheme} colors=${r.colorKeys} fonts=${r.fontKeys}`);
      }
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_THEME_MATCH_RATE_PCT);
  }, 180000);
});
