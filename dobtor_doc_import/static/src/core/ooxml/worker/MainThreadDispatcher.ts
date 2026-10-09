/**
 * MainThreadDispatcher — 不啟動真實 Worker、在 main thread 同步執行 parse
 * 的 fallback 實作（Sprint 292）。
 *
 * 用途：
 *   1. 環境不支援 Worker（舊瀏覽器 / SSR / Node 內 cache miss）→ graceful degrade
 *   2. 測試：harness API contract 驗證不需開真 worker
 *   3. 未來 polish sprint：把實際 worker_threads / browser Worker 實作放在另一個
 *      dispatcher、harness 介面不變、可無痛切換
 *
 * 紀律 #18 scope-down：不在 main thread 偽裝 async 行為（直接同步 emit response、
 * setTimeout 0 確保 caller 完成 subscribe 才收到、避免 race）。
 */
import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

/** caller 注入的同步 parse 函式（給 main-thread fallback 直接 call） */
export type SyncParseFn = (bytes: Uint8Array | ArrayBuffer) => Promise<unknown> | unknown;

export interface MainThreadDispatcherOptions {
  parse: SyncParseFn;
}

export class MainThreadDispatcher implements ParseWorkerDispatcher {
  private readonly parseImpl: SyncParseFn;
  private readonly listeners = new Set<(response: ParseWorkerResponse) => void>();
  private readonly cancelled = new Set<string>();

  constructor(opts: MainThreadDispatcherOptions) {
    this.parseImpl = opts.parse;
  }

  post(request: ParseWorkerRequest): void {
    if (request.kind === 'cancel') {
      this.cancelled.add(request.requestId);
      // emit cancelled async（讓 harness 來得及 dequeue pending）
      queueMicrotask(() => {
        this.emit({ kind: 'cancelled', requestId: request.requestId });
      });
      return;
    }
    // parse
    const startedAt = Date.now();
    Promise.resolve().then(async () => {
      try {
        if (this.cancelled.has(request.requestId)) {
          this.emit({ kind: 'cancelled', requestId: request.requestId });
          return;
        }
        const ast = await this.parseImpl(request.bytes);
        if (this.cancelled.has(request.requestId)) {
          this.emit({ kind: 'cancelled', requestId: request.requestId });
          return;
        }
        this.emit({
          kind: 'success',
          requestId: request.requestId,
          ast,
          parseTimeMs: Date.now() - startedAt,
        });
      } catch (e) {
        const err = e instanceof Error ? e : new Error(String(e));
        this.emit({
          kind: 'error',
          requestId: request.requestId,
          reason: 'parse-error',
          message: err.message,
          stack: err.stack,
        });
      }
    });
  }

  subscribe(listener: (response: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  terminate(): void {
    this.listeners.clear();
    this.cancelled.clear();
  }

  private emit(response: ParseWorkerResponse): void {
    for (const l of this.listeners) {
      try {
        l(response);
      } catch {
        // listener throw 不影響其他 listener
      }
    }
  }
}
