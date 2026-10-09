/**
 * OoxmlParser — 對外總入口
 *
 * 把 ArrayBuffer (.docx) 一路解析成 DocumentNode。
 *
 * 內部組裝順序（Phase A — Sprint 0 通電）：
 *   1. PackageReader 解 ZIP → parts + relationships
 *   2. 透過 root .rels 找出 mainDocument 路徑（officeDocument 關係型別）
 *   3. StyleResolver / NumberingResolver 對 styles.xml / numbering.xml 解析
 *      （Phase A 為空 Map，Phase B 補完整繼承鏈）
 *   4. DocumentParser 走訪 document.xml body：dispatch <w:p> 與 <w:tbl>
 *   5. SectionParser 對 body 末尾 <w:sectPr>（與段落內 sectPr）切多 section
 *   6. HeaderFooterParser 對 document.xml.rels 中所有 header*.xml / footer*.xml 解析
 *   7. 媒體收集：document.xml.rels 內 type=image 的 rId → base64 data URL
 *   8. 組裝 DocumentNode 回傳
 *
 * Phase B 之後：
 *   - styles / numbering 從空 Map 變成真正展開的 StyleMap / NumberingMap
 *   - sections 從單一 section 切成多 section（每個 sectPr 一節）
 *   - tables 由 TableParser 完整解析（gridSpan + 邊框 + 跨頁 props）
 *   - GridResolver vMerge 兩 pass 演算法接入
 */

import type {
  BlockNode,
  DocumentLatentStyles,
  DocumentNode,
  DocumentSettings,
  DocumentWatermark,
  DocumentWebSettings,
  SmartArtNode,
  ChartNode,
  FontTable,
  FootnoteContent,
  HeaderFooterContent,
  NumberingMap,
  SectionNode,
  StyleMap,
} from './ast/types';
import { DocumentParser } from './document/DocumentParser';
import { FontTableParser } from './font-table/FontTableParser';
import { FootnotesParser } from './footnotes/FootnotesParser';
import { HeaderFooterParser } from './header-footer/HeaderFooterParser';
import { NumberingResolver } from './numbering/NumberingResolver';
import { SettingsParser } from './settings/SettingsParser';
import { WebSettingsParser } from './web-settings/WebSettingsParser';
import { BackgroundParser } from './background/BackgroundParser';
import { WatermarkParser } from './watermark/WatermarkParser';
import { CommentsParser } from './comments/CommentsParser';
import { DiagramParser } from './diagram/DiagramParser';
import { ChartParser } from './chart/ChartParser';
import {
  PackageReader,
  type OoxmlPackage,
  type PackagePart,
  type RelationshipDef,
} from './package/PackageReader';
import { LatentStylesParser } from './styles/LatentStylesParser';
import { SectionParser } from './section/SectionParser';
import { StyleResolver } from './styles/StyleResolver';
import { mergeParagraphStyles } from './styles/ParagraphStyleMerger';
import { TableParser } from './table/TableParser';
import { parseTheme, DEFAULT_THEME_MAP, type ThemeMap } from './styles/ThemeResolver';
import { parseDocProps } from './DocPropsParser';
import { parseAppProps } from './doc-props/AppPropsParser';
import { parseCustomProps } from './doc-props/CustomPropsParser';

const REL_TYPE_OFFICE_DOCUMENT =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument';
const REL_TYPE_STYLES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles';
const REL_TYPE_NUMBERING =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering';
const REL_TYPE_HEADER =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header';
const REL_TYPE_FOOTER =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer';
const REL_TYPE_FOOTNOTES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes';
const REL_TYPE_ENDNOTES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes';
const REL_TYPE_COMMENTS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments';
const REL_TYPE_SETTINGS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings';
const REL_TYPE_FONT_TABLE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable';
const REL_TYPE_WEB_SETTINGS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings';
const REL_TYPE_IMAGE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image';
const REL_TYPE_DIAGRAM_DATA =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData';
const REL_TYPE_CHART =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart';

