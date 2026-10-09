/**
 * Phase 7 Worker parse — 訊息協議定義（Sprint 292 spike）。
 *
 * User 指令「繼續執行 1-6」⑥ = explicit OVERRIDE（autopilot Sprint 197 final audit
 * 判定 worker 改造「不建議」cost vs benefit marginal、ChienYi 20-50p、cache
 * 五連發已 ~10× warm path 加速；user override = 仍要鋪基礎）。
 *
 * 本 sprint = SPIKE-only：定義 main thread ↔ parse worker 的訊息協議 + main-thread
 * fallback harness（無實際 Worker 啟動、為未來實際 Worker 改造鋪 API contract）。
 *
 * 紀律 #18 scope-down：不啟動真實 Worker（structured clone of AST Map/class 風險未解）；
 * 不接 production parse pipeline（OoxmlParser 主流程不變）。
 * 紀律 #21：本 spike 為 read-only API design + tests、不污染 VR pipeline。
 */

/**
 * Worker 接收訊息：parse 請求或 cancel。
 *
 * - `parse`：交付 docx zip bytes + requestId（caller 用此匹配 response）
 * - `cancel`：取消進行中的 parse（caller 不再關心結果）
 */
export type ParseWorkerRequest =
  | {
      kind: 'parse';
      requestId: string;
      bytes: Uint8Array | ArrayBuffer;
      /** 可選 timeout（ms、預設 60000）；逾時 worker 回 'timeout' error */
      timeoutMs?: number;
    }
  | {
      kind: 'cancel';
      requestId: string;
    };

/**
 * Worker 回送訊息：success / error / progress（可選）/ cancelled。
 *
 * - `success`：完整 AST（結構化複製安全；DocumentNode 內 Map 由 structuredClone 序列化）
 * - `error`：error 含可讀 message + 可選 stack；reason 可分類給 caller decide retry
 * - `progress`：parse 進度回報（0..1）；caller 可顯示 spinner（optional emit）
 * - `cancelled`：caller 之前 cancel 過、worker 已停下
 */
export type ParseWorkerResponse =
  | {
      kind: 'success';
      requestId: string;
      /** DocumentNode；caller 自行 cast 為實際型別 */
      ast: unknown;
      /** parser 端量得的 parse time（ms、worker thread 內） */
      parseTimeMs: number;
    }
  | {
      kind: 'error';
      requestId: string;
      reason: 'parse-error' | 'timeout' | 'unknown';
      message: string;
      stack?: string;
    }
  | {
      kind: 'progress';
      requestId: string;
      progress: number;
    }
  | {
      kind: 'cancelled';
      requestId: string;
    };

/**
 * Harness 對外暴露的單次 parse 結果（resolve 內容；error 走 reject）。
 */
export interface ParseHarnessResult {
  ast: unknown;
  parseTimeMs: number;
  /** harness 量到的 wall-clock time（含 postMessage + structured clone overhead） */
  wallClockMs: number;
}

/**
 * Worker dispatcher 抽象 — 把實際 Worker / worker_threads / main-thread fallback
 * 包成同一個 ContractAPI；harness 不知道下面是真 worker 還是 main thread。
 *
 * - `post`: send request → worker
 * - `subscribe`: 收 worker 回的 response（caller 從 requestId 匹配）
 * - `terminate`: 釋放底層 Worker（main-thread fallback 為 no-op）
 */
export interface ParseWorkerDispatcher {
  post(request: ParseWorkerRequest): void;
  subscribe(listener: (response: ParseWorkerResponse) => void): () => void;
  terminate(): void;
}
