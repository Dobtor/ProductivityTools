/**
 * OoxmlWriter — DocumentNode → .docx ArrayBuffer / Uint8Array（Phase 6 docx export）
 *
 * Sprint 185 — Phase 6 minimum viable slice（MVS）：
 *   把 OoxmlParser 的「parse」反向：DocumentNode → ZIP package。本 sprint 走通
 *   end-to-end 骨架，覆蓋率最小但 round-trip 可驗證（規畫書 §6 黃金測試
 *   `import(export(doc))` ≅ `doc`）。
 *
 * MVS 覆蓋（scope-down 紀律 #18）：
 *   - paragraph + run（純文字）
 *   - 單 section 的 pgSz / pgMar（pt → twips）
 *   - `[Content_Types].xml` / `_rels/.rels` / `word/_rels/document.xml.rels` /
 *     `word/styles.xml`（空骨架）/ `word/document.xml`
 *
 * MVS 不覆蓋（後續 sprint 逐步補）：
 *   - RunProps / ParagraphProps（粗體/斜體/字級/顏色/對齊/縮排等）
 *   - 樣式繼承（styles.xml 完整輸出）/ numbering / 多 section
 *   - 表格 / 圖片 / 頁首頁尾 / 註腳 / 註解
 *   - Phase 5 子功能（OMML / SmartArt / Chart / 浮水印 / 追蹤修訂）
 *   - docProps / appProps / customProps / fontTable / settings / webSettings
 *
 * 架構：per-part writer 函式（鏡像 parser 的 per-part class）、
 * 主流程 `write()` orchestrator 組裝 + fflate `zipSync` 打包。
 */

import { zipSync, strToU8 } from 'fflate';
import type {
  AbstractNumbering,
  BlockNode,
  CellBorders,
  CellNode,
  ChartNode,
  CommentContent,
  CustomPropertyValue,
  DocProps,
  DocPropsApp,
  DocPropsCustom,
  DocumentNode,
  DocumentSettings,
  DocumentWebSettings,
  FloatImageNode,
  FontEntry,
  FootnoteContent,
  InlineImageNode,
  MathNode,
  NumberingLevel,
  OmmlNode,
  ParagraphNode,
  ParagraphProps,
  RowNode,
  RunNode,
  RunProps,
  SectionNode,
  SmartArtNode,
  TableNode,
} from '../ast/types';

/** OOXML wordprocessingml 命名空間 URI。 */
const W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
/** Package relationships 命名空間 URI。 */
const REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships';
/** Content Types 命名空間 URI。 */
const CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types';
/** officeDocument 關係型別（root rels → word/document.xml）。 */
const REL_TYPE_OFFICE_DOCUMENT =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument';
/** styles 關係型別（document.xml.rels → styles.xml）。 */
const REL_TYPE_STYLES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles';
/** numbering 關係型別（document.xml.rels → numbering.xml）。 */
const REL_TYPE_NUMBERING =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering';
/** image 關係型別（document.xml.rels → media/imageN.ext）。 */
const REL_TYPE_IMAGE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image';
/** header 關係型別（document.xml.rels → headerN.xml）。 */
const REL_TYPE_HEADER =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header';
/** footer 關係型別（document.xml.rels → footerN.xml）。 */
const REL_TYPE_FOOTER =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer';
/** comments 關係型別（document.xml.rels → comments.xml）。 */
const REL_TYPE_COMMENTS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments';
/** Sprint 239：footnotes 關係型別（document.xml.rels → footnotes.xml）。 */
const REL_TYPE_FOOTNOTES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes';
/** Sprint 239：endnotes 關係型別（document.xml.rels → endnotes.xml）。 */
const REL_TYPE_ENDNOTES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes';
/** Sprint 243：settings 關係型別（document.xml.rels → settings.xml）。 */
const REL_TYPE_SETTINGS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings';
/** Sprint 246：fontTable 關係型別（document.xml.rels → fontTable.xml）。 */
const REL_TYPE_FONT_TABLE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable';
/** Sprint 249：webSettings 關係型別（document.xml.rels → webSettings.xml）。 */
const REL_TYPE_WEB_SETTINGS =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings';
/** Sprint 253：core properties 關係型別（root rels → docProps/core.xml）。 */
const REL_TYPE_CORE_PROPERTIES =
  'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties';
/** Sprint 253：extended properties 關係型別（root rels → docProps/app.xml）。 */
const REL_TYPE_EXTENDED_PROPERTIES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties';
/** Sprint 253：custom properties 關係型別（root rels → docProps/custom.xml）。 */
const REL_TYPE_CUSTOM_PROPERTIES =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties';
/** Sprint 253：Dublin Core namespace + DC Terms namespace（core.xml）。 */
const DC_NS = 'http://purl.org/dc/elements/1.1/';
const DCTERMS_NS = 'http://purl.org/dc/terms/';
const DCMITYPE_NS = 'http://purl.org/dc/dcmitype/';
const XSI_NS = 'http://www.w3.org/2001/XMLSchema-instance';
const CP_NS = 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties';
/** Sprint 253：extended-properties namespace（app.xml）。 */
const EXT_PROPS_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties';
/** Sprint 253：custom-properties namespace（custom.xml）。 */
const CUSTOM_PROPS_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties';
/** Sprint 253：vt variant namespace（custom.xml 內 vt:lpwstr 等）。 */
const VT_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes';
/** OMML 命名空間（ECMA-376 §22.1）。 */
const M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math';
/** Sprint 195：SmartArt diagram data 關係型別。 */
const REL_TYPE_DIAGRAM_DATA =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData';
/** Sprint 195：Chart 關係型別。 */
const REL_TYPE_CHART =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart';
/** Sprint 262：theme 關係型別（document.xml.rels → theme/theme1.xml）。 */
const REL_TYPE_THEME =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme';
/** Sprint 195：SmartArt graphicData uri。 */
const A_GRAPHIC_DIAGRAM_URI = 'http://schemas.openxmlformats.org/drawingml/2006/diagram';
/** Sprint 195：Chart graphicData uri。 */
const A_GRAPHIC_CHART_URI = 'http://schemas.openxmlformats.org/drawingml/2006/chart';
/** Sprint 195：DrawingML diagram 命名空間（dgm）。 */
const DGM_NS = 'http://schemas.openxmlformats.org/drawingml/2006/diagram';
/** Sprint 195：DrawingML chart 命名空間（c）。 */
const C_NS = 'http://schemas.openxmlformats.org/drawingml/2006/chart';
/** Sprint 196：VML 命名空間（urn:schemas-microsoft-com:vml）—— watermark `<v:shape>`。 */
const V_NS = 'urn:schemas-microsoft-com:vml';
/** Sprint 196：Office 命名空間（urn:schemas-microsoft-com:office:office）—— `<o:lock>` 等。 */
const O_NS = 'urn:schemas-microsoft-com:office:office';
/** Sprint 196：文字浮水印 WordArt shape type（OOXML §17、Word 內建 type #_x0000_t136）。 */
const WATERMARK_SHAPE_TYPE = '#_x0000_t136';
/** Sprint 196：合成 watermark header 部件的 rId（避開原 doc.headers/footers rId 數字命名空間）。 */
const WATERMARK_HEADER_RID = 'rIdWatermarkHdr';
/** Sprint 196：合成 watermark header 部件檔名。 */
const WATERMARK_HEADER_FILENAME = 'word/watermarkHeader.xml';
/** Sprint 196：文字浮水印 default rotation（Word 「設計 → 浮水印」對角預設）。 */
const WATERMARK_DEFAULT_ROTATION = 315;
/** Sprint 196：文字浮水印 default fill 顏色（Word 內建灰）。 */
const WATERMARK_DEFAULT_FILLCOLOR = '#C0C0C0';

/** DrawingML 命名空間：wordprocessingDrawing（wp）。 */
const WP_NS = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing';
/** DrawingML 命名空間：main（a）。 */
const A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main';
/** DrawingML 命名空間：picture（pic）。 */
const PIC_NS = 'http://schemas.openxmlformats.org/drawingml/2006/picture';
/** officeDocument relationships 命名空間（r:embed）。 */
const R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
/** `<a:graphicData uri>` for picture。 */
const A_GRAPHIC_PICTURE_URI = 'http://schemas.openxmlformats.org/drawingml/2006/picture';

/** 1 pt = 20 twips（OOXML 度量單位、§17.18.85）。 */
const TWIPS_PER_PT = 20;
/** 1 pt = 2 half-points（`<w:sz>` 用半 pt 單位、OOXML §17.3.2.39）。 */
const HALF_POINTS_PER_PT = 2;
/** `w:line` 的 auto 規則分母（240 = 單行、360 = 1.5 行；OOXML §17.3.1.33）。 */
const LINE_SPACING_AUTO_BASE = 240;
/** 邊框寬度單位：`<w:sz>` 為 1/8 pt（OOXML §17.3.1.23 CT_Border）。 */
const BORDER_EIGHTHS_PER_PT = 8;
/** EMU per pt：1 inch = 914400 EMU = 72 pt → 1 pt = 12700 EMU（OOXML §20.1）。 */
const EMU_PER_PT = 12700;

/** A4 直式預設頁面尺寸（pt），section.page 缺漏時 fallback。 */
const DEFAULT_PAGE_WIDTH_PT = 595.3;
const DEFAULT_PAGE_HEIGHT_PT = 841.9;
/** Word 預設邊距（pt），section.margins 缺漏時 fallback（top/bottom 72pt = 2.54cm）。 */
const DEFAULT_MARGIN_TB_PT = 72;
const DEFAULT_MARGIN_LR_PT = 72;
const DEFAULT_MARGIN_HF_PT = 36;

export class OoxmlWriter {
  /**
   * 把 DocumentNode 序列化為 .docx（OPC ZIP package）位元組。
   *
   * @param doc 由 OoxmlParser.parse 產出（或 caller 手構）的 DocumentNode
   * @returns .docx 的 Uint8Array；caller 可 `.buffer` 取 ArrayBuffer 寫檔
   */
  write(doc: DocumentNode): Uint8Array {
    // Sprint 192：重置每次 write 的內部計數器（docPr 序號）
    resetDocPrCounter();

    // Sprint 192：收集 media（base64 data URL → bytes + 檔名）
    const mediaItems = collectMedia(doc.media);
    const imageExtensions = new Set(mediaItems.map((m) => m.ext));

    // Sprint 193：收集 headers / footers（每個 rId 配一個 wordpath）
    const hfItems = collectHeadersFooters(doc);

    // Sprint 195：收集 SmartArt / Chart 部件（依 doc.smartArts / doc.charts）
    const smartArtItems = collectSmartArts(doc);
    const chartItems = collectCharts(doc);

    // Sprint 196：收集 watermark header 部件（依 doc.watermark）
    const watermarkItem = collectWatermark(doc);

    const parts: { [path: string]: Uint8Array } = {
      '[Content_Types].xml': strToU8(writeContentTypes(imageExtensions, hfItems, smartArtItems, chartItems, watermarkItem, doc)),
      '_rels/.rels': strToU8(writeRootRels(doc)),
      'word/_rels/document.xml.rels': strToU8(writeDocumentRels(mediaItems, hfItems, smartArtItems, chartItems, watermarkItem, doc)),
      'word/document.xml': strToU8(writeDocument(doc, watermarkItem)),
      'word/styles.xml': strToU8(writeStyles(doc)),
      'word/numbering.xml': strToU8(writeNumbering(doc)),
      // Sprint 194：comments.xml 永遠 emit（空 Map → 空 <w:comments/>）
      'word/comments.xml': strToU8(writeComments(doc)),
    };
    // Sprint 239：footnotes.xml / endnotes.xml 非空才 emit（保持 minimal docx
    // 不被加入冗餘 part；ChienYi 多 fixture 有 separator/continuationSeparator
    // 預設裝飾 footnote、必須 round-trip 保留）
    if (doc.footnotes.size > 0) {
      parts['word/footnotes.xml'] = strToU8(writeFootnotes(doc));
    }
    if (doc.endnotes.size > 0) {
      parts['word/endnotes.xml'] = strToU8(writeEndnotes(doc));
    }
    // Sprint 243：settings.xml 非空才 emit（OOXML §17.15）
    if (hasSettings(doc.settings)) {
      parts['word/settings.xml'] = strToU8(writeSettings(doc.settings));
    }
    // Sprint 246：fontTable.xml 非空才 emit（OOXML §17.8.3）
    if (doc.fontTable.size > 0) {
      parts['word/fontTable.xml'] = strToU8(writeFontTable(doc.fontTable));
    }
    // Sprint 249：webSettings.xml 非空才 emit（OOXML §17.16）
    if (hasWebSettings(doc.webSettings)) {
      parts['word/webSettings.xml'] = strToU8(writeWebSettings(doc.webSettings));
    }
    // Sprint 253：docProps/core.xml、app.xml、custom.xml 非空才 emit
    if (hasDocProps(doc.docProps)) {
      parts['docProps/core.xml'] = strToU8(writeDocPropsCore(doc.docProps));
    }
    if (hasAppProps(doc.appProps)) {
      parts['docProps/app.xml'] = strToU8(writeDocPropsApp(doc.appProps));
    }
    if (doc.customProps.size > 0) {
      parts['docProps/custom.xml'] = strToU8(writeDocPropsCustom(doc.customProps));
    }
    // Sprint 262：theme1.xml 有 parsedTheme 才 emit（OOXML §20.1.6）
    if (doc.theme !== undefined) {
      parts['word/theme/theme1.xml'] = strToU8(writeTheme(doc.theme));
    }
    // Sprint 192：把每張 media 圖片的 bytes 寫進 zip
    for (const m of mediaItems) {
      parts[m.target] = m.bytes;
    }
    // Sprint 193：把每個 header/footer 部件寫進 zip
    for (const hf of hfItems) {
      parts[hf.filename] = strToU8(writeHeaderFooterPart(hf));
    }
    // Sprint 195：SmartArt diagram data 部件
    for (const sa of smartArtItems) {
      parts[sa.filename] = strToU8(writeSmartArtPart(sa));
    }
    // Sprint 195：Chart 部件
    for (const ch of chartItems) {
      parts[ch.filename] = strToU8(writeChartPart(ch));
    }
    // Sprint 196：watermark header 部件
    if (watermarkItem) {
      parts[watermarkItem.filename] = strToU8(writeWatermarkHeaderPart(watermarkItem));
    }
    return zipSync(parts);
  }
}

// ── 各 part 寫出函式 ─────────────────────────────────────────────────────────

/**
 * `[Content_Types].xml`：宣告 part MIME 型別。
 *
 * Sprint 192：依 doc 內出現的圖片副檔名集合新增 Default entries
 * （`<Default Extension="png" ContentType="image/png"/>` 等）。Word 對未宣告
 * 副檔名的 part 會回退到「未知」處理、可能丟失。
 */
