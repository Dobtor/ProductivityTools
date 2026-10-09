/**
 * numberingFormatter — 把序號數字按 OOXML w:numFmt 規則格式化為顯示字串
 *
 * 用途：NumberingResolver 解析 `<w:lvl><w:numFmt val="chineseCounting"/></w:lvl>`
 * 後保留原始 `numFmt` 字串；Renderer / mapper 階段把計數器 number 透過此模組轉為
 * 「一」「二」「壹」「i」「I」「a」… 等實際顯示字元。
 *
 * 設計決策（Sprint 132、規畫書 §Phase 4.3）：
 *   - **純函式 + 無狀態**：好 cache、好測試（紀律 #3 / #5）
 *   - **不在 Renderer 內 inline**：保持「OOXML 知識」集中在 numbering 目錄
 *   - **fallback 為 decimal**：未知 numFmt 不 throw、回 `String(n)` 確保 render 不斷
 *   - **0 / 負數防禦**：依各 format 語意決定（如 decimal 直回；CN 序數的 0 = 〇）
 *
 * 涵蓋的 numFmt（ECMA-376 §17.18.59 ST_NumberFormat 子集，依規畫書 §Phase 4.3）：
 *
 * | numFmt | 範例（n=1, 2, 11） | 備註 |
 * |---|---|---|
 * | decimal | 1, 2, 11 | 預設 / fallback |
 * | decimalZero | 01, 02, 11 | 兩位數補 0（OOXML 標準 padding） |
 * | none | "" | 不渲染（OOXML 規定）|
 * | bullet | "" | 由 w:lvlText 直接給字元、formatter 不處理 |
 * | lowerLetter / upperLetter | a/A, b/B, aa/AA | base-26 |
 * | lowerRoman / upperRoman | i/I, ii/II, xi/XI | 1–3999 範圍 |
 * | ordinal | 1st, 2nd, 3rd, 11th | 英文序數 |
 * | ordinalText | first, second, eleventh | 英文序數文字（1–20）|
 * | cardinalText | one, two, eleven | 英文基數文字（1–20）|
 * | chineseCounting | 一, 二, 十一 | 繁/簡通用書寫形式（1–9999）|
 * | chineseCountingThousand | 一千零一 | 千分隔（1–9999）|
 * | chineseLegalSimplified | 壹, 貳, 拾壹 | 法定大寫（繁體寫法、簡體稍有差異）|
 * | ideographDigital | 〇, 一, 二, 一一 | 用作 digits（每位數獨立）|
 * | ideographZodiac | 子, 丑, 寅 | 12 地支循環 |
 * | ideographTraditional | 甲, 乙, 丙 | 10 天干循環 |
 * | japaneseCounting | 一, 二, 十一 | 與 chineseCounting 同（W 規格簡化）|
 * | japaneseDigitalTenThousand | 一万 | 萬分隔 |
 * | japaneseLegal | 壱, 弐, 参 | 日文法定大寫（與中文略異）|
 * | taiwaneseCounting | 一, 二, 十一 | 同 chineseCounting |
 * | taiwaneseCountingThousand | 一千, 二千 | 同 chineseCountingThousand |
 * | iroha | い, ろ, は, … | 47 字假名循環 |
 * | aiueo | あ, い, う, … | 46 字假名循環 |
 *
 * 規格參考：
 *   - ECMA-376 Part 1 §17.18.59 (ST_NumberFormat)
 *   - ECMA-376 Part 1 §17.9.27 (lvlText)
 *   - ECMA-376 Part 1 §17.9.30 (numFmt)
 */

/**
 * 把計數 n 依 numFmt 格式化為顯示字串。
 *
 * @param n        計數值（通常 ≥ 1；0 / 負數依 format 各自處理）
 * @param numFmt   OOXML w:numFmt 字串（如 'chineseCounting'）
 * @returns 顯示字串；未知 numFmt 回 `String(n)`（fallback to decimal）
 *
 * @example
 *   formatNumber(1, 'chineseCounting')         // → "一"
 *   formatNumber(11, 'chineseCounting')        // → "十一"
 *   formatNumber(5, 'lowerRoman')              // → "v"
 *   formatNumber(28, 'lowerLetter')            // → "ab"
 *   formatNumber(3, 'ordinal')                 // → "3rd"
 *   formatNumber(2024, 'ideographDigital')     // → "二〇二四"
 *   formatNumber(101, 'chineseLegalSimplified')// → "壹佰零壹"
 */
