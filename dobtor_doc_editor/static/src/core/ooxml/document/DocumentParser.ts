/**
 * DocumentParser — word/document.xml 主走訪器
 *
 * 接收 word/document.xml 的 XML 字串，走 <w:document> → <w:body>，
 * 對直接子節點做 dispatch：
 *   <w:p>     → ParagraphParser
 *   <w:tbl>   → TableParser
 *   <w:sectPr> → 暫存於 trailingSectPr，由 OoxmlParser 使用
 *
 * 表格解析委派 TableParser；TableParser cell 內容反過來呼叫 parseBodyContent，
 * 因此兩者循環依賴。本檔用 lazy getter 解決：第一次用到 TableParser 時才實例化，
 * 並把 this 傳進去讓 TableParser 反向引用，避免無窮 new 迴圈。
 *
 * Phase A — Sprint 0 通電：
 *   - styles / numbering / headers / footers / media 仍保留空 Map
 *   - 由 OoxmlParser orchestrator 負責填入真實值
 *
 * Phase B Sprint 1+ 後續：
 *   - 多 section 切分（每個 <w:sectPr> 切一節）由 OoxmlParser 處理
 *   - StyleResolver / NumberingResolver / HeaderFooterParser 由 OoxmlParser 注入
 */

import type {
  BlockNode,
  DocumentNode,
  HeaderFooterContent,
  NumberingMap,
  SectionNode,
  StyleMap,
  TableNode,
} from '../ast/types';
import { ParagraphParser, type RelsLookup } from './ParagraphParser';
import { TableParser } from '../table/TableParser';
import { effectiveChildren } from '../utils/dom';

export class DocumentParser {
  private paragraphParser = new ParagraphParser();

  /** 由建構子注入的 TableParser；不傳則由 lazy getter 即時建立 */
  private _tableParser?: TableParser;

  /**
   * @param tableParser 可選；OoxmlParser orchestrator 可注入共用 instance 以節省記憶體。
   *                    不傳則 first-use 時自動 new 並把 this 傳給 TableParser，避免循環。
   */
  constructor(tableParser?: TableParser) {
    if (tableParser) this._tableParser = tableParser;
  }

  private get tableParser(): TableParser {
    if (!this._tableParser) {
      this._tableParser = new TableParser(this);
    }
    return this._tableParser;
  }

  /**
   * 把 hyperlink rId → URL 查詢函式轉發給內部 ParagraphParser。
   *
   * 由 OoxmlParser orchestrator 在 parse() 開始時呼叫；
   * 影響本 DocumentParser 與其 lazy-持有的所有 ParagraphParser instance。
   */
  setRelsLookup(fn: RelsLookup | undefined): void {
    this.paragraphParser.setRelsLookup(fn);
  }

  /**
   * 把 ThemeMap 注入內部 ParagraphParser（Phase 4.1）。
   *
   * ParagraphParser.parseRunProps 用 ThemeMap 將 themeColor reference 解析為具體 hex。
   * 缺 ThemeMap 時 themeColor 屬性會被忽略（fallback 到 w:val 或 default）。
   */
  setThemeMap(theme: import('../styles/ThemeResolver').ThemeMap | null): void {
    this.paragraphParser.setThemeMap(theme);
  }

  /**
   * 解析 word/document.xml 字串為 DocumentNode（含 body 與 placeholder metadata）。
   * @throws Error 若 XML 無法解析或缺 <w:body>
   */
  parse(documentXml: string): DocumentNode {
    const doc = parseXml(documentXml);
    const root = doc.documentElement;
    if (!root) {
      throw new Error('DocumentParser: empty document');
    }
    const body = directChild(root, 'w:body');
    if (!body) {
      throw new Error('DocumentParser: <w:body> not found');
    }

    const blocks: BlockNode[] = [];
    let trailingSectPr: Element | undefined;

    // effectiveChildren 自動展開 mc:AlternateContent
    for (const child of effectiveChildren(body)) {
      switch (child.tagName) {
        case 'w:p':
          blocks.push(this.paragraphParser.parse(child));
          break;
        case 'w:tbl':
          blocks.push(this.tableParser.parse(child));
          break;
        case 'w:sectPr':
          // body 末尾的 w:sectPr 描述整份文件的最後一節
          trailingSectPr = child;
          break;
        // 其他不認得的子節點靜默忽略（w:bookmarkStart 等通常僅作標記）
      }
    }

    const section: SectionNode = makeSectionPlaceholder(trailingSectPr, blocks);

    const headers: Map<string, HeaderFooterContent> = new Map();
    const footers: Map<string, HeaderFooterContent> = new Map();
    const styles: StyleMap = new Map();
    const numbering: NumberingMap = new Map();
    const media: Map<string, string> = new Map();

    return {
      type: 'document',
      sections: [section],
      headers,
      footers,
      footnotes: new Map(),
      endnotes: new Map(),
      comments: new Map(),
      settings: {},
      fontTable: new Map(),
      webSettings: {},
      styles,
      numbering,
      media,
      docProps: {},
      appProps: {},
      customProps: new Map(),
      contentTypes: { defaults: new Map(), overrides: new Map() },
      latentStyles: {},
    };
  }