const DEFAULT_DOC_PATH = 'word/document.xml';

export interface ParseOptions {
  /** 是否在 Run 上預先填入近似 LineMetrics（Phase 1 預設 false，Phase 2 開啟） */
  fillMetrics?: boolean;
}

export class OoxmlParser {
  private packageReader = new PackageReader();
  private styleResolver = new StyleResolver();
  private numberingResolver = new NumberingResolver();
  private sectionParser = new SectionParser();

  // 共用 Document/Table/HeaderFooter 解析鏈：
  //   - DocumentParser 持有 TableParser（透過建構子注入）
  //   - TableParser 第一次 parse cell 時會 lazy 建立 own DocumentParser，
  //     反向把自己（this TableParser）注入該 DP，循環安全閉環，無無窮 new。
  //   - HeaderFooterParser 共用 OoxmlParser 持有的 DocumentParser，
  //     確保 header/footer 內表格也走同一條 TableParser 解析鏈。
  private tableParser = new TableParser();
  private documentParser = new DocumentParser(this.tableParser);
  private headerFooterParser = new HeaderFooterParser(this.documentParser);
  /** Sprint 145：footnotes / endnotes 重用 documentParser、與 header/footer 對齊 */
  private footnotesParser = new FootnotesParser(this.documentParser);
  /** Sprint 146：settings.xml capture-only */
  private settingsParser = new SettingsParser();
  /** Sprint 147：fontTable.xml capture-only */
  private fontTableParser = new FontTableParser();
  /** Sprint 148：webSettings.xml capture-only(結束 Phase 1 part 三連 cluster)*/
  private webSettingsParser = new WebSettingsParser();
  /** Sprint 153：styles.xml `<w:latentStyles>` capture-only */
  private latentStylesParser = new LatentStylesParser();
  /** Sprint 171：document.xml `<w:background>` 文件背景（Phase 5.6 浮水印 + 背景）*/
  private backgroundParser = new BackgroundParser();
  /** Sprint 172：header VML 浮水印 shape capture（Phase 5.6 浮水印 + 背景）*/
  private watermarkParser = new WatermarkParser();
  /** Sprint 176：comments.xml 註解 capture（Phase 5.5 註解）*/
  private commentsParser = new CommentsParser();
  /** Sprint 181：SmartArt diagrams/dataN.xml capture（Phase 5.2 SmartArt、mc:Fallback 壓縮）*/
  private diagramParser = new DiagramParser();
  /** Sprint 182：Chart charts/chartN.xml capture（Phase 5.3 Charts、mc:Fallback 壓縮）*/
  private chartParser = new ChartParser();

