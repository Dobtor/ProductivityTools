/**
 * Sprint 275 — Phase 2 Exit ④ cache hitRate 量測（Sprint 269 保留條件解除）
 *
 * Sprint 269 Phase 2 Exit re-verify 時把 Condition ④「Glyph cache 觀察
 * hitRate > 50% on Layout pass」標為「附保留條件 hypothesis、待 Phase 6
 * Layout 接 measureRun 時驗證」。本 sprint 用合成 Layout pass 模擬實際使用
 * 場景、量測 ShapingEngine cache 實際 hitRate、解除保留條件。
 *
 * Layout pass 模擬場景（典型 docx editor 重排）：
 *   - Pass 1（cold layout）：parser → 段落 → measureRun(word) tokenized
 *   - Pass 2（warm reflow）：同段落 trial-and-error 重排（例如 inline edit /
 *     視窗 resize / 字級調整）→ 同 (text, font, size) 再 measureRun
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import { ShapingEngine } from '../../static/src/core/ooxml/font';

const FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT_PATH);

/** 樣本段落（混合 ASCII + 標點 + 重複字詞 / 模擬 ChienYi 監造日誌典型內容）。 */
const SAMPLE_PARAGRAPHS = [
  'The quick brown fox jumps over the lazy dog.',
  'A construction supervisor inspects the foundation work daily.',
  'Concrete strength testing requires standardized procedures.',
  'Safety equipment must be worn at all times on site.',
  'The quick brown fox jumps over the lazy dog.',  // 重複（reflow 模擬）
  'Project schedule deviations are reported weekly.',
  'A construction supervisor inspects the foundation work daily.',  // 重複
  'Material delivery logs are verified against purchase orders.',
];

const PHASE2_EXIT_HITRATE_THRESHOLD = 0.5;
const PHASE2_EXIT_WARM_HITRATE_THRESHOLD = 0.95;

