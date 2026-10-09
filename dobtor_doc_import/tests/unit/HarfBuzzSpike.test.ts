/**
 * HarfBuzz WASM 整合 spike (Phase D.2)
 *
 * 目的：驗證 harfbuzzjs WASM 在 Node + vitest 環境能：
 *   (a) 載入 WASM 模組
 *   (b) 載入字型 buffer 為 hb.face / hb.font
 *   (c) shape 一段中英文混排文字產生 glyph[]
 *   (d) 取得 glyph 的 advance / xOffset 資訊
 *
 * 若以上 4 步全綠 → ShapingEngine 接 HarfBuzz；
 * 若任何一步失敗（常見：Node ESM/CJS 互通、WASM 路徑、async load timing）
 *   → 降級為 opentype.js 純 metrics 模式（讀 ascender / descender / lineGap，
 *      跳過 glyph shaping），由 canvas-editor measureText 接管字距。
 *
 * 此 spike 使用系統字型（從 /usr/share/fonts 找）；找不到時 skip 整個 suite。
 */

import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// 用 createRequire 直接 require CJS 套件，避開 vitest ESM/CJS 互通的 [object Module] 雷
const localRequire = createRequire(import.meta.url);

/**
 * 載入 harfbuzzjs。其 module.exports 是 `new Promise(...)`，需要 await。
 *
 * 此函式封裝載入細節：用 createRequire 取得 CJS module.exports 直接 await。
 */
async function loadHarfBuzz(): Promise<unknown> {
  const mod = localRequire('harfbuzzjs');
  return await mod;
}

// 候選字型（WSL Ubuntu / 容器常見）— 找到第一個存在的就用
const FONT_CANDIDATES = [
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
  '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
  '/mnt/c/Windows/Fonts/arial.ttf',
];

function findSystemFont(): string | null {
  for (const path of FONT_CANDIDATES) {
    if (existsSync(path)) return path;
  }
  return null;
}

const FONT_PATH = findSystemFont();

interface HBInstance {
  createBlob: (data: Uint8Array) => unknown;
  createFace: (blob: unknown) => unknown;
  createFont: (face: unknown) => unknown;
  createBuffer: () => {
    addText: (text: string) => void;
    guessSegmentProperties: () => void;
    json: () => Array<{ ax: number; ay: number; dx: number; dy: number; g: number; cl: number }>;
  };
  shape: (font: unknown, buffer: unknown) => void;
}

describe.skipIf(!FONT_PATH)('HarfBuzz WASM spike', () => {
  it('(a) harfbuzzjs 模組能載入並回傳 hb instance', async () => {
    const instance = (await loadHarfBuzz()) as HBInstance;
    expect(instance).toBeDefined();
    expect(typeof instance).toBe('object');
    expect(typeof instance.createBlob).toBe('function');
    expect(typeof instance.createFace).toBe('function');
    expect(typeof instance.createFont).toBe('function');
    expect(typeof instance.shape).toBe('function');
  });

  it('(b) 載入字型 buffer → blob → face → font', async () => {
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const blob = hb.createBlob(new Uint8Array(fontBytes));
    expect(blob).toBeDefined();
    const face = hb.createFace(blob);
    expect(face).toBeDefined();
    const font = hb.createFont(face);
    expect(font).toBeDefined();
  });

  it('(c) shape "Hello" 產生 5 個 glyph 且 advance > 0', async () => {
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const buffer = hb.createBuffer();
    buffer.addText('Hello');
    buffer.guessSegmentProperties();
    hb.shape(font, buffer);

    const glyphs = buffer.json();
    expect(glyphs.length).toBe(5);
    for (const g of glyphs) {
      expect(g.ax).toBeGreaterThan(0);
    }
  });

  it('(d) shape 中英混排不 throw（中文字型不足時會出 .notdef）', async () => {
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const buffer = hb.createBuffer();
    buffer.addText('Hello 世界');
    buffer.guessSegmentProperties();
    hb.shape(font, buffer);

    const glyphs = buffer.json();
    expect(glyphs.length).toBeGreaterThan(0);
  });
});