  /**
   * 把 .docx ArrayBuffer 解析為 DocumentNode。
   *
   * @throws Error 如果不是有效 OOXML 包（ZIP 損壞、缺 [Content_Types].xml、缺 mainDocument 關聯）
   */
  parse(buffer: ArrayBuffer, _options: ParseOptions = {}): DocumentNode {
    // Step 1：解 ZIP
    const pkg = this.packageReader.parse(buffer);

    // Step 2：找 mainDocument 路徑
    const mainDocPath = findMainDocumentPath(pkg) ?? DEFAULT_DOC_PATH;
    const documentXml = pkg.partAsText(mainDocPath);
    if (!documentXml) {
      throw new Error(
        `OoxmlParser: main document part not found at "${mainDocPath}"`,
      );
    }

    // Step 2.5：注入 hyperlink rels lookup
    //   ParagraphParser.parseHyperlinkInfo 透過此函式把 rId → External URL
    //   - mainDoc rels：負責本文 hyperlink
    //   - 注意：header/footer 的 hyperlink 在各自 part 的 rels；目前 lookup 只覆蓋 mainDoc
    //     若 fixture 中出現 header hyperlink，可在 collectHeadersFooters 中 per-part 注入
    this.documentParser.setRelsLookup((rId) =>
      readExternalUrl(pkg, mainDocPath, rId),
    );

    // Step 2.6：解析 theme1.xml 並注入 ThemeMap（Phase 4.1）
    //   parser 階段把 themeColor/themeTint/themeShade reference 解為具體 hex
    //   缺檔 / 解析失敗：用 DEFAULT_THEME_MAP（Office 預設色）降級
    //   Sprint 262：parsedTheme 保留 null/ThemeMap 區別、寫回 DocumentNode.theme
    //     供 Phase 6 export 對稱性使用（紀律 #21 optional）
    const parsedTheme = parseTheme(pkg);
    const themeMap: ThemeMap = parsedTheme ?? DEFAULT_THEME_MAP;
    this.documentParser.setThemeMap(themeMap);
    this.styleResolver.setThemeMap(themeMap);

    // Step 3：Styles / Numbering（Phase A 為空 Map）
    const stylesXml = readRelatedPart(pkg, mainDocPath, REL_TYPE_STYLES);
    const styles: StyleMap = this.styleResolver.resolve(stylesXml);
    const numbering: NumberingMap = this.numberingResolver.resolve(
      readRelatedPart(pkg, mainDocPath, REL_TYPE_NUMBERING),
    );
    // Step 3.1（Sprint 153）：latentStyles capture — 與 StyleResolver 平行運作、不影響 active styles
    const latentStyles: DocumentLatentStyles = this.latentStylesParser.parse(stylesXml);

    // Step 3.5：注入 StyleMap 給 TableParser（Phase 4.2 條件樣式套用用）
    this.tableParser.setStyleMap(styles);

    // Step 4-5：走訪 body 並切多 section
    const rawSections = this.documentParser.walkBodyAsSections(documentXml);
    const sections: SectionNode[] = rawSections.map((rs) => {
      const sec = this.sectionParser.parse(rs.sectPrEl);
      sec.body = rs.blocks;
      return sec;
    });

    // Step 6：Headers / Footers
    const headers = new Map<string, HeaderFooterContent>();
    const footers = new Map<string, HeaderFooterContent>();
    collectHeadersFooters(pkg, mainDocPath, this.headerFooterParser, headers, footers);

    // Step 6.5（Sprint 145）：Footnotes / Endnotes — capture-only、無 wire-up
    //   42 fixture footnoteReference 0 出現,本步驟只是 parse 進 AST 不影響 layout/render。
    //   為將來 user 提供含 footnoteReference 的 fixture 後 wire-up 鋪路。
    const footnotes = collectNotes(pkg, mainDocPath, this.footnotesParser, REL_TYPE_FOOTNOTES);
    const endnotes = collectNotes(pkg, mainDocPath, this.footnotesParser, REL_TYPE_ENDNOTES);

    // Step 6.5b（Sprint 176）：comments.xml — capture-only、無 wire-up（Phase 5.5 註解）
    //   comment 範圍錨點（commentRangeStart/End/Reference）+ 右側 panel render 留後續。
    const comments = collectComments(pkg, mainDocPath, this.commentsParser);

    // Step 6.6（Sprint 146）：settings.xml — capture-only、無 wire-up
    //   42/42 fixture 都有 settings.xml、含 zoom / defaultTabStop / characterSpacingControl /
    //   footnotePr / endnotePr / compat 等文件級設定;為將來 wire-up 鋪路。
    const settings = collectSettings(pkg, mainDocPath, this.settingsParser);

    // Step 6.7（Sprint 147）：fontTable.xml — capture-only、無 wire-up
    //   42/42 fixture 都有 fontTable.xml、~20-30 fonts/file;為將來 altName fallback
    //   chain / metric hint / Unicode sig 精確匹配 wire-up 鋪路。
    const fontTable = collectFontTable(pkg, mainDocPath, this.fontTableParser);

    // Step 6.8（Sprint 148）：webSettings.xml — capture-only、無 wire-up
    //   42/42 fixture 都有 webSettings.xml(Word 預設骨架)、layout/render 不用;
    //   結束 Phase 1 part 三連 cluster(Sprint 145-148)、留 Phase 6 docx export 用。
    const webSettings = collectWebSettings(pkg, mainDocPath, this.webSettingsParser);

    // Step 7：媒體收集（image rId → data URL）
    const media = collectMedia(pkg, mainDocPath);

    // Step 8：docProps/core.xml 解析（Sprint 13）
    //   缺檔 / 解析失敗 → 空 docProps；不阻塞 parse
    const docProps = parseDocProps(pkg);

    // Step 8.1（Sprint 150）：docProps/app.xml 解析 — capture-only、無 wire-up
    //   42/42 fixture 都有 app.xml(Word/WPS 預設骨架)、17 elements 100% 覆蓋;
    //   layout/render 不消費、為將來 Phase 6 docx export 對稱性鋪路。
    const appProps = parseAppProps(pkg);

    // Step 8.2（Sprint 151）：docProps/custom.xml 解析 — capture-only、無 wire-up
    //   25/42 fixture 有 custom.xml(WPS / Grammarly 等 SaaS app stamp);
    //   variant 型別 discriminated union(string / int / bool / real / filetime / unknown)
    //   留 Phase 6 docx export 對稱性 + author 自訂中介資料保留。
    const customProps = parseCustomProps(pkg);

    // Step 8.3（Sprint 152）：[Content_Types].xml — capture-only、無 wire-up
    //   PackageReader 已解析、本 step 把 pkg.contentTypes 暴露到 DocumentNode
    //   為 Phase 6 docx export 對稱性鋪路(export 時要原樣重建)、layout/render 不用。
    const contentTypes = pkg.contentTypes;

    // Step 8.4（Sprint 171）：document.xml `<w:background>` 文件背景（Phase 5.6）
    //   render wire-up：CanvasRenderer 以 pageBackgroundColor 選項消費 background.color。
    //   多數 docx 無此元素 → background 為 undefined（紀律 #21）。
    //   Sprint 178：傳 themeMap、把 w:themeColor 解析為具體 hex 寫入 background.color。
    const background = this.backgroundParser.parse(documentXml, themeMap);

    // Step 8.5（Sprint 172）：header VML 浮水印 shape capture（Phase 5.6）
    //   掃所有 header part、capture 第一個浮水印 shape；capture-only、render 留 Sprint 173。
    //   多數 docx 無浮水印 → watermark 為 undefined（紀律 #21）。
    const watermark = collectWatermark(pkg, mainDocPath, this.watermarkParser);

    // Step 8.6（Sprint 181）：SmartArt diagrams/dataN.xml capture（Phase 5.2、mc:Fallback 壓縮）
    //   走 document.xml.rels 抓所有 type=diagramData 的關係、解析資料模型文字。
    //   capture-only；render wire-up（線性文字 fallback）留後續 sprint。
    //   多數 docx 無 SmartArt → smartArts 為空陣列（紀律 #21：空時不掛 key）。
    const smartArts = collectSmartArts(pkg, mainDocPath, this.diagramParser);

    // Step 8.7（Sprint 182）：Chart charts/chartN.xml capture（Phase 5.3、mc:Fallback 壓縮）
    //   走 document.xml.rels 抓所有 type=chart 的關係、解析數值快取。
    //   capture-only；render wire-up 留後續 sprint。
    //   多數 docx 無圖表 → charts 為空陣列（紀律 #21：空時不掛 key）。
    const charts = collectCharts(pkg, mainDocPath, this.chartParser);

    const doc: DocumentNode = {
      type: 'document',
      sections,
      headers,
      footers,
      footnotes,
      endnotes,
      comments,
      settings,
      fontTable,
      webSettings,
      styles,
      numbering,
      media,
      docProps,
      appProps,
      customProps,
      contentTypes,
      latentStyles,
      ...(background !== undefined ? { background } : {}),
      ...(watermark !== undefined ? { watermark } : {}),
      ...(smartArts.length > 0 ? { smartArts } : {}),
      ...(charts.length > 0 ? { charts } : {}),
      ...(parsedTheme !== null ? { theme: parsedTheme } : {}),
    };

    // Step 9 (Sprint 19)：把 styles.xml 的 pProps 合併到所有 body 段落的 props
    //   - StyleResolver 已展開繼承鏈為 StyleMap
    //   - 但 ParagraphParser 只解析 inline pPr；style-defined keepNext / spacing /
    //     fontSize 從未落到 paragraph.props，下游 Paginator R6 看不到
    //   - 此 post-pass 補完 props 合併（in-place mutate paragraph.props）
    //   - header/footer 內段落 Sprint 19 暫不合併（範圍見 ParagraphStyleMerger）
    mergeParagraphStyles(doc);

    return doc;
  }
}

