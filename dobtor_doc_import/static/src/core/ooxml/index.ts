/**
 * OOXML Parser 主入口
 *
 * 此檔案是 rollup.config.js 的 input。
 * Phase 1 之前僅做 re-export 與 stub 驗證，build 鏈不能斷。
 */

export { OoxmlParser, __DOBTOR_OOXML_STUB__ } from './OoxmlParser';
export type { ParseOptions } from './OoxmlParser';

// AST 型別對外
export type * from './ast/types';

// 子模組對外（讓上層可單獨 import 子 Parser 做組合測試）
export { PackageReader } from './package';
export type { PackagePart, RelationshipDef, OoxmlPackage } from './package';
export { DocumentParser, ParagraphParser } from './document';
export { TableParser, GridResolver } from './table';
export { StyleResolver } from './styles';
export { NumberingResolver } from './numbering';
export { SectionParser } from './section';
export { HeaderFooterParser } from './header-footer';
export { DrawingParser } from './drawing';
export { ToCanvasEditor } from './mapper';
export type { CEElement } from './mapper';
export * as Units from './units';
export { parseDocProps, parseDocPropsXml } from './DocPropsParser';
