/**
 * Sprint 312 — ⑥ deeper³：WorkerHealthMonitor。
 *
 * Sprint 292/294/299/307 worker cluster 第三輪深推。本 sprint 補
 * observability wrapper：latency / error rate / timeout 累積。
 *
 * 紀律 #18 scope-down：不接 production monitoring（caller decide export）；
 *   不主動 alert；不做 sliding window。
 */
import { describe, expect, it } from 'vitest';

import { WorkerHealthMonitor } from '../../static/src/core/ooxml/worker/WorkerHealthMonitor';
import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from '../../static/src/core/ooxml/worker/parse_worker_protocol';

/** Controllable fake dispatcher + fake clock. */
function mkFake() {
  const listeners: Array<(r: ParseWorkerResponse) => void> = [];
  const posted: ParseWorkerRequest[] = [];
  let terminated = false;
  const fake: ParseWorkerDispatcher & { emit: (r: ParseWorkerResponse) => void; terminated: boolean } = {
    post(req) { posted.push(req); },
    subscribe(l) { listeners.push(l); return () => { const i = listeners.indexOf(l); if (i >= 0) listeners.splice(i, 1); }; },
    terminate() { terminated = true; },
    emit(r) { for (const l of listeners) l(r); },
    get terminated() { return terminated; },
    set terminated(v) { terminated = v; },
  };
  return { fake, posted };
}

function mkReq(id: string): ParseWorkerRequest {
  return { kind: 'parse', requestId: id, bytes: new Uint8Array(0) };
}

// ── post / response latency 記帳 ─────────────────────────────────────────

describe('Sprint 312 — latency 記帳', () => {
  it('post → success：記下 elapsed', () => {
    const { fake } = mkFake();
    let t = 100;
    const monitor = new WorkerHealthMonitor({ dispatcher: fake, now: () => t });
    monitor.post(mkReq('r1'));
    t = 130;
    fake.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    const s = monitor.getStats();
    expect(s.successCount).toBe(1);
    expect(s.meanLatencyMs).toBe(30);
  });

  it('多筆完成 → mean / p50 / p95 計算', () => {
    const { fake } = mkFake();
    let t = 0;
    const monitor = new WorkerHealthMonitor({ dispatcher: fake, now: () => t });
    // 5 筆，elapsed 10/20/30/40/100
    const elapsed = [10, 20, 30, 40, 100];
    for (let i = 0; i < elapsed.length; i++) {
      t = 0;
      monitor.post(mkReq(`r${i}`));
      t = elapsed[i];
      fake.emit({ kind: 'success', requestId: `r${i}`, ast: null, parseTimeMs: 1 });
    }
    const s = monitor.getStats();
    expect(s.meanLatencyMs).toBe(40); // (10+20+30+40+100)/5
    expect(s.p50LatencyMs).toBe(30);
    expect(s.p95LatencyMs).toBe(100);
  });
});

// ── error 累積 ─────────────────────────────────────────────────────────

describe('Sprint 312 — error rate', () => {
  it('混合 success + error → errorRate 計算', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.post(mkReq('a'));
    monitor.post(mkReq('b'));
    monitor.post(mkReq('c'));
    fake.emit({ kind: 'success', requestId: 'a', ast: null, parseTimeMs: 1 });
    fake.emit({ kind: 'error', requestId: 'b', reason: 'parse-error', message: 'x' });
    fake.emit({ kind: 'error', requestId: 'c', reason: 'parse-error', message: 'y' });
    const s = monitor.getStats();
    expect(s.successCount).toBe(1);
    expect(s.errorCount).toBe(2);
    expect(s.errorRate).toBeCloseTo(2 / 3);
  });

  it('0 完成 → errorRate 0', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    expect(monitor.getStats().errorRate).toBe(0);
  });
});

// ── recordTimeout ─────────────────────────────────────────────────────

describe('Sprint 312 — recordTimeout', () => {
  it('inflight 中的 request 標 timeout → timeoutCount + inflight 移除', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.post(mkReq('r1'));
    expect(monitor.getStats().inflightCount).toBe(1);
    monitor.recordTimeout('r1');
    const s = monitor.getStats();
    expect(s.timeoutCount).toBe(1);
    expect(s.inflightCount).toBe(0);
  });

  it('非 inflight 的 requestId 不增 timeoutCount', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.recordTimeout('never-posted');
    expect(monitor.getStats().timeoutCount).toBe(0);
  });
});

// ── fan-out subscribe ──────────────────────────────────────────────────

describe('Sprint 312 — listener fan-out', () => {
  it('底層 emit → monitor subscribers 也收到', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    const received: ParseWorkerResponse[] = [];
    monitor.subscribe((r) => received.push(r));
    monitor.post(mkReq('r1'));
    fake.emit({ kind: 'success', requestId: 'r1', ast: 'ok', parseTimeMs: 1 });
    expect(received).toHaveLength(1);
  });

  it('unsubscribe 後不再收', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    const received: ParseWorkerResponse[] = [];
    const unsub = monitor.subscribe((r) => received.push(r));
    unsub();
    fake.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(0);
  });
});

// ── terminate fan-out ─────────────────────────────────────────────────

describe('Sprint 312 — terminate fan-out', () => {
  it('terminate 後 fan-out 給底層 dispatcher', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.terminate();
    expect(fake.terminated).toBe(true);
  });

  it('terminate 後 post no-op', () => {
    const { fake, posted } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.terminate();
    monitor.post(mkReq('r1'));
    expect(posted).toHaveLength(0);
  });

  it('terminate 後底層 emit 不傳給 listener', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    const received: ParseWorkerResponse[] = [];
    monitor.subscribe((r) => received.push(r));
    monitor.terminate();
    fake.emit({ kind: 'success', requestId: 'z', ast: null, parseTimeMs: 1 });
    expect(received).toHaveLength(0);
  });
});

// ── clearStats ─────────────────────────────────────────────────────────

describe('Sprint 312 — clearStats', () => {
  it('清掉 latencies + counts、但不影響 inflight', () => {
    const { fake } = mkFake();
    const monitor = new WorkerHealthMonitor({ dispatcher: fake });
    monitor.post(mkReq('r1'));
    fake.emit({ kind: 'success', requestId: 'r1', ast: null, parseTimeMs: 1 });
    monitor.post(mkReq('r2')); // 仍 inflight
    monitor.clearStats();
    const s = monitor.getStats();
    expect(s.postCount).toBe(0);
    expect(s.successCount).toBe(0);
    expect(s.meanLatencyMs).toBe(0);
    expect(s.inflightCount).toBe(1); // 仍有 r2 inflight
  });
});
