/**
 * Sprint 54 — ImageDecodeCache 單元測試
 *
 * 用 string sentinel 替代 HTMLImageElement（node 環境無 DOM），測 LRU 語意本身。
 * 真正 HTMLImageElement 整合走 puppeteer perf 驗證。
 */

import { describe, expect, it } from 'vitest';
import { ImageDecodeCache } from '../../static/src/core/cache/image_decode_cache';

function dataUrlOf(tag: string): string {
  return `data:image/png;base64,${tag}`;
}

describe('ImageDecodeCache — 基本 put/get', () => {
  it('miss 回 undefined、hit 回原值', () => {
    const c = new ImageDecodeCache<string>();
    expect(c.get('k1')).toBeUndefined();
    c.put('k1', 'imgA');
    expect(c.get('k1')).toBe('imgA');
  });

  it('stats 正確計數 hits 與 misses', () => {
    const c = new ImageDecodeCache<string>();
    c.put('k', 'v');
    c.get('k'); // hit
    c.get('k'); // hit
    c.get('nope'); // miss
    expect(c.stats()).toEqual({ hits: 2, misses: 1, size: 1 });
  });

  it('has 不影響 hits/misses 計數', () => {
    const c = new ImageDecodeCache<string>();
    c.put('k', 'v');
    c.has('k');
    c.has('nope');
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 1 });
  });

  it('clear() 重置 entries 與計數', () => {
    const c = new ImageDecodeCache<string>();
    c.put('k', 'v');
    c.get('k');
    c.get('nope');
    c.clear();
    expect(c.stats()).toEqual({ hits: 0, misses: 0, size: 0 });
    expect(c.get('k')).toBeUndefined();
  });
});

describe('ImageDecodeCache — LRU 淘汰', () => {
  it('超過 maxEntries 時淘汰最舊', () => {
    const c = new ImageDecodeCache<string>({ maxEntries: 3 });
    c.put('A', 'a');
    c.put('B', 'b');
    c.put('C', 'c');
    c.put('D', 'd'); // A 被淘汰
    expect(c.has('A')).toBe(false);
    expect(c.has('B')).toBe(true);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
  });

  it('get() 命中後 entry 推到最新端、避免被淘汰', () => {
    const c = new ImageDecodeCache<string>({ maxEntries: 3 });
    c.put('A', 'a');
    c.put('B', 'b');
    c.put('C', 'c');
    expect(c.get('A')).toBeDefined(); // touch A
    c.put('D', 'd'); // 應淘汰 B（現在最舊），A 不動
    expect(c.has('A')).toBe(true);
    expect(c.has('B')).toBe(false);
    expect(c.has('C')).toBe(true);
    expect(c.has('D')).toBe(true);
  });

  it('既存 key 重複 put 不增加 size、不觸發淘汰', () => {
    const c = new ImageDecodeCache<string>({ maxEntries: 2 });
    c.put('A', 'a');
    c.put('B', 'b');
    c.put('A', 'a2');
    expect(c.stats().size).toBe(2);
    expect(c.has('B')).toBe(true);
    expect(c.get('A')).toBe('a2');
  });

  it('maxEntries <= 0 throw', () => {
    expect(() => new ImageDecodeCache({ maxEntries: 0 })).toThrow();
    expect(() => new ImageDecodeCache({ maxEntries: -1 })).toThrow();
    expect(() => new ImageDecodeCache({ maxEntries: 1.5 })).toThrow();
  });
});

describe('ImageDecodeCache — dataURL 當 key', () => {
  it('相同 dataURL 視為同一 entry', () => {
    const c = new ImageDecodeCache<string>();
    const url = dataUrlOf('AAAA');
    c.put(url, 'img1');
    expect(c.get(url)).toBe('img1');
  });

  it('不同 dataURL 視為獨立 entry', () => {
    const c = new ImageDecodeCache<string>();
    c.put(dataUrlOf('AAAA'), 'img1');
    c.put(dataUrlOf('BBBB'), 'img2');
    expect(c.get(dataUrlOf('AAAA'))).toBe('img1');
    expect(c.get(dataUrlOf('BBBB'))).toBe('img2');
    expect(c.stats().size).toBe(2);
  });
});