function writeContentTypes(
  imageExtensions: Set<string>,
  hfItems: HeaderFooterItem[],
  smartArtItems: SmartArtPartItem[] = [],
  chartItems: ChartPartItem[] = [],
  watermarkItem: WatermarkHeaderItem | undefined = undefined,
  doc?: DocumentNode,
): string {
  const imageDefaults: string[] = [];
  for (const ext of imageExtensions) {
    const ct = mimeForExtension(ext);
    imageDefaults.push(`<Default Extension="${escapeXml(ext)}" ContentType="${ct}"/>`);
  }
  // Sprint 193：每個 header / footer 部件加 Override
  const hfOverrides = hfItems.map((hf) => {
    const ct = hf.kind === 'header'
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml'
      : 'application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml';
    return `<Override PartName="/${hf.filename}" ContentType="${ct}"/>`;
  }).join('');
  // Sprint 195：SmartArt diagram data / Chart 部件 Override
  const smartArtOverrides = smartArtItems.map((sa) =>
    `<Override PartName="/${sa.filename}" ContentType="application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml"/>`
  ).join('');
  const chartOverrides = chartItems.map((ch) =>
    `<Override PartName="/${ch.filename}" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>`
  ).join('');
  // Sprint 196：watermark header 部件用 header MIME 同 hfOverrides
  const watermarkOverride = watermarkItem
    ? `<Override PartName="/${watermarkItem.filename}" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>`
    : '';
  return xmlDecl() +
    `<Types xmlns="${CT_NS}">` +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    imageDefaults.join('') +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>' +
    '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>' +
    // Sprint 239：footnotes.xml / endnotes.xml Override（非空才宣告）
    (doc && doc.footnotes.size > 0
      ? '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
      : '') +
    (doc && doc.endnotes.size > 0
      ? '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/>'
      : '') +
    // Sprint 243：settings.xml Override（非空才宣告）
    (doc && hasSettings(doc.settings)
      ? '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
      : '') +
    // Sprint 246：fontTable.xml Override（非空才宣告）
    (doc && doc.fontTable.size > 0
      ? '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
      : '') +
    // Sprint 249：webSettings.xml Override（非空才宣告）
    (doc && hasWebSettings(doc.webSettings)
      ? '<Override PartName="/word/webSettings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.webSettings+xml"/>'
      : '') +
    // Sprint 253：docProps Override（非空才宣告）
    (doc && hasDocProps(doc.docProps)
      ? '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
      : '') +
    (doc && hasAppProps(doc.appProps)
      ? '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
      : '') +
    (doc && doc.customProps.size > 0
      ? '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
      : '') +
    // Sprint 262：theme1.xml Override（doc.theme 有值才宣告）
    (doc && doc.theme !== undefined
      ? '<Override PartName="/word/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
      : '') +
    hfOverrides +
    smartArtOverrides +
    chartOverrides +
    watermarkOverride +
    '</Types>';
}

/** `_rels/.rels`：root 關係（→ word/document.xml）。 */
function writeRootRels(doc?: DocumentNode): string {
  return xmlDecl() +
    `<Relationships xmlns="${REL_NS}">` +
    `<Relationship Id="rId1" Type="${REL_TYPE_OFFICE_DOCUMENT}" Target="word/document.xml"/>` +
    // Sprint 253：docProps root rels（非空才宣告）
    (doc && hasDocProps(doc.docProps)
      ? `<Relationship Id="rIdCore" Type="${REL_TYPE_CORE_PROPERTIES}" Target="docProps/core.xml"/>`
      : '') +
    (doc && hasAppProps(doc.appProps)
      ? `<Relationship Id="rIdApp" Type="${REL_TYPE_EXTENDED_PROPERTIES}" Target="docProps/app.xml"/>`
      : '') +
    (doc && doc.customProps.size > 0
      ? `<Relationship Id="rIdCustom" Type="${REL_TYPE_CUSTOM_PROPERTIES}" Target="docProps/custom.xml"/>`
      : '') +
    '</Relationships>';
}

/**
 * `word/_rels/document.xml.rels`：document 關係（styles + numbering + images）。
 *
 * Sprint 192：styles / numbering 用具名 Id（rIdStyles / rIdNumbering）以避免
 * 與 image rIds 的數字命名空間衝突（image rIds 從 doc.media 原樣帶入、可能
 * 是 "rId1" 等）。
 */
function writeDocumentRels(
  mediaItems: MediaItem[],
  hfItems: HeaderFooterItem[],
  smartArtItems: SmartArtPartItem[] = [],
  chartItems: ChartPartItem[] = [],
  watermarkItem: WatermarkHeaderItem | undefined = undefined,
  doc?: DocumentNode,
): string {
  const imageRels: string[] = [];
  for (const m of mediaItems) {
    // Target 為相對 word/ 目錄：去掉 'word/' 前綴
    const target = m.target.startsWith('word/') ? m.target.slice('word/'.length) : m.target;
    imageRels.push(
      `<Relationship Id="${escapeXml(m.rId)}" Type="${REL_TYPE_IMAGE}" Target="${escapeXml(target)}"/>`,
    );
  }
  // Sprint 193：header / footer rels（rId 從 doc.headers/footers Map keys 取）
  const hfRels = hfItems.map((hf) => {
    const target = hf.filename.startsWith('word/') ? hf.filename.slice('word/'.length) : hf.filename;
    const type = hf.kind === 'header' ? REL_TYPE_HEADER : REL_TYPE_FOOTER;
    return `<Relationship Id="${escapeXml(hf.rId)}" Type="${type}" Target="${escapeXml(target)}"/>`;
  }).join('');
  // Sprint 195：SmartArt diagram data / Chart rels（rId 從 doc.smartArts/charts node.rId 取）
  const smartArtRels = smartArtItems.map((sa) => {
    const target = sa.filename.startsWith('word/') ? sa.filename.slice('word/'.length) : sa.filename;
    return `<Relationship Id="${escapeXml(sa.rId)}" Type="${REL_TYPE_DIAGRAM_DATA}" Target="${escapeXml(target)}"/>`;
  }).join('');
  const chartRels = chartItems.map((ch) => {
    const target = ch.filename.startsWith('word/') ? ch.filename.slice('word/'.length) : ch.filename;
    return `<Relationship Id="${escapeXml(ch.rId)}" Type="${REL_TYPE_CHART}" Target="${escapeXml(target)}"/>`;
  }).join('');
  // Sprint 196：watermark header 部件 rels 條目（REL_TYPE_HEADER）
  const watermarkRel = watermarkItem
    ? `<Relationship Id="${escapeXml(watermarkItem.rId)}" Type="${REL_TYPE_HEADER}" Target="${escapeXml(watermarkItem.filename.startsWith('word/') ? watermarkItem.filename.slice('word/'.length) : watermarkItem.filename)}"/>`
    : '';
  return xmlDecl() +
    `<Relationships xmlns="${REL_NS}">` +
    `<Relationship Id="rIdStyles" Type="${REL_TYPE_STYLES}" Target="styles.xml"/>` +
    `<Relationship Id="rIdNumbering" Type="${REL_TYPE_NUMBERING}" Target="numbering.xml"/>` +
    `<Relationship Id="rIdComments" Type="${REL_TYPE_COMMENTS}" Target="comments.xml"/>` +
    // Sprint 239：footnotes / endnotes rel（非空才宣告）
    (doc && doc.footnotes.size > 0
      ? `<Relationship Id="rIdFootnotes" Type="${REL_TYPE_FOOTNOTES}" Target="footnotes.xml"/>`
      : '') +
    (doc && doc.endnotes.size > 0
      ? `<Relationship Id="rIdEndnotes" Type="${REL_TYPE_ENDNOTES}" Target="endnotes.xml"/>`
      : '') +
    // Sprint 243：settings.xml rel（非空才宣告）
    (doc && hasSettings(doc.settings)
      ? `<Relationship Id="rIdSettings" Type="${REL_TYPE_SETTINGS}" Target="settings.xml"/>`
      : '') +
    // Sprint 246：fontTable.xml rel（非空才宣告）
    (doc && doc.fontTable.size > 0
      ? `<Relationship Id="rIdFontTable" Type="${REL_TYPE_FONT_TABLE}" Target="fontTable.xml"/>`
      : '') +
    // Sprint 249：webSettings.xml rel（非空才宣告）
    (doc && hasWebSettings(doc.webSettings)
      ? `<Relationship Id="rIdWebSettings" Type="${REL_TYPE_WEB_SETTINGS}" Target="webSettings.xml"/>`
      : '') +
    // Sprint 262：theme1.xml rel（doc.theme 有值才宣告；OOXML §13.2.5）
    (doc && doc.theme !== undefined
      ? `<Relationship Id="rIdTheme" Type="${REL_TYPE_THEME}" Target="theme/theme1.xml"/>`
      : '') +
    imageRels.join('') +
    hfRels +
    smartArtRels +
    chartRels +
    watermarkRel +
    '</Relationships>';
}

/**
 * `word/styles.xml`：Sprint 189 完整輸出 DocumentNode.styles。
 *
 * 序列化策略（與 parser StyleResolver 對稱）：
 *   - DocumentNode.styles 為 StyleMap = Map<styleId, StyleEntry>。
 *   - StyleResolver 在 parse 時把 docDefaults → basedOn 鏈 → current props 全部
 *     flatten 進 entry.pProps / entry.rProps，故 export **不需**輸出
 *     `<w:docDefaults>` 與 `<w:basedOn>`（re-parse 時 resolver 看不到 docDefaults
 *     與 basedOn、entry 的 flat props 原樣保留 → round-trip 等價）。
 *   - 每個 style 統一 `w:type="paragraph"`（StyleEntry 不保留 type、type 在
 *     re-parse 時不影響 pProps/rProps 解析結果）。
 *   - StyleEntry.name / conditional table styles 留後續 sprint。
 *
 * 空 StyleMap → 空 `<w:styles/>` 骨架（與 Sprint 185 MVS 相容）。
 */
function writeStyles(doc: DocumentNode): string {
  if (doc.styles.size === 0) {
    return xmlDecl() + `<w:styles xmlns:w="${W_NS}"/>`;
  }
  const entries: string[] = [];
  for (const [styleId, entry] of doc.styles) {
    entries.push(writeStyleEntry(styleId, entry));
  }
  return xmlDecl() +
    `<w:styles xmlns:w="${W_NS}">` +
    entries.join('') +
    '</w:styles>';
}

/**
 * Sprint 189：序列化單一 StyleEntry 為 `<w:style w:type="paragraph" w:styleId="...">`。
 *
 * 內容：可選 `<w:pPr>` + `<w:rPr>`。pProps / rProps 皆無 → 空 body（`<w:style/>`）；
 * 保持 styleId 鍵的存在性以便 round-trip Map 大小一致。
 */
function writeStyleEntry(styleId: string, entry: { pProps?: ParagraphProps; rProps?: RunProps; basedOn?: string }): string {
  // Sprint 230：先 emit `<w:basedOn>` 以保留 style 繼承鏈（Sprint 189 設計
  // 為 render 對等故 flat、但 audit 揭發 entry.basedOn 欄位本身 round-trip
  // drift；StyleResolver 在 reparse 時對已 flat 的 props 重新套 basedOn 是
  // idempotent、不會破壞既有 flat props 結果、僅恢復 basedOn 欄位）。
  const basedOnXml = entry.basedOn !== undefined
    ? `<w:basedOn w:val="${escapeXml(entry.basedOn)}"/>`
    : '';
  const pPrXml = writePPr(entry.pProps ?? {}, undefined);
  const rPrXml = writeRPr(entry.rProps ?? {});
  const inner = basedOnXml + pPrXml + rPrXml;
  const attrs = `w:type="paragraph" w:styleId="${escapeXml(styleId)}"`;
  return inner === ''
    ? `<w:style ${attrs}/>`
    : `<w:style ${attrs}>${inner}</w:style>`;
}

/**
 * `word/document.xml`：把 DocumentNode 序列化為 `<w:document>`。
 *
 * MVS 策略：把所有 section 的段落串成單一 body、用**最後一個** section 的
 * page/margins 作為 trailing `<w:sectPr>`。多 section 場景退化為單 section
 * （多 section 區隔資訊有損；後續 sprint 補）。
 */
/**
 * `word/document.xml`：把 DocumentNode 序列化為 `<w:document>`。
 *
 * Sprint 191：完整支援多 section（OOXML §17.6）。對 N 個 section：
 *   - section 0..N-2：emit blocks、之後追加「anchor paragraph」
 *     `<w:p><w:pPr><w:sectPr>...</w:sectPr></w:pPr></w:p>` 結束該 section
 *   - section N-1：emit blocks、之後 body 末端追加 `<w:sectPr>`
 *
 * （parser walkBodyAsSections 支援兩種 sectPr 位置：段內 pPr 或 body 末端。）
 */
function writeDocument(doc: DocumentNode, watermarkItem: WatermarkHeaderItem | undefined = undefined): string {
  const bodyParts: string[] = [];
  const n = doc.sections.length;
  for (let i = 0; i < n; i++) {
    const sec = doc.sections[i];
    for (const block of sec.body) {
      bodyParts.push(writeBlock(block));
    }
    if (i < n - 1) {
      // 非最後 section：anchor paragraph 把 sectPr 嵌入 pPr 內、結束該 section
      bodyParts.push(`<w:p><w:pPr>${writeSectPr(sec, watermarkItem)}</w:pPr></w:p>`);
    }
  }
  // 最後 section（或無 section 時 fallback）：body 末端 sectPr
  bodyParts.push(writeSectPr(n > 0 ? doc.sections[n - 1] : undefined, watermarkItem));

  // Sprint 194：`<w:background>` 為 `<w:document>` 直接子（在 `<w:body>` 之前）
  const backgroundEl = writeBackground(doc.background);

  return xmlDecl() +
    `<w:document xmlns:w="${W_NS}" xmlns:r="${R_NS}">` +
    backgroundEl +
    '<w:body>' +
    bodyParts.join('') +
    '</w:body>' +
    '</w:document>';
}

/**
 * Sprint 194：`<w:background>` 文件背景（OOXML §17.2.1）。
 *
 * 為 `<w:document>` 的直接子元素（`<w:body>` 之 sibling）、表頁面背景色。
 * 紀律 #21：無 background → 回空字串。
 */
function writeBackground(bg: DocumentNode['background']): string {
  if (!bg) return '';
  const color = bg.color;
  if (!color) return '';
  return `<w:background w:color="${escapeXml(color)}"/>`;
}

/**
 * Sprint 190：把 BlockNode（paragraph / table）序列化。
 * 巢狀表格用 —— cell.content 內亦呼叫此函式遞迴處理。
 */
function writeBlock(block: BlockNode): string {
  return block.type === 'paragraph' ? writeParagraph(block) : writeTable(block);
}

/**
 * 單一段落 `<w:p>`：可選 `<w:pPr>` + 各 RunNode。
 *
 * Sprint 187：加 ParagraphProps + styleId 序列化、`<w:pPr>` 子元素依 CT_PPr
 * schema 順序輸出（pStyle → keepNext → keepLines → pageBreakBefore → numPr →
 * tabs → spacing → ind → jc → textAlignment → snapToGrid）。
 */
