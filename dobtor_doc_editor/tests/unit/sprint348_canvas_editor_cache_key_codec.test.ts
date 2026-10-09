/**
 * Sprint 348 — ① deeper¹²：CanvasEditorCacheKeyCodec。
 *
 * 補 Sprint 338 keyFor 的「text 含 | 會 mangle」gap：round-trip safe escape。
 *
 * 紀律 #18：純字串 codec；不接 production canvas-editor。
 */
import { describe, expect, it } from 'vitest';

import {
  encodeCacheKey,
  decodeCacheKey,
  isValidCacheKey,
} from '../../static/src/core/ooxml/font/CanvasEditorCacheKeyCodec';

// ── encode / decode round-trip ─────────────────────────────────────

describe('Sprint 348 — encode/decode round-trip', () => {
  it('一般欄位', () => {
    const parts = { family: 'Arial', sizePt: 10, text: 'hello' };
    const key = encodeCacheKey(parts);
    expect(decodeCacheKey(key)).toEqual(parts);
  });

  it('text 含 | → escape 後仍可還原', () => {
    const parts = { family: 'Arial', sizePt: 10, text: 'a|b|c' };
    const key = encodeCacheKey(parts);
    expect(decodeCacheKey(key)).toEqual(parts);
  });

  it('family 含 | → 可還原', () => {
    const parts = { family: 'Wei|rd Font', sizePt: 12, text: 'x' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });

  it('text 含跳脫字元 \\ → 可還原', () => {
    const parts = { family: 'Arial', sizePt: 10, text: 'back\\slash' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });

  it('text 含 \\| 混合 → 可還原', () => {
    const parts = { family: 'A', sizePt: 10, text: 'a\\|b\\\\c|d' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });

  it('空 text / 空 family', () => {
    const parts = { family: '', sizePt: 10, text: '' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });

  it('CJK text', () => {
    const parts = { family: '微軟正黑體', sizePt: 12, text: '中文字|測試' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });

  it('小數 sizePt', () => {
    const parts = { family: 'Arial', sizePt: 10.5, text: 'x' };
    expect(decodeCacheKey(encodeCacheKey(parts))).toEqual(parts);
  });
});

// ── decode malformed ───────────────────────────────────────────────

describe('Sprint 348 — decodeCacheKey malformed', () => {
  it('欄位數 != 3 → null', () => {
    expect(decodeCacheKey('only|two')).toBeNull();
    expect(decodeCacheKey('a|b|c|d')).toBeNull();
    expect(decodeCacheKey('single')).toBeNull();
  });

  it('sizePt 非數 → null', () => {
    expect(decodeCacheKey('Arial|notanumber|hi')).toBeNull();
  });

  it('sizePt = Infinity 字串 → null', () => {
    expect(decodeCacheKey('Arial|Infinity|hi')).toBeNull();
  });

  it('escaped 分隔不算欄位邊界', () => {
    // 'a\|b' 是單一 family 欄位（含字面 |），整體只有 1 欄 → null
    expect(decodeCacheKey('a\\|b')).toBeNull();
  });
});

// ── isValidCacheKey ────────────────────────────────────────────────

describe('Sprint 348 — isValidCacheKey', () => {
  it('canonical encode 結果 → true', () => {
    const key = encodeCacheKey({ family: 'Arial', sizePt: 10, text: 'a|b' });
    expect(isValidCacheKey(key)).toBe(true);
  });

  it('malformed → false', () => {
    expect(isValidCacheKey('only|two')).toBe(false);
  });

  it('非 canonical sizePt（10.0）→ false（與 re-encode 不一致）', () => {
    expect(isValidCacheKey('Arial|10.0|hi')).toBe(false);
  });
});

// ── 與 Sprint 338 keyFor 對照（無特殊字元時一致）────────────────────

describe('Sprint 348 — 無特殊字元時與簡單串接同形', () => {
  it('普通 key 與 family|sizePt|text 同字串', () => {
    expect(encodeCacheKey({ family: 'Arial', sizePt: 10, text: 'hi' })).toBe('Arial|10|hi');
  });
});