  /**
   * 從 body 抽出僅 BlockNode 的陣列（不包成 DocumentNode），
   * 給 header/footer parser 與 TableParser cell 內容等需要重用 body 走訪邏輯的場景使用。
   *
   * 不含 sectPr / unknown 節點處理。
   */
  parseBodyContent(bodyElement: Element): BlockNode[] {
    const blocks: BlockNode[] = [];
    // effectiveChildren 自動展開 mc:AlternateContent（cell 內 / header 內 drawing 常被它包）
    for (const child of effectiveChildren(bodyElement)) {
      if (child.tagName === 'w:p') {
        blocks.push(this.paragraphParser.parse(child));
      } else if (child.tagName === 'w:tbl') {
        blocks.push(this.tableParser.parse(child));
      }
    }
    return blocks;
  }

  /**
   * 暴露給 OoxmlParser orchestrator：從 body 元素直接走訪並回傳 BlockNode + 末尾 sectPr。
   *
   * @internal
   * @deprecated 改用 walkBodyAsSections 取得多節切分
   */
  walkBody(documentXml: string): { blocks: BlockNode[]; trailingSectPr?: Element } {
    const doc = parseXml(documentXml);
    const root = doc.documentElement;
    if (!root) throw new Error('DocumentParser: empty document');
    const body = directChild(root, 'w:body');
    if (!body) throw new Error('DocumentParser: <w:body> not found');

    const blocks: BlockNode[] = [];
    let trailingSectPr: Element | undefined;
    for (const child of directChildren(body)) {
      switch (child.tagName) {
        case 'w:p':
          blocks.push(this.paragraphParser.parse(child));
          break;
        case 'w:tbl':
          blocks.push(this.tableParser.parse(child));
          break;
        case 'w:sectPr':
          trailingSectPr = child;
          break;
      }
    }
    const out: { blocks: BlockNode[]; trailingSectPr?: Element } = { blocks };
    if (trailingSectPr) out.trailingSectPr = trailingSectPr;
    return out;
  }

  /**
   * 走訪 body 並切分多 section。
   *
   * OOXML 規格：
   *   - <w:p> 內含 <w:pPr><w:sectPr> 時，該段落是當前 section 的最後一段
   *   - body 末尾的 <w:sectPr> 描述最後一節的屬性
   *
   * 回傳：每個 section 含 sectPrEl（可能 undefined）與屬於該節的 BlockNode[]。
   *
   * @internal 給 OoxmlParser orchestrator 用，搭配 SectionParser 產生 SectionNode[]
   */
  walkBodyAsSections(
    documentXml: string,
  ): Array<{ sectPrEl?: Element; blocks: BlockNode[] }> {
    const doc = parseXml(documentXml);
    const root = doc.documentElement;
    if (!root) throw new Error('DocumentParser: empty document');
    const body = directChild(root, 'w:body');
    if (!body) throw new Error('DocumentParser: <w:body> not found');

    const sections: Array<{ sectPrEl?: Element; blocks: BlockNode[] }> = [];
    let currentBlocks: BlockNode[] = [];

    // effectiveChildren 自動展開 body 層級的 mc:AlternateContent
    for (const child of effectiveChildren(body)) {
      switch (child.tagName) {
        case 'w:p': {
          // Sprint 200：識別 writer Sprint 191 emit 的 anchor paragraph
          // （無 run + pPr 只含 sectPr）→ skip 不加入 blocks、保 round-trip 對稱
          const pPr = directChild(child, 'w:pPr');
          const innerSectPr = directChild(pPr, 'w:sectPr');
          const isAnchor = innerSectPr !== undefined && isWriterAnchorParagraph(child, pPr);
          if (!isAnchor) {
            // 一般段落（含原始 docx 含 sectPr 的「最後段帶內容」case）：先加入
            currentBlocks.push(this.paragraphParser.parse(child));
          }
          // 段內 sectPr 表示當前 section 在此段落結束
          if (innerSectPr) {
            sections.push({ sectPrEl: innerSectPr, blocks: currentBlocks });
            currentBlocks = [];
          }
          break;
        }
        case 'w:tbl':
          currentBlocks.push(this.tableParser.parse(child));
          break;
        case 'w:sectPr':
          // body 末尾 sectPr：當前 blocks（即便為空也接受）成為最後一節
          sections.push({ sectPrEl: child, blocks: currentBlocks });
          currentBlocks = [];
          break;
      }
    }

    // 如果走完還有未歸入 section 的 blocks（沒有任何 sectPr），用無 sectPr 的最後一節
    if (currentBlocks.length > 0 || sections.length === 0) {
      sections.push({ blocks: currentBlocks });
    }
    return sections;
  }