function writeParagraph(para: ParagraphNode): string {
  const pPr = writePPr(para.props, para.styleId);

  // Sprint 194：commentRangeStart 在 runs 之前
  const commentRefs = para.commentRefs ?? [];
  const rangeStarts = commentRefs.map((id) => `<w:commentRangeStart w:id="${id}"/>`).join('');
  const rangeEnds = commentRefs.map((id) => `<w:commentRangeEnd w:id="${id}"/>`).join('');
  // commentReference 元素需放在 `<w:r>` 內、放於段落末以代表 comment 錨點位置
  const commentReferences = commentRefs
    .map((id) => `<w:r><w:commentReference w:id="${id}"/></w:r>`)
    .join('');

  const runs: string[] = [];
  for (const node of para.runs) {
    if (node.type === 'run') {
      // Sprint 194：追蹤修訂 `<w:ins>` / `<w:del>` 包裹 run
      runs.push(node.revision ? writeRevisedRun(node) : writeRun(node));
    } else if (node.type === 'inlineImage' || node.type === 'floatImage') {
      // Sprint 192：圖片 → `<w:r><w:drawing><wp:inline>...`
      // floatImage 降級為 inline（與 ToCanvasEditor 一致：canvas-editor
      // 浮動繞排支援不完整、production pipeline 已將 float 視為 inline）
      runs.push(writeInlineImageRun(node));
    } else if (node.type === 'footnoteRef') {
      // Sprint 242 — Phase 1 optional 第二批升級：footnoteReference / endnoteReference
      const tag = node.noteType === 'footnote' ? 'w:footnoteReference' : 'w:endnoteReference';
      runs.push(`<w:r><${tag} w:id="${node.id}"/></w:r>`);
    }
    // break / field 仍跳過、留後續 sprint
  }

  // Sprint 194：para.math 線性 fallback → 同 Sprint 180 ToCanvasEditor 邏輯、
  // 但這裡寫回完整 OMML 樹（高保真 round-trip）而非線性化文字
  const mathXml = writeParagraphMath(para.math);

  return `<w:p>${pPr}${rangeStarts}${runs.join('')}${mathXml}${commentReferences}${rangeEnds}</w:p>`;
}

/**
 * Sprint 187：把 ParagraphProps + styleId 序列化為 `<w:pPr>` 屬性容器。
 *
 * 子元素順序依 OOXML CT_PPr schema（§17.3.1）大致排序。紀律 #21：欄位皆
 * optional、無值不掛子元素；props 全空且無 styleId → 回空字串
 * （不輸出 `<w:pPr>` 標籤、與 parser「無 pPr 視為無 props」對稱）。
 *
 * 本 sprint 覆蓋：pStyle / keepNext / keepLines / pageBreakBefore / numPr
 * (numId+ilvl) / tabs / spacing / ind / jc / textAlignment / snapToGrid。
 * 留後續：borders（pBdr）/ shading（shd）/ framePr。
 */
function writePPr(props: ParagraphProps, styleId: string | undefined): string {
  const parts: string[] = [];

  // 1. <w:pStyle> — 段落樣式 ID（CT_PPr schema 第一個子元素）
  if (styleId !== undefined && styleId !== '') {
    parts.push(`<w:pStyle w:val="${escapeXml(styleId)}"/>`);
  }

  // 2-4. toggle properties（true=空 element、false=w:val="0" 顯式覆蓋 style）
  if (props.keepNext === true) parts.push('<w:keepNext/>');
  else if (props.keepNext === false) parts.push('<w:keepNext w:val="0"/>');
  if (props.keepLines === true) parts.push('<w:keepLines/>');
  else if (props.keepLines === false) parts.push('<w:keepLines w:val="0"/>');
  if (props.pageBreakBefore === true) parts.push('<w:pageBreakBefore/>');
  else if (props.pageBreakBefore === false) parts.push('<w:pageBreakBefore w:val="0"/>');

  // 5. <w:framePr>：段落框（CT_PPr schema 在 pageBreakBefore 與 numPr 之間）
  const framePrXml = writeFramePr(props.framePr);
  if (framePrXml) parts.push(framePrXml);

  // 6. <w:numPr>：清單編號（ilvl + numId 兩子元素）
  if (props.numId !== undefined || props.ilvl !== undefined) {
    const inner: string[] = [];
    if (props.ilvl !== undefined) inner.push(`<w:ilvl w:val="${props.ilvl}"/>`);
    if (props.numId !== undefined) inner.push(`<w:numId w:val="${props.numId}"/>`);
    parts.push(`<w:numPr>${inner.join('')}</w:numPr>`);
  }

  // 7. <w:pBdr>：段落邊框（CT_PPr schema 在 numPr 之後、tabs 之前）
  const pBdrXml = writePBdr(props.borders);
  if (pBdrXml) parts.push(pBdrXml);

  // 8. <w:shd>：段落底色 / 圖案（CT_PPr schema 在 pBdr 之後）
  const shdXml = writeShd(props.shading);
  if (shdXml) parts.push(shdXml);

  // 9. <w:tabs>：tab stop 陣列
  if (props.tabs && props.tabs.length > 0) {
    const tabEls = props.tabs.map((t) => {
      const attrs = [`w:val="${t.align}"`, `w:pos="${ptToTwips(t.pos)}"`];
      if (t.leader) attrs.push(`w:leader="${escapeXml(t.leader)}"`);
      return `<w:tab ${attrs.join(' ')}/>`;
    });
    parts.push(`<w:tabs>${tabEls.join('')}</w:tabs>`);
  }

  // 10. <w:spacing>：段前 / 段後 / 行距
  if (props.spacing) {
    const attrs: string[] = [];
    if (props.spacing.before !== undefined) attrs.push(`w:before="${ptToTwips(props.spacing.before)}"`);
    if (props.spacing.after !== undefined) attrs.push(`w:after="${ptToTwips(props.spacing.after)}"`);
    if (props.spacing.line) {
      const { rule, value } = props.spacing.line;
      // auto 規則用 240 分母（Word 慣例）；其餘 rule = twips
      const lineVal = rule === 'auto'
        ? Math.round(value * LINE_SPACING_AUTO_BASE)
        : ptToTwips(value);
      attrs.push(`w:line="${lineVal}"`);
      attrs.push(`w:lineRule="${rule}"`);
    }
    if (attrs.length > 0) parts.push(`<w:spacing ${attrs.join(' ')}/>`);
  }

  // 11. <w:ind>：縮排
  if (props.indent) {
    const attrs: string[] = [];
    if (props.indent.left !== undefined) attrs.push(`w:left="${ptToTwips(props.indent.left)}"`);
    if (props.indent.right !== undefined) attrs.push(`w:right="${ptToTwips(props.indent.right)}"`);
    if (props.indent.firstLine !== undefined) attrs.push(`w:firstLine="${ptToTwips(props.indent.firstLine)}"`);
    if (props.indent.hanging !== undefined) attrs.push(`w:hanging="${ptToTwips(props.indent.hanging)}"`);
    if (attrs.length > 0) parts.push(`<w:ind ${attrs.join(' ')}/>`);
  }

  // 12. <w:jc>：水平對齊
  if (props.alignment !== undefined) {
    parts.push(`<w:jc w:val="${props.alignment}"/>`);
  }

  // 13. <w:textAlignment>：行內垂直對齊
  if (props.textAlignment !== undefined) {
    parts.push(`<w:textAlignment w:val="${props.textAlignment}"/>`);
  }

  // 14. <w:snapToGrid>：是否貼齊 docGrid
  if (props.snapToGrid === true) parts.push('<w:snapToGrid/>');
  else if (props.snapToGrid === false) parts.push('<w:snapToGrid w:val="0"/>');

  return parts.length > 0 ? `<w:pPr>${parts.join('')}</w:pPr>` : '';
}

/**
 * Sprint 188：把 `ParagraphProps.framePr` 序列化為 `<w:framePr/>`（自閉合）。
 *
 * 屬性順序對 Word reader 不重要、本實作依 OOXML §17.3.1.11 文件出現順序輸出
 * （w / h / hRule / hSpace / vSpace / wrap / hAnchor / vAnchor / xAlign /
 * yAlign / x / y）。w/h/hSpace/vSpace/x/y 為 twips、其餘列舉值原樣輸出。
 *
 * 紀律 #21：framePr undefined 或所有欄位皆空 → 回空字串、不輸出 `<w:framePr/>`。
 */
function writeFramePr(framePr: ParagraphProps['framePr']): string {
  if (!framePr) return '';
  const attrs: string[] = [];
  if (framePr.width !== undefined) attrs.push(`w:w="${ptToTwips(framePr.width)}"`);
  if (framePr.height !== undefined) attrs.push(`w:h="${ptToTwips(framePr.height)}"`);
  if (framePr.hRule !== undefined) attrs.push(`w:hRule="${framePr.hRule}"`);
  if (framePr.hSpace !== undefined) attrs.push(`w:hSpace="${ptToTwips(framePr.hSpace)}"`);
  if (framePr.vSpace !== undefined) attrs.push(`w:vSpace="${ptToTwips(framePr.vSpace)}"`);
  if (framePr.wrap !== undefined) attrs.push(`w:wrap="${framePr.wrap}"`);
  if (framePr.hAnchor !== undefined) attrs.push(`w:hAnchor="${framePr.hAnchor}"`);
  if (framePr.vAnchor !== undefined) attrs.push(`w:vAnchor="${framePr.vAnchor}"`);
  if (framePr.xAlign !== undefined) attrs.push(`w:xAlign="${framePr.xAlign}"`);
  if (framePr.yAlign !== undefined) attrs.push(`w:yAlign="${framePr.yAlign}"`);
  if (framePr.x !== undefined) attrs.push(`w:x="${ptToTwips(framePr.x)}"`);
  if (framePr.y !== undefined) attrs.push(`w:y="${ptToTwips(framePr.y)}"`);
  return attrs.length > 0 ? `<w:framePr ${attrs.join(' ')}/>` : '';
}

/**
 * Sprint 188：把 `ParagraphProps.borders` 序列化為 `<w:pBdr>`（OOXML §17.3.1.24）。
 *
 * 子元素：`<w:top w:val w:sz w:color w:space/>`、bottom / left / right 同結構。
 * `w:sz` 單位 = 1/8 pt（內部 `BorderDef.width: Pt` × 8、四捨五入）。
 * between / bar 子元素本 sprint 不支援（types.ts 也未含、後續若需要再補）。
 *
 * 紀律 #21：無 borders 或所有邊都 undefined → 回空字串。
 */
function writePBdr(borders: ParagraphProps['borders']): string {
  if (!borders) return '';
  const sides: Array<keyof NonNullable<ParagraphProps['borders']>> = ['top', 'bottom', 'left', 'right'];
  const inner: string[] = [];
  for (const side of sides) {
    const b = borders[side];
    if (!b) continue;
    const attrs = [
      `w:val="${escapeXml(b.style)}"`,
      `w:sz="${Math.round(b.width * BORDER_EIGHTHS_PER_PT)}"`,
      `w:color="${escapeXml(b.color)}"`,
    ];
    if (b.space !== undefined) attrs.push(`w:space="${Math.round(b.space)}"`);
    inner.push(`<w:${side} ${attrs.join(' ')}/>`);
  }
  return inner.length > 0 ? `<w:pBdr>${inner.join('')}</w:pBdr>` : '';
}

/**
 * Sprint 188：把 `ParagraphProps.shading` 序列化為 `<w:shd/>`（OOXML §17.3.5.34）。
 *
 * `shading.pattern` → `w:val`（"clear" / "solid" / "pct10" 等圖案）；
 * `shading.fill` → `w:fill`（背景 hex）；`shading.color` → `w:color`（前景 hex）。
 *
 * 紀律 #21：無 shading 或所有欄位空 → 回空字串。
 */
function writeShd(shading: ParagraphProps['shading']): string {
  if (!shading) return '';
  const attrs: string[] = [];
  if (shading.pattern !== undefined) attrs.push(`w:val="${escapeXml(shading.pattern)}"`);
  if (shading.fill !== undefined) attrs.push(`w:fill="${escapeXml(shading.fill)}"`);
  if (shading.color !== undefined) attrs.push(`w:color="${escapeXml(shading.color)}"`);
  return attrs.length > 0 ? `<w:shd ${attrs.join(' ')}/>` : '';
}

/**
 * 單一文字 run `<w:r>`：含可選 `<w:rPr>` + `<w:t>`。
 *
 * Sprint 186：加 RunProps 序列化（粗體 / 斜體 / 刪除線 / 底線 / 字級 / 顏色 /
 * 字型 / 高亮 / 上下標 / 字距 / 語言）。紀律 #21：無 props 時不輸出 `<w:rPr>`。
 */
function writeRun(run: RunNode, useDelText = false): string {
  const rPr = writeRPr(run.props);
  // `xml:space="preserve"` 保留前後空白（OOXML §17.3.3.31）；一律帶上
  // Sprint 194：`<w:del>` 包裹的 run 用 `<w:delText>` 而非 `<w:t>`
  const textTag = useDelText ? 'w:delText' : 'w:t';
  return `<w:r>${rPr}<${textTag} xml:space="preserve">${escapeXml(run.text)}</${textTag}></w:r>`;
}

/**
 * Sprint 194：把 run.revision 序列化為 `<w:ins>` 或 `<w:del>` 包裹的 run
 * （OOXML §17.13.5 / §17.13.5.14）。
 *
 * - ins：`<w:ins w:id w:author? w:date?><w:r>...</w:r></w:ins>`
 * - del：`<w:del w:id w:author? w:date?><w:r>...<w:delText>...</w:delText></w:r></w:del>`
 */
function writeRevisedRun(run: RunNode): string {
  const rev = run.revision!;
  const tag = rev.type === 'ins' ? 'w:ins' : 'w:del';
  const attrs: string[] = [`w:id="${rev.id ?? 0}"`];
  if (rev.author !== undefined) attrs.push(`w:author="${escapeXml(rev.author)}"`);
  if (rev.date !== undefined) attrs.push(`w:date="${escapeXml(rev.date)}"`);
  const inner = writeRun(run, rev.type === 'del');
  return `<${tag} ${attrs.join(' ')}>${inner}</${tag}>`;
}

/**
 * Sprint 186：把 RunProps 序列化為 `<w:rPr>` 屬性容器。
 *
 * 子元素順序大致依 OOXML CT_RPr schema（§17.3.2）：
 *   rFonts → b → i → strike → dstrike → color → spacing → sz → highlight →
 *   u → vertAlign → lang
 *
 * 紀律 #21：所有欄位皆 optional、無值不掛、props 全空 → 回空字串（不輸出
 * `<w:rPr/>` 標籤、與 parser 「無 rPr 就視為無 props」對稱）。
 */
