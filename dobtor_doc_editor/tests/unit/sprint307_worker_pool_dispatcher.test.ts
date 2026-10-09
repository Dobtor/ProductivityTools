/**
 * Sprint 307 — ⑥ deeper：WorkerPoolDispatcher round-robin。
 *
 * Sprint 292/294/299 完成 dispatcher cluster；本 sprint 補 pool 層。
 *
 * 紀律 #18 scope-down：pure round-robin（不做 least-busy）；不主動 spawn worker
 *   （caller 傳入既有 dispatcher）；不做 crash recovery。
 */
import { describe, expect, it, vi } from 'vitest';

import { WorkerPoolDispatcher } from '../../static/src/core/ooxml/worker/WorkerPoolDispatcher';
import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from '../../static/src/core/ooxml/worker/parse_worker_protocol';

/** Fake dispatcher：記錄收到的 request、可手動 emit response 給 listener。 */
function mkFakeDispatcher(): ParseWorkerDispatcher & {
  posted: ParseWorkerRequest[];
  emit: (resp: ParseWorkerResponse) => void;
  terminated: boolean;
} {
  const listeners: Array<(r: ParseWorkerResponse) => void> = [];
  const posted: ParseWorkerRequest[] = [];
  const state = { terminated: false };
  return {
    posted,
    get terminated() { return state.terminated; },
    set terminated(v: boolean) { state.terminated = v; },
    post(req) { posted.push(req); },
    subscribe(l) {
      listeners.push(l);
      return () => {
        const i = listeners.indexOf(l);
        if (i >= 0) listeners.splice(i, 1);
      };
    },
    terminate() { state.terminated = true; },
    emit(resp) { for (const l of listeners) l(resp); },
  } as ReturnType<typeof mkFakeDispatcher>;
}

function mkRequest(id: string): ParseWorkerRequest {
  return { kind: 'parse', requestId: id, bytes: new Uint8Array(0) };
}

// ── round-robin ───────────────────────────────────────────────────────────

describe('Sprint 307 — round-robin', () => {
  it('post 平均派發到 pool 內各 dispatcher', () => {
    const d0 = mkFakeDispatcher();
    const d1 = mkFakeDispatcher();
    const d2 = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d0, d1, d2] });
    pool.post(mkRequest('r1'));
    pool.post(mkRequest('r2'));
    pool.post(mkRequest('r3'));
    pool.post(mkRequest('r4'));
    expect(d0.posted.map((r) => 'requestId' in r ? r.requestId : '')).toEqual(['r1', 'r4']);
    expect(d1.posted.map((r) => 'requestId' in r ? r.requestId : '')).toEqual(['r2']);
    expect(d2.posted.map((r) => 'requestId' in r ? r.requestId : '')).toEqual(['r3']);
  });

  it('pool size = 1 時所有 request 都到同一個 dispatcher', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    pool.post(mkRequest('r1'));
    pool.post(mkRequest('r2'));
    expect(d.posted).toHaveLength(2);
  });
});

// ── fan-out subscribe ─────────────────────────────────────────────────────

describe('Sprint 307 — fan-out subscribe', () => {
  it('任一底層 emit → pool listener 全收', () => {
    const d0 = mkFakeDispatcher();
    const d1 = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d0, d1] });
    const received: ParseWorkerResponse[] = [];
    pool.subscribe((r) => received.push(r));
    d0.emit({ kind: 'success', requestId: 'r1', ast: { x: 1 }, parseTimeMs: 1 });
    d1.emit({ kind: 'success', requestId: 'r2', ast: { y: 2 }, parseTimeMs: 1 });
    expect(received).toHaveLength(2);
    expect((received[0] as { requestId: string }).requestId).toBe('r1');
    expect((received[1] as { requestId: string }).requestId).toBe('r2');
  });

  it('unsubscribe 後不再收訊息', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    const received: ParseWorkerResponse[] = [];
    const unsub = pool.subscribe((r) => received.push(r));
    d.emit({ kind: 'success', requestId: 'a', ast: null, parseTimeMs: 1 });
    unsub();
    d.emit({ kind: 'success', requestId: 'b', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(1);
  });

  it('listener throw 不影響其他 listener', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    pool.subscribe(() => { throw new Error('boom'); });
    const good = vi.fn();
    pool.subscribe(good);
    d.emit({ kind: 'success', requestId: 'x', ast: null, parseTimeMs: 1 });
    expect(good).toHaveBeenCalledOnce();
  });
});

// ── inflight tracking ─────────────────────────────────────────────────────

describe('Sprint 307 — inflight 追蹤', () => {
  it('post 增加 inflight、response 後清掉', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    expect(pool.inflightCount()).toBe(0);
    pool.post(mkRequest('a'));
    pool.post(mkRequest('b'));
    expect(pool.inflightCount()).toBe(2);
    d.emit({ kind: 'success', requestId: 'a', ast: null, parseTimeMs: 1 });
    expect(pool.inflightCount()).toBe(1);
    d.emit({ kind: 'error', requestId: 'b', reason: 'parse-error', message: 'x' });
    expect(pool.inflightCount()).toBe(0);
  });
});

// ── dispose ───────────────────────────────────────────────────────────────

describe('Sprint 307 — terminate fan-out', () => {
  it('terminate 後 fan-out 給所有底層 dispatcher', () => {
    const d0 = mkFakeDispatcher();
    const d1 = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d0, d1] });
    pool.terminate();
    expect(d0.terminated).toBe(true);
    expect(d1.terminated).toBe(true);
  });

  it('terminate 後 post 為 no-op', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    pool.terminate();
    pool.post(mkRequest('r1'));
    expect(d.posted).toHaveLength(0);
  });

  it('terminate 後底層 emit 不傳給 listener（unsubscribe 已撤）', () => {
    const d = mkFakeDispatcher();
    const pool = new WorkerPoolDispatcher({ dispatchers: [d] });
    const received: ParseWorkerResponse[] = [];
    pool.subscribe((r) => received.push(r));
    pool.terminate();
    d.emit({ kind: 'success', requestId: 'z', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(0);
  });
});

// ── constructor 驗證 ────────────────────────────────────────────────────

describe('Sprint 307 — constructor 驗證', () => {
  it('空 dispatchers throw', () => {
    expect(() => new WorkerPoolDispatcher({ dispatchers: [] })).toThrow(/at least 1/);
  });
});

// ── size ──────────────────────────────────────────────────────────────────

describe('Sprint 307 — size()', () => {
  it('size 回 pool 大小', () => {
    const pool = new WorkerPoolDispatcher({
      dispatchers: [mkFakeDispatcher(), mkFakeDispatcher(), mkFakeDispatcher()],
    });
    expect(pool.size()).toBe(3);
  });
});
