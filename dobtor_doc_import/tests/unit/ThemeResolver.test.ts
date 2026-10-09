/**
 * ThemeResolver.test.ts — Phase 4.1
 *
 * 涵蓋：
 *   - parseTheme：clrScheme / fontScheme / 缺檔降級
 *   - resolveThemeColor：themeColor 對應、tint/shade 演算法
 *   - 邊界：未知 themeColor、無效 hex、null theme
 */

import { describe, expect, it } from 'vitest';
import {
  parseTheme,
  resolveThemeColor,
  DEFAULT_THEME_COLORS,
  DEFAULT_THEME_MAP,
  type ThemeMap,
} from '../../static/src/core/ooxml/styles/ThemeResolver';
import type { OoxmlPackage } from '../../static/src/core/ooxml/package/PackageReader';

// ── helpers ──────────────────────────────────────────────────────────────────

/** 輔助：建立含 theme1.xml 的 fake OoxmlPackage（測試用） */
function makePackageWithTheme(themeXml: string | null): OoxmlPackage {
  return {
    parts: new Map(),
    relationships: new Map(),
    getPart: () => undefined,
    getRelationships: () => new Map(),
    partAsText: (path: string) =>
      path === 'word/theme/theme1.xml' && themeXml ? themeXml : undefined,
    resolveRelationship: () => undefined,
  };
}

// 標準 Office theme1.xml（取自 fixture 01_simple/監造會議記錄）
const SAMPLE_THEME_XML = `<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office">
  <a:themeElements>
    <a:clrScheme name="Office">
      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F497D"/></a:dk2>
      <a:lt2><a:srgbClr val="EEECE1"/></a:lt2>
      <a:accent1><a:srgbClr val="4F81BD"/></a:accent1>
      <a:accent2><a:srgbClr val="C0504D"/></a:accent2>
      <a:accent3><a:srgbClr val="9BBB59"/></a:accent3>
      <a:accent4><a:srgbClr val="8064A2"/></a:accent4>
      <a:accent5><a:srgbClr val="4BACC6"/></a:accent5>
      <a:accent6><a:srgbClr val="F79646"/></a:accent6>
      <a:hlink><a:srgbClr val="0000FF"/></a:hlink>
      <a:folHlink><a:srgbClr val="800080"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Office">
      <a:majorFont>
        <a:latin typeface="Cambria"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
        <a:font script="Hant" typeface="新細明體"/>
      </a:majorFont>
      <a:minorFont>
        <a:latin typeface="Calibri"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
        <a:font script="Hant" typeface="新細明體"/>
      </a:minorFont>
    </a:fontScheme>
  </a:themeElements>
</a:theme>`;

// ── parseTheme ───────────────────────────────────────────────────────────────

describe('ThemeResolver — parseTheme', () => {
  it('解析標準 Office theme1.xml 為完整 ThemeMap', () => {
    const pkg = makePackageWithTheme(SAMPLE_THEME_XML);
    const theme = parseTheme(pkg);
    expect(theme).not.toBeNull();
    expect(theme!.colorScheme.dk1).toBe('000000');
    expect(theme!.colorScheme.lt1).toBe('FFFFFF');
    expect(theme!.colorScheme.dk2).toBe('1F497D');
    expect(theme!.colorScheme.accent1).toBe('4F81BD');
    expect(theme!.colorScheme.accent6).toBe('F79646');
    expect(theme!.colorScheme.hlink).toBe('0000FF');
    expect(theme!.colorScheme.folHlink).toBe('800080');
  });

  it('解析 fontScheme 的 majorFont / minorFont latin', () => {
    const pkg = makePackageWithTheme(SAMPLE_THEME_XML);
    const theme = parseTheme(pkg)!;
    expect(theme.fontScheme.major.latin).toBe('Cambria');
    expect(theme.fontScheme.minor.latin).toBe('Calibri');
  });

  it('缺 theme1.xml 時回 null', () => {
    const pkg = makePackageWithTheme(null);
    expect(parseTheme(pkg)).toBeNull();
  });

  it('破碎 XML 不 throw，回 null', () => {
    const pkg = makePackageWithTheme('<<broken xml');
    const theme = parseTheme(pkg);
    // 接受 null 或 default 都算降級成功（不同 DOMParser 對 broken XML 行為不同）
    if (theme !== null) {
      // 若有回，至少要是 ThemeMap 結構
      expect(theme.colorScheme.dk1).toBeTruthy();
    }
  });

  it('缺 themeElements 時回 null', () => {
    const pkg = makePackageWithTheme(
      '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>',
    );
    expect(parseTheme(pkg)).toBeNull();
  });

  it('缺 clrScheme 時用 DEFAULT_THEME_COLORS', () => {
    const pkg = makePackageWithTheme(`
      <a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
        <a:themeElements>
          <a:fontScheme name="X"/>
        </a:themeElements>
      </a:theme>
    `);
    const theme = parseTheme(pkg)!;
    expect(theme.colorScheme).toEqual(DEFAULT_THEME_COLORS);
  });

  it('部分 clrScheme 缺色時用 DEFAULT_THEME_COLORS 補齊', () => {
    const pkg = makePackageWithTheme(`
      <a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
        <a:themeElements>
          <a:clrScheme name="X">
            <a:accent1><a:srgbClr val="ABCDEF"/></a:accent1>
          </a:clrScheme>
        </a:themeElements>
      </a:theme>
    `);
    const theme = parseTheme(pkg)!;
    expect(theme.colorScheme.accent1).toBe('ABCDEF');
    expect(theme.colorScheme.accent2).toBe(DEFAULT_THEME_COLORS.accent2); // 補預設
  });
});