  /**
   * 在 body 中找出所有 <w:sectPr>（含段落內 pPr 中的 sectPr 與 body 末尾 sectPr）
   * 用於 OoxmlParser 切分多 section。
   *
   * @internal
   */
  findAllSectPrs(documentXml: string): Element[] {
    const doc = parseXml(documentXml);
    const root = doc.documentElement;
    if (!root) return [];
    const body = directChild(root, 'w:body');
    if (!body) return [];
    const out: Element[] = [];
    // body 直接子 sectPr
    for (const child of directChildren(body)) {
      if (child.tagName === 'w:sectPr') out.push(child);
    }
    // 段落中段內 sectPr：<w:p><w:pPr><w:sectPr>...</w:sectPr></w:pPr></w:p>
    const allParas = body.getElementsByTagName('w:p');
    for (let i = 0; i < allParas.length; i++) {
      const pPr = directChild(allParas[i], 'w:pPr');
      const sectPr = directChild(pPr, 'w:sectPr');
      if (sectPr) out.push(sectPr);
    }
    return out;
  }
}

// ── Placeholder builders ──────────────────────────────────────────────────────

/**
 * 預設 SectionNode：用 A4 直式預設值。
 *
 * OoxmlParser orchestrator 會用 SectionParser 解析 sectPrEl 的真實值；
 * 此 placeholder 只在 DocumentParser.parse() 直接被外部呼叫（單元測試）時使用。
 */
function makeSectionPlaceholder(
  _sectPrEl: Element | undefined,
  body: BlockNode[],
): SectionNode {
  return {
    type: 'section',
    page: {
      width: 595.3, // A4 寬 (pt) ≈ 210mm
      height: 841.9, // A4 高 (pt) ≈ 297mm
      orientation: 'portrait',
    },
    margins: {
      top: 72,
      bottom: 72,
      left: 72,
      right: 72,
      header: 36,
      footer: 36,
    },
    headerRefs: {},
    footerRefs: {},
    titlePage: false,
    evenAndOddHeaders: false,
    body,
  };
}

// ── 共用工具 ──────────────────────────────────────────────────────────────────

/**
 * Sprint 200：辨識 writer Sprint 191 emit 的「anchor paragraph」簽名。
 *
 * Sprint 191 的多 section 寫法：對非最後 section、emit
 *   `<w:p><w:pPr><w:sectPr>...</w:sectPr></w:pPr></w:p>`
 * 把該 section 的 sectPr 嵌在一個空的 anchor paragraph 中（OOXML 規範允許）。
 *
 * 但這個 anchor paragraph 在 round-trip 時若被當成實際段落收入，section.body
 * 段落數會 +1（每個非最後 section）、破壞 round-trip 結構對稱性
 * （Sprint 199 audit 揭出：section 結構保留率 46%）。
 *
 * 嚴格簽名（不誤判 LibreOffice / Word 自然 emit 的「最後段帶 sectPr」case）：
 *   - paragraph 元素沒有任何 run-like 子節點
 *     （w:r / w:ins / w:del / w:hyperlink / w:fldSimple / w:smartTag）
 *   - w:pPr 存在
 *   - w:pPr 直接子元素只有一個、且為 w:sectPr
 *
 * 真實 docx 若用空段落結尾 section、通常 pPr 還會有 w:rPr 帶字型大小等屬性、
 * 不會走入此分支。
 */
function isWriterAnchorParagraph(pEl: Element, pPr: Element | undefined): boolean {
  if (!pPr) return false;
  // paragraph 不可有任何 run-like 子節點
  for (const c of directChildren(pEl)) {
    switch (c.tagName) {
      case 'w:r':
      case 'w:ins':
      case 'w:del':
      case 'w:hyperlink':
      case 'w:fldSimple':
      case 'w:smartTag':
        return false;
    }
  }
  // pPr 子元素必須剛好一個、且為 sectPr
  const pPrKids = directChildren(pPr);
  if (pPrKids.length !== 1) return false;
  return pPrKids[0].tagName === 'w:sectPr';
}

function directChildren(el: Element): Element[] {
  const out: Element[] = [];
  const children = el.childNodes;
  for (let i = 0; i < children.length; i++) {
    const n = children[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

function directChild(el: Element | undefined | null, tagName: string): Element | undefined {
  if (!el) return undefined;
  for (const child of directChildren(el)) {
    if (child.tagName === tagName) return child;
  }
  return undefined;
}

function parseXml(xml: string): Document {
  if (typeof DOMParser === 'undefined') {
    throw new Error(
      'DocumentParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom',
    );
  }
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const errors = doc.getElementsByTagName('parsererror');
  if (errors.length > 0) {
    throw new Error(`DocumentParser: XML parse error — ${errors[0].textContent}`);
  }
  return doc;
}

// 對外便捷 export
export type { ParagraphNode } from '../ast/types';
