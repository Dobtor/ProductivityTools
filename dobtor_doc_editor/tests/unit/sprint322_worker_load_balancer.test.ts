/**
 * Sprint 322 — ⑥ deeper⁵：WorkerLoadBalancer。
 *
 * Sprint 292/294/299/307/312/317 worker cluster 第五輪深推。Smart pool 用
 * WorkerHealthMonitor stats 選 worker。
 *
 * 紀律 #18 scope-down：純基於 monitor stats；無動態 worker 增刪。
 */
import { describe, expect, it } from 'vitest';

import { WorkerLoadBalancer } from '../../static/src/core/ooxml/worker/WorkerLoadBalancer';
import { WorkerHealthMonitor } from '../../static/src/core/ooxml/worker/WorkerHealthMonitor';
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

// ── least-inflight strategy ─────────────────────────────────────────

describe('Sprint 322 — least-inflight', () => {
  it('預設選 inflight=0 的 monitor', () => {
    const a = new WorkerHealthMonitor({ dispatcher: mkFake() });
    const b = new WorkerHealthMonitor({ dispatcher: mkFake() });
    // a 已有 2 個 inflight、b 沒有
    a.post(mkReq('a1'));
    a.post(mkReq('a2'));
    const lb = new WorkerLoadBalancer({ monitors: [a, b] });
    expect(lb.peekNextIndex()).toBe(1);
  });

  it('多 post 自動分配最閒的', () => {
    const fA = mkFake();
    const fB = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    const lb = new WorkerLoadBalancer({ monitors: [a, b] });
    lb.post(mkReq('r1'));
    lb.post(mkReq('r2'));
    // 第一次：a 與 b 都 0，tie → round-robin 給 a；第二次 a inflight=1、b=0 → 給 b
    expect(fA.posted).toHaveLength(1);
    expect(fB.posted).toHaveLength(1);
  });
});

// ── lowest-p95 strategy ─────────────────────────────────────────────

describe('Sprint 322 — lowest-p95', () => {
  it('選 p95 latency 最低的 monitor', () => {
    const fA = mkFake();
    const fB = mkFake();
    let now = 0;
    const a = new WorkerHealthMonitor({ dispatcher: fA, now: () => now });
    const b = new WorkerHealthMonitor({ dispatcher: fB, now: () => now });
    // a：5 筆 latency=100、b：5 筆 latency=10
    for (let i = 0; i < 5; i++) {
      now = 0;
      a.post(mkReq(`a${i}`));
      now = 100;
      fA.emit({ kind: 'success', requestId: `a${i}`, ast: null, parseTimeMs: 1 });
      now = 0;
      b.post(mkReq(`b${i}`));
      now = 10;
      fB.emit({ kind: 'success', requestId: `b${i}`, ast: null, parseTimeMs: 1 });
    }
    const lb = new WorkerLoadBalancer({ monitors: [a, b], strategy: 'lowest-p95' });
    expect(lb.peekNextIndex()).toBe(1);
  });
});

// ── lowest-error-rate strategy ──────────────────────────────────────

describe('Sprint 322 — lowest-error-rate', () => {
  it('選 errorRate 最低的 monitor', () => {
    const fA = mkFake();
    const fB = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    // a：3 success + 2 error；b：5 success
    for (let i = 0; i < 3; i++) {
      a.post(mkReq(`as${i}`));
      fA.emit({ kind: 'success', requestId: `as${i}`, ast: null, parseTimeMs: 1 });
    }
    for (let i = 0; i < 2; i++) {
      a.post(mkReq(`ae${i}`));
      fA.emit({ kind: 'error', requestId: `ae${i}`, reason: 'parse-error', message: 'x' });
    }
    for (let i = 0; i < 5; i++) {
      b.post(mkReq(`bs${i}`));
      fB.emit({ kind: 'success', requestId: `bs${i}`, ast: null, parseTimeMs: 1 });
    }
    const lb = new WorkerLoadBalancer({ monitors: [a, b], strategy: 'lowest-error-rate' });
    expect(lb.peekNextIndex()).toBe(1);
  });
});

// ── tie-break round-robin ───────────────────────────────────────────

describe('Sprint 322 — tie-break round-robin', () => {
  it('多 monitor 同 metric → round-robin 切換', () => {
    const fA = mkFake();
    const fB = mkFake();
    const fC = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    const c = new WorkerHealthMonitor({ dispatcher: fC });
    const lb = new WorkerLoadBalancer({ monitors: [a, b, c] });
    lb.post(mkReq('r1'));
    lb.post(mkReq('r2'));
    lb.post(mkReq('r3'));
    // tie-break round-robin：r1→a, r2→b, r3→c
    expect(fA.posted).toHaveLength(1);
    expect(fB.posted).toHaveLength(1);
    expect(fC.posted).toHaveLength(1);
  });

  it('roundRobinTieBreak=false → 永遠選第一個 tie', () => {
    const fA = mkFake();
    const fB = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    const lb = new WorkerLoadBalancer({ monitors: [a, b], roundRobinTieBreak: false });
    lb.post(mkReq('r1'));
    lb.post(mkReq('r2'));
    // a 第一次有 inflight=1 之後不再是 minimum、所以還是 b
    expect(fA.posted).toHaveLength(1);
    expect(fB.posted).toHaveLength(1);
  });
});

// ── fan-out subscribe ──────────────────────────────────────────────

describe('Sprint 322 — fan-out subscribe', () => {
  it('任一底層 monitor emit → balancer listeners 全收', () => {
    const fA = mkFake();
    const fB = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    const lb = new WorkerLoadBalancer({ monitors: [a, b] });
    const received: ParseWorkerResponse[] = [];
    lb.subscribe((r) => received.push(r));
    fA.emit({ kind: 'success', requestId: 'a1', ast: null, parseTimeMs: 1 });
    fB.emit({ kind: 'success', requestId: 'b1', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(2);
  });
});

// ── terminate fan-out ──────────────────────────────────────────────

describe('Sprint 322 — terminate fan-out', () => {
  it('terminate 給所有 monitor', () => {
    const fA = mkFake();
    const fB = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const b = new WorkerHealthMonitor({ dispatcher: fB });
    const lb = new WorkerLoadBalancer({ monitors: [a, b] });
    lb.terminate();
    expect(fA.terminated).toBe(true);
    expect(fB.terminated).toBe(true);
  });

  it('terminate 後 post no-op', () => {
    const fA = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    const lb = new WorkerLoadBalancer({ monitors: [a] });
    lb.terminate();
    lb.post(mkReq('x'));
    expect(fA.posted).toHaveLength(0);
  });
});

// ── constructor 驗證 ─────────────────────────────────────────────

describe('Sprint 322 — constructor 驗證', () => {
  it('空 monitors 陣列 throw', () => {
    expect(() => new WorkerLoadBalancer({ monitors: [] })).toThrow(/at least 1/);
  });
});

// ── getMetrics ──────────────────────────────────────────────────

describe('Sprint 322 — getMetrics', () => {
  it('回每個 monitor 當前 metric 值', () => {
    const fA = mkFake();
    const a = new WorkerHealthMonitor({ dispatcher: fA });
    a.post(mkReq('x1'));
    a.post(mkReq('x2'));
    const lb = new WorkerLoadBalancer({ monitors: [a] });
    const m = lb.getMetrics();
    expect(m[0].metric).toBe(2);  // inflight=2
  });
});