export function formatNumber(n: number, numFmt: string): string {
  // none / bullet：renderer 直接用 lvlText、不該 call 這裡；防禦回 ""
  if (numFmt === 'none' || numFmt === 'bullet') return '';

  if (!Number.isFinite(n)) return '';

  switch (numFmt) {
    case 'decimal':
      return String(n);
    case 'decimalZero':
      return n < 10 && n >= 0 ? '0' + n : String(n);

    case 'lowerLetter':
      return toBase26Letter(n, false);
    case 'upperLetter':
      return toBase26Letter(n, true);

    case 'lowerRoman':
      return toRoman(n).toLowerCase();
    case 'upperRoman':
      return toRoman(n);

    case 'ordinal':
      return toOrdinal(n);
    case 'ordinalText':
      return toOrdinalText(n);
    case 'cardinalText':
      return toCardinalText(n);

    case 'chineseCounting':
    case 'japaneseCounting':
    case 'taiwaneseCounting':
      return toChineseCounting(n);

    case 'chineseCountingThousand':
    case 'taiwaneseCountingThousand':
      return toChineseCountingThousand(n);

    case 'chineseLegalSimplified':
      return toChineseLegal(n);
    case 'japaneseLegal':
      return toJapaneseLegal(n);

    case 'ideographDigital':
    case 'taiwaneseDigital':
      return toIdeographDigital(n);

    case 'japaneseDigitalTenThousand':
      return toJapaneseDigitalTenThousand(n);

    case 'ideographZodiac':
      return toZodiac(n);
    case 'ideographTraditional':
      return toHeavenlyStem(n);

    case 'iroha':
      return toIroha(n, false);
    case 'irohaFullWidth':
      return toIroha(n, true);
    case 'aiueo':
      return toAiueo(n, false);
    case 'aiueoFullWidth':
      return toAiueo(n, true);

    default:
      // 未知 format fallback to decimal — 不 throw、保 render 不斷
      return String(n);
  }
}

/**
 * 展開 lvlText 模板字串（如 `"%1.%2."`）為實際序號（如 `"1.2."`）。
 *
 * @param template       OOXML w:lvlText/@val 字串
 * @param counters       各 level 的目前計數值（counters[0] = ilvl 0 的計數、counters[1] = ilvl 1 的計數 ...）
 * @param numFmts        各 level 的 numFmt 字串（與 counters 同長、由 NumberingMap 提供）
 * @returns 展開後字串；缺對應 counter / numFmt 時該 placeholder 留空
 *
 * @example
 *   expandLvlText("%1.%2.", [3, 2], ['decimal', 'lowerLetter']) // → "3.b."
 *   expandLvlText("第%1章", [5], ['chineseCounting'])           // → "第五章"
 */
export function expandLvlText(
  template: string,
  counters: number[],
  numFmts: string[],
): string {
  // 用單一 regex 取代 %1, %2, ..., %9 placeholder
  return template.replace(/%([1-9])/g, (_, digit: string) => {
    const idx = parseInt(digit, 10) - 1; // %1 → counters[0]
    const counter = counters[idx];
    const fmt = numFmts[idx];
    if (counter === undefined || fmt === undefined) return '';
    return formatNumber(counter, fmt);
  });
}

// ── 西式格式 ────────────────────────────────────────────────────────────────

/** base-26：1=a, 26=z, 27=aa, 52=az, 53=ba, … */
function toBase26Letter(n: number, uppercase: boolean): string {
  if (n < 1) return uppercase ? 'A' : 'a';
  let v = Math.floor(n);
  let out = '';
  const base = uppercase ? 65 : 97; // 'A' or 'a'
  while (v > 0) {
    const rem = (v - 1) % 26;
    out = String.fromCharCode(base + rem) + out;
    v = Math.floor((v - 1) / 26);
  }
  return out;
}

