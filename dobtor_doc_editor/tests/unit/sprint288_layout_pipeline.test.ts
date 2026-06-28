/**
 * Sprint 288 — Phase 2.1-2.3 整合 façade `LayoutPipeline`。
 *
 * 驗證單一入口能消化 Phase 2 完整 stack：
 *   - readFontMetrics (opentype.js)
 *   - resolveOoxmlLineHeight (Sprint 267 OOXML rule)
 *   - baselineOffsetPt
 *   - breakParagraph (Sprint 277 LineBreaker)
 *   - loadShapingFontWithChain (Sprint 280)
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 *
 * 紀律 #18 scope-down：façade 不接 canvas-editor；測試只驗 API contract、
 * 不驗 render。Phase 6 完整 Layout 才會擴充 mixed run / kerning / Knuth-Plass。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';
import {
  layoutParagraph,
  layoutParagraphWithFontChain,
} from '../../static/src/core/ooxml/layout';

const FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT_PATH);
const FONT_BYTES: Uint8Array | undefined = HAS_FONT
  ? new Uint8Array(readFileSync(FONT_PATH))
  : undefined;

function makeEngine(): ShapingEngine {
  if (!FONT_BYTES) throw new Error('font missing');
  const engine = new ShapingEngine();
  engine.loadFont('DejaVuSans', FONT_BYTES);
  return engine;
}

describe.skipIf(!HAS_FONT)('Sprint 288 — LayoutPipeline.layoutParagraph', () => {
  it('整合 layout：拿到 lines + lineHeightPt + baselineOffsetPt + fontMetrics', async () => {
    const engine = makeEngine();
    const result = await layoutParagraph(engine, {
      text: 'Hello world this is a longer paragraph for layout pipeline test',
      availableWidthPt: 200,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
    });
    // lines
    expect(result.totalLines).toBeGreaterThan(0);
    expect(result.maxLineWidthPt).toBeGreaterThan(0);
    expect(result.maxLineWidthPt).toBeLessThanOrEqual(200);
    // metrics
    expect(result.fontMetrics.unitsPerEm).toBeGreaterThan(0);
    expect(result.fontMetrics.ascender).toBeGreaterThan(0);
    expect(result.fontMetrics.descender).toBeGreaterThan(0);
    // line height
    expect(result.lineHeight.rule).toBe('natural'); // 無 lineRule
    expect(result.lineHeightPt).toBeGreaterThan(0);
    expect(result.lineHeightPt).toBe(result.lineHeight.heightPt);
    // baseline
    expect(result.baselineOffsetPt).toBeGreaterThan(0);
    expect(result.baselineOffsetPt).toBeLessThan(result.lineHeightPt);
  });

  it('lineRule="auto" multiplier=2.0 → 行高為 natural × 2', async () => {
    const engine = makeEngine();
    const natural = await layoutParagraph(engine, {
      text: 'Hello',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
    });
    const double = await layoutParagraph(engine, {
      text: 'Hello',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
      lineRule: 'auto',
      lineValue: 2.0,
    });
    expect(double.lineHeight.rule).toBe('auto');
    expect(double.lineHeight.lineValue).toBe(2.0);
    expect(double.lineHeightPt).toBeCloseTo(natural.lineHeightPt * 2, 2);
  });

  it('lineRule="exact" value=30pt → 行高固定 30pt（忽略 natural）', async () => {
    const engine = makeEngine();
    const result = await layoutParagraph(engine, {
      text: 'Hi',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 24, // natural 應 > 30pt
      fontBytes: FONT_BYTES!,
      lineRule: 'exact',
      lineValue: 30,
    });
    expect(result.lineHeight.rule).toBe('exact');
    expect(result.lineHeightPt).toBe(30);
  });

  it('lineRule="atLeast" value < natural → 取 natural（下限不觸發）', async () => {
    const engine = makeEngine();
    const result = await layoutParagraph(engine, {
      text: 'Hi',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 24,
      fontBytes: FONT_BYTES!,
      lineRule: 'atLeast',
      lineValue: 5, // 應遠小於 natural
    });
    expect(result.lineHeight.rule).toBe('atLeast');
    expect(result.lineHeightPt).toBeGreaterThan(5);
    expect(result.lineHeightPt).toBe(result.lineHeight.naturalHeightPt);
  });

  it('lineRule="atLeast" value > natural → 取 value（下限觸發）', async () => {
    const engine = makeEngine();
    const result = await layoutParagraph(engine, {
      text: 'Hi',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
      lineRule: 'atLeast',
      lineValue: 100, // 應遠大於 12pt 自然行高
    });
    expect(result.lineHeight.rule).toBe('atLeast');
    expect(result.lineHeightPt).toBe(100);
  });

  it('空字串 → lines 為空陣列、maxLineWidthPt = 0', async () => {
    const engine = makeEngine();
    const result = await layoutParagraph(engine, {
      text: '',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
    });
    expect(result.totalLines).toBe(0);
    expect(result.maxLineWidthPt).toBe(0);
    // metrics 仍能讀到（與字串無關）
    expect(result.fontMetrics.unitsPerEm).toBeGreaterThan(0);
  });

  it('spaceWidthPt 注入 → 加速、結果一致', async () => {
    const engine = makeEngine();
    const noInject = await layoutParagraph(engine, {
      text: 'Hello world foo bar',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
    });
    // 用 noInject 量得的 space 寬度當注入值
    const spaceWidth = await engine.measureRun(' ', 'DejaVuSans', 12).then((m) => m.widthPt);
    const withInject = await layoutParagraph(engine, {
      text: 'Hello world foo bar',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      fontBytes: FONT_BYTES!,
      spaceWidthPt: spaceWidth,
    });
    expect(withInject.maxLineWidthPt).toBeCloseTo(noInject.maxLineWidthPt, 3);
    expect(withInject.totalLines).toBe(noInject.totalLines);
  });
});

describe.skipIf(!HAS_FONT)('Sprint 288 — LayoutPipeline.layoutParagraphWithFontChain', () => {
  // Mock fetch：給特定 URL 回 DejaVuSans bytes、其他 URL throw（模擬 fallback）
  const FAKE_URL = 'https://fonts.test/dejavu.ttf';

  function fakeFetch(targetUrl: string): typeof fetch {
    return (async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === targetUrl) {
        return new Response(FONT_BYTES!, { status: 200 });
      }
      return new Response(null, { status: 404 });
    }) as typeof fetch;
  }

  it('primary 成功 → 不走 fallback、layout 完整、fontLoad.attemptedCount === 1', async () => {
    const engine = new ShapingEngine();
    const result = await layoutParagraphWithFontChain(engine, {
      text: 'Hello world',
      availableWidthPt: 1000,
      sizePt: 12,
      primary: { family: 'DejaVuSans', url: FAKE_URL },
      fallbacks: [],
      fetchImpl: fakeFetch(FAKE_URL),
    });
    expect(result.fontLoad.loadedAs).toBe('DejaVuSans');
    expect(result.fontLoad.attemptedCount).toBe(1);
    expect(result.totalLines).toBe(1);
    expect(result.lineHeightPt).toBeGreaterThan(0);
  });

  it('primary 失敗 + fallback 成功 → warn 觸發、attemptedCount === 2', async () => {
    const engine = new ShapingEngine();
    const warnings: string[] = [];
    const result = await layoutParagraphWithFontChain(engine, {
      text: 'Hello',
      availableWidthPt: 1000,
      sizePt: 12,
      primary: { family: 'NotExist', url: 'https://nope/missing.ttf' },
      fallbacks: [{ family: 'DejaVuSansFallback', url: FAKE_URL }],
      fetchImpl: fakeFetch(FAKE_URL),
      warn: (m) => warnings.push(m),
    });
    // primary family 仍是 NotExist（with fallback bytes 載入到 primary 名下）
    expect(result.fontLoad.loadedAs).toBe('NotExist');
    expect(result.fontLoad.attemptedCount).toBe(2);
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toContain('fallback');
    expect(result.totalLines).toBe(1);
  });
});
