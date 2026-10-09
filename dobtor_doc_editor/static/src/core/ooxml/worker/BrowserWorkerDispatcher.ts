/**
 * BrowserWorkerDispatcher — Sprint 299。
 *
 * 真實 browser `Worker` API dispatcher 實作；mirror of Sprint 294
 * `NodeWorkerThreadDispatcher`，用同一 `ParseWorkerDispatcher` interface（Sprint 292）。
 *
 * 範圍（PROBE）：
 *   - 啟動 browser Worker（caller 注入 worker script URL 或 Blob URL）
 *   - postMessage / 'message' event listener 接 protocol
 *   - terminate 釋放 Worker
 *   - 不啟動真實 OoxmlParser（與 Sprint 294 一致、留 future polish）
 *
 * 紀律 #18 scope-down：actual OoxmlParser inside worker 為 future polish
 *   sprint（structured clone of DocumentNode 含 Map / class instance 風險未解）。
 *   本 dispatcher 接 caller 提供的 worker script、不假設其內容。
 *
 * 紀律 #21：worker 為 isolated context、不污染 main thread。
 */

import type {
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

/**
 * Browser Worker 構造選項。
 *
 * 兩種 worker 來源：
 *   1. `scriptUrl`：caller 提供已 deploy 的 worker script URL（推薦 production 用）
 *   2. `inlineScript`：caller 提供 worker source code 字串；dispatcher 用
 *      Blob URL 即時包出 Worker（測試 / spike 用）
 */
export interface BrowserWorkerDispatcherOptions {
  /** 真實 worker script URL（與 inlineScript 二選一） */
  scriptUrl?: string | URL;
  /** Worker source code 字串（與 scriptUrl 二選一；自動 Blob.URL 包） */
  inlineScript?: string;
  /** Worker 構造選項（passthrough、'type': 'module' 等） */
  workerOptions?: WorkerOptions;
}

/** Caller 必須提供 globalThis.Worker（測試 polyfill / production browser native）。 */
type WorkerCtor = typeof Worker;

function getWorkerCtor(): WorkerCtor {
  const W = (globalThis as { Worker?: WorkerCtor }).Worker;
  if (!W) {
    throw new Error('[BrowserWorkerDispatcher] globalThis.Worker not available; this dispatcher needs a browser environment or Worker polyfill');
  }
  return W;
}

function makeBlobUrl(source: string): string {
  const blob = new Blob([source], { type: 'text/javascript' });
  return URL.createObjectURL(blob);
}

export class BrowserWorkerDispatcher implements ParseWorkerDispatcher {
  private readonly worker: Worker;
  private readonly listeners = new Set<(response: ParseWorkerResponse) => void>();
  private readonly blobUrl?: string;
  private disposed = false;

  constructor(opts: BrowserWorkerDispatcherOptions) {
    if (!opts.scriptUrl && !opts.inlineScript) {
      throw new Error('[BrowserWorkerDispatcher] must provide either scriptUrl or inlineScript');
    }
    const W = getWorkerCtor();
    let url: string | URL;
    if (opts.inlineScript) {
      this.blobUrl = makeBlobUrl(opts.inlineScript);
      url = this.blobUrl;
    } else {
      url = opts.scriptUrl as string | URL;
    }
    this.worker = new W(url, opts.workerOptions);
    this.worker.addEventListener('message', (ev) => {
      if (this.disposed) return;
      const response = (ev as MessageEvent<unknown>).data as ParseWorkerResponse;
      for (const l of this.listeners) {
        try {
          l(response);
        } catch {
          // listener 自己崩潰不影響其他
        }
      }
    });
  }

  post(request: ParseWorkerRequest): void {
    if (this.disposed) return;
    this.worker.postMessage(request);
  }

  subscribe(listener: (response: ParseWorkerResponse) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  terminate(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.listeners.clear();
    this.worker.terminate();
    if (this.blobUrl) {
      try {
        URL.revokeObjectURL(this.blobUrl);
      } catch {
        // ignore
      }
    }
  }
}
