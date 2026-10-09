/**
 * Sprint 317 — ⑥ deeper⁴：WorkerCircuitBreaker。
 *
 * Sprint 292/294/299/307/312 之後第四輪深推。Circuit breaker 三狀態：
 *   closed → 錯誤率超閾值 → open → cooldown → half-open → probe 成功 → closed
 *                                                     → probe 失敗 → open
 *
 * 紀律 #18 scope-down：記憶體 state machine、caller 提供 clock；最近 N 筆 window
 *   而非時間 window。
 */
import { describe, expect, it } from 'vitest';

import { WorkerCircuitBreaker } from '../../static/src/core/ooxml/worker/WorkerCircuitBreaker';
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

function ok(id: string): ParseWorkerResponse {
  return { kind: 'success', requestId: id, ast: null, parseTimeMs: 1 };
}

function err(id: string): ParseWorkerResponse {
  return { kind: 'error', requestId: id, reason: 'parse-error', message: 'boom' };
}

// ── closed：路由給 primary ────────────────────────────────────────────

describe('Sprint 317 — closed 狀態', () => {
  it('全部 post 走 primary、fallback 不收', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    cb.post(mkReq('r1'));
    cb.post(mkReq('r2'));
    expect(p.posted).toHaveLength(2);
    expect(f.posted).toHaveLength(0);
    expect(cb.getStats().state).toBe('closed');
  });
});

// ── closed → open：錯誤率閾值 ──────────────────────────────────────────

describe('Sprint 317 — closed → open transition', () => {
  it('5 筆 sample 全錯 → open', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f, minSamples: 5, errorRateThreshold: 0.5 });
    for (let i = 0; i < 5; i++) {
      cb.post(mkReq(`r${i}`));
      p.emit(err(`r${i}`));
    }
    expect(cb.getStats().state).toBe('open');
    expect(cb.getStats().openCount).toBe(1);
  });

  it('< minSamples 時不 open', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f, minSamples: 5 });
    for (let i = 0; i < 3; i++) {
      cb.post(mkReq(`r${i}`));
      p.emit(err(`r${i}`));
    }
    expect(cb.getStats().state).toBe('closed');
  });

  it('錯誤率 < threshold 不 open', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f, minSamples: 5, errorRateThreshold: 0.8 });
    // 5 筆裡 3 錯 2 對 = 0.6 < 0.8
    const results = [err, err, err, ok, ok];
    for (let i = 0; i < 5; i++) {
      cb.post(mkReq(`r${i}`));
      p.emit(results[i](`r${i}`));
    }
    expect(cb.getStats().state).toBe('closed');
  });
});

// ── open：路由給 fallback ───────────────────────────────────────────

describe('Sprint 317 — open 狀態', () => {
  it('open 之後所有 post 走 fallback', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    cb.forceState('open');
    cb.post(mkReq('a'));
    cb.post(mkReq('b'));
    expect(p.posted).toHaveLength(0);
    expect(f.posted).toHaveLength(2);
  });
});

// ── open → half-open：cooldown ────────────────────────────────────────

describe('Sprint 317 — open → half-open cooldown', () => {
  it('cooldown 過了、next post 進 half-open + probe 走 primary', () => {
    const p = mkFake(); const f = mkFake();
    let t = 1000;
    const cb = new WorkerCircuitBreaker({
      primary: p, fallback: f, cooldownMs: 500, now: () => t,
    });
    cb.forceState('open');
    t = 1100;  // 未到 cooldown
    cb.post(mkReq('a'));
    expect(f.posted).toHaveLength(1);
    expect(cb.getStats().state).toBe('open');

    t = 1600;  // 過 cooldown
    cb.post(mkReq('b'));
    expect(p.posted).toHaveLength(1); // probe 給 primary
    expect(cb.getStats().state).toBe('half-open');
  });

  it('half-open probe 成功 → closed', () => {
    const p = mkFake(); const f = mkFake();
    let t = 0;
    const cb = new WorkerCircuitBreaker({
      primary: p, fallback: f, cooldownMs: 100, now: () => t,
    });
    cb.forceState('open');
    t = 200;
    cb.post(mkReq('probe'));
    expect(cb.getStats().state).toBe('half-open');
    p.emit(ok('probe'));
    expect(cb.getStats().state).toBe('closed');
  });

  it('half-open probe 失敗 → 回 open', () => {
    const p = mkFake(); const f = mkFake();
    let t = 0;
    const cb = new WorkerCircuitBreaker({
      primary: p, fallback: f, cooldownMs: 100, now: () => t,
    });
    cb.forceState('open');
    const initialOpenCount = cb.getStats().openCount;
    t = 200;
    cb.post(mkReq('probe'));
    p.emit(err('probe'));
    expect(cb.getStats().state).toBe('open');
    expect(cb.getStats().openCount).toBeGreaterThan(initialOpenCount);
  });

  it('half-open 期間：probe pending、其他 post 走 fallback', () => {
    const p = mkFake(); const f = mkFake();
    let t = 0;
    const cb = new WorkerCircuitBreaker({
      primary: p, fallback: f, cooldownMs: 100, now: () => t,
    });
    cb.forceState('open');
    t = 200;
    cb.post(mkReq('probe'));  // primary
    cb.post(mkReq('next1'));  // fallback (probe still pending)
    cb.post(mkReq('next2'));  // fallback
    expect(p.posted.map((r) => 'requestId' in r ? r.requestId : '')).toEqual(['probe']);
    expect(f.posted).toHaveLength(2);
  });
});

// ── stats 累積 ─────────────────────────────────────────────────────

describe('Sprint 317 — stats 累積', () => {
  it('primary success / error 計次', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f, minSamples: 100 }); // 不 trigger open
    cb.post(mkReq('a'));
    p.emit(ok('a'));
    cb.post(mkReq('b'));
    p.emit(err('b'));
    const s = cb.getStats();
    expect(s.primarySuccess).toBe(1);
    expect(s.primaryError).toBe(1);
    expect(s.recentErrorRate).toBe(0.5);
  });

  it('fallback success / error 計次', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    cb.forceState('open');
    cb.post(mkReq('a'));
    f.emit(ok('a'));
    cb.post(mkReq('b'));
    f.emit(err('b'));
    const s = cb.getStats();
    expect(s.fallbackSuccess).toBe(1);
    expect(s.fallbackError).toBe(1);
  });
});

// ── terminate ────────────────────────────────────────────────────────

describe('Sprint 317 — terminate', () => {
  it('terminate fan-out 給 primary + fallback', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    cb.terminate();
    expect(p.terminated).toBe(true);
    expect(f.terminated).toBe(true);
  });

  it('terminate 後 post no-op', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    cb.terminate();
    cb.post(mkReq('z'));
    expect(p.posted).toHaveLength(0);
    expect(f.posted).toHaveLength(0);
  });
});

// ── listener fan-out ────────────────────────────────────────────────

describe('Sprint 317 — listener fan-out', () => {
  it('primary 與 fallback emit 都轉發給 listener', () => {
    const p = mkFake(); const f = mkFake();
    const cb = new WorkerCircuitBreaker({ primary: p, fallback: f });
    const received: ParseWorkerResponse[] = [];
    cb.subscribe((r) => received.push(r));
    p.emit(ok('a'));
    f.emit(ok('b'));
    expect(received).toHaveLength(2);
  });
});
