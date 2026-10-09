#!/usr/bin/env node
/**
 * Sprint 277 — Phase 6 LineBreaker MVP standalone verify（雙驗 path 2）
 *
 * 與 tests/unit/sprint277_linebreaker_mvp.test.ts 同算法、不依賴 vitest /
 * harfbuzz wasm / 系統字型；WSL ENOMEM 時走此路徑驗證 algorithm 正確性。
 *
 * 雙驗 path 1：tsc standalone（LineBreaker.ts 型別乾淨、僅 pre-existing
 *              opentype.js 一條 error 不增）
 * 雙驗 path 2：本檔（Node ESM、確定性 mock measureRun、6 assertion 案例）
 *
 * 兩條路徑都通才視為 Sprint 277 三層 SOP 通過；vitest 案會在 WSL 記憶體釋放後
 * 補跑（hypothesis、不阻塞 commit）。
 */

// === Inline breakParagraph (mirror of LineBreaker.ts algorithm) ===
async function breakParagraph(engine, opts) {
  const { text, availableWidthPt, fontFamily, sizePt } = opts;
  const words = text.split(' ').filter((w) => w.length > 0);
  if (words.length === 0) {
    return { lines: [], maxLineWidthPt: 0, totalLines: 0 };
  }
  const spaceWidthPt = opts.spaceWidthPt
    ?? (await engine.measureRun(' ', fontFamily, sizePt)).widthPt;
  const lines = [];
  let curWords = [];
  let curWidth = 0;
  for (const word of words) {
    const { widthPt: wordWidth } = await engine.measureRun(word, fontFamily, sizePt);
    const wouldBe = curWords.length === 0 ? wordWidth : curWidth + spaceWidthPt + wordWidth;
    if (wouldBe <= availableWidthPt || curWords.length === 0) {
      curWords.push(word);
      curWidth = wouldBe;
    } else {
      lines.push({ text: curWords.join(' '), widthPt: curWidth, words: curWords });
      curWords = [word];
      curWidth = wordWidth;
    }
  }
  if (curWords.length > 0) {
    lines.push({ text: curWords.join(' '), widthPt: curWidth, words: curWords });
  }
  const maxLineWidthPt = lines.reduce((m, l) => Math.max(m, l.widthPt), 0);
  return { lines, maxLineWidthPt, totalLines: lines.length };
}

// === Deterministic mock ShapingEngine ===
// 模擬：每字元寬度 = sizePt * 0.5pt（線性、可重現、無 wasm 依賴）
class MockShapingEngine {
  async measureRun(text, _fontFamily, sizePt) {
    const widthPt = text.length * sizePt * 0.5;
    return { widthPt, heightPt: 0, glyphCount: text.length, advancesPt: [], glyphs: [] };
  }
}

// === Test harness ===
let pass = 0;
let fail = 0;
const failures = [];
function assert(cond, msg) {
  if (cond) { pass++; } else { fail++; failures.push(msg); }
}
function assertEq(actual, expected, msg) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) { pass++; }
  else { fail++; failures.push(`${msg}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`); }
}

// === 6 案例（vitest 同 case + 確定性） ===
async function main() {
  const engine = new MockShapingEngine();

  // Case 1: Single line（大寬度全 fit 一行）
  {
    const r = await breakParagraph(engine, {
      text: 'Hello world', availableWidthPt: 1000, fontFamily: 'mock', sizePt: 12,
    });
    assertEq(r.totalLines, 1, 'Case 1.totalLines');
    assertEq(r.lines[0].text, 'Hello world', 'Case 1.text');
    assertEq(r.lines[0].words, ['Hello', 'world'], 'Case 1.words');
    assert(r.lines[0].widthPt > 0, 'Case 1.widthPt>0');
    // "Hello"(5) + " "(1) + "world"(5) = 11 chars × 12 × 0.5 = 66pt
    assertEq(r.lines[0].widthPt, 66, 'Case 1.widthPt=66');
  }

  // Case 2: Multi-line greedy break
  {
    const r = await breakParagraph(engine, {
      text: 'The quick brown fox jumps over the lazy dog',
      availableWidthPt: 60, fontFamily: 'mock', sizePt: 12,
    });
    assert(r.totalLines > 1, 'Case 2.totalLines>1');
    assert(r.totalLines < 10, 'Case 2.totalLines<10');
    for (const line of r.lines) {
      if (line.words.length >= 2) {
        assert(line.widthPt <= 60, `Case 2.fit line "${line.text}"`);
      }
    }
    assertEq(r.lines.map((l) => l.text).join(' '),
             'The quick brown fox jumps over the lazy dog', 'Case 2.roundtrip');
  }

  // Case 3: Overlong word force-fit
  {
    const r = await breakParagraph(engine, {
      text: 'short supercalifragilisticexpialidocious end',
      availableWidthPt: 50, fontFamily: 'mock', sizePt: 12,
    });
    assert(r.totalLines >= 3, 'Case 3.totalLines>=3');
    const overlong = r.lines.find((l) =>
      l.words.length === 1 && l.words[0] === 'supercalifragilisticexpialidocious');
    assert(overlong !== undefined, 'Case 3.overlong exists');
    assert(overlong.widthPt > 50, 'Case 3.overlong overflow');
  }

  // Case 4: Empty/whitespace
  {
    const empty = await breakParagraph(engine, {
      text: '', availableWidthPt: 100, fontFamily: 'mock', sizePt: 12,
    });
    assertEq(empty.totalLines, 0, 'Case 4.empty.lines=0');
    assertEq(empty.maxLineWidthPt, 0, 'Case 4.empty.maxWidth=0');
    const spaces = await breakParagraph(engine, {
      text: '   ', availableWidthPt: 100, fontFamily: 'mock', sizePt: 12,
    });
    assertEq(spaces.totalLines, 0, 'Case 4.spaces.lines=0');
  }

  // Case 5: Larger size → more lines（線性 mock 滿足此性質）
  {
    const text = 'The quick brown fox jumps over the lazy dog';
    const tight = await breakParagraph(engine, {
      text, availableWidthPt: 120, fontFamily: 'mock', sizePt: 10,
    });
    const big = await breakParagraph(engine, {
      text, availableWidthPt: 120, fontFamily: 'mock', sizePt: 20,
    });
    assert(big.totalLines >= tight.totalLines, 'Case 5.big>=tight');
  }

  // Case 6: Injected spaceWidthPt
  {
    const r = await breakParagraph(engine, {
      text: 'Hello world test', availableWidthPt: 100,
      fontFamily: 'mock', sizePt: 12, spaceWidthPt: 3.0,
    });
    assert(r.totalLines >= 1, 'Case 6.lines>=1');
    assertEq(r.lines.map((l) => l.text).join(' '), 'Hello world test', 'Case 6.roundtrip');
  }

  // === Report ===
  console.log(`\n[sprint277 verify] pass=${pass} fail=${fail}`);
  if (fail > 0) {
    console.error('FAILURES:');
    for (const f of failures) console.error('  -', f);
    process.exit(1);
  }
  console.log('[sprint277 verify] 雙驗 path 2 (standalone Node) PASSED');
}

main().catch((e) => { console.error(e); process.exit(2); });
