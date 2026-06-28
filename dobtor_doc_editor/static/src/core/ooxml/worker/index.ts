/**
 * Phase 7 Worker parse — barrel export（Sprint 292 spike）。
 *
 * 紀律 #18 scope-down：本 spike 為 API contract design + MainThreadDispatcher
 * fallback；真實 Worker（browser Worker / node:worker_threads）實作為未來
 * polish sprint 範圍。
 */
export type {
  ParseWorkerRequest,
  ParseWorkerResponse,
  ParseHarnessResult,
  ParseWorkerDispatcher,
} from './parse_worker_protocol';
export { ParseWorkerHarness } from './ParseWorkerHarness';
export type { ParseHarnessOptions } from './ParseWorkerHarness';
export { MainThreadDispatcher } from './MainThreadDispatcher';
export type { MainThreadDispatcherOptions, SyncParseFn } from './MainThreadDispatcher';
// Sprint 294：node:worker_threads 真實 dispatcher
export { NodeWorkerThreadDispatcher } from './NodeWorkerThreadDispatcher';
export type {
  NodeWorkerThreadDispatcherOptions,
  ParseStub,
} from './NodeWorkerThreadDispatcher';
// Sprint 299：browser Worker API 真實 dispatcher
export { BrowserWorkerDispatcher } from './BrowserWorkerDispatcher';
export type { BrowserWorkerDispatcherOptions } from './BrowserWorkerDispatcher';
// Sprint 307：worker pool round-robin（compose existing dispatchers）
export { WorkerPoolDispatcher } from './WorkerPoolDispatcher';
export type { WorkerPoolDispatcherOptions } from './WorkerPoolDispatcher';
// Sprint 312：worker observability wrapper（latency / error rate / timeout）
export { WorkerHealthMonitor } from './WorkerHealthMonitor';
export type {
  WorkerHealthStats,
  WorkerHealthMonitorOptions,
} from './WorkerHealthMonitor';
// Sprint 317：circuit breaker with primary + fallback
export { WorkerCircuitBreaker } from './WorkerCircuitBreaker';
export type {
  BreakerState,
  WorkerCircuitBreakerOptions,
  CircuitBreakerStats,
} from './WorkerCircuitBreaker';
// Sprint 322：load balancer based on WorkerHealthMonitor stats
export { WorkerLoadBalancer } from './WorkerLoadBalancer';
export type {
  LoadBalanceStrategy,
  WorkerLoadBalancerOptions,
} from './WorkerLoadBalancer';
// Sprint 327：retry wrapper with exponential backoff
export { WorkerRetryWrapper } from './WorkerRetryWrapper';
export type {
  WorkerRetryWrapperOptions,
  RetryStats,
} from './WorkerRetryWrapper';
// Sprint 332：time-series metrics collector（bucket stats given lifetime 312 stats）
export {
  WorkerMetricsCollector,
  recordSuccess,
  recordError,
  recordTimeout,
} from './WorkerMetricsCollector';
export type {
  WorkerMetricEvent,
  WorkerMetricsCollectorOptions,
  BucketStats,
} from './WorkerMetricsCollector';
// Sprint 337：threshold-based alert evaluator on bucket stats
export {
  evaluateAlertRules,
  thresholdMeanLatency,
  thresholdErrorRate,
  thresholdTimeoutCount,
  consecutiveErrorRate,
  summarizeAlerts,
} from './WorkerAlertEvaluator';
export type {
  AlertSeverity,
  AlertEvent,
  AlertRule,
  AlertSummary,
} from './WorkerAlertEvaluator';
// Sprint 342：alert cooldown wrapper（dedup by ruleName+severity）
export { WorkerAlertCooldown } from './WorkerAlertCooldown';
export type {
  WorkerAlertCooldownOptions,
  CooldownStats,
} from './WorkerAlertCooldown';
// Sprint 347：priority queue（static priority + aging anti-starvation）
export { WorkerPriorityQueue } from './WorkerPriorityQueue';
export type {
  QueueItem,
  WorkerPriorityQueueOptions,
  PriorityQueueStats,
} from './WorkerPriorityQueue';
// Sprint 352：scheduler（priority queue + concurrency 限流 dispatch）
export { WorkerScheduler } from './WorkerScheduler';
export type {
  WorkerSchedulerOptions,
  SchedulerStats,
} from './WorkerScheduler';
// Sprint 357：batch coalescer（window 收集 + maxBatchSize / 手動 flush）
export { WorkerBatchCoalescer } from './WorkerBatchCoalescer';
export type {
  WorkerBatchCoalescerOptions,
  BatchCoalescerStats,
} from './WorkerBatchCoalescer';
