/**
 * Sprint 273 — Phase 6 Phase 5 (07/08/09) fixture theme1.xml raw byte-level audit
 *
 * 對齊 Sprint 271 raw preserve；Phase 5 fixtures 多為 synthetic minimal、無
 * theme1.xml，預期 0 fixture hasTheme → trivially pass。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { unzipSync, strFromU8 } from 'fflate';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const PHASE5_CATEGORIES = ['07_chart', '08_smartart', '09_omml'];
const EXPECTED_FIXTURE_COUNT = 18;

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
function extractThemeXml(docxBytes: Uint8Array): string | null {
  try {
    const parts = unzipSync(docxBytes);
    const theme = parts['word/theme/theme1.xml'];
    if (theme === undefined) return null;
    return strFromU8(theme);
  } catch { return null; }
}

describe('Sprint 273 — Phase 6 Phase 5 (07/08/09) fixture theme1.xml raw byte-level audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`raw byte：${EXPECTED_FIXTURE_COUNT} Phase 5 fixture（synthetic minimal、無 theme1.xml 預期 0/0 trivially）`, () => {
    interface Result { path: string; category: string; hasTheme: boolean; originalBytes: number; exportedBytes: number; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const origRaw = readFileSync(f.abspath);
      const origThemeXml = extractThemeXml(origRaw);
      const doc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedDocx = writer.write(doc);
      const exportedThemeXml = extractThemeXml(exportedDocx);
      results.push({
        path: f.path, category: f.category,
        hasTheme: origThemeXml !== null,
        originalBytes: origThemeXml !== null ? Buffer.byteLength(origThemeXml, 'utf8') : 0,
        exportedBytes: exportedThemeXml !== null ? Buffer.byteLength(exportedThemeXml, 'utf8') : 0,
      });
    }
    const total = results.length;
    const hasThemeCount = results.filter((r) => r.hasTheme).length;
    const totalOrig = results.reduce((a, r) => a + r.originalBytes, 0);
    const totalExp = results.reduce((a, r) => a + r.exportedBytes, 0);
    // eslint-disable-next-line no-console
    console.log(`[sprint273] total=${total} hasTheme=${hasThemeCount}/${total} bytes orig=${totalOrig} exp=${totalExp}`);
    // 無 theme1.xml → 兩端皆 0、trivially pass
    expect(total).toBe(EXPECTED_FIXTURE_COUNT);
    // 兩端應一致：原無 theme writer 不應憑空產生（doc.theme undefined → no emit）
    expect(totalExp).toBe(totalOrig);
  });
});
