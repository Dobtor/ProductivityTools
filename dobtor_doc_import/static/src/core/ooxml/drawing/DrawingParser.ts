/**
 * DrawingParser — 解析 <w:drawing> 內嵌與浮動圖片
 *
 * 範圍（Phase B.7 完整版）：
 *   - <wp:inline> → InlineImageNode（rId、width、height、altText）
 *   - <wp:anchor> → FloatImageNode：
 *       - <wp:positionH relativeFrom> + <wp:posOffset> 或 <wp:align>
 *       - <wp:positionV relativeFrom> + <wp:posOffset> 或 <wp:align>
 *       - <wp:wrapNone|wrapSquare|wrapTight|wrapThrough|wrapTopAndBottom>
 *       - behindDoc / allowOverlap 旗標
 *   - <a:blip r:embed="rIdN"> 取得圖片關係 rId
 *   - <wp:extent cx cy>（EMU → Pt）
 *   - <wp:docPr descr=""> altText
 *
 * 範圍（Sprint 286 補）：
 *   - <wp:effectExtent l/t/r/b>（EMU → Pt）— 陰影/光暈外擴，per-image
 *
 * 不在此 Parser 範圍：
 *   - <a:srcRect> 圖片裁切 — 由 Renderer 處理
 *   - <v:shape> VML 舊版圖形 — 降級為空 InlineImageNode（與 fallback 一致）
 *
 * Phase 5（規劃文件）：SmartArt / Charts 視為 fallback 圖片，仍經此 Parser。
 */

import type { AnchorMetadata, AnchorWrapText, EffectExtent, FloatImageNode, FloatTextBoxNode, ImageSrcRect, InlineImageNode, ParagraphNode, Pt, WrapPolygon, WrapPolygonPoint } from '../ast/types';
import { emuToPt } from '../units/units';

/**
 * Sprint 38：text box 內 paragraph 的解析 callback。
 * 由 caller（ParagraphParser）傳入，避免 DrawingParser ↔ ParagraphParser 循環依賴。
 */
export type ParagraphFactory = (p: Element) => ParagraphNode;

export class DrawingParser {
  /**
   * 解析單一 <w:drawing> 元素。
   *
   * @param drawing  <w:drawing> 元素
   * @param paragraphFactory  Sprint 38：解析 text box 內 `<w:p>` 的 callback。
   *                          不傳時 anchor text box 將以空 paragraphs 收場（不影響 image-type anchor）
   * @returns InlineImageNode / FloatImageNode / FloatTextBoxNode；無法辨識內容時回 fallback inline image（rId 為空）
   */
  parse(
    drawing: Element,
    paragraphFactory?: ParagraphFactory,
  ): InlineImageNode | FloatImageNode | FloatTextBoxNode {
    const inlineEl = directChild(drawing, 'wp:inline');
    if (inlineEl) {
      return parseInlineImage(inlineEl);
    }

    const anchorEl = directChild(drawing, 'wp:anchor');
    if (anchorEl) {
      // Sprint 38：偵測 anchor 是否為 text box（含 <wps:wsp><wps:txbx>）；
      // 是 → FloatTextBoxNode；否 → 走原 image 路徑
      const txbxContent = findTxbxContent(anchorEl);
      if (txbxContent) {
        return parseFloatTextBox(anchorEl, txbxContent, paragraphFactory);
      }
      return parseFloatImage(anchorEl);
    }

    return makeFallbackImage();
  }
}

// ── wp:inline → InlineImageNode ──────────────────────────────────────────────

function parseInlineImage(el: Element): InlineImageNode {
  const { width, height } = parseExtent(el);
  const altText = parseAltText(el);
  const rId = findBlipEmbed(el) ?? '';

  const node: InlineImageNode = { type: 'inlineImage', rId, width, height };
  if (altText) node.altText = altText;
  const srcRect = parseSrcRect(el);
  if (srcRect) node.srcRect = srcRect;
  // Sprint 183：偵測 SmartArt（diagram）/ Chart graphic frame —— 圖形不內嵌、
  // 以 relId 指向獨立部件，render 時做線性文字 fallback。
  const graphic = parseGraphicFrame(el);
  if (graphic) node.graphic = graphic;
  const effectExtent = parseEffectExtent(el);
  if (effectExtent) node.effectExtent = effectExtent;
  return node;
}

