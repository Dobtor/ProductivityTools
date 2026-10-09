/**
 * ThemeResolver — 解析 word/theme/theme1.xml 為 ThemeMap
 *
 * 提供：
 *   - parseTheme(pkg) → ThemeMap | null（缺檔回 null，不 throw）
 *   - resolveThemeColor(theme, themeColor, tint?, shade?) → HexColor
 *
 * 為何有此模組：
 *   <w:color w:themeColor="accent1" w:themeTint="80"/> 在 ParagraphParser 階段
 *   只能讀到 themeColor reference；要轉成具體 hex 必須查 theme1.xml 的 colorScheme
 *   並套用 tint/shade 演算法。
 *
 * 設計決策（ADR-012 補 + Sprint 130 升級）：
 *   - eager resolve：parser 階段就把 themeColor → hex 寫回 RunProps.color，
 *     mapper / renderer 不用再查 theme（簡化下游邏輯，但失去原 themeColor 識別）
 *   - tint/shade 演算法：**Sprint 130 升級為 HSL luminance**（規畫書 §Phase 4.1）。
 *     原 Sprint 1-129 用 RGB linear blend（對 mid-saturation 色差異 < 5pp、但對
 *     vivid 色如 dark navy 會 wash out hue）。HSL 版本保留 hue+saturation、只調 L。
 *     極端值 tint=FF/shade=FF 仍回 white/black（與舊版相容）。
 *   - 缺檔降級：parseTheme 回 null，caller 需自行決定是否用 DEFAULT_THEME_MAP
 *
 * 規格參考：
 *   - ECMA-376 Part 1 §20.1.6.5 (themeElements)
 *   - ECMA-376 Part 1 §20.1.6.2 (clrScheme)
 *   - ECMA-376 Part 1 §17.18.40 (themeColor)
 *   - ECMA-376 Part 1 §17.18.97 (themeTint) / §17.18.85 (themeShade)
 */

import type { OoxmlPackage } from '../package/PackageReader';
import type { HexColor } from '../ast/types';
import { directChild, attr } from '../utils/dom';

/** clrScheme 的 12 色 */
export interface ThemeColors {
  dk1: HexColor;
  lt1: HexColor;
  dk2: HexColor;
  lt2: HexColor;
  accent1: HexColor;
  accent2: HexColor;
  accent3: HexColor;
  accent4: HexColor;
  accent5: HexColor;
  accent6: HexColor;
  hlink: HexColor;
  folHlink: HexColor;
}

/** fontScheme 的 6 組（major/minor × latin/ea/cs） */
export interface ThemeFonts {
  major: { latin?: string; ea?: string; cs?: string };
  minor: { latin?: string; ea?: string; cs?: string };
}

/**
 * Sprint 271：單一 script-specific fallback font（fontScheme 內
 * `<a:font script="Jpan" typeface="ＭＳ ゴシック"/>` 等東亞語系對映）。
 */
export interface ThemeFontFallback {
  parent: 'majorFont' | 'minorFont';
  script: string;
  typeface: string;
}

/**
 * Sprint 271：theme1.xml raw XML extras（parser AST 未消費的 sub-tree、
 * 純為 Phase 6 byte-identical round-trip 而 capture）。
 *
 * OOXML §20.1.6 themeElements 完整結構：
 *   - clrScheme（Sprint 262 已 capture 為 ThemeColors）
 *   - fontScheme（major/minor × latin/ea/cs 已 capture；script fonts 本層補）
 *   - **fmtScheme**（線條/填色/效果樣式、Word UI「主題效果」用、render 不消費）
 *   - **objectDefaults**（圖形 spDef/lnDef/txDef 預設）
 *   - **extraClrSchemeLst**（額外色彩主題）
 *
 * 紀律 #21：每個 extras 欄位皆 optional、缺則不掛 key。
 * 紀律 #18 scope-down：raw XML string preserve、不解析內容（與 mc:Fallback
 *   壓縮哲學一致：parser 不消費的 sub-tree 不結構化、原樣 round-trip）。
 */