// ── orchestrator helpers ─────────────────────────────────────────────────────

/**
 * 透過 root .rels 找出 mainDocument part 的絕對路徑。
 * root 的 part path 用空字串 "" 索引（PackageReader 慣例）。
 */
function findMainDocumentPath(pkg: OoxmlPackage): string | undefined {
  const rootRels = pkg.relationships.get('') ?? new Map<string, RelationshipDef>();
  for (const rel of rootRels.values()) {
    if (rel.type === REL_TYPE_OFFICE_DOCUMENT && rel.targetMode === 'Internal') {
      return rel.target;
    }
  }
  return undefined;
}

/**
 * 從 mainDoc 的 .rels 找出指定 type 的第一個關聯，回傳該 part 的文字內容。
 * 找不到關聯或 part 不存在時回 undefined（resolver 會回空 Map）。
 */
function readRelatedPart(
  pkg: OoxmlPackage,
  mainDocPath: string,
  relType: string,
): string | undefined {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return undefined;
  for (const rel of rels.values()) {
    if (rel.type === relType && rel.targetMode === 'Internal') {
      return pkg.partAsText(rel.target);
    }
  }
  return undefined;
}

/**
 * 從指定 part 的 .rels 把 rId 解析為 External URL。
 *
 * - 若 rel.targetMode === 'External'：回 rel.target（即 URL 字串）
 * - 若 Internal 連結（同文件 part 跳轉，罕見）：回 undefined（hyperlink 用 anchor 而非 url）
 * - 找不到 rId：回 undefined
 *
 * @example
 *   readExternalUrl(pkg, 'word/document.xml', 'rId5') → 'https://example.com/foo'
 */
