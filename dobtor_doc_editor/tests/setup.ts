/**
 * vitest 全域 setup — 把 @xmldom/xmldom 的 DOMParser 注入 globalThis
 *
 * 為什麼不用 happy-dom：
 *   happy-dom 的 DOMParser 不論 mimeType 都當 HTML 解（會把 <w:p> 包在 <html><body> 中）。
 *   OOXML 主體大量使用前綴命名空間（w: / a: / wp:），HTML parser 完全無法處理。
 *
 * 為什麼選 @xmldom/xmldom：
 *   - 真 XML DOM 實作（W3C 標準）
 *   - 輕量（~30KB），無 HTML 包袱
 *   - tagName / localName / prefix / getElementsByTagName(NS) 行為與瀏覽器一致
 *
 * Production 環境（瀏覽器內 OWL 元件）使用 native DOMParser，不引用此 setup。
 */

import { DOMParser, XMLSerializer } from '@xmldom/xmldom';

(globalThis as { DOMParser?: typeof DOMParser }).DOMParser =
  DOMParser as unknown as typeof globalThis.DOMParser;

(globalThis as { XMLSerializer?: typeof XMLSerializer }).XMLSerializer =
  XMLSerializer as unknown as typeof globalThis.XMLSerializer;
