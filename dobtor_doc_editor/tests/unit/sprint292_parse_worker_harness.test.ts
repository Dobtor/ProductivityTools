/**
 * Sprint 292 — ⑥ Phase 7 Worker parse harness（OVERRIDE）。
 *
 * User 指令「繼續執行 1-6」⑥ = explicit OVERRIDE（Sprint 197 final audit 判定
 * 不建議；user override 仍要鋪基礎）。
 *
 * SPIKE-only：API contract + MainThreadDispatcher fallback + 14 tests。
 * 真實 browser Worker / node:worker_threads 實作為未來 polish sprint。
 *
 * 紀律 #18 scope-down：不啟動真實 Worker、不接 OoxmlParser production pipeline。
 * 紀律 #21：harness 為 read-only API、不污染 VR pipeline。
 */
import { describe, expect, it, vi } from 'vitest';

import {
  ParseWorkerHarness,
  MainThreadDispatcher,
} from '../../static/src/core/ooxml/worker';
import type { ParseWorkerDispatcher } from '../../static/src/core/ooxml/worker';

describe('Sprint 292 — MainThreadDispatcher (fallback)', () => {
  it('parse 成功 → harness.parse 拿到 ast + parseTimeMs + wallClockMs', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: async (bytes) => ({ ok: true, byteLength: (bytes as Uint8Array).byteLength }),
    });
    const harness = new ParseWorkerHarness({ dispatcher });

    const result = await harness.parse(new Uint8Array([1, 2, 3]));
    expect(result.ast).toEqual({ ok: true, byteLength: 3 });
    expect(result.parseTimeMs).toBeGreaterThanOrEqual(0);
    expect(result.wallClockMs).toBeGreaterThanOrEqual(0);
    harness.dispose();
  });

  it('parse 失敗（synchronous throw）→ reject 含 reason="parse-error"', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: () => {
        throw new Error('parse boom');
      },
    });
    const harness = new ParseWorkerHarness({ dispatcher });
    await expect(harness.parse(new Uint8Array([0]))).rejects.toThrow('parse-error: parse boom');
    harness.dispose();
  });

  it('parse 失敗（async reject）→ 同樣 reject', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: async () => {
        throw new Error('async boom');
      },
    });
    const harness = new ParseWorkerHarness({ dispatcher });
    await expect(harness.parse(new Uint8Array([0]))).rejects.toThrow('async boom');
    harness.dispose();
  });

  it('多個並發 parse → 各自獨立 requestId、互不干擾', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: async (bytes) => (bytes as Uint8Array)[0],
    });
    const harness = new ParseWorkerHarness({ dispatcher });

    const results = await Promise.all([
      harness.parse(new Uint8Array([10])),
      harness.parse(new Uint8Array([20])),
      harness.parse(new Uint8Array([30])),
    ]);
    expect(results.map((r) => r.ast)).toEqual([10, 20, 30]);
    harness.dispose();
  });

  it('timeout 觸發 → reject "timeout after Nms"', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: () => new Promise(() => { /* never resolve */ }),
    });
    const harness = new ParseWorkerHarness({ dispatcher });
    await expect(harness.parse(new Uint8Array([0]), 50)).rejects.toThrow(/timeout after 50ms/);
    harness.dispose();
  });
});

describe('Sprint 292 — Progress reporting', () => {
  it('dispatcher emit progress → onProgress callback 被呼叫', async () => {
    const onProgress = vi.fn();
    let emitProgress: ((p: number) => void) | undefined;
    let emitSuccess: ((ast: unknown) => void) | undefined;
    let currentRequestId = '';

    const dispatcher: ParseWorkerDispatcher = {
      post: (req) => {
        if (req.kind === 'parse') {
          currentRequestId = req.requestId;
          // 先 emit 兩個 progress、再 success
          setTimeout(() => emitProgress?.(0.3), 1);
          setTimeout(() => emitProgress?.(0.7), 2);
          setTimeout(() => emitSuccess?.('done'), 3);
        }
      },
      subscribe: (listener) => {
        emitProgress = (p) =>
          listener({ kind: 'progress', requestId: currentRequestId, progress: p });
        emitSuccess = (ast) =>
          listener({ kind: 'success', requestId: currentRequestId, ast, parseTimeMs: 5 });
        return () => {};
      },
      terminate: () => {},
    };
    const harness = new ParseWorkerHarness({ dispatcher, onProgress });
    const result = await harness.parse(new Uint8Array([0]));
    expect(result.ast).toBe('done');
    expect(onProgress).toHaveBeenCalledWith(0.3);
    expect(onProgress).toHaveBeenCalledWith(0.7);
    expect(onProgress).toHaveBeenCalledTimes(2);
    harness.dispose();
  });
});

