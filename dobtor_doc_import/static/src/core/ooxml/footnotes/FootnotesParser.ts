/**
 * FootnotesParser — 解析 word/footnotes.xml 與 word/endnotes.xml
 *
 * Sprint 145(Phase 3.6 capture-only):
 *   - 規畫書 §11.2 行 2「Phase 3.6 註腳 / 尾註:30% 政府文件需求」
 *   - 當前 42 fixture footnoteReference 0 出現(雖每個 docx 都有 footnotes.xml/endnotes.xml part)
 *   - **本 sprint 只做 parser、不做 layout/render wire-up**(同 Sprint 134 textAlignment/framePr 模式)
 *   - 為將來 user 提供含 footnoteReference fixture 時的 wire-up 鋪路
 *
 * Footnote 結構(OOXML §17.11):
 *   <w:footnotes>
 *     <w:footnote w:type="separator" w:id="-1">
 *       <w:p><w:r><w:separator/></w:r></w:p>
 *     </w:footnote>
 *     <w:footnote w:type="continuationSeparator" w:id="0">
 *       <w:p><w:r><w:continuationSeparator/></w:r></w:p>
 *     </w:footnote>
 *     <w:footnote w:id="1">
 *       <w:p>...一般 footnote 內容...</w:p>
 *     </w:footnote>
 *   </w:footnotes>
 *
 * Endnote 結構同 footnote、僅根元素為 <w:endnotes> / <w:endnote>。
 *
 * w:type 可能值(ECMA-376 §17.11.21):
 *   - 未設(普通 footnote 內容):一般用 footnoteReference 引用
 *   - "separator":footnote 區頂端的分隔線
 *   - "continuationSeparator":跨頁延續的分隔線
 *   - "continuationNotice":跨頁延續提示文字
 *
 * w:id:
 *   - -1:separator(預設)
 *   - 0:continuationSeparator(預設)
 *   - 1+:普通 footnote 內容(被 footnoteReference 引用)
 *
 * 重用 DocumentParser.parseBodyContent 解析 footnote 內部段落 + 表格,
 * 與 HeaderFooterParser 模式對齊。
 */

import type { BlockNode, FootnoteContent } from '../ast/types';
import { DocumentParser } from '../document/DocumentParser';

export class FootnotesParser {
  private documentParser: DocumentParser;

  /**
   * @param documentParser 可選;OoxmlParser orchestrator 注入共用 instance 以重用 TableParser 等狀態。
   *                       不傳則自建一個。
   */
  constructor(documentParser?: DocumentParser) {
    this.documentParser = documentParser ?? new DocumentParser();
  }

  /**
   * 解析 word/footnotes.xml(或 endnotes.xml)為 Map<id, FootnoteContent>。
   *
   * @param xml footnotes.xml / endnotes.xml 完整字串;undefined / 空 → 回空 Map
   * @returns Map<id, FootnoteContent>;id 是 footnote 的 w:id 整數
   *          ;XML 無法解析時回空 Map(不 throw)
   */
  parse(xml: string | undefined): Map<number, FootnoteContent> {
    const out = new Map<number, FootnoteContent>();
    if (!xml) return out;

    try {
      const doc = parseXml(xml);
      const root = doc.documentElement;
      if (!root) return out;

      // 收集所有 <w:footnote> 或 <w:endnote> 直接子元素(根節點下)
      // 用 tagName endsWith 容忍 endnotes.xml(<w:endnote>)和 footnotes.xml(<w:footnote>)
      const cs = root.childNodes;
      for (let i = 0; i < cs.length; i++) {
        const n = cs[i];
        if (n.nodeType !== 1) continue;
        const el = n as Element;
        // 允許 w:footnote 或 w:endnote
        if (el.tagName !== 'w:footnote' && el.tagName !== 'w:endnote') continue;

        const idRaw = el.getAttribute('w:id');
        if (idRaw === null) continue;
        const id = parseInt(idRaw, 10);
        if (!Number.isFinite(id)) continue;

        const typeRaw = el.getAttribute('w:type') ?? undefined;
        const type = normalizeType(typeRaw);

        // 內部結構等同 <w:body> — 重用 DocumentParser
        let content: BlockNode[] = [];
        try {
          content = this.documentParser.parseBodyContent(el);
        } catch {
          content = [];
        }

        const entry: FootnoteContent = { id, content };
        if (type !== undefined) entry.type = type;
        out.set(id, entry);
      }
    } catch {
      // 整檔解析失敗 → 回空 Map(不阻塞 OoxmlParser)
      return new Map();
    }

    return out;
  }
}

// ── 內部 helpers ──────────────────────────────────────────────────────────

function normalizeType(raw: string | undefined): FootnoteContent['type'] | undefined {
  if (raw === undefined) return undefined;
  switch (raw) {
    case 'separator':
    case 'continuationSeparator':
    case 'continuationNotice':
      return raw;
    default:
      // 未知 type 視為 undefined(降級為一般 footnote)
      return undefined;
  }
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'FootnotesParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`FootnotesParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}