function readExternalUrl(
  pkg: OoxmlPackage,
  partPath: string,
  rId: string,
): string | undefined {
  const rels = pkg.relationships.get(partPath);
  if (!rels) return undefined;
  const rel = rels.get(rId);
  if (!rel) return undefined;
  return rel.targetMode === 'External' ? rel.target : undefined;
}

/**
 * 走訪 mainDoc 的 .rels，把所有 header*.xml / footer*.xml 解析為 HeaderFooterContent
 * 並以 rId 為 key 存入兩個 Map。
 */
function collectHeadersFooters(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: HeaderFooterParser,
  headers: Map<string, HeaderFooterContent>,
  footers: Map<string, HeaderFooterContent>,
): void {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return;
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal') continue;
    if (rel.type === REL_TYPE_HEADER) {
      const xml = pkg.partAsText(rel.target);
      if (xml === undefined) continue;
      headers.set(rel.id, parser.parse(xml, rel.id));
    } else if (rel.type === REL_TYPE_FOOTER) {
      const xml = pkg.partAsText(rel.target);
      if (xml === undefined) continue;
      footers.set(rel.id, parser.parse(xml, rel.id));
    }
  }
}

/**
 * Sprint 176：走訪 mainDoc 的 .rels、抓 comments.xml part 並解析。
 *
 * @returns Map<id, CommentContent>；rels 沒指向 comments 時回空 Map
 */
function collectComments(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: CommentsParser,
): Map<number, import('./ast/types').CommentContent> {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return new Map();
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_COMMENTS) continue;
    return parser.parse(pkg.partAsText(rel.target));
  }
  return new Map();
}

