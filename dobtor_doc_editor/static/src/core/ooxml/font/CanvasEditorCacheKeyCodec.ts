/**
 * CanvasEditorCacheKeyCodec — Sprint 348。
 *
 * Sprint 338 CacheWarmer 的 `keyFor` 用 `family|sizePt|text` 串接、但留了 honest
 * gap：「text 含 `|` 不會 mangle（caller 自負）」。實務上 family 名稱或 text
 * 本身可能含 `|`（罕見但存在），導致 key 衝突或無法反解。
 *
 * 本 sprint 補 round-trip safe 的 codec：
 *   - encode：把 `|` 與跳脫字元 `\` escape 後串接
 *   - decode：反解回 { family, sizePt, text }
 *   - 保證 encode → decode 還原原值（含含 `|` / `\` 的字串）
 *
 * 紀律 #18 scope-down：
 *   - 純字串 codec；不接 production canvas-editor real path（紀律 #21）
 *   - 不做版本化（schema 用 Sprint 328 snapshot 那層）
 *   - sizePt 以十進位字串編碼、decode 時 parseFloat（caller 負責合法數值）
 *
 * 紀律 #21：純函式；caller 把 codec 接到 Sprint 343 coordinator / 338 warmer。
 */

export interface CacheKeyParts {
  family: string;
  sizePt: number;
  text: string;
}

const SEP = '|';
const ESC = '\\';

/**
 * Escape 單一欄位：`\` → `\\`、`|` → `\|`。
 */
function escapeField(s: string): string {
  let out = '';
  for (const ch of s) {
    if (ch === ESC) out += ESC + ESC;
    else if (ch === SEP) out += ESC + SEP;
    else out += ch;
  }
  return out;
}

/**
 * 把 escaped 字串切回欄位（依未跳脫的 `|` 分段）。
 */
function splitEscaped(encoded: string): string[] {
  const fields: string[] = [];
  let cur = '';
  let i = 0;
  while (i < encoded.length) {
    const ch = encoded[i];
    if (ch === ESC && i + 1 < encoded.length) {
      // 跳脫序列：取下一字元字面值
      cur += encoded[i + 1];
      i += 2;
      continue;
    }
    if (ch === SEP) {
      fields.push(cur);
      cur = '';
      i += 1;
      continue;
    }
    cur += ch;
    i += 1;
  }
  fields.push(cur);
  return fields;
}

/**
 * encode：round-trip safe 的 cache key。
 *
 * 格式：`escape(family)|sizePt|escape(text)`
 * sizePt 不含 `|` / `\`、不需 escape。
 */
export function encodeCacheKey(parts: CacheKeyParts): string {
  return `${escapeField(parts.family)}${SEP}${parts.sizePt}${SEP}${escapeField(parts.text)}`;
}

/**
 * decode：反解 key。
 *
 * - 欄位數不等於 3 → null（malformed）
 * - sizePt 非有限數 → null
 */
export function decodeCacheKey(key: string): CacheKeyParts | null {
  const fields = splitEscaped(key);
  if (fields.length !== 3) return null;
  const [family, sizeStr, text] = fields;
  const sizePt = Number(sizeStr);
  if (!Number.isFinite(sizePt)) return null;
  return { family, sizePt, text };
}

/**
 * Caller 想驗證一個 key 是否為合法 encode 結果（round-trip 一致）。
 */
export function isValidCacheKey(key: string): boolean {
  const parts = decodeCacheKey(key);
  if (!parts) return false;
  return encodeCacheKey(parts) === key;
}