/** `<a:graphicData uri>` 的 SmartArt / Chart 命名空間。 */
const GRAPHIC_URI_DIAGRAM = 'http://schemas.openxmlformats.org/drawingml/2006/diagram';
const GRAPHIC_URI_CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart';

/**
 * Sprint 183：偵測 `<wp:inline>` 內的 SmartArt / Chart graphic frame。
 *
 * - SmartArt：`<a:graphicData uri=".../diagram"><dgm:relIds r:dm="rId..">`
 * - Chart：`<a:graphicData uri=".../chart"><c:chart r:id="rId..">`
 *
 * @returns `{ kind, relId }` 或 undefined（非 SmartArt/Chart 的一般圖片）
 */
function parseGraphicFrame(
  el: Element,
): { kind: 'diagram' | 'chart'; relId: string } | undefined {
  const gds = el.getElementsByTagName('a:graphicData');
  if (gds.length === 0) return undefined;
  const uri = gds[0].getAttribute('uri');
  if (uri === GRAPHIC_URI_DIAGRAM) {
    const relIds = gds[0].getElementsByTagName('dgm:relIds');
    const relId = relIds.length > 0 ? relIds[0].getAttribute('r:dm') : null;
    if (relId) return { kind: 'diagram', relId };
  } else if (uri === GRAPHIC_URI_CHART) {
    const charts = gds[0].getElementsByTagName('c:chart');
    const relId = charts.length > 0 ? charts[0].getAttribute('r:id') : null;
    if (relId) return { kind: 'chart', relId };
  }
  return undefined;
}

// ── wp:anchor → FloatImageNode ───────────────────────────────────────────────

function parseFloatImage(el: Element): FloatImageNode {
  const { width, height } = parseExtent(el);
  const altText = parseAltText(el);
  const rId = findBlipEmbed(el) ?? '';

  const posH = parsePositionH(directChild(el, 'wp:positionH'));
  const posV = parsePositionV(directChild(el, 'wp:positionV'));
  const wrapType = detectWrapType(el);

  const behindDocRaw = el.getAttribute('behindDoc');
  const allowOverlapRaw = el.getAttribute('allowOverlap');

  const node: FloatImageNode = {
    type: 'floatImage',
    rId,
    width,
    height,
    posH,
    posV,
    wrapType,
  };
  if (altText) node.altText = altText;
  if (behindDocRaw === '1' || behindDocRaw === 'true') node.behindDoc = true;
  if (allowOverlapRaw === '1' || allowOverlapRaw === 'true') node.allowOverlap = true;
  const srcRect = parseSrcRect(el);
  if (srcRect) node.srcRect = srcRect;
  const effectExtent = parseEffectExtent(el);
  if (effectExtent) node.effectExtent = effectExtent;
  // Sprint 287：補完整 anchor metadata + wrapText
  const anchorMeta = parseAnchorMetadata(el);
  if (anchorMeta) node.anchor = anchorMeta;
  const wrapText = detectWrapText(el);
  if (wrapText) node.wrapText = wrapText;
  // Sprint 289：wrapTight / wrapThrough 的 wrapPolygon 輪廓
  const wrapPolygon = parseWrapPolygon(el);
  if (wrapPolygon) node.wrapPolygon = wrapPolygon;
  return node;
}

/**
 * Sprint 286：解析 DrawingML `<wp:effectExtent l="..." t="..." r="..." b="..."/>`。
 *
 * 屬性值單位 EMU（直接 EMU→Pt），缺漏屬性以 0 計（OOXML 預設）。
 * 找不到元素 → undefined（不掛欄位、writer 不 emit）。
 * 任一屬性非數字 → 該軸視為 0（saneness）。
 *
 * 全 0 仍保留（與 srcRect 不同：effectExtent 全 0 是 Word 對「無陰影」的明示記號，
 * 為 round-trip lossless 不可省略）。
 */
