/**
 * ParseWorkerHarness — 給 caller 用的 high-level Promise-based API（Sprint 292）。
 *
 * Wraps a `ParseWorkerDispatcher`（真 Worker / worker_threads / main-thread fallback）
 * 為 `async parse(bytes) → Promise<ParseHarnessResult>`。
 *
 * 紀律 #18：本 harness 不啟動 Worker；caller 注入已 ready 的 dispatcher。
 */
import type {
  ParseHarnessResult,
  ParseWorkerDispatcher,
  ParseWorkerRequest,
  ParseWorkerResponse,
} from './parse_worker_protocol';

export interface ParseHarnessOptions {
  dispatcher: ParseWorkerDispatcher;
  /** parse timeout（ms、預設 60000） */
  defaultTimeoutMs?: number;
  /** progress callback（如有） */
  onProgress?: (progress: number) => void;
}

export class ParseWorkerHarness {
  private readonly dispatcher: ParseWorkerDispatcher;
  private readonly defaultTimeoutMs: number;
  private readonly onProgress?: (progress: number) => void;
  private readonly unsubscribe: () => void;
  private readonly pending = new Map<
    string,
    {
      resolve: (result: ParseHarnessResult) => void;
      reject: (err: Error) => void;
      startedAt: number;
      timer?: ReturnType<typeof setTimeout>;
    }
  >();
  private requestSeq = 0;

  constructor(opts: ParseHarnessOptions) {
    this.dispatcher = opts.dispatcher;
    this.defaultTimeoutMs = opts.defaultTimeoutMs ?? 60_000;
    this.onProgress = opts.onProgress;
    this.unsubscribe = this.dispatcher.subscribe((r) => this.handleResponse(r));
  }

  private nextRequestId(): string {
    this.requestSeq++;
    return `parse-${Date.now()}-${this.requestSeq}`;
  }

  private handleResponse(response: ParseWorkerResponse): void {
    if (response.kind === 'progress') {
      this.onProgress?.(response.progress);
      return;
    }
    const entry = this.pending.get(response.requestId);
    if (!entry) return; // unknown requestId — could be late after cancel
    if (entry.timer) clearTimeout(entry.timer);
    this.pending.delete(response.requestId);
    if (response.kind === 'success') {
      entry.resolve({
        ast: response.ast,
        parseTimeMs: response.parseTimeMs,
        wallClockMs: Date.now() - entry.startedAt,
      });
    } else if (response.kind === 'error') {
      const err = new Error(`[ParseWorker] ${response.reason}: ${response.message}`);
      if (response.stack) err.stack = response.stack;
      entry.reject(err);
    } else {
      // cancelled
      entry.reject(new Error('[ParseWorker] cancelled'));
    }
  }

  parse(bytes: Uint8Array | ArrayBuffer, timeoutMs?: number): Promise<ParseHarnessResult> {
    const requestId = this.nextRequestId();
    const effectiveTimeout = timeoutMs ?? this.defaultTimeoutMs;
    return new Promise<ParseHarnessResult>((resolve, reject) => {
      const entry = { resolve, reject, startedAt: Date.now(), timer: undefined as ReturnType<typeof setTimeout> | undefined };
      this.pending.set(requestId, entry);
      entry.timer = setTimeout(() => {
        if (this.pending.delete(requestId)) {
          this.dispatcher.post({ kind: 'cancel', requestId });
          reject(new Error(`[ParseWorker] timeout after ${effectiveTimeout}ms`));
        }
      }, effectiveTimeout);
      const request: ParseWorkerRequest = { kind: 'parse', requestId, bytes, timeoutMs: effectiveTimeout };
      this.dispatcher.post(request);
    });
  }

  cancel(requestId: string): void {
    const entry = this.pending.get(requestId);
    if (!entry) return;
    if (entry.timer) clearTimeout(entry.timer);
    this.pending.delete(requestId);
    this.dispatcher.post({ kind: 'cancel', requestId });
    entry.reject(new Error('[ParseWorker] cancelled by caller'));
  }

  /** 釋放 dispatcher 底層 worker；之後 parse() 行為 undefined */
  dispose(): void {
    this.unsubscribe();
    this.dispatcher.terminate();
    // reject all pending
    for (const [, entry] of this.pending) {
      if (entry.timer) clearTimeout(entry.timer);
      entry.reject(new Error('[ParseWorker] disposed'));
    }
    this.pending.clear();
  }
}