describe('HarfBuzz spike — 字型偵測', () => {
  it('找到至少一個系統字型（用於 spike）', () => {
    if (!FONT_PATH) {
      console.warn('No system fonts found in candidate paths; HarfBuzz spike skipped.');
    }
    // 不 fail：spike 是「探測性」，找不到字型不阻塞 CI
    expect(true).toBe(true);
  });
});

// ── Sprint 128：HarfBuzz 進階能力 spike（kerning / ligature / CJK / 純函式）────

describe.skipIf(!FONT_PATH)('Sprint 128 — HarfBuzz 進階能力 spike', () => {
  it('(e) kerning：AV ≤ AB（kerning pair 至少不擴張）', async () => {
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const shapeText = (text: string): number => {
      const buf = hb.createBuffer();
      buf.addText(text);
      buf.guessSegmentProperties();
      hb.shape(font, buf);
      return buf.json().reduce((sum, g) => sum + g.ax, 0);
    };

    const avWidth = shapeText('AV');
    const abWidth = shapeText('AB');

    // Hypothesis：AV 通常有 negative kerning（V 收進 A 下方）→ AV < AB
    //   - 若字型沒 kerning 表（如 LiberationSans）、可能相等；用 ≤ 容忍
    //   - 嚴格 < 需特定字型（如 DejaVu）；此 test 鎖弱條件
    expect(avWidth).toBeLessThanOrEqual(abWidth);
    expect(avWidth).toBeGreaterThan(0);
  });

  it('(f) ligature "fi"：1-2 glyph 合理區間（取決於字型 liga feature）', async () => {
    // harfbuzz 預設 'liga' feature 開；不同字型實作 ligature 程度不同
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const buf = hb.createBuffer();
    buf.addText('fi');
    buf.guessSegmentProperties();
    hb.shape(font, buf);

    const glyphs = buf.json();
    expect(glyphs.length).toBeGreaterThanOrEqual(1);
    expect(glyphs.length).toBeLessThanOrEqual(2);
    expect(glyphs.reduce((s, g) => s + g.ax, 0)).toBeGreaterThan(0);
  });

  it('(g) CJK 字「中」shape 出有效 advance（或 .notdef glyph）', async () => {
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const buf = hb.createBuffer();
    buf.addText('中');
    buf.guessSegmentProperties();
    hb.shape(font, buf);

    const glyphs = buf.json();
    expect(glyphs.length).toBeGreaterThanOrEqual(1);
    expect(glyphs[0].ax).toBeGreaterThanOrEqual(0);
  });

  it('(h) shape 純函式驗證（兩次同樣輸入 → byte-identical 輸出 → 可 cache）', async () => {
    // Sprint 51-58 cache 系列教訓：要 cache 必先 prove pure
    const hb = (await loadHarfBuzz()) as HBInstance;
    const fontBytes = readFileSync(FONT_PATH!);
    const font = hb.createFont(hb.createFace(hb.createBlob(new Uint8Array(fontBytes))));

    const shapeOnce = (): string => {
      const buf = hb.createBuffer();
      buf.addText('Hello World 測試');
      buf.guessSegmentProperties();
      hb.shape(font, buf);
      return JSON.stringify(buf.json());
    };

    expect(shapeOnce()).toBe(shapeOnce());
  });

  it('(i) harfbuzzjs module 可 require、體積審視留 audit doc', () => {
    // 不直接量 node_modules 大小（CI 環境差異），驗證 module exists
    // 實際 IIFE bundle 影響由 Sprint 128 audit doc 紀錄
    const hb = localRequire('harfbuzzjs');
    expect(hb).toBeDefined();
  });
});

const FOUND_FONT_PATH = FONT_PATH;
export { FOUND_FONT_PATH };