export interface ThemeRawExtras {
  /** `<a:fmtScheme>...</a:fmtScheme>` 完整子樹 raw XML。 */
  fmtSchemeXml?: string;
  /** `<a:objectDefaults>...</a:objectDefaults>` 完整子樹 raw XML。 */
  objectDefaultsXml?: string;
  /** `<a:extraClrSchemeLst>...</a:extraClrSchemeLst>` 完整子樹 raw XML。 */
  extraClrSchemeLstXml?: string;
  /** fontScheme 內 script-specific fallback fonts（Word 預設東亞語系字型對映）。 */
  scriptFonts: ThemeFontFallback[];
  /** Sprint 271：theme root name 屬性（如 "Office 佈景主題"）。 */
  themeName?: string;
  /** Sprint 271：clrScheme name 屬性（如 "Office"）。 */
  clrSchemeName?: string;
  /** Sprint 271：fontScheme name 屬性（如 "Office"）。 */
  fontSchemeName?: string;
  /**
   * Sprint 274：完整 `<a:clrScheme>...</a:clrScheme>` raw XML（含 sysClr vs srgbClr
   * 區分、attribute 順序、原始格式）。
   *
   * 為何：Sprint 262 ThemeColors 走 eager resolve（sysClr.lastClr → hex），
   *   round-trip 寫 srgbClr、丟掉 sysClr 識別 → raw byte drift ~2.1%。本 raw
   *   preserve 同時 capture，writer 寫 theme1.xml 時優先用 raw XML（與
   *   ThemeColors 結構化 capture 並存：parser 端走 ThemeColors 供 eager
   *   resolve、writer 端走 rawXml 供 byte preserve）。
   */
  clrSchemeRawXml?: string;
  /** Sprint 274：完整 `<a:fontScheme>...</a:fontScheme>` raw XML（含 script fonts + name + 任何 parser 未消費的 child elements）。 */
  fontSchemeRawXml?: string;
}

export interface ThemeMap {
  colorScheme: ThemeColors;
  fontScheme: ThemeFonts;
  /** Sprint 271：Phase 6 byte-identical round-trip raw extras。 */
  extras?: ThemeRawExtras;
}

/**
 * Office 預設 theme 顏色（accent1~6 為 Office 2007 default scheme）。
 * 用於 theme1.xml 缺檔或 colorScheme 不完整時降級。
 */
export const DEFAULT_THEME_COLORS: ThemeColors = {
  dk1: '000000',
  lt1: 'FFFFFF',
  dk2: '1F497D',
  lt2: 'EEECE1',
  accent1: '4F81BD',
  accent2: 'C0504D',
  accent3: '9BBB59',
  accent4: '8064A2',
  accent5: '4BACC6',
  accent6: 'F79646',
  hlink: '0000FF',
  folHlink: '800080',
};

export const DEFAULT_THEME_FONTS: ThemeFonts = {
  major: { latin: 'Cambria' },
  minor: { latin: 'Calibri' },
};

export const DEFAULT_THEME_MAP: ThemeMap = {
  colorScheme: DEFAULT_THEME_COLORS,
  fontScheme: DEFAULT_THEME_FONTS,
};

/**
 * 從 OOXML package 解析 theme1.xml。
 * 缺檔或解析失敗時回 null（caller 用 DEFAULT_THEME_MAP 降級）。
 *
 * Sprint 271：parsed 結果額外掛 `extras` raw XML preserve（fmtScheme /
 * objectDefaults / extraClrSchemeLst + scriptFonts）；Phase 6 byte-identical
 * round-trip 用。紀律 #21 optional：缺對應 sub-tree → 該欄位 undefined。
 */
