/**
 * Sprint 270 — Phase 6 theme1.xml raw byte-level audit（揭發實情、Sprint 218→219 mode probe）
 *
 * Sprint 262-264 第十八層 audit 100% 是 AST 層面（colorScheme + fontScheme
 * major/minor × latin/ea/cs）；本 audit 對 raw file bytes 直接量測 export 後
 * theme1.xml 與原檔的差距、揭發 parser 未 capture 的子樹（fmtScheme /
 * objectDefaults / extraClrSchemeLst / 多 script fontScheme fallback fonts）
 * 造成的 byte-level drift。
 *
 * 預期結果（hypothesis）：
 *   - 原 theme1.xml ~7KB → export 後 ~1KB（loss ~85%）
 *   - AST round-trip 100% 但 raw file ≠ byte-identical
 *
 * 本 audit 純揭發、無修法；user 決定後續 GO（raw preserve）/ NO-GO（接受
 * mc:Fallback 壓縮現狀、優先級低）。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { unzipSync, strFromU8 } from 'fflate';

import { OoxmlParser } from '../../static/src/core/ooxml/OoxmlParser';
import { OoxmlWriter } from '../../static/src/core/ooxml/export/OoxmlWriter';

const FIXTURE_ROOT = resolve(__dirname, '../fixtures');
const CHIENYI_CATEGORIES = ['01_simple', '02_std_table', '03_complex_table', '04_with_image', '05_header_footer', '06_template'];
const EXPECTED_FIXTURE_COUNT = 42;

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

function extractThemeXml(docxBytes: Uint8Array): string | null {
  const parts = unzipSync(docxBytes);
  const theme = parts['word/theme/theme1.xml'];
  if (theme === undefined) return null;
  return strFromU8(theme);
}

interface DriftReport {
  hasTheme: boolean;
  originalBytes: number;
  exportedBytes: number;
  // 標籤出現次數比較
  fmtSchemeOriginal: number;
  fmtSchemeExported: number;
  objectDefaultsOriginal: number;
  objectDefaultsExported: number;
  extraClrSchemeLstOriginal: number;
  extraClrSchemeLstExported: number;
  // fontScheme 內 script-specific fallback fonts 數
  scriptFontsOriginal: number;
  scriptFontsExported: number;
  byteIdentical: boolean;
}

function analyzeDrift(origXml: string | null, exportXml: string | null): DriftReport {
  if (origXml === null) {
    return {
      hasTheme: false,
      originalBytes: 0, exportedBytes: 0,
      fmtSchemeOriginal: 0, fmtSchemeExported: 0,
      objectDefaultsOriginal: 0, objectDefaultsExported: 0,
      extraClrSchemeLstOriginal: 0, extraClrSchemeLstExported: 0,
      scriptFontsOriginal: 0, scriptFontsExported: 0,
      byteIdentical: false,
    };
  }
  const exp = exportXml ?? '';
  return {
    hasTheme: true,
    originalBytes: Buffer.byteLength(origXml, 'utf8'),
    exportedBytes: Buffer.byteLength(exp, 'utf8'),
    fmtSchemeOriginal: (origXml.match(/<a:fmtScheme/g) ?? []).length,
    fmtSchemeExported: (exp.match(/<a:fmtScheme/g) ?? []).length,
    objectDefaultsOriginal: (origXml.match(/<a:objectDefaults/g) ?? []).length,
    objectDefaultsExported: (exp.match(/<a:objectDefaults/g) ?? []).length,
    extraClrSchemeLstOriginal: (origXml.match(/<a:extraClrSchemeLst/g) ?? []).length,
    extraClrSchemeLstExported: (exp.match(/<a:extraClrSchemeLst/g) ?? []).length,
    scriptFontsOriginal: (origXml.match(/<a:font\s+script=/g) ?? []).length,
    scriptFontsExported: (exp.match(/<a:font\s+script=/g) ?? []).length,
    byteIdentical: origXml === exp,
  };
}

describe('Sprint 270 — Phase 6 ChienYi 42 fixture theme1.xml raw byte-level drift audit', () => {
  const fixtures = collectFixtures();
  const parser = new OoxmlParser();
  const writer = new OoxmlWriter();

  it(`raw byte 對照：${EXPECTED_FIXTURE_COUNT} fixture 揭發 fmtScheme/objectDefaults/script fonts drift`, () => {
    interface Result { path: string; report: DriftReport; }
    const results: Result[] = [];
    for (const f of fixtures) {
      const origBytes = readFileSync(f.abspath);
      const origThemeXml = extractThemeXml(origBytes);

      const doc = parser.parse(loadAsArrayBuffer(f.abspath));
      const exportedDocx = writer.write(doc);
      const exportedThemeXml = extractThemeXml(exportedDocx);

      results.push({ path: f.path, report: analyzeDrift(origThemeXml, exportedThemeXml) });
    }

    // 統計
    const hasThemeCount = results.filter((r) => r.report.hasTheme).length;
    const byteIdenticalCount = results.filter((r) => r.report.byteIdentical).length;
    const totalOrigBytes = results.reduce((a, r) => a + r.report.originalBytes, 0);
    const totalExportBytes = results.reduce((a, r) => a + r.report.exportedBytes, 0);
    const totalFmtSchemeOrig = results.reduce((a, r) => a + r.report.fmtSchemeOriginal, 0);
    const totalFmtSchemeExp = results.reduce((a, r) => a + r.report.fmtSchemeExported, 0);
    const totalObjDefOrig = results.reduce((a, r) => a + r.report.objectDefaultsOriginal, 0);
    const totalObjDefExp = results.reduce((a, r) => a + r.report.objectDefaultsExported, 0);
    const totalExtraOrig = results.reduce((a, r) => a + r.report.extraClrSchemeLstOriginal, 0);
    const totalExtraExp = results.reduce((a, r) => a + r.report.extraClrSchemeLstExported, 0);
    const totalScriptFontsOrig = results.reduce((a, r) => a + r.report.scriptFontsOriginal, 0);
    const totalScriptFontsExp = results.reduce((a, r) => a + r.report.scriptFontsExported, 0);
    const byteRetention = totalOrigBytes > 0 ? (totalExportBytes / totalOrigBytes) * 100 : 0;

    // eslint-disable-next-line no-console
    console.log(`[sprint270] hasTheme=${hasThemeCount}/${results.length} byteIdentical=${byteIdenticalCount}/${results.length}`);
    // eslint-disable-next-line no-console
    console.log(`[sprint270] bytes: orig=${totalOrigBytes} exp=${totalExportBytes} retention=${byteRetention.toFixed(1)}%`);
    // eslint-disable-next-line no-console
    console.log(`[sprint270] fmtScheme: orig=${totalFmtSchemeOrig} exp=${totalFmtSchemeExp} (loss ${totalFmtSchemeOrig - totalFmtSchemeExp})`);
    // eslint-disable-next-line no-console
    console.log(`[sprint270] objectDefaults: orig=${totalObjDefOrig} exp=${totalObjDefExp} (loss ${totalObjDefOrig - totalObjDefExp})`);
    // eslint-disable-next-line no-console
    console.log(`[sprint270] extraClrSchemeLst: orig=${totalExtraOrig} exp=${totalExtraExp} (loss ${totalExtraOrig - totalExtraExp})`);
    // eslint-disable-next-line no-console
    console.log(`[sprint270] script fonts: orig=${totalScriptFontsOrig} exp=${totalScriptFontsExp} (loss ${totalScriptFontsOrig - totalScriptFontsExp})`);

    // sample first 3 fixture detail
    for (const r of results.slice(0, 3)) {
      // eslint-disable-next-line no-console
      console.log(`[sprint270]   ${r.path}: orig=${r.report.originalBytes}B exp=${r.report.exportedBytes}B fmt=${r.report.fmtSchemeOriginal}→${r.report.fmtSchemeExported} obj=${r.report.objectDefaultsOriginal}→${r.report.objectDefaultsExported} scriptFonts=${r.report.scriptFontsOriginal}→${r.report.scriptFontsExported}`);
    }

    // Sprint 271 raw preserve 修法後（v1 揭發 0/42 byteIdentical / 12.6% retention →
    //   v2 修法 raw preserve fmtScheme + objectDefaults + extraClrSchemeLst +
    //   script fonts + name attrs → retention >= 95% commercial-grade、剩餘
    //   ~2% 是 sysClr → srgbClr eager resolve 等效差異、紀律 #18 scope-down 不修）
    expect(results.length).toBe(EXPECTED_FIXTURE_COUNT);
    expect(hasThemeCount).toBe(EXPECTED_FIXTURE_COUNT);
    expect(totalFmtSchemeExp).toBe(totalFmtSchemeOrig);
    expect(totalObjDefExp).toBe(totalObjDefOrig);
    expect(totalExtraExp).toBe(totalExtraOrig);
    expect(totalScriptFontsExp).toBe(totalScriptFontsOrig);
    expect(byteRetention).toBeGreaterThanOrEqual(95);
  });
});