/**
 * Sprint 172：走訪所有 header part、capture 第一個浮水印 VML shape。
 *
 * 浮水印存於 header（每頁顯示），多份 header 可能含同一浮水印；本函式回傳第一個
 * 找到的浮水印（scope-down、不區分 default/first/even header）。
 *
 * @returns DocumentWatermark 或 undefined（無 header 含浮水印）
 */
function collectWatermark(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: WatermarkParser,
): DocumentWatermark | undefined {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return undefined;
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_HEADER) continue;
    const xml = pkg.partAsText(rel.target);
    const wm = parser.parse(xml);
    if (wm) return wm;
  }
  return undefined;
}

/**
 * Sprint 181：走訪 mainDoc 的 .rels、抓所有 type=diagramData 的 SmartArt 部件並解析。
 *
 * 與 collectWatermark 不同：一份 docx 可含多個 SmartArt（每個各有獨立的
 * diagramData 部件），故全部收集為陣列；依 rels 走訪順序排列。
 *
 * @returns SmartArtNode[]；無 SmartArt 時回空陣列
 */
function collectSmartArts(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: DiagramParser,
): SmartArtNode[] {
  const out: SmartArtNode[] = [];
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return out;
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_DIAGRAM_DATA) continue;
    const node = parser.parse(pkg.partAsText(rel.target), rel.id);
    if (node) out.push(node);
  }
  return out;
}

/**
 * Sprint 182：走訪 mainDoc 的 .rels、抓所有 type=chart 的圖表部件並解析。
 *
 * 比照 collectSmartArts：一份 docx 可含多個圖表、全部收集為陣列、依 rels
 * 走訪順序排列。
 *
 * @returns ChartNode[]；無圖表時回空陣列
 */
function collectCharts(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: ChartParser,
): ChartNode[] {
  const out: ChartNode[] = [];
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return out;
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_CHART) continue;
    const node = parser.parse(pkg.partAsText(rel.target), rel.id);
    if (node) out.push(node);
  }
  return out;
}

/**
 * Sprint 145：走訪 mainDoc 的 .rels、抓 footnotes 或 endnotes part 並解析。
 *
 * 與 collectHeadersFooters 不同點：footnote/endnote 的 key 是 numeric id（OOXML w:id）、
 * 不是 rId；rels 只指向「文件級別的 footnotes.xml」單一 part、parse 後產出 Map<id, content>。
 *
 * @param relType REL_TYPE_FOOTNOTES 或 REL_TYPE_ENDNOTES
 * @returns Map<id, FootnoteContent>；rels 沒指向 footnotes/endnotes 時回空 Map
 */
function collectNotes(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: FootnotesParser,
  relType: string,
): Map<number, FootnoteContent> {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return new Map();
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal') continue;
    if (rel.type !== relType) continue;
    const xml = pkg.partAsText(rel.target);
    return parser.parse(xml);  // 找到第一個就回（footnotes/endnotes 各最多 1 個 part）
  }
  return new Map();
}

/**
 * Sprint 146：走訪 mainDoc 的 .rels、抓 settings.xml part 並解析。
 *
 * @returns DocumentSettings；rels 沒指向 settings 時回 {}（capture-only safety）
 */
function collectSettings(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: SettingsParser,
): DocumentSettings {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return {};
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal') continue;
    if (rel.type !== REL_TYPE_SETTINGS) continue;
    const xml = pkg.partAsText(rel.target);
    return parser.parse(xml);
  }
  return {};
}

/**
 * Sprint 147：走訪 mainDoc 的 .rels、抓 fontTable.xml part 並解析。
 *
 * @returns FontTable；rels 沒指向 fontTable 時回空 Map
 */
function collectFontTable(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: FontTableParser,
): FontTable {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return new Map();
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal') continue;
    if (rel.type !== REL_TYPE_FONT_TABLE) continue;
    const xml = pkg.partAsText(rel.target);
    return parser.parse(xml);
  }
  return new Map();
}