function parseEffectExtent(el: Element): EffectExtent | undefined {
  const ee = directChild(el, 'wp:effectExtent');
  if (!ee) return undefined;
  const toEmu = (raw: string | null): number => {
    if (raw === null || raw === '') return 0;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : 0;
  };
  return {
    left: emuToPt(toEmu(ee.getAttribute('l'))),
    top: emuToPt(toEmu(ee.getAttribute('t'))),
    right: emuToPt(toEmu(ee.getAttribute('r'))),
    bottom: emuToPt(toEmu(ee.getAttribute('b'))),
  };
}

/**
 * Sprint 40：解析 DrawingML `<a:srcRect l="..." t="..." r="..." b="..."/>`。
 *
 * OOXML §20.1.10.40：屬性值 = 百分比 × 1000（即 4066 = 4.066%）。
 * 0–1 分數轉換：raw / 100000。
 *
 * 兩種情況回 undefined：
 *   - 找不到 `<a:srcRect>`
 *   - 找到但所有四個屬性都 0（空裁切）
 *
 * 範圍 sanitize：每軸 left+right < 1 且 top+bottom < 1，否則回 undefined（避免裁光）。
 */
function parseSrcRect(el: Element): ImageSrcRect | undefined {
  const srcRects = el.getElementsByTagName('a:srcRect');
  if (srcRects.length === 0) return undefined;
  const sr = srcRects[0];
  const toFrac = (raw: string | null): number => {
    if (raw === null || raw === '') return 0;
    const n = parseInt(raw, 10);
    if (!Number.isFinite(n) || n <= 0) return 0;
    return n / 100000;
  };
  const l = toFrac(sr.getAttribute('l'));
  const t = toFrac(sr.getAttribute('t'));
  const r = toFrac(sr.getAttribute('r'));
  const b = toFrac(sr.getAttribute('b'));
  if (l === 0 && t === 0 && r === 0 && b === 0) return undefined;
  if (l + r >= 1 || t + b >= 1) return undefined; // 整張被裁光 → 不裁切（fallback 安全）
  return { leftPct: l, topPct: t, rightPct: r, bottomPct: b };
}

// ── Sprint 38: wp:anchor + wps:wsp + wps:txbx → FloatTextBoxNode ────────────

/**
 * 在 anchor 子樹下找 `<wps:txbx>` 或 `<w:txbxContent>`（兩種 markup 都見過：
 * Office 較新版用 `<wps:wsp><wps:txbx><w:txbxContent>`；舊版可能直接內嵌 `<w:txbxContent>`）。
 */
function findTxbxContent(anchorEl: Element): Element | undefined {
  // 直接找 w:txbxContent；DOM getElementsByTagName 不分 namespace 也會匹配到 .txbxContent
  const direct = anchorEl.getElementsByTagName('w:txbxContent');
  if (direct.length > 0) return direct[0];
  const noNs = anchorEl.getElementsByTagName('txbxContent');
  if (noNs.length > 0) return noNs[0];
  return undefined;
}

function parseFloatTextBox(
  anchorEl: Element,
  txbxContent: Element,
  paragraphFactory: ParagraphFactory | undefined,
): FloatTextBoxNode {
  const { width, height } = parseExtent(anchorEl);
  const posH = parsePositionH(directChild(anchorEl, 'wp:positionH'));
  const posV = parsePositionV(directChild(anchorEl, 'wp:positionV'));
  const wrapType = detectWrapType(anchorEl);

  const behindDocRaw = anchorEl.getAttribute('behindDoc');
  const allowOverlapRaw = anchorEl.getAttribute('allowOverlap');

  // 解析 textbox 內所有 <w:p>
  const paragraphs: ParagraphNode[] = [];
  if (paragraphFactory) {
    for (const child of directChildren(txbxContent)) {
      if (child.tagName === 'w:p') {
        paragraphs.push(paragraphFactory(child));
      }
    }
  }

  const node: FloatTextBoxNode = {
    type: 'floatTextBox',
    width,
    height,
    posH,
    posV,
    wrapType,
    paragraphs,
  };
  if (behindDocRaw === '1' || behindDocRaw === 'true') node.behindDoc = true;
  if (allowOverlapRaw === '1' || allowOverlapRaw === 'true') node.allowOverlap = true;
  const effectExtent = parseEffectExtent(anchorEl);
  if (effectExtent) node.effectExtent = effectExtent;
  // Sprint 287：anchor metadata + wrapText（與 FloatImage 對稱）
  const anchorMeta = parseAnchorMetadata(anchorEl);
  if (anchorMeta) node.anchor = anchorMeta;
  const wrapText = detectWrapText(anchorEl);
  if (wrapText) node.wrapText = wrapText;
  // Sprint 289：wrapTight / wrapThrough 的 wrapPolygon 輪廓（textbox 對稱）
  const wrapPolygon = parseWrapPolygon(anchorEl);
  if (wrapPolygon) node.wrapPolygon = wrapPolygon;

  // Sprint 39：解析 <wps:wsp> 內的 bodyPr / spPr（padding / 背景 / 邊框）
  const wsp = findWsp(anchorEl);
  if (wsp) {
    const bodyPr = directChild(wsp, 'wps:bodyPr');
    if (bodyPr) {
      const parsed = parseBodyPr(bodyPr);
      if (parsed) node.bodyPr = parsed;
    }
    const spPr = directChild(wsp, 'wps:spPr');
    if (spPr) {
      const fill = parseShapeFill(spPr);
      if (fill) node.fill = fill;
      const border = parseShapeBorder(spPr);
      if (border) node.border = border;
    }
  }

  return node;
}