export function parseTheme(pkg: OoxmlPackage): ThemeMap | null {
  const xml = pkg.partAsText('word/theme/theme1.xml');
  if (!xml) return null;

  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xml, 'application/xml');
  } catch {
    return null;
  }

  const root = doc.documentElement;
  if (!root) return null;

  const themeElements = directChild(root, 'a:themeElements');
  if (!themeElements) return null;

  const clrSchemeEl = directChild(themeElements, 'a:clrScheme');
  const fontSchemeEl = directChild(themeElements, 'a:fontScheme');

  const result: ThemeMap = {
    colorScheme: clrSchemeEl ? parseColorScheme(clrSchemeEl) : { ...DEFAULT_THEME_COLORS },
    fontScheme: fontSchemeEl ? parseFontScheme(fontSchemeEl) : { major: { ...DEFAULT_THEME_FONTS.major }, minor: { ...DEFAULT_THEME_FONTS.minor } },
  };

  // Sprint 271：抽 raw XML extras（fmtScheme / objectDefaults / extraClrSchemeLst）
  //   用 substring 切割（xmldom serializer 對 namespace 處理 inconsistent、
  //   regex 對 nested 不穩；OOXML §20.1.6 內 fmtScheme 等不可 nested、
  //   simple boundary-match 即足）。
  const fmtSchemeXml = extractRawElement(xml, 'a:fmtScheme');
  const objectDefaultsXml = extractRawElement(xml, 'a:objectDefaults');
  const extraClrSchemeLstXml = extractRawElement(xml, 'a:extraClrSchemeLst');
  const scriptFonts = fontSchemeEl ? parseScriptFonts(fontSchemeEl) : [];
  // Sprint 274：完整 clrScheme + fontScheme raw XML 也 capture
  //   （preserve sysClr vs srgbClr 區分 + attr order + 任何 parser 未消費的 child）
  const clrSchemeRawXml = extractRawElement(xml, 'a:clrScheme');
  const fontSchemeRawXml = extractRawElement(xml, 'a:fontScheme');

  // Sprint 271：capture root/clrScheme/fontScheme name 屬性（剩餘 byte drift 主來源）
  const themeName = attr(root, 'name');
  const clrSchemeName = clrSchemeEl ? attr(clrSchemeEl, 'name') : undefined;
  const fontSchemeName = fontSchemeEl ? attr(fontSchemeEl, 'name') : undefined;

  const hasExtras = fmtSchemeXml !== undefined
    || objectDefaultsXml !== undefined
    || extraClrSchemeLstXml !== undefined
    || scriptFonts.length > 0
    || themeName !== undefined
    || clrSchemeName !== undefined
    || fontSchemeName !== undefined
    || clrSchemeRawXml !== undefined
    || fontSchemeRawXml !== undefined;
  if (hasExtras) {
    const extras: ThemeRawExtras = { scriptFonts };
    if (fmtSchemeXml !== undefined) extras.fmtSchemeXml = fmtSchemeXml;
    if (objectDefaultsXml !== undefined) extras.objectDefaultsXml = objectDefaultsXml;
    if (extraClrSchemeLstXml !== undefined) extras.extraClrSchemeLstXml = extraClrSchemeLstXml;
    if (themeName !== undefined) extras.themeName = themeName;
    if (clrSchemeName !== undefined) extras.clrSchemeName = clrSchemeName;
    if (fontSchemeName !== undefined) extras.fontSchemeName = fontSchemeName;
    if (clrSchemeRawXml !== undefined) extras.clrSchemeRawXml = clrSchemeRawXml;
    if (fontSchemeRawXml !== undefined) extras.fontSchemeRawXml = fontSchemeRawXml;
    result.extras = extras;
  }
  return result;
}

/**
 * Sprint 271：從 raw XML 抽取單一 top-level element 子樹（含 closing tag）。
 *
 * @returns 完整 `<tagName...>...</tagName>` 字串、或 self-closing
 *   `<tagName.../>`；找不到回 undefined。
 *
 * 限制（紀律 #18 scope-down）：
 *   - 假設 tagName 在 XML 內唯一出現（OOXML §20.1.6 fmtScheme/objectDefaults/
 *     extraClrSchemeLst 為 themeElements 直接子元素、不會 nested）
 *   - 不處理 CDATA / 註解內 false-positive（OOXML theme1.xml 不含 CDATA）
 */
export function extractRawElement(xml: string, tagName: string): string | undefined {
  const startPattern = `<${tagName}`;
  const startIdx = xml.indexOf(startPattern);
  if (startIdx < 0) return undefined;
  // 判定是 paired 還是 self-closing：找從 startIdx 開始的第一個 '>' 或 '/>'
  const tagCloseIdx = xml.indexOf('>', startIdx);
  if (tagCloseIdx < 0) return undefined;
  if (xml[tagCloseIdx - 1] === '/') {
    // self-closing：<tagName .../>
    return xml.substring(startIdx, tagCloseIdx + 1);
  }
  // paired：找 </tagName>
  const endPattern = `</${tagName}>`;
  const endIdx = xml.indexOf(endPattern, tagCloseIdx);
  if (endIdx < 0) return undefined;
  return xml.substring(startIdx, endIdx + endPattern.length);
}

/**
 * Sprint 271：從 fontScheme 抽 script-specific fallback fonts
 * （Word 預設東亞語系字型對映、Jpan / Hans / Hant / Hang / Arab / Hebr / ...）。
 */
function parseScriptFonts(fontSchemeEl: Element): ThemeFontFallback[] {
  const out: ThemeFontFallback[] = [];
  const major = directChild(fontSchemeEl, 'a:majorFont');
  const minor = directChild(fontSchemeEl, 'a:minorFont');
  if (major) collectScriptFonts(major, 'majorFont', out);
  if (minor) collectScriptFonts(minor, 'minorFont', out);
  return out;
}

