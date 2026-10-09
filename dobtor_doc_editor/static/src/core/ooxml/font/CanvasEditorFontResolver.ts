/**
 * CanvasEditorFontResolver — Sprint 313。
 *
 * Sprint 303 CanvasEditorMeasureBridge + Sprint 308 CanvasEditorPatchProbe 之後
 * 第三輪深推。Canvas2D 的 `ctx.font` 是 CSS-style 字串（如
 * `"12pt DejaVu Sans, sans-serif"` 或 `"bold italic 14px 'Noto Sans CJK'"`）；
 * caller 接管 measureText 時必須從這個字串拆出 family + sizePt 才能餵 bridge。
 *
 * 範圍：
 *   - `parseCanvasFont(fontStr)` → `{ family, sizePt, style?, weight? }`
 *   - 支援 size 單位：pt / px / em / rem / %（轉成 pt、用 96 dpi 換算）
 *   - 支援 quoted family（單/雙引號）+ fallback list
 *   - 不支援 stretch / variant / line-height（CSS font shorthand 罕用、Canvas2D 接受
 *     但 ctx.measureText 不消費這些）
 *
 * 紀律 #18 scope-down：
 *   - 不接 Browser native 解析（caller 環境若需精準對齊瀏覽器、自行用
 *     CSSStyleDeclaration 解析）；本層為輕量 PROBE-grade parser
 *   - 不處理 CSS @font-face descriptor、unicode-range 等進階屬性
 *
 * 紀律 #21：純 pure-fn、不污染既有 production；caller 顯式呼叫才生效。
 */

const PT_PER_PX_AT_96DPI = 72 / 96;

export interface ResolvedFont {
  family: string;
  sizePt: number;
  /** italic / oblique / normal；缺省 normal */
  style?: 'normal' | 'italic' | 'oblique';
  /** bold / normal / 100-900；缺省 normal */
  weight?: 'normal' | 'bold' | number;
  /** 後備字型列表（caller 第一個 family load 失敗時依序試） */
  fallbacks?: string[];
}

export interface ParseCanvasFontOptions {
  /** Caller 環境 DPI；用於 px → pt 轉換時。缺省 96。 */
  dpi?: number;
  /** em / rem / % 的 base size in pt；缺省 12 */
  baseSizePt?: number;
}

const STYLE_TOKENS = new Set(['italic', 'oblique', 'normal']);
const WEIGHT_TOKENS = new Set(['bold', 'normal', 'lighter', 'bolder']);
const STRETCH_TOKENS = new Set([
  'ultra-condensed', 'extra-condensed', 'condensed', 'semi-condensed',
  'semi-expanded', 'expanded', 'extra-expanded', 'ultra-expanded',
]);
const VARIANT_TOKENS = new Set(['small-caps']);

/**
 * 解析 Canvas2D `ctx.font` 字串（subset of CSS font shorthand）。
 *
 * 範例：
 *   "12pt DejaVu Sans"                        → { family: "DejaVu Sans", sizePt: 12 }
 *   "16px 'Noto Sans CJK TC', sans-serif"     → { family: "Noto Sans CJK TC", sizePt: 12, fallbacks: ["sans-serif"] }
 *   "bold italic 14pt Arial"                  → { family: "Arial", sizePt: 14, weight: "bold", style: "italic" }
 *   "1.5em 'Source Han Sans'"                 → { family: "Source Han Sans", sizePt: 18 (baseSizePt=12 * 1.5) }
 *
 * 解析失敗（無 size + family）→ throw。
 */