/**
 * Sprint 39：在 anchor 下找 `<wps:wsp>` 元素（通常路徑：
 * `<wp:anchor><a:graphic><a:graphicData><wps:wsp>...</wps:wsp></a:graphicData></a:graphic></wp:anchor>`）。
 */
function findWsp(anchorEl: Element): Element | undefined {
  const direct = anchorEl.getElementsByTagName('wps:wsp');
  if (direct.length > 0) return direct[0];
  const noNs = anchorEl.getElementsByTagName('wsp');
  if (noNs.length > 0) return noNs[0];
  return undefined;
}

/**
 * Sprint 39：解析 `<wps:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>` 為 padding（Pt）。
 * 缺漏屬性套 Office 預設值（l/r=91440 EMU=7.2pt、t/b=45720 EMU=3.6pt）。
 * 整體缺漏（無 bodyPr）→ caller 不呼叫此函式；呼叫到時至少有 element 存在。
 */
function parseBodyPr(el: Element): FloatTextBoxNode['bodyPr'] | undefined {
  const lRaw = el.getAttribute('lIns');
  const tRaw = el.getAttribute('tIns');
  const rRaw = el.getAttribute('rIns');
  const bRaw = el.getAttribute('bIns');
  // OOXML 預設值（§17.18.93 / DrawingML）
  const DEFAULT_LR_EMU = 91440;
  const DEFAULT_TB_EMU = 45720;
  const parseEmu = (raw: string | null, def: number): number => {
    if (raw === null || raw === '') return def;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : def;
  };
  return {
    leftInset: emuToPt(parseEmu(lRaw, DEFAULT_LR_EMU)),
    topInset: emuToPt(parseEmu(tRaw, DEFAULT_TB_EMU)),
    rightInset: emuToPt(parseEmu(rRaw, DEFAULT_LR_EMU)),
    bottomInset: emuToPt(parseEmu(bRaw, DEFAULT_TB_EMU)),
  };
}

/**
 * Sprint 39：解析 `<wps:spPr>` 內的 `<a:solidFill><a:srgbClr val="RRGGBB"/></a:solidFill>` 為背景色。
 * `<a:noFill/>` 或缺漏 → undefined。
 */
function parseShapeFill(spPr: Element): string | undefined {
  // `<a:noFill/>` 直接子節點 → 無背景
  if (directChild(spPr, 'a:noFill')) return undefined;
  const solidFill = directChild(spPr, 'a:solidFill');
  if (!solidFill) return undefined;
  const srgb = directChild(solidFill, 'a:srgbClr');
  if (!srgb) return undefined;
  const val = srgb.getAttribute('val');
  return val && /^[0-9A-Fa-f]{6}$/.test(val) ? val.toUpperCase() : undefined;
}

/**
 * Sprint 39：解析 `<wps:spPr><a:ln w="..."><a:solidFill><a:srgbClr val="..."/></a:solidFill></a:ln>` 為邊框。
 * `<a:ln><a:noFill/>` 或缺漏 `<a:solidFill>` → undefined。
 * width 從 EMU 換算 Pt。
 */