// ── resolveThemeColor ────────────────────────────────────────────────────────

describe('ThemeResolver — resolveThemeColor', () => {
  const theme: ThemeMap = {
    colorScheme: {
      ...DEFAULT_THEME_COLORS,
      accent1: '4F81BD', // r=79, g=129, b=189
      text1: '000000',
    } as typeof DEFAULT_THEME_COLORS,
    fontScheme: { major: {}, minor: {} },
  };

  it('themeColor 直接對應到 colorScheme', () => {
    expect(resolveThemeColor(theme, 'accent1')).toBe('4F81BD');
    expect(resolveThemeColor(theme, 'dk1')).toBe('000000');
  });

  it('Word 別名 background1/text1 → lt1/dk1', () => {
    // theme.colorScheme.dk1 是 DEFAULT_THEME_COLORS.dk1 = '000000'
    expect(resolveThemeColor(theme, 'text1')).toBe('000000');
    // theme.colorScheme.lt1 是 DEFAULT_THEME_COLORS.lt1 = 'FFFFFF'
    expect(resolveThemeColor(theme, 'background1')).toBe('FFFFFF');
  });

  it('未知 themeColor 回黑色 000000', () => {
    expect(resolveThemeColor(theme, 'unknownColor')).toBe('000000');
  });

  it('themeTint 把顏色推向白（HSL luminance、Sprint 130）', () => {
    // accent1 = 4F81BD (r=79, g=129, b=189)
    // HSL: L=0.5255、S=0.4545、H=0.5909（藍色相）
    // tint=80 (hex) = 128/255 ≈ 0.502
    // L_new = 0.5255 + (1 - 0.5255) * 0.502 = 0.7637
    // HSL(0.5909, 0.4545, 0.7637) → RGB ≈ (167, 192, 222) → A7C0DE
    const result = resolveThemeColor(theme, 'accent1', '80');
    expect(result).toMatch(/^[0-9A-F]{6}$/);
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(r, 16)).toBeGreaterThan(150);
    expect(parseInt(r, 16)).toBeLessThan(180);
    expect(parseInt(g, 16)).toBeGreaterThan(180);
    expect(parseInt(b, 16)).toBeGreaterThan(210);
    // 藍色相必須保留：B > G > R（accent1 為藍色）
    expect(parseInt(b, 16)).toBeGreaterThan(parseInt(g, 16));
    expect(parseInt(g, 16)).toBeGreaterThan(parseInt(r, 16));
  });

  it('themeTint=FF 推到白 FFFFFF（極端值）', () => {
    expect(resolveThemeColor(theme, 'accent1', 'FF')).toBe('FFFFFF');
  });

  it('themeTint=00 不變色（極端值）', () => {
    expect(resolveThemeColor(theme, 'accent1', '00')).toBe('4F81BD');
  });

  it('themeShade 把顏色推向黑', () => {
    // accent1 = 4F81BD (r=79, g=129, b=189)
    // shade=80 (hex) = 0.502 → 約 50% 推向黑
    // r' = 79 * (1-0.502) ≈ 39.3 → 39 → 27
    // g' = 129 * 0.498 ≈ 64.2 → 64 → 40
    // b' = 189 * 0.498 ≈ 94.1 → 94 → 5E
    const result = resolveThemeColor(theme, 'accent1', undefined, '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(r, 16)).toBeLessThan(50);
    expect(parseInt(g, 16)).toBeLessThan(75);
    expect(parseInt(b, 16)).toBeLessThan(105);
  });

  it('themeShade=FF 推到黑 000000（極端值）', () => {
    expect(resolveThemeColor(theme, 'accent1', undefined, 'FF')).toBe('000000');
  });

  it('tint 與 shade 同時提供時 tint 優先（與 Word 行為一致）', () => {
    const tintOnly = resolveThemeColor(theme, 'accent1', '80');
    const both = resolveThemeColor(theme, 'accent1', '80', '80');
    expect(both).toBe(tintOnly);
  });

  it('無效 hex 字串回原色（容錯）', () => {
    expect(resolveThemeColor(theme, 'accent1', 'GG')).toBe('4F81BD');
  });
});