const ROMAN_PAIRS: ReadonlyArray<readonly [number, string]> = [
  [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
  [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
  [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
];

/** 1–3999；範圍外回 decimal */
function toRoman(n: number): string {
  if (n < 1 || n > 3999) return String(n);
  let v = Math.floor(n);
  let out = '';
  for (const [val, sym] of ROMAN_PAIRS) {
    while (v >= val) {
      out += sym;
      v -= val;
    }
  }
  return out;
}

function toOrdinal(n: number): string {
  const v = Math.floor(n);
  const mod100 = v % 100;
  if (mod100 >= 11 && mod100 <= 13) return v + 'th';
  switch (v % 10) {
    case 1: return v + 'st';
    case 2: return v + 'nd';
    case 3: return v + 'rd';
    default: return v + 'th';
  }
}

const ORDINAL_TEXT: ReadonlyArray<string> = [
  '', 'first', 'second', 'third', 'fourth', 'fifth',
  'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
  'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth',
  'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth',
];

function toOrdinalText(n: number): string {
  const v = Math.floor(n);
  return v >= 1 && v <= 20 ? ORDINAL_TEXT[v] : toOrdinal(v);
}

const CARDINAL_TEXT: ReadonlyArray<string> = [
  '', 'one', 'two', 'three', 'four', 'five',
  'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
  'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
];

function toCardinalText(n: number): string {
  const v = Math.floor(n);
  return v >= 1 && v <= 20 ? CARDINAL_TEXT[v] : String(v);
}

// ── 中文格式 ────────────────────────────────────────────────────────────────

const CN_DIGITS: ReadonlyArray<string> = ['〇', '一', '二', '三', '四', '五', '六', '七', '八', '九'];

/**
 * 繁體中文計數寫法（1–9999）：
 *   1=一, 10=十, 11=十一, 20=二十, 99=九十九,
 *   100=一百, 101=一百零一, 110=一百一十, 999=九百九十九,
 *   1000=一千, 9999=九千九百九十九
 *
 * 範圍外 fallback decimal。
 */
function toChineseCounting(n: number): string {
  if (n < 0) return '負' + toChineseCounting(-n);
  if (n === 0) return CN_DIGITS[0];
  if (n >= 10000) return String(n); // 超出 4 位 fallback decimal（萬以上由 chineseCountingThousand 處理）

  const v = Math.floor(n);
  if (v < 10) return CN_DIGITS[v];

  // 10–19：十、十一、…、十九（無「一十」前綴）
  if (v < 20) return v === 10 ? '十' : '十' + CN_DIGITS[v - 10];

  // 20–99
  if (v < 100) {
    const tens = Math.floor(v / 10);
    const ones = v % 10;
    return CN_DIGITS[tens] + '十' + (ones === 0 ? '' : CN_DIGITS[ones]);
  }

  // 100–999
  if (v < 1000) {
    const h = Math.floor(v / 100);
    const rest = v % 100;
    if (rest === 0) return CN_DIGITS[h] + '百';
    // 101–109：一百零一
    if (rest < 10) return CN_DIGITS[h] + '百零' + CN_DIGITS[rest];
    // 110, 120 ..：一百一十；111–199 → 一百一十一
    return CN_DIGITS[h] + '百' + toChineseCounting(rest);
  }

  // 1000–9999
  const k = Math.floor(v / 1000);
  const rest = v % 1000;
  if (rest === 0) return CN_DIGITS[k] + '千';
  if (rest < 100) return CN_DIGITS[k] + '千零' + toChineseCounting(rest);
  return CN_DIGITS[k] + '千' + toChineseCounting(rest);
}

/**
 * 千分隔變體：相對於 chineseCounting，本變體不省略「零」、適用法律 / 正式文書。
 * Sprint 132 簡化為 alias to chineseCounting；如未來 fixture 出現差異再分流。
 */
function toChineseCountingThousand(n: number): string {
  return toChineseCounting(n);
}

const CN_LEGAL_DIGITS: ReadonlyArray<string> = [
  '零', '壹', '貳', '參', '肆', '伍', '陸', '柒', '捌', '玖',
];

/**
 * 中文法定大寫（繁體寫法）：
 *   1=壹, 10=拾, 11=拾壹, 100=壹佰, 1000=壹仟, 10000=壹萬
 *
 * 用於支票、財報、法律文件防竄改。範圍 1–99999999（億以下）。
 */
function toChineseLegal(n: number): string {
  if (n < 0) return '負' + toChineseLegal(-n);
  if (n === 0) return CN_LEGAL_DIGITS[0];
  const v = Math.floor(n);

  if (v < 10) return CN_LEGAL_DIGITS[v];

  // 10–19：拾、拾壹…（同 chineseCounting 不寫「壹拾」）
  if (v < 20) return v === 10 ? '拾' : '拾' + CN_LEGAL_DIGITS[v - 10];

  if (v < 100) {
    const tens = Math.floor(v / 10);
    const ones = v % 10;
    return CN_LEGAL_DIGITS[tens] + '拾' + (ones === 0 ? '' : CN_LEGAL_DIGITS[ones]);
  }

  if (v < 1000) {
    const h = Math.floor(v / 100);
    const rest = v % 100;
    if (rest === 0) return CN_LEGAL_DIGITS[h] + '佰';
    if (rest < 10) return CN_LEGAL_DIGITS[h] + '佰零' + CN_LEGAL_DIGITS[rest];
    return CN_LEGAL_DIGITS[h] + '佰' + toChineseLegal(rest);
  }

  if (v < 10000) {
    const k = Math.floor(v / 1000);
    const rest = v % 1000;
    if (rest === 0) return CN_LEGAL_DIGITS[k] + '仟';
    if (rest < 100) return CN_LEGAL_DIGITS[k] + '仟零' + toChineseLegal(rest);
    return CN_LEGAL_DIGITS[k] + '仟' + toChineseLegal(rest);
  }

  // 萬以上 — 簡化處理：直接 fallback decimal（超大金額罕用 ilvl 編號）
  return String(v);
}

/**
 * 日文法定大寫（與中文略異）：
 *   1=壱, 2=弐, 3=参, 10=拾, 100=百, 1000=千
 *
 * 日本對某些字使用簡化版（壱弐参）、其他字（肆伍）回退到普通寫法。
 * Sprint 132 簡化：用日文 1-3 + 普通 4-9、結構同 chineseLegal。
 */
const JP_LEGAL_DIGITS: ReadonlyArray<string> = [
  '零', '壱', '弐', '参', '四', '五', '六', '七', '八', '九',
];

function toJapaneseLegal(n: number): string {
  if (n < 0) return '負' + toJapaneseLegal(-n);
  if (n === 0) return JP_LEGAL_DIGITS[0];
  const v = Math.floor(n);
  if (v < 10) return JP_LEGAL_DIGITS[v];
  if (v < 20) return v === 10 ? '拾' : '拾' + JP_LEGAL_DIGITS[v - 10];
  if (v < 100) {
    const tens = Math.floor(v / 10);
    const ones = v % 10;
    return JP_LEGAL_DIGITS[tens] + '拾' + (ones === 0 ? '' : JP_LEGAL_DIGITS[ones]);
  }
  return String(v);
}

/**
 * ideographDigital：把 n 的每位數獨立轉為中文數字（不含「十百千」）。
 *
 *   1 → 一
 *   23 → 二三
 *   100 → 一〇〇
 *   2024 → 二〇二四
 *
 * 適用「壹零壹」式編號（如電話號碼、年份）。
 */
function toIdeographDigital(n: number): string {
  if (n < 0) return '負' + toIdeographDigital(-n);
  const v = Math.floor(Math.abs(n));
  return String(v).split('').map((d) => CN_DIGITS[parseInt(d, 10)] ?? d).join('');
}

/**
 * 日文 ten-thousand：使用「万」分隔。
 *   1 → 一, 10000 → 一万, 12345 → 一万二千三百四十五
 *
 * Sprint 132 簡化：n < 10000 同 chineseCounting；n ≥ 10000 加「万」前綴。
 */
function toJapaneseDigitalTenThousand(n: number): string {
  if (n < 0) return '負' + toJapaneseDigitalTenThousand(-n);
  const v = Math.floor(n);
  if (v < 10000) return toChineseCounting(v);
  const man = Math.floor(v / 10000);
  const rest = v % 10000;
  const manStr = toChineseCounting(man) + '万';
  if (rest === 0) return manStr;
  return manStr + toChineseCounting(rest);
}

// ── 循環序列 ────────────────────────────────────────────────────────────────

const ZODIAC: ReadonlyArray<string> = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'];

function toZodiac(n: number): string {
  if (n < 1) return ZODIAC[0];
  return ZODIAC[(Math.floor(n) - 1) % 12];
}

const HEAVENLY_STEM: ReadonlyArray<string> = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸'];

function toHeavenlyStem(n: number): string {
  if (n < 1) return HEAVENLY_STEM[0];
  return HEAVENLY_STEM[(Math.floor(n) - 1) % 10];
}

const IROHA_HW: ReadonlyArray<string> = [
  'い', 'ろ', 'は', 'に', 'ほ', 'へ', 'と', 'ち', 'り', 'ぬ',
  'る', 'を', 'わ', 'か', 'よ', 'た', 'れ', 'そ', 'つ', 'ね',
  'な', 'ら', 'む', 'う', 'ゐ', 'の', 'お', 'く', 'や', 'ま',
  'け', 'ふ', 'こ', 'え', 'て', 'あ', 'さ', 'き', 'ゆ', 'め',
  'み', 'し', 'ゑ', 'ひ', 'も', 'せ', 'す',
];

/**
 * いろは 47 字假名循環。半形（katakana）目前 fall through to 平假名（OOXML 用
 * 全形 / 半形 hint 但實務上 fixture 罕見、defer）。
 */
function toIroha(n: number, _fullWidth: boolean): string {
  if (n < 1) return IROHA_HW[0];
  return IROHA_HW[(Math.floor(n) - 1) % IROHA_HW.length];
}

const AIUEO_HW: ReadonlyArray<string> = [
  'あ', 'い', 'う', 'え', 'お', 'か', 'き', 'く', 'け', 'こ',
  'さ', 'し', 'す', 'せ', 'そ', 'た', 'ち', 'つ', 'て', 'と',
  'な', 'に', 'ぬ', 'ね', 'の', 'は', 'ひ', 'ふ', 'へ', 'ほ',
  'ま', 'み', 'む', 'め', 'も', 'や', 'ゆ', 'よ', 'ら', 'り',
  'る', 'れ', 'ろ', 'わ', 'を', 'ん',
];

function toAiueo(n: number, _fullWidth: boolean): string {
  if (n < 1) return AIUEO_HW[0];
  return AIUEO_HW[(Math.floor(n) - 1) % AIUEO_HW.length];
}
