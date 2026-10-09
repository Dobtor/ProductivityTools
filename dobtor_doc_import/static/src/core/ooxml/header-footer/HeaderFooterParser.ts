/**
 * HeaderFooterParser — 解析 word/headerN.xml 與 word/footerN.xml
 *
 * 結構與 document.xml 的 body 相同（BlockNode[]），重用 DocumentParser.parseBodyContent
 * 的 body 走訪邏輯，避免重造段落/表格走訪。
 *
 * 目前實作層級（Phase A — Sprint 0 通電）：
 *   - 解析 <w:hdr> / <w:ftr> 根元素 → BlockNode[]
 *   - rId 由 OoxmlParser orchestrator 帶入（headerReference / footerReference）
 *
 * Phase B Sprint 1 仍維持本實作（重用 DocumentParser.parseBodyContent，
 * 已能正確解析段落 + 表格 placeholder；待 TableParser 完成後表格自動升級）。
 */

import type { BlockNode, HeaderFooterContent } from '../ast/types';
import { DocumentParser } from '../document/DocumentParser';

export class HeaderFooterParser {
  private documentParser: DocumentParser;

  /**
   * @param documentParser 可選；OoxmlParser orchestrator 注入共用 instance 以重用 TableParser 等狀態。
   *                       不傳則自建一個（lazy 建 TableParser，安全可運行）。
   */
  constructor(documentParser?: DocumentParser) {
    this.documentParser = documentParser ?? new DocumentParser();
  }

  /**
   * 解析單一 header/footer XML 字串為 HeaderFooterContent。
   *
   * @param xml header*.xml 或 footer*.xml 完整字串
   * @param rId 此 part 對應的 relationship Id（由 sectPr 指向）
   * @returns HeaderFooterContent；XML 無法解析時 content 為空陣列（不 throw）
   */
  parse(xml: string, rId: string): HeaderFooterContent {
    let content: BlockNode[] = [];
    try {
      const doc = parseXml(xml);
      const root = doc.documentElement;
      if (root) {
        // <w:hdr> 與 <w:ftr> 內部結構等同 <w:body> — 直接走訪即可
        content = this.documentParser.parseBodyContent(root);
      }
    } catch {
      // 解析失敗時降級為空內容；不影響整份文件解析
      content = [];
    }
    return { rId, content };
  }
}

// ── 共用 XML 解析 ─────────────────────────────────────────────────────────────

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'HeaderFooterParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`HeaderFooterParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