function parseShapeBorder(spPr: Element): FloatTextBoxNode['border'] | undefined {
  const ln = directChild(spPr, 'a:ln');
  if (!ln) return undefined;
  // `<a:ln><a:noFill/>` → 不畫
  if (directChild(ln, 'a:noFill')) return undefined;
  const solidFill = directChild(ln, 'a:solidFill');
  if (!solidFill) return undefined;
  const srgb = directChild(solidFill, 'a:srgbClr');
  if (!srgb) return undefined;
  const colorVal = srgb.getAttribute('val');
  if (!colorVal || !/^[0-9A-Fa-f]{6}$/.test(colorVal)) return undefined;
  const wRaw = ln.getAttribute('w');
  // OOXML 預設線寬若無 w → 0.75pt（9525 EMU）；缺漏給 0 視為不畫
  const wEmu = wRaw ? parseInt(wRaw, 10) : 9525;
  if (!Number.isFinite(wEmu) || wEmu <= 0) return undefined;
  return {
    width: emuToPt(wEmu),
    color: colorVal.toUpperCase(),
  };
}

// ── 共用：尺寸 / altText / blip rId ──────────────────────────────────────────

function parseExtent(el: Element): { width: number; height: number } {
  const extent = directChild(el, 'wp:extent');
  if (!extent) return { width: 0, height: 0 };
  const cx = parseInt(extent.getAttribute('cx') ?? '0', 10);
  const cy = parseInt(extent.getAttribute('cy') ?? '0', 10);
  return {
    width: Number.isFinite(cx) ? emuToPt(cx) : 0,
    height: Number.isFinite(cy) ? emuToPt(cy) : 0,
  };
}

function parseAltText(el: Element): string | undefined {
  const docPr = directChild(el, 'wp:docPr');
  if (!docPr) return undefined;
  return docPr.getAttribute('descr') ?? docPr.getAttribute('title') ?? undefined;
}

function findBlipEmbed(el: Element): string | undefined {
  const blips = el.getElementsByTagName('a:blip');
  if (blips.length === 0) return undefined;
  const blip = blips[0];
  return (
    blip.getAttribute('r:embed') ??
    blip.getAttribute('embed') ??
    undefined
  );
}

// ── wp:positionH / wp:positionV ──────────────────────────────────────────────

type PosHRelative = FloatImageNode['posH']['relativeFrom'];
type PosHAlign = NonNullable<FloatImageNode['posH']['align']>;
type PosVRelative = FloatImageNode['posV']['relativeFrom'];
type PosVAlign = NonNullable<FloatImageNode['posV']['align']>;

const POS_H_RELATIVE: PosHRelative[] = [
  'margin',
  'page',
  'column',
  'character',
  'leftMargin',
  'rightMargin',
  'insideMargin',
  'outsideMargin',
];

const POS_V_RELATIVE: PosVRelative[] = [
  'margin',
  'page',
  'paragraph',
  'line',
  'topMargin',
  'bottomMargin',
  'insideMargin',
  'outsideMargin',
];

const POS_H_ALIGN: PosHAlign[] = ['left', 'right', 'center', 'inside', 'outside'];
const POS_V_ALIGN: PosVAlign[] = ['top', 'bottom', 'center', 'inside', 'outside'];

function parsePositionH(el: Element | undefined): FloatImageNode['posH'] {
  const relRaw = el?.getAttribute('relativeFrom') ?? 'column';
  const relativeFrom: PosHRelative = (POS_H_RELATIVE as readonly string[]).includes(relRaw)
    ? (relRaw as PosHRelative)
    : 'column';
  const out: FloatImageNode['posH'] = { relativeFrom };
  if (!el) return out;

  const alignEl = directChild(el, 'wp:align');
  if (alignEl) {
    const txt = (alignEl.textContent ?? '').trim();
    if ((POS_H_ALIGN as readonly string[]).includes(txt)) {
      out.align = txt as PosHAlign;
    }
  }
  const offsetEl = directChild(el, 'wp:posOffset');
  if (offsetEl) {
    const n = parseInt((offsetEl.textContent ?? '0').trim(), 10);
    if (Number.isFinite(n)) out.posOffset = emuToPt(n);
  }
  return out;
}

