/**
 * Node worker_threads parse worker entry — Sprint 294。
 *
 * Spawned by NodeWorkerThreadDispatcher; implements the same
 * `ParseWorkerRequest` / `ParseWorkerResponse` protocol as Sprint 292.
 *
 * 紀律 #18 PROBE scope-down：actual OoxmlParser integration deferred
 *   (structured clone of DocumentNode 含 Map 風險未解)；本 entry 使用
 *   caller 透過 workerData.parseImpl 指定的 stub function name + 接 echo /
 *   byteLength stub。Sprint 295+ polish 才接真實 parser。
 *
 * Worker 啟動接 workerData：
 *   - `parseStub`: 'echo' | 'byteLength' | 'sum-bytes' — 內建 stub function 名稱
 *   - `delayMs`: 可選 — 模擬 parse 耗時（給 timeout / cancel 測試）
 *
 * Worker 接訊息：
 *   - { kind: 'parse', requestId, bytes, timeoutMs }
 *   - { kind: 'cancel', requestId }
 *
 * Worker 回訊息：
 *   - { kind: 'success', requestId, ast, parseTimeMs }
 *   - { kind: 'error', requestId, reason, message, stack? }
 *   - { kind: 'cancelled', requestId }
 *
 * Stub function 行為：
 *   - 'echo'        → ast = bytes（原樣回；測 structured clone overhead）
 *   - 'byteLength'  → ast = { byteLength }
 *   - 'sum-bytes'   → ast = sum(bytes)（測 worker 真實 CPU 工作）
 */
import { parentPort, workerData } from 'node:worker_threads';

if (!parentPort) {
  throw new Error('[node_worker_entry] must be spawned as worker_threads worker');
}

const parseStub = (workerData && workerData.parseStub) || 'byteLength';
const delayMs = (workerData && workerData.delayMs) || 0;
const cancelled = new Set();

function runStub(bytes) {
  if (parseStub === 'echo') return bytes;
  if (parseStub === 'sum-bytes') {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    let sum = 0;
    for (let i = 0; i < u8.length; i++) sum += u8[i];
    return { sum, byteLength: u8.byteLength };
  }
  // byteLength (default)
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return { byteLength: u8.byteLength };
}

async function handleParse(req) {
  const startedAt = Date.now();
  try {
    if (cancelled.has(req.requestId)) {
      parentPort.postMessage({ kind: 'cancelled', requestId: req.requestId });
      cancelled.delete(req.requestId);
      return;
    }
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    if (cancelled.has(req.requestId)) {
      parentPort.postMessage({ kind: 'cancelled', requestId: req.requestId });
      cancelled.delete(req.requestId);
      return;
    }
    const ast = runStub(req.bytes);
    parentPort.postMessage({
      kind: 'success',
      requestId: req.requestId,
      ast,
      parseTimeMs: Date.now() - startedAt,
    });
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e));
    parentPort.postMessage({
      kind: 'error',
      requestId: req.requestId,
      reason: 'parse-error',
      message: err.message,
      stack: err.stack,
    });
  }
}

parentPort.on('message', (msg) => {
  if (!msg || typeof msg !== 'object') return;
  if (msg.kind === 'parse') {
    handleParse(msg);
  } else if (msg.kind === 'cancel') {
    cancelled.add(msg.requestId);
  }
});
