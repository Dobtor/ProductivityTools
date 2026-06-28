/**
 * Sprint 327 — ⑥ deeper⁶：WorkerRetryWrapper。
 *
 * Sprint 292/294/299/307/312/317/322 worker 第七輪深推。Automatic retry +
 * exponential backoff。
 *
 * 紀律 #18 scope-down：純記憶體 retry state；caller 提供 clock + schedule fn。
 */
import { describe, expect, it } from 'vitest';

import { WorkerRetryWrapper } from '../../static/src/core/ooxml/worker/WorkerRetryWrapper';
import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from '../../static/src/core/ooxml/worker/parse_worker_protocol';

function mkFake() {
  const listeners: Array<(r: ParseWorkerResponse) => void> = [];
  const posted: ParseWorkerRequest[] = [];
  const state = { terminated: false };
  return {
    posted,
    get terminated() { return state.terminated; },
    post(req: ParseWorkerRequest) { posted.push(req); },
    subscribe(l: (r: ParseWorkerResponse) => void) {
      listeners.push(l);
      return () => { const i = listeners.indexOf(l); if (i >= 0) listeners.splice(i, 1); };
    },
    terminate() { state.terminated = true; },
    emit(r: ParseWorkerResponse) { for (const l of listeners) l(r); },
  } as ParseWorkerDispatcher & { posted: ParseWorkerRequest[]; emit: (r: ParseWorkerResponse) => void; terminated: boolean };
}

function mkReq(id: string): ParseWorkerRequest {
  return { kind: 'parse', requestId: id, bytes: new Uint8Array(0) };
}

/** Synchronous schedule（立刻執行）給測試用。 */
const syncSchedule = (fn: () => void): void => fn();

// ── success → propagate ────────────────────────────────────────────

describe('Sprint 327 — success 直接 propagate', () => {
  it('success response → final-success +1、不重 post', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    const received: ParseWorkerResponse[] = [];
    wrapper.subscribe((r) => received.push(r));
    wrapper.post(mkReq('r1'));
    f.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(1);
    expect(wrapper.getStats().finalSuccess).toBe(1);
    expect(wrapper.getStats().retries).toBe(0);
    expect(f.posted).toHaveLength(1);
  });
});

// ── error → 重試 ───────────────────────────────────────────────────

describe('Sprint 327 — retryable error 自動重試', () => {
  it('parse-error 重試到 maxAttempts、最終成功', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule, maxAttempts: 3 });
    const received: ParseWorkerResponse[] = [];
    wrapper.subscribe((r) => received.push(r));
    wrapper.post(mkReq('r1'));
    // 第 1 次 error → retry
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'boom' });
    // 第 2 次 error → retry
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'boom' });
    // 第 3 次 success
    f.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    // 中間兩次 error 不 propagate；最終 success propagate
    expect(received).toHaveLength(1);
    expect(received[0].kind).toBe('success');
    expect(f.posted).toHaveLength(3); // 原 post + 2 retries
    expect(wrapper.getStats().retries).toBe(2);
    expect(wrapper.getStats().finalSuccess).toBe(1);
  });

  it('用完 attempts 仍 error → 最終 propagate error', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule, maxAttempts: 2 });
    const received: ParseWorkerResponse[] = [];
    wrapper.subscribe((r) => received.push(r));
    wrapper.post(mkReq('r1'));
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    expect(received).toHaveLength(1);
    expect(received[0].kind).toBe('error');
    expect(wrapper.getStats().finalError).toBe(1);
    expect(wrapper.getStats().retries).toBe(1);
  });
});

// ── non-retryable error → 不重試 ──────────────────────────────────

describe('Sprint 327 — 不可重試 error 直接 propagate', () => {
  it('error reason 不在 retryableReasons → 直接 final error', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({
      dispatcher: f,
      schedule: syncSchedule,
      retryableReasons: ['timeout'], // 不含 parse-error
    });
    const received: ParseWorkerResponse[] = [];
    wrapper.subscribe((r) => received.push(r));
    wrapper.post(mkReq('r1'));
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    expect(received).toHaveLength(1);
    expect(wrapper.getStats().finalError).toBe(1);
    expect(wrapper.getStats().retries).toBe(0);
  });
});

// ── exponential backoff ────────────────────────────────────────────

describe('Sprint 327 — exponential backoff', () => {
  it('retry 1 = base * 1、retry 2 = base * 2、retry 3 = base * 4', () => {
    const f = mkFake();
    const delays: number[] = [];
    const wrapper = new WorkerRetryWrapper({
      dispatcher: f,
      maxAttempts: 4,
      baseBackoffMs: 100,
      schedule: (fn, d) => { delays.push(d); fn(); },
    });
    wrapper.post(mkReq('r1'));
    // retry 1：state.attempts=2、Math.pow(2, 0)=1 → delay=100
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    expect(delays[0]).toBe(100);
    // retry 2：state.attempts=3、Math.pow(2, 1)=2 → delay=200
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    expect(delays[1]).toBe(200);
    // retry 3：state.attempts=4、Math.pow(2, 2)=4 → delay=400
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' });
    expect(delays[2]).toBe(400);
  });

  it('backoff 不超過 maxBackoffMs', () => {
    const f = mkFake();
    const delays: number[] = [];
    const wrapper = new WorkerRetryWrapper({
      dispatcher: f,
      maxAttempts: 10,
      baseBackoffMs: 1000,
      maxBackoffMs: 3000,
      schedule: (fn, d) => { delays.push(d); fn(); },
    });
    wrapper.post(mkReq('r1'));
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' }); // 1000
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' }); // 2000
    f.emit({ kind: 'error', requestId: 'r1', reason: 'parse-error', message: 'x' }); // 4000 → cap 3000
    expect(delays[2]).toBe(3000);
  });
});

// ── inflight tracking ──────────────────────────────────────────────

describe('Sprint 327 — inflight tracking', () => {
  it('post 後 inflightCount++、success 後 --', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    wrapper.post(mkReq('r1'));
    expect(wrapper.getStats().inflightCount).toBe(1);
    f.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    expect(wrapper.getStats().inflightCount).toBe(0);
  });
});

// ── unknown requestId → propagate without tracking ──────────────

describe('Sprint 327 — unknown requestId 不追蹤', () => {
  it('沒 post 過的 requestId 來的 response → propagate but no stats change', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    const received: ParseWorkerResponse[] = [];
    wrapper.subscribe((r) => received.push(r));
    f.emit({ kind: 'success', requestId: 'ghost', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(1);
    expect(wrapper.getStats().finalSuccess).toBe(0);
  });
});

// ── terminate fan-out ─────────────────────────────────────────────

describe('Sprint 327 — terminate fan-out', () => {
  it('terminate 給底層 dispatcher', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    wrapper.terminate();
    expect(f.terminated).toBe(true);
  });

  it('terminate 後 post no-op', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    wrapper.terminate();
    wrapper.post(mkReq('r1'));
    expect(f.posted).toHaveLength(0);
  });
});

// ── clearStats ──────────────────────────────────────────────────

describe('Sprint 327 — clearStats', () => {
  it('清掉 counts、保留 inflight', () => {
    const f = mkFake();
    const wrapper = new WorkerRetryWrapper({ dispatcher: f, schedule: syncSchedule });
    wrapper.post(mkReq('r1'));
    f.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    wrapper.post(mkReq('r2'));  // 仍 inflight
    wrapper.clearStats();
    const s = wrapper.getStats();
    expect(s.finalSuccess).toBe(0);
    expect(s.completed).toBe(0);
    expect(s.inflightCount).toBe(1);
  });
});