/**
 * Sprint 148：走訪 mainDoc 的 .rels、抓 webSettings.xml part 並解析。
 *
 * @returns DocumentWebSettings；rels 沒指向 webSettings 時回 {}（capture-only safety）
 */
function collectWebSettings(
  pkg: OoxmlPackage,
  mainDocPath: string,
  parser: WebSettingsParser,
): DocumentWebSettings {
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return {};
  for (const rel of rels.values()) {
    if (rel.targetMode !== 'Internal') continue;
    if (rel.type !== REL_TYPE_WEB_SETTINGS) continue;
    const xml = pkg.partAsText(rel.target);
    return parser.parse(xml);
  }
  return {};
}

/**
 * 走訪 mainDoc 的 .rels，把所有 image 關聯的 rId 對應到該 part 的 base64 data URL。
 *
 * Phase A：對每個 image part 直接做 base64 編碼成 `data:<mime>;base64,<...>`
 * Phase D：可改用 Blob URL（瀏覽器執行時）或惰性 lazy fetch（大圖時）
 */
function collectMedia(pkg: OoxmlPackage, mainDocPath: string): Map<string, string> {
  const out = new Map<string, string>();
  const rels = pkg.relationships.get(mainDocPath);
  if (!rels) return out;
  for (const rel of rels.values()) {
    if (rel.type !== REL_TYPE_IMAGE || rel.targetMode !== 'Internal') continue;
    const part = pkg.parts.get(rel.target);
    if (!part) continue;
    out.set(rel.id, partToDataUrl(part));
  }
  return out;
}

/**
 * 把 PackagePart 編碼為 data URL。
 *
 * 兼容 Node（Buffer）與瀏覽器（btoa + Uint8Array → 字串）兩個環境。
 */
function partToDataUrl(part: PackagePart): string {
  const mime = part.contentType || guessImageMime(part.path) || 'application/octet-stream';
  const b64 = toBase64(part.data);
  return `data:${mime};base64,${b64}`;
}

function guessImageMime(path: string): string | undefined {
  const ext = path.toLowerCase().split('.').pop();
  switch (ext) {
    case 'png':
      return 'image/png';
    case 'jpg':
    case 'jpeg':
      return 'image/jpeg';
    case 'gif':
      return 'image/gif';
    case 'bmp':
      return 'image/bmp';
    case 'svg':
      return 'image/svg+xml';
    case 'webp':
      return 'image/webp';
    case 'tiff':
    case 'tif':
      return 'image/tiff';
    case 'emf':
      return 'image/x-emf';
    case 'wmf':
      return 'image/x-wmf';
    default:
      return undefined;
  }
}

/**
 * Uint8Array → base64 字串。
 *
 * - Node：用 globalThis.Buffer（Node 內建）
 * - 瀏覽器：用 btoa + 逐 byte 轉 String.fromCharCode
 */
function toBase64(bytes: Uint8Array): string {
  // Node.js 環境
  const g = globalThis as { Buffer?: { from(b: Uint8Array): { toString(enc: string): string } } };
  if (g.Buffer && typeof g.Buffer.from === 'function') {
    return g.Buffer.from(bytes).toString('base64');
  }
  // 瀏覽器環境：btoa 處理 Latin1 字串；分塊避免 stack overflow
  let bin = '';
  const chunkSize = 0x8000; // 32KB chunks
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const sub = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
    bin += String.fromCharCode.apply(null, Array.from(sub));
  }
  // btoa 在 Node 18+ 也存在，但 globalThis.Buffer 已先處理；此處為瀏覽器後備
  const btoa = (globalThis as { btoa?: (s: string) => string }).btoa;
  if (typeof btoa === 'function') return btoa(bin);
  throw new Error('OoxmlParser: no base64 encoder available (need Buffer or btoa)');
}

// 旁路：方便外部探測 stub 是否已連通
export const __DOBTOR_OOXML_STUB__ = 'phase-a' as const;

// 對外 re-export 型別
export type { BlockNode };
