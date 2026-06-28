/**
 * Font Pipeline — Phase D.2 / Phase 6 Layout Engine 預備
 *
 * 包含：
 *   - ShapingEngine：HarfBuzz WASM 文字成形
 *   - FontMetrics：opentype.js 讀字型核心度量（行高計算用）
 *
 * Phase D 範圍：提供類別與單測；不接到 OoxmlParser 主流程
 * Phase 6 範圍：自寫 Layout Engine 時取代 canvas-editor 的 measureText
 */

export {
  ShapingEngine,
  __resetHbForTesting,
  detectScript,
  defaultLanguageForScript,
  defaultDirectionForScript,
  // Sprint 279：browser-compat refactor — caller-injectable hbModuleLoader
  setHbModuleLoader,
  __resetHbModuleLoaderForTesting,
} from './ShapingEngine';
export type { ShapedGlyph, ShapeOptions, RunMetrics, ShapingCacheStats } from './ShapingEngine';
export {
  readFontMetrics,
  lineHeightPt,
  resolveOoxmlLineHeight,
  baselineOffsetPt,
  readOpentypeAdvances,
} from './FontMetrics';
export type { FontMetricsResult, OoxmlLineHeightResult, OpentypeAdvanceResult } from './FontMetrics';
// Sprint 280：browser/Node 通用字型 fetch + fallback chain wire-up
export {
  loadShapingFontWithChain,
  getDefaultCjkFallbackChain,
  FontChainExhaustedError,
} from './ShapingFontChain';
export type {
  ShapingFontChainEntry,
  LoadShapingFontWithChainOptions,
  LoadShapingFontResult,
} from './ShapingFontChain';
// Sprint 302：canvas-editor measureText proxy PROBE
export { TextMeasureProxy } from './TextMeasureProxy';
export type {
  MeasureRunFn,
  TextMeasureProxyOptions,
  TextMeasureCacheEntry,
} from './TextMeasureProxy';
// Sprint 303：Canvas-shape adapter on top of TextMeasureProxy
export { CanvasEditorMeasureBridge } from './CanvasEditorMeasureBridge';
export type {
  CanvasEditorMeasureBridgeOptions,
  TextMetricsLike,
} from './CanvasEditorMeasureBridge';
// Sprint 308：Canvas-editor measureText patch PROBE
export { wrapCanvasContext, canSafelyPatchPrototype } from './CanvasEditorPatchProbe';
export type {
  MinimalCanvasContextForPatch,
  WrapCanvasContextOptions,
  PatchProbeStats,
} from './CanvasEditorPatchProbe';
// Sprint 313：Canvas-editor font CSS shorthand parser
export { parseCanvasFont, formatCanvasFont } from './CanvasEditorFontResolver';
export type { ResolvedFont, ParseCanvasFontOptions } from './CanvasEditorFontResolver';
// Sprint 318：CanvasEditorPipeline 整合層（resolver + bridge + ctx 一次包好）
export { CanvasEditorPipeline } from './CanvasEditorPipeline';
export type {
  CanvasEditorPipelineOptions,
  PipelineStats,
  CanvasContextForPipeline,
} from './CanvasEditorPipeline';
// Sprint 323：heuristic prewarm strategies
export {
  collectPrewarmCandidates,
  classifyCharset,
  byTopFrequency,
  byFontFamilyWhitelist,
  byCharsetClassification,
} from './CanvasEditorPrewarmStrategy';
export type {
  PrewarmEntry,
  PrewarmEntryWithMeta,
} from './CanvasEditorPrewarmStrategy';
// Sprint 328：JSON-safe cache snapshot for cross-session persistence
export {
  CANVAS_EDITOR_CACHE_SCHEMA_VERSION,
  toSnapshot,
  fromSnapshot,
  mergeSnapshots,
  pickByMinFrequency,
  summarizeSnapshot,
} from './CanvasEditorCacheSnapshot';
export type {
  CacheSnapshotV1,
  SnapshotSummary,
} from './CanvasEditorCacheSnapshot';
// Sprint 333：cache lifecycle（LRU + TTL + invalidation predicates）
export { CanvasEditorCacheLifecycle } from './CanvasEditorCacheLifecycle';
export type {
  CacheEntry,
  CanvasEditorCacheLifecycleOptions,
  CacheLifecycleStats,
} from './CanvasEditorCacheLifecycle';
// Sprint 338：snapshot → lifecycle seeder + reverse export helpers
export {
  keyFor,
  warmFromSnapshot,
  exportLifecycleAsEntries,
  predictWarmFootprint,
} from './CanvasEditorCacheWarmer';
// Sprint 343：snapshot + lifecycle + warmer orchestration（restore/persist/dirty）
export { CanvasEditorCacheCoordinator } from './CanvasEditorCacheCoordinator';
export type {
  CacheCoordinatorOptions,
  CoordinatorStats,
} from './CanvasEditorCacheCoordinator';
// Sprint 348：round-trip safe cache key codec（escape | and \）
export {
  encodeCacheKey,
  decodeCacheKey,
  isValidCacheKey,
} from './CanvasEditorCacheKeyCodec';
export type { CacheKeyParts } from './CanvasEditorCacheKeyCodec';
// Sprint 353：multi-doc cache namespace partition（codec + lifecycle 組合）
export {
  nsKey,
  parseNsKey,
  namespacePrefix,
  invalidateNamespace,
  nsSet,
  nsGet,
  groupKeysByNamespace,
} from './CanvasEditorCacheNamespace';
export type { ParsedNsKey } from './CanvasEditorCacheNamespace';
