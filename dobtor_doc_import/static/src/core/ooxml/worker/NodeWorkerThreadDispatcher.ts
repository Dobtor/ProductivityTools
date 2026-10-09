/**
 * NodeWorkerThreadDispatcher — Sprint 294。
 *
 * 真實 node:worker_threads dispatcher 實作。實作 ParseWorkerDispatcher
 * interface（Sprint 292），可與 ParseWorkerHarness 共用。
 *
 * 範圍（PROBE）：
 *   - 啟動 worker_threads.Worker 載入 node_worker_entry.mjs
 *   - postMessage / on('message') 接 protocol
 *   - terminate 釋放 worker
 *   - workerData 帶 parseStub 名稱 + 可選 delayMs（測試用）
 *
 * 紀律 #18 scope-down：actual OoxmlParser inside worker 為 future polish
 *   sprint（structured clone of DocumentNode 含 Map 風險未解）；本 dispatcher
 *   只跑 stub function（echo / byteLength / sum-bytes）。
 *
 * 紀律 #21：worker 為 isolated process、不污染 main thread 的 OoxmlParser /
 *   VR pipeline / layout / render。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

/** node_worker_entry.mjs 接受的 stub function name。 */
export type ParseStub = 'echo' | 'byteLength' | 'sum-bytes';

export interface NodeWorkerThreadDispatcherOptions {
  /** stub function name；預設 'byteLength' */
  parseStub?: ParseStub;
  /** worker 內部 parse 前的 delay（ms）；給 timeout / cancel 測試用 */
  delayMs?: number;
  /** worker entry 路徑；預設取本 module 旁的 node_worker_entry.mjs */
  workerScriptUrl?: URL;
}

interface NodeWorkerThreadsModule {
  Worker: new (
    file: string | URL,
    opts?: { workerData?: unknown; eval?: boolean },
  ) => NodeWorker;
}

interface NodeWorker {
  postMessage(value: unknown): void;
  on(event: 'message', listener: (value: unknown) => void): void;
  on(event: 'error', listener: (err: Error) => void): void;
  on(event: 'exit', listener: (code: number) => void): void;
  terminate(): Promise<number>;
}

/**
 * 載入 node:worker_threads（dynamic import，避免 browser bundle 撞）。
 */
async function loadWorkerThreads(): Promise<NodeWorkerThreadsModule> {
  const mod = await import('node:worker_threads');
  return mod as unknown as NodeWorkerThreadsModule;
}

export class NodeWorkerThreadDispatcher implements ParseWorkerDispatcher {
  private worker?: NodeWorker;
  private readonly ready: Promise<void>;
  private readonly listeners = new Set<(response: ParseWorkerResponse) => void>();
  private readonly pendingPosts: ParseWorkerRequest[] = [];
  private disposed = false;
  private readonly errorListeners = new Set<(err: Error) => void>();

  constructor(opts: NodeWorkerThreadDispatcherOptions = {}) {
    const scriptUrl =
      opts.workerScriptUrl
      ?? new URL('./node_worker_entry.mjs', import.meta.url);
    this.ready = (async () => {
      const wt = await loadWorkerThreads();
      const worker = new wt.Worker(scriptUrl, {
        workerData: {
          parseStub: opts.parseStub ?? 'byteLength',
          delayMs: opts.delayMs ?? 0,
        },
      });
      worker.on('message', (msg) => {
        if (this.disposed) return;
        // msg 是 ParseWorkerResponse
        for (const l of this.listeners) {
          try {
            l(msg as ParseWorkerResponse);
          } catch {
            // listener 自己崩潰不影響其他
          }
        }
      });
      worker.on('error', (err) => {
        for (const l of this.errorListeners) {
          try {
            l(err);
          } catch {
            // ignore
          }
        }
      });
      this.worker = worker;
      // 處理啟動前 queue 的訊息
      for (const req of this.pendingPosts) {
        worker.postMessage(req);
      }
      this.pendingPosts.length = 0;
    })();
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    if (!this.worker) {
      this.pendingPosts.push(request);
      return;
    }
    this.worker.postMessage(request);
  }

  subscribe(listener: (response: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** 暴露 onError 觀察（給測試 / 上層診斷用）。 */
  onError(listener: (err: Error) => void): () => void {
    this.errorListeners.add(listener);
    return () => {
      this.errorListeners.delete(listener);
    };
  }

  /** 等到底層 worker 已啟動（給測試確保 race-free）。 */
  async waitReady(): Promise<void> {
    await this.ready;
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.listeners.clear();
    this.errorListeners.clear();
    if (this.worker) {
      // fire-and-forget; caller 用 dispose 時不關心 exit code
      this.worker.terminate().catch(() => undefined);
      this.worker = undefined;
    }
  }
}
