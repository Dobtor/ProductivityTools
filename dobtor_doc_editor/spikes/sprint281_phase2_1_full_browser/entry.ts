/**
 * Sprint 281 — Phase 2.1 完整鏈 browser e2e entry
 *
 * Bundle 入口：把 ShapingEngine + ShapingFontChain + FontMetrics 與所需依賴
 * 打成單一 IIFE / ESM 給 spike HTML 用。
 *
 * 鏈：
 *   1. setHbModuleLoader → 注入 browser createHarfBuzz(...) + hbjs
 *   2. loadShapingFontWithChain → fetch primary、necessary 時 fallback
 *   3. engine.measureRun → HarfBuzz shape 拿 5-field Glyph[]
 *   4. readFontMetrics → opentype.js parse 拿 ascender / descender / typoMetrics
 *   5. resolveOoxmlLineHeight → 用 metrics 算 OOXML auto / exact / atLeast 行高
 */

import {
  ShapingEngine,
  setHbModuleLoader,
  loadShapingFontWithChain,
  readFontMetrics,
  resolveOoxmlLineHeight,
} from '../../static/src/core/ooxml/font';

export {
  ShapingEngine,
  setHbModuleLoader,
  loadShapingFontWithChain,
  readFontMetrics,
  resolveOoxmlLineHeight,
};

// 暴露為 global、HTML inline script 用
(globalThis as any).Sprint281 = {
  ShapingEngine,
  setHbModuleLoader,
  loadShapingFontWithChain,
  readFontMetrics,
  resolveOoxmlLineHeight,
};