function parsePositionV(el: Element | undefined): FloatImageNode['posV'] {
  const relRaw = el?.getAttribute('relativeFrom') ?? 'paragraph';
  const relativeFrom: PosVRelative = (POS_V_RELATIVE as readonly string[]).includes(relRaw)
    ? (relRaw as PosVRelative)
    : 'paragraph';
  const out: FloatImageNode['posV'] = { relativeFrom };
  if (!el) return out;

  const alignEl = directChild(el, 'wp:align');
  if (alignEl) {
    const txt = (alignEl.textContent ?? '').trim();
    if ((POS_V_ALIGN as readonly string[]).includes(txt)) {
      out.align = txt as PosVAlign;
    }
  }
  const offsetEl = directChild(el, 'wp:posOffset');
  if (offsetEl) {
    const n = parseInt((offsetEl.textContent ?? '0').trim(), 10);
    if (Number.isFinite(n)) out.posOffset = emuToPt(n);
  }
  return out;
}

// ── wrap type 偵測 ────────────────────────────────────────────────────────────

function detectWrapType(el: Element): FloatImageNode['wrapType'] {
  for (const child of directChildren(el)) {
    switch (child.tagName) {
      case 'wp:wrapNone':
        return 'none';
      case 'wp:wrapSquare':
        return 'square';
      case 'wp:wrapTight':
        return 'tight';
      case 'wp:wrapThrough':
        return 'through';
      case 'wp:wrapTopAndBottom':
        return 'topAndBottom';
    }
  }
  // 預設：square（最常見）
  return 'square';
}

/**
 * Sprint 287：偵測 wrap mode 子元素的 `wrapText` 屬性。
 *
 * 適用於 `<wp:wrapSquare>` / `<wp:wrapTight>` / `<wp:wrapThrough>` /
 * `<wp:wrapTopAndBottom>`。`<wp:wrapNone>` 無 wrapText（不繞排）。
 * 預設值（Office）：bothSides；本函式對「無屬性 / 無 wrap 元素」回 undefined
 * （capture-only：let caller 知道 docx 沒明指、不偽造預設）。
 */
function detectWrapText(el: Element): AnchorWrapText | undefined {
  for (const child of directChildren(el)) {
    if (
      child.tagName === 'wp:wrapSquare' ||
      child.tagName === 'wp:wrapTight' ||
      child.tagName === 'wp:wrapThrough' ||
      child.tagName === 'wp:wrapTopAndBottom'
    ) {
      const raw = child.getAttribute('wrapText');
      if (raw === 'left' || raw === 'right' || raw === 'largest' || raw === 'bothSides') {
        return raw;
      }
      return undefined;
    }
  }
  return undefined;
}

/**
 * Sprint 289：解析 wp:wrapTight / wp:wrapThrough 內的 `<wp:wrapPolygon>`。
 *
 * 結構（OOXML §20.4.2.10）：
 *   ```xml
 *   <wp:wrapTight wrapText="bothSides">
 *     <wp:wrapPolygon edited="1">
 *       <wp:start x="0" y="0"/>
 *       <wp:lineTo x="21337" y="0"/>
 *       ...
 *     </wp:wrapPolygon>
 *   </wp:wrapTight>
 *   ```
 *
 * 缺漏 `<wp:wrapPolygon>` / 無 `<wp:start>` / 無 `<wp:lineTo>` → undefined。
 * 座標單位為 drawing coordinates（OOXML §20.4.2.17 ST_Coordinate）— 不直接是 EMU，
 * caller 拿到的是 raw int；render 時應配合 image extent 縮放。
 * 紀律 #18 scope-down：本函式只 capture、render 端 polygon clip 留 Phase 3.4 完整 wrapTight。
 */