function writeRPr(props: RunProps): string {
  if (!props || Object.keys(props).length === 0) return '';
  const parts: string[] = [];

  // w:rFonts ascii / eastAsia / hAnsi / cs（缺漏屬性跳過）
  const fontAttrs: string[] = [];
  if (props.fontFamily !== undefined) fontAttrs.push(`w:ascii="${escapeXml(props.fontFamily)}"`);
  if (props.fontFamilyEastAsia !== undefined) fontAttrs.push(`w:eastAsia="${escapeXml(props.fontFamilyEastAsia)}"`);
  if (props.fontFamilyHAnsi !== undefined) fontAttrs.push(`w:hAnsi="${escapeXml(props.fontFamilyHAnsi)}"`);
  if (props.fontFamilyCs !== undefined) fontAttrs.push(`w:cs="${escapeXml(props.fontFamilyCs)}"`);
  if (fontAttrs.length > 0) parts.push(`<w:rFonts ${fontAttrs.join(' ')}/>`);

  // toggle properties：true → 空 element、false → w:val="0"（顯式關閉、覆蓋 style）
  if (props.bold === true) parts.push('<w:b/>');
  else if (props.bold === false) parts.push('<w:b w:val="0"/>');
  if (props.italic === true) parts.push('<w:i/>');
  else if (props.italic === false) parts.push('<w:i w:val="0"/>');
  if (props.strike === true) parts.push('<w:strike/>');
  else if (props.strike === false) parts.push('<w:strike w:val="0"/>');
  if (props.dstrike === true) parts.push('<w:dstrike/>');
  else if (props.dstrike === false) parts.push('<w:dstrike w:val="0"/>');

  // w:color w:val="RRGGBB"（或 auto / themeColor、本 sprint 只支援具體 hex）
  if (props.color !== undefined) parts.push(`<w:color w:val="${escapeXml(props.color)}"/>`);

  // w:spacing w:val（字元間距、單位 = 20 倍 pt = twips；可正可負）
  if (props.spacing !== undefined) parts.push(`<w:spacing w:val="${ptToTwips(props.spacing)}"/>`);

  // w:sz w:val（half-points、12pt = 24）
  if (props.fontSize !== undefined) parts.push(`<w:sz w:val="${ptToHalfPoints(props.fontSize)}"/>`);

  // w:highlight w:val（具名色 yellow / cyan / red…；HexColor 型別也可能裝具名色字串）
  if (props.highlight !== undefined) parts.push(`<w:highlight w:val="${escapeXml(props.highlight)}"/>`);

  // w:u w:val（none / single / double / words / thick / wave / 自訂…）
  if (props.underline !== undefined) parts.push(`<w:u w:val="${escapeXml(props.underline)}"/>`);

  // w:vertAlign w:val（baseline / superscript / subscript）
  if (props.vertAlign !== undefined) parts.push(`<w:vertAlign w:val="${escapeXml(props.vertAlign)}"/>`);

  // w:lang w:val（zh-TW / en-US / ja-JP…）
  if (props.lang !== undefined) parts.push(`<w:lang w:val="${escapeXml(props.lang)}"/>`);

  return parts.length > 0 ? `<w:rPr>${parts.join('')}</w:rPr>` : '';
}

/**
 * `<w:sectPr>` —— section 屬性容器（OOXML §17.6.17 CT_SectPr）。
 *
 * 子元素依 schema 順序：headerReference / footerReference / pgSz / pgMar /
 * titlePg。Sprint 193 加 headerRefs / footerRefs / titlePage 序列化。
 */
function writeSectPr(section: SectionNode | undefined, watermarkItem: WatermarkHeaderItem | undefined = undefined): string {
  const parts: string[] = [];

  // Sprint 193：headerReference / footerReference（schema 順序最前）
  // Sprint 196：對「無既有 default header」的 section 注入 watermark rId 為 default；
  //            「有既有 default header」的 section 仍走原 default（honest sub-gap：
  //            watermark 視覺不出現於這些 section、但 watermark header 部件仍 emit、
  //            round-trip 保 watermark capture 對稱性）。
  if (section) {
    const headerRefs = section.headerRefs;
    const injectedHeaderRefs = watermarkItem && headerRefs.default === undefined
      ? { ...headerRefs, default: watermarkItem.rId }
      : headerRefs;
    parts.push(...writeRefs('w:headerReference', injectedHeaderRefs));
    parts.push(...writeRefs('w:footerReference', section.footerRefs));
  } else if (watermarkItem) {
    // 無 section（極少見、僅 fallback）：仍 emit 一筆 default headerReference 指向 watermark
    parts.push(`<w:headerReference w:type="default" r:id="${escapeXml(watermarkItem.rId)}"/>`);
  }

  // Sprint 226：sectionBreakType（CT_SectPr schema：type 在 pgSz 之前）
  // parser 對 `<w:type>` 缺 element 不存 sectionBreakType、若 writer 不 emit
  // 已存的 type、'continuous'/'evenPage'/'oddPage' 等非預設值會在 round-trip
  // 丟失（reparse 為 undefined ≡ 預設 'nextPage'）、多 section 文件破壞。
  if (section?.sectionBreakType !== undefined) {
    parts.push(`<w:type w:val="${section.sectionBreakType}"/>`);
  }

  // pgSz / pgMar（section 缺漏 → A4 + Word 預設邊距）
  const page = section?.page;
  const margins = section?.margins;
  const w = ptToTwips(page?.width ?? DEFAULT_PAGE_WIDTH_PT);
  const h = ptToTwips(page?.height ?? DEFAULT_PAGE_HEIGHT_PT);
  const top = ptToTwips(margins?.top ?? DEFAULT_MARGIN_TB_PT);
  const right = ptToTwips(margins?.right ?? DEFAULT_MARGIN_LR_PT);
  const bottom = ptToTwips(margins?.bottom ?? DEFAULT_MARGIN_TB_PT);
  const left = ptToTwips(margins?.left ?? DEFAULT_MARGIN_LR_PT);
  const headerMargin = ptToTwips(margins?.header ?? DEFAULT_MARGIN_HF_PT);
  const footerMargin = ptToTwips(margins?.footer ?? DEFAULT_MARGIN_HF_PT);
  parts.push(`<w:pgSz w:w="${w}" w:h="${h}"/>`);
  // Sprint 225：gutter 條件 emit—— parser 對缺 attr 不存 gutter、若 writer
  // 硬寫 "0" 會讓「source 無 gutter」的 fixture 在 round-trip 被注入
  // gutter=0、reparse 對等性破壞。
  const gutterAttr = margins?.gutter !== undefined ? ` w:gutter="${ptToTwips(margins.gutter)}"` : '';
  parts.push(`<w:pgMar w:top="${top}" w:right="${right}" w:bottom="${bottom}" w:left="${left}" w:header="${headerMargin}" w:footer="${footerMargin}"${gutterAttr}/>`);

  // Sprint 226：cols（CT_SectPr schema：cols 在 pgMar 之後、titlePg 之前）
  // parser 對 count<=1 不存 columns、故此處存在即代表多欄；不 emit 會讓
  // 多欄文件 round-trip 退化為單欄。equalWidth 預設 true、只在 false 時
  // emit attribute；個別 colWidths/colSpaces 在 !equalWidth 時 emit `<w:col>` 子節點。
  const columns = section?.columns;
  if (columns && columns.count > 1) {
    const colsAttrs: string[] = [`w:num="${columns.count}"`];
    if (columns.space !== undefined) colsAttrs.push(`w:space="${ptToTwips(columns.space)}"`);
    if (columns.equalWidth === false) colsAttrs.push('w:equalWidth="0"');
    if (columns.separator) colsAttrs.push('w:sep="1"');
    const hasCustomCols = columns.equalWidth === false && columns.colWidths && columns.colWidths.length > 0;
    if (hasCustomCols) {
      const colEls: string[] = [];
      const widths = columns.colWidths!;
      const spaces = columns.colSpaces ?? [];
      for (let i = 0; i < widths.length; i++) {
        const wAttr = ` w:w="${ptToTwips(widths[i])}"`;
        const sAttr = i < spaces.length ? ` w:space="${ptToTwips(spaces[i])}"` : '';
        colEls.push(`<w:col${wAttr}${sAttr}/>`);
      }
      parts.push(`<w:cols ${colsAttrs.join(' ')}>${colEls.join('')}</w:cols>`);
    } else {
      parts.push(`<w:cols ${colsAttrs.join(' ')}/>`);
    }
  }

  // titlePg（在 pgMar 之後、docGrid 之前依 CT_SectPr schema）
  if (section?.titlePage) parts.push('<w:titlePg/>');

  // Sprint 223：docGrid（CT_SectPr schema 末段、CJK 文件 line snap 必要、
  // 不寫會讓中文文件 line height 在 round-trip 丟失 grid 對齊）
  // parser 對 type='default' 不存（返回 undefined）、故此處 section.docGrid
  // 存在即代表 type ∈ {lines, linesAndChars, snapToChars}
  const docGrid = section?.docGrid;
  if (docGrid) {
    const linePitchTwips = ptToTwips(docGrid.linePitch);
    parts.push(`<w:docGrid w:type="${docGrid.type}" w:linePitch="${linePitchTwips}"/>`);
  }

  return '<w:sectPr>' + parts.join('') + '</w:sectPr>';
}

/**
 * Sprint 193：生成 `<w:headerReference>` 或 `<w:footerReference>` 元素陣列。
 * 三種 type（default / first / even）—— 各自 optional、有 rId 才 emit。
 */
function writeRefs(
  elementName: string,
  refs: { default?: string; first?: string; even?: string },
): string[] {
  const out: string[] = [];
  if (refs.default !== undefined) {
    out.push(`<${elementName} w:type="default" r:id="${escapeXml(refs.default)}"/>`);
  }
  if (refs.first !== undefined) {
    out.push(`<${elementName} w:type="first" r:id="${escapeXml(refs.first)}"/>`);
  }
  if (refs.even !== undefined) {
    out.push(`<${elementName} w:type="even" r:id="${escapeXml(refs.even)}"/>`);
  }
  return out;
}

// ── Sprint 190：表格序列化 ────────────────────────────────────────────────────

/**
 * Sprint 190：把 TableNode 序列化為 `<w:tbl>`（OOXML §17.4）。
 *
 * 結構：`<w:tbl><w:tblPr>...</w:tblPr><w:tblGrid>...</w:tblGrid>0..N <w:tr>...</w:tr></w:tbl>`。
 */
function writeTable(table: TableNode): string {
  const tblPr = writeTblPr(table.props, table.styleId);
  const tblGrid = writeTblGrid(table.grid);
  const rows = table.rows.map(writeRow).join('');
  return `<w:tbl>${tblPr}${tblGrid}${rows}</w:tbl>`;
}

/**
 * `<w:tblPr>` — 表格層級屬性（OOXML §17.4.59）。
 *
 * 子元素順序（CT_TblPrBase schema）：tblStyle → tblpPr → tblOverlap → bidiVisual →
 * tblStyleRowBandSize → tblStyleColBandSize → tblW → jc → tblCellSpacing →
 * tblInd → tblBorders → shd → tblLayout → tblCellMar → tblLook → tblCaption →
 * tblDescription → tblPrChange
 */
function writeTblPr(props: TableNode['props'], styleId: string | undefined): string {
  const parts: string[] = [];
  if (styleId !== undefined && styleId !== '') {
    parts.push(`<w:tblStyle w:val="${escapeXml(styleId)}"/>`);
  }
  parts.push(writeTblW(props.width, props.widthType));
  if (props.alignment !== undefined) parts.push(`<w:jc w:val="${props.alignment}"/>`);
  if (props.indent !== undefined) {
    parts.push(`<w:tblInd w:w="${ptToTwips(props.indent)}" w:type="dxa"/>`);
  }
  if (props.borders) parts.push(writeBorderSet(props.borders, 'w:tblBorders'));
  if (props.cellMargins) parts.push(writeTblCellMar(props.cellMargins));
  if (props.look !== undefined) parts.push(`<w:tblLook w:val="${escapeXml(props.look)}"/>`);
  return parts.length > 0 ? `<w:tblPr>${parts.filter((p) => p !== '').join('')}</w:tblPr>` : '';
}

/** `<w:tblW>` / `<w:tcW>` 共用：width(Pt) + widthType → twips + w:type 屬性。 */
function writeTblW(
  width: number | undefined,
  widthType: TableNode['props']['widthType'],
): string {
  // 預設 type = 'dxa'；其餘 pct/auto/nil 時 w 用 0（與 parser 對稱、parser 對非 dxa 不讀 width）
  const type = widthType ?? 'dxa';
  const wVal = type === 'dxa' && width !== undefined ? ptToTwips(width) : 0;
  return `<w:tblW w:w="${wVal}" w:type="${type}"/>`;
}

/** `<w:tcW>` (same encoding as tblW but element name 不同)。 */
function writeTcW(width: number | undefined): string {
  if (width === undefined) return '';
  return `<w:tcW w:w="${ptToTwips(width)}" w:type="dxa"/>`;
}

/** `<w:tblCellMar>` 表格層級預設 cell 邊距。 */
function writeTblCellMar(m: NonNullable<TableNode['props']['cellMargins']>): string {
  const parts: string[] = [];
  if (m.top !== undefined) parts.push(`<w:top w:w="${ptToTwips(m.top)}" w:type="dxa"/>`);
  if (m.left !== undefined) parts.push(`<w:left w:w="${ptToTwips(m.left)}" w:type="dxa"/>`);
  if (m.bottom !== undefined) parts.push(`<w:bottom w:w="${ptToTwips(m.bottom)}" w:type="dxa"/>`);
  if (m.right !== undefined) parts.push(`<w:right w:w="${ptToTwips(m.right)}" w:type="dxa"/>`);
  return parts.length > 0 ? `<w:tblCellMar>${parts.join('')}</w:tblCellMar>` : '';
}

/** `<w:tcMar>` cell 層級邊距（與 tblCellMar 同結構）。 */
function writeTcMar(m: NonNullable<CellNode['props']['margins']>): string {
  const parts: string[] = [];
  if (m.top !== undefined) parts.push(`<w:top w:w="${ptToTwips(m.top)}" w:type="dxa"/>`);
  if (m.left !== undefined) parts.push(`<w:left w:w="${ptToTwips(m.left)}" w:type="dxa"/>`);
  if (m.bottom !== undefined) parts.push(`<w:bottom w:w="${ptToTwips(m.bottom)}" w:type="dxa"/>`);
  if (m.right !== undefined) parts.push(`<w:right w:w="${ptToTwips(m.right)}" w:type="dxa"/>`);
  return parts.length > 0 ? `<w:tcMar>${parts.join('')}</w:tcMar>` : '';
}

/**
 * CellBorders → `<w:tblBorders>` 或 `<w:tcBorders>`（依 wrapper 名）。
 *
 * 子元素 top / left / bottom / right / insideH / insideV，皆 BorderDef 結構：
 * w:val / w:sz (1/8 pt) / w:color / w:space。
 */
function writeBorderSet(borders: CellBorders, wrapper: string): string {
  const sides: Array<keyof CellBorders> = ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'];
  const parts: string[] = [];
  for (const side of sides) {
    const b = borders[side];
    if (!b) continue;
    const attrs = [
      `w:val="${escapeXml(b.style)}"`,
      `w:sz="${Math.round(b.width * BORDER_EIGHTHS_PER_PT)}"`,
      `w:color="${escapeXml(b.color)}"`,
    ];
    if (b.space !== undefined) attrs.push(`w:space="${Math.round(b.space)}"`);
    parts.push(`<w:${side} ${attrs.join(' ')}/>`);
  }
  return parts.length > 0 ? `<${wrapper}>${parts.join('')}</${wrapper}>` : '';
}