describe.skipIf(!HAS_FONT)('Sprint 275 — Phase 2 Exit ④ cache hitRate validation', () => {
  it('Layout pass 模擬：tokenize 段落為單字、measureRun 每字、量測 cache hitRate', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH)));

    // Pass 1（cold layout）— 走過所有段落、tokenize 為單字、逐字 measureRun
    let pass1Words = 0;
    for (const para of SAMPLE_PARAGRAPHS) {
      for (const word of para.split(/\s+/)) {
        if (word.length === 0) continue;
        await engine.measureRun(word, 'DejaVuSans', 12);
        pass1Words++;
      }
    }
    const pass1Stats = engine.getCacheStats();
    // eslint-disable-next-line no-console
    console.log(`[sprint275] Pass 1 (cold): words=${pass1Words} hits=${pass1Stats.hits} misses=${pass1Stats.misses} entries=${pass1Stats.entries} hitRate=${pass1Stats.hitRate.toFixed(4)}`);

    // Pass 2（warm reflow）— 同樣段落再走一次（模擬 inline edit / resize）
    let pass2Words = 0;
    for (const para of SAMPLE_PARAGRAPHS) {
      for (const word of para.split(/\s+/)) {
        if (word.length === 0) continue;
        await engine.measureRun(word, 'DejaVuSans', 12);
        pass2Words++;
      }
    }
    const pass2Stats = engine.getCacheStats();
    // Pass 2 期間的局部 hit/miss
    const pass2Hits = pass2Stats.hits - pass1Stats.hits;
    const pass2Misses = pass2Stats.misses - pass1Stats.misses;
    const pass2HitRate = pass2Hits / (pass2Hits + pass2Misses);
    // eslint-disable-next-line no-console
    console.log(`[sprint275] Pass 2 (warm): words=${pass2Words} pass-local hits=${pass2Hits} misses=${pass2Misses} hitRate=${pass2HitRate.toFixed(4)}`);

    // 累積 hitRate
    // eslint-disable-next-line no-console
    console.log(`[sprint275] Cumulative: hits=${pass2Stats.hits} misses=${pass2Stats.misses} hitRate=${pass2Stats.hitRate.toFixed(4)}`);

    // Phase 2 Exit ④ thresholds（Sprint 269 hypothesis）
    expect(pass2HitRate).toBeGreaterThanOrEqual(PHASE2_EXIT_WARM_HITRATE_THRESHOLD);
    expect(pass2Stats.hitRate).toBeGreaterThanOrEqual(PHASE2_EXIT_HITRATE_THRESHOLD);
  });

  it('Trial-and-error 重排場景：同段落 5 次重排、warm passes 累積 hitRate 接近 100%', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH)));

    const PASSES = 5;
    const passHitRates: number[] = [];
    let prevHits = 0;
    let prevMisses = 0;
    for (let pass = 0; pass < PASSES; pass++) {
      for (const para of SAMPLE_PARAGRAPHS) {
        for (const word of para.split(/\s+/)) {
          if (word.length === 0) continue;
          await engine.measureRun(word, 'DejaVuSans', 12);
        }
      }
      const stats = engine.getCacheStats();
      const passHits = stats.hits - prevHits;
      const passMisses = stats.misses - prevMisses;
      const passRate = passHits / (passHits + passMisses);
      passHitRates.push(passRate);
      prevHits = stats.hits;
      prevMisses = stats.misses;
    }

    // eslint-disable-next-line no-console
    console.log(`[sprint275] 5 reflow passes hitRates: ${passHitRates.map((r) => r.toFixed(4)).join(' / ')}`);

    // Pass 0（cold）hitRate ~低；Pass 1+ warm hitRate 應 == 1.0（同 text/font/size）
    expect(passHitRates[0]).toBeLessThan(0.3);  // cold 大多 miss
    for (let i = 1; i < PASSES; i++) {
      expect(passHitRates[i]).toBe(1.0);  // warm 全 hit
    }
  });

  it('多字級 reflow（resize 場景）：同段落 + 不同 sizePt → 每 sizePt 內 hitRate=100%', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT_PATH)));

    const SIZES = [10, 12, 14, 16, 18];
    // 對每個 size 跑兩 pass（cold + warm）
    const sizeStats: Array<{ size: number; coldHits: number; coldMisses: number; warmHits: number; warmMisses: number }> = [];
    for (const size of SIZES) {
      const before = engine.getCacheStats();
      // Cold pass for this size
      for (const para of SAMPLE_PARAGRAPHS) {
        for (const word of para.split(/\s+/)) {
          if (word.length === 0) continue;
          await engine.measureRun(word, 'DejaVuSans', size);
        }
      }
      const afterCold = engine.getCacheStats();
      // Warm pass
      for (const para of SAMPLE_PARAGRAPHS) {
        for (const word of para.split(/\s+/)) {
          if (word.length === 0) continue;
          await engine.measureRun(word, 'DejaVuSans', size);
        }
      }
      const afterWarm = engine.getCacheStats();
      sizeStats.push({
        size,
        coldHits: afterCold.hits - before.hits,
        coldMisses: afterCold.misses - before.misses,
        warmHits: afterWarm.hits - afterCold.hits,
        warmMisses: afterWarm.misses - afterCold.misses,
      });
    }

    for (const s of sizeStats) {
      // eslint-disable-next-line no-console
      console.log(`[sprint275] size=${s.size}pt cold ${s.coldHits}h/${s.coldMisses}m warm ${s.warmHits}h/${s.warmMisses}m`);
      // Cold pass for new size：mostly misses（同字串新 sizePt 視為 new cache entry）
      expect(s.coldMisses).toBeGreaterThan(0);
      // Warm pass：100% hit（cache key 含 sizePt）
      expect(s.warmMisses).toBe(0);
      expect(s.warmHits).toBeGreaterThan(0);
    }

    const final = engine.getCacheStats();
    // eslint-disable-next-line no-console
    console.log(`[sprint275] Multi-size final: entries=${final.entries} hits=${final.hits} misses=${final.misses} hitRate=${final.hitRate.toFixed(4)}`);
    expect(final.hitRate).toBeGreaterThan(PHASE2_EXIT_HITRATE_THRESHOLD);
  });
});
