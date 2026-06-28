/**
 * Layout Engine 公開入口
 *
 * 用法：
 *   import { layoutDocument } from 'core/layout';
 *   const layout = layoutDocument(documentNode.sections);
 *   // layout.pages = Page[]，可直接由 Renderer 消費
 */

export type {
  Box,
  Glue,
  Penalty,
  LayoutItem,
  ParagraphInput,
  Line,
  Page,
  PageEntry,
  LinePageEntry,
  TablePageEntry,
  TableLayoutEntry,
  RowLayout,
  CellLayout,
  CellBlock,
  NestedTableInCell,
  ImagePageEntry,
  FloatImageEntry,
  DocumentLayout,
  LayoutOptions,
  TextMetrics,
} from './types';

export { EstimateMetrics, isCjkChar } from './TextMetrics';
export { FontMetricsAdapter } from './FontMetricsAdapter';
export { buildParagraph } from './BoxBuilder';
export { breakParagraph } from './LineBreaker';
export { layoutTable, layoutRow, layoutCell, allocateColumnWidths } from './TableLayout';
export { paginate, layoutDocument } from './Paginator';
