/**
 * Sprint 265 — Phase 2 ShapingEngine 擴充：Script/Language/Direction + features +
 * measureRun() 物理寬度量測（取代 ctx.measureText）
 *
 * 規畫書 §Phase 2 對應：
 *   - HarfBuzz WASM 整合（spike 已通過 Sprint 128、本 sprint 補完 ShapeOptions API）
 *   - Script & Language 偵測（detectScript / defaultLanguageForScript /
 *     defaultDirectionForScript）
 *   - kerning / liga feature 控制（'kern,liga' / '-kern' 等）
 *   - measureRun() 物理寬度（advance × sizePt / unitsPerEm）
 *
 * 系統字型依賴：DejaVuSans (Latin) + NotoSansCJK (CJK)；找不到時 skip。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import {
  ShapingEngine,
  detectScript,
  defaultLanguageForScript,
  defaultDirectionForScript,
} from '../../static/src/core/ooxml/font';

const FONT_CANDIDATES_LATIN = [
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/dejavu/DejaVuSans.ttf',
  '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
];
const FONT_CANDIDATES_CJK = [
  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
  '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
];

function findFont(candidates: string[]): string | null {
  for (const p of candidates) if (existsSync(p)) return p;
  return null;
}
const LATIN_PATH = findFont(FONT_CANDIDATES_LATIN);
const CJK_PATH = findFont(FONT_CANDIDATES_CJK);
const HAS_LATIN = LATIN_PATH !== null;
const HAS_CJK = CJK_PATH !== null;

describe('Sprint 265 — detectScript / defaultLanguage / defaultDirection（純函式、不需字型）', () => {
  it('ASCII 文字 → latn', () => {
    expect(detectScript('Hello, world!')).toBe('latn');
    expect(detectScript('123 abc XYZ')).toBe('latn');
  });
  it('CJK 統一漢字 → hani', () => {
    expect(detectScript('磺港溪')).toBe('hani');
    expect(detectScript('   工程進度報告')).toBe('hani'); // skip leading spaces
  });
  it('Hiragana / Katakana → hira / kana', () => {
    expect(detectScript('ひらがな')).toBe('hira');
    expect(detectScript('カタカナ')).toBe('kana');
  });
  it('Hangul → hang', () => {
    expect(detectScript('한국어')).toBe('hang');
  });
  it('Arabic → arab；Hebrew → hebr', () => {
    expect(detectScript('مرحبا')).toBe('arab');
    expect(detectScript('שלום')).toBe('hebr');
  });
  it('Devanagari / Thai → deva / thai', () => {
    expect(detectScript('नमस्ते')).toBe('deva');
    expect(detectScript('สวัสดี')).toBe('thai');
  });
  it('混排：取第一個非空白字元 script', () => {
    expect(detectScript('  Hello 世界')).toBe('latn'); // 第一字 H
    expect(detectScript('  世界 Hello')).toBe('hani'); // 第一字 世
  });
  it('defaultLanguageForScript：hani→zh-tw / arab→ar / latn→en', () => {
    expect(defaultLanguageForScript('hani')).toBe('zh-tw');
    expect(defaultLanguageForScript('arab')).toBe('ar');
    expect(defaultLanguageForScript('hebr')).toBe('he');
    expect(defaultLanguageForScript('thai')).toBe('th');
    expect(defaultLanguageForScript('latn')).toBe('en');
  });
  it('defaultDirectionForScript：arab/hebr→rtl、其餘→ltr', () => {
    expect(defaultDirectionForScript('arab')).toBe('rtl');
    expect(defaultDirectionForScript('hebr')).toBe('rtl');
    expect(defaultDirectionForScript('hani')).toBe('ltr');
    expect(defaultDirectionForScript('latn')).toBe('ltr');
  });
});

describe.skipIf(!HAS_LATIN)('Sprint 265 — ShapingEngine.measureRun（Latin、DejaVuSans）', () => {
  it('measureRun 回傳 widthPt > 0 + advancesPt 長度對應 glyphs', async () => {
    const engine = new ShapingEngine();
    const bytes = new Uint8Array(readFileSync(LATIN_PATH!));
    engine.loadFont('DejaVuSans', bytes);
    const metrics = await engine.measureRun('Hello, world!', 'DejaVuSans', 12);
    expect(metrics.widthPt).toBeGreaterThan(0);
    expect(metrics.glyphCount).toBeGreaterThanOrEqual('Hello, world!'.length - 2); // ligature 可能少
    expect(metrics.advancesPt.length).toBe(metrics.glyphCount);
    // 寬度應在合理範圍（12pt × 13 字 × ~0.5em ≈ 60-100pt）
    expect(metrics.widthPt).toBeGreaterThan(40);
    expect(metrics.widthPt).toBeLessThan(150);
  });

  it('measureRun 對短字串 vs 長字串：寬度單調遞增', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(LATIN_PATH!)));
    const short = await engine.measureRun('A', 'DejaVuSans', 12);
    const long = await engine.measureRun('AAAAAA', 'DejaVuSans', 12);
    expect(long.widthPt).toBeGreaterThan(short.widthPt);
    // 6 個 A 寬度應接近單 A × 6（kerning 對相同字母對效果有限）
    expect(long.widthPt).toBeGreaterThan(short.widthPt * 5);
    expect(long.widthPt).toBeLessThan(short.widthPt * 7);
  });

  it('sizePt 線性 scale：12pt vs 24pt 寬度 ~2 倍', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(LATIN_PATH!)));
    const m12 = await engine.measureRun('Hello', 'DejaVuSans', 12);
    const m24 = await engine.measureRun('Hello', 'DejaVuSans', 24);
    const ratio = m24.widthPt / m12.widthPt;
    expect(ratio).toBeGreaterThan(1.95);
    expect(ratio).toBeLessThan(2.05);
  });

  it('features 控制：-kern 關閉 kerning（部分字型對 AV 字距會差）', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(LATIN_PATH!)));
    const withKern = await engine.measureRun('AVAVAV', 'DejaVuSans', 24, { features: 'kern' });
    const withoutKern = await engine.measureRun('AVAVAV', 'DejaVuSans', 24, { features: '-kern' });
    // DejaVuSans 對 AV 有 kerning；關掉應該稍寬（差異很小、僅驗證不會 throw）
    expect(withKern.widthPt).toBeGreaterThan(0);
    expect(withoutKern.widthPt).toBeGreaterThan(0);
    expect(Math.abs(withoutKern.widthPt - withKern.widthPt)).toBeLessThan(withKern.widthPt * 0.2);
  });
});

describe.skipIf(!HAS_CJK)('Sprint 265 — ShapingEngine.measureRun（CJK、NotoSansCJK）', () => {
  it('CJK 文字 measureRun 寬度 > 0 + 自動偵測 script hani', async () => {
    const engine = new ShapingEngine();
    const bytes = new Uint8Array(readFileSync(CJK_PATH!));
    engine.loadFont('NotoSansCJK', bytes);
    const metrics = await engine.measureRun('磺港溪工程', 'NotoSansCJK', 12);
    expect(metrics.widthPt).toBeGreaterThan(0);
    expect(metrics.glyphCount).toBe(5);
    // 等寬 CJK：5 字 × 12pt ≈ 60pt（容差 ±20%）
    expect(metrics.widthPt).toBeGreaterThan(48);
    expect(metrics.widthPt).toBeLessThan(72);
  });

  it('Explicit script="hani" + language="zh-tw" 與 auto-detect 結果一致', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('NotoSansCJK', new Uint8Array(readFileSync(CJK_PATH!)));
    const auto = await engine.measureRun('磺港溪', 'NotoSansCJK', 12);
    const explicit = await engine.measureRun('磺港溪', 'NotoSansCJK', 12, {
      script: 'hani', language: 'zh-tw', direction: 'ltr',
    });
    expect(explicit.widthPt).toBeCloseTo(auto.widthPt, 4);
  });
});