function collectScriptFonts(
  parent: Element,
  parentTag: 'majorFont' | 'minorFont',
  out: ThemeFontFallback[],
): void {
  for (let i = 0; i < parent.childNodes.length; i++) {
    const node = parent.childNodes[i] as Element;
    if (node.nodeType !== 1) continue;
    if (node.nodeName !== 'a:font') continue;
    const script = attr(node, 'script');
    const typeface = attr(node, 'typeface');
    if (script && typeface !== undefined) {
      out.push({ parent: parentTag, script, typeface });
    }
  }
}

function parseColorScheme(el: Element): ThemeColors {
  const out: ThemeColors = { ...DEFAULT_THEME_COLORS };
  const keys: (keyof ThemeColors)[] = [
    'dk1', 'lt1', 'dk2', 'lt2',
    'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6',
    'hlink', 'folHlink',
  ];
  for (const key of keys) {
    const child = directChild(el, `a:${key}`);
    if (!child) continue;
    const hex = readClrValue(child);
    if (hex) out[key] = hex;
  }
  return out;
}

/** 從 <a:srgbClr val="HEX"/> 或 <a:sysClr lastClr="HEX"/> 取 hex */
function readClrValue(parent: Element): HexColor | null {
  const srgb = directChild(parent, 'a:srgbClr');
  if (srgb) {
    const v = attr(srgb, 'val');
    return v ? v.toUpperCase() : null;
  }
  const sys = directChild(parent, 'a:sysClr');
  if (sys) {
    const v = attr(sys, 'lastClr') || attr(sys, 'val');
    if (!v) return null;
    // sysClr val 可能是 'windowText'/'window' 等識別字；此時用 lastClr
    if (/^[0-9A-Fa-f]{6}$/.test(v)) return v.toUpperCase();
    return null;
  }
  return null;
}

function parseFontScheme(el: Element): ThemeFonts {
  const out: ThemeFonts = {
    major: { ...DEFAULT_THEME_FONTS.major },
    minor: { ...DEFAULT_THEME_FONTS.minor },
  };
  const major = directChild(el, 'a:majorFont');
  const minor = directChild(el, 'a:minorFont');
  if (major) {
    out.major.latin = attr(directChild(major, 'a:latin'), 'typeface') || out.major.latin;
    out.major.ea = attr(directChild(major, 'a:ea'), 'typeface') || undefined;
    out.major.cs = attr(directChild(major, 'a:cs'), 'typeface') || undefined;
  }
  if (minor) {
    out.minor.latin = attr(directChild(minor, 'a:latin'), 'typeface') || out.minor.latin;
    out.minor.ea = attr(directChild(minor, 'a:ea'), 'typeface') || undefined;
    out.minor.cs = attr(directChild(minor, 'a:cs'), 'typeface') || undefined;
  }
  return out;
}

/**
 * Word 的 themeColor 識別字 → clrScheme key 對應表。
 * 規格 ECMA-376 §17.18.40。
 */
const THEME_COLOR_MAP: Record<string, keyof ThemeColors> = {
  // 標準名稱
  background1: 'lt1',
  background2: 'lt2',
  text1: 'dk1',
  text2: 'dk2',
  accent1: 'accent1',
  accent2: 'accent2',
  accent3: 'accent3',
  accent4: 'accent4',
  accent5: 'accent5',
  accent6: 'accent6',
  hyperlink: 'hlink',
  followedHyperlink: 'folHlink',
  // 早期版本 Word 有時用這組
  dark1: 'dk1',
  dark2: 'dk2',
  light1: 'lt1',
  light2: 'lt2',
};

/**
 * 把 themeColor reference + tint/shade 解析為具體 hex。
 *
 * @param theme       已解析的 ThemeMap
 * @param themeColor  Word 的 themeColor 識別字（如 "accent1"、"text2"）
 * @param tint        themeTint 屬性 hex 0x00–0xFF（變亮量）
 * @param shade       themeShade 屬性 hex 0x00–0xFF（變暗量）
 * @returns 6-hex color（無效 themeColor 回 "000000"）
 *
 * @example
 *   resolveThemeColor(theme, 'accent1', '80')   // 50% 變亮的 accent1
 *   resolveThemeColor(theme, 'text2', undefined, 'CC')  // 80% 變暗的 text2
 */
