/**
 * Sprint 277 — Phase 6 Layout Engine MVP spike：Greedy LineBreaker
 *
 * 驗證 Sprint 269/275 標的「Phase 2 API ready 銜接 Phase 6 自寫 Layout」聲明：
 * 消費 ShapingEngine.measureRun() 物理寬度（取代 ctx.measureText）做 greedy
 * line break。
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 *
 * 雙驗：本檔（vitest framework 路徑）+ scripts/verify_sprint277.mjs（standalone
 * Node 路徑、不依賴 vitest），WSL ENOMEM 時可走 standalone 驗證。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';
import { breakParagraph } from '../../static/src/core/ooxml/layout';

const FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT_PATH);

function makeEngine(): ShapingEngine {
  const engine = new ShapingEngine();
  engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH)));
  return engine;
}

describe.skipIf(!HAS_FONT)('Sprint 277 — Phase 6 LineBreaker MVP greedy break', () => {
  it('Single line：短文 + 大寬度 → 全部 fit 一行', async () => {
    const engine = makeEngine();
    const result = await breakParagraph(engine, {
      text: 'Hello world',
      availableWidthPt: 1000,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
    });
    expect(result.totalLines).toBe(1);
    expect(result.lines[0].text).toBe('Hello world');
    expect(result.lines[0].words).toEqual(['Hello', 'world']);
    expect(result.lines[0].widthPt).toBeGreaterThan(0);
    expect(result.maxLineWidthPt).toBe(result.lines[0].widthPt);
  });

  it('Multi-line greedy break：tight 寬度 → 多行', async () => {
    const engine = makeEngine();
    const result = await breakParagraph(engine, {
      text: 'The quick brown fox jumps over the lazy dog',
      availableWidthPt: 60,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
    });
    expect(result.totalLines).toBeGreaterThan(1);
    expect(result.totalLines).toBeLessThan(10);
    for (const line of result.lines) {
      if (line.words.length >= 2) {
        expect(line.widthPt).toBeLessThanOrEqual(60);
      }
    }
    expect(result.lines.map((l) => l.text).join(' ')).toBe(
      'The quick brown fox jumps over the lazy dog',
    );
  });

  it('Overlong word force-fit：單字 > availableWidth → 自佔一行', async () => {
    const engine = makeEngine();
    const result = await breakParagraph(engine, {
      text: 'short supercalifragilisticexpialidocious end',
      availableWidthPt: 50,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
    });
    expect(result.totalLines).toBeGreaterThanOrEqual(3);
    const overlong = result.lines.find((l) =>
      l.words.length === 1 && l.words[0] === 'supercalifragilisticexpialidocious',
    );
    expect(overlong).toBeDefined();
    expect(overlong!.widthPt).toBeGreaterThan(50);
  });

  it('Empty / whitespace-only text → 0 lines', async () => {
    const engine = makeEngine();
    const empty = await breakParagraph(engine, {
      text: '',
      availableWidthPt: 100,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
    });
    expect(empty.totalLines).toBe(0);
    expect(empty.maxLineWidthPt).toBe(0);

    const spaces = await breakParagraph(engine, {
      text: '   ',
      availableWidthPt: 100,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
    });
    expect(spaces.totalLines).toBe(0);
  });

  it('Same paragraph + larger sizePt → 行數變多（measureRun 隨 size 線性）', async () => {
    const engine = makeEngine();
    const text = 'The quick brown fox jumps over the lazy dog';
    const tight = await breakParagraph(engine, {
      text,
      availableWidthPt: 120,
      fontFamily: 'DejaVuSans',
      sizePt: 10,
    });
    const big = await breakParagraph(engine, {
      text,
      availableWidthPt: 120,
      fontFamily: 'DejaVuSans',
      sizePt: 20,
    });
    expect(big.totalLines).toBeGreaterThanOrEqual(tight.totalLines);
  });

  it('Injected spaceWidthPt：可注入避 wasm shape（測試友好）', async () => {
    const engine = makeEngine();
    const result = await breakParagraph(engine, {
      text: 'Hello world test',
      availableWidthPt: 100,
      fontFamily: 'DejaVuSans',
      sizePt: 12,
      spaceWidthPt: 3.0,
    });
    expect(result.totalLines).toBeGreaterThanOrEqual(1);
    expect(result.lines.map((l) => l.text).join(' ')).toBe('Hello world test');
  });
});