describe('Sprint 292 — Cancel + dispose', () => {
  it('parse 進行中 dispose → reject "disposed"', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: () => new Promise(() => { /* never resolve */ }),
    });
    const harness = new ParseWorkerHarness({ dispatcher });
    const pending = harness.parse(new Uint8Array([0]));
    setTimeout(() => harness.dispose(), 5);
    await expect(pending).rejects.toThrow('disposed');
  });

  it('已 success 的 requestId 後續 cancel → no-op、不 throw', async () => {
    const dispatcher = new MainThreadDispatcher({
      parse: async () => 'ok',
    });
    const harness = new ParseWorkerHarness({ dispatcher });
    const result = await harness.parse(new Uint8Array([0]));
    expect(result.ast).toBe('ok');
    // 不知道 requestId — 但 cancel 不存在的 id 應 no-op
    harness.cancel('non-existent-id');
    harness.dispose();
  });
});

describe('Sprint 292 — Dispatcher API contract', () => {
  it('subscribe 回傳 unsubscribe 函式、之後 listener 不再收訊息', () => {
    const dispatcher = new MainThreadDispatcher({ parse: () => 'x' });
    const received: unknown[] = [];
    const unsub = dispatcher.subscribe((r) => received.push(r));
    dispatcher.post({ kind: 'cancel', requestId: 'r1' });
    return new Promise((resolve) => {
      queueMicrotask(() => {
        expect(received).toHaveLength(1);
        unsub();
        dispatcher.post({ kind: 'cancel', requestId: 'r2' });
        queueMicrotask(() => {
          expect(received).toHaveLength(1); // unsub 後不再收
          resolve(undefined);
        });
      });
    });
  });

  it('多 listener → 全部都收到訊息', () => {
    const dispatcher = new MainThreadDispatcher({ parse: () => 'x' });
    const r1: unknown[] = [];
    const r2: unknown[] = [];
    dispatcher.subscribe((r) => r1.push(r));
    dispatcher.subscribe((r) => r2.push(r));
    dispatcher.post({ kind: 'cancel', requestId: 'r1' });
    return new Promise((resolve) => {
      queueMicrotask(() => {
        expect(r1).toHaveLength(1);
        expect(r2).toHaveLength(1);
        resolve(undefined);
      });
    });
  });

  it('listener throw 不影響其他 listener', () => {
    const dispatcher = new MainThreadDispatcher({ parse: () => 'x' });
    const received: unknown[] = [];
    dispatcher.subscribe(() => {
      throw new Error('listener boom');
    });
    dispatcher.subscribe((r) => received.push(r));
    dispatcher.post({ kind: 'cancel', requestId: 'r1' });
    return new Promise((resolve) => {
      queueMicrotask(() => {
        expect(received).toHaveLength(1);
        resolve(undefined);
      });
    });
  });

  it('terminate → 清空 listener + 之後 post 不再 emit', () => {
    const dispatcher = new MainThreadDispatcher({ parse: () => 'x' });
    const received: unknown[] = [];
    dispatcher.subscribe((r) => received.push(r));
    dispatcher.terminate();
    dispatcher.post({ kind: 'cancel', requestId: 'r1' });
    return new Promise((resolve) => {
      queueMicrotask(() => {
        expect(received).toHaveLength(0);
        resolve(undefined);
      });
    });
  });
});