export function resolveThemeColor(
  theme: ThemeMap,
  themeColor: string,
  tint?: string,
  shade?: string,
): HexColor {
  const colorKey = THEME_COLOR_MAP[themeColor];
  if (!colorKey) return '000000';
  let base = theme.colorScheme[colorKey];

  if (tint !== undefined && tint !== '') {
    base = applyTint(base, parseHexByte(tint));
  } else if (shade !== undefined && shade !== '') {
    base = applyShade(base, parseHexByte(shade));
  }

  return base;
}

/**
 * Tint = 把顏色亮度往 1.0（白）推；t 為 0..1 比例。
 *
 * HSL luminance 演算法（OOXML §20.1.2.3.20、規畫書 §Phase 4.1）：
 *   L_new = L * (1 - t) + 1.0 * t  →  L + (1 - L) * t
 * 保留 hue 與 saturation、只調 L，避免 vivid 色被 wash out 成 gray-pastel。
 *
 * 極端值：t=0 不變色；t=1 → L_new=1.0 → 純白（與舊 RGB linear 版相容）。
 */
function applyTint(hex: HexColor, t: number): HexColor {
  const tt = clamp01(t);
  const [r, g, b] = hexToRgb(hex);
  const [h, s, l] = rgbToHsl(r, g, b);
  const lNew = l + (1 - l) * tt;
  const [nr, ng, nb] = hslToRgb(h, s, lNew);
  return rgbToHex([Math.round(nr), Math.round(ng), Math.round(nb)]);
}

/**
 * Shade = 把顏色亮度往 0.0（黑）推；s 為 0..1 比例。
 *
 * HSL luminance 演算法（OOXML §20.1.2.3.20、規畫書 §Phase 4.1）：
 *   L_new = L * (1 - s)
 * 保留 hue 與 saturation、只調 L。
 *
 * 極端值：s=0 不變色；s=1 → L_new=0 → 純黑（與舊 RGB linear 版相容）。
 */
function applyShade(hex: HexColor, s: number): HexColor {
  const ss = clamp01(s);
  const [r, g, b] = hexToRgb(hex);
  const [h, sat, l] = rgbToHsl(r, g, b);
  const lNew = l * (1 - ss);
  const [nr, ng, nb] = hslToRgb(h, sat, lNew);
  return rgbToHex([Math.round(nr), Math.round(ng), Math.round(nb)]);
}

/**
 * RGB → HSL 轉換（標準公式，rgb 為 0..255，回傳 h:0..1, s:0..1, l:0..1）。
 * 灰階（max==min）回 h=0、s=0。
 */
function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;

  if (max === min) {
    return [0, 0, l]; // 灰階：無 hue、無 saturation
  }

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case rn:
      h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
      break;
    case gn:
      h = ((bn - rn) / d + 2) / 6;
      break;
    default:
      h = ((rn - gn) / d + 4) / 6;
      break;
  }
  return [h, s, l];
}

/**
 * HSL → RGB 轉換（標準公式，h/s/l 為 0..1，回傳 rgb 0..255 浮點，caller 自行 round）。
 */
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const lc = clamp01(l);
  const sc = clamp01(s);
  if (sc === 0) {
    const v = lc * 255;
    return [v, v, v]; // 灰階：r=g=b=L
  }
  const q = lc < 0.5 ? lc * (1 + sc) : lc + sc - lc * sc;
  const p = 2 * lc - q;
  const hMod = ((h % 1) + 1) % 1; // 包進 0..1
  return [
    hueToRgb(p, q, hMod + 1 / 3) * 255,
    hueToRgb(p, q, hMod) * 255,
    hueToRgb(p, q, hMod - 1 / 3) * 255,
  ];
}

function hueToRgb(p: number, q: number, t: number): number {
  let tt = t;
  if (tt < 0) tt += 1;
  if (tt > 1) tt -= 1;
  if (tt < 1 / 6) return p + (q - p) * 6 * tt;
  if (tt < 1 / 2) return q;
  if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
  return p;
}

/** 把 OOXML 的 hex byte（"00"–"FF"）正規化為 0..1 */
function parseHexByte(hex: string): number {
  const v = parseInt(hex, 16);
  if (Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(255, v)) / 255;
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

function hexToRgb(hex: HexColor): [number, number, number] {
  const h = hex.replace('#', '').padStart(6, '0').toUpperCase();
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function rgbToHex(rgb: [number, number, number]): HexColor {
  return rgb
    .map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0').toUpperCase())
    .join('');
}