/** `<w:tblGrid><w:gridCol w:w="N"/>...</w:tblGrid>`：欄寬定義（皆 twips）。 */
function writeTblGrid(grid: TableNode['grid']): string {
  const cols = grid.map((w) => `<w:gridCol w:w="${ptToTwips(w)}"/>`).join('');
  return `<w:tblGrid>${cols}</w:tblGrid>`;
}

/** `<w:tr>` 單一列。 */
function writeRow(row: RowNode): string {
  const trPr = writeTrPr(row.props);
  const cells = row.cells.map(writeCell).join('');
  return `<w:tr>${trPr}${cells}</w:tr>`;
}

/** `<w:trPr>` — 列屬性（OOXML §17.4.81）：trHeight / tblHeader / cantSplit。 */
function writeTrPr(props: RowNode['props']): string {
  const parts: string[] = [];
  if (props.height !== undefined) {
    const rule = props.heightRule ?? 'auto';
    parts.push(`<w:trHeight w:val="${ptToTwips(props.height)}" w:hRule="${rule}"/>`);
  }
  if (props.isHeader) parts.push('<w:tblHeader/>');
  if (props.cantSplit) parts.push('<w:cantSplit/>');
  return parts.length > 0 ? `<w:trPr>${parts.join('')}</w:trPr>` : '';
}

/**
 * `<w:tc>` 單一儲存格。
 *
 * isContinuation=true 的 cell（vMerge 延續格）仍要輸出 `<w:tc>` —— OOXML 的
 * vMerge 機制需要每個邏輯列都有對應 cell、第二列以後的延續格用 `<w:vMerge/>`
 * （無 w:val、預設 = continue）；最上格用 `<w:vMerge w:val="restart"/>` 開始合併。
 *
 * cell content 為 BlockNode[]（可含巢狀表格）→ writeBlock 遞迴。
 */
function writeCell(cell: CellNode): string {
  const tcPr = writeTcPr(cell);
  const content = cell.content.map(writeBlock).join('');
  // 即使 isContinuation = true、cell 內容仍需有至少一個 <w:p>（OOXML 規範：
  // 每個 <w:tc> 必含一個 block-level child）。若 content 空 → 補空段落。
  const body = content !== '' ? content : '<w:p/>';
  return `<w:tc>${tcPr}${body}</w:tc>`;
}

/** `<w:tcPr>` — cell 屬性（OOXML §17.4.70）：寬 / gridSpan / vMerge / borders / shd / margins / vAlign / textDirection / noWrap。 */
function writeTcPr(cell: CellNode): string {
  const parts: string[] = [];
  const p = cell.props;

  // w:tcW
  const tcW = writeTcW(p.width);
  if (tcW !== '') parts.push(tcW);

  // w:gridSpan（>1 才掛）
  if (cell.gridSpan > 1) parts.push(`<w:gridSpan w:val="${cell.gridSpan}"/>`);

  // w:vMerge：rowSpan>1 的起始 cell → restart；isContinuation=true → 預設 continue
  if (cell.isContinuation) {
    parts.push('<w:vMerge/>');
  } else if (cell.rowSpan > 1) {
    parts.push('<w:vMerge w:val="restart"/>');
  }

  // w:tcBorders
  if (p.borders) parts.push(writeBorderSet(p.borders, 'w:tcBorders'));

  // w:shd
  if (p.shading) {
    const attrs: string[] = [];
    if (p.shading.pattern !== undefined) attrs.push(`w:val="${escapeXml(p.shading.pattern)}"`);
    if (p.shading.fill !== undefined) attrs.push(`w:fill="${escapeXml(p.shading.fill)}"`);
    if (p.shading.color !== undefined) attrs.push(`w:color="${escapeXml(p.shading.color)}"`);
    if (attrs.length > 0) parts.push(`<w:shd ${attrs.join(' ')}/>`);
  }

  // w:noWrap
  if (p.noWrap === true) parts.push('<w:noWrap/>');

  // w:tcMar
  if (p.margins) {
    const tcMar = writeTcMar(p.margins);
    if (tcMar !== '') parts.push(tcMar);
  }

  // w:textDirection
  if (p.textDirection !== undefined) {
    parts.push(`<w:textDirection w:val="${p.textDirection}"/>`);
  }

  // w:vAlign
  if (p.vAlign !== undefined) parts.push(`<w:vAlign w:val="${p.vAlign}"/>`);

  // w:tcFitText（OOXML §17.4.65）
  if (p.fitText === true) parts.push('<w:tcFitText/>');

  return parts.length > 0 ? `<w:tcPr>${parts.join('')}</w:tcPr>` : '';
}

// ── Sprint 191：numbering.xml 序列化 ─────────────────────────────────────────

/**
 * `word/numbering.xml`：序列化 DocumentNode.numbering。
 *
 * 對稱性設計：parser 把 `<w:num numId>` → `<w:abstractNumId>` → `<w:abstractNum>`
 * 的關係 resolve 後、每個 numId 在 NumberingMap 內存一份完整 levels 副本。
 *
 * Export 策略：**用 numId 直接當 abstractNumId**（保證唯一、避免「多個 numId
 * 共用 abstractNumId 但 levels 不同」場景在 re-parse 時被 Map 覆蓋）。
 * `entry.abstractNumId` 欄位於 round-trip 後變為 numId（acceptable lossy；
 * parser 不靠此值來解析 levels）。
 *
 * 空 NumberingMap → 空 `<w:numbering/>` 骨架（parser 接受、與 Sprint 185 MVS 相容）。
 */
function writeNumbering(doc: DocumentNode): string {
  if (doc.numbering.size === 0) {
    return xmlDecl() + `<w:numbering xmlns:w="${W_NS}"/>`;
  }
  const abstractNums: string[] = [];
  const numEntries: string[] = [];
  for (const [numId, entry] of doc.numbering) {
    // 用 numId 作為 abstractNumId（唯一性保證）
    abstractNums.push(writeAbstractNum(numId, entry));
    numEntries.push(
      `<w:num w:numId="${numId}"><w:abstractNumId w:val="${numId}"/></w:num>`,
    );
  }
  return xmlDecl() +
    `<w:numbering xmlns:w="${W_NS}">` +
    abstractNums.join('') +
    numEntries.join('') +
    '</w:numbering>';
}

/** 單一 `<w:abstractNum>` element + 內含 0..9 個 `<w:lvl>`。 */
function writeAbstractNum(abstractNumId: number, entry: AbstractNumbering): string {
  const lvls = entry.levels.map(writeLvl).join('');
  return `<w:abstractNum w:abstractNumId="${abstractNumId}">${lvls}</w:abstractNum>`;
}

/**
 * 單一 `<w:lvl w:ilvl="N">`：start / numFmt / lvlText / lvlRestart / isLgl /
 * pPr / rPr（OOXML §17.9.6 CT_Lvl）。
 *
 * indent 合併到 pPr：parser 把 `<w:ind w:left w:hanging>` 抽出為獨立 `indent`
 * 欄位（firstLine / right 留在 pProps.indent）；export 時把兩者 merge 回 pPr。
 */
function writeLvl(level: NumberingLevel): string {
  const parts: string[] = [];
  parts.push(`<w:start w:val="${level.start}"/>`);
  parts.push(`<w:numFmt w:val="${escapeXml(level.numFmt)}"/>`);
  parts.push(`<w:lvlText w:val="${escapeXml(level.text)}"/>`);
  if (level.lvlRestart !== undefined) {
    parts.push(`<w:lvlRestart w:val="${level.lvlRestart}"/>`);
  }
  if (level.isLegal === true) parts.push('<w:isLgl/>');

  // 合併 indent + pProps、輸出 pPr
  const mergedPProps: ParagraphProps = { ...(level.pProps ?? {}) };
  if (level.indent) {
    mergedPProps.indent = { ...(mergedPProps.indent ?? {}), ...level.indent };
  }
  const pPrXml = writePPr(mergedPProps, undefined);
  if (pPrXml !== '') parts.push(pPrXml);

  if (level.runProps) {
    const rPrXml = writeRPr(level.runProps);
    if (rPrXml !== '') parts.push(rPrXml);
  }

  return `<w:lvl w:ilvl="${level.ilvl}">${parts.join('')}</w:lvl>`;
}

// ── Sprint 192：圖片 / media 序列化 ──────────────────────────────────────────

/**
 * 單一 media 項目：rId / 副檔名 / mime / 解碼後 bytes / zip 內路徑。
 * 由 `collectMedia` 從 `DocumentNode.media`（rId → base64 data URL）建立。
 */
interface MediaItem {
  rId: string;
  ext: string;        // 'png' / 'jpeg' / 'gif' / ...
  mime: string;       // 'image/png' / 'image/jpeg' / ...
  bytes: Uint8Array;
  target: string;     // 'word/media/imageN.ext'
}

/**
 * 把 `DocumentNode.media`（Map<rId, data URL>）轉為 MediaItem[]。
 *
 * - data URL 格式：`data:<mime>;base64,<base64-bytes>`
 * - 非 image/* 或解析失敗的條目 → 跳過
 * - 檔名用序列流水號 imageN.ext 避免 rId 字串衝突
 */
function collectMedia(media: Map<string, string>): MediaItem[] {
  const items: MediaItem[] = [];
  let counter = 0;
  for (const [rId, dataUrl] of media) {
    const parsed = parseDataUrl(dataUrl);
    if (!parsed) continue; // 非 base64 data URL / 解碼失敗
    if (!parsed.mime.startsWith('image/')) continue; // 非圖片 → 跳過
    counter++;
    const ext = extensionForMime(parsed.mime);
    items.push({
      rId,
      ext,
      mime: parsed.mime,
      bytes: parsed.bytes,
      target: `word/media/image${counter}.${ext}`,
    });
  }
  return items;
}

/**
 * 解析 `data:<mime>;base64,<...>` 為 mime + bytes。
 * 非 base64 或格式錯誤 → undefined。
 */
function parseDataUrl(dataUrl: string): { mime: string; bytes: Uint8Array } | undefined {
  if (!dataUrl.startsWith('data:')) return undefined;
  const commaIdx = dataUrl.indexOf(',');
  if (commaIdx < 0) return undefined;
  const header = dataUrl.slice(5, commaIdx); // skip 'data:'
  const b64Body = dataUrl.slice(commaIdx + 1);
  // header 形如 "image/png;base64" 或 "image/png"（無 base64）
  const semi = header.indexOf(';');
  const mime = semi >= 0 ? header.slice(0, semi) : header;
  const isBase64 = semi >= 0 && header.slice(semi + 1).toLowerCase().includes('base64');
  if (!isBase64) return undefined;
  try {
    return { mime, bytes: base64ToBytes(b64Body) };
  } catch {
    return undefined;
  }
}

/**
 * base64 字串 → Uint8Array。Node 用 Buffer、瀏覽器用 atob 後備。
 */