export function parseCanvasFont(fontStr: string, opts: ParseCanvasFontOptions = {}): ResolvedFont {
  const dpi = opts.dpi ?? 96;
  const baseSizePt = opts.baseSizePt ?? 12;

  const trimmed = fontStr.trim();
  if (!trimmed) {
    throw new Error('[CanvasEditorFontResolver] empty font string');
  }

  // 簡化 tokenizer：把 quoted family group 為單一 token（不切空白）
  const tokens = tokenize(trimmed);

  let style: ResolvedFont['style'] | undefined;
  let weight: ResolvedFont['weight'] | undefined;
  let sizeIdx = -1;

  // 依 CSS spec：style/variant/weight/stretch 可任意順序、size 之前
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i].toLowerCase();
    if (STYLE_TOKENS.has(t)) {
      if (t === 'italic' || t === 'oblique') style = t;
    } else if (WEIGHT_TOKENS.has(t)) {
      if (t === 'bold') weight = 'bold';
    } else if (/^\d{3}$/.test(t)) {
      // 100-900 numeric weight
      weight = parseInt(t, 10);
    } else if (STRETCH_TOKENS.has(t) || VARIANT_TOKENS.has(t)) {
      // 跳過（紀律 #18 scope-down）
    } else if (isSizeToken(t)) {
      sizeIdx = i;
      break;
    } else {
      // 不識別 prefix token：可能是 family 已開始（如 "Arial"）→ 視為 size 缺失
      throw new Error(`[CanvasEditorFontResolver] missing size before family token: "${tokens[i]}"`);
    }
  }

  if (sizeIdx < 0) {
    throw new Error(`[CanvasEditorFontResolver] no size found in font string: "${fontStr}"`);
  }

  const sizePt = parseSize(tokens[sizeIdx], dpi, baseSizePt);

  // size 之後到字串結尾為 family list（可能含 line-height 加在 size 後、紀律 #18 不處理）
  const familyTokens = tokens.slice(sizeIdx + 1);
  if (familyTokens.length === 0) {
    throw new Error(`[CanvasEditorFontResolver] no family in font string: "${fontStr}"`);
  }
  // 重組 family list：join 後依 comma 切
  const familyJoined = familyTokens.join(' ');
  const familyList = familyJoined.split(',').map((f) => unquoteFamily(f.trim())).filter(Boolean);
  if (familyList.length === 0) {
    throw new Error(`[CanvasEditorFontResolver] empty family list in font string: "${fontStr}"`);
  }

  const result: ResolvedFont = {
    family: familyList[0],
    sizePt,
  };
  if (style !== undefined) result.style = style;
  if (weight !== undefined) result.weight = weight;
  if (familyList.length > 1) result.fallbacks = familyList.slice(1);
  return result;
}

/**
 * 反向：把 ResolvedFont 組回 CSS font shorthand（caller 想 round-trip 用）。
 */
export function formatCanvasFont(font: ResolvedFont): string {
  const parts: string[] = [];
  if (font.style && font.style !== 'normal') parts.push(font.style);
  if (font.weight !== undefined && font.weight !== 'normal') {
    parts.push(typeof font.weight === 'number' ? String(font.weight) : font.weight);
  }
  parts.push(`${font.sizePt}pt`);
  const families = [font.family, ...(font.fallbacks ?? [])];
  parts.push(families.map((f) => (/\s/.test(f) ? `'${f}'` : f)).join(', '));
  return parts.join(' ');
}

// ── internals ──────────────────────────────────────────────────────────

function tokenize(s: string): string[] {
  // 把 quoted segment 整合為單一 token、避免空白切錯
  const tokens: string[] = [];
  let i = 0;
  while (i < s.length) {
    while (i < s.length && /\s/.test(s[i])) i++;
    if (i >= s.length) break;
    const c = s[i];
    if (c === '"' || c === "'") {
      const end = s.indexOf(c, i + 1);
      if (end < 0) {
        // unterminated quote → 取到結尾
        tokens.push(s.slice(i));
        break;
      }
      tokens.push(s.slice(i, end + 1));
      i = end + 1;
    } else {
      let j = i;
      while (j < s.length && !/\s/.test(s[j])) {
        if (s[j] === ',') {
          // comma 為分隔符、單獨成 token
          if (j === i) { tokens.push(','); j++; break; }
          break;
        }
        j++;
      }
      if (j > i) tokens.push(s.slice(i, j));
      i = j;
      // 把附帶的 comma 也吞掉
      if (s[i] === ',') { tokens.push(','); i++; }
    }
  }
  // 合併 comma 相鄰 token → "Arial," / ",sans-serif" 維持原樣，由 family 階段處理 split
  // 此處 tokens 已是 reasonable list
  return tokens.filter((t) => t.length > 0);
}

function isSizeToken(t: string): boolean {
  return /^\d+(\.\d+)?(pt|px|em|rem|%)$/i.test(t);
}

function parseSize(token: string, dpi: number, baseSizePt: number): number {
  const m = /^(\d+(?:\.\d+)?)(pt|px|em|rem|%)$/i.exec(token);
  if (!m) throw new Error(`[CanvasEditorFontResolver] bad size token: "${token}"`);
  const value = parseFloat(m[1]);
  const unit = m[2].toLowerCase();
  switch (unit) {
    case 'pt': return value;
    case 'px': return value * PT_PER_PX_AT_96DPI * (96 / dpi);
    case 'em':
    case 'rem': return value * baseSizePt;
    case '%': return (value / 100) * baseSizePt;
    default: throw new Error(`[CanvasEditorFontResolver] unsupported size unit: "${unit}"`);
  }
}

function unquoteFamily(s: string): string {
  if (s.length >= 2 && (s.startsWith("'") || s.startsWith('"')) && s.endsWith(s[0])) {
    return s.slice(1, -1);
  }
  return s;
}
