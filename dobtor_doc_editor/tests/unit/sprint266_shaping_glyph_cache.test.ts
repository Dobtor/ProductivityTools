/**
 * Sprint 266 — Phase 2 ShapingEngine Glyph cache + 統計 / 清除 / 容量控制
 *
 * 規畫書 §Phase 2 對應：Glyph 快取（cache shaped glyphs by per-prop key）
 *
 * 測試重點：
 *   - cache hit/miss 計數正確
 *   - 同 key 第二次秒回（同 glyph[] 引用）
 *   - 不同 options 不互相 cache（features 變動 → new entry）
 *   - clear() 重置 stats
 *   - setShapeCacheMaxEntries(n) FIFO 淘汰超量
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';

const FONT_CANDIDATES_LATIN = [
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
];
function findFont(c: string[]): string | null {
  for (const p of c) if (existsSync(p)) return p;
  return null;
}
const FONT_PATH = findFont(FONT_CANDIDATES_LATIN);
const HAS_FONT = FONT_PATH !== null;

describe.skipIf(!HAS_FONT)('Sprint 266 — ShapingEngine glyph cache', () => {
  it('第一次 shape 是 miss、第二次同 key 是 hit、stats 對齊', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));
    expect(engine.getCacheStats().hits).toBe(0);
    expect(engine.getCacheStats().misses).toBe(0);

    const first = await engine.shape('Hello', 'DejaVuSans', 12);
    expect(engine.getCacheStats().hits).toBe(0);
    expect(engine.getCacheStats().misses).toBe(1);
    expect(engine.getCacheStats().entries).toBe(1);

    const second = await engine.shape('Hello', 'DejaVuSans', 12);
    expect(engine.getCacheStats().hits).toBe(1);
    expect(engine.getCacheStats().misses).toBe(1);
    expect(engine.getCacheStats().entries).toBe(1);

    // 同 reference（cache 命中時直接回原 array、不重新建立）
    expect(second).toBe(first);
  });

  it('不同 text / sizePt / features / script 各自獨立 entry', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));

    await engine.shape('A', 'DejaVuSans', 12);
    await engine.shape('B', 'DejaVuSans', 12);
    expect(engine.getCacheStats().entries).toBe(2);

    await engine.shape('A', 'DejaVuSans', 24);
    expect(engine.getCacheStats().entries).toBe(3);

    await engine.shape('A', 'DejaVuSans', 12, { features: '-kern' });
    expect(engine.getCacheStats().entries).toBe(4);

    await engine.shape('A', 'DejaVuSans', 12, { script: 'latn', language: 'en', direction: 'ltr' });
    expect(engine.getCacheStats().entries).toBe(5);

    expect(engine.getCacheStats().misses).toBe(5);
    expect(engine.getCacheStats().hits).toBe(0);
  });

  it('hitRate 為 hits / (hits + misses)', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));
    expect(Number.isNaN(engine.getCacheStats().hitRate)).toBe(true);

    await engine.shape('A', 'DejaVuSans', 12);
    await engine.shape('A', 'DejaVuSans', 12);
    await engine.shape('A', 'DejaVuSans', 12);
    const stats = engine.getCacheStats();
    expect(stats.hits).toBe(2);
    expect(stats.misses).toBe(1);
    expect(stats.hitRate).toBeCloseTo(2 / 3, 6);
  });

  it('clearShapeCache 重置 entries + hits + misses（不影響字型載入）', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));
    await engine.shape('Hello', 'DejaVuSans', 12);
    await engine.shape('Hello', 'DejaVuSans', 12);
    expect(engine.getCacheStats().entries).toBe(1);
    expect(engine.getCacheStats().hits).toBe(1);
    expect(engine.getCacheStats().misses).toBe(1);

    engine.clearShapeCache();
    const cleared = engine.getCacheStats();
    expect(cleared.entries).toBe(0);
    expect(cleared.hits).toBe(0);
    expect(cleared.misses).toBe(0);

    // 字型仍載入、再 shape 仍 work
    const after = await engine.shape('Hello', 'DejaVuSans', 12);
    expect(after.length).toBeGreaterThan(0);
  });

  it('setShapeCacheMaxEntries 縮小容量 → FIFO 淘汰最早 entry', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));
    await engine.shape('A', 'DejaVuSans', 12);
    await engine.shape('B', 'DejaVuSans', 12);
    await engine.shape('C', 'DejaVuSans', 12);
    expect(engine.getCacheStats().entries).toBe(3);

    engine.setShapeCacheMaxEntries(2);
    expect(engine.getCacheStats().entries).toBe(2);

    // A 應被淘汰、再 shape A 視為 miss
    const beforeMisses = engine.getCacheStats().misses;
    await engine.shape('A', 'DejaVuSans', 12);
    expect(engine.getCacheStats().misses).toBe(beforeMisses + 1);
  });

  it('cache 滿時新 entry 觸發 FIFO 淘汰（內部 set 行為）', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));
    engine.setShapeCacheMaxEntries(3);

    await engine.shape('A', 'DejaVuSans', 12);
    await engine.shape('B', 'DejaVuSans', 12);
    await engine.shape('C', 'DejaVuSans', 12);
    expect(engine.getCacheStats().entries).toBe(3);

    // D 進來 → 淘汰最舊（A）；entries=[B,C,D]
    await engine.shape('D', 'DejaVuSans', 12);
    expect(engine.getCacheStats().entries).toBe(3);
    expect(engine.getCacheStats().misses).toBe(4);

    // B / C / D 仍 hit（先驗、避免 A miss 觸發 FIFO 連鎖淘汰）
    const beforeHits = engine.getCacheStats().hits;
    await engine.shape('B', 'DejaVuSans', 12);
    await engine.shape('C', 'DejaVuSans', 12);
    await engine.shape('D', 'DejaVuSans', 12);
    expect(engine.getCacheStats().hits).toBe(beforeHits + 3);

    // A 已被淘汰 → 再 shape A 視為 miss + 觸發 B 淘汰
    const beforeMisses = engine.getCacheStats().misses;
    await engine.shape('A', 'DejaVuSans', 12);
    expect(engine.getCacheStats().misses).toBe(beforeMisses + 1);
  });

  it('setShapeCacheMaxEntries 拒絕負數 / 非有限數', () => {
    const engine = new ShapingEngine();
    expect(() => engine.setShapeCacheMaxEntries(-1)).toThrow();
    expect(() => engine.setShapeCacheMaxEntries(Number.NaN)).toThrow();
    expect(() => engine.setShapeCacheMaxEntries(Infinity)).toThrow();
  });

  it('measureRun 也走 cache（共用同 shape backend）', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH!)));

    await engine.measureRun('Hello', 'DejaVuSans', 12);
    const after1 = engine.getCacheStats();
    expect(after1.misses).toBe(1);

    await engine.measureRun('Hello', 'DejaVuSans', 12);
    const after2 = engine.getCacheStats();
    expect(after2.hits).toBe(1);
    expect(after2.misses).toBe(1);
  });
});
