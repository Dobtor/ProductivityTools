/**
 * Sprint 279 — ShapingEngine browser-compat refactor unit tests
 *
 * 驗證 caller-injectable hbModuleLoader：
 *   1. 預設 path（無 injection）= Node createRequire fallback、原行為不變
 *   2. setHbModuleLoader(loader) 注入後 shape() 走 caller loader
 *   3. loader 注入 reset 既有 cache、下次 shape 重新走 loader
 *   4. __resetHbModuleLoaderForTesting 清空 loader + cache
 *
 * 系統字型依賴：DejaVuSans；找不到時 skip。
 */
import { afterEach, describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

import {
  ShapingEngine,
  __resetHbForTesting,
  __resetHbModuleLoaderForTesting,
  setHbModuleLoader,
} from '../../static/src/core/ooxml/font';

const FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
const HAS_FONT = existsSync(FONT);

afterEach(() => {
  __resetHbModuleLoaderForTesting();
  __resetHbForTesting();
});

describe.skipIf(!HAS_FONT)('Sprint 279 — ShapingEngine loader injection (browser-compat)', () => {
  it('default path（無 loader injection）= Node createRequire fallback、shape 正常', async () => {
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    const r = await engine.measureRun('Hello', 'DejaVuSans', 12);
    expect(r.glyphCount).toBe(5);
    expect(r.widthPt).toBeGreaterThan(0);
  });

  it('setHbModuleLoader 注入 mock loader → shape 走 caller loader', async () => {
    let loaderInvoked = 0;
    setHbModuleLoader(async () => {
      loaderInvoked++;
      // 真正 invoke node 端 require、但路徑由 caller 控制（模擬 browser 自取 wasm）
      const { createRequire } = await import('node:module');
      const localRequire = createRequire(import.meta.url);
      return localRequire('harfbuzzjs');
    });

    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    const r = await engine.measureRun('Hi', 'DejaVuSans', 12);
    expect(loaderInvoked).toBe(1);
    expect(r.glyphCount).toBe(2);
  });

  it('caller loader 被 cache、第二次 shape 不重複 invoke', async () => {
    let loaderInvoked = 0;
    setHbModuleLoader(async () => {
      loaderInvoked++;
      const { createRequire } = await import('node:module');
      const localRequire = createRequire(import.meta.url);
      return localRequire('harfbuzzjs');
    });

    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    await engine.measureRun('a', 'DejaVuSans', 12);
    await engine.measureRun('b', 'DejaVuSans', 12);
    await engine.measureRun('c', 'DejaVuSans', 12);
    expect(loaderInvoked).toBe(1);
  });

  it('setHbModuleLoader 重複呼叫 reset cache → 新 loader 被 invoke', async () => {
    let loaderA = 0;
    let loaderB = 0;
    setHbModuleLoader(async () => {
      loaderA++;
      const { createRequire } = await import('node:module');
      const localRequire = createRequire(import.meta.url);
      return localRequire('harfbuzzjs');
    });
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    await engine.measureRun('a', 'DejaVuSans', 12);
    expect(loaderA).toBe(1);

    setHbModuleLoader(async () => {
      loaderB++;
      const { createRequire } = await import('node:module');
      const localRequire = createRequire(import.meta.url);
      return localRequire('harfbuzzjs');
    });
    await engine.measureRun('b', 'DejaVuSans', 12);
    expect(loaderA).toBe(1);  // 不再增加
    expect(loaderB).toBe(1);  // 新 loader 被 invoke
  });

  it('__resetHbModuleLoaderForTesting 清 loader + cache、後續 shape 走 default Node path', async () => {
    let injected = 0;
    setHbModuleLoader(async () => {
      injected++;
      const { createRequire } = await import('node:module');
      const localRequire = createRequire(import.meta.url);
      return localRequire('harfbuzzjs');
    });
    const engine = new ShapingEngine();
    engine.loadFont('DejaVuSans', new Uint8Array(readFileSync(FONT)));
    await engine.measureRun('x', 'DejaVuSans', 12);
    expect(injected).toBe(1);

    __resetHbModuleLoaderForTesting();
    // 再 shape：走 default path（createRequire fallback、不 invoke injected）
    await engine.measureRun('y', 'DejaVuSans', 12);
    expect(injected).toBe(1);  // 沒再 invoke
  });
});
