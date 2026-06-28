/**
 * Sprint 262 — Phase 6 ChienYi 42 fixture theme.xml 第十八層 audit
 *
 * 對齊 Sprint 262 writer：collectTheme / writeTheme / writeThemeFont 新增；
 * parser 端 OoxmlParser.parsedTheme 寫回 DocumentNode.theme（紀律 #21 optional）。
 *
 * audit 驗 round-trip：original.theme === reparse.theme（colorScheme 12 色 +
 * fontScheme major/minor × latin/ea/cs）。
 *
 * ChienYi 42 fixture 都應有 theme1.xml（Word 預設骨架）；本 audit 揭發 writer
 * 第十一次真實修法（若未修則 0/42 預期）。
 */
import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';
import type { ThemeMap } from '../../static/src/core/ooxml/styles/ThemeResolver';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;
const MIN_THEME_MATCH_RATE_PCT = 90;

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

describe('Sprint 262 — Phase 6 ChienYi 42 fixture theme.xml preservation audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`theme SHA-256 對照：${EXPECTED_FIXTURE_COUNT} fixture 保留率 ≥ ${MIN_THEME_MATCH_RATE_PCT}%`, () => {
    interface Result { path: string; category: string; hasTheme: boolean; colorKeys: number; fontKeys: number; match: boolean; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const originalDoc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedBytes = writer.write(originalDoc);
      const ab = exportedBytes.buffer.slice(exportedBytes.byteOffset, exportedBytes.byteOffset + exportedBytes.byteLength) as ArrayBuffer;
      const reparseDoc = parser.parse(ab);
      const match = matchTheme(originalDoc, reparseDoc);
      const t = originalDoc.theme;
      const colorKeys = t ? Object.keys(t.colorScheme).length : 0;
      const fontKeys = t
        ? Object.keys(t.fontScheme.major).filter((k) => t.fontScheme.major[k as keyof typeof t.fontScheme.major] !== undefined).length +
          Object.keys(t.fontScheme.minor).filter((k) => t.fontScheme.minor[k as keyof typeof t.fontScheme.minor] !== undefined).length
        : 0;
      results.push({ path: f.path, category: f.category, hasTheme: t !== undefined, colorKeys, fontKeys, match });
    }
    const total = results.length;
    const matchCount = results.filter((r) => r.match).length;
    const matchRate = (matchCount / total) * 100;
    const hasThemeCount = results.filter((r) => r.hasTheme).length;
    const totalColors = results.reduce((a, r) => a + r.colorKeys, 0);
    const totalFonts = results.reduce((a, r) => a + r.fontKeys, 0);
    const byCategory: Record<string, { total: number; match: number; hasTheme: number; colors: number; fonts: number }> = {};
    for (const r of results) {
      if (!byCategory[r.category]) byCategory[r.category] = { total: 0, match: 0, hasTheme: 0, colors: 0, fonts: 0 };
      byCategory[r.category].total++;
      byCategory[r.category].colors += r.colorKeys;
      byCategory[r.category].fonts += r.fontKeys;
      if (r.hasTheme) byCategory[r.category].hasTheme++;
      if (r.match) byCategory[r.category].match++;
    }
    // eslint-disable-next-line no-console
    console.log(`[sprint262] total=${total} match=${matchCount}/${total} (${matchRate.toFixed(1)}%) hasTheme=${hasThemeCount}/${total} totalColors=${totalColors} totalFonts=${totalFonts}`);
    for (const cat of CHIENYI_CATEGORIES) {
      const stats = byCategory[cat];
      if (!stats) continue;
      const pct = stats.total > 0 ? (stats.match / stats.total) * 100 : 0;
      // eslint-disable-next-line no-console
      console.log(`[sprint262]   ${cat.padEnd(20)}: ${stats.match}/${stats.total} (${pct.toFixed(1)}%) hasTheme=${stats.hasTheme} colors=${stats.colors} fonts=${stats.fonts}`);
    }
    for (const r of results.filter((x) => !x.match).slice(0, 5)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint262]   DIFF ${r.path}: hasTheme=${r.hasTheme} colors=${r.colorKeys} fonts=${r.fontKeys}`);
    }
    expect(matchRate).toBeGreaterThanOrEqual(MIN_THEME_MATCH_RATE_PCT);
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
  });
});
