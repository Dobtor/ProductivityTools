/**
 * Sprint 294 — NodeWorkerThreadDispatcher real implementation。
 *
 * Follow-up to Sprint 292（API contract design + MainThread fallback）。
 * Sprint 292 honest gap：「真實 Browser Worker / node:worker_threads dispatcher 未做」。
 * 本 sprint 補 node:worker_threads 真實 dispatcher（Browser Worker 留 future sprint）。
 *
 * Strategy A spike：真實 worker 啟動 + protocol 來回 + parse stub + cancel + timeout。
 *
 * 紀律 #18 scope-down：actual OoxmlParser inside worker = future polish
 *   sprint（structured clone of DocumentNode 含 Map 風險未解）；本 sprint
 *   只跑 stub function（echo / byteLength / sum-bytes）以驗證 worker_threads
 *   接線 + protocol round-trip。
 * 紀律 #21：worker 為 isolated process、不污染 main thread 的 OoxmlParser /
 *   VR pipeline / layout / render。
 */
import { describe, expect, it } from 'vitest';

import {
  NodeWorkerThreadDispatcher,
  ParseWorkerHarness,
} from '../../static/src/core/ooxml/worker';

describe('Sprint 294 — NodeWorkerThreadDispatcher basic round-trip', () => {
  it('byteLength stub：worker 收 bytes → 回 { byteLength }', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'byteLength' });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    const result = await harness.parse(new Uint8Array([1, 2, 3, 4, 5]));
    expect(result.ast).toEqual({ byteLength: 5 });
    expect(result.parseTimeMs).toBeGreaterThanOrEqual(0);
    expect(result.wallClockMs).toBeGreaterThanOrEqual(0);
    // worker wall clock >= worker parseTimeMs（含 IPC overhead）
    expect(result.wallClockMs).toBeGreaterThanOrEqual(result.parseTimeMs);
    harness.dispose();
  });

  it('sum-bytes stub：worker 內真實 CPU 計算 sum', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'sum-bytes' });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    const bytes = new Uint8Array([10, 20, 30, 40]);
    const result = await harness.parse(bytes);
    expect(result.ast).toEqual({ sum: 100, byteLength: 4 });
    harness.dispose();
  });

  it('echo stub：worker structured-clone bytes 原樣回（測 IPC 序列化）', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'echo' });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    const bytes = new Uint8Array([1, 2, 3]);
    const result = await harness.parse(bytes);
    const echoed = result.ast as Uint8Array;
    expect(echoed.byteLength).toBe(3);
    expect(echoed[0]).toBe(1);
    expect(echoed[2]).toBe(3);
    harness.dispose();
  });
});

describe('Sprint 294 — NodeWorkerThreadDispatcher concurrency', () => {
  it('多 parse 同時 in-flight：worker 序列化處理、各自正確回應', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'byteLength' });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    const results = await Promise.all([
      harness.parse(new Uint8Array(10)),
      harness.parse(new Uint8Array(20)),
      harness.parse(new Uint8Array(30)),
    ]);
    expect((results[0].ast as { byteLength: number }).byteLength).toBe(10);
    expect((results[1].ast as { byteLength: number }).byteLength).toBe(20);
    expect((results[2].ast as { byteLength: number }).byteLength).toBe(30);
    harness.dispose();
  });
});

describe('Sprint 294 — NodeWorkerThreadDispatcher timeout + cancel', () => {
  it('worker delay > harness timeout → reject "timeout"', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({
      parseStub: 'byteLength',
      delayMs: 1000,
    });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    await expect(harness.parse(new Uint8Array([0]), 100)).rejects.toThrow(/timeout/);
    harness.dispose();
  });

  it('harness.cancel(requestId) 不存在 id → no-op', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'byteLength' });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    // 不會 throw
    harness.cancel('nonexistent-id');
    harness.dispose();
  });
});

describe('Sprint 294 — NodeWorkerThreadDispatcher dispose lifecycle', () => {
  it('dispose 進行中 parse → reject "disposed"', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({
      parseStub: 'byteLength',
      delayMs: 2000,
    });
    await dispatcher.waitReady();
    const harness = new ParseWorkerHarness({ dispatcher });
    const pending = harness.parse(new Uint8Array([0]));
    setTimeout(() => harness.dispose(), 50);
    await expect(pending).rejects.toThrow('disposed');
  });

  it('dispose 後 post → no-op、不 throw', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'byteLength' });
    await dispatcher.waitReady();
    dispatcher.terminate();
    // dispose 後 post 不該 throw
    dispatcher.post({ kind: 'parse', requestId: 'r1', bytes: new Uint8Array(0) });
  });
});

describe('Sprint 294 — pendingPosts: 啟動前 post 自動 queue', () => {
  it('啟動前 post → waitReady 後 worker 收到、回 success', async () => {
    const dispatcher = new NodeWorkerThreadDispatcher({ parseStub: 'byteLength' });
    // 不 waitReady！直接 wrap harness、立刻 post
    const harness = new ParseWorkerHarness({ dispatcher });
    const result = await harness.parse(new Uint8Array([1, 2, 3, 4, 5, 6, 7]));
    expect((result.ast as { byteLength: number }).byteLength).toBe(7);
    harness.dispose();
  });
});