function base64ToBytes(b64: string): Uint8Array {
  const g = globalThis as {
    Buffer?: { from(s: string, enc: string): { length: number; [k: number]: number } };
    atob?: (s: string) => string;
  };
  if (g.Buffer && typeof g.Buffer.from === 'function') {
    const buf = g.Buffer.from(b64, 'base64');
    return new Uint8Array(buf as unknown as ArrayBuffer);
  }
  if (typeof g.atob === 'function') {
    const bin = g.atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  throw new Error('OoxmlWriter: no base64 decoder available (need Buffer or atob)');
}

/** mime 'image/png' → 副檔名 'png'；'image/x-emf' → 'emf'；'image/svg+xml' → 'svg'。 */
function extensionForMime(mime: string): string {
  const slash = mime.indexOf('/');
  if (slash < 0) return 'bin';
  let ext = mime.slice(slash + 1);
  // 去掉 +xml 等後綴
  const plus = ext.indexOf('+');
  if (plus >= 0) ext = ext.slice(0, plus);
  // 去掉 'x-' 前綴
  if (ext.startsWith('x-')) ext = ext.slice(2);
  return ext.toLowerCase();
}

/** 副檔名 → MIME（Content_Types Default 用）。未知副檔名 fallback 為 `image/${ext}`。 */
function mimeForExtension(ext: string): string {
  switch (ext) {
    case 'png': return 'image/png';
    case 'jpeg':
    case 'jpg': return 'image/jpeg';
    case 'gif': return 'image/gif';
    case 'bmp': return 'image/bmp';
    case 'tiff':
    case 'tif': return 'image/tiff';
    case 'webp': return 'image/webp';
    case 'svg': return 'image/svg+xml';
    case 'emf': return 'image/x-emf';
    case 'wmf': return 'image/x-wmf';
    default: return `image/${ext}`;
  }
}

// ── docPr id 計數器（每次 write 重置） ────────────────────────────────────

let _docPrCounter = 0;
function resetDocPrCounter(): void { _docPrCounter = 0; }
function nextDocPrId(): number { _docPrCounter += 1; return _docPrCounter; }

/**
 * Sprint 192：把 InlineImageNode / FloatImageNode 序列化為 `<w:r><w:drawing><wp:inline>`。
 *
 * FloatImageNode 降級為 inline 輸出（與 ToCanvasEditor 一致：production pipeline
 * 已把浮動圖片視為 inline）。posH / posV / wrap / srcRect 等屬性 lossy 留後續。
 *
 * 結構：`<w:r><w:drawing><wp:inline>` 含 wp:extent（EMU 換算）+ wp:docPr + a:graphic
 * → a:graphicData uri=picture → pic:pic（nvPicPr + blipFill + spPr）。
 */
function writeInlineImageRun(img: InlineImageNode | FloatImageNode): string {
  const cx = ptToEmu(img.width);
  const cy = ptToEmu(img.height);
  const docPrId = nextDocPrId();
  const descrAttr = img.altText ? ` descr="${escapeXml(img.altText)}"` : '';

  // Sprint 195：依 img.graphic.kind 選 graphicData 內容（SmartArt / Chart / 一般圖片）
  const graphicData = img.type === 'inlineImage' && img.graphic
    ? writeGraphicDataForGraphicFrame(img.graphic, cx, cy, docPrId)
    : writeGraphicDataForPicture(img.rId, cx, cy, docPrId);

  // Sprint 286：effectExtent 若 AST 有 → emit；無 → 略（與既有行為一致）
  const effectExtentXml = img.effectExtent
    ? `<wp:effectExtent l="${ptToEmu(img.effectExtent.left)}" t="${ptToEmu(img.effectExtent.top)}" r="${ptToEmu(img.effectExtent.right)}" b="${ptToEmu(img.effectExtent.bottom)}"/>`
    : '';

  return '<w:r><w:drawing>' +
    `<wp:inline xmlns:wp="${WP_NS}" distT="0" distB="0" distL="0" distR="0">` +
    `<wp:extent cx="${cx}" cy="${cy}"/>` +
    effectExtentXml +
    `<wp:docPr id="${docPrId}" name="Image${docPrId}"${descrAttr}/>` +
    '<wp:cNvGraphicFramePr/>' +
    `<a:graphic xmlns:a="${A_NS}">` +
    graphicData +
    '</a:graphic>' +
    '</wp:inline>' +
    '</w:drawing></w:r>';
}

/** 一般圖片 graphicData：`<pic:pic>` 包 blipFill + spPr。 */
function writeGraphicDataForPicture(rId: string, cx: number, cy: number, docPrId: number): string {
  return `<a:graphicData uri="${A_GRAPHIC_PICTURE_URI}">` +
    `<pic:pic xmlns:pic="${PIC_NS}">` +
    `<pic:nvPicPr><pic:cNvPr id="${docPrId}" name="Image${docPrId}"/><pic:cNvPicPr/></pic:nvPicPr>` +
    '<pic:blipFill>' +
    `<a:blip xmlns:r="${R_NS}" r:embed="${escapeXml(rId)}"/>` +
    '<a:stretch><a:fillRect/></a:stretch>' +
    '</pic:blipFill>' +
    '<pic:spPr>' +
    `<a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm>` +
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>' +
    '</pic:spPr>' +
    '</pic:pic>' +
    '</a:graphicData>';
}

/**
 * Sprint 195：SmartArt / Chart graphicData。
 *
 * - diagram → `<a:graphicData uri=".../diagram"><dgm:relIds r:dm="rId..."/>`
 *   `r:dm` 是必需的 data relationship；r:lo/r:qs/r:cs 在 capture 已資料丟失、
 *   export 重指向 r:dm 同 rId（lossy 但 parser 仍能解析）
 * - chart → `<a:graphicData uri=".../chart"><c:chart r:id="rId..."/>`
 */
function writeGraphicDataForGraphicFrame(
  graphic: { kind: 'diagram' | 'chart'; relId: string },
  _cx: number,
  _cy: number,
  _docPrId: number,
): string {
  const uri = graphic.kind === 'diagram' ? A_GRAPHIC_DIAGRAM_URI : A_GRAPHIC_CHART_URI;
  if (graphic.kind === 'diagram') {
    // dgm:relIds 需要 dm/lo/qs/cs 四個 rId；本實作用同 relId 作所有四個
    // （只有 dm 是 parser 必讀；其他三個指向不存在的 rId 也不影響解析）
    return `<a:graphicData uri="${uri}">` +
      `<dgm:relIds xmlns:dgm="${DGM_NS}" xmlns:r="${R_NS}" ` +
      `r:dm="${escapeXml(graphic.relId)}" r:lo="${escapeXml(graphic.relId)}" ` +
      `r:qs="${escapeXml(graphic.relId)}" r:cs="${escapeXml(graphic.relId)}"/>` +
      '</a:graphicData>';
  }
  return `<a:graphicData uri="${uri}">` +
    `<c:chart xmlns:c="${C_NS}" xmlns:r="${R_NS}" r:id="${escapeXml(graphic.relId)}"/>` +
    '</a:graphicData>';
}

/** pt → EMU（四捨五入為整數、OOXML drawing 屬性要求整數）。 */
function ptToEmu(pt: number): number {
  return Math.round(pt * EMU_PER_PT);
}

// ── Sprint 193：頁首 / 頁尾序列化 ────────────────────────────────────────────

/**
 * 單一 header / footer 部件資訊（由 collectHeadersFooters 從 doc.headers/footers 建立）。
 *
 * rId 從 Map 原樣帶入；filename 為新生成的 word/headerN.xml / word/footerN.xml
 * 路徑（與原 docx 的 target 無關、export 端自由命名）。
 */
interface HeaderFooterItem {
  kind: 'header' | 'footer';
  rId: string;
  filename: string;
  content: BlockNode[];
}

/**
 * 把 doc.headers 與 doc.footers 整理為 HeaderFooterItem[]、賦予新檔名。
 *
 * 檔名用序號流水（header1.xml / header2.xml；footer1.xml / footer2.xml…）
 * 與 image collectMedia 同模式。
 */
function collectHeadersFooters(doc: DocumentNode): HeaderFooterItem[] {
  const out: HeaderFooterItem[] = [];
  let hN = 0, fN = 0;
  for (const [rId, hf] of doc.headers) {
    hN += 1;
    out.push({ kind: 'header', rId, filename: `word/header${hN}.xml`, content: hf.content });
  }
  for (const [rId, hf] of doc.footers) {
    fN += 1;
    out.push({ kind: 'footer', rId, filename: `word/footer${fN}.xml`, content: hf.content });
  }
  return out;
}

/**
 * 寫單一 header / footer 部件的 XML 字串。
 *
 * 結構：`<w:hdr>` 或 `<w:ftr>` 包住 BlockNode[]（reuse writeBlock dispatcher
 * → 段落 / 表格 / 巢狀皆自然支援）。`xmlns:r` 一併宣告以備內含 hyperlink /
 * image / 其他 r:id 引用。
 */
function writeHeaderFooterPart(hf: HeaderFooterItem): string {
  const rootTag = hf.kind === 'header' ? 'w:hdr' : 'w:ftr';
  const blocks = hf.content.map(writeBlock).join('');
  return xmlDecl() +
    `<${rootTag} xmlns:w="${W_NS}" xmlns:r="${R_NS}">` +
    blocks +
    `</${rootTag}>`;
}

// ── Sprint 196：watermark export（合成 header VML） ──────────────────────────

/**
 * Sprint 196：合成 watermark header 部件資訊。
 *
 * Word「設計 → 浮水印」實作為 header part 內 `<w:pict>` 包 VML
 * `<v:shape type="#_x0000_t136">` WordArt（文字浮水印）或 `<v:imagedata>`
 * （圖片浮水印）。export 端用 dedicated synthetic header part 攜帶浮水印，
 * 對「無既有 default header」的 section 注入該 rId 為 default。
 *
 * 紀律 #21：doc.watermark 為 undefined → 不產出 watermark header（此 type
 * 不存在於 hfItems）。
 */
interface WatermarkHeaderItem {
  /** 合成 rId（不與既有 doc.headers/footers rId 衝突）。 */
  rId: string;
  /** 合成檔名（word/watermarkHeader.xml）。 */
  filename: string;
  /** 浮水印 capture 來源（kind / text / font / rotation / imageRId）。 */
  watermark: NonNullable<DocumentNode['watermark']>;
}

/**
 * 從 doc.watermark 整理出 watermark header 部件；無浮水印 → undefined。
 *
 * 紀律 #21：watermark 為 undefined → 不輸出部件、Content_Types / rels / section
 * headerRefs 都不掛此 rId（無 watermark 文件零開銷）。
 */
function collectWatermark(doc: DocumentNode): WatermarkHeaderItem | undefined {
  if (!doc.watermark) return undefined;
  return {
    rId: WATERMARK_HEADER_RID,
    filename: WATERMARK_HEADER_FILENAME,
    watermark: doc.watermark,
  };
}

/**
 * 把 WatermarkHeaderItem 序列化為 header part XML 字串。
 *
 * 結構：`<w:hdr><w:p><w:r><w:pict><v:shape ...>` 包 textpath / imagedata。
 *   - 文字浮水印：`<v:shape type="#_x0000_t136" style="...rotation:N">` +
 *                 `<v:fill color=...>` + `<v:textpath string="..." style="font-family:...">`
 *   - 圖片浮水印：`<v:shape id="WordPictureWatermark..." style="...">` +
 *                 `<v:imagedata r:id="..."/>`（rId 來自 doc.media 對應的圖片）
 *
 * 紀律 #18 scope-down：fill / stroke 等視覺屬性走 Word 預設值；style 只攜帶
 * width / height / rotation（其餘 absolute / margin-* 等留後續）。
 */
function writeWatermarkHeaderPart(item: WatermarkHeaderItem): string {
  const wm = item.watermark;
  const rotation = wm.rotation ?? WATERMARK_DEFAULT_ROTATION;
  // VML shape style：用 Word 浮水印慣例（width/height 採點數、rotation 度數）
  const shapeStyle = `position:absolute;margin-left:0;margin-top:0;width:468pt;height:117pt;rotation:${rotation};z-index:-251658752`;

  let shapeInner: string;
  if (wm.kind === 'text') {
    const text = wm.text ?? '';
    const font = wm.font ?? '標楷體';
    const textpathStyle = `font-family:&quot;${escapeXml(font)}&quot;;font-size:1pt`;
    shapeInner =
      `<v:fill color="${WATERMARK_DEFAULT_FILLCOLOR}"/>` +
      `<v:textpath xmlns:v="${V_NS}" style="${textpathStyle}" string="${escapeXml(text)}"/>`;
  } else {
    // image watermark — 引用 doc.media 對應的圖片 rId
    const imageRId = wm.imageRId ?? '';
    shapeInner = `<v:imagedata r:id="${escapeXml(imageRId)}" o:title="WordPictureWatermark"/>`;
  }

  // VML shape id 含 "watermark" 字串（parser kind='image' 判定條件）；
  // type='#_x0000_t136' 為文字 WordArt（parser kind='text' 判定條件 = 有 textpath）
  const shapeAttrs = wm.kind === 'text'
    ? `id="PowerPlusWaterMarkObject" type="${WATERMARK_SHAPE_TYPE}" style="${shapeStyle}"`
    : `id="WordPictureWatermark" style="${shapeStyle}"`;

  return xmlDecl() +
    `<w:hdr xmlns:w="${W_NS}" xmlns:r="${R_NS}" xmlns:v="${V_NS}" xmlns:o="${O_NS}">` +
    '<w:p>' +
    '<w:r>' +
    '<w:pict>' +
    `<v:shape ${shapeAttrs}>` +
    shapeInner +
    '</v:shape>' +
    '</w:pict>' +
    '</w:r>' +
    '</w:p>' +
    '</w:hdr>';
}

// ── Sprint 194：OMML 數學公式序列化 ──────────────────────────────────────────

/**
 * 把 `ParagraphNode.math?: MathNode[]` 序列化為 0..N 個 `<m:oMath>` /
 * `<m:oMathPara>` 元素。
 *
 * - display = true → `<m:oMathPara><m:oMath>...</m:oMath></m:oMathPara>`（獨立置中公式）
 * - display = false → 段落直屬 `<m:oMath>`（行內公式）
 *
 * 每個 `<m:oMath>` / `<m:oMathPara>` 自帶 `xmlns:m`（為簡化、不在 root 統一宣告）。
 * 紀律 #21：math 為 undefined / 空陣列 → 回空字串。
 */
function writeParagraphMath(math: MathNode[] | undefined): string {
  if (!math || math.length === 0) return '';
  return math.map((m) => {
    const oMath = `<m:oMath xmlns:m="${M_NS}">${writeOmmlChildren(m.omml)}</m:oMath>`;
    return m.display ? `<m:oMathPara xmlns:m="${M_NS}">${oMath}</m:oMathPara>` : oMath;
  }).join('');
}

/** 序列化 OmmlNode 陣列（遞迴）。 */
function writeOmmlChildren(nodes: OmmlNode[]): string {
  return nodes.map(writeOmmlNode).join('');
}

/**
 * 序列化單一 OmmlNode 為 `<m:tag>` 元素。
 *
 * - tag 自動加 `m:` 前綴（parser 解析時去除、export 時還原）
 * - attrs 同 `m:` 前綴
 * - text 葉節點（`<m:t>`）→ `<m:t>text</m:t>`
 * - 含 children → 遞迴
 * - 無 text 也無 children → self-closing
 */
function writeOmmlNode(node: OmmlNode): string {
  // Sprint 199 修法：parser stripMathPrefix 只去 `m:` 前綴、其他 namespace 子元素
  // （如 OMML 內嵌的 `<w:rPr>`、`<w:rFonts>`）原樣保留 `w:` 前綴。writer 若一律
  // 前綴 `m:` 會產生 `m:w:rPr` invalid XML（nested colon）→ re-parse 全失敗。
  // 規則：tag / 屬性 key 已含 `:` 表已帶 namespace、不再前綴。
  const tag = node.tag.includes(':') ? node.tag : `m:${node.tag}`;
  const attrs = node.attrs
    ? Object.entries(node.attrs)
        .map(([k, v]) => {
          const fullName = k.includes(':') ? k : `m:${k}`;
          return ` ${escapeXml(fullName)}="${escapeXml(v)}"`;
        })
        .join('')
    : '';
  if (node.text !== undefined) {
    return `<${tag}${attrs}>${escapeXml(node.text)}</${tag}>`;
  }
  if (node.children && node.children.length > 0) {
    return `<${tag}${attrs}>${writeOmmlChildren(node.children)}</${tag}>`;
  }
  return `<${tag}${attrs}/>`;
}

// ── Sprint 194：comments.xml 序列化 ──────────────────────────────────────────

/**
 * `word/comments.xml`：序列化 `DocumentNode.comments`。
 *
 * 結構（OOXML §17.13.4）：
 *   <w:comments>
 *     <w:comment w:id="0" w:author="..." w:date="..." w:initials="...">
 *       <w:p>...</w:p>+ | <w:tbl>...</w:tbl>+
 *     </w:comment>
 *     ...
 *   </w:comments>
 *
 * content 透過 writeBlock dispatcher（reuse 段落 / 表格 / 巢狀邏輯）。
 * 空 Map → 空 `<w:comments/>` 骨架。
 */
function writeComments(doc: DocumentNode): string {
  if (doc.comments.size === 0) {
    return xmlDecl() + `<w:comments xmlns:w="${W_NS}"/>`;
  }
  const comments: string[] = [];
  for (const [, c] of doc.comments) {
    comments.push(writeCommentEntry(c));
  }
  return xmlDecl() +
    `<w:comments xmlns:w="${W_NS}">` +
    comments.join('') +
    '</w:comments>';
}

/** 序列化單一 `<w:comment>`。 */
function writeCommentEntry(c: CommentContent): string {
  const attrs: string[] = [`w:id="${c.id}"`];
  if (c.author !== undefined) attrs.push(`w:author="${escapeXml(c.author)}"`);
  if (c.date !== undefined) attrs.push(`w:date="${escapeXml(c.date)}"`);
  if (c.initials !== undefined) attrs.push(`w:initials="${escapeXml(c.initials)}"`);
  const body = c.content.map(writeBlock).join('') || '<w:p/>';
  return `<w:comment ${attrs.join(' ')}>${body}</w:comment>`;
}

// ── Sprint 239：footnotes.xml / endnotes.xml 序列化 ──────────────────────────

/**
 * `word/footnotes.xml`：序列化 `DocumentNode.footnotes`。
 *
 * 結構（OOXML §17.11.16 footnotes）：
 *   <w:footnotes>
 *     <w:footnote w:id w:type?>
 *       <w:p>...</w:p>+ | <w:tbl>...</w:tbl>+
 *     </w:footnote>
 *     ...
 *   </w:footnotes>
 *
 * - `w:type` 為 'separator' / 'continuationSeparator' / 'continuationNotice'
 *   裝飾用 footnote（id=-1 / 0 通常）；對純內容 footnote 省略
 * - content 透過 writeBlock dispatcher 重用段落 / 表格 / 巢狀邏輯
 * - caller 已確保 doc.footnotes.size > 0（空 Map 不 emit 整個 part）
 */
function writeFootnotes(doc: DocumentNode): string {
  const items: string[] = [];
  const ids = Array.from(doc.footnotes.keys()).sort((a, b) => a - b);
  for (const id of ids) {
    items.push(writeFootnoteEntry(doc.footnotes.get(id)!, 'footnote'));
  }
  return xmlDecl() +
    `<w:footnotes xmlns:w="${W_NS}">` +
    items.join('') +
    '</w:footnotes>';
}

/**
 * `word/endnotes.xml`：序列化 `DocumentNode.endnotes`。結構同 footnotes、tag 名換成 endnote。
 */
function writeEndnotes(doc: DocumentNode): string {
  const items: string[] = [];
  const ids = Array.from(doc.endnotes.keys()).sort((a, b) => a - b);
  for (const id of ids) {
    items.push(writeFootnoteEntry(doc.endnotes.get(id)!, 'endnote'));
  }
  return xmlDecl() +
    `<w:endnotes xmlns:w="${W_NS}">` +
    items.join('') +
    '</w:endnotes>';
}

/** 序列化單一 `<w:footnote>` 或 `<w:endnote>`。 */
function writeFootnoteEntry(f: FootnoteContent, tag: 'footnote' | 'endnote'): string {
  const attrs: string[] = [`w:id="${f.id}"`];
  if (f.type !== undefined) attrs.push(`w:type="${f.type}"`);
  const body = f.content.map(writeBlock).join('') || '<w:p/>';
  return `<w:${tag} ${attrs.join(' ')}>${body}</w:${tag}>`;
}

// ── Sprint 243：settings.xml 序列化 ──────────────────────────────────────────

/**
 * 判定 DocumentSettings 是否含可序列化欄位。空 settings（如 Phase 5 fixture
 * 無 settings.xml）→ parser 回 {}、writer 跳過 emit、避免 minimal docx 加冗餘 part。
 */
function hasSettings(s: DocumentSettings): boolean {
  return Object.keys(s).length > 0;
}

/**
 * `word/settings.xml`：序列化 `DocumentNode.settings`（OOXML §17.15）。
 *
 * Sprint 146 parser capture：zoom / defaultTabStop / characterSpacingControl /
 * autoHyphenation / evenAndOddHeaders / trackChanges / proofState /
 * footnotePr / endnotePr / compat 共 10 欄位。本 sprint 對稱序列化。
 *
 * 設計：caller 已用 hasSettings 過濾、本函式假設至少有一個欄位需 emit。
 */
function writeSettings(s: DocumentSettings): string {
  const parts: string[] = [];
  if (s.zoomPercent !== undefined) {
    parts.push(`<w:zoom w:percent="${s.zoomPercent}"/>`);
  }
  if (s.defaultTabStop !== undefined) {
    // pt → twip：1pt = 20twip（OOXML §17.18）
    parts.push(`<w:defaultTabStop w:val="${Math.round(s.defaultTabStop * 20)}"/>`);
  }
  if (s.characterSpacingControl !== undefined) {
    parts.push(`<w:characterSpacingControl w:val="${s.characterSpacingControl}"/>`);
  }
  if (s.autoHyphenation === true) {
    parts.push('<w:autoHyphenation/>');
  } else if (s.autoHyphenation === false) {
    parts.push('<w:autoHyphenation w:val="0"/>');
  }
  if (s.evenAndOddHeaders === true) {
    parts.push('<w:evenAndOddHeaders/>');
  } else if (s.evenAndOddHeaders === false) {
    parts.push('<w:evenAndOddHeaders w:val="0"/>');
  }
  if (s.trackChanges === true) {
    parts.push('<w:trackChanges/>');
  } else if (s.trackChanges === false) {
    parts.push('<w:trackChanges w:val="0"/>');
  }
  if (s.proofState) {
    const attrs: string[] = [];
    if (s.proofState.spelling) attrs.push(`w:spelling="${s.proofState.spelling}"`);
    if (s.proofState.grammar) attrs.push(`w:grammar="${s.proofState.grammar}"`);
    if (attrs.length > 0) parts.push(`<w:proofState ${attrs.join(' ')}/>`);
  }
  if (s.footnotePr) parts.push(writeNotePr(s.footnotePr, 'footnotePr'));
  if (s.endnotePr) parts.push(writeNotePr(s.endnotePr, 'endnotePr'));
  if (s.compat && s.compat.length > 0) {
    const compatChildren = s.compat.map((name) => `<w:${name}/>`).join('');
    parts.push(`<w:compat>${compatChildren}</w:compat>`);
  }
  return xmlDecl() +
    `<w:settings xmlns:w="${W_NS}">` +
    parts.join('') +
    '</w:settings>';
}

/** 序列化 `<w:footnotePr>` 或 `<w:endnotePr>` 子元素。 */
function writeNotePr(np: NonNullable<DocumentSettings['footnotePr']>, tag: 'footnotePr' | 'endnotePr'): string {
  const subs: string[] = [];
  if (np.numFmt !== undefined) subs.push(`<w:numFmt w:val="${np.numFmt}"/>`);
  if (np.numStart !== undefined) subs.push(`<w:numStart w:val="${np.numStart}"/>`);
  if (np.numRestart !== undefined) subs.push(`<w:numRestart w:val="${np.numRestart}"/>`);
  if (np.position !== undefined) subs.push(`<w:pos w:val="${np.position}"/>`);
  return `<w:${tag}>${subs.join('')}</w:${tag}>`;
}

// ── Sprint 246：fontTable.xml 序列化 ─────────────────────────────────────────

/**
 * `word/fontTable.xml`：序列化 `DocumentNode.fontTable`（OOXML §17.8.3）。
 *
 * Sprint 147 parser capture：name / altName / charset / family / pitch /
 * panose1 / sig（usb0-3, csb0-1）。本 sprint 對稱序列化。
 *
 * 順序：以 name 字典序輸出（與 audit 排序一致；OOXML 不規定 font 順序、
 * round-trip 不靠原始順序）。caller 已用 doc.fontTable.size > 0 過濾。
 */
function writeFontTable(ft: Map<string, FontEntry>): string {
  const names = Array.from(ft.keys()).sort();
  const fonts: string[] = [];
  for (const n of names) {
    fonts.push(writeFontEntry(ft.get(n)!));
  }
  return xmlDecl() +
    `<w:fonts xmlns:w="${W_NS}">` +
    fonts.join('') +
    '</w:fonts>';
}

/** 序列化單一 `<w:font w:name="...">`。 */
function writeFontEntry(f: FontEntry): string {
  const subs: string[] = [];
  if (f.altName !== undefined) subs.push(`<w:altName w:val="${escapeXml(f.altName)}"/>`);
  if (f.charset !== undefined) subs.push(`<w:charset w:val="${escapeXml(f.charset)}"/>`);
  if (f.family !== undefined) subs.push(`<w:family w:val="${f.family}"/>`);
  if (f.pitch !== undefined) subs.push(`<w:pitch w:val="${f.pitch}"/>`);
  if (f.panose1 !== undefined) subs.push(`<w:panose1 w:val="${escapeXml(f.panose1)}"/>`);
  if (f.sig) {
    const attrs: string[] = [];
    if (f.sig.usb0 !== undefined) attrs.push(`w:usb0="${escapeXml(f.sig.usb0)}"`);
    if (f.sig.usb1 !== undefined) attrs.push(`w:usb1="${escapeXml(f.sig.usb1)}"`);
    if (f.sig.usb2 !== undefined) attrs.push(`w:usb2="${escapeXml(f.sig.usb2)}"`);
    if (f.sig.usb3 !== undefined) attrs.push(`w:usb3="${escapeXml(f.sig.usb3)}"`);
    if (f.sig.csb0 !== undefined) attrs.push(`w:csb0="${escapeXml(f.sig.csb0)}"`);
    if (f.sig.csb1 !== undefined) attrs.push(`w:csb1="${escapeXml(f.sig.csb1)}"`);
    if (attrs.length > 0) subs.push(`<w:sig ${attrs.join(' ')}/>`);
  }
  return `<w:font w:name="${escapeXml(f.name)}">${subs.join('')}</w:font>`;
}

// ── Sprint 249：webSettings.xml 序列化 ────────────────────────────────────────

/** 判定 DocumentWebSettings 是否含可序列化欄位。 */
function hasWebSettings(w: DocumentWebSettings): boolean {
  return Object.keys(w).length > 0;
}

/**
 * `word/webSettings.xml`：序列化 `DocumentNode.webSettings`（OOXML §17.16）。
 *
 * Sprint 148 parser capture：optimizeForBrowser / allowPNG / saveSmartTagsAsXml
 * / doNotSaveAsSingleFile / hasDivs 共 5 個 toggle 欄位。本 sprint 對稱序列化。
 *
 * hasDivs 為「結構提示存在」flag（parser scope-down 未深入 divs 子元素內容）；
 * 序列化為 `<w:divs/>` 空骨架、re-parse 仍可標 hasDivs=true。
 */
function writeWebSettings(w: DocumentWebSettings): string {
  const parts: string[] = [];
  if (w.optimizeForBrowser === true) parts.push('<w:optimizeForBrowser/>');
  else if (w.optimizeForBrowser === false) parts.push('<w:optimizeForBrowser w:val="0"/>');
  if (w.allowPNG === true) parts.push('<w:allowPNG/>');
  else if (w.allowPNG === false) parts.push('<w:allowPNG w:val="0"/>');
  if (w.saveSmartTagsAsXml === true) parts.push('<w:saveSmartTagsAsXml/>');
  else if (w.saveSmartTagsAsXml === false) parts.push('<w:saveSmartTagsAsXml w:val="0"/>');
  if (w.doNotSaveAsSingleFile === true) parts.push('<w:doNotSaveAsSingleFile/>');
  else if (w.doNotSaveAsSingleFile === false) parts.push('<w:doNotSaveAsSingleFile w:val="0"/>');
  // Sprint 249 root cause #10：parser 對空 `<w:divs/>` 視為無 divs（Sprint 148
  // scope-down 設計），writer 必須 emit 至少一個 `<w:div>` 子元素才能讓 re-parse
  // 識別為 hasDivs=true。emit minimal stub child（不深入結構、紀律 #18）。
  if (w.hasDivs === true) parts.push('<w:divs><w:div w:id="0"/></w:divs>');
  return xmlDecl() +
    `<w:webSettings xmlns:w="${W_NS}">` +
    parts.join('') +
    '</w:webSettings>';
}

// ── Sprint 253：docProps/core.xml / app.xml / custom.xml 序列化 ───────────────

/** 判定 DocProps（core）是否含可序列化欄位。 */
function hasDocProps(p: DocProps): boolean {
  return Object.keys(p).length > 0;
}

/** 判定 DocPropsApp 是否含可序列化欄位。 */
function hasAppProps(p: DocPropsApp): boolean {
  return Object.keys(p).length > 0;
}

/**
 * `docProps/core.xml`：序列化 `DocumentNode.docProps`（OOXML §22.2.4 cp:coreProperties）。
 *
 * 結構（Dublin Core + DC Terms namespaces）：
 *   <cp:coreProperties xmlns:cp xmlns:dc xmlns:dcterms xmlns:dcmitype xmlns:xsi>
 *     <dc:title>...</dc:title>
 *     <dc:creator>...</dc:creator>
 *     <dc:subject>...</dc:subject>
 *     <dc:description>...</dc:description>
 *     <cp:keywords>...</cp:keywords>
 *     <cp:lastModifiedBy>...</cp:lastModifiedBy>
 *     <dcterms:created xsi:type="dcterms:W3CDTF">ISO</dcterms:created>
 *     <dcterms:modified xsi:type="dcterms:W3CDTF">ISO</dcterms:modified>
 *   </cp:coreProperties>
 */
function writeDocPropsCore(p: DocProps): string {
  const elems: string[] = [];
  if (p.title !== undefined) elems.push(`<dc:title>${escapeXml(p.title)}</dc:title>`);
  if (p.creator !== undefined) elems.push(`<dc:creator>${escapeXml(p.creator)}</dc:creator>`);
  if (p.subject !== undefined) elems.push(`<dc:subject>${escapeXml(p.subject)}</dc:subject>`);
  if (p.description !== undefined) elems.push(`<dc:description>${escapeXml(p.description)}</dc:description>`);
  if (p.keywords !== undefined) elems.push(`<cp:keywords>${escapeXml(p.keywords)}</cp:keywords>`);
  if (p.lastModifiedBy !== undefined) elems.push(`<cp:lastModifiedBy>${escapeXml(p.lastModifiedBy)}</cp:lastModifiedBy>`);
  if (p.created !== undefined) elems.push(`<dcterms:created xsi:type="dcterms:W3CDTF">${escapeXml(p.created)}</dcterms:created>`);
  if (p.modified !== undefined) elems.push(`<dcterms:modified xsi:type="dcterms:W3CDTF">${escapeXml(p.modified)}</dcterms:modified>`);
  return xmlDecl() +
    `<cp:coreProperties xmlns:cp="${CP_NS}" xmlns:dc="${DC_NS}" ` +
    `xmlns:dcterms="${DCTERMS_NS}" xmlns:dcmitype="${DCMITYPE_NS}" xmlns:xsi="${XSI_NS}">` +
    elems.join('') +
    '</cp:coreProperties>';
}

/**
 * `docProps/app.xml`：序列化 `DocumentNode.appProps`（OOXML §22.2）。
 *
 * extended-properties namespace；欄位皆 optional。
 */
function writeDocPropsApp(p: DocPropsApp): string {
  const elems: string[] = [];
  if (p.template !== undefined) elems.push(`<Template>${escapeXml(p.template)}</Template>`);
  if (p.totalTime !== undefined) elems.push(`<TotalTime>${p.totalTime}</TotalTime>`);
  if (p.pages !== undefined) elems.push(`<Pages>${p.pages}</Pages>`);
  if (p.words !== undefined) elems.push(`<Words>${p.words}</Words>`);
  if (p.characters !== undefined) elems.push(`<Characters>${p.characters}</Characters>`);
  if (p.application !== undefined) elems.push(`<Application>${escapeXml(p.application)}</Application>`);
  if (p.docSecurity !== undefined) elems.push(`<DocSecurity>${p.docSecurity}</DocSecurity>`);
  if (p.lines !== undefined) elems.push(`<Lines>${p.lines}</Lines>`);
  if (p.paragraphs !== undefined) elems.push(`<Paragraphs>${p.paragraphs}</Paragraphs>`);
  if (p.scaleCrop !== undefined) elems.push(`<ScaleCrop>${p.scaleCrop ? 'true' : 'false'}</ScaleCrop>`);
  if (p.company !== undefined) elems.push(`<Company>${escapeXml(p.company)}</Company>`);
  if (p.linksUpToDate !== undefined) elems.push(`<LinksUpToDate>${p.linksUpToDate ? 'true' : 'false'}</LinksUpToDate>`);
  if (p.charactersWithSpaces !== undefined) elems.push(`<CharactersWithSpaces>${p.charactersWithSpaces}</CharactersWithSpaces>`);
  if (p.sharedDoc !== undefined) elems.push(`<SharedDoc>${p.sharedDoc ? 'true' : 'false'}</SharedDoc>`);
  if (p.hyperlinksChanged !== undefined) elems.push(`<HyperlinksChanged>${p.hyperlinksChanged ? 'true' : 'false'}</HyperlinksChanged>`);
  if (p.appVersion !== undefined) elems.push(`<AppVersion>${escapeXml(p.appVersion)}</AppVersion>`);
  return xmlDecl() +
    `<Properties xmlns="${EXT_PROPS_NS}" xmlns:vt="${VT_NS}">` +
    elems.join('') +
    '</Properties>';
}

/**
 * `docProps/custom.xml`：序列化 `DocumentNode.customProps`（OOXML §22.4）。
 *
 * 結構：`<Properties><property fmtid pid name><vt:lpwstr>...</vt:lpwstr></property>...`。
 * fmtid 固定 = 標準 GUID；pid 從 2 起遞增（OOXML §22.4.2.5）。
 *
 * Sprint 151 parser 不保留 fmtid / pid（紀律 #18 scope-down）；writer 用標準
 * GUID 重建 fmtid、pid 從 2 起按 name 字典序遞增。
 */
function writeDocPropsCustom(c: DocPropsCustom): string {
  // OOXML §22.4 規範的 fmtid（D5CDD505-2E9C-101B-9397-08002B2CF9AE）
  const FMTID = '{D5CDD505-2E9C-101B-9397-08002B2CF9AE}';
  const names = Array.from(c.keys()).sort();
  const elems: string[] = [];
  let pid = 2;
  for (const name of names) {
    const v = c.get(name)!;
    elems.push(
      `<property fmtid="${FMTID}" pid="${pid}" name="${escapeXml(name)}">` +
      writeCustomVariant(v) +
      '</property>'
    );
    pid++;
  }
  return xmlDecl() +
    `<Properties xmlns="${CUSTOM_PROPS_NS}" xmlns:vt="${VT_NS}">` +
    elems.join('') +
    '</Properties>';
}

/** 序列化單一 custom property 的 vt:variant 值。 */
function writeCustomVariant(v: CustomPropertyValue): string {
  switch (v.kind) {
    case 'string':
      return `<vt:lpwstr>${escapeXml(v.value)}</vt:lpwstr>`;
    case 'int':
      return `<vt:i4>${v.value}</vt:i4>`;
    case 'bool':
      return `<vt:bool>${v.value ? 'true' : 'false'}</vt:bool>`;
    case 'real':
      return `<vt:r8>${v.value}</vt:r8>`;
    case 'filetime':
      return `<vt:filetime>${escapeXml(v.value)}</vt:filetime>`;
    case 'unknown':
    default:
      return `<vt:lpwstr>${escapeXml((v as { raw?: string }).raw ?? '')}</vt:lpwstr>`;
  }
}

// ── Sprint 262：theme1.xml 序列化 ──────────────────────────────────────────

/**
 * `word/theme/theme1.xml`：序列化 `DocumentNode.theme`（OOXML §20.1.6）。
 *
 * 結構（DrawingML、a namespace）：
 *   <a:theme xmlns:a name="...">
 *     <a:themeElements>
 *       <a:clrScheme name="...">
 *         <a:dk1><a:srgbClr val="HEX"/></a:dk1>  (× 12 色)
 *         ...
 *       </a:clrScheme>
 *       <a:fontScheme name="...">
 *         <a:majorFont><a:latin typeface="..."/>(<a:ea/><a:cs/>)</a:majorFont>
 *         <a:minorFont>...</a:minorFont>
 *       </a:fontScheme>
 *     </a:themeElements>
 *   </a:theme>
 *
 * 紀律 #18 scope-down：本 writer 僅 emit colorScheme + fontScheme，與 parser
 *   capture 範圍對稱；fmtScheme / objectDefaults / extraClrSchemeLst 不寫
 *   （parser 不消費、re-parse 後仍無、byte-identical）。
 */
function writeTheme(t: import('../styles/ThemeResolver').ThemeMap): string {
  // Sprint 274：clrScheme / fontScheme 優先用 raw XML（preserve sysClr vs srgbClr +
  //   attr order + parser 未消費的 child elements）；fallback 走 Sprint 262
  //   reconstructed 路徑（無 raw XML 時、例如缺檔降級 DEFAULT_THEME_MAP）
  const clrSchemeXml = t.extras?.clrSchemeRawXml ?? buildClrSchemeXml(t);
  const fontSchemeXml = t.extras?.fontSchemeRawXml ?? buildFontSchemeXml(t);
  // Sprint 271：raw extras 原樣插入（fmtScheme / objectDefaults / extraClrSchemeLst）
  const fmtScheme = t.extras?.fmtSchemeXml ?? '';
  const objectDefaults = t.extras?.objectDefaultsXml ?? '';
  const extraClrSchemeLst = t.extras?.extraClrSchemeLstXml ?? '';
  const themeNameAttr = t.extras?.themeName !== undefined ? ` name="${escapeXml(t.extras.themeName)}"` : '';
  return xmlDecl() +
    `<a:theme xmlns:a="${A_NS}"${themeNameAttr}>` +
    '<a:themeElements>' +
    clrSchemeXml +
    fontSchemeXml +
    fmtScheme +
    '</a:themeElements>' +
    objectDefaults +
    extraClrSchemeLst +
    '</a:theme>';
}

/** Sprint 262 + 274：reconstructed clrScheme（無 rawXml fallback 路徑、寫 12 色 srgbClr）。 */
function buildClrSchemeXml(t: import('../styles/ThemeResolver').ThemeMap): string {
  const c = t.colorScheme;
  const colorElems = [
    `<a:dk1><a:srgbClr val="${escapeXml(c.dk1)}"/></a:dk1>`,
    `<a:lt1><a:srgbClr val="${escapeXml(c.lt1)}"/></a:lt1>`,
    `<a:dk2><a:srgbClr val="${escapeXml(c.dk2)}"/></a:dk2>`,
    `<a:lt2><a:srgbClr val="${escapeXml(c.lt2)}"/></a:lt2>`,
    `<a:accent1><a:srgbClr val="${escapeXml(c.accent1)}"/></a:accent1>`,
    `<a:accent2><a:srgbClr val="${escapeXml(c.accent2)}"/></a:accent2>`,
    `<a:accent3><a:srgbClr val="${escapeXml(c.accent3)}"/></a:accent3>`,
    `<a:accent4><a:srgbClr val="${escapeXml(c.accent4)}"/></a:accent4>`,
    `<a:accent5><a:srgbClr val="${escapeXml(c.accent5)}"/></a:accent5>`,
    `<a:accent6><a:srgbClr val="${escapeXml(c.accent6)}"/></a:accent6>`,
    `<a:hlink><a:srgbClr val="${escapeXml(c.hlink)}"/></a:hlink>`,
    `<a:folHlink><a:srgbClr val="${escapeXml(c.folHlink)}"/></a:folHlink>`,
  ].join('');
  const clrSchemeName = escapeXml(t.extras?.clrSchemeName ?? '');
  return `<a:clrScheme name="${clrSchemeName}">${colorElems}</a:clrScheme>`;
}

/** Sprint 262 + 274：reconstructed fontScheme（無 rawXml fallback 路徑）。 */
function buildFontSchemeXml(t: import('../styles/ThemeResolver').ThemeMap): string {
  const scriptFonts = t.extras?.scriptFonts ?? [];
  const majorScriptFonts = scriptFonts.filter((s) => s.parent === 'majorFont');
  const minorScriptFonts = scriptFonts.filter((s) => s.parent === 'minorFont');
  const major = writeThemeFont('majorFont', t.fontScheme.major, majorScriptFonts);
  const minor = writeThemeFont('minorFont', t.fontScheme.minor, minorScriptFonts);
  const fontSchemeName = escapeXml(t.extras?.fontSchemeName ?? '');
  return `<a:fontScheme name="${fontSchemeName}">${major}${minor}</a:fontScheme>`;
}

/**
 * Sprint 262 / 271：序列化 majorFont / minorFont。
 * Sprint 271 加 scriptFonts 參數：寫入 `<a:font script="X" typeface="Y"/>` 系列
 * fallback fonts（Word 預設東亞語系字型對映）。
 */
function writeThemeFont(
  elementName: 'majorFont' | 'minorFont',
  f: { latin?: string; ea?: string; cs?: string },
  scriptFonts: Array<{ script: string; typeface: string }> = [],
): string {
  const subs: string[] = [];
  if (f.latin !== undefined) subs.push(`<a:latin typeface="${escapeXml(f.latin)}"/>`);
  if (f.ea !== undefined) subs.push(`<a:ea typeface="${escapeXml(f.ea)}"/>`);
  if (f.cs !== undefined) subs.push(`<a:cs typeface="${escapeXml(f.cs)}"/>`);
  for (const sf of scriptFonts) {
    subs.push(`<a:font script="${escapeXml(sf.script)}" typeface="${escapeXml(sf.typeface)}"/>`);
  }
  return `<a:${elementName}>${subs.join('')}</a:${elementName}>`;
}

// ── Sprint 195：SmartArt diagram data 部件 ───────────────────────────────────

interface SmartArtPartItem {
  rId: string;          // 對應 graphic.relId
  filename: string;     // 'word/diagrams/data1.xml' 等
  node: SmartArtNode;
}

/**
 * 從 doc.smartArts 整理為 SmartArtPartItem[]、檔名用流水序號。
 *
 * Sprint 195：parser 把 4 個 SmartArt 部件（data/layout/quickStyle/colors）
 * 摺成一個 SmartArtNode、export 端只需寫 data 部件（parser 走 type=diagramData
 * 解析）；layout/quickStyle/colors 留 後續。
 */
function collectSmartArts(doc: DocumentNode): SmartArtPartItem[] {
  const out: SmartArtPartItem[] = [];
  if (!doc.smartArts) return out;
  let n = 0;
  for (const sa of doc.smartArts) {
    n += 1;
    out.push({ rId: sa.rId, filename: `word/diagrams/data${n}.xml`, node: sa });
  }
  return out;
}

/**
 * 寫單一 `diagrams/dataN.xml`（OOXML §21.4 `<dgm:dataModel>`）。
 *
 * 為 SmartArt 內容點（content pt）逐一 emit `<dgm:pt><dgm:t><a:p><a:r><a:t>`
 * 結構；doc 點（type='doc'）含 `<dgm:prSet loTypeId>` 帶版面類型識別碼。
 * 紀律 #18 scope-down：不重建 cxnLst 連接資訊（parser 不消費、無需 round-trip）。
 */
function writeSmartArtPart(item: SmartArtPartItem): string {
  const sa = item.node;
  const docPt = sa.layoutType
    ? `<dgm:pt modelId="{doc}" type="doc"><dgm:prSet loTypeId="${escapeXml(sa.layoutType)}"/></dgm:pt>`
    : '';
  const contentPts = sa.texts.map((t, i) =>
    `<dgm:pt modelId="{N${i}}"><dgm:t><a:p><a:r><a:t>${escapeXml(t)}</a:t></a:r></a:p></dgm:t></dgm:pt>`,
  ).join('');
  return xmlDecl() +
    `<dgm:dataModel xmlns:dgm="${DGM_NS}" xmlns:a="${A_NS}">` +
    '<dgm:ptLst>' +
    docPt +
    contentPts +
    '</dgm:ptLst>' +
    '</dgm:dataModel>';
}

// ── Sprint 195：Chart 部件 ─────────────────────────────────────────────────

interface ChartPartItem {
  rId: string;          // 對應 graphic.relId
  filename: string;     // 'word/charts/chart1.xml' 等
  node: ChartNode;
}

/**
 * 從 doc.charts 整理為 ChartPartItem[]、檔名用流水序號。
 */
function collectCharts(doc: DocumentNode): ChartPartItem[] {
  const out: ChartPartItem[] = [];
  if (!doc.charts) return out;
  let n = 0;
  for (const ch of doc.charts) {
    n += 1;
    out.push({ rId: ch.rId, filename: `word/charts/chart${n}.xml`, node: ch });
  }
  return out;
}

/**
 * 寫單一 `charts/chartN.xml`（OOXML §21.2 `<c:chartSpace>`）。
 *
 * 結構：`<c:chartSpace><c:chart><c:title>?<c:plotArea><c:{chartType}><c:ser>...`
 * 每 `<c:ser>` 含 tx (name) + cat (strCache) + val (numCache)。
 */
function writeChartPart(item: ChartPartItem): string {
  const ch = item.node;
  const title = ch.title
    ? `<c:title><c:tx><c:rich><a:p><a:r><a:t>${escapeXml(ch.title)}</a:t></a:r></a:p></c:rich></c:tx></c:title>`
    : '';
  const seriesXml = ch.series.map(writeChartSeries).join('');
  const chartType = ch.chartType || 'barChart';
  return xmlDecl() +
    `<c:chartSpace xmlns:c="${C_NS}" xmlns:a="${A_NS}">` +
    '<c:chart>' +
    title +
    '<c:plotArea>' +
    `<c:${chartType}>` +
    seriesXml +
    `</c:${chartType}>` +
    '</c:plotArea>' +
    '</c:chart>' +
    '</c:chartSpace>';
}

/** 序列化單一 ChartSeries 為 `<c:ser>`。 */
function writeChartSeries(s: { name?: string; categories: string[]; values: (number | null)[] }): string {
  const tx = s.name
    ? `<c:tx><c:strRef><c:f>x</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>${escapeXml(s.name)}</c:v></c:pt></c:strCache></c:strRef></c:tx>`
    : '';
  const cat = writeChartStrCache('cat', s.categories);
  const val = writeChartNumCache('val', s.values);
  return `<c:ser>${tx}${cat}${val}</c:ser>`;
}

/** `<c:cat>` 或 `<c:tx>` 內字串快取結構。 */
function writeChartStrCache(elementName: string, values: string[]): string {
  const pts = values
    .map((v, i) => v !== '' ? `<c:pt idx="${i}"><c:v>${escapeXml(v)}</c:v></c:pt>` : '')
    .join('');
  return `<c:${elementName}><c:strRef><c:f>x</c:f><c:strCache>` +
    `<c:ptCount val="${values.length}"/>${pts}` +
    `</c:strCache></c:strRef></c:${elementName}>`;
}

/** `<c:val>` 數值快取結構（null 視為缺漏點、不 emit `<c:pt>`）。 */
function writeChartNumCache(elementName: string, values: (number | null)[]): string {
  const pts = values
    .map((v, i) => v !== null && v !== undefined ? `<c:pt idx="${i}"><c:v>${v}</c:v></c:pt>` : '')
    .join('');
  return `<c:${elementName}><c:numRef><c:f>x</c:f><c:numCache>` +
    `<c:ptCount val="${values.length}"/>${pts}` +
    `</c:numCache></c:numRef></c:${elementName}>`;
}

// ── 工具 ─────────────────────────────────────────────────────────────────────

/** XML 宣告（OOXML standard：UTF-8、standalone="yes"）。 */
function xmlDecl(): string {
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
}

/** XML 字元跳脫：& < > " '。 */
function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/** pt → twips（四捨五入到整數、OOXML 要求整數）。 */
function ptToTwips(pt: number): number {
  return Math.round(pt * TWIPS_PER_PT);
}

/** pt → half-points（`<w:sz>` 單位、12pt = 24、四捨五入到整數）。 */
function ptToHalfPoints(pt: number): number {
  return Math.round(pt * HALF_POINTS_PER_PT);
}
