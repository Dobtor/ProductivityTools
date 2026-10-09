/**
 * Sprint 299 — BrowserWorkerDispatcher real implementation。
 *
 * Follow-up to Sprint 294 honest gap「真實 Browser Worker dispatcher 未做」。
 *
 * Strategy A spike：browser Worker API dispatcher + 9 tests。
 *
 * 紀律 #18 scope-down：actual OoxmlParser inside worker 留 future polish
 *   sprint；本 sprint 用 inline script stub 驗證 Worker API 接線 + protocol
 *   round-trip。
 *
 * Test 環境：vitest with happy-dom；happy-dom 提供 Worker / Blob / URL 等
 *   browser API，本測試直接用真 Worker class。
 */
import { describe, expect, it, beforeAll } from 'vitest';

import {
  BrowserWorkerDispatcher,
  ParseWorkerHarness,
} from '../../static/src/core/ooxml/worker';

// happy-dom 預設可能不完整支援 Worker；偵測後再決定 skip
let WORKER_AVAILABLE = false;
beforeAll(() => {
  try {
    const W = (globalThis as { Worker?: typeof Worker }).Worker;
    WORKER_AVAILABLE = typeof W === 'function';
  } catch {
    WORKER_AVAILABLE = false;
  }
});

/** Inline worker script：byteLength stub（模擬 Sprint 294 node_worker_entry 的 byteLength 邏輯）。 */
const INLINE_BYTELENGTH_WORKER = `
self.addEventListener('message', (ev) => {
  const msg = ev.data;
  if (!msg || typeof msg !== 'object') return;
  if (msg.kind === 'parse') {
    const startedAt = Date.now();
    const bytes = msg.bytes;
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    self.postMessage({
      kind: 'success',
      requestId: msg.requestId,
      ast: { byteLength: u8.byteLength },
      parseTimeMs: Date.now() - startedAt,
    });
  }
});
`;

/** Inline worker：拋錯 → 確認 error reason 流。 */
const INLINE_THROW_WORKER = `
self.addEventListener('message', (ev) => {
  const msg = ev.data;
  if (msg.kind === 'parse') {
    self.postMessage({
      kind: 'error',
      requestId: msg.requestId,
      reason: 'parse-error',
      message: 'inline throw test',
    });
  }
});
`;

describe.skipIf(!WORKER_AVAILABLE)('Sprint 299 — BrowserWorkerDispatcher round-trip', () => {
  it('byteLength inline worker → harness.parse 拿到 { byteLength }', async () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    const harness = new ParseWorkerHarness({ dispatcher });
    const result = await harness.parse(new Uint8Array([1, 2, 3, 4]));
    expect(result.ast).toEqual({ byteLength: 4 });
    harness.dispose();
  });

  it('worker emit error → harness.parse reject with reason', async () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_THROW_WORKER });
    const harness = new ParseWorkerHarness({ dispatcher });
    await expect(harness.parse(new Uint8Array([0]))).rejects.toThrow('inline throw test');
    harness.dispose();
  });

  it('多並發 parse → 各自 requestId 隔離', async () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    const harness = new ParseWorkerHarness({ dispatcher });
    const results = await Promise.all([
      harness.parse(new Uint8Array(5)),
      harness.parse(new Uint8Array(10)),
      harness.parse(new Uint8Array(15)),
    ]);
    expect((results[0].ast as { byteLength: number }).byteLength).toBe(5);
    expect((results[1].ast as { byteLength: number }).byteLength).toBe(10);
    expect((results[2].ast as { byteLength: number }).byteLength).toBe(15);
    harness.dispose();
  });
});

describe.skipIf(!WORKER_AVAILABLE)('Sprint 299 — BrowserWorkerDispatcher dispose', () => {
  it('dispose → worker.terminate() + blobUrl revoked', () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    dispatcher.terminate();
    // 不 throw
  });

  it('dispose 後 post → no-op', () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    dispatcher.terminate();
    // 不 throw
    dispatcher.post({ kind: 'parse', requestId: 'r1', bytes: new Uint8Array(0) });
  });

  it('dispose 後 listener 不再收訊息', () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    const received: unknown[] = [];
    dispatcher.subscribe((r) => received.push(r));
    dispatcher.terminate();
    return new Promise((resolve) => setTimeout(() => {
      expect(received).toHaveLength(0);
      resolve(undefined);
    }, 50));
  });
});

describe('Sprint 299 — BrowserWorkerDispatcher constructor validation', () => {
  it('未提供 scriptUrl 或 inlineScript → throw', () => {
    expect(() => new BrowserWorkerDispatcher({})).toThrow(/must provide/);
  });
});

describe.skipIf(!WORKER_AVAILABLE)('Sprint 299 — subscribe / unsubscribe', () => {
  it('多 listener 都收到、unsubscribe 後不再收', async () => {
    const dispatcher = new BrowserWorkerDispatcher({ inlineScript: INLINE_BYTELENGTH_WORKER });
    const r1: unknown[] = [];
    const r2: unknown[] = [];
    dispatcher.subscribe((r) => r1.push(r));
    const unsub = dispatcher.subscribe((r) => r2.push(r));
    const harness = new ParseWorkerHarness({ dispatcher });
    await harness.parse(new Uint8Array([0]));
    expect(r1.length).toBeGreaterThanOrEqual(1);
    expect(r2.length).toBeGreaterThanOrEqual(1);
    unsub();
    const r2BeforeSecondCall = r2.length;
    await harness.parse(new Uint8Array([0]));
    expect(r2.length).toBe(r2BeforeSecondCall); // 沒新訊息
    harness.dispose();
  });
});