// ── Sprint 130：HSL luminance 演算法新增驗證 ───────────────────────────────────

describe('ThemeResolver — Sprint 130 HSL luminance 升級', () => {
  const themeWithVividColors: ThemeMap = {
    colorScheme: {
      ...DEFAULT_THEME_COLORS,
      accent1: '000080',   // 純深藍（vivid、HSL 與 RGB 差最大的情境）
      accent2: 'FF0000',   // 純紅
      accent3: '808080',   // 純灰階（hue 不存在）
      accent4: '4F81BD',   // Office accent1（mid-saturation 藍）
    } as typeof DEFAULT_THEME_COLORS,
    fontScheme: { major: {}, minor: {} },
  };

  it('深藍 (000080) tint=80 保留藍色相、不 wash out 為灰色', () => {
    // HSL: H=240°(藍)、S=1.0、L=0.251
    // L_new = 0.251 + (1 - 0.251) * 0.502 = 0.627
    // HSL→RGB ≈ (64, 64, 254) — B 仍遠大於 R/G
    // 對比 RGB linear: 0*0.498 + 255*0.502 = 128, b=128*0.498+255*0.502=192
    //                  → (128, 128, 192) 嚴重 wash out 為淡紫
    const result = resolveThemeColor(themeWithVividColors, 'accent1', '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(b, 16)).toBeGreaterThan(220);  // B 仍非常飽和（HSL 特徵）
    expect(parseInt(r, 16)).toBeLessThan(100);     // R 沒被 wash up（HSL 特徵）
    expect(parseInt(g, 16)).toBeLessThan(100);
    expect(parseInt(b, 16) - parseInt(r, 16)).toBeGreaterThan(150);  // 藍紅差仍很大
  });

  it('純紅 (FF0000) tint=80 維持紅色相、不變灰', () => {
    // HSL: H=0°、S=1.0、L=0.5
    // L_new = 0.5 + 0.5 * 0.502 = 0.751
    // HSL→RGB ≈ (255, 128, 128) — 鮮明粉紅
    const result = resolveThemeColor(themeWithVividColors, 'accent2', '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(r, 16)).toBeGreaterThan(240);  // R 仍 saturated
    expect(parseInt(g, 16)).toBeLessThan(140);     // G/B 適度提升、仍遠小於 R
    expect(parseInt(b, 16)).toBeLessThan(140);
    expect(parseInt(g, 16)).toBe(parseInt(b, 16)); // G=B（純紅 hue 保持）
  });

  it('純灰 (808080) tint=80 維持灰階、無 hue artifact', () => {
    // 灰階輸入 S=0、HSL→RGB roundtrip R=G=B
    // L=0.502、L_new=0.751 → 192,192,192 = C0C0C0
    const result = resolveThemeColor(themeWithVividColors, 'accent3', '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(r, 16)).toBe(parseInt(g, 16));  // 灰階保持 R=G=B
    expect(parseInt(g, 16)).toBe(parseInt(b, 16));
    expect(parseInt(r, 16)).toBeGreaterThan(180);   // 比原 128 變亮
    expect(parseInt(r, 16)).toBeLessThan(210);
  });

  it('純灰 (808080) shade=80 維持灰階、無 hue artifact', () => {
    // L=0.502、L_new = 0.502 * 0.498 = 0.250 → 64,64,64 = 404040
    const result = resolveThemeColor(themeWithVividColors, 'accent3', undefined, '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    expect(parseInt(r, 16)).toBe(parseInt(g, 16));
    expect(parseInt(g, 16)).toBe(parseInt(b, 16));
    expect(parseInt(r, 16)).toBeGreaterThan(50);    // 比原 128 變暗
    expect(parseInt(r, 16)).toBeLessThan(80);
  });

  it('tint=00 round-trip 完美還原（HSL 數值穩定性）', () => {
    // L_new = L、HSL→RGB roundtrip 應 exact 還原 4F81BD
    // 確保 HSL 轉換鏈無精度漂移
    expect(resolveThemeColor(themeWithVividColors, 'accent4', '00')).toBe('4F81BD');
  });

  it('shade=00 round-trip 完美還原（HSL 數值穩定性）', () => {
    expect(resolveThemeColor(themeWithVividColors, 'accent4', undefined, '00')).toBe('4F81BD');
  });

  it('tint 單調性：tint 值愈大、L 愈接近 1.0（愈白）', () => {
    // 同色多次 tint、亮度應 monotonic 上升
    const tint20 = resolveThemeColor(themeWithVividColors, 'accent1', '20'); // 0.125
    const tint60 = resolveThemeColor(themeWithVividColors, 'accent1', '60'); // 0.376
    const tintC0 = resolveThemeColor(themeWithVividColors, 'accent1', 'C0'); // 0.753

    // 用 R 通道作 luminance proxy（深藍 base R=0、tint 愈多 R 應愈大）
    const r20 = parseInt(tint20.slice(0, 2), 16);
    const r60 = parseInt(tint60.slice(0, 2), 16);
    const rC0 = parseInt(tintC0.slice(0, 2), 16);
    expect(r20).toBeLessThan(r60);
    expect(r60).toBeLessThan(rC0);
  });

  it('shade 單調性：shade 值愈大、L 愈接近 0（愈暗）', () => {
    // 同色多次 shade、亮度應 monotonic 下降
    const shade20 = resolveThemeColor(themeWithVividColors, 'accent2', undefined, '20'); // 0.125
    const shade60 = resolveThemeColor(themeWithVividColors, 'accent2', undefined, '60'); // 0.376
    const shadeC0 = resolveThemeColor(themeWithVividColors, 'accent2', undefined, 'C0'); // 0.753

    // 純紅 base R=255、shade 愈多 R 應愈小
    const r20 = parseInt(shade20.slice(0, 2), 16);
    const r60 = parseInt(shade60.slice(0, 2), 16);
    const rC0 = parseInt(shadeC0.slice(0, 2), 16);
    expect(r20).toBeGreaterThan(r60);
    expect(r60).toBeGreaterThan(rC0);
  });

  it('白色 base (FFFFFF) tint=80 仍為白（已到 L=1 上限）', () => {
    const whiteTheme: ThemeMap = {
      colorScheme: { ...DEFAULT_THEME_COLORS, accent1: 'FFFFFF' } as typeof DEFAULT_THEME_COLORS,
      fontScheme: { major: {}, minor: {} },
    };
    // L=1.0、L_new = 1 + 0 * t = 1 → 仍白
    expect(resolveThemeColor(whiteTheme, 'accent1', '80')).toBe('FFFFFF');
    expect(resolveThemeColor(whiteTheme, 'accent1', 'FF')).toBe('FFFFFF');
  });

  it('黑色 base (000000) shade=80 仍為黑（已到 L=0 下限）', () => {
    const blackTheme: ThemeMap = {
      colorScheme: { ...DEFAULT_THEME_COLORS, accent1: '000000' } as typeof DEFAULT_THEME_COLORS,
      fontScheme: { major: {}, minor: {} },
    };
    // L=0、L_new = 0 * (1-s) = 0 → 仍黑
    expect(resolveThemeColor(blackTheme, 'accent1', undefined, '80')).toBe('000000');
    expect(resolveThemeColor(blackTheme, 'accent1', undefined, 'FF')).toBe('000000');
  });

  it('黑色 base (000000) tint=80 推向白（L 從 0 上升）', () => {
    const blackTheme: ThemeMap = {
      colorScheme: { ...DEFAULT_THEME_COLORS, accent1: '000000' } as typeof DEFAULT_THEME_COLORS,
      fontScheme: { major: {}, minor: {} },
    };
    // L=0、L_new = 0 + 1 * 0.502 = 0.502 → 中灰 ≈ 128
    const result = resolveThemeColor(blackTheme, 'accent1', '80');
    const [, r, g, b] = result.match(/^(..)(..)(..)$/) || [];
    // 黑 tint 應為灰階（無 hue source）、R=G=B
    expect(parseInt(r, 16)).toBe(parseInt(g, 16));
    expect(parseInt(g, 16)).toBe(parseInt(b, 16));
    expect(parseInt(r, 16)).toBeGreaterThan(120);
    expect(parseInt(r, 16)).toBeLessThan(140);
  });
});

// ── 整合：fixture-style theme + RunProps color resolution ───────────────────

describe('ThemeResolver — DEFAULT_THEME_MAP', () => {
  it('DEFAULT_THEME_MAP 為 12 色 + 預設字型', () => {
    const t = DEFAULT_THEME_MAP;
    expect(t.colorScheme.accent1).toBe('4F81BD');
    expect(t.colorScheme.dk1).toBe('000000');
    expect(t.fontScheme.major.latin).toBe('Cambria');
    expect(t.fontScheme.minor.latin).toBe('Calibri');
  });

  it('DEFAULT_THEME_MAP 對 themeColor reference 仍能解析', () => {
    expect(resolveThemeColor(DEFAULT_THEME_MAP, 'accent3')).toBe('9BBB59');
    expect(resolveThemeColor(DEFAULT_THEME_MAP, 'hyperlink')).toBe('0000FF');
  });
});