function parseWrapPolygon(anchorEl: Element): WrapPolygon | undefined {
  let wrapEl: Element | undefined;
  for (const child of directChildren(anchorEl)) {
    if (child.tagName === 'wp:wrapTight' || child.tagName === 'wp:wrapThrough') {
      wrapEl = child;
      break;
    }
  }
  if (!wrapEl) return undefined;
  const polyEl = directChild(wrapEl, 'wp:wrapPolygon');
  if (!polyEl) return undefined;

  const parsePoint = (el: Element): WrapPolygonPoint | undefined => {
    const xRaw = el.getAttribute('x');
    const yRaw = el.getAttribute('y');
    if (xRaw === null || yRaw === null) return undefined;
    const x = parseInt(xRaw, 10);
    const y = parseInt(yRaw, 10);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return undefined;
    return { x, y };
  };

  const startEl = directChild(polyEl, 'wp:start');
  if (!startEl) return undefined;
  const start = parsePoint(startEl);
  if (!start) return undefined;

  const lineTo: WrapPolygonPoint[] = [];
  for (const child of directChildren(polyEl)) {
    if (child.tagName === 'wp:lineTo') {
      const pt = parsePoint(child);
      if (pt) lineTo.push(pt);
    }
  }
  if (lineTo.length === 0) return undefined;

  const editedRaw = polyEl.getAttribute('edited');
  const polygon: WrapPolygon = { start, lineTo };
  if (editedRaw === '1' || editedRaw === 'true') polygon.edited = true;
  return polygon;
}

/**
 * Sprint 287：補完整 wp:anchor 屬性 capture（除 posH/posV/wrapType/behindDoc/
 * allowOverlap 等 Sprint 37 已 capture 之外）。
 *
 * 全屬性 optional；任何一個有值則 caller 拿到 AnchorMetadata 物件、無則 undefined。
 * EMU 屬性走 emuToPt；Boolean 屬性 "1"/"true" → true，"0"/"false"/缺漏 → false
 * (false 視為 undefined 不掛欄位、避免污染預設行為)。
 * relativeHeight 為非負整數 UInt（Word 用 z-order index）。
 */
function parseAnchorMetadata(el: Element): AnchorMetadata | undefined {
  const meta: AnchorMetadata = {};
  const parseEmuAttr = (name: string): Pt | undefined => {
    const raw = el.getAttribute(name);
    if (raw === null || raw === '') return undefined;
    const n = parseInt(raw, 10);
    if (!Number.isFinite(n)) return undefined;
    return emuToPt(n);
  };
  const parseBoolAttr = (name: string): boolean | undefined => {
    const raw = el.getAttribute(name);
    if (raw === '1' || raw === 'true') return true;
    return undefined;
  };

  const dt = parseEmuAttr('distT');
  if (dt !== undefined) meta.distT = dt;
  const db = parseEmuAttr('distB');
  if (db !== undefined) meta.distB = db;
  const dl = parseEmuAttr('distL');
  if (dl !== undefined) meta.distL = dl;
  const dr = parseEmuAttr('distR');
  if (dr !== undefined) meta.distR = dr;

  const rh = el.getAttribute('relativeHeight');
  if (rh !== null && rh !== '') {
    const n = parseInt(rh, 10);
    if (Number.isFinite(n) && n >= 0) meta.relativeHeight = n;
  }

  const locked = parseBoolAttr('locked');
  if (locked) meta.locked = true;
  const lic = parseBoolAttr('layoutInCell');
  if (lic) meta.layoutInCell = true;
  const hidden = parseBoolAttr('hidden');
  if (hidden) meta.hidden = true;

  // 全為空 → 不掛欄位（與 srcRect 對稱）
  if (Object.keys(meta).length === 0) return undefined;
  return meta;
}

// ── fallback ──────────────────────────────────────────────────────────────────

function makeFallbackImage(): InlineImageNode {
  return { type: 'inlineImage', rId: '', width: 0, height: 0 };
}

// ── 共用工具 ──────────────────────────────────────────────────────────────────

function directChildren(el: Element | undefined): Element[] {
  if (!el) return [];
  const out: Element[] = [];
  const cs = el.childNodes;
  for (let i = 0; i < cs.length; i++) {
    const n = cs[i];
    if (n.nodeType === 1) out.push(n as Element);
  }
  return out;
}

function directChild(el: Element | undefined, tagName: string): Element | undefined {
  for (const child of directChildren(el)) {
    if (child.tagName === tagName) return child;
  }
  return undefined;
}
