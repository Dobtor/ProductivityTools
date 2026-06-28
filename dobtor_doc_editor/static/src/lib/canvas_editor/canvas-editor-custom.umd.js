(function (global, factory) {
    typeof exports === 'object' && typeof module !== 'undefined' ? factory(exports) :
    typeof define === 'function' && define.amd ? define(['exports'], factory) :
    (global = typeof globalThis !== 'undefined' ? globalThis : global || self, factory(global.DobtorCanvasEditor = {}));
})(this, (function (exports) { 'use strict';

    /**
     * units — OOXML 度量單位轉換工具
     *
     * OOXML 慣用單位：
     *   - twip (1/20 pt) — w:sz、w:tblW (w:dxa)
     *   - half-point (1/2 pt) — w:sz of w:rPr font size
     *   - eighth-point (1/8 pt) — w:sz of border width
     *   - EMU (English Metric Unit, 1/914400 inch) — DrawingML wp:extent
     *
     * 全模組一律以 pt 為標準（見 ast/types.ts: Pt）。
     */
    const TWIP_PER_PT = 20;
    const HALF_POINT_PER_PT = 2;
    const EIGHTH_POINT_PER_PT = 8;
    const EMU_PER_INCH = 914400;
    const PT_PER_INCH = 72;
    const EMU_PER_PT = EMU_PER_INCH / PT_PER_INCH; // 12700
    function twipToPt(twip) {
        return twip / TWIP_PER_PT;
    }
    function halfPointToPt(hp) {
        return hp / HALF_POINT_PER_PT;
    }
    function eighthPointToPt(ep) {
        return ep / EIGHTH_POINT_PER_PT;
    }
    function emuToPt(emu) {
        return emu / EMU_PER_PT;
    }
    function ptToPx(pt, dpi = 96) {
        return (pt / PT_PER_INCH) * dpi;
    }

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
     * 不在此 Parser 範圍：
     *   - <wp:effectExtent> 陰影外擴 — 由 Renderer 處理
     *   - <a:srcRect> 圖片裁切 — 由 Renderer 處理
     *   - <v:shape> VML 舊版圖形 — 降級為空 InlineImageNode（與 fallback 一致）
     *
     * Phase 5（規劃文件）：SmartArt / Charts 視為 fallback 圖片，仍經此 Parser。
     */
    class DrawingParser {
        /**
         * 解析單一 <w:drawing> 元素。
         *
         * @param drawing  <w:drawing> 元素
         * @param paragraphFactory  Sprint 38：解析 text box 內 `<w:p>` 的 callback。
         *                          不傳時 anchor text box 將以空 paragraphs 收場（不影響 image-type anchor）
         * @returns InlineImageNode / FloatImageNode / FloatTextBoxNode；無法辨識內容時回 fallback inline image（rId 為空）
         */
        parse(drawing, paragraphFactory) {
            const inlineEl = directChild$7(drawing, 'wp:inline');
            if (inlineEl) {
                return parseInlineImage(inlineEl);
            }
            const anchorEl = directChild$7(drawing, 'wp:anchor');
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
    function parseInlineImage(el) {
        const { width, height } = parseExtent(el);
        const altText = parseAltText(el);
        const rId = findBlipEmbed(el) ?? '';
        const node = { type: 'inlineImage', rId, width, height };
        if (altText)
            node.altText = altText;
        const srcRect = parseSrcRect(el);
        if (srcRect)
            node.srcRect = srcRect;
        // Sprint 183：偵測 SmartArt（diagram）/ Chart graphic frame —— 圖形不內嵌、
        // 以 relId 指向獨立部件，render 時做線性文字 fallback。
        const graphic = parseGraphicFrame(el);
        if (graphic)
            node.graphic = graphic;
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
    function parseGraphicFrame(el) {
        const gds = el.getElementsByTagName('a:graphicData');
        if (gds.length === 0)
            return undefined;
        const uri = gds[0].getAttribute('uri');
        if (uri === GRAPHIC_URI_DIAGRAM) {
            const relIds = gds[0].getElementsByTagName('dgm:relIds');
            const relId = relIds.length > 0 ? relIds[0].getAttribute('r:dm') : null;
            if (relId)
                return { kind: 'diagram', relId };
        }
        else if (uri === GRAPHIC_URI_CHART) {
            const charts = gds[0].getElementsByTagName('c:chart');
            const relId = charts.length > 0 ? charts[0].getAttribute('r:id') : null;
            if (relId)
                return { kind: 'chart', relId };
        }
        return undefined;
    }
    // ── wp:anchor → FloatImageNode ───────────────────────────────────────────────
    function parseFloatImage(el) {
        const { width, height } = parseExtent(el);
        const altText = parseAltText(el);
        const rId = findBlipEmbed(el) ?? '';
        const posH = parsePositionH(directChild$7(el, 'wp:positionH'));
        const posV = parsePositionV(directChild$7(el, 'wp:positionV'));
        const wrapType = detectWrapType(el);
        const behindDocRaw = el.getAttribute('behindDoc');
        const allowOverlapRaw = el.getAttribute('allowOverlap');
        const node = {
            type: 'floatImage',
            rId,
            width,
            height,
            posH,
            posV,
            wrapType,
        };
        if (altText)
            node.altText = altText;
        if (behindDocRaw === '1' || behindDocRaw === 'true')
            node.behindDoc = true;
        if (allowOverlapRaw === '1' || allowOverlapRaw === 'true')
            node.allowOverlap = true;
        const srcRect = parseSrcRect(el);
        if (srcRect)
            node.srcRect = srcRect;
        return node;
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
    function parseSrcRect(el) {
        const srcRects = el.getElementsByTagName('a:srcRect');
        if (srcRects.length === 0)
            return undefined;
        const sr = srcRects[0];
        const toFrac = (raw) => {
            if (raw === null || raw === '')
                return 0;
            const n = parseInt(raw, 10);
            if (!Number.isFinite(n) || n <= 0)
                return 0;
            return n / 100000;
        };
        const l = toFrac(sr.getAttribute('l'));
        const t = toFrac(sr.getAttribute('t'));
        const r = toFrac(sr.getAttribute('r'));
        const b = toFrac(sr.getAttribute('b'));
        if (l === 0 && t === 0 && r === 0 && b === 0)
            return undefined;
        if (l + r >= 1 || t + b >= 1)
            return undefined; // 整張被裁光 → 不裁切（fallback 安全）
        return { leftPct: l, topPct: t, rightPct: r, bottomPct: b };
    }
    // ── Sprint 38: wp:anchor + wps:wsp + wps:txbx → FloatTextBoxNode ────────────
    /**
     * 在 anchor 子樹下找 `<wps:txbx>` 或 `<w:txbxContent>`（兩種 markup 都見過：
     * Office 較新版用 `<wps:wsp><wps:txbx><w:txbxContent>`；舊版可能直接內嵌 `<w:txbxContent>`）。
     */
    function findTxbxContent(anchorEl) {
        // 直接找 w:txbxContent；DOM getElementsByTagName 不分 namespace 也會匹配到 .txbxContent
        const direct = anchorEl.getElementsByTagName('w:txbxContent');
        if (direct.length > 0)
            return direct[0];
        const noNs = anchorEl.getElementsByTagName('txbxContent');
        if (noNs.length > 0)
            return noNs[0];
        return undefined;
    }
    function parseFloatTextBox(anchorEl, txbxContent, paragraphFactory) {
        const { width, height } = parseExtent(anchorEl);
        const posH = parsePositionH(directChild$7(anchorEl, 'wp:positionH'));
        const posV = parsePositionV(directChild$7(anchorEl, 'wp:positionV'));
        const wrapType = detectWrapType(anchorEl);
        const behindDocRaw = anchorEl.getAttribute('behindDoc');
        const allowOverlapRaw = anchorEl.getAttribute('allowOverlap');
        // 解析 textbox 內所有 <w:p>
        const paragraphs = [];
        if (paragraphFactory) {
            for (const child of directChildren$b(txbxContent)) {
                if (child.tagName === 'w:p') {
                    paragraphs.push(paragraphFactory(child));
                }
            }
        }
        const node = {
            type: 'floatTextBox',
            width,
            height,
            posH,
            posV,
            wrapType,
            paragraphs,
        };
        if (behindDocRaw === '1' || behindDocRaw === 'true')
            node.behindDoc = true;
        if (allowOverlapRaw === '1' || allowOverlapRaw === 'true')
            node.allowOverlap = true;
        // Sprint 39：解析 <wps:wsp> 內的 bodyPr / spPr（padding / 背景 / 邊框）
        const wsp = findWsp(anchorEl);
        if (wsp) {
            const bodyPr = directChild$7(wsp, 'wps:bodyPr');
            if (bodyPr) {
                const parsed = parseBodyPr(bodyPr);
                if (parsed)
                    node.bodyPr = parsed;
            }
            const spPr = directChild$7(wsp, 'wps:spPr');
            if (spPr) {
                const fill = parseShapeFill(spPr);
                if (fill)
                    node.fill = fill;
                const border = parseShapeBorder(spPr);
                if (border)
                    node.border = border;
            }
        }
        return node;
    }
    /**
     * Sprint 39：在 anchor 下找 `<wps:wsp>` 元素（通常路徑：
     * `<wp:anchor><a:graphic><a:graphicData><wps:wsp>...</wps:wsp></a:graphicData></a:graphic></wp:anchor>`）。
     */
    function findWsp(anchorEl) {
        const direct = anchorEl.getElementsByTagName('wps:wsp');
        if (direct.length > 0)
            return direct[0];
        const noNs = anchorEl.getElementsByTagName('wsp');
        if (noNs.length > 0)
            return noNs[0];
        return undefined;
    }
    /**
     * Sprint 39：解析 `<wps:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>` 為 padding（Pt）。
     * 缺漏屬性套 Office 預設值（l/r=91440 EMU=7.2pt、t/b=45720 EMU=3.6pt）。
     * 整體缺漏（無 bodyPr）→ caller 不呼叫此函式；呼叫到時至少有 element 存在。
     */
    function parseBodyPr(el) {
        const lRaw = el.getAttribute('lIns');
        const tRaw = el.getAttribute('tIns');
        const rRaw = el.getAttribute('rIns');
        const bRaw = el.getAttribute('bIns');
        // OOXML 預設值（§17.18.93 / DrawingML）
        const DEFAULT_LR_EMU = 91440;
        const DEFAULT_TB_EMU = 45720;
        const parseEmu = (raw, def) => {
            if (raw === null || raw === '')
                return def;
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
    function parseShapeFill(spPr) {
        // `<a:noFill/>` 直接子節點 → 無背景
        if (directChild$7(spPr, 'a:noFill'))
            return undefined;
        const solidFill = directChild$7(spPr, 'a:solidFill');
        if (!solidFill)
            return undefined;
        const srgb = directChild$7(solidFill, 'a:srgbClr');
        if (!srgb)
            return undefined;
        const val = srgb.getAttribute('val');
        return val && /^[0-9A-Fa-f]{6}$/.test(val) ? val.toUpperCase() : undefined;
    }
    /**
     * Sprint 39：解析 `<wps:spPr><a:ln w="..."><a:solidFill><a:srgbClr val="..."/></a:solidFill></a:ln>` 為邊框。
     * `<a:ln><a:noFill/>` 或缺漏 `<a:solidFill>` → undefined。
     * width 從 EMU 換算 Pt。
     */
    function parseShapeBorder(spPr) {
        const ln = directChild$7(spPr, 'a:ln');
        if (!ln)
            return undefined;
        // `<a:ln><a:noFill/>` → 不畫
        if (directChild$7(ln, 'a:noFill'))
            return undefined;
        const solidFill = directChild$7(ln, 'a:solidFill');
        if (!solidFill)
            return undefined;
        const srgb = directChild$7(solidFill, 'a:srgbClr');
        if (!srgb)
            return undefined;
        const colorVal = srgb.getAttribute('val');
        if (!colorVal || !/^[0-9A-Fa-f]{6}$/.test(colorVal))
            return undefined;
        const wRaw = ln.getAttribute('w');
        // OOXML 預設線寬若無 w → 0.75pt（9525 EMU）；缺漏給 0 視為不畫
        const wEmu = wRaw ? parseInt(wRaw, 10) : 9525;
        if (!Number.isFinite(wEmu) || wEmu <= 0)
            return undefined;
        return {
            width: emuToPt(wEmu),
            color: colorVal.toUpperCase(),
        };
    }
    // ── 共用：尺寸 / altText / blip rId ──────────────────────────────────────────
    function parseExtent(el) {
        const extent = directChild$7(el, 'wp:extent');
        if (!extent)
            return { width: 0, height: 0 };
        const cx = parseInt(extent.getAttribute('cx') ?? '0', 10);
        const cy = parseInt(extent.getAttribute('cy') ?? '0', 10);
        return {
            width: Number.isFinite(cx) ? emuToPt(cx) : 0,
            height: Number.isFinite(cy) ? emuToPt(cy) : 0,
        };
    }
    function parseAltText(el) {
        const docPr = directChild$7(el, 'wp:docPr');
        if (!docPr)
            return undefined;
        return docPr.getAttribute('descr') ?? docPr.getAttribute('title') ?? undefined;
    }
    function findBlipEmbed(el) {
        const blips = el.getElementsByTagName('a:blip');
        if (blips.length === 0)
            return undefined;
        const blip = blips[0];
        return (blip.getAttribute('r:embed') ??
            blip.getAttribute('embed') ??
            undefined);
    }
    const POS_H_RELATIVE = [
        'margin',
        'page',
        'column',
        'character',
        'leftMargin',
        'rightMargin',
        'insideMargin',
        'outsideMargin',
    ];
    const POS_V_RELATIVE = [
        'margin',
        'page',
        'paragraph',
        'line',
        'topMargin',
        'bottomMargin',
        'insideMargin',
        'outsideMargin',
    ];
    const POS_H_ALIGN = ['left', 'right', 'center', 'inside', 'outside'];
    const POS_V_ALIGN = ['top', 'bottom', 'center', 'inside', 'outside'];
    function parsePositionH(el) {
        const relRaw = el?.getAttribute('relativeFrom') ?? 'column';
        const relativeFrom = POS_H_RELATIVE.includes(relRaw)
            ? relRaw
            : 'column';
        const out = { relativeFrom };
        if (!el)
            return out;
        const alignEl = directChild$7(el, 'wp:align');
        if (alignEl) {
            const txt = (alignEl.textContent ?? '').trim();
            if (POS_H_ALIGN.includes(txt)) {
                out.align = txt;
            }
        }
        const offsetEl = directChild$7(el, 'wp:posOffset');
        if (offsetEl) {
            const n = parseInt((offsetEl.textContent ?? '0').trim(), 10);
            if (Number.isFinite(n))
                out.posOffset = emuToPt(n);
        }
        return out;
    }
    function parsePositionV(el) {
        const relRaw = el?.getAttribute('relativeFrom') ?? 'paragraph';
        const relativeFrom = POS_V_RELATIVE.includes(relRaw)
            ? relRaw
            : 'paragraph';
        const out = { relativeFrom };
        if (!el)
            return out;
        const alignEl = directChild$7(el, 'wp:align');
        if (alignEl) {
            const txt = (alignEl.textContent ?? '').trim();
            if (POS_V_ALIGN.includes(txt)) {
                out.align = txt;
            }
        }
        const offsetEl = directChild$7(el, 'wp:posOffset');
        if (offsetEl) {
            const n = parseInt((offsetEl.textContent ?? '0').trim(), 10);
            if (Number.isFinite(n))
                out.posOffset = emuToPt(n);
        }
        return out;
    }
    // ── wrap type 偵測 ────────────────────────────────────────────────────────────
    function detectWrapType(el) {
        for (const child of directChildren$b(el)) {
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
    // ── fallback ──────────────────────────────────────────────────────────────────
    function makeFallbackImage() {
        return { type: 'inlineImage', rId: '', width: 0, height: 0 };
    }
    // ── 共用工具 ──────────────────────────────────────────────────────────────────
    function directChildren$b(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild$7(el, tagName) {
        for (const child of directChildren$b(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }

    /**
     * DOM 走訪共用工具
     *
     * 集中放跨 Parser 共用的 DOM helper，避免每個檔案重複定義。
     *
     * 主要 API：
     *   - directChildren(el)：取直接子 Element（過濾 text node / comment）
     *   - directChild(el, tag)：取首個指定 tagName 的直接子 Element
     *   - effectiveChildren(el)：directChildren 但展開 <mc:AlternateContent>
     *
     * 為什麼要 effectiveChildren：
     *   Word 365 產出常含 <mc:AlternateContent>：
     *     <mc:AlternateContent>
     *       <mc:Choice Requires="...">新版內容</mc:Choice>
     *       <mc:Fallback>舊版相容內容</mc:Fallback>
     *     </mc:AlternateContent>
     *   Parser 應優先讀 <mc:Choice>；若無 Choice 子元素，讀 <mc:Fallback>。
     *   此函式把 AlternateContent 包裝層展開，讓上層 walker 直接看到「實際內容子元素」。
     *   也支援巢狀 AlternateContent（雖極罕見）。
     */
    /** 直接 Element 子節點（過濾 text/comment 等非 Element 子節點）。 */
    function directChildren$a(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    /** 找首個指定 tagName 的直接子 Element。 */
    function directChild$6(el, tagName) {
        for (const child of directChildren$a(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    /**
     * 直接 Element 子節點，但 mc:AlternateContent 子層自動展開。
     *
     * 展開規則：
     *   - 若直接子是 mc:AlternateContent：
     *       - 優先取其 mc:Choice 子元素的子節點（多個 Choice 取第一個）
     *       - 若無 Choice，取 mc:Fallback 子元素的子節點
     *       - 兩者都無時跳過此 AlternateContent
     *   - 其餘子節點原樣保留
     *   - 展開後若還含 mc:AlternateContent（巢狀），再遞迴展開
     *
     * @example
     *   <w:r>
     *     <mc:AlternateContent>
     *       <mc:Choice Requires="wps">  <newDrawing/>  </mc:Choice>
     *       <mc:Fallback>              <oldPict/>     </mc:Fallback>
     *     </mc:AlternateContent>
     *     <w:t>after</w:t>
     *   </w:r>
     *   →  effectiveChildren(<w:r>) = [<newDrawing/>, <w:t>after</w:t>]
     */
    function effectiveChildren(el) {
        const out = [];
        for (const child of directChildren$a(el)) {
            if (child.tagName === 'mc:AlternateContent') {
                // 優先 Choice，否則 Fallback
                const choice = directChild$6(child, 'mc:Choice');
                const fallback = directChild$6(child, 'mc:Fallback');
                const target = choice ?? fallback;
                if (target) {
                    // 遞迴展開：target 內可能再有 AlternateContent
                    out.push(...effectiveChildren(target));
                }
                // Choice 與 Fallback 都無時：跳過此 AlternateContent
            }
            else if (child.tagName === 'w:sdt') {
                // Sprint 124 — SDT 結構化文件標籤透明展開（ECMA-376 §17.5.2）
                // `<w:sdt>` 包 `<w:sdtPr>` (metadata) + `<w:sdtContent>` (actual content)。
                // 我們不渲染 sdtPr 的 alias / tag / form control type、純取 sdtContent
                // 子節點 inline 到父級（block-level / inline-level / cell-level 都適用）。
                // 遞迴展開 sdtContent（OOXML 允許 sdt 嵌套，且 sdtContent 內可能再含
                // AlternateContent 或 sdt）。
                const sdtContent = directChild$6(child, 'w:sdtContent');
                if (sdtContent) {
                    out.push(...effectiveChildren(sdtContent));
                }
                // sdtContent 缺失（malformed docx）→ 此 sdt 不貢獻內容、跳過
            }
            else {
                out.push(child);
            }
        }
        return out;
    }
    /** 取屬性，無屬性時回 undefined（簡化 null/string 二元判斷）。 */
    function attr$2(el, name) {
        if (!el)
            return undefined;
        const v = el.getAttribute(name);
        return v === null ? undefined : v;
    }

    /**
     * ThemeResolver — 解析 word/theme/theme1.xml 為 ThemeMap
     *
     * 提供：
     *   - parseTheme(pkg) → ThemeMap | null（缺檔回 null，不 throw）
     *   - resolveThemeColor(theme, themeColor, tint?, shade?) → HexColor
     *
     * 為何有此模組：
     *   <w:color w:themeColor="accent1" w:themeTint="80"/> 在 ParagraphParser 階段
     *   只能讀到 themeColor reference；要轉成具體 hex 必須查 theme1.xml 的 colorScheme
     *   並套用 tint/shade 演算法。
     *
     * 設計決策（ADR-012 補 + Sprint 130 升級）：
     *   - eager resolve：parser 階段就把 themeColor → hex 寫回 RunProps.color，
     *     mapper / renderer 不用再查 theme（簡化下游邏輯，但失去原 themeColor 識別）
     *   - tint/shade 演算法：**Sprint 130 升級為 HSL luminance**（規畫書 §Phase 4.1）。
     *     原 Sprint 1-129 用 RGB linear blend（對 mid-saturation 色差異 < 5pp、但對
     *     vivid 色如 dark navy 會 wash out hue）。HSL 版本保留 hue+saturation、只調 L。
     *     極端值 tint=FF/shade=FF 仍回 white/black（與舊版相容）。
     *   - 缺檔降級：parseTheme 回 null，caller 需自行決定是否用 DEFAULT_THEME_MAP
     *
     * 規格參考：
     *   - ECMA-376 Part 1 §20.1.6.5 (themeElements)
     *   - ECMA-376 Part 1 §20.1.6.2 (clrScheme)
     *   - ECMA-376 Part 1 §17.18.40 (themeColor)
     *   - ECMA-376 Part 1 §17.18.97 (themeTint) / §17.18.85 (themeShade)
     */
    /**
     * Office 預設 theme 顏色（accent1~6 為 Office 2007 default scheme）。
     * 用於 theme1.xml 缺檔或 colorScheme 不完整時降級。
     */
    const DEFAULT_THEME_COLORS = {
        dk1: '000000',
        lt1: 'FFFFFF',
        dk2: '1F497D',
        lt2: 'EEECE1',
        accent1: '4F81BD',
        accent2: 'C0504D',
        accent3: '9BBB59',
        accent4: '8064A2',
        accent5: '4BACC6',
        accent6: 'F79646',
        hlink: '0000FF',
        folHlink: '800080',
    };
    const DEFAULT_THEME_FONTS = {
        major: { latin: 'Cambria' },
        minor: { latin: 'Calibri' },
    };
    const DEFAULT_THEME_MAP = {
        colorScheme: DEFAULT_THEME_COLORS,
        fontScheme: DEFAULT_THEME_FONTS,
    };
    /**
     * 從 OOXML package 解析 theme1.xml。
     * 缺檔或解析失敗時回 null（caller 用 DEFAULT_THEME_MAP 降級）。
     */
    function parseTheme(pkg) {
        const xml = pkg.partAsText('word/theme/theme1.xml');
        if (!xml)
            return null;
        let doc;
        try {
            doc = new DOMParser().parseFromString(xml, 'application/xml');
        }
        catch {
            return null;
        }
        const root = doc.documentElement;
        if (!root)
            return null;
        const themeElements = directChild$6(root, 'a:themeElements');
        if (!themeElements)
            return null;
        const clrSchemeEl = directChild$6(themeElements, 'a:clrScheme');
        const fontSchemeEl = directChild$6(themeElements, 'a:fontScheme');
        return {
            colorScheme: clrSchemeEl ? parseColorScheme(clrSchemeEl) : { ...DEFAULT_THEME_COLORS },
            fontScheme: fontSchemeEl ? parseFontScheme(fontSchemeEl) : { major: { ...DEFAULT_THEME_FONTS.major }, minor: { ...DEFAULT_THEME_FONTS.minor } },
        };
    }
    function parseColorScheme(el) {
        const out = { ...DEFAULT_THEME_COLORS };
        const keys = [
            'dk1', 'lt1', 'dk2', 'lt2',
            'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6',
            'hlink', 'folHlink',
        ];
        for (const key of keys) {
            const child = directChild$6(el, `a:${key}`);
            if (!child)
                continue;
            const hex = readClrValue(child);
            if (hex)
                out[key] = hex;
        }
        return out;
    }
    /** 從 <a:srgbClr val="HEX"/> 或 <a:sysClr lastClr="HEX"/> 取 hex */
    function readClrValue(parent) {
        const srgb = directChild$6(parent, 'a:srgbClr');
        if (srgb) {
            const v = attr$2(srgb, 'val');
            return v ? v.toUpperCase() : null;
        }
        const sys = directChild$6(parent, 'a:sysClr');
        if (sys) {
            const v = attr$2(sys, 'lastClr') || attr$2(sys, 'val');
            if (!v)
                return null;
            // sysClr val 可能是 'windowText'/'window' 等識別字；此時用 lastClr
            if (/^[0-9A-Fa-f]{6}$/.test(v))
                return v.toUpperCase();
            return null;
        }
        return null;
    }
    function parseFontScheme(el) {
        const out = {
            major: { ...DEFAULT_THEME_FONTS.major },
            minor: { ...DEFAULT_THEME_FONTS.minor },
        };
        const major = directChild$6(el, 'a:majorFont');
        const minor = directChild$6(el, 'a:minorFont');
        if (major) {
            out.major.latin = attr$2(directChild$6(major, 'a:latin'), 'typeface') || out.major.latin;
            out.major.ea = attr$2(directChild$6(major, 'a:ea'), 'typeface') || undefined;
            out.major.cs = attr$2(directChild$6(major, 'a:cs'), 'typeface') || undefined;
        }
        if (minor) {
            out.minor.latin = attr$2(directChild$6(minor, 'a:latin'), 'typeface') || out.minor.latin;
            out.minor.ea = attr$2(directChild$6(minor, 'a:ea'), 'typeface') || undefined;
            out.minor.cs = attr$2(directChild$6(minor, 'a:cs'), 'typeface') || undefined;
        }
        return out;
    }
    /**
     * Word 的 themeColor 識別字 → clrScheme key 對應表。
     * 規格 ECMA-376 §17.18.40。
     */
    const THEME_COLOR_MAP = {
        // 標準名稱
        background1: 'lt1',
        background2: 'lt2',
        text1: 'dk1',
        text2: 'dk2',
        accent1: 'accent1',
        accent2: 'accent2',
        accent3: 'accent3',
        accent4: 'accent4',
        accent5: 'accent5',
        accent6: 'accent6',
        hyperlink: 'hlink',
        followedHyperlink: 'folHlink',
        // 早期版本 Word 有時用這組
        dark1: 'dk1',
        dark2: 'dk2',
        light1: 'lt1',
        light2: 'lt2',
    };
    /**
     * 把 themeColor reference + tint/shade 解析為具體 hex。
     *
     * @param theme       已解析的 ThemeMap
     * @param themeColor  Word 的 themeColor 識別字（如 "accent1"、"text2"）
     * @param tint        themeTint 屬性 hex 0x00–0xFF（變亮量）
     * @param shade       themeShade 屬性 hex 0x00–0xFF（變暗量）
     * @returns 6-hex color（無效 themeColor 回 "000000"）
     *
     * @example
     *   resolveThemeColor(theme, 'accent1', '80')   // 50% 變亮的 accent1
     *   resolveThemeColor(theme, 'text2', undefined, 'CC')  // 80% 變暗的 text2
     */
    function resolveThemeColor(theme, themeColor, tint, shade) {
        const colorKey = THEME_COLOR_MAP[themeColor];
        if (!colorKey)
            return '000000';
        let base = theme.colorScheme[colorKey];
        if (tint !== undefined && tint !== '') {
            base = applyTint(base, parseHexByte(tint));
        }
        else if (shade !== undefined && shade !== '') {
            base = applyShade(base, parseHexByte(shade));
        }
        return base;
    }
    /**
     * Tint = 把顏色亮度往 1.0（白）推；t 為 0..1 比例。
     *
     * HSL luminance 演算法（OOXML §20.1.2.3.20、規畫書 §Phase 4.1）：
     *   L_new = L * (1 - t) + 1.0 * t  →  L + (1 - L) * t
     * 保留 hue 與 saturation、只調 L，避免 vivid 色被 wash out 成 gray-pastel。
     *
     * 極端值：t=0 不變色；t=1 → L_new=1.0 → 純白（與舊 RGB linear 版相容）。
     */
    function applyTint(hex, t) {
        const tt = clamp01(t);
        const [r, g, b] = hexToRgb(hex);
        const [h, s, l] = rgbToHsl(r, g, b);
        const lNew = l + (1 - l) * tt;
        const [nr, ng, nb] = hslToRgb(h, s, lNew);
        return rgbToHex([Math.round(nr), Math.round(ng), Math.round(nb)]);
    }
    /**
     * Shade = 把顏色亮度往 0.0（黑）推；s 為 0..1 比例。
     *
     * HSL luminance 演算法（OOXML §20.1.2.3.20、規畫書 §Phase 4.1）：
     *   L_new = L * (1 - s)
     * 保留 hue 與 saturation、只調 L。
     *
     * 極端值：s=0 不變色；s=1 → L_new=0 → 純黑（與舊 RGB linear 版相容）。
     */
    function applyShade(hex, s) {
        const ss = clamp01(s);
        const [r, g, b] = hexToRgb(hex);
        const [h, sat, l] = rgbToHsl(r, g, b);
        const lNew = l * (1 - ss);
        const [nr, ng, nb] = hslToRgb(h, sat, lNew);
        return rgbToHex([Math.round(nr), Math.round(ng), Math.round(nb)]);
    }
    /**
     * RGB → HSL 轉換（標準公式，rgb 為 0..255，回傳 h:0..1, s:0..1, l:0..1）。
     * 灰階（max==min）回 h=0、s=0。
     */
    function rgbToHsl(r, g, b) {
        const rn = r / 255;
        const gn = g / 255;
        const bn = b / 255;
        const max = Math.max(rn, gn, bn);
        const min = Math.min(rn, gn, bn);
        const l = (max + min) / 2;
        if (max === min) {
            return [0, 0, l]; // 灰階：無 hue、無 saturation
        }
        const d = max - min;
        const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        let h;
        switch (max) {
            case rn:
                h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
                break;
            case gn:
                h = ((bn - rn) / d + 2) / 6;
                break;
            default:
                h = ((rn - gn) / d + 4) / 6;
                break;
        }
        return [h, s, l];
    }
    /**
     * HSL → RGB 轉換（標準公式，h/s/l 為 0..1，回傳 rgb 0..255 浮點，caller 自行 round）。
     */
    function hslToRgb(h, s, l) {
        const lc = clamp01(l);
        const sc = clamp01(s);
        if (sc === 0) {
            const v = lc * 255;
            return [v, v, v]; // 灰階：r=g=b=L
        }
        const q = lc < 0.5 ? lc * (1 + sc) : lc + sc - lc * sc;
        const p = 2 * lc - q;
        const hMod = ((h % 1) + 1) % 1; // 包進 0..1
        return [
            hueToRgb(p, q, hMod + 1 / 3) * 255,
            hueToRgb(p, q, hMod) * 255,
            hueToRgb(p, q, hMod - 1 / 3) * 255,
        ];
    }
    function hueToRgb(p, q, t) {
        let tt = t;
        if (tt < 0)
            tt += 1;
        if (tt > 1)
            tt -= 1;
        if (tt < 1 / 6)
            return p + (q - p) * 6 * tt;
        if (tt < 1 / 2)
            return q;
        if (tt < 2 / 3)
            return p + (q - p) * (2 / 3 - tt) * 6;
        return p;
    }
    /** 把 OOXML 的 hex byte（"00"–"FF"）正規化為 0..1 */
    function parseHexByte(hex) {
        const v = parseInt(hex, 16);
        if (Number.isNaN(v))
            return 0;
        return Math.max(0, Math.min(255, v)) / 255;
    }
    function clamp01(x) {
        return Math.max(0, Math.min(1, x));
    }
    function hexToRgb(hex) {
        const h = hex.replace('#', '').padStart(6, '0').toUpperCase();
        return [
            parseInt(h.slice(0, 2), 16),
            parseInt(h.slice(2, 4), 16),
            parseInt(h.slice(4, 6), 16),
        ];
    }
    function rgbToHex(rgb) {
        return rgb
            .map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0').toUpperCase())
            .join('');
    }

    /**
     * colorResolver — 統一處理 <w:color> 元素 → hex 解析（含 themeColor）
     *
     * Word 的 <w:color> 元素三種寫法：
     *   1. <w:color w:val="FF0000"/>             → 直接 hex
     *   2. <w:color w:val="auto"/>               → 系統預設（黑色）
     *   3. <w:color w:themeColor="accent1"
     *               w:themeTint="80"/>           → theme reference + tint
     *
     * 此 helper 把三種統一回傳 6-hex；無 ThemeMap 或無法解析時降級為 undefined。
     *
     * 使用情境：
     *   - ParagraphParser.parseRunProps 對 <w:color> 子元素呼叫
     *   - StyleResolver.flattenStyle 對 <w:color> 子元素呼叫
     *   - 未來 BorderConflictResolver 對 <w:tcBorders> / <w:tblBorders> 內每邊呼叫
     */
    /**
     * 從 <w:color w:val="..." w:themeColor="..." w:themeTint="..." w:themeShade="..."/>
     * 取出最終 hex color。
     *
     * @param colorEl  `<w:color>` Element（可能 undefined）
     * @param theme    ThemeMap（可能 null，無 theme 時不解析 themeColor）
     * @returns 6-hex；找不到合法值回 undefined
     */
    function resolveColorElement(colorEl, theme) {
        if (!colorEl)
            return undefined;
        const val = attr$2(colorEl, 'w:val');
        // val="auto" 表示自動色（系統預設，通常黑）；不視為明確指定
        if (val && val.toLowerCase() !== 'auto' && /^[0-9A-Fa-f]{6}$/.test(val)) {
            return val.toUpperCase();
        }
        const themeColor = attr$2(colorEl, 'w:themeColor');
        if (themeColor && theme) {
            const tint = attr$2(colorEl, 'w:themeTint');
            const shade = attr$2(colorEl, 'w:themeShade');
            return resolveThemeColor(theme, themeColor, tint, shade);
        }
        return undefined;
    }

    /**
     * borderShading — 共用的 `<w:bdr>` / `<w:tcBorders>` / `<w:tblBorders>` / `<w:pBdr>`
     * 邊框解析 + `<w:shd>` 陰影解析 utility（Sprint 133 從 TableParser 抽出）。
     *
     * 由 TableParser（cell/table borders + cell shading）、ParagraphParser（pBdr + shd）、
     * 未來 BorderConflictResolver 共用。集中後 BorderDef shape 變更只需一處同步。
     *
     * 參考：
     *   - ECMA-376 Part 1 §17.4.65 (tblBorders) / §17.4.66 (tcBorders) / §17.3.1.24 (pBdr)
     *   - ECMA-376 Part 1 §17.18.97 (shd)
     *   - 單位：w:sz 為 1/8 pt（eighthPointToPt）；w:space 為 pt 整數
     */
    /**
     * 解析單一邊 `<w:top>` / `<w:bottom>` / `<w:left>` / `<w:right>` / `<w:insideH>` / ... 為 BorderDef。
     *
     * - `w:val` 缺則回 undefined（OOXML 規範：無 val 視為「不指定」）
     * - `w:sz` 缺則 width = 0（仍視為合法 border，由 caller 判斷是否渲染）
     * - `w:color="auto"` 保留為字面值 'auto'、不轉成具體 hex（caller 決定 default）
     * - `w:space` 缺則回 undefined（不掛 key）
     *
     * @param el 邊框子元素（`<w:top>` 等）
     * @returns BorderDef 或 undefined（無 val）
     */
    function parseBorderDef(el) {
        const valRaw = el.getAttribute('w:val');
        if (!valRaw)
            return undefined;
        const style = valRaw;
        let width = 0;
        const szRaw = el.getAttribute('w:sz');
        if (szRaw !== null) {
            const n = parseInt(szRaw, 10);
            if (Number.isFinite(n))
                width = eighthPointToPt(n);
        }
        const colorRaw = el.getAttribute('w:color');
        const color = colorRaw ?? 'auto';
        const out = { style, width, color };
        const spaceRaw = el.getAttribute('w:space');
        if (spaceRaw !== null) {
            const n = parseInt(spaceRaw, 10);
            if (Number.isFinite(n))
                out.space = n;
        }
        return out;
    }
    /**
     * 解析 `<w:shd w:val="clear" w:fill="DEEAF6" w:color="auto"/>` 為 shading 物件。
     *
     * - 三屬性都缺則 caller 拿到空物件、自行決定是否視為「無 shading」
     * - 'auto' 保留為字面值（與 parseBorderDef 一致）
     *
     * @param el `<w:shd>` 元素
     * @returns shading 物件（含 fill / color / pattern，缺則該 key 不掛）
     */
    function parseShading(el) {
        const out = {};
        const fill = el.getAttribute('w:fill');
        const color = el.getAttribute('w:color');
        const pattern = el.getAttribute('w:val');
        if (fill)
            out.fill = fill;
        if (color)
            out.color = color;
        if (pattern)
            out.pattern = pattern;
        return out;
    }
    /**
     * 解析段落邊框 `<w:pBdr>` 為 ParagraphProps.borders 子集（top / bottom / left / right）。
     *
     * Sprint 133 起 ParagraphParser 用此 helper；
     * 與 cell/table borders 共用 parseBorderDef 但段落邊框只有 4 邊（無 insideH/insideV）。
     *
     * @param pBdr `<w:pBdr>` 元素
     * @returns borders 物件（缺邊則該 key 不掛；全空回 undefined）
     */
    function parseParagraphBorders(pBdr) {
        const out = {};
        for (const child of directChildren$9(pBdr)) {
            const def = parseBorderDef(child);
            if (!def)
                continue;
            switch (child.tagName) {
                case 'w:top':
                    out.top = def;
                    break;
                case 'w:bottom':
                    out.bottom = def;
                    break;
                case 'w:left':
                case 'w:start':
                    out.left = def;
                    break;
                case 'w:right':
                case 'w:end':
                    out.right = def;
                    break;
                // 注意：段落 w:pBdr 也可包 between / bar，但這兩種屬「段落間 / 邊欄」
                // 不對應 ParagraphProps.borders 4 邊；defer 未來 sprint
            }
        }
        if (!out.top && !out.bottom && !out.left && !out.right)
            return undefined;
        return out;
    }
    /** 內部：直接子節點（Element）走訪。獨立於 dom.ts 避免 cross-layer dependency */
    function directChildren$9(el) {
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }

    /**
     * OmmlParser — 解析 OMML 數學公式（`m:` 命名空間、ECMA-376 §22.1、Phase 5.1）
     *
     * Sprint 179（capture）：
     *   Word 數學公式（「插入 → 方程式」）以 OMML（Office Math Markup Language）儲存，
     *   內嵌於 document.xml 的段落中：
     *     - 段落直屬 `<m:oMath>`                    → 行內公式（inline math）
     *     - 段落直屬 `<m:oMathPara><m:oMath>...`     → 獨立置中公式（display math）
     *
     *   OMML 結構元素（部分）：
     *     <m:f>   分數（<m:num> 分子 / <m:den> 分母）
     *     <m:rad> 根號（<m:deg> 次數 / <m:e> 被開方數）
     *     <m:nary> n 元運算子（求和 / 積分；<m:sub> 下限 / <m:sup> 上限 / <m:e> 主體）
     *     <m:sSub> / <m:sSup> / <m:sSubSup>  下標 / 上標 / 上下標
     *     <m:d>   括號分隔符（delimiter）
     *     <m:m>   矩陣（<m:mr> 列 / <m:e> 格）
     *     <m:r>   math run（含 <m:t> 文字）
     *
     * Sprint 179 以遞迴通用樹（OmmlNode）保留完整結構；Sprint 180 補 attrs 捕捉 +
     * `ommlToLinearText` 線性文字 fallback render（OMML → KaTeX 全保真留未來 optional）。
     *
     * 防禦：undefined / 無子元素 → 回空陣列 / 空字串（不 throw）。
     */
    /** OMML 命名空間前綴。 */
    const MATH_NS_PREFIX = 'm:';
    /** OMML 文字葉節點標籤（去前綴後）。 */
    const MATH_TEXT_TAG = 't';
    /** OOXML §22.1.2.70：`<m:nary>` 的 `m:chr` 屬性預設值（積分符號 U+222B）。 */
    const NARY_DEFAULT_CHAR = '∫';
    /** `<m:d>` delimiter 的預設左右括號（OOXML §22.1.2.21/§22.1.2.36）。 */
    const DELIM_DEFAULT_BEG = '(';
    const DELIM_DEFAULT_END = ')';
    /**
     * 把 OOXML 標籤名 / 屬性名去掉 `m:` 命名空間前綴，回傳 localName。
     * 無前綴則原樣回傳。
     */
    function stripMathPrefix(name) {
        return name.startsWith(MATH_NS_PREFIX) ? name.slice(MATH_NS_PREFIX.length) : name;
    }
    /**
     * 收集元素的屬性 → Record（key 去 `m:` 前綴）。無屬性回 undefined（紀律 #21）。
     */
    function collectAttrs(el) {
        const attrs = {};
        let has = false;
        const list = el.attributes;
        for (let i = 0; i < list.length; i++) {
            const a = list[i];
            if (a.name.startsWith('xmlns'))
                continue; // 跳過命名空間宣告
            attrs[stripMathPrefix(a.name)] = a.value;
            has = true;
        }
        return has ? attrs : undefined;
    }
    /**
     * 遞迴解析 OMML 元素的子節點為 OmmlNode 樹。
     *
     * @param el `<m:oMath>` 或任一 OMML 結構元素
     * @returns 子節點的 OmmlNode 陣列；無元素子節點 → 空陣列
     */
    function parseOmmlChildren(el) {
        if (!el)
            return [];
        const out = [];
        for (const child of directChildren$a(el)) {
            const tag = stripMathPrefix(child.tagName);
            const node = { tag };
            const attrs = collectAttrs(child);
            if (attrs)
                node.attrs = attrs;
            if (tag === MATH_TEXT_TAG) {
                // `<m:t>` 為文字葉節點（OOXML §22.1.2.116）
                node.text = child.textContent ?? '';
            }
            else {
                const kids = parseOmmlChildren(child);
                // 紀律 #21：無子節點不掛 key、避免 AST diff noise
                if (kids.length > 0)
                    node.children = kids;
            }
            out.push(node);
        }
        return out;
    }
    // ── Sprint 180：線性文字 fallback render ─────────────────────────────────────
    /** 找第一個 tag 相符的子節點。 */
    function childByTag(node, tag) {
        return node.children?.find((c) => c.tag === tag);
    }
    /** 取某子節點（依 tag）的線性文字；無此子節點回空字串。 */
    function tagText(node, tag) {
        const c = childByTag(node, tag);
        return c ? linearizeNode(c) : '';
    }
    /**
     * 把單一 OmmlNode 遞迴轉為線性文字。
     *
     * capture-only fallback：不做版面排版，僅以線性符號近似（分數 a/b、根號 √(x)、
     * 上下標 x_(n)^(2)、矩陣 [a, b; c, d]）。全保真排版需 KaTeX、留未來 optional sprint。
     */
    function linearizeNode(node) {
        switch (node.tag) {
            case 't':
                return node.text ?? '';
            case 'r': // math run：拼接內部 <m:t>
            case 'e': // 通用 element 容器
            case 'num':
            case 'den':
            case 'deg':
            case 'sub':
            case 'sup':
            case 'oMath':
                return linearizeChildren(node);
            case 'f': // 分數 num/den
                return `${tagText(node, 'num')}/${tagText(node, 'den')}`;
            case 'rad': { // 根號（deg 可選）
                const deg = tagText(node, 'deg');
                return `${deg}√(${tagText(node, 'e')})`;
            }
            case 'nary': { // n 元運算子（求和 / 積分）
                const chr = childByTag(node, 'naryPr')
                    ? naryChar(childByTag(node, 'naryPr'))
                    : NARY_DEFAULT_CHAR;
                const sub = tagText(node, 'sub');
                const sup = tagText(node, 'sup');
                const body = tagText(node, 'e');
                return `${chr}${sub ? `_(${sub})` : ''}${sup ? `^(${sup})` : ''}(${body})`;
            }
            case 'sSub':
                return `${tagText(node, 'e')}_(${tagText(node, 'sub')})`;
            case 'sSup':
                return `${tagText(node, 'e')}^(${tagText(node, 'sup')})`;
            case 'sSubSup':
                return `${tagText(node, 'e')}_(${tagText(node, 'sub')})^(${tagText(node, 'sup')})`;
            case 'd': { // delimiter 括號
                const pr = childByTag(node, 'dPr');
                const beg = pr?.attrs?.begChr ?? DELIM_DEFAULT_BEG;
                const end = pr?.attrs?.endChr ?? DELIM_DEFAULT_END;
                return `${beg}${linearizeChildren(node)}${end}`;
            }
            case 'm': { // 矩陣：mr 列以 ; 分隔、e 格以 , 分隔
                const rows = (node.children ?? [])
                    .filter((c) => c.tag === 'mr')
                    .map((mr) => (mr.children ?? [])
                    .filter((c) => c.tag === 'e')
                    .map((e) => linearizeNode(e))
                    .join(', '));
                return `[${rows.join('; ')}]`;
            }
            case 'rPr':
            case 'ctrlPr':
            case 'naryPr':
            case 'fPr':
            case 'dPr':
            case 'radPr':
            case 'mPr':
                return ''; // 屬性容器、不產生文字
            default:
                // 未明列的結構元素 → 遞迴拼接子節點（盡力 fallback）
                return linearizeChildren(node);
        }
    }
    /** 從 `<m:naryPr>` 取運算子字元（`<m:chr m:val>`），缺則用預設積分符號。 */
    function naryChar(naryPr) {
        return childByTag(naryPr, 'chr')?.attrs?.val ?? NARY_DEFAULT_CHAR;
    }
    /** 拼接一節點所有子節點的線性文字。 */
    function linearizeChildren(node) {
        return (node.children ?? []).map((c) => linearizeNode(c)).join('');
    }
    /**
     * 把 `<m:oMath>` 的 OmmlNode 樹轉為線性文字 fallback。
     *
     * @param omml `MathNode.omml`（`<m:oMath>` 子元素樹）
     * @returns 線性文字近似；空樹 → 空字串
     */
    function ommlToLinearText(omml) {
        return omml.map((n) => linearizeNode(n)).join('');
    }

    /**
     * ParagraphParser — 解析 <w:p>（段落）與內部 <w:r>（Run）
     *
     * 處理範圍（Sprint 1）：
     *   - w:pPr 段落屬性：jc, ind, spacing, pStyle, numPr, keepNext, pageBreakBefore
     *   - w:rPr Run 屬性：rFonts, sz, b, i, u, strike, color, highlight, vertAlign
     *   - w:t 文字（含 xml:space="preserve" 保留空白）
     *   - w:br type="line|page|column" → BreakNode
     *   - w:tab → 暫時當文字 "\t"
     *   - w:fldSimple instr="..." → FieldNode
     *
     * 設計原則：
     *   - 用 getElementsByTagName(qualifiedName) 而非 getElementsByTagNameNS
     *     （happy-dom 對預設命名空間 NS 查詢有缺陷；此 walker 全環境一致）
     *   - 只處理「直接子節點」，不遞迴尋找（OOXML 結構非 free-form HTML）
     *   - 樣式繼承鏈交給 StyleResolver 在 Sprint 2 處理；本 Parser 只解 in-line 屬性
     *
     * Sprint 1 issue #4 + #5 + #6
     */
    const drawingParser = new DrawingParser();
    /**
     * Sprint 38：module-level「目前正在解析的 ParagraphParser 實例」reference。
     *
     * 由 ParagraphParser.parse() 在入口處 push、出口處 pop，讓 module-level 函式
     * （parseRun）可以回呼到目前實例（保留 relsLookup / themeMap 等狀態）。
     *
     * 用於 anchor text box (`<wp:anchor><wps:wsp><wps:txbx><w:txbxContent>`) 遞迴解析
     * 內部 `<w:p>`：DrawingParser.parse 接受 paragraphFactory callback。
     */
    let currentParagraphParser = null;
    /**
     * Module-scoped ThemeMap，由 setThemeMapForParser() / ParagraphParser.setThemeMap 賦值。
     * parseRunProps / parseParagraphProps 為 named export（不在 class），
     * 此中介變數允許 module-level 函式存取 ThemeMap 而不需重整 API。
     *
     * 對外 named export `setThemeMapForParser` 讓 StyleResolver、test 等其他位置也能直接設定。
     */
    let themeMapForParser = null;
    function setThemeMapForParser(theme) {
        themeMapForParser = theme;
    }
    // ── 對外 ──────────────────────────────────────────────────────────────────────
    class ParagraphParser {
        /**
         * 注入 rels 查詢函式。
         *
         * @example
         *   parser.setRelsLookup((rId) => pkg.relationships.get('word/document.xml')?.get(rId)
         *     ?.targetMode === 'External' ? rels.get(rId).target : undefined);
         */
        setRelsLookup(fn) {
            this.relsLookup = fn;
        }
        /**
         * Phase 4.1：設定 ThemeMap（給 parseRunProps / parseParagraphProps 用以解 themeColor）
         *
         * parseRunProps 是 module-level named export（Phase B+ ADR-008.4），無法直接
         * 從 class state 讀；所以用 module-scoped variable themeMapForParser 中介，
         * 由此 setter 賦值。
         */
        setThemeMap(theme) {
            setThemeMapForParser(theme);
        }
        /**
         * 解析單一 <w:p> Element 為 ParagraphNode。
         * @param p w:p 元素（已是 DOM Element）
         */
        parse(p) {
            // Sprint 38：把自己 push 到 module-level current 變數，讓 parseRun 在處理
            // `<w:drawing>` 時能回呼到本實例（保留 relsLookup / themeMap 狀態）。
            // 用 try/finally 確保 nested 呼叫 ( anchor text box 內 paragraph) 正確 push/pop。
            const prevParser = currentParagraphParser;
            currentParagraphParser = this;
            try {
                return this._parseInternal(p);
            }
            finally {
                currentParagraphParser = prevParser;
            }
        }
        _parseInternal(p) {
            const pPrEl = directChild$5(p, 'w:pPr');
            const props = pPrEl ? parseParagraphProps(pPrEl) : {};
            const styleId = pPrEl
                ? attr$1(directChild$5(pPrEl, 'w:pStyle'), 'w:val')
                : undefined;
            const runs = [];
            // Sprint 123：複式 field 跨多 w:r 的 state machine。
            // OOXML §17.16.1.7 fldChar：begin → [instrText...] → separate → [w:t...] → end
            // 三段可分屬不同 w:r、必須在 paragraph 層收集。
            // - mode='instr'：收集 instrText 串到 instruction
            // - mode='cached'：收集 w:t 串到 cachedValue
            // - 嵌套不支援（規畫書 §1.9 未列）；遇 nested begin 不嘗試處理、視為 unknown
            let fieldMode = null;
            let fieldInstr = '';
            let fieldCached = '';
            const emitField = () => {
                if (fieldMode === null && fieldInstr === '' && fieldCached === '')
                    return;
                const node = {
                    type: 'field',
                    instruction: fieldInstr.trim(),
                    fieldType: classifyFieldType(fieldInstr),
                };
                if (fieldCached)
                    node.cachedValue = fieldCached;
                runs.push(node);
                fieldMode = null;
                fieldInstr = '';
                fieldCached = '';
            };
            // Sprint 125：bookmark 名稱收集（段落直屬 + run 內含）
            // ECMA-376 §17.13.6：`<w:bookmarkStart w:id="N" w:name="...">` / `<w:bookmarkEnd w:id="N"/>`
            // 不影響 render（純錨點），但需 capture name 供未來 hyperlink anchor 反查、PDF 內部跳轉。
            const bookmarkNames = new Set();
            // Sprint 177：此段落引用的註解 id（`<w:commentReference w:id>` + `<w:commentRangeStart w:id>`）
            const commentIds = new Set();
            // Sprint 179（Phase 5.1 OMML）：此段落內的數學公式（capture-only、行內 + display）
            const mathNodes = [];
            // 掃單一 w:r 的子元素、收集 bookmark 名稱（Sprint 125）與 commentReference id（Sprint 177）
            const collectRunAnchors = (r) => {
                for (const c of directChildren$8(r)) {
                    if (c.tagName === 'w:bookmarkStart') {
                        const name = c.getAttribute('w:name');
                        if (name)
                            bookmarkNames.add(name);
                    }
                    else if (c.tagName === 'w:commentReference') {
                        const id = parseInt(c.getAttribute('w:id') ?? '', 10);
                        if (Number.isFinite(id))
                            commentIds.add(id);
                    }
                    // bookmarkEnd 不帶 name、不收集
                }
            };
            for (const child of effectiveChildren(p)) {
                switch (child.tagName) {
                    case 'w:r': {
                        // Sprint 125：先收集 run 內 bookmark（即使後續走 field path）
                        collectRunAnchors(child);
                        // Sprint 123：field state machine 入口
                        //   - 已在 field 模式 → 全交給 consumeRunIntoField（含 separate / end 切換）
                        //   - 未在 field 模式但 r 內含 fldChar begin → 同樣交給 consumeRunIntoField
                        //     （consume 內部會 setMode('instr') 並接後續 instrText / 切換信號）
                        const inField = fieldMode !== null;
                        const beginFound = !inField && detectFieldBegin(child);
                        if (inField || beginFound) {
                            consumeRunIntoField(child, () => fieldMode, (m) => { fieldMode = m; }, (s) => { fieldInstr += s; }, (s) => { fieldCached += s; }, emitField);
                            break;
                        }
                        for (const node of parseRun(child))
                            runs.push(node);
                        break;
                    }
                    case 'w:fldSimple':
                        runs.push(parseFldSimple(child));
                        break;
                    case 'w:hyperlink': {
                        const linkInfo = parseHyperlinkInfo(child, this.relsLookup);
                        // hyperlink 內含 w:r，視同包裹 — 展平 runs 並標記 hyperlink 資訊
                        for (const r of effectiveChildren(child)) {
                            if (r.tagName !== 'w:r')
                                continue;
                            collectRunAnchors(r); // Sprint 125：hyperlink 內 w:r 也掃 bookmark
                            for (const node of parseRun(r)) {
                                if (linkInfo && node.type === 'run') {
                                    node.hyperlink = linkInfo;
                                }
                                runs.push(node);
                            }
                        }
                        break;
                    }
                    case 'w:bookmarkStart': {
                        // Sprint 125：段落直屬 bookmarkStart（w:r 同層）
                        const name = child.getAttribute('w:name');
                        if (name)
                            bookmarkNames.add(name);
                        break;
                    }
                    case 'w:bookmarkEnd':
                        // bookmarkEnd 純結尾標記、無 name、無內容、不影響 runs
                        break;
                    case 'w:commentRangeStart': {
                        // Sprint 177：段落直屬註解範圍起點 `<w:commentRangeStart w:id>`
                        const id = parseInt(child.getAttribute('w:id') ?? '', 10);
                        if (Number.isFinite(id))
                            commentIds.add(id);
                        break;
                    }
                    case 'w:commentRangeEnd':
                        // commentRangeEnd 純結尾標記、id 與 Start 相同、不重複收集
                        break;
                    case 'w:ins':
                    case 'w:del': {
                        // Sprint 174（Phase 5.4 追蹤修訂）：`<w:ins>` 插入 / `<w:del>` 刪除
                        //   容器包裹 `<w:r>`，展平 runs 並標記 revision（author / date / id）。
                        //   `<w:del>` 內 run 的文字在 `<w:delText>` —— parseRun 已支援。
                        //   Scope-down（紀律 #18）：只處理直接 `<w:r>` 子元素；巢狀 ins/del、
                        //   ins/del 內含 hyperlink、moveFrom/moveTo、段落標記修訂留後續 sprint。
                        const revType = child.tagName === 'w:ins' ? 'ins' : 'del';
                        const revision = parseRevision(child, revType);
                        for (const r of effectiveChildren(child)) {
                            if (r.tagName !== 'w:r')
                                continue;
                            collectRunAnchors(r);
                            for (const node of parseRun(r)) {
                                if (node.type === 'run')
                                    node.revision = revision;
                                runs.push(node);
                            }
                        }
                        break;
                    }
                    case 'm:oMath': {
                        // Sprint 179（Phase 5.1 OMML）：段落直屬 `<m:oMath>` = 行內公式。
                        //   capture-only：遞迴解 OMML 樹、不解語意、不轉 KaTeX（留 Sprint 180）。
                        mathNodes.push({ display: false, omml: parseOmmlChildren(child) });
                        break;
                    }
                    case 'm:oMathPara': {
                        // Sprint 179：`<m:oMathPara>` 包裹獨立置中公式（display math）。
                        //   可含 `<m:oMathParaPr>` 屬性 + 一或多個 `<m:oMath>`；逐 `<m:oMath>` 收集。
                        for (const m of effectiveChildren(child)) {
                            if (m.tagName !== 'm:oMath')
                                continue;
                            mathNodes.push({ display: true, omml: parseOmmlChildren(m) });
                        }
                        break;
                    }
                    // w:pPr 已先處理；其他子節點 (w:proofErr) 暫時忽略
                }
            }
            // 若段落結束時 field 未閉合（malformed docx）、emit 已收集部分為 unknown
            if (fieldMode !== null || fieldInstr !== '' || fieldCached !== '') {
                emitField();
            }
            const node = {
                type: 'paragraph',
                props,
                runs,
            };
            if (styleId)
                node.styleId = styleId;
            // Sprint 125：bookmarks 只有在有內容時才掛 key、避免 AST diff noise
            if (bookmarkNames.size > 0) {
                node.bookmarks = Array.from(bookmarkNames);
            }
            // Sprint 177：commentRefs 同樣只在非空時掛 key（紀律 #21）；升序去重
            if (commentIds.size > 0) {
                node.commentRefs = Array.from(commentIds).sort((a, b) => a - b);
            }
            // Sprint 179：math 只在非空時掛 key（紀律 #21）；capture-only、layout 不消費
            if (mathNodes.length > 0) {
                node.math = mathNodes;
            }
            return node;
        }
    }
    /**
     * Sprint 174：解析 `<w:ins>` / `<w:del>` 的 w:author / w:date / w:id 為 RunRevision。
     *
     * @param el `<w:ins>` 或 `<w:del>` 元素
     * @param type 'ins'（插入）或 'del'（刪除）
     */
    function parseRevision(el, type) {
        const rev = { type };
        const author = el.getAttribute('w:author');
        if (author)
            rev.author = author;
        const date = el.getAttribute('w:date');
        if (date)
            rev.date = date;
        const idRaw = el.getAttribute('w:id');
        if (idRaw) {
            const n = parseInt(idRaw, 10);
            if (Number.isFinite(n))
                rev.id = n;
        }
        return rev;
    }
    /**
     * 解析 <w:hyperlink> 的 r:id / w:anchor / w:tooltip 為 HyperlinkInfo。
     *
     * @param el w:hyperlink 元素
     * @param lookup rId → URL 查詢函式（External 連結才回 URL）
     * @returns HyperlinkInfo；若四個欄位皆無則回 undefined
     */
    function parseHyperlinkInfo(el, lookup) {
        const rId = el.getAttribute('r:id') ?? el.getAttribute('id') ?? undefined;
        const anchor = el.getAttribute('w:anchor') ?? undefined;
        const tooltip = el.getAttribute('w:tooltip') ?? undefined;
        const url = rId && lookup ? lookup(rId) : undefined;
        // Sprint 126：額外 rels 屬性
        const tgtFrame = el.getAttribute('w:tgtFrame') ?? undefined;
        const docLocation = el.getAttribute('w:docLocation') ?? undefined;
        const historyRaw = el.getAttribute('w:history');
        // OOXML 布林：'1' / 'true' → true、'0' / 'false' → false、缺則 undefined
        let history;
        if (historyRaw === '1' || historyRaw === 'true')
            history = true;
        else if (historyRaw === '0' || historyRaw === 'false')
            history = false;
        const info = {};
        if (rId)
            info.rId = rId;
        if (url)
            info.url = url;
        if (anchor)
            info.anchor = anchor;
        if (tooltip)
            info.tooltip = tooltip;
        if (tgtFrame)
            info.tgtFrame = tgtFrame;
        if (history !== undefined)
            info.history = history;
        if (docLocation)
            info.docLocation = docLocation;
        // 紀律 #21 候選遵守：空集合不掛 key、只在有值時 set
        return Object.keys(info).length > 0 ? info : undefined;
    }
    // ── w:pPr ─────────────────────────────────────────────────────────────────────
    /**
     * 解析 <w:pPr> 為 ParagraphProps。對外公開供 StyleResolver 共用同一份邏輯。
     *
     * @public 給 StyleResolver / SectionParser 在解析 styles.xml / sectPr 時重用
     */
    function parseParagraphProps(pPr) {
        const props = {};
        const jc = attr$1(directChild$5(pPr, 'w:jc'), 'w:val');
        if (jc) {
            const a = mapAlignment$1(jc);
            if (a)
                props.alignment = a;
        }
        const indEl = directChild$5(pPr, 'w:ind');
        if (indEl) {
            const indent = {};
            const left = attrTwip$1(indEl, 'w:left') ?? attrTwip$1(indEl, 'w:start');
            const right = attrTwip$1(indEl, 'w:right') ?? attrTwip$1(indEl, 'w:end');
            const firstLine = attrTwip$1(indEl, 'w:firstLine');
            const hanging = attrTwip$1(indEl, 'w:hanging');
            if (left !== undefined)
                indent.left = left;
            if (right !== undefined)
                indent.right = right;
            if (firstLine !== undefined)
                indent.firstLine = firstLine;
            if (hanging !== undefined)
                indent.hanging = hanging;
            if (Object.keys(indent).length > 0)
                props.indent = indent;
        }
        const spEl = directChild$5(pPr, 'w:spacing');
        if (spEl) {
            const spacing = {};
            const before = attrTwip$1(spEl, 'w:before');
            const after = attrTwip$1(spEl, 'w:after');
            if (before !== undefined)
                spacing.before = before;
            if (after !== undefined)
                spacing.after = after;
            const lineRaw = spEl.getAttribute('w:line');
            const ruleRaw = spEl.getAttribute('w:lineRule');
            if (lineRaw) {
                const line = parseInt(lineRaw, 10);
                if (Number.isFinite(line)) {
                    const rule = mapLineSpacingRule(ruleRaw);
                    // auto 規則用 240 分母（Word 慣例）；其餘 rule 與 exact/atLeast 用 twip
                    const value = rule === 'auto' ? line / 240 : twipToPt(line);
                    spacing.line = { rule, value };
                }
            }
            if (Object.keys(spacing).length > 0)
                props.spacing = spacing;
        }
        const numPrEl = directChild$5(pPr, 'w:numPr');
        if (numPrEl) {
            const ilvlVal = attr$1(directChild$5(numPrEl, 'w:ilvl'), 'w:val');
            const numIdVal = attr$1(directChild$5(numPrEl, 'w:numId'), 'w:val');
            if (ilvlVal !== undefined) {
                const n = parseInt(ilvlVal, 10);
                if (Number.isFinite(n))
                    props.ilvl = n;
            }
            if (numIdVal !== undefined) {
                const n = parseInt(numIdVal, 10);
                if (Number.isFinite(n))
                    props.numId = n;
            }
        }
        if (boolFlag$2(directChild$5(pPr, 'w:keepNext')))
            props.keepNext = true;
        if (boolFlag$2(directChild$5(pPr, 'w:keepLines')))
            props.keepLines = true;
        if (boolFlag$2(directChild$5(pPr, 'w:pageBreakBefore')))
            props.pageBreakBefore = true;
        // Sprint 133: w:pBdr — 段落邊框（top / bottom / left / right、between / bar defer）
        const pBdrEl = directChild$5(pPr, 'w:pBdr');
        if (pBdrEl) {
            const borders = parseParagraphBorders(pBdrEl);
            if (borders)
                props.borders = borders;
        }
        // Sprint 133: w:shd — 段落底色 / 圖案
        const shdEl = directChild$5(pPr, 'w:shd');
        if (shdEl) {
            const shading = parseShading(shdEl);
            if (shading.fill || shading.color || shading.pattern) {
                props.shading = shading;
            }
        }
        // Sprint 134: w:textAlignment — 行內垂直對齊（OOXML §17.3.1.36）
        const textAlignEl = directChild$5(pPr, 'w:textAlignment');
        if (textAlignEl) {
            const v = textAlignEl.getAttribute('w:val');
            if (v === 'auto' || v === 'top' || v === 'center' || v === 'baseline' || v === 'bottom') {
                props.textAlignment = v;
            }
        }
        // Sprint 134: w:framePr — 段落框基礎屬性（OOXML §17.3.1.11）
        const framePrEl = directChild$5(pPr, 'w:framePr');
        if (framePrEl) {
            const frame = parseFramePr(framePrEl);
            if (frame)
                props.framePr = frame;
        }
        // Sprint 29：w:snapToGrid — 預設 true（OOXML §17.3.1.32），val="0" 顯式關閉
        const snapEl = directChild$5(pPr, 'w:snapToGrid');
        if (snapEl) {
            const v = snapEl.getAttribute('w:val');
            if (v === '0' || v === 'false')
                props.snapToGrid = false;
        }
        // w:tabs — tab stop 定義
        const tabsEl = directChild$5(pPr, 'w:tabs');
        if (tabsEl) {
            const tabs = [];
            for (const child of directChildren$8(tabsEl)) {
                if (child.tagName !== 'w:tab')
                    continue;
                // w:val 可為 left / right / center / decimal / bar / num / clear / start / end
                const valRaw = child.getAttribute('w:val');
                // 'clear' 表示移除繼承的 tab stop，跳過記錄
                if (valRaw === 'clear')
                    continue;
                let align = 'left';
                if (valRaw === 'right' || valRaw === 'end')
                    align = 'right';
                else if (valRaw === 'center')
                    align = 'center';
                else if (valRaw === 'decimal')
                    align = 'decimal';
                const posRaw = child.getAttribute('w:pos');
                if (posRaw === null)
                    continue;
                const posTwip = parseInt(posRaw, 10);
                if (!Number.isFinite(posTwip))
                    continue;
                const tab = {
                    pos: twipToPt(posTwip),
                    align,
                };
                const leader = child.getAttribute('w:leader');
                if (leader)
                    tab.leader = leader;
                tabs.push(tab);
            }
            if (tabs.length > 0) {
                // 依 pos 升序排序（OOXML 不保證寫入順序）
                tabs.sort((a, b) => a.pos - b.pos);
                props.tabs = tabs;
            }
        }
        return props;
    }
    // ── Sprint 134：w:framePr 段落框基礎屬性解析 ────────────────────────────────
    /**
     * 解析 `<w:framePr/>` 為 ParagraphProps.framePr 子集（OOXML §17.3.1.11）。
     *
     * Word 用此元素標示「位置與大小固定的浮動段落」（drop cap / 邊欄注釋）。
     * 當前 capture 主流屬性、進階（dropCap / lines / anchorLock）defer。
     *
     * 缺所有屬性回 undefined（紀律 #21）。
     */
    function parseFramePr(el) {
        const out = {};
        const w = attrTwip$1(el, 'w:w');
        if (w !== undefined)
            out.width = w;
        const h = attrTwip$1(el, 'w:h');
        if (h !== undefined)
            out.height = h;
        const hRuleRaw = el.getAttribute('w:hRule');
        if (hRuleRaw === 'auto' || hRuleRaw === 'atLeast' || hRuleRaw === 'exact') {
            out.hRule = hRuleRaw;
        }
        const hSpace = attrTwip$1(el, 'w:hSpace');
        if (hSpace !== undefined)
            out.hSpace = hSpace;
        const vSpace = attrTwip$1(el, 'w:vSpace');
        if (vSpace !== undefined)
            out.vSpace = vSpace;
        const wrapRaw = el.getAttribute('w:wrap');
        if (wrapRaw === 'around' || wrapRaw === 'notBeside' || wrapRaw === 'through' ||
            wrapRaw === 'tight' || wrapRaw === 'none') {
            out.wrap = wrapRaw;
        }
        const hAnchorRaw = el.getAttribute('w:hAnchor');
        if (hAnchorRaw === 'margin' || hAnchorRaw === 'page' || hAnchorRaw === 'text') {
            out.hAnchor = hAnchorRaw;
        }
        const vAnchorRaw = el.getAttribute('w:vAnchor');
        if (vAnchorRaw === 'margin' || vAnchorRaw === 'page' || vAnchorRaw === 'text') {
            out.vAnchor = vAnchorRaw;
        }
        const xAlignRaw = el.getAttribute('w:xAlign');
        if (xAlignRaw === 'left' || xAlignRaw === 'center' || xAlignRaw === 'right' ||
            xAlignRaw === 'inside' || xAlignRaw === 'outside') {
            out.xAlign = xAlignRaw;
        }
        const yAlignRaw = el.getAttribute('w:yAlign');
        if (yAlignRaw === 'top' || yAlignRaw === 'center' || yAlignRaw === 'bottom' ||
            yAlignRaw === 'inside' || yAlignRaw === 'outside' || yAlignRaw === 'inline') {
            out.yAlign = yAlignRaw;
        }
        const x = attrTwip$1(el, 'w:x');
        if (x !== undefined)
            out.x = x;
        const y = attrTwip$1(el, 'w:y');
        if (y !== undefined)
            out.y = y;
        if (Object.keys(out).length === 0)
            return undefined;
        return out;
    }
    // ── w:r → RunNode[]（單一 run 可能因 w:br 等切多筆） ─────────────────────────
    function parseRun(r) {
        const rPrEl = directChild$5(r, 'w:rPr');
        const baseProps = rPrEl ? parseRunProps(rPrEl) : {};
        const out = [];
        let textBuf = '';
        const flushText = () => {
            if (textBuf.length === 0)
                return;
            out.push({ type: 'run', text: textBuf, props: { ...baseProps } });
            textBuf = '';
        };
        // 用 effectiveChildren 展開 mc:AlternateContent（Run 內 drawing 常被它包）
        for (const child of effectiveChildren(r)) {
            switch (child.tagName) {
                case 'w:t':
                // Sprint 174：`<w:delText>`（`<w:del>` 內刪除文字）與 `<w:t>` 同樣讀取 textContent
                case 'w:delText': {
                    // xml:space="preserve" → 保留前後空白
                    // 注意：DOM 對缺省屬性取出可能是 null，不影響 textContent 讀取
                    textBuf += child.textContent ?? '';
                    break;
                }
                case 'w:br': {
                    flushText();
                    const t = child.getAttribute('w:type');
                    const breakType = t === 'page' ? 'page' : t === 'column' ? 'column' : 'line';
                    out.push({ type: 'break', breakType });
                    break;
                }
                case 'w:tab':
                    textBuf += '\t';
                    break;
                case 'w:noBreakHyphen':
                    textBuf += '‑'; // non-breaking hyphen
                    break;
                case 'w:softHyphen':
                    textBuf += '­'; // soft hyphen
                    break;
                case 'w:cr':
                    textBuf += '\n';
                    break;
                case 'w:drawing': {
                    flushText();
                    // Sprint 38：透過 module-level currentParagraphParser 提供 paragraphFactory，
                    // 讓 DrawingParser 解析 anchor text box (`<wps:txbx>` 內 `<w:p>`) 遞迴回到本實例
                    const activeParser = currentParagraphParser;
                    const factory = activeParser
                        ? (el) => activeParser.parse(el)
                        : undefined;
                    out.push(drawingParser.parse(child, factory));
                    break;
                }
                case 'w:object': {
                    // Sprint 122 — OLE 物件降級渲染（ECMA-376 §17.3.3.19）
                    // <w:object> 包 <v:shape>（VML preview）+ <o:OLEObject ProgID="..."/>
                    // 我們不嘗試渲染實際 OLE blob、emit italic 文字 placeholder 讓使用者
                    // 至少知道此處原本有嵌入物件、配合 ProgID / alt 顯示類型。
                    flushText();
                    const placeholder = buildOleFallbackText(child);
                    if (placeholder) {
                        out.push({
                            type: 'run',
                            text: placeholder,
                            props: { ...baseProps, italic: true },
                        });
                    }
                    break;
                }
                case 'w:pict': {
                    // Sprint 122 — VML 舊圖 placeholder（ECMA-376 §17.3.3.21、Word 97-2003 相容）
                    // <w:pict> 內含 <v:shape>、可能有 <o:OLEObject>（圖象化的舊版 OLE）。
                    // 同樣 emit italic placeholder、若內含 OLEObject 走 OLE 文案、否則 VML 文案。
                    flushText();
                    const placeholder = buildPictFallbackText(child);
                    if (placeholder) {
                        out.push({
                            type: 'run',
                            text: placeholder,
                            props: { ...baseProps, italic: true },
                        });
                    }
                    break;
                }
                // w:rPr 已先處理；w:fldChar 暫不處理（Sprint 123 候選）
            }
        }
        flushText();
        return out;
    }
    // ── w:rPr ─────────────────────────────────────────────────────────────────────
    /**
     * 解析 <w:rPr> 為 RunProps。對外公開供 StyleResolver 共用同一份邏輯。
     *
     * @public 給 StyleResolver 解析 styles.xml 時重用
     */
    function parseRunProps(rPr) {
        const props = {};
        const fontsEl = directChild$5(rPr, 'w:rFonts');
        if (fontsEl) {
            const ascii = fontsEl.getAttribute('w:ascii');
            const east = fontsEl.getAttribute('w:eastAsia');
            const hAnsi = fontsEl.getAttribute('w:hAnsi');
            const cs = fontsEl.getAttribute('w:cs');
            if (ascii)
                props.fontFamily = ascii;
            if (east)
                props.fontFamilyEastAsia = east;
            if (hAnsi)
                props.fontFamilyHAnsi = hAnsi;
            if (cs)
                props.fontFamilyCs = cs;
        }
        // w:sz 與 w:szCs 都是 half-point；CS 給 complex script。先用 w:sz。
        const szVal = attr$1(directChild$5(rPr, 'w:sz'), 'w:val');
        if (szVal !== undefined) {
            const n = parseInt(szVal, 10);
            if (Number.isFinite(n))
                props.fontSize = halfPointToPt(n);
        }
        if (boolFlag$2(directChild$5(rPr, 'w:b')))
            props.bold = true;
        if (boolFlag$2(directChild$5(rPr, 'w:i')))
            props.italic = true;
        if (boolFlag$2(directChild$5(rPr, 'w:strike')))
            props.strike = true;
        if (boolFlag$2(directChild$5(rPr, 'w:dstrike')))
            props.dstrike = true;
        const uVal = attr$1(directChild$5(rPr, 'w:u'), 'w:val');
        if (uVal)
            props.underline = uVal;
        // 顏色：優先 w:val（顯式 hex），再嘗試 themeColor + tint/shade（透過 ThemeMap）
        const colorEl = directChild$5(rPr, 'w:color');
        const resolvedColor = resolveColorElement(colorEl, themeMapForParser);
        if (resolvedColor)
            props.color = resolvedColor;
        // w:highlight 用具名色（yellow/cyan/...）；w:shd val + w:fill 才是 hex shading
        const highlight = attr$1(directChild$5(rPr, 'w:highlight'), 'w:val');
        if (highlight)
            props.highlight = highlight;
        const vert = attr$1(directChild$5(rPr, 'w:vertAlign'), 'w:val');
        if (vert === 'superscript' || vert === 'subscript' || vert === 'baseline') {
            props.vertAlign = vert;
        }
        const spacing = attr$1(directChild$5(rPr, 'w:spacing'), 'w:val');
        if (spacing !== undefined) {
            const n = parseInt(spacing, 10);
            if (Number.isFinite(n))
                props.spacing = twipToPt(n);
        }
        const lang = attr$1(directChild$5(rPr, 'w:lang'), 'w:val');
        if (lang)
            props.lang = lang;
        return props;
    }
    // ── Sprint 122：OLE / VML pict 降級 placeholder ─────────────────────────────
    /**
     * Sprint 122 — `<w:object>` placeholder 文字。
     *
     * OOXML §17.3.3.19：`<w:object>` 包 VML `<v:shape>` + `<o:OLEObject>`。
     *   - 嘗試讀 `<o:OLEObject ProgID="Equation.3"/>` → `[嵌入物件: Equation.3]`
     *   - 若有 `<v:shape alt="...">` → 加 alt 補充
     *   - 兩者都缺 → 純 `[嵌入物件]`
     *
     * 設計：getElementsByTagName 不限 namespace 前綴（OOXML 真實 docx 偶見
     *   `<OLEObject>` 無前綴、或 `<v:shape>` 改成 `<vml:shape>`）。
     */
    function buildOleFallbackText(objectEl) {
        let progId = '';
        let alt = '';
        // 寬鬆 walk：對 wildcard tagName endsWith 比對
        // happy-dom / browser 對 namespace 前綴處理不一致、用 walker 統一
        const walk = (root) => {
            const children = root.childNodes;
            for (let i = 0; i < children.length; i++) {
                const c = children[i];
                if (c.nodeType !== 1)
                    continue;
                const el = c;
                const local = el.localName ?? el.tagName.split(':').pop() ?? '';
                if (!progId && local === 'OLEObject') {
                    progId = el.getAttribute('ProgID') ?? '';
                }
                if (!alt && local === 'shape') {
                    alt = el.getAttribute('alt') ?? '';
                }
                walk(el);
            }
        };
        walk(objectEl);
        if (progId && alt)
            return `[嵌入物件: ${progId} — ${alt}]`;
        if (progId)
            return `[嵌入物件: ${progId}]`;
        if (alt)
            return `[嵌入物件: ${alt}]`;
        return '[嵌入物件]';
    }
    /**
     * Sprint 122 — `<w:pict>` placeholder 文字（VML legacy picture）。
     *
     * OOXML §17.3.3.21：Word 97-2003 相容圖片包裝。
     *   - 內含 `<o:OLEObject>` → 走 OLE 文案
     *   - 否則純 VML → `[圖片(VML)]` 或 `[圖片(VML): <alt>]`
     */
    function buildPictFallbackText(pictEl) {
        let hasOle = false;
        let progId = '';
        let alt = '';
        const walk = (root) => {
            const children = root.childNodes;
            for (let i = 0; i < children.length; i++) {
                const c = children[i];
                if (c.nodeType !== 1)
                    continue;
                const el = c;
                const local = el.localName ?? el.tagName.split(':').pop() ?? '';
                if (local === 'OLEObject') {
                    hasOle = true;
                    if (!progId)
                        progId = el.getAttribute('ProgID') ?? '';
                }
                if (!alt && local === 'shape') {
                    alt = el.getAttribute('alt') ?? '';
                }
                walk(el);
            }
        };
        walk(pictEl);
        if (hasOle) {
            if (progId && alt)
                return `[嵌入物件: ${progId} — ${alt}]`;
            if (progId)
                return `[嵌入物件: ${progId}]`;
            if (alt)
                return `[嵌入物件: ${alt}]`;
            return '[嵌入物件]';
        }
        if (alt)
            return `[圖片(VML): ${alt}]`;
        return '[圖片(VML)]';
    }
    // ── Sprint 123：複式 fldChar 跨多 w:r state machine helpers ─────────────────
    /**
     * Sprint 123 — 偵測 w:r 內是否含 `<w:fldChar w:fldCharType="begin">`。
     * 用於 paragraph-level state machine 起始判斷（不消費內容）。
     */
    function detectFieldBegin(r) {
        for (const child of directChildren$8(r)) {
            if (child.tagName !== 'w:fldChar')
                continue;
            if (child.getAttribute('w:fldCharType') === 'begin')
                return true;
        }
        return false;
    }
    /**
     * Sprint 123 — 在 field-collection mode 中消費一個 w:r 的內容。
     *
     * w:r 子元素可能含：
     *   - `<w:fldChar w:fldCharType="separate">` → 切換 instr → cached
     *   - `<w:fldChar w:fldCharType="end">` → emit field、結束 mode
     *   - `<w:instrText>` → instr mode 時 append 到 instruction
     *   - `<w:t>` → cached mode 時 append 到 cachedValue（instr mode 時忽略）
     *
     * @returns true 若此 w:r 完全被 field machine 消費；false 表示應 fallthrough 普通處理
     */
    function consumeRunIntoField(r, getMode, setMode, appendInstr, appendCached, emit) {
        // mode 可能在迭代中變動（begin / separate / end），故每個元素都重新讀
        for (const child of directChildren$8(r)) {
            switch (child.tagName) {
                case 'w:fldChar': {
                    const type = child.getAttribute('w:fldCharType');
                    if (type === 'begin') {
                        // begin 已由 caller 處理（或嵌套：不支援、清空已有累積以 unknown 開新 field）
                        if (getMode() !== null) {
                            emit(); // 強制 close 前一個（malformed）
                        }
                        setMode('instr');
                    }
                    else if (type === 'separate') {
                        if (getMode() !== null)
                            setMode('cached');
                    }
                    else if (type === 'end') {
                        if (getMode() !== null)
                            emit();
                    }
                    break;
                }
                case 'w:instrText': {
                    if (getMode() === 'instr')
                        appendInstr(child.textContent ?? '');
                    break;
                }
                case 'w:t': {
                    if (getMode() === 'cached')
                        appendCached(child.textContent ?? '');
                    // instr 模式時 w:t 是異常（spec 用 instrText）、忽略
                    break;
                }
                // 其他 (w:rPr / w:br 等) field 模式內忽略
            }
        }
        return getMode() !== null;
    }
    // ── w:fldSimple → FieldNode ──────────────────────────────────────────────────
    function parseFldSimple(el) {
        const instruction = (el.getAttribute('w:instr') ?? '').trim();
        const fieldType = classifyFieldType(instruction);
        // 快取值：fldSimple 內部的 w:r → w:t 串接
        let cached = '';
        for (const r of directChildren$8(el)) {
            if (r.tagName !== 'w:r')
                continue;
            for (const t of directChildren$8(r)) {
                if (t.tagName === 'w:t')
                    cached += t.textContent ?? '';
            }
        }
        const node = { type: 'field', instruction, fieldType };
        if (cached)
            node.cachedValue = cached;
        return node;
    }
    /**
     * Sprint 123 — instruction 字串 → FieldNode['fieldType'] 分類。
     * 第一個非空字 token 轉大寫對映已知集合；未知者回 'unknown'。
     * 共用給 parseFldSimple（簡式）+ 複式 fldChar（同 paragraph 跨多 w:r）。
     */
    function classifyFieldType(instruction) {
        const firstToken = instruction.trim().split(/\s+/)[0]?.toUpperCase() ?? '';
        const knownTypes = [
            'PAGE', 'NUMPAGES',
            'DATE', 'TIME',
            'AUTHOR', 'FILENAME',
            'SEQ', 'TOC', 'REF', 'HYPERLINK', 'STYLEREF',
        ];
        return knownTypes.includes(firstToken)
            ? firstToken
            : 'unknown';
    }
    // ── 共用工具 ──────────────────────────────────────────────────────────────────
    function directChildren$8(el) {
        const out = [];
        const children = el.childNodes;
        for (let i = 0; i < children.length; i++) {
            const n = children[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild$5(el, tagName) {
        if (!el)
            return undefined;
        for (const child of directChildren$8(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    function attr$1(el, name) {
        if (!el)
            return undefined;
        const v = el.getAttribute(name);
        return v === null ? undefined : v;
    }
    function attrTwip$1(el, name) {
        const v = attr$1(el, name);
        if (v === undefined)
            return undefined;
        const n = parseInt(v, 10);
        return Number.isFinite(n) ? twipToPt(n) : undefined;
    }
    /**
     * OOXML 布林屬性慣例：
     *   - 元素存在且無 w:val 屬性 → true
     *   - w:val="0" / "false" → false
     *   - w:val="1" / "true"  → true
     */
    function boolFlag$2(el) {
        if (!el)
            return false;
        const v = el.getAttribute('w:val');
        if (v === null)
            return true;
        return v !== '0' && v.toLowerCase() !== 'false';
    }
    function mapAlignment$1(jc) {
        switch (jc) {
            case 'left':
            case 'start':
                return 'left';
            case 'right':
            case 'end':
                return 'right';
            case 'center':
                return 'center';
            case 'both':
            case 'justify':
                return 'justify';
            case 'distribute':
                return 'distribute';
            default:
                return undefined;
        }
    }
    function mapLineSpacingRule(rule) {
        if (rule === 'exact')
            return 'exact';
        if (rule === 'atLeast')
            return 'atLeast';
        return 'auto';
    }

    /**
     * GridResolver — vMerge 兩 pass 演算法
     *
     * Pass 1（已在 TableParser.materializeRow 完成）：
     *   依 gridSpan 累計 cell.gridCol；vMerge=continue 的格子標記 isContinuation=true。
     *
     * Pass 2（本檔）：
     *   對每個 isContinuation 格子，往上掃同 gridCol 的非 continue 格子（= anchor），
     *   把 anchor.rowSpan 提升為 (continueRow - anchorRow + 1)。
     *
     * 邊界情況：
     *   - 連續 continue：每個 continue 都會獨立更新 anchor.rowSpan，最後 anchor 取得最大值
     *   - 找不到 anchor（孤兒 continue）：忽略，不 throw（OOXML spec：應由 Renderer 把孤兒當 restart）
     *   - 跨 gridSpan 不同的 vMerge 鏈：本演算法用「精確 gridCol 匹配」，
     *     不同 gridSpan 的鏈會被視為獨立鏈（少見且非規格保證情況）
     *   - 列高混合 atLeast/exact/auto：rowSpan 計算與列高無關，僅 Renderer 處理拉伸
     *
     * Renderer 使用 rowSpan + isContinuation：
     *   - rowSpan > 1：anchor 格子需繪製跨多列
     *   - isContinuation = true：跳過繪製內容；若跨頁，第一頁底邊框 omit、第二頁頂邊框 omit
     */
    class GridResolver {
        /**
         * 解析 vMerge 鏈，**就地改寫** rows 的 anchor cell 的 rowSpan。
         *
         * @param rows TableParser 產出的 RowNode[]，每個 cell 已有正確的 gridCol / gridSpan / isContinuation
         * @returns 同一份 rows（mutated in place），方便鏈式呼叫
         */
        resolve(rows) {
            for (let r = 0; r < rows.length; r++) {
                for (const cell of rows[r].cells) {
                    if (!cell.isContinuation)
                        continue;
                    // 往上找 anchor：同 gridCol 的第一個非 continue cell
                    for (let rUp = r - 1; rUp >= 0; rUp--) {
                        const anchor = rows[rUp].cells.find((c) => c.gridCol === cell.gridCol);
                        if (!anchor) {
                            // 此列沒有對齊 gridCol 的 cell — 跳過繼續往上
                            continue;
                        }
                        if (anchor.isContinuation) {
                            // 此 cell 也是 continue — 屬同一鏈，繼續往上找真正的 anchor
                            continue;
                        }
                        // 找到 anchor → 提升 rowSpan
                        const span = r - rUp + 1;
                        if (span > anchor.rowSpan) {
                            anchor.rowSpan = span;
                        }
                        break;
                    }
                    // 找不到 anchor 時靜默忽略（孤兒 continue）
                }
            }
            return rows;
        }
    }

    /**
     * TableStyleApplicator — 套用 w:tblStyle 與 w:tblStylePr 條件樣式到 TableNode（Phase 4.2）
     *
     * 流程：
     *   1. base = styleEntry.pProps + rProps（基底樣式，從 wholeTable conditional 補強）
     *   2. 對每一 row 判斷其位置（firstRow / lastRow / 偶/奇 band）
     *   3. 對每一 cell 判斷其位置（firstCol / lastCol / 偶/奇 band / corner）
     *   4. 依 ECMA-376 §17.7.6 套用順序合併條件樣式
     *   5. 最終 effective props 寫回 cell.content 內每段 paragraph + run（explicit 屬性優先）
     *
     * 套用順序（後者覆蓋前者，但 explicit 永遠最優先）：
     *   1. wholeTable
     *   2. band1Horz / band2Horz（依 row band index）
     *   3. band1Vert / band2Vert（依 col band index）
     *   4. firstRow / lastRow（若 tblLook 啟用）
     *   5. firstCol / lastCol（若 tblLook 啟用）
     *   6. nwCell / neCell / swCell / seCell（角落，僅 firstRow×firstCol 等同時啟用）
     *   7. cell-level explicit pPr/rPr（para.props / run.props 已有值）→ 覆蓋上述
     *
     * 設計決策：
     *   - **mutation**：直接修改 cell.content 的 paragraph.props 與 run.props
     *     避免在 AST 加 effectiveProps 欄位讓 mapper / renderer 多一層查詢
     *   - **explicit wins**：para.props / run.props 已有值的 key 不被覆寫，符合 Word 行為
     *   - **isContinuation 跳過**：vMerge 連續 cell 不渲染，無需套用
     */
    /**
     * Word 預設 tblLook（規格 §17.7.6.16 default 值）：
     *   firstRow=1, firstColumn=1, noVBand=1（即啟用首列首欄、停用縱向 banding）
     */
    const DEFAULT_TBL_LOOK = {
        firstRow: true,
        lastRow: false,
        firstColumn: true,
        lastColumn: false,
        noHBand: false,
        noVBand: true,
    };
    /**
     * 解析 w:tblLook val hex（如 "04A0" / "0420"）為旗標。
     *
     * Hex bit 對應（ECMA-376 §17.7.6.16）：
     *   0x0020 = firstRow
     *   0x0040 = lastRow
     *   0x0080 = firstColumn
     *   0x0100 = lastColumn
     *   0x0200 = noHBand
     *   0x0400 = noVBand
     *
     * 缺值 / 無效時回 DEFAULT_TBL_LOOK。
     */
    function parseTblLook(hex) {
        if (!hex)
            return { ...DEFAULT_TBL_LOOK };
        const v = parseInt(hex, 16);
        if (Number.isNaN(v))
            return { ...DEFAULT_TBL_LOOK };
        return {
            firstRow: !!(v & 0x0020),
            lastRow: !!(v & 0x0040),
            firstColumn: !!(v & 0x0080),
            lastColumn: !!(v & 0x0100),
            noHBand: !!(v & 0x0200),
            noVBand: !!(v & 0x0400),
        };
    }
    /**
     * 套用 tblStyle 與 tblStylePr 條件樣式到 TableNode。
     *
     * 副作用：mutates table.rows[*].cells[*].content[*].props 與 .runs[*].props
     *
     * @param table       要套用的 TableNode（將被 mutation）
     * @param styleEntry  StyleResolver 已 flatten 的 style entry（含 conditional Map）
     * @param tblLook     w:tblLook 解析結果（控制哪些 conditional types 會被套用）
     */
    function applyTableStyle(table, styleEntry, tblLook) {
        const baseP = styleEntry.pProps;
        const baseR = styleEntry.rProps;
        const cond = styleEntry.conditional;
        const totalRows = table.rows.length;
        const totalCols = table.grid.length;
        for (let r = 0; r < totalRows; r++) {
            const row = table.rows[r];
            const isFirstRow = r === 0 || row.props.isHeader;
            const isLastRow = r === totalRows - 1;
            const horzBand = computeHorzBand(r, totalRows, tblLook);
            for (const cell of row.cells) {
                if (cell.isContinuation)
                    continue;
                const isFirstCol = cell.gridCol === 0;
                const cellLastGrid = cell.gridCol + cell.gridSpan - 1;
                const isLastCol = cellLastGrid === totalCols - 1;
                const vertBand = computeVertBand(cell.gridCol, totalCols, tblLook);
                let effP = baseP ? { ...baseP } : {};
                let effR = baseR ? { ...baseR } : {};
                // Sprint 131：累積條件樣式的 cell-level props（shading + vAlign）
                let effC = {};
                // 1. wholeTable
                const ct = (k) => cond?.get(k);
                const apply = (entry) => {
                    if (!entry)
                        return;
                    effP = mergeProps(effP, entry.pProps);
                    effR = mergeProps(effR, entry.rProps);
                    if (entry.cProps)
                        effC = mergeCellConditionalProps(effC, entry.cProps);
                };
                apply(ct('wholeTable'));
                // 2. Horizontal banding
                if (horzBand === 1)
                    apply(ct('band1Horz'));
                else if (horzBand === 2)
                    apply(ct('band2Horz'));
                // 3. Vertical banding
                if (vertBand === 1)
                    apply(ct('band1Vert'));
                else if (vertBand === 2)
                    apply(ct('band2Vert'));
                // 4. First / Last row（受 tblLook 開關）
                if (isFirstRow && tblLook.firstRow)
                    apply(ct('firstRow'));
                if (isLastRow && tblLook.lastRow)
                    apply(ct('lastRow'));
                // 5. First / Last column（受 tblLook 開關）
                if (isFirstCol && tblLook.firstColumn)
                    apply(ct('firstCol'));
                if (isLastCol && tblLook.lastColumn)
                    apply(ct('lastCol'));
                // 6. Corner cells（最高優先級，僅相關 row/col 旗標都啟用時）
                if (isFirstRow && isFirstCol && tblLook.firstRow && tblLook.firstColumn) {
                    apply(ct('nwCell'));
                }
                if (isFirstRow && isLastCol && tblLook.firstRow && tblLook.lastColumn) {
                    apply(ct('neCell'));
                }
                if (isLastRow && isFirstCol && tblLook.lastRow && tblLook.firstColumn) {
                    apply(ct('swCell'));
                }
                if (isLastRow && isLastCol && tblLook.lastRow && tblLook.lastColumn) {
                    apply(ct('seCell'));
                }
                // 7a. Sprint 131：把 effective cell-level conditional props 寫回 cell.props
                //     explicit cell.props（TableParser 已 set）優先；空欄位才補入 conditional
                if (effC.shading || effC.vAlign) {
                    applyConditionalCellProps(cell, effC);
                }
                // 7. 把 effective props 寫回 cell 內每段段落 + run（explicit 永遠優先）
                // Sprint 7：cell.content 內 TableNode 也遞迴套用同一 styleEntry + tblLook
                // （巢狀表格繼承外層樣式；若巢狀表本身有 styleId，由 TableParser 階段已 apply 自己的樣式）
                for (const block of cell.content) {
                    if (block.type === 'paragraph') {
                        block.props = mergeProps(effP, block.props);
                        for (const node of block.runs) {
                            if (node.type === 'run') {
                                node.props = mergeProps(effR, node.props);
                            }
                        }
                    }
                    else if (block.type === 'table') {
                        // 遞迴套用：用外層 effective props 為 base，避免巢狀表完全遺失外層樣式
                        // 若巢狀表已有自己的 styleId（TableParser 應已 apply 過），不重套
                        if (!block.styleId) {
                            applyTableStyle(block, { pProps: effP, rProps: effR }, DEFAULT_TBL_LOOK);
                        }
                    }
                }
            }
        }
    }
    /**
     * 計算 row 的 horizontal band index：
     *   - 1 = odd band（套用 band1Horz）
     *   - 2 = even band（套用 band2Horz）
     *   - 0 = no band（跳過所有 banding）
     *
     * 規則：
     *   - tblLook.noHBand → 0（不套）
     *   - 第一列 / 最後一列被 firstRow/lastRow 處理時，banding 跳過
     *   - 其餘 row 從 1 開始計算 band（odd=1, even=2）
     */
    function computeHorzBand(rowIndex, totalRows, tblLook) {
        if (tblLook.noHBand)
            return 0;
        const isFirst = rowIndex === 0;
        const isLast = rowIndex === totalRows - 1;
        if (tblLook.firstRow && isFirst)
            return 0;
        if (tblLook.lastRow && isLast)
            return 0;
        // 從 firstRow 之後開始算 band，第一個非 firstRow 的列為 band1
        let bandIdx = rowIndex;
        if (tblLook.firstRow)
            bandIdx -= 1;
        return bandIdx % 2 === 0 ? 1 : 2;
    }
    function computeVertBand(gridCol, totalCols, tblLook) {
        if (tblLook.noVBand)
            return 0;
        const isFirst = gridCol === 0;
        const isLast = gridCol === totalCols - 1;
        if (tblLook.firstColumn && isFirst)
            return 0;
        if (tblLook.lastColumn && isLast)
            return 0;
        let bandIdx = gridCol;
        if (tblLook.firstColumn)
            bandIdx -= 1;
        return bandIdx % 2 === 0 ? 1 : 2;
    }
    /**
     * Sprint 131：合併 cell-level conditional props（後者覆蓋前者、shading 巢狀深合併）。
     *
     * shading 物件做 per-key 淺合併（fill/color/pattern 各自獨立覆蓋）；
     * vAlign 是 atomic 整體覆蓋。
     */
    function mergeCellConditionalProps(base, overlay) {
        const out = { ...base };
        if (overlay.shading) {
            out.shading = { ...(base.shading ?? {}), ...overlay.shading };
        }
        if (overlay.vAlign !== undefined) {
            out.vAlign = overlay.vAlign;
        }
        return out;
    }
    /**
     * Sprint 131：把 effective conditional cell props 寫回 cell.props，explicit 優先。
     *
     * 規則（與 paragraph/run props 一致）：
     *   - cell.props.shading 已有值 → 條件樣式整體放棄（atomic、避免半填半空）
     *     注意：TableParser 即使遇到 `<w:shd w:val="clear"/>`（無 fill/color）也會
     *     設置 shading={}（pattern only），這時 conditional 會被「卡掉」。
     *     現實中這種空 shading 罕見；shading=undefined 才是常態 fall-through。
     *   - cell.props.vAlign 已有值 → 條件樣式放棄；否則套用
     */
    function applyConditionalCellProps(cell, effC) {
        if (effC.shading && cell.props.shading === undefined) {
            cell.props.shading = { ...effC.shading };
        }
        if (effC.vAlign !== undefined && cell.props.vAlign === undefined) {
            cell.props.vAlign = effC.vAlign;
        }
    }
    /**
     * 合併兩個 props 物件：overlay 覆蓋 base；undefined keys 不影響。
     *
     * 注意：only shallow merge — 巢狀物件（如 indent.left）若 overlay 有 indent，
     * 整個 indent 會被覆蓋。Phase 4.2 不處理巢狀深層合併（StyleResolver 已對
     * docDefaults → basedOn 做完逐 key 巢狀合併；conditional 階段視為 atomic）。
     */
    function mergeProps(base, overlay) {
        if (!overlay)
            return base ? { ...base } : {};
        if (!base)
            return { ...overlay };
        return { ...base, ...overlay };
    }

    /**
     * BorderConflictResolver — ECMA-376 §17.4.65 表格邊框衝突解決
     *
     * 目的：
     *   Word 表格邊框可從 4 處來源：
     *     1. cell 自己的 <w:tcBorders>
     *     2. row 的 <w:trPr>（罕見）
     *     3. table 的 <w:tblBorders>（含 insideH/insideV 控制 cell 內邊）
     *     4. style 的 <w:tblBorders>（從 tblStyle 繼承，已被 StyleResolver 展開到 entry）
     *   多個來源在同一邊衝突時，需依優先級表決勝。
     *
     * 提供：
     *   - mergeCellBorders(cell, row, table, isInside) → CellBorders（單格 4 邊）
     *   - resolveCellEdge(edgeA, edgeB) → BorderDef（相鄰 cell 兩側競合）
     *   - resolveTableBorders(table) → 對全表 mutate 每 cell 的 borders 為 resolved 結果
     *
     * 優先級規則（§17.4.65 簡化版）：
     *   - nil/none 永遠輸（除非雙方皆 nil）
     *   - size 較大者勝
     *   - size 平手 → style weight 排序
     *   - style 平手 → color 字典序（穩定排序，少見）
     *
     * 為何在 Parser 階段做：
     *   - 渲染端（canvas-editor）只接受 cell 級 4 邊，不知道 insideH/insideV 概念
     *   - 跨 cell 邊框衝突在 layout 前要解決，否則重疊邊框會被畫兩次或缺失
     *   - 此處輸出的 CellBorders 已是 resolved 結果，render 直接用
     */
    /**
     * Border style weight 排序（依 ECMA-376 §17.4.65 與 §17.18.2 決定）。
     *
     * 數字越大 = 越「強」優先級。
     * style 同尺寸時，weight 大者勝。
     */
    const STYLE_WEIGHT = {
        nil: 0,
        none: 0,
        // 細線
        hair: 1,
        dotted: 2,
        dashed: 3,
        dashDot: 4,
        dashDotDot: 5,
        dashSmallGap: 4,
        dashDotStroked: 5,
        // 標準
        single: 10,
        // 粗線
        thick: 20,
        // 多線
        double: 30,
        triple: 32,
        // 內厚外薄 / 外厚內薄
        thinThickSmallGap: 40,
        thickThinSmallGap: 41,
        thinThickThinSmallGap: 42,
        thickThinThinSmallGap: 43,
        thinThickMediumGap: 44,
        thickThinMediumGap: 45,
        thinThickThinMediumGap: 46,
        thickThinThinMediumGap: 47,
        thinThickLargeGap: 48,
        thickThinLargeGap: 49,
        thinThickThinLargeGap: 50,
        thickThinThinLargeGap: 51,
        // 浪線/裝飾
        wave: 60,
        doubleWave: 61,
        dashLongHeavy: 62,
        dashDotHeavy: 63,
        dashDotDotHeavy: 64,
    };
    function styleWeight(style) {
        if (!style)
            return 0;
        return STYLE_WEIGHT[style] ?? 5; // 未列入表的給中等權重
    }
    /**
     * 比較兩個 BorderDef，回傳「贏家」（即優先採用的那一側）。
     *
     * 規則：
     *   1. 任一為 nil/none：另一方勝（皆 nil → undefined，雙方都不畫）
     *   2. width（pt）較大者勝
     *   3. width 平手 → styleWeight 較大者勝
     *   4. style 平手 → color 字典序穩定排序
     *   5. 全平手 → 回 a（穩定）
     */
    function resolveCellEdge(a, b) {
        if (!a && !b)
            return undefined;
        if (!a)
            return isNil(b) ? undefined : b;
        if (!b)
            return isNil(a) ? undefined : a;
        if (isNil(a) && isNil(b))
            return undefined;
        if (isNil(a))
            return b;
        if (isNil(b))
            return a;
        if (a.width !== b.width)
            return a.width > b.width ? a : b;
        const wa = styleWeight(a.style);
        const wb = styleWeight(b.style);
        if (wa !== wb)
            return wa > wb ? a : b;
        if (a.color !== b.color)
            return a.color < b.color ? a : b;
        return a;
    }
    function isNil(b) {
        if (!b)
            return true;
        return b.style === 'nil' || b.style === 'none';
    }
    /**
     * 對單一 cell 計算其四邊 effective borders。
     *
     * 套用順序（後者可能蓋前者，依 resolveCellEdge 競爭）：
     *   1. table.borders.top/bottom/left/right → cell 對應外邊
     *   2. table.borders.insideH/insideV → cell 內邊（非外緣 cell 的）
     *   3. cell.props.borders.* → cell 自己的設定
     *
     * @param cell           CellNode（將回傳新的 CellBorders，不 mutate cell）
     * @param row            cell 所在 RowNode（目前 row 沒 borders 欄位，留待未來擴展）
     * @param table          TableNode
     * @param totalRows      表格列總數
     * @param rowIndex       此 cell 所在 row index（0-based）
     */
    function mergeCellBorders(cell, _row, table, rowIndex, totalRows) {
        const out = {};
        const tblBorders = table.props.borders;
        const cellBorders = cell.props.borders;
        const isFirstRow = rowIndex === 0;
        const isLastRow = rowIndex === totalRows - 1;
        const isFirstCol = cell.gridCol === 0;
        const isLastCol = cell.gridCol + cell.gridSpan === table.grid.length;
        // top
        let top;
        if (isFirstRow)
            top = tblBorders?.top;
        else
            top = tblBorders?.insideH;
        top = resolveCellEdge(top, cellBorders?.top);
        if (top)
            out.top = top;
        // bottom
        let bottom;
        if (isLastRow)
            bottom = tblBorders?.bottom;
        else
            bottom = tblBorders?.insideH;
        bottom = resolveCellEdge(bottom, cellBorders?.bottom);
        if (bottom)
            out.bottom = bottom;
        // left
        let left;
        if (isFirstCol)
            left = tblBorders?.left;
        else
            left = tblBorders?.insideV;
        left = resolveCellEdge(left, cellBorders?.left);
        if (left)
            out.left = left;
        // right
        let right;
        if (isLastCol)
            right = tblBorders?.right;
        else
            right = tblBorders?.insideV;
        right = resolveCellEdge(right, cellBorders?.right);
        if (right)
            out.right = right;
        return out;
    }
    /**
     * 對全表 mutate 每 cell.props.borders 為 resolved 結果。
     *
     * 步驟：
     *   1. 對每 cell 跑 mergeCellBorders 取「table inside/outside + cell own」競爭結果
     *   2. 對相鄰 cell 兩側做 resolveCellEdge：
     *        - 同列左右相鄰：cell[i].right vs cell[i+1].left
     *        - 跨列上下相鄰：cell(r, c).bottom vs cell(r+1, c).top
     *      取勝者寫回兩側（讓兩邊看到的 border 一致）
     *   3. vMerge continuation cell 的水平邊（在 anchor span 中段）省略：
     *        - anchor cell 的 bottom = anchor 範圍內最末 row 的 bottom（不被 inside 影響）
     *        - 簡化：本實作只處理「不可見 continuation」，不對 cross-page render 做 special handling
     *
     * 副作用：mutate table.rows[*].cells[*].props.borders
     */
    function resolveTableBorders(table) {
        const totalRows = table.rows.length;
        const totalCols = table.grid.length;
        // Pass 1：每 cell 算自己的 4 邊（與 tblBorders 競爭）
        for (let r = 0; r < totalRows; r++) {
            const row = table.rows[r];
            for (const cell of row.cells) {
                cell.props.borders = mergeCellBorders(cell, row, table, r, totalRows);
            }
        }
        // Pass 2：相鄰 cell 邊界協調
        // 建 grid-position map：(row, gridCol) → cell
        const cellAt = [];
        for (let r = 0; r < totalRows; r++) {
            cellAt[r] = new Array(totalCols).fill(undefined);
            for (const cell of table.rows[r].cells) {
                for (let c = cell.gridCol; c < cell.gridCol + cell.gridSpan && c < totalCols; c++) {
                    cellAt[r][c] = cell;
                }
            }
        }
        // 同列左右相鄰
        for (let r = 0; r < totalRows; r++) {
            for (let c = 0; c < totalCols - 1; c++) {
                const left = cellAt[r][c];
                const right = cellAt[r][c + 1];
                if (!left || !right)
                    continue;
                if (left === right)
                    continue; // 同 cell（gridSpan）跳過
                const winner = resolveCellEdge(left.props.borders?.right, right.props.borders?.left);
                if (winner) {
                    if (!left.props.borders)
                        left.props.borders = {};
                    if (!right.props.borders)
                        right.props.borders = {};
                    left.props.borders.right = winner;
                    right.props.borders.left = winner;
                }
            }
        }
        // 跨列上下相鄰
        for (let r = 0; r < totalRows - 1; r++) {
            for (let c = 0; c < totalCols; c++) {
                const top = cellAt[r][c];
                const bottom = cellAt[r + 1][c];
                if (!top || !bottom)
                    continue;
                if (top === bottom)
                    continue; // vMerge anchor 跨多 row 視為同 cell
                // 若 top 是 vMerge anchor 且 bottom 是 continuation：bottom 不渲染，跳過協調
                if (bottom.isContinuation && bottom === cellAt[r][c])
                    continue;
                const winner = resolveCellEdge(top.props.borders?.bottom, bottom.props.borders?.top);
                if (winner) {
                    if (!top.props.borders)
                        top.props.borders = {};
                    if (!bottom.props.borders)
                        bottom.props.borders = {};
                    top.props.borders.bottom = winner;
                    bottom.props.borders.top = winner;
                }
            }
        }
    }

    /**
     * TableParser — 解析 <w:tbl>
     *
     * 範圍（Phase B.5 完整版）：
     *   - <w:tblGrid> + <w:gridCol w:w="..."> 欄寬定義
     *   - <w:tblPr>：tblW / tblInd / tblBorders / tblLook / tblStyle / jc / tblCellMar
     *   - <w:tr> + <w:trPr>：trHeight (含 hRule) / tblHeader / cantSplit
     *   - <w:tc> + <w:tcPr>：
     *       - tcW（dxa / pct / auto / nil）
     *       - gridSpan、vMerge
     *       - tcBorders（top/bottom/left/right/insideH/insideV）
     *       - shd（fill/color/pattern）
     *       - tcMar（儲存格邊界）
     *       - vAlign（top/center/bottom）
     *       - noWrap、hideMark、textDirection
     *
     * 不在此 Parser 範圍：
     *   - <w:tblStylePr> 條件樣式（15 種：firstRow/lastRow/etc.）— 由 StyleResolver 處理
     *   - Border conflict resolution（ECMA-376 17.4.65）— 由 Layout Engine 處理
     *   - 巢狀表格內容：cell.content 目前限定 ParagraphNode[]（AST 限制）
     *
     * Phase B.6 GridResolver 補完後，rowSpan / isContinuation 的計算交由它做。
     */
    class TableParser {
        constructor(documentParser) {
            this.gridResolver = new GridResolver();
            /** Phase 4.2：StyleMap 用於 tblStyle 解析 */
            this.styleMap = null;
            if (documentParser)
                this._documentParser = documentParser;
        }
        get documentParser() {
            if (!this._documentParser) {
                this._documentParser = new DocumentParser(this);
            }
            return this._documentParser;
        }
        /**
         * 注入 StyleMap（OoxmlParser orchestrator 在 styleResolver.resolve() 後呼叫）。
         *
         * 用於 parse() 結尾解 tblStyle id 並套用條件樣式。null 時跳過 applyTableStyle。
         */
        setStyleMap(map) {
            this.styleMap = map;
        }
        parse(tbl) {
            const grid = parseTblGrid(tbl);
            const tblProps = parseTblPr(directChild$4(tbl, 'w:tblPr'));
            const rawRows = this.parseRows(tbl);
            // Pass 1：cursor 推進 gridCol、標記 isContinuation
            let rows = rawRows.map((rr) => this.materializeRow(rr));
            // Pass 2：GridResolver 解析 vMerge 鏈 → 設定 anchor.rowSpan
            rows = this.gridResolver.resolve(rows);
            const node = {
                type: 'table',
                grid,
                rows,
                props: tblProps.props,
            };
            if (tblProps.styleId)
                node.styleId = tblProps.styleId;
            // Phase 4.2：套用 tblStyle 條件樣式（StyleResolver 已 collect tblStylePr）
            if (tblProps.styleId && this.styleMap) {
                const styleEntry = this.styleMap.get(tblProps.styleId);
                if (styleEntry) {
                    const tblLook = parseTblLook(tblProps.props.look);
                    applyTableStyle(node, styleEntry, tblLook);
                }
            }
            // Phase 4.3：邊框衝突解決（ECMA-376 §17.4.65）
            // 把 table.props.borders（含 insideH/V）+ 各 cell own borders 合併成
            // 每 cell 的 effective 4 邊；相鄰 cell 邊界協調避免重疊或漏失。
            resolveTableBorders(node);
            return node;
        }
        // ── row / cell 走訪 ────────────────────────────────────────────────────────
        parseRows(tbl) {
            const rows = [];
            for (const child of directChildren$7(tbl)) {
                if (child.tagName !== 'w:tr')
                    continue;
                rows.push(this.parseRow(child));
            }
            return rows;
        }
        parseRow(tr) {
            const cells = [];
            let height;
            let heightRule;
            let isHeader = false;
            let cantSplit = false;
            const trPr = directChild$4(tr, 'w:trPr');
            if (trPr) {
                const trHeightEl = directChild$4(trPr, 'w:trHeight');
                if (trHeightEl) {
                    // Sprint 121 — 進階 row height 防禦性解析（ECMA-376 §17.4.81）：
                    //   - val 必須是有限非負整數；負值 / NaN 視為缺 val
                    //   - hRule 顯式為 'exact' / 'atLeast' / 'auto'；其他值 fallback 'auto'
                    //   - val=0 配 hRule=exact 是合法的「零高度行」（Word 真的會渲染塌陷列）
                    //   - val=0 配 hRule=auto/缺 不視為「行高 0 的下限」（語意上等同沒給 val）
                    //   - hRule=exact / atLeast 沒給有效 val 時、demote heightRule 為 'auto'
                    //     （避免下游 TableLayout 走「heightRule==='exact' && height」分支但 height undefined）
                    const valRaw = trHeightEl.getAttribute('w:val');
                    if (valRaw !== null) {
                        const n = parseInt(valRaw, 10);
                        if (Number.isFinite(n) && n >= 0)
                            height = twipToPt(n);
                    }
                    const ruleRaw = trHeightEl.getAttribute('w:hRule');
                    if (ruleRaw === 'exact' || ruleRaw === 'atLeast')
                        heightRule = ruleRaw;
                    else
                        heightRule = 'auto';
                    // val=0 + hRule=auto/缺 → strip height（auto 0 沒下限意義）
                    if (height === 0 && heightRule === 'auto')
                        height = undefined;
                    // hRule 強約束但無有效 val → demote 'auto' 防 TableLayout 分支不一致
                    if ((heightRule === 'exact' || heightRule === 'atLeast') && height === undefined) {
                        heightRule = 'auto';
                    }
                }
                if (boolFlag$1(directChild$4(trPr, 'w:tblHeader')))
                    isHeader = true;
                if (boolFlag$1(directChild$4(trPr, 'w:cantSplit')))
                    cantSplit = true;
            }
            for (const child of directChildren$7(tr)) {
                if (child.tagName !== 'w:tc')
                    continue;
                cells.push(this.parseCell(child));
            }
            const out = { cells, isHeader, cantSplit };
            if (height !== undefined)
                out.height = height;
            if (heightRule !== undefined)
                out.heightRule = heightRule;
            return out;
        }
        parseCell(tc) {
            let gridSpan = 1;
            let vMerge = undefined;
            let width;
            let borders;
            let shading;
            let margins;
            let vAlign;
            let noWrap;
            let fitText;
            let textDirection;
            const tcPr = directChild$4(tc, 'w:tcPr');
            if (tcPr) {
                // gridSpan
                const gridSpanVal = attr(directChild$4(tcPr, 'w:gridSpan'), 'w:val');
                if (gridSpanVal) {
                    const n = parseInt(gridSpanVal, 10);
                    if (Number.isFinite(n) && n > 0)
                        gridSpan = n;
                }
                // vMerge
                const vMergeEl = directChild$4(tcPr, 'w:vMerge');
                if (vMergeEl) {
                    const valRaw = vMergeEl.getAttribute('w:val');
                    vMerge = valRaw === 'restart' ? 'restart' : 'continue';
                }
                // tcW
                const tcW = directChild$4(tcPr, 'w:tcW');
                if (tcW) {
                    const wVal = tcW.getAttribute('w:w');
                    const wType = tcW.getAttribute('w:type');
                    if (wVal && (wType === 'dxa' || wType === null)) {
                        const n = parseInt(wVal, 10);
                        if (Number.isFinite(n))
                            width = twipToPt(n);
                    }
                    // pct / auto / nil 不轉 pt（width undefined，由 Layout 處理）
                }
                // tcBorders
                const tcBordersEl = directChild$4(tcPr, 'w:tcBorders');
                if (tcBordersEl) {
                    borders = parseCellBorders(tcBordersEl);
                }
                // shd
                const shdEl = directChild$4(tcPr, 'w:shd');
                if (shdEl) {
                    shading = parseShading(shdEl);
                }
                // tcMar
                const tcMarEl = directChild$4(tcPr, 'w:tcMar');
                if (tcMarEl) {
                    margins = parseCellMargins(tcMarEl);
                }
                // vAlign
                const vAlignVal = attr(directChild$4(tcPr, 'w:vAlign'), 'w:val');
                if (vAlignVal === 'top' || vAlignVal === 'center' || vAlignVal === 'bottom') {
                    vAlign = vAlignVal;
                }
                // noWrap / hideMark / fitText
                if (boolFlag$1(directChild$4(tcPr, 'w:noWrap')))
                    noWrap = true;
                if (boolFlag$1(directChild$4(tcPr, 'w:tcFitText')))
                    fitText = true;
                // textDirection（OOXML §17.18.93 ST_TextDirection）
                // Sprint 34：擴充接受 V-suffix variants（glyph 旋轉式垂直文字，中文表單常用）
                const tdVal = attr(directChild$4(tcPr, 'w:textDirection'), 'w:val');
                if (tdVal === 'lrTb' || tdVal === 'tbRl' || tdVal === 'btLr'
                    || tdVal === 'lrTbV' || tdVal === 'tbRlV' || tdVal === 'tbLrV') {
                    textDirection = tdVal;
                }
            }
            // 內容：reuse DocumentParser.parseBodyContent；
            // Sprint 5 起 cell.content = BlockNode[]，支援巢狀表格（不再 filter 掉 TableNode）。
            const content = this.documentParser.parseBodyContent(tc);
            const out = { gridSpan, vMerge, content };
            if (width !== undefined)
                out.width = width;
            if (borders)
                out.borders = borders;
            if (shading)
                out.shading = shading;
            if (margins)
                out.margins = margins;
            if (vAlign)
                out.vAlign = vAlign;
            if (noWrap)
                out.noWrap = noWrap;
            if (fitText)
                out.fitText = fitText;
            if (textDirection)
                out.textDirection = textDirection;
            return out;
        }
        // ── raw → AST ─────────────────────────────────────────────────────────────
        materializeRow(rr) {
            let cursor = 0;
            const cells = rr.cells.map((rc) => {
                const props = {};
                if (rc.width !== undefined)
                    props.width = rc.width;
                if (rc.borders)
                    props.borders = rc.borders;
                if (rc.shading)
                    props.shading = rc.shading;
                if (rc.margins)
                    props.margins = rc.margins;
                if (rc.vAlign)
                    props.vAlign = rc.vAlign;
                if (rc.noWrap)
                    props.noWrap = rc.noWrap;
                if (rc.fitText)
                    props.fitText = rc.fitText;
                if (rc.textDirection)
                    props.textDirection = rc.textDirection;
                const cell = {
                    type: 'cell',
                    gridCol: cursor,
                    gridSpan: rc.gridSpan,
                    rowSpan: 1, // Phase B.6 GridResolver 補
                    isContinuation: rc.vMerge === 'continue',
                    content: rc.content,
                    props,
                };
                cursor += rc.gridSpan;
                return cell;
            });
            const props = {
                isHeader: rr.isHeader,
                cantSplit: rr.cantSplit,
            };
            if (rr.height !== undefined)
                props.height = rr.height;
            if (rr.heightRule !== undefined)
                props.heightRule = rr.heightRule;
            return { type: 'row', cells, props };
        }
    }
    // ── <w:tblGrid> ───────────────────────────────────────────────────────────────
    function parseTblGrid(tbl) {
        const tblGrid = directChild$4(tbl, 'w:tblGrid');
        if (!tblGrid)
            return [];
        const widths = [];
        for (const child of directChildren$7(tblGrid)) {
            if (child.tagName !== 'w:gridCol')
                continue;
            const w = child.getAttribute('w:w');
            if (w === null)
                continue;
            const n = parseInt(w, 10);
            widths.push(Number.isFinite(n) ? twipToPt(n) : 0);
        }
        return widths;
    }
    function parseTblPr(tblPr) {
        const props = {};
        let styleId;
        if (!tblPr)
            return { props };
        // tblStyle
        const tblStyleVal = attr(directChild$4(tblPr, 'w:tblStyle'), 'w:val');
        if (tblStyleVal)
            styleId = tblStyleVal;
        // tblW
        const tblW = directChild$4(tblPr, 'w:tblW');
        if (tblW) {
            const wVal = tblW.getAttribute('w:w');
            const wType = tblW.getAttribute('w:type');
            if (wType === 'dxa' || wType === null) {
                if (wVal) {
                    const n = parseInt(wVal, 10);
                    if (Number.isFinite(n))
                        props.width = twipToPt(n);
                }
                props.widthType = 'dxa';
            }
            else if (wType === 'pct' || wType === 'auto' || wType === 'nil') {
                props.widthType = wType;
            }
        }
        // tblInd
        const tblInd = directChild$4(tblPr, 'w:tblInd');
        if (tblInd) {
            const w = tblInd.getAttribute('w:w');
            if (w !== null) {
                const n = parseInt(w, 10);
                if (Number.isFinite(n))
                    props.indent = twipToPt(n);
            }
        }
        // jc → alignment
        const jcVal = attr(directChild$4(tblPr, 'w:jc'), 'w:val');
        if (jcVal === 'left' || jcVal === 'right' || jcVal === 'center') {
            props.alignment = jcVal;
        }
        else if (jcVal === 'start')
            props.alignment = 'left';
        else if (jcVal === 'end')
            props.alignment = 'right';
        // tblBorders
        const tblBordersEl = directChild$4(tblPr, 'w:tblBorders');
        if (tblBordersEl) {
            props.borders = parseCellBorders(tblBordersEl);
        }
        // tblLook
        const tblLookEl = directChild$4(tblPr, 'w:tblLook');
        if (tblLookEl) {
            const v = tblLookEl.getAttribute('w:val');
            if (v)
                props.look = v;
        }
        // tblCellMar → cellMargins
        const tblCellMarEl = directChild$4(tblPr, 'w:tblCellMar');
        if (tblCellMarEl) {
            props.cellMargins = parseCellMargins(tblCellMarEl);
        }
        return { props, styleId };
    }
    // ── <w:tcBorders> / <w:tblBorders> ───────────────────────────────────────────
    function parseCellBorders(el) {
        const out = {};
        for (const child of directChildren$7(el)) {
            const def = parseBorderDef(child);
            if (!def)
                continue;
            switch (child.tagName) {
                case 'w:top':
                    out.top = def;
                    break;
                case 'w:bottom':
                    out.bottom = def;
                    break;
                case 'w:left':
                case 'w:start':
                    out.left = def;
                    break;
                case 'w:right':
                case 'w:end':
                    out.right = def;
                    break;
                case 'w:insideH':
                    out.insideH = def;
                    break;
                case 'w:insideV':
                    out.insideV = def;
                    break;
            }
        }
        return out;
    }
    // Sprint 133：parseBorderDef / parseShading 已抽到 ../styles/borderShading.ts
    // 共用、本檔 import 使用、避免雙處維護 BorderDef shape
    // ── <w:tcMar> / <w:tblCellMar> ───────────────────────────────────────────────
    function parseCellMargins(el) {
        const out = {};
        for (const child of directChildren$7(el)) {
            const wVal = child.getAttribute('w:w');
            const wType = child.getAttribute('w:type');
            if (wVal === null)
                continue;
            if (wType !== null && wType !== 'dxa' && wType !== 'nil')
                continue; // 只認 dxa
            const n = parseInt(wVal, 10);
            if (!Number.isFinite(n))
                continue;
            const v = twipToPt(n);
            switch (child.tagName) {
                case 'w:top':
                    out.top = v;
                    break;
                case 'w:bottom':
                    out.bottom = v;
                    break;
                case 'w:left':
                case 'w:start':
                    out.left = v;
                    break;
                case 'w:right':
                case 'w:end':
                    out.right = v;
                    break;
            }
        }
        return out;
    }
    // ── 共用工具 ──────────────────────────────────────────────────────────────────
    function directChildren$7(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild$4(el, tagName) {
        for (const child of directChildren$7(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    function attr(el, name) {
        if (!el)
            return undefined;
        const v = el.getAttribute(name);
        return v === null ? undefined : v;
    }
    function boolFlag$1(el) {
        if (!el)
            return false;
        const v = el.getAttribute('w:val');
        if (v === null)
            return true;
        return v !== '0' && v.toLowerCase() !== 'false';
    }

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
    class DocumentParser {
        /**
         * @param tableParser 可選；OoxmlParser orchestrator 可注入共用 instance 以節省記憶體。
         *                    不傳則 first-use 時自動 new 並把 this 傳給 TableParser，避免循環。
         */
        constructor(tableParser) {
            this.paragraphParser = new ParagraphParser();
            if (tableParser)
                this._tableParser = tableParser;
        }
        get tableParser() {
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
        setRelsLookup(fn) {
            this.paragraphParser.setRelsLookup(fn);
        }
        /**
         * 把 ThemeMap 注入內部 ParagraphParser（Phase 4.1）。
         *
         * ParagraphParser.parseRunProps 用 ThemeMap 將 themeColor reference 解析為具體 hex。
         * 缺 ThemeMap 時 themeColor 屬性會被忽略（fallback 到 w:val 或 default）。
         */
        setThemeMap(theme) {
            this.paragraphParser.setThemeMap(theme);
        }
        /**
         * 解析 word/document.xml 字串為 DocumentNode（含 body 與 placeholder metadata）。
         * @throws Error 若 XML 無法解析或缺 <w:body>
         */
        parse(documentXml) {
            const doc = parseXml$e(documentXml);
            const root = doc.documentElement;
            if (!root) {
                throw new Error('DocumentParser: empty document');
            }
            const body = directChild$3(root, 'w:body');
            if (!body) {
                throw new Error('DocumentParser: <w:body> not found');
            }
            const blocks = [];
            let trailingSectPr;
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
            const section = makeSectionPlaceholder(trailingSectPr, blocks);
            const headers = new Map();
            const footers = new Map();
            const styles = new Map();
            const numbering = new Map();
            const media = new Map();
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
        parseBodyContent(bodyElement) {
            const blocks = [];
            // effectiveChildren 自動展開 mc:AlternateContent（cell 內 / header 內 drawing 常被它包）
            for (const child of effectiveChildren(bodyElement)) {
                if (child.tagName === 'w:p') {
                    blocks.push(this.paragraphParser.parse(child));
                }
                else if (child.tagName === 'w:tbl') {
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
        walkBody(documentXml) {
            const doc = parseXml$e(documentXml);
            const root = doc.documentElement;
            if (!root)
                throw new Error('DocumentParser: empty document');
            const body = directChild$3(root, 'w:body');
            if (!body)
                throw new Error('DocumentParser: <w:body> not found');
            const blocks = [];
            let trailingSectPr;
            for (const child of directChildren$6(body)) {
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
            const out = { blocks };
            if (trailingSectPr)
                out.trailingSectPr = trailingSectPr;
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
        walkBodyAsSections(documentXml) {
            const doc = parseXml$e(documentXml);
            const root = doc.documentElement;
            if (!root)
                throw new Error('DocumentParser: empty document');
            const body = directChild$3(root, 'w:body');
            if (!body)
                throw new Error('DocumentParser: <w:body> not found');
            const sections = [];
            let currentBlocks = [];
            // effectiveChildren 自動展開 body 層級的 mc:AlternateContent
            for (const child of effectiveChildren(body)) {
                switch (child.tagName) {
                    case 'w:p': {
                        // Sprint 200：識別 writer Sprint 191 emit 的 anchor paragraph
                        // （無 run + pPr 只含 sectPr）→ skip 不加入 blocks、保 round-trip 對稱
                        const pPr = directChild$3(child, 'w:pPr');
                        const innerSectPr = directChild$3(pPr, 'w:sectPr');
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
        findAllSectPrs(documentXml) {
            const doc = parseXml$e(documentXml);
            const root = doc.documentElement;
            if (!root)
                return [];
            const body = directChild$3(root, 'w:body');
            if (!body)
                return [];
            const out = [];
            // body 直接子 sectPr
            for (const child of directChildren$6(body)) {
                if (child.tagName === 'w:sectPr')
                    out.push(child);
            }
            // 段落中段內 sectPr：<w:p><w:pPr><w:sectPr>...</w:sectPr></w:pPr></w:p>
            const allParas = body.getElementsByTagName('w:p');
            for (let i = 0; i < allParas.length; i++) {
                const pPr = directChild$3(allParas[i], 'w:pPr');
                const sectPr = directChild$3(pPr, 'w:sectPr');
                if (sectPr)
                    out.push(sectPr);
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
    function makeSectionPlaceholder(_sectPrEl, body) {
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
    function isWriterAnchorParagraph(pEl, pPr) {
        if (!pPr)
            return false;
        // paragraph 不可有任何 run-like 子節點
        for (const c of directChildren$6(pEl)) {
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
        const pPrKids = directChildren$6(pPr);
        if (pPrKids.length !== 1)
            return false;
        return pPrKids[0].tagName === 'w:sectPr';
    }
    function directChildren$6(el) {
        const out = [];
        const children = el.childNodes;
        for (let i = 0; i < children.length; i++) {
            const n = children[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild$3(el, tagName) {
        if (!el)
            return undefined;
        for (const child of directChildren$6(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    function parseXml$e(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('DocumentParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`DocumentParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * FontTableParser — 解析 word/fontTable.xml(OOXML §17.8)
     *
     * Sprint 147(capture-only):
     *   - 42/42 fixture 都有 fontTable.xml、平均 ~20-30 fonts/file
     *   - 同 Sprint 145/146 capture-only 模式、不 wire-up
     *   - 為將來 wire-up 鋪路:
     *     - altName fallback chain(主字型缺失時 Word 自動用 alt)
     *     - family + pitch metric 選擇 hint
     *     - sig usb/csb Unicode 支援度精確 fallback 匹配
     *
     * 解析範圍:
     *   - <w:font w:name="..."> 主 key
     *   - <w:altName w:val="..."> 替代字型
     *   - <w:charset w:val="..."> hex 字串(如 '88' = BIG5)
     *   - <w:family w:val="..."> 列舉降級(auto/decorative/modern/roman/script/swiss)
     *   - <w:pitch w:val="..."> 列舉降級(fixed/variable/default)
     *   - <w:panose1 w:val="..."> 10-byte hex 字串
     *   - <w:sig w:usb0 ... w:csb1> 6 hex 屬性(紀律 #21 全空不掛 key)
     *
     * 與 FontMetricsAdapter(Sprint 60-65)的關係:
     *   - FontMetricsAdapter 走 opentype.js 量真實字型 metric;
     *   - 本 sprint capture fontTable.xml 是 docx 自帶的 font 表、不依賴 opentype.js;
     *   - 兩者互補:fontTable 提供 fallback hint、FontMetricsAdapter 提供精確 metric。
     *
     * 防禦:undefined / 空 / XML 失敗 → 回空 Map(不阻塞 OoxmlParser)。
     */
    class FontTableParser {
        /**
         * 解析 word/fontTable.xml 字串為 FontTable(Map<name, FontEntry>)。
         *
         * @param xml fontTable.xml 完整字串;undefined / 空 → 回空 Map
         */
        parse(xml) {
            const out = new Map();
            if (!xml)
                return out;
            let doc;
            try {
                doc = parseXml$d(xml);
            }
            catch {
                return out;
            }
            const root = doc.documentElement;
            if (!root)
                return out;
            // 收集所有 <w:font> 直接子元素
            const fontEls = directChildren$5(root).filter((el) => el.tagName === 'w:font');
            for (const fontEl of fontEls) {
                const name = fontEl.getAttribute('w:name');
                if (!name)
                    continue; // 缺 name → 跳過此條目
                const entry = { name };
                for (const sub of directChildren$5(fontEl)) {
                    switch (sub.tagName) {
                        case 'w:altName': {
                            const v = sub.getAttribute('w:val');
                            if (v)
                                entry.altName = v;
                            break;
                        }
                        case 'w:charset': {
                            const v = sub.getAttribute('w:val');
                            if (v)
                                entry.charset = v;
                            break;
                        }
                        case 'w:family': {
                            const v = sub.getAttribute('w:val');
                            const family = normalizeFamily(v);
                            if (family !== undefined)
                                entry.family = family;
                            break;
                        }
                        case 'w:pitch': {
                            const v = sub.getAttribute('w:val');
                            const pitch = normalizePitch(v);
                            if (pitch !== undefined)
                                entry.pitch = pitch;
                            break;
                        }
                        case 'w:panose1': {
                            const v = sub.getAttribute('w:val');
                            if (v)
                                entry.panose1 = v;
                            break;
                        }
                        case 'w:sig': {
                            const sig = parseSig(sub);
                            // 紀律 #21:全空時不掛 key
                            if (Object.keys(sig).length > 0)
                                entry.sig = sig;
                            break;
                        }
                    }
                }
                out.set(name, entry);
            }
            return out;
        }
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    function normalizeFamily(v) {
        if (v === null)
            return undefined;
        switch (v) {
            case 'auto':
            case 'decorative':
            case 'modern':
            case 'roman':
            case 'script':
            case 'swiss':
                return v;
            default:
                return undefined;
        }
    }
    function normalizePitch(v) {
        if (v === null)
            return undefined;
        switch (v) {
            case 'fixed':
            case 'variable':
            case 'default':
                return v;
            default:
                return undefined;
        }
    }
    function parseSig(el) {
        const sig = {};
        const usb0 = el.getAttribute('w:usb0');
        const usb1 = el.getAttribute('w:usb1');
        const usb2 = el.getAttribute('w:usb2');
        const usb3 = el.getAttribute('w:usb3');
        const csb0 = el.getAttribute('w:csb0');
        const csb1 = el.getAttribute('w:csb1');
        if (usb0)
            sig.usb0 = usb0;
        if (usb1)
            sig.usb1 = usb1;
        if (usb2)
            sig.usb2 = usb2;
        if (usb3)
            sig.usb3 = usb3;
        if (csb0)
            sig.csb0 = csb0;
        if (csb1)
            sig.csb1 = csb1;
        return sig;
    }
    function directChildren$5(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function parseXml$d(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('FontTableParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`FontTableParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

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
    class FootnotesParser {
        /**
         * @param documentParser 可選;OoxmlParser orchestrator 注入共用 instance 以重用 TableParser 等狀態。
         *                       不傳則自建一個。
         */
        constructor(documentParser) {
            this.documentParser = documentParser ?? new DocumentParser();
        }
        /**
         * 解析 word/footnotes.xml(或 endnotes.xml)為 Map<id, FootnoteContent>。
         *
         * @param xml footnotes.xml / endnotes.xml 完整字串;undefined / 空 → 回空 Map
         * @returns Map<id, FootnoteContent>;id 是 footnote 的 w:id 整數
         *          ;XML 無法解析時回空 Map(不 throw)
         */
        parse(xml) {
            const out = new Map();
            if (!xml)
                return out;
            try {
                const doc = parseXml$c(xml);
                const root = doc.documentElement;
                if (!root)
                    return out;
                // 收集所有 <w:footnote> 或 <w:endnote> 直接子元素(根節點下)
                // 用 tagName endsWith 容忍 endnotes.xml(<w:endnote>)和 footnotes.xml(<w:footnote>)
                const cs = root.childNodes;
                for (let i = 0; i < cs.length; i++) {
                    const n = cs[i];
                    if (n.nodeType !== 1)
                        continue;
                    const el = n;
                    // 允許 w:footnote 或 w:endnote
                    if (el.tagName !== 'w:footnote' && el.tagName !== 'w:endnote')
                        continue;
                    const idRaw = el.getAttribute('w:id');
                    if (idRaw === null)
                        continue;
                    const id = parseInt(idRaw, 10);
                    if (!Number.isFinite(id))
                        continue;
                    const typeRaw = el.getAttribute('w:type') ?? undefined;
                    const type = normalizeType(typeRaw);
                    // 內部結構等同 <w:body> — 重用 DocumentParser
                    let content = [];
                    try {
                        content = this.documentParser.parseBodyContent(el);
                    }
                    catch {
                        content = [];
                    }
                    const entry = { id, content };
                    if (type !== undefined)
                        entry.type = type;
                    out.set(id, entry);
                }
            }
            catch {
                // 整檔解析失敗 → 回空 Map(不阻塞 OoxmlParser)
                return new Map();
            }
            return out;
        }
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    function normalizeType(raw) {
        if (raw === undefined)
            return undefined;
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
    function parseXml$c(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('FootnotesParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`FootnotesParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

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
    class HeaderFooterParser {
        /**
         * @param documentParser 可選；OoxmlParser orchestrator 注入共用 instance 以重用 TableParser 等狀態。
         *                       不傳則自建一個（lazy 建 TableParser，安全可運行）。
         */
        constructor(documentParser) {
            this.documentParser = documentParser ?? new DocumentParser();
        }
        /**
         * 解析單一 header/footer XML 字串為 HeaderFooterContent。
         *
         * @param xml header*.xml 或 footer*.xml 完整字串
         * @param rId 此 part 對應的 relationship Id（由 sectPr 指向）
         * @returns HeaderFooterContent；XML 無法解析時 content 為空陣列（不 throw）
         */
        parse(xml, rId) {
            let content = [];
            try {
                const doc = parseXml$b(xml);
                const root = doc.documentElement;
                if (root) {
                    // <w:hdr> 與 <w:ftr> 內部結構等同 <w:body> — 直接走訪即可
                    content = this.documentParser.parseBodyContent(root);
                }
            }
            catch {
                // 解析失敗時降級為空內容；不影響整份文件解析
                content = [];
            }
            return { rId, content };
        }
    }
    // ── 共用 XML 解析 ─────────────────────────────────────────────────────────────
    function parseXml$b(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('HeaderFooterParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`HeaderFooterParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * NumberingResolver — word/numbering.xml 多層次清單編號
     *
     * 解析鏈：
     *   <w:num numId="N"> → <w:abstractNumId w:val="M"> → <w:abstractNum abstractNumId="M">
     *
     * 演算法：
     *   1. 第一遍走訪 <w:abstractNum> 收集 levels（ilvl 0–8）
     *   2. 第二遍走訪 <w:num>：解析 abstractNumId 與 lvlOverride
     *      - 把對應 abstractNum 的 levels copy 一份
     *      - 套用 lvlOverride（可能改 startOverride 或整層 lvl 內容）
     *   3. 產出 NumberingMap = Map<numId, AbstractNumbering>
     *
     * 注意：
     *   - 缺失的 abstractNumId 視為空 levels（不 throw）
     *   - 缺失的 ilvl 對應 level 視為 placeholder（numFmt='none', text='', start=1）
     *   - <w:lvlText val="%1.%2."> 模板字串原樣保留，由 Renderer 在 Layout 階段展開
     *
     * Phase B.2 範圍 — 全 numFmt 支援：decimal / lowerLetter / upperLetter /
     *   lowerRoman / upperRoman / bullet / chineseCounting / japaneseCounting / ordinal /
     *   ordinalText / cardinalText / iroha / aiueo / taiwaneseCounting / ideographDigital /
     *   chineseLegalSimplified（透傳，由 Renderer 解碼為實際數字）
     */
    class NumberingResolver {
        /**
         * 解析 numbering.xml 字串為 NumberingMap。
         *
         * @param xml word/numbering.xml 內容；undefined 時回空 Map
         */
        resolve(xml) {
            if (!xml)
                return new Map();
            const doc = parseXml$a(xml);
            const root = doc.documentElement;
            if (!root)
                return new Map();
            // Step 1：abstractNum
            const abstractByM = new Map();
            const abstractEls = root.getElementsByTagName('w:abstractNum');
            for (let i = 0; i < abstractEls.length; i++) {
                const an = parseAbstractNum(abstractEls[i]);
                if (an)
                    abstractByM.set(an.abstractNumId, an);
            }
            // Step 2：num（含 lvlOverride）
            const out = new Map();
            const numEls = root.getElementsByTagName('w:num');
            for (let i = 0; i < numEls.length; i++) {
                const raw = parseRawNum(numEls[i]);
                if (!raw)
                    continue;
                const baseAbstract = abstractByM.get(raw.abstractNumId);
                const resolved = applyOverrides(raw, baseAbstract);
                out.set(raw.numId, resolved);
            }
            return out;
        }
    }
    // ── <w:abstractNum> 解析 ─────────────────────────────────────────────────────
    function parseAbstractNum(el) {
        const idRaw = el.getAttribute('w:abstractNumId');
        if (!idRaw)
            return undefined;
        const abstractNumId = parseInt(idRaw, 10);
        if (!Number.isFinite(abstractNumId))
            return undefined;
        const levels = [];
        const lvlEls = el.getElementsByTagName('w:lvl');
        for (let i = 0; i < lvlEls.length; i++) {
            // 注意：abstractNum > lvl 是直接子；不會在 lvlOverride 內嵌套（那走另一個 path）
            // 用 parentNode 判斷是否為直接 lvl
            const parent = lvlEls[i].parentNode;
            if (!parent || parent.tagName !== 'w:abstractNum')
                continue;
            const level = parseLvl(lvlEls[i]);
            if (level)
                levels.push(level);
        }
        // 確保 ilvl 索引正確排序
        levels.sort((a, b) => a.ilvl - b.ilvl);
        return { abstractNumId, levels };
    }
    // ── <w:lvl> 解析 ─────────────────────────────────────────────────────────────
    function parseLvl(lvlEl) {
        const ilvlRaw = lvlEl.getAttribute('w:ilvl');
        if (!ilvlRaw)
            return undefined;
        const ilvl = parseInt(ilvlRaw, 10);
        if (!Number.isFinite(ilvl))
            return undefined;
        let numFmt = 'decimal';
        let text = '';
        let start = 1;
        let lvlRestart;
        let indent;
        let runProps;
        let pProps;
        let isLegal;
        for (const child of directChildren$4(lvlEl)) {
            switch (child.tagName) {
                case 'w:start': {
                    const v = child.getAttribute('w:val');
                    const n = v ? parseInt(v, 10) : NaN;
                    if (Number.isFinite(n))
                        start = n;
                    break;
                }
                case 'w:numFmt': {
                    const v = child.getAttribute('w:val');
                    if (v)
                        numFmt = v;
                    break;
                }
                case 'w:lvlText': {
                    const v = child.getAttribute('w:val');
                    if (v !== null)
                        text = v;
                    break;
                }
                case 'w:lvlRestart': {
                    const v = child.getAttribute('w:val');
                    const n = v ? parseInt(v, 10) : NaN;
                    if (Number.isFinite(n))
                        lvlRestart = n;
                    break;
                }
                case 'w:isLgl': {
                    const v = child.getAttribute('w:val');
                    isLegal = v === null ? true : v !== '0' && v.toLowerCase() !== 'false';
                    break;
                }
                case 'w:pPr': {
                    const ppFull = parseParagraphProps(child);
                    // 抽出 indent 給專屬欄位，其餘合併到 pProps
                    if (ppFull.indent) {
                        indent = {};
                        if (ppFull.indent.left !== undefined)
                            indent.left = ppFull.indent.left;
                        if (ppFull.indent.hanging !== undefined)
                            indent.hanging = ppFull.indent.hanging;
                        // firstLine / right 仍保留在 pProps（給段落整體用）
                        const { left: _l, hanging: _h, ...rest } = ppFull.indent;
                        if (Object.keys(rest).length > 0) {
                            pProps = { ...(pProps ?? {}), indent: rest };
                        }
                    }
                    // pPr 其他欄位（jc / spacing 等）合併到 pProps
                    const rest = { ...ppFull };
                    delete rest.indent;
                    if (Object.keys(rest).length > 0) {
                        pProps = { ...(pProps ?? {}), ...rest };
                    }
                    break;
                }
                case 'w:rPr':
                    runProps = parseRunProps(child);
                    break;
            }
        }
        const out = { ilvl, numFmt, text, start };
        if (lvlRestart !== undefined)
            out.lvlRestart = lvlRestart;
        if (indent && Object.keys(indent).length > 0)
            out.indent = indent;
        if (runProps)
            out.runProps = runProps;
        if (pProps && Object.keys(pProps).length > 0)
            out.pProps = pProps;
        if (isLegal)
            out.isLegal = isLegal;
        // 將 indent 中 hanging 用 twipToPt 已在 parseParagraphProps 處理過 — 這裡不需再轉
        // （parseParagraphProps 內部呼叫 attrTwip）
        return out;
    }
    // ── <w:num> 解析（含 lvlOverride）─────────────────────────────────────────────
    function parseRawNum(numEl) {
        const idRaw = numEl.getAttribute('w:numId');
        if (!idRaw)
            return undefined;
        const numId = parseInt(idRaw, 10);
        if (!Number.isFinite(numId))
            return undefined;
        let abstractNumId = -1;
        const overrides = [];
        for (const child of directChildren$4(numEl)) {
            if (child.tagName === 'w:abstractNumId') {
                const v = child.getAttribute('w:val');
                const n = v ? parseInt(v, 10) : NaN;
                if (Number.isFinite(n))
                    abstractNumId = n;
            }
            else if (child.tagName === 'w:lvlOverride') {
                const ov = parseLvlOverride(child);
                if (ov)
                    overrides.push(ov);
            }
        }
        if (abstractNumId < 0)
            return undefined;
        return { numId, abstractNumId, overrides };
    }
    function parseLvlOverride(el) {
        const ilvlRaw = el.getAttribute('w:ilvl');
        if (!ilvlRaw)
            return undefined;
        const ilvl = parseInt(ilvlRaw, 10);
        if (!Number.isFinite(ilvl))
            return undefined;
        const out = { ilvl };
        for (const child of directChildren$4(el)) {
            if (child.tagName === 'w:startOverride') {
                const v = child.getAttribute('w:val');
                const n = v ? parseInt(v, 10) : NaN;
                if (Number.isFinite(n))
                    out.startOverride = n;
            }
            else if (child.tagName === 'w:lvl') {
                const lvl = parseLvl(child);
                if (lvl)
                    out.level = lvl;
            }
        }
        return out;
    }
    // ── 套用 overrides ───────────────────────────────────────────────────────────
    function applyOverrides(raw, base) {
        // 缺失 abstract 仍輸出空殼
        if (!base) {
            return { abstractNumId: raw.abstractNumId, levels: [] };
        }
        // 拷貝 levels（對 NumberingLevel 做淺 copy 即可，避免污染原 abstract）
        const levels = base.levels.map((l) => ({ ...l }));
        for (const ov of raw.overrides) {
            if (ov.level) {
                // 整層覆蓋：找到同 ilvl 替換，沒找到就 push
                const idx = levels.findIndex((l) => l.ilvl === ov.ilvl);
                if (idx >= 0)
                    levels[idx] = { ...ov.level };
                else
                    levels.push({ ...ov.level });
            }
            else if (ov.startOverride !== undefined) {
                const idx = levels.findIndex((l) => l.ilvl === ov.ilvl);
                if (idx >= 0)
                    levels[idx] = { ...levels[idx], start: ov.startOverride };
            }
        }
        levels.sort((a, b) => a.ilvl - b.ilvl);
        return { abstractNumId: raw.abstractNumId, levels };
    }
    // ── 共用工具 ──────────────────────────────────────────────────────────────────
    function directChildren$4(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function parseXml$a(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('NumberingResolver: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`NumberingResolver: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * SettingsParser — 解析 word/settings.xml(OOXML §17.15)
     *
     * Sprint 146(capture-only):
     *   - 42 fixture settings.xml 全覆蓋(100%)、未來 layout/render 端 wire-up 鋪路
     *   - 高覆蓋元素: zoom / defaultTabStop / characterSpacingControl /
     *     footnotePr / endnotePr / compat 全 42/42
     *   - 不 wire-up(同 Sprint 145 Footnotes 模式)、capture 進 AST 供 caller 查詢
     *
     * 解析範圍(對應 DocumentSettings interface):
     *   - w:zoom w:percent → zoomPercent: number
     *   - w:defaultTabStop w:val → defaultTabStop: pt(從 twip 轉)
     *   - w:characterSpacingControl w:val → 列舉
     *   - w:autoHyphenation / w:evenAndOddHeaders / w:trackChanges → boolean(存在即 true)
     *   - w:proofState w:spelling/w:grammar → proofState
     *   - w:footnotePr / w:endnotePr → 結構物件
     *   - w:compat 內所有子元素標籤名 → string[]
     *
     * 紀律 #21:optional 欄位空集合不掛 key — 空物件 {} 代表「無設定」、所有欄位 undefined。
     *
     * 防禦:undefined / 空 / XML 解析失敗 → 回 {}(不阻塞 OoxmlParser)。
     */
    class SettingsParser {
        /**
         * 解析 word/settings.xml 字串為 DocumentSettings。
         *
         * @param xml settings.xml 完整字串;undefined / 空 → 回 {}
         */
        parse(xml) {
            if (!xml)
                return {};
            let doc;
            try {
                doc = parseXml$9(xml);
            }
            catch {
                return {};
            }
            const root = doc.documentElement;
            if (!root)
                return {};
            const out = {};
            for (const child of directChildren$3(root)) {
                switch (child.tagName) {
                    case 'w:zoom': {
                        const v = child.getAttribute('w:percent');
                        const n = v !== null ? parseInt(v, 10) : NaN;
                        if (Number.isFinite(n) && n > 0)
                            out.zoomPercent = n;
                        break;
                    }
                    case 'w:defaultTabStop': {
                        const v = child.getAttribute('w:val');
                        const n = v !== null ? parseInt(v, 10) : NaN;
                        if (Number.isFinite(n) && n > 0) {
                            out.defaultTabStop = twipToPt(n);
                        }
                        break;
                    }
                    case 'w:characterSpacingControl': {
                        const v = child.getAttribute('w:val');
                        if (v === 'doNotCompress' ||
                            v === 'compressPunctuation' ||
                            v === 'compressPunctuationAndJapaneseKana') {
                            out.characterSpacingControl = v;
                        }
                        break;
                    }
                    case 'w:autoHyphenation':
                        out.autoHyphenation = readToggle$1(child);
                        break;
                    case 'w:evenAndOddHeaders':
                        out.evenAndOddHeaders = readToggle$1(child);
                        break;
                    case 'w:trackChanges':
                        out.trackChanges = readToggle$1(child);
                        break;
                    case 'w:proofState': {
                        const ps = {};
                        const sp = child.getAttribute('w:spelling');
                        const gr = child.getAttribute('w:grammar');
                        if (sp === 'clean' || sp === 'dirty')
                            ps.spelling = sp;
                        if (gr === 'clean' || gr === 'dirty')
                            ps.grammar = gr;
                        if (Object.keys(ps).length > 0)
                            out.proofState = ps;
                        break;
                    }
                    case 'w:footnotePr':
                        out.footnotePr = parseNotePr(child, 'footnote');
                        break;
                    case 'w:endnotePr':
                        out.endnotePr = parseNotePr(child, 'endnote');
                        break;
                    case 'w:compat': {
                        const names = [];
                        for (const sub of directChildren$3(child)) {
                            // 去掉 w: 前綴
                            const tag = sub.tagName;
                            const local = tag.includes(':') ? tag.split(':')[1] : tag;
                            if (local)
                                names.push(local);
                        }
                        if (names.length > 0)
                            out.compat = names;
                        break;
                    }
                }
            }
            return out;
        }
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    /**
     * OOXML toggle:`<w:foo/>` 或 `<w:foo w:val="1"/>` 為 true、`w:val="0"` / `"false"` 為 false。
     * 預設(無屬性)= true、與 OOXML §17.17.4 規範對齊。
     */
    function readToggle$1(el) {
        const v = el.getAttribute('w:val');
        if (v === null)
            return true; // 元素存在 = true
        return v !== '0' && v.toLowerCase() !== 'false';
    }
    function parseNotePr(el, kind) {
        const out = {};
        for (const sub of directChildren$3(el)) {
            switch (sub.tagName) {
                case 'w:numRestart': {
                    const v = sub.getAttribute('w:val');
                    if (v === 'continuous' || v === 'eachPage' || v === 'eachSect') {
                        out.numRestart = v;
                    }
                    break;
                }
                case 'w:numFmt': {
                    const v = sub.getAttribute('w:val');
                    if (v)
                        out.numFmt = v;
                    break;
                }
                case 'w:pos': {
                    const v = sub.getAttribute('w:val');
                    // footnote: pageBottom/beneathText/sectEnd/docEnd
                    // endnote: sectEnd/docEnd
                    const valid = kind === 'footnote'
                        ? ['pageBottom', 'beneathText', 'sectEnd', 'docEnd']
                        : ['sectEnd', 'docEnd'];
                    if (v && valid.includes(v)) {
                        out.position = v;
                    }
                    break;
                }
                case 'w:numStart': {
                    const v = sub.getAttribute('w:val');
                    const n = v !== null ? parseInt(v, 10) : NaN;
                    if (Number.isFinite(n))
                        out.numStart = n;
                    break;
                }
                // <w:footnote w:id="-1"/> 等 — fixture 中 footnotes 預設 stub 引用、本 sprint 不解析
            }
        }
        return out;
    }
    function directChildren$3(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function parseXml$9(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('SettingsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`SettingsParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * WebSettingsParser — 解析 word/webSettings.xml(OOXML §17.16)
     *
     * Sprint 148(capture-only、結束 Phase 1 part 三連 cluster):
     *   - 42/42 fixture 都有 webSettings.xml(Word 預設骨架)
     *   - 主要是 docx 匯出 HTML 時的 hint、import / layout / render 不用
     *   - 留 hook 給將來 Phase 6 docx export 對稱性
     *
     * 解析範圍(scope-down、紀律 #18):
     *   - 4 toggle 元素(allowPNG / optimizeForBrowser / saveSmartTagsAsXml / doNotSaveAsSingleFile)
     *   - hasDivs:是否含 w:divs(不深入內部巢狀結構)
     *
     * 防禦:undefined / 空 / XML 失敗 → 回 {}(不阻塞 OoxmlParser)。
     */
    class WebSettingsParser {
        /**
         * 解析 word/webSettings.xml 字串為 DocumentWebSettings。
         *
         * @param xml webSettings.xml 完整字串;undefined / 空 → 回 {}
         */
        parse(xml) {
            if (!xml)
                return {};
            let doc;
            try {
                doc = parseXml$8(xml);
            }
            catch {
                return {};
            }
            const root = doc.documentElement;
            if (!root)
                return {};
            const out = {};
            for (const child of directChildren$2(root)) {
                switch (child.tagName) {
                    case 'w:optimizeForBrowser':
                        out.optimizeForBrowser = readToggle(child);
                        break;
                    case 'w:allowPNG':
                        out.allowPNG = readToggle(child);
                        break;
                    case 'w:saveSmartTagsAsXml':
                        out.saveSmartTagsAsXml = readToggle(child);
                        break;
                    case 'w:doNotSaveAsSingleFile':
                        out.doNotSaveAsSingleFile = readToggle(child);
                        break;
                    case 'w:divs':
                        // 只 capture 存在性、不深入內部結構(紀律 #18)
                        // 空 w:divs(無子元素)視為「無 divs」、與 OOXML §17.16.5 一致
                        if (directChildren$2(child).length > 0) {
                            out.hasDivs = true;
                        }
                        break;
                }
            }
            return out;
        }
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    function readToggle(el) {
        const v = el.getAttribute('w:val');
        if (v === null)
            return true;
        return v !== '0' && v.toLowerCase() !== 'false';
    }
    function directChildren$2(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function parseXml$8(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('WebSettingsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`WebSettingsParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * BackgroundParser — 解析 word/document.xml 的 `<w:background>`（OOXML §17.2.1）
     *
     * Sprint 171（Phase 5.6 浮水印 + 背景）：
     *   `<w:background>` 是 `<w:document>` 的直接子元素（`<w:body>` 的 sibling）、
     *   描述頁面背景色。Word「設計 → 頁面色彩」功能的儲存位置。
     *
     * 解析範圍（對應 DocumentBackground interface）：
     *   - `w:color`      → color（6-hex 大寫；"auto" / 非法 / 缺 → 不掛）
     *   - `w:themeColor` → themeColor（capture raw 主題色名、未解析為 hex）
     *
     * Scope-down（紀律 #18）：themeColor 不解析為 hex（render wire-up 用 color）；
     * `<v:background>` VML 圖片填充背景留後續 sprint。
     *
     * 紀律 #21：無 `<w:background>` 或無有效屬性 → 回 undefined（不掛空 key）。
     * 防禦：undefined / 空 / XML 解析失敗 → 回 undefined（不阻塞 OoxmlParser）。
     */
    /** OOXML hex 色：6 位 16 進位。 */
    const HEX6_RE = /^[0-9A-Fa-f]{6}$/;
    class BackgroundParser {
        /**
         * 解析 word/document.xml 字串、抽出 `<w:background>` 為 DocumentBackground。
         *
         * @param documentXml document.xml 完整字串；undefined / 空 → 回 undefined
         * @param themeMap    Sprint 178：已解析的 ThemeMap；提供時把 `w:themeColor`
         *                    （含 themeTint/themeShade）解析為具體 hex 寫入 `color`
         *                    （`w:color` 已直接給時不覆寫）。
         * @returns DocumentBackground 或 undefined（無背景設定）
         */
        parse(documentXml, themeMap) {
            if (!documentXml)
                return undefined;
            let doc;
            try {
                doc = parseXml$7(documentXml);
            }
            catch {
                return undefined;
            }
            const root = doc.documentElement;
            if (!root)
                return undefined;
            const bg = directChild$2(root, 'w:background');
            if (!bg)
                return undefined;
            const out = {};
            const color = bg.getAttribute('w:color');
            if (color && HEX6_RE.test(color)) {
                out.color = color.toUpperCase();
            }
            const themeColor = bg.getAttribute('w:themeColor');
            if (themeColor) {
                out.themeColor = themeColor;
                // Sprint 178：themeColor → 具體 hex（w:color 已直接給時不覆寫）。
                //   含 themeTint / themeShade（resolveThemeColor 內套變亮 / 變暗）。
                if (out.color === undefined && themeMap) {
                    const tint = bg.getAttribute('w:themeTint') ?? undefined;
                    const shade = bg.getAttribute('w:themeShade') ?? undefined;
                    out.color = resolveThemeColor(themeMap, themeColor, tint, shade);
                }
            }
            // 紀律 #21：無有效屬性（如僅 w:color="auto"）→ 不掛空物件
            return Object.keys(out).length > 0 ? out : undefined;
        }
    }
    /** 取得第一個 tagName 相符的直接子元素。 */
    function directChild$2(el, tagName) {
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1 && n.tagName === tagName) {
                return n;
            }
        }
        return undefined;
    }
    function parseXml$7(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('BackgroundParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`BackgroundParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * WatermarkParser — 從 header*.xml 抽出文件浮水印（Phase 5.6 浮水印 + 背景）
     *
     * Sprint 172（capture-only）：
     *   Word「設計 → 浮水印」儲存為 header part 內 `<w:pict>` 的 VML `<v:shape>`：
     *     - 文字浮水印：`<v:shape type="#_x0000_t136">` WordArt、含 `<v:textpath string="...">`
     *     - 圖片浮水印：`<v:shape id="...watermark...">`、含 `<v:imagedata r:id="...">`
     *
     * 解析範圍（對應 DocumentWatermark interface）：
     *   - kind 'text'  → text（textpath string）、font（textpath style font-family）
     *   - kind 'image' → imageRId（imagedata r:id）
     *   - rotation     → v:shape style 的 rotation（度）
     *
     * 偵測準則：
     *   - `<v:textpath>` 帶非空 `string` → 文字浮水印（header 內 WordArt 幾乎必為浮水印）
     *   - `<v:imagedata>` + shape id 含 "watermark"（Word 命名 WordPictureWatermark*）→ 圖片浮水印
     *
     * Scope-down（紀律 #18）：capture-only，render（每頁繪旋轉浮水印）留 Sprint 173；
     * 只 capture 第一個浮水印 shape；不解析 fill 透明度 / shape 尺寸。
     *
     * 防禦：undefined / 空 / XML 失敗 / 無浮水印 → 回 undefined（不阻塞 OoxmlParser）。
     */
    class WatermarkParser {
        /**
         * 從單一 header XML 抽出第一個浮水印。
         *
         * @param headerXml header*.xml 完整字串；undefined / 空 → undefined
         * @returns DocumentWatermark 或 undefined（此 header 無浮水印）
         */
        parse(headerXml) {
            if (!headerXml)
                return undefined;
            let doc;
            try {
                doc = parseXml$6(headerXml);
            }
            catch {
                return undefined;
            }
            const root = doc.documentElement;
            if (!root)
                return undefined;
            const shapes = root.getElementsByTagName('v:shape');
            for (let i = 0; i < shapes.length; i++) {
                const shape = shapes[i];
                const wm = parseShape(shape);
                if (wm)
                    return wm;
            }
            return undefined;
        }
    }
    /** 嘗試把單一 `<v:shape>` 解為浮水印；非浮水印 → undefined。 */
    function parseShape(shape) {
        const shapeStyle = shape.getAttribute('style');
        const rotation = parseRotation(shapeStyle);
        // 文字浮水印：<v:textpath string="...">
        const textpath = firstByTag$1(shape, 'v:textpath');
        if (textpath) {
            const text = textpath.getAttribute('string');
            if (text) {
                const out = { kind: 'text', text };
                const font = styleProp(textpath.getAttribute('style'), 'font-family');
                if (font)
                    out.font = stripQuotes(font);
                if (rotation !== undefined)
                    out.rotation = rotation;
                return out;
            }
        }
        // 圖片浮水印：shape id 含 "watermark" + <v:imagedata r:id="...">
        const id = shape.getAttribute('id') ?? '';
        if (/watermark/i.test(id)) {
            const imagedata = firstByTag$1(shape, 'v:imagedata');
            if (imagedata) {
                const rId = imagedata.getAttribute('r:id') ?? imagedata.getAttribute('o:relid');
                const out = { kind: 'image' };
                if (rId)
                    out.imageRId = rId;
                if (rotation !== undefined)
                    out.rotation = rotation;
                return out;
            }
        }
        return undefined;
    }
    /** 取第一個 tagName 相符的後代元素。 */
    function firstByTag$1(el, tagName) {
        const found = el.getElementsByTagName(tagName);
        return found.length > 0 ? found[0] : undefined;
    }
    /** 從 CSS-like style 字串取某屬性值（如 "font-family:標楷體;font-size:1pt"）。 */
    function styleProp(style, prop) {
        if (!style)
            return undefined;
        for (const decl of style.split(';')) {
            const idx = decl.indexOf(':');
            if (idx < 0)
                continue;
            if (decl.slice(0, idx).trim().toLowerCase() === prop) {
                return decl.slice(idx + 1).trim();
            }
        }
        return undefined;
    }
    /** 從 v:shape style 取 rotation（度）；無 / 非數 → undefined。 */
    function parseRotation(style) {
        const raw = styleProp(style, 'rotation');
        if (raw === undefined)
            return undefined;
        const n = parseFloat(raw);
        return Number.isFinite(n) ? n : undefined;
    }
    /** 去除前後成對的單 / 雙引號。 */
    function stripQuotes(s) {
        if (s.length >= 2) {
            const first = s[0];
            const last = s[s.length - 1];
            if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
                return s.slice(1, -1);
            }
        }
        return s;
    }
    function parseXml$6(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('WatermarkParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`WatermarkParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * CommentsParser — 解析 word/comments.xml（OOXML §17.13.4、Phase 5.5 註解）
     *
     * Sprint 176（capture-only）：
     *   Word 註解（「校閱 → 新增註解」）儲存於 comments.xml；document.xml 以
     *   `<w:commentRangeStart/End w:id>` 標記範圍、`<w:commentReference w:id>` 為錨點。
     *
     * comments.xml 結構：
     *   <w:comments>
     *     <w:comment w:id="0" w:author="Alice" w:date="2024-..." w:initials="A">
     *       <w:p>...註解內容...</w:p>
     *     </w:comment>
     *   </w:comments>
     *
     * 重用 DocumentParser.parseBodyContent 解析註解內部段落 + 表格（同 FootnotesParser /
     * HeaderFooterParser 模式）。
     *
     * Scope-down（紀律 #18）：capture comments.xml 內容；document.xml 的
     * commentRangeStart/End/Reference 錨點 wire-up + 右側 panel render 留後續 sprint。
     *
     * 防禦：undefined / 空 / XML 解析失敗 → 回空 Map（不阻塞 OoxmlParser）。
     */
    class CommentsParser {
        /**
         * @param documentParser 可選；OoxmlParser orchestrator 注入共用 instance 以重用
         *                       TableParser 等狀態。不傳則自建一個。
         */
        constructor(documentParser) {
            this.documentParser = documentParser ?? new DocumentParser();
        }
        /**
         * 解析 word/comments.xml 為 Map<id, CommentContent>。
         *
         * @param xml comments.xml 完整字串；undefined / 空 → 回空 Map
         * @returns Map<id, CommentContent>；XML 無法解析時回空 Map（不 throw）
         */
        parse(xml) {
            const out = new Map();
            if (!xml)
                return out;
            let doc;
            try {
                doc = parseXml$5(xml);
            }
            catch {
                return out;
            }
            const root = doc.documentElement;
            if (!root)
                return out;
            const cs = root.childNodes;
            for (let i = 0; i < cs.length; i++) {
                const n = cs[i];
                if (n.nodeType !== 1)
                    continue;
                const el = n;
                if (el.tagName !== 'w:comment')
                    continue;
                const idRaw = el.getAttribute('w:id');
                if (idRaw === null)
                    continue;
                const id = parseInt(idRaw, 10);
                if (!Number.isFinite(id))
                    continue;
                // 內部結構等同 <w:body> — 重用 DocumentParser
                let content = [];
                try {
                    content = this.documentParser.parseBodyContent(el);
                }
                catch {
                    content = [];
                }
                const entry = { id, content };
                const author = el.getAttribute('w:author');
                if (author)
                    entry.author = author;
                const date = el.getAttribute('w:date');
                if (date)
                    entry.date = date;
                const initials = el.getAttribute('w:initials');
                if (initials)
                    entry.initials = initials;
                out.set(id, entry);
            }
            return out;
        }
    }
    /**
     * Sprint 184：把註解內容轉為純文字（render 用）。
     *
     * mc:Fallback 壓縮（同 OMML / SmartArt / Chart 線性文字 fallback）：不重建 Word
     * 右側註解 panel，僅把註解段落文字攤平 —— ToCanvasEditor 以此在被註解段落後
     * append `[註解 …]` 標記（degraded fidelity）。
     *
     * @returns 註解段落文字（多段落以空白串接）；無文字 → 空字串
     */
    function commentToText(comment) {
        return blocksToText(comment.content);
    }
    /** 遞迴攤平 BlockNode[] 為純文字：段落取 run 文字、表格遞迴 cell。 */
    function blocksToText(blocks) {
        const lines = [];
        for (const b of blocks) {
            if (b.type === 'paragraph') {
                const t = b.runs
                    .filter((r) => r.type === 'run')
                    .map((r) => r.text)
                    .join('');
                if (t !== '')
                    lines.push(t);
            }
            else {
                // 表格 → 遞迴每個 cell 內容
                for (const row of b.rows) {
                    for (const cell of row.cells) {
                        const t = blocksToText(cell.content);
                        if (t !== '')
                            lines.push(t);
                    }
                }
            }
        }
        return lines.join(' ');
    }
    function parseXml$5(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('CommentsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`CommentsParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * DiagramParser — 解析 SmartArt 圖表資料模型（`dgm:` 命名空間、ECMA-376 §21.4、Phase 5.2）
     *
     * Sprint 181（capture-only）：
     *   Word SmartArt（「插入 → SmartArt」）在 document.xml 以 `<w:drawing>` 內
     *   `<a:graphicData uri=".../diagram"><dgm:relIds r:dm="rId..">` 表示，圖本身不內嵌於
     *   document.xml —— `r:dm` 以 rId 指向獨立的 `diagrams/dataN.xml`（資料模型部件）。
     *
     *   dataN.xml 結構（`<dgm:dataModel>`）：
     *     <dgm:dataModel>
     *       <dgm:ptLst>
     *         <dgm:pt type="doc"><dgm:prSet loTypeId="...VerticalCircleList"/>...</dgm:pt>
     *         <dgm:pt modelId="{..}">                  ← 內容點（無 type 屬性）
     *           <dgm:t><a:p><a:r><a:t>節點文字</a:t></a:r></a:p></dgm:t>
     *         </dgm:pt>
     *         <dgm:pt type="pres">...</dgm:pt>          ← presentation 點（跳過）
     *         <dgm:pt type="parTrans"/> <dgm:pt type="sibTrans"/>  ← 連接點（跳過）
     *       </dgm:ptLst>
     *       <dgm:cxnLst>...</dgm:cxnLst>                ← 連接關係（本 capture 不取）
     *     </dgm:dataModel>
     *
     * mc:Fallback 壓縮策略（user 2026-05-21 拍板）：本 capture 僅取資料模型的**文字內容**
     * 與版面類型識別碼，不重建圖形版面與連接線（degraded fidelity，對應 OMML 線性文字
     * fallback）。圖形精確 render 留未來 optional sprint。
     *
     * 防禦：undefined / 空 / XML 解析失敗 / root 非 `<dgm:dataModel>` → 回 undefined（不 throw）。
     */
    /** SmartArt 資料模型 root 元素 localName。 */
    const DATA_MODEL_TAG = 'dataModel';
    /** 內容點（非 presentation / 連接點）的 type 值；亦涵蓋「無 type 屬性」。 */
    const CONTENT_PT_TYPE = 'node';
    /** 跳過的 presentation / 結構點 type 值（不含使用者輸入文字的語意內容）。 */
    const SKIP_PT_TYPES = new Set(['doc', 'pres', 'parTrans', 'sibTrans']);
    class DiagramParser {
        /**
         * 解析 `diagrams/dataN.xml` 字串為 SmartArtNode。
         *
         * @param xml `diagrams/dataN.xml` 完整字串；undefined / 空 → 回 undefined
         * @param rId 對應的 diagramData 關係 rId（寫入 SmartArtNode.rId）
         * @returns SmartArtNode；XML 無法解析 / root 非 dataModel → undefined（不 throw）
         */
        parse(xml, rId) {
            if (!xml)
                return undefined;
            let doc;
            try {
                doc = parseXml$4(xml);
            }
            catch {
                return undefined;
            }
            const root = doc.documentElement;
            if (!root || stripDgmPrefix(root.tagName) !== DATA_MODEL_TAG)
                return undefined;
            const ptLst = directChild$6(root, 'dgm:ptLst');
            const pts = ptLst ? directChildren$a(ptLst) : [];
            const node = { rId, texts: [] };
            for (const pt of pts) {
                if (stripDgmPrefix(pt.tagName) !== 'pt')
                    continue;
                const type = pt.getAttribute('type') ?? CONTENT_PT_TYPE;
                // doc 點：抓版面類型識別碼（loTypeId）
                if (type === 'doc') {
                    const layoutType = readLayoutType(pt);
                    if (layoutType)
                        node.layoutType = layoutType;
                    continue;
                }
                // presentation / 連接點：無語意文字、跳過
                if (SKIP_PT_TYPES.has(type))
                    continue;
                // 內容點：抓 <dgm:t> 文字
                const text = readPtText(pt);
                if (text)
                    node.texts.push(text);
            }
            return node;
        }
    }
    /**
     * Sprint 183：把 SmartArt 轉為線性文字 fallback（render 用）。
     *
     * mc:Fallback 壓縮（user 2026-05-21 拍板）：不重建圖形版面與連接線，
     * 各內容點文字以 ` / ` 串接呈現（degraded fidelity、對應 OMML 線性文字 fallback）。
     *
     * @returns 線性文字；無文字 → 空字串
     */
    function smartArtToText(node) {
        return node.texts.join(' / ');
    }
    /**
     * 從 `<dgm:pt type="doc">` 的 `<dgm:prSet loTypeId>` 取版面類型識別碼。
     * 無 prSet 或無 loTypeId → undefined。
     */
    function readLayoutType(docPt) {
        const prSet = directChild$6(docPt, 'dgm:prSet');
        const loTypeId = prSet?.getAttribute('loTypeId');
        return loTypeId && loTypeId.length > 0 ? loTypeId : undefined;
    }
    /**
     * 取 `<dgm:pt>` 內 `<dgm:t>` 的文字：各 `<a:p>` 段落以 `\n` 串接，
     * 段落內所有 `<a:t>` 文字依序拼接。無文字 → 空字串。
     */
    function readPtText(pt) {
        const t = directChild$6(pt, 'dgm:t');
        if (!t)
            return '';
        const paras = [];
        for (const p of directChildren$a(t)) {
            if (stripDgmPrefix(p.tagName) !== 'p')
                continue; // <a:p>
            const runs = p.getElementsByTagName('a:t');
            let line = '';
            for (let i = 0; i < runs.length; i++) {
                line += runs[i].textContent ?? '';
            }
            paras.push(line);
        }
        return paras.join('\n').trim();
    }
    /**
     * 去掉標籤名的命名空間前綴（`dgm:` / `a:` 等），回傳 localName。
     * 無前綴則原樣回傳。
     */
    function stripDgmPrefix(name) {
        const idx = name.indexOf(':');
        return idx >= 0 ? name.slice(idx + 1) : name;
    }
    function parseXml$4(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('DiagramParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`DiagramParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * ChartParser — 解析圖表（`c:` 命名空間、ECMA-376 §21.2、Phase 5.3）
     *
     * Sprint 182（capture-only）：
     *   Word 圖表（「插入 → 圖表」）在 document.xml 以 `<w:drawing>` 內
     *   `<a:graphicData uri=".../chart"><c:chart r:id="rId..">` 表示，圖本身不內嵌
     *   document.xml —— `r:id` 以 rId 指向獨立的 `charts/chartN.xml`。
     *
     *   chartN.xml 結構（`<c:chartSpace>` root）：
     *     <c:chartSpace>
     *       <c:chart>
     *         <c:title>...<a:t>標題</a:t>...</c:title>          ← 可選
     *         <c:plotArea>
     *           <c:barChart>                                    ← 圖表型別元素
     *             <c:ser>                                       ← 資料數列
     *               <c:tx><c:strRef><c:strCache>...數列名...</c:strCache></c:strRef></c:tx>
     *               <c:cat><c:strRef><c:strCache>...類別軸...</c:strCache></c:strRef></c:cat>
     *               <c:val><c:numRef><c:numCache>...數值...</c:numCache></c:numRef></c:val>
     *             </c:ser>
     *           </c:barChart>
     *         </c:plotArea>
     *       </c:chart>
     *     </c:chartSpace>
     *
     *   快取（`<c:strCache>` / `<c:numCache>`）是 Word 為離線顯示而存的資料副本：
     *   `<c:ptCount val="N"/>` 點數 + 0..N 個 `<c:pt idx="i"><c:v>值</c:v></c:pt>`
     *   （idx 可能稀疏 —— 空白點省略）。
     *
     * mc:Fallback 壓縮策略（user 2026-05-21 拍板）：本 capture 取**數值快取**——
     * 圖表型別 + 標題 + 各數列的類別 / 數值；不重繪座標軸與圖形（degraded fidelity，
     * 同 SmartArt 取資料模型文字）。座標軸 / 圖例 / 圖形 render 留未來 optional sprint。
     *
     * 防禦：undefined / 空 / XML 解析失敗 / root 非 `<c:chartSpace>` → 回 undefined（不 throw）。
     */
    /** chart 部件 root 元素 localName。 */
    const CHART_SPACE_TAG = 'chartSpace';
    /** 圖表型別元素 localName 字尾（barChart / pieChart / bar3DChart …）。 */
    const CHART_TYPE_SUFFIX = 'Chart';
    class ChartParser {
        /**
         * 解析 `charts/chartN.xml` 字串為 ChartNode。
         *
         * @param xml `charts/chartN.xml` 完整字串；undefined / 空 → 回 undefined
         * @param rId 對應的 chart 關係 rId（寫入 ChartNode.rId）
         * @returns ChartNode；XML 無法解析 / root 非 chartSpace / 無圖表型別 → undefined（不 throw）
         */
        parse(xml, rId) {
            if (!xml)
                return undefined;
            let doc;
            try {
                doc = parseXml$3(xml);
            }
            catch {
                return undefined;
            }
            const root = doc.documentElement;
            if (!root || stripPrefix(root.tagName) !== CHART_SPACE_TAG)
                return undefined;
            const chart = firstByTag(root, 'c:chart');
            if (!chart)
                return undefined;
            const plotArea = firstByTag(chart, 'c:plotArea');
            if (!plotArea)
                return undefined;
            // 圖表型別：plotArea 直屬子元素中第一個 localName 以 'Chart' 結尾者
            const typeEl = directChildren$a(plotArea).find((el) => stripPrefix(el.tagName).endsWith(CHART_TYPE_SUFFIX));
            if (!typeEl)
                return undefined;
            const node = {
                rId,
                chartType: stripPrefix(typeEl.tagName),
                series: [],
            };
            const title = readTitle(chart);
            if (title)
                node.title = title;
            for (const ser of tagChildren(typeEl, 'c:ser')) {
                node.series.push(readSeries(ser));
            }
            return node;
        }
    }
    /**
     * Sprint 183：把圖表轉為線性文字 fallback（render 用）。
     *
     * mc:Fallback 壓縮（user 2026-05-21 拍板）：不重繪座標軸與圖形，以
     * 「標題 數列名: 類別=值, …; …」格式呈現數值快取（degraded fidelity）。
     *
     * @returns 線性文字；無數列 → 空字串（或僅標題）
     */
    function chartToText(node) {
        const parts = [];
        for (const s of node.series) {
            const pairs = [];
            for (let i = 0; i < s.categories.length; i++) {
                const cat = s.categories[i];
                const val = s.values[i];
                const hasVal = val !== null && val !== undefined;
                if (cat === '' && !hasVal)
                    continue; // 完全空白點 → 跳過
                pairs.push(hasVal ? `${cat}=${val}` : cat);
            }
            const body = pairs.join(', ');
            const line = s.name ? `${s.name}: ${body}` : body;
            if (line !== '')
                parts.push(line);
        }
        const joined = parts.join('; ');
        return node.title ? `${node.title} ${joined}`.trim() : joined;
    }
    /** 從 `<c:chart>` 的 `<c:title>` 取標題文字（拼接所有 `<a:t>`）。空 → undefined。 */
    function readTitle(chart) {
        const title = firstByTag(chart, 'c:title');
        if (!title)
            return undefined;
        const ts = title.getElementsByTagName('a:t');
        let out = '';
        for (let i = 0; i < ts.length; i++)
            out += ts[i].textContent ?? '';
        return out.trim() || undefined;
    }
    /** 解析單一 `<c:ser>` 為 ChartSeries。 */
    function readSeries(ser) {
        const series = { categories: [], values: [] };
        // 數列名稱：<c:tx> 內快取的第一個 <c:v>
        const tx = firstByTag(ser, 'c:tx');
        if (tx) {
            const v = firstByTag(tx, 'c:v');
            const name = v?.textContent?.trim();
            if (name)
                series.name = name;
        }
        // 類別軸：<c:cat> 快取（字串）
        const cat = firstByTag(ser, 'c:cat');
        if (cat) {
            const { count, pts } = readCachePoints(cat);
            series.categories = Array.from({ length: count }, (_, i) => pts.get(i) ?? '');
        }
        // 數值：<c:val> numCache
        const val = firstByTag(ser, 'c:val');
        if (val) {
            const { count, pts } = readCachePoints(val);
            series.values = Array.from({ length: count }, (_, i) => {
                const raw = pts.get(i);
                if (raw === undefined || raw === '')
                    return null;
                const n = Number(raw);
                return Number.isFinite(n) ? n : null;
            });
        }
        return series;
    }
    /**
     * 從 `<c:cat>` / `<c:val>` / `<c:tx>` 容器內的 `<c:strCache>` / `<c:numCache>`
     * 讀取點資料。
     *
     * @returns count = `<c:ptCount val>`（缺則用最大 idx+1）；pts = idx → `<c:v>` 文字
     */
    function readCachePoints(container) {
        const pts = new Map();
        let maxIdx = -1;
        const ptEls = container.getElementsByTagName('c:pt');
        for (let i = 0; i < ptEls.length; i++) {
            const pt = ptEls[i];
            const idx = parseInt(pt.getAttribute('idx') ?? '', 10);
            if (!Number.isFinite(idx) || idx < 0)
                continue;
            const v = firstByTag(pt, 'c:v');
            pts.set(idx, v?.textContent ?? '');
            if (idx > maxIdx)
                maxIdx = idx;
        }
        // ptCount 優先；缺漏時退回最大 idx + 1
        let count = maxIdx + 1;
        const ptCountEls = container.getElementsByTagName('c:ptCount');
        if (ptCountEls.length > 0) {
            const n = parseInt(ptCountEls[0].getAttribute('val') ?? '', 10);
            if (Number.isFinite(n) && n >= 0)
                count = n;
        }
        return { count, pts };
    }
    /** 取第一個 localName 相符的後代元素（含命名空間前綴比對）。 */
    function firstByTag(el, qualifiedName) {
        const list = el.getElementsByTagName(qualifiedName);
        return list.length > 0 ? list[0] : undefined;
    }
    /** 取直屬子元素中 tagName 相符者。 */
    function tagChildren(el, qualifiedName) {
        return directChildren$a(el).filter((c) => c.tagName === qualifiedName);
    }
    /** 去掉標籤名的命名空間前綴（`c:` / `a:` 等），回傳 localName。 */
    function stripPrefix(name) {
        const idx = name.indexOf(':');
        return idx >= 0 ? name.slice(idx + 1) : name;
    }
    function parseXml$3(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('ChartParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`ChartParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    // DEFLATE is a complex format; to read this code, you should probably check the RFC first:
    // https://tools.ietf.org/html/rfc1951
    // You may also wish to take a look at the guide I made about this program:
    // https://gist.github.com/101arrowz/253f31eb5abc3d9275ab943003ffecad
    // Some of the following code is similar to that of UZIP.js:
    // https://github.com/photopea/UZIP.js
    // However, the vast majority of the codebase has diverged from UZIP.js to increase performance and reduce bundle size.
    // Sometimes 0 will appear where -1 would be more appropriate. This is because using a uint
    // is better for memory in most engines (I *think*).

    // aliases for shorter compressed code (most minifers don't do this)
    var u8 = Uint8Array, u16 = Uint16Array, i32 = Int32Array;
    // fixed length extra bits
    var fleb = new u8([0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0, /* unused */ 0, 0, /* impossible */ 0]);
    // fixed distance extra bits
    var fdeb = new u8([0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, /* unused */ 0, 0]);
    // code length index map
    var clim = new u8([16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]);
    // get base, reverse index map from extra bits
    var freb = function (eb, start) {
        var b = new u16(31);
        for (var i = 0; i < 31; ++i) {
            b[i] = start += 1 << eb[i - 1];
        }
        // numbers here are at max 18 bits
        var r = new i32(b[30]);
        for (var i = 1; i < 30; ++i) {
            for (var j = b[i]; j < b[i + 1]; ++j) {
                r[j] = ((j - b[i]) << 5) | i;
            }
        }
        return { b: b, r: r };
    };
    var _a = freb(fleb, 2), fl = _a.b, revfl = _a.r;
    // we can ignore the fact that the other numbers are wrong; they never happen anyway
    fl[28] = 258, revfl[258] = 28;
    var _b = freb(fdeb, 0), fd = _b.b;
    // map of value to reverse (assuming 16 bits)
    var rev = new u16(32768);
    for (var i = 0; i < 32768; ++i) {
        // reverse table algorithm from SO
        var x = ((i & 0xAAAA) >> 1) | ((i & 0x5555) << 1);
        x = ((x & 0xCCCC) >> 2) | ((x & 0x3333) << 2);
        x = ((x & 0xF0F0) >> 4) | ((x & 0x0F0F) << 4);
        rev[i] = (((x & 0xFF00) >> 8) | ((x & 0x00FF) << 8)) >> 1;
    }
    // create huffman tree from u8 "map": index -> code length for code index
    // mb (max bits) must be at most 15
    // TODO: optimize/split up?
    var hMap = (function (cd, mb, r) {
        var s = cd.length;
        // index
        var i = 0;
        // u16 "map": index -> # of codes with bit length = index
        var l = new u16(mb);
        // length of cd must be 288 (total # of codes)
        for (; i < s; ++i) {
            if (cd[i])
                ++l[cd[i] - 1];
        }
        // u16 "map": index -> minimum code for bit length = index
        var le = new u16(mb);
        for (i = 1; i < mb; ++i) {
            le[i] = (le[i - 1] + l[i - 1]) << 1;
        }
        var co;
        if (r) {
            // u16 "map": index -> number of actual bits, symbol for code
            co = new u16(1 << mb);
            // bits to remove for reverser
            var rvb = 15 - mb;
            for (i = 0; i < s; ++i) {
                // ignore 0 lengths
                if (cd[i]) {
                    // num encoding both symbol and bits read
                    var sv = (i << 4) | cd[i];
                    // free bits
                    var r_1 = mb - cd[i];
                    // start value
                    var v = le[cd[i] - 1]++ << r_1;
                    // m is end value
                    for (var m = v | ((1 << r_1) - 1); v <= m; ++v) {
                        // every 16 bit value starting with the code yields the same result
                        co[rev[v] >> rvb] = sv;
                    }
                }
            }
        }
        else {
            co = new u16(s);
            for (i = 0; i < s; ++i) {
                if (cd[i]) {
                    co[i] = rev[le[cd[i] - 1]++] >> (15 - cd[i]);
                }
            }
        }
        return co;
    });
    // fixed length tree
    var flt = new u8(288);
    for (var i = 0; i < 144; ++i)
        flt[i] = 8;
    for (var i = 144; i < 256; ++i)
        flt[i] = 9;
    for (var i = 256; i < 280; ++i)
        flt[i] = 7;
    for (var i = 280; i < 288; ++i)
        flt[i] = 8;
    // fixed distance tree
    var fdt = new u8(32);
    for (var i = 0; i < 32; ++i)
        fdt[i] = 5;
    // fixed length map
    var flrm = /*#__PURE__*/ hMap(flt, 9, 1);
    // fixed distance map
    var fdrm = /*#__PURE__*/ hMap(fdt, 5, 1);
    // find max of array
    var max = function (a) {
        var m = a[0];
        for (var i = 1; i < a.length; ++i) {
            if (a[i] > m)
                m = a[i];
        }
        return m;
    };
    // read d, starting at bit p and mask with m
    var bits = function (d, p, m) {
        var o = (p / 8) | 0;
        return ((d[o] | (d[o + 1] << 8)) >> (p & 7)) & m;
    };
    // read d, starting at bit p continuing for at least 16 bits
    var bits16 = function (d, p) {
        var o = (p / 8) | 0;
        return ((d[o] | (d[o + 1] << 8) | (d[o + 2] << 16)) >> (p & 7));
    };
    // get end of byte
    var shft = function (p) { return ((p + 7) / 8) | 0; };
    // typed array slice - allows garbage collector to free original reference,
    // while being more compatible than .slice
    var slc = function (v, s, e) {
        if (s == null || s < 0)
            s = 0;
        if (e == null || e > v.length)
            e = v.length;
        // can't use .constructor in case user-supplied
        return new u8(v.subarray(s, e));
    };
    // error codes
    var ec = [
        'unexpected EOF',
        'invalid block type',
        'invalid length/literal',
        'invalid distance',
        'stream finished',
        'no stream handler',
        ,
        'no callback',
        'invalid UTF-8 data',
        'extra field too long',
        'date not in range 1980-2099',
        'filename too long',
        'stream finishing',
        'invalid zip data'
        // determined by unknown compression method
    ];
    var err = function (ind, msg, nt) {
        var e = new Error(msg || ec[ind]);
        e.code = ind;
        if (Error.captureStackTrace)
            Error.captureStackTrace(e, err);
        if (!nt)
            throw e;
        return e;
    };
    // expands raw DEFLATE data
    var inflt = function (dat, st, buf, dict) {
        // source length       dict length
        var sl = dat.length, dl = dict ? dict.length : 0;
        if (!sl || st.f && !st.l)
            return buf || new u8(0);
        var noBuf = !buf;
        // have to estimate size
        var resize = noBuf || st.i != 2;
        // no state
        var noSt = st.i;
        // Assumes roughly 33% compression ratio average
        if (noBuf)
            buf = new u8(sl * 3);
        // ensure buffer can fit at least l elements
        var cbuf = function (l) {
            var bl = buf.length;
            // need to increase size to fit
            if (l > bl) {
                // Double or set to necessary, whichever is greater
                var nbuf = new u8(Math.max(bl * 2, l));
                nbuf.set(buf);
                buf = nbuf;
            }
        };
        //  last chunk         bitpos           bytes
        var final = st.f || 0, pos = st.p || 0, bt = st.b || 0, lm = st.l, dm = st.d, lbt = st.m, dbt = st.n;
        // total bits
        var tbts = sl * 8;
        do {
            if (!lm) {
                // BFINAL - this is only 1 when last chunk is next
                final = bits(dat, pos, 1);
                // type: 0 = no compression, 1 = fixed huffman, 2 = dynamic huffman
                var type = bits(dat, pos + 1, 3);
                pos += 3;
                if (!type) {
                    // go to end of byte boundary
                    var s = shft(pos) + 4, l = dat[s - 4] | (dat[s - 3] << 8), t = s + l;
                    if (t > sl) {
                        if (noSt)
                            err(0);
                        break;
                    }
                    // ensure size
                    if (resize)
                        cbuf(bt + l);
                    // Copy over uncompressed data
                    buf.set(dat.subarray(s, t), bt);
                    // Get new bitpos, update byte count
                    st.b = bt += l, st.p = pos = t * 8, st.f = final;
                    continue;
                }
                else if (type == 1)
                    lm = flrm, dm = fdrm, lbt = 9, dbt = 5;
                else if (type == 2) {
                    //  literal                            lengths
                    var hLit = bits(dat, pos, 31) + 257, hcLen = bits(dat, pos + 10, 15) + 4;
                    var tl = hLit + bits(dat, pos + 5, 31) + 1;
                    pos += 14;
                    // length+distance tree
                    var ldt = new u8(tl);
                    // code length tree
                    var clt = new u8(19);
                    for (var i = 0; i < hcLen; ++i) {
                        // use index map to get real code
                        clt[clim[i]] = bits(dat, pos + i * 3, 7);
                    }
                    pos += hcLen * 3;
                    // code lengths bits
                    var clb = max(clt), clbmsk = (1 << clb) - 1;
                    // code lengths map
                    var clm = hMap(clt, clb, 1);
                    for (var i = 0; i < tl;) {
                        var r = clm[bits(dat, pos, clbmsk)];
                        // bits read
                        pos += r & 15;
                        // symbol
                        var s = r >> 4;
                        // code length to copy
                        if (s < 16) {
                            ldt[i++] = s;
                        }
                        else {
                            //  copy   count
                            var c = 0, n = 0;
                            if (s == 16)
                                n = 3 + bits(dat, pos, 3), pos += 2, c = ldt[i - 1];
                            else if (s == 17)
                                n = 3 + bits(dat, pos, 7), pos += 3;
                            else if (s == 18)
                                n = 11 + bits(dat, pos, 127), pos += 7;
                            while (n--)
                                ldt[i++] = c;
                        }
                    }
                    //    length tree                 distance tree
                    var lt = ldt.subarray(0, hLit), dt = ldt.subarray(hLit);
                    // max length bits
                    lbt = max(lt);
                    // max dist bits
                    dbt = max(dt);
                    lm = hMap(lt, lbt, 1);
                    dm = hMap(dt, dbt, 1);
                }
                else
                    err(1);
                if (pos > tbts) {
                    if (noSt)
                        err(0);
                    break;
                }
            }
            // Make sure the buffer can hold this + the largest possible addition
            // Maximum chunk size (practically, theoretically infinite) is 2^17
            if (resize)
                cbuf(bt + 131072);
            var lms = (1 << lbt) - 1, dms = (1 << dbt) - 1;
            var lpos = pos;
            for (;; lpos = pos) {
                // bits read, code
                var c = lm[bits16(dat, pos) & lms], sym = c >> 4;
                pos += c & 15;
                if (pos > tbts) {
                    if (noSt)
                        err(0);
                    break;
                }
                if (!c)
                    err(2);
                if (sym < 256)
                    buf[bt++] = sym;
                else if (sym == 256) {
                    lpos = pos, lm = null;
                    break;
                }
                else {
                    var add = sym - 254;
                    // no extra bits needed if less
                    if (sym > 264) {
                        // index
                        var i = sym - 257, b = fleb[i];
                        add = bits(dat, pos, (1 << b) - 1) + fl[i];
                        pos += b;
                    }
                    // dist
                    var d = dm[bits16(dat, pos) & dms], dsym = d >> 4;
                    if (!d)
                        err(3);
                    pos += d & 15;
                    var dt = fd[dsym];
                    if (dsym > 3) {
                        var b = fdeb[dsym];
                        dt += bits16(dat, pos) & (1 << b) - 1, pos += b;
                    }
                    if (pos > tbts) {
                        if (noSt)
                            err(0);
                        break;
                    }
                    if (resize)
                        cbuf(bt + 131072);
                    var end = bt + add;
                    if (bt < dt) {
                        var shift = dl - dt, dend = Math.min(dt, end);
                        if (shift + bt < 0)
                            err(3);
                        for (; bt < dend; ++bt)
                            buf[bt] = dict[shift + bt];
                    }
                    for (; bt < end; ++bt)
                        buf[bt] = buf[bt - dt];
                }
            }
            st.l = lm, st.p = lpos, st.b = bt, st.f = final;
            if (lm)
                final = 1, st.m = lbt, st.d = dm, st.n = dbt;
        } while (!final);
        // don't reallocate for streams or user buffers
        return bt != buf.length && noBuf ? slc(buf, 0, bt) : buf.subarray(0, bt);
    };
    // empty
    var et = /*#__PURE__*/ new u8(0);
    // read 2 bytes
    var b2 = function (d, b) { return d[b] | (d[b + 1] << 8); };
    // read 4 bytes
    var b4 = function (d, b) { return (d[b] | (d[b + 1] << 8) | (d[b + 2] << 16) | (d[b + 3] << 24)) >>> 0; };
    var b8 = function (d, b) { return b4(d, b) + (b4(d, b + 4) * 4294967296); };
    /**
     * Expands DEFLATE data with no wrapper
     * @param data The data to decompress
     * @param opts The decompression options
     * @returns The decompressed version of the data
     */
    function inflateSync(data, opts) {
        return inflt(data, { i: 2 }, opts && opts.out, opts && opts.dictionary);
    }
    // text decoder
    var td = typeof TextDecoder != 'undefined' && /*#__PURE__*/ new TextDecoder();
    // text decoder stream
    var tds = 0;
    try {
        td.decode(et, { stream: true });
        tds = 1;
    }
    catch (e) { }
    // decode UTF8
    var dutf8 = function (d) {
        for (var r = '', i = 0;;) {
            var c = d[i++];
            var eb = (c > 127) + (c > 223) + (c > 239);
            if (i + eb > d.length)
                return { s: r, r: slc(d, i - 1) };
            if (!eb)
                r += String.fromCharCode(c);
            else if (eb == 3) {
                c = ((c & 15) << 18 | (d[i++] & 63) << 12 | (d[i++] & 63) << 6 | (d[i++] & 63)) - 65536,
                    r += String.fromCharCode(55296 | (c >> 10), 56320 | (c & 1023));
            }
            else if (eb & 1)
                r += String.fromCharCode((c & 31) << 6 | (d[i++] & 63));
            else
                r += String.fromCharCode((c & 15) << 12 | (d[i++] & 63) << 6 | (d[i++] & 63));
        }
    };
    /**
     * Converts a Uint8Array to a string
     * @param dat The data to decode to string
     * @param latin1 Whether or not to interpret the data as Latin-1. This should
     *               not need to be true unless encoding to binary string.
     * @returns The original UTF-8/Latin-1 string
     */
    function strFromU8(dat, latin1) {
        if (latin1) {
            var r = '';
            for (var i = 0; i < dat.length; i += 16384)
                r += String.fromCharCode.apply(null, dat.subarray(i, i + 16384));
            return r;
        }
        else if (td) {
            return td.decode(dat);
        }
        else {
            var _a = dutf8(dat), s = _a.s, r = _a.r;
            if (r.length)
                err(8);
            return s;
        }
    }
    // skip local zip header
    var slzh = function (d, b) { return b + 30 + b2(d, b + 26) + b2(d, b + 28); };
    // read zip header
    var zh = function (d, b, z) {
        var fnl = b2(d, b + 28), fn = strFromU8(d.subarray(b + 46, b + 46 + fnl), !(b2(d, b + 8) & 2048)), es = b + 46 + fnl, bs = b4(d, b + 20);
        var _a = z && bs == 4294967295 ? z64e(d, es) : [bs, b4(d, b + 24), b4(d, b + 42)], sc = _a[0], su = _a[1], off = _a[2];
        return [b2(d, b + 10), sc, su, fn, es + b2(d, b + 30) + b2(d, b + 32), off];
    };
    // read zip64 extra field
    var z64e = function (d, b) {
        for (; b2(d, b) != 1; b += 4 + b2(d, b + 2))
            ;
        return [b8(d, b + 12), b8(d, b + 4), b8(d, b + 20)];
    };
    /**
     * Synchronously decompresses a ZIP archive. Prefer using `unzip` for better
     * performance with more than one file.
     * @param data The raw compressed ZIP file
     * @param opts The ZIP extraction options
     * @returns The decompressed files
     */
    function unzipSync(data, opts) {
        var files = {};
        var e = data.length - 22;
        for (; b4(data, e) != 0x6054B50; --e) {
            if (!e || data.length - e > 65558)
                err(13);
        }
        var c = b2(data, e + 8);
        if (!c)
            return {};
        var o = b4(data, e + 16);
        var z = o == 4294967295 || c == 65535;
        if (z) {
            var ze = b4(data, e - 12);
            z = b4(data, ze) == 0x6064B50;
            if (z) {
                c = b4(data, ze + 32);
                o = b4(data, ze + 48);
            }
        }
        for (var i = 0; i < c; ++i) {
            var _a = zh(data, o, z), c_2 = _a[0], sc = _a[1], su = _a[2], fn = _a[3], no = _a[4], off = _a[5], b = slzh(data, off);
            o = no;
            {
                if (!c_2)
                    files[fn] = slc(data, b, b + sc);
                else if (c_2 == 8)
                    files[fn] = inflateSync(data.subarray(b, b + sc), { out: new u8(su) });
                else
                    err(14, 'unknown compression type ' + c_2);
            }
        }
        return files;
    }

    /**
     * PackageReader — OOXML ZIP 容器解包
     *
     * 職責：
     *   1. 解開 .docx (ZIP) 取出每份 part（XML / 圖片 / 等）
     *   2. 解析 [Content_Types].xml：建立 path → MIME type 對照
     *      - <Default Extension="xml" ContentType="..."> 預設規則
     *      - <Override PartName="/word/document.xml" ContentType="..."> 覆蓋規則
     *   3. 解析 _rels/.rels 與 <part>/_rels/<part>.rels：建立 rId → target 對照
     *
     * 重要設計：
     *   - 所有 part 路徑統一去除前導 "/"（OOXML 慣例）
     *   - relationship target 解析為「相對於 .rels 所屬 part 的目錄」的絕對路徑
     *   - 不在此處解任何 OOXML 內容語意（document.xml / styles.xml 留給上層 Parser）
     *
     * Sprint 1 實作完成；後續若 ZIP 體積大可改 unzipAsync。
     */
    // 註：[Content_Types].xml 與 .rels 都用「預設命名空間 + 無 prefix」結構，
    // 用 getElementsByTagName(localName) 在瀏覽器與 happy-dom 都能正確匹配；
    // 而 getElementsByTagNameNS 在 happy-dom 對預設命名空間實作有缺陷（回傳 0）。
    class PackageReader {
        /**
         * 解析 .docx ArrayBuffer 為結構化 OoxmlPackage。
         * @throws Error 如果 ZIP 損壞、缺 [Content_Types].xml、或 XML 解析失敗
         */
        parse(buffer) {
            const bytes = new Uint8Array(buffer);
            const entries = unzipSync(bytes);
            const parts = new Map();
            const relationships = new Map();
            // Step 1: [Content_Types].xml 必須存在
            const ctRaw = entries['[Content_Types].xml'];
            if (!ctRaw) {
                throw new Error('PackageReader: [Content_Types].xml not found — not a valid OOXML package');
            }
            const contentTypes = parseContentTypes(strFromU8(ctRaw));
            // Step 2: 走訪所有 entry，分類為 part 或 relationship
            for (const [rawPath, data] of Object.entries(entries)) {
                // 跳過 ZIP 目錄項目（fflate 通常已過濾，但保險）
                if (rawPath.endsWith('/'))
                    continue;
                // 標準化路徑：去除前導 "/"
                const path = rawPath.replace(/^\/+/, '');
                // 跳過 [Content_Types].xml 本身（不是 part）
                if (path === '[Content_Types].xml')
                    continue;
                // .rels 檔：解析後存入 relationships map，不放進 parts
                if (path.endsWith('.rels')) {
                    const ownerPart = relsOwnerPath(path);
                    const xml = strFromU8(data);
                    const rels = parseRelationships(xml, ownerPart);
                    relationships.set(ownerPart, rels);
                    continue;
                }
                // 其他檔案 → part；查 contentType
                const contentType = resolveContentType(path, contentTypes);
                parts.set(path, { path, contentType, data });
            }
            return makePackage(parts, relationships, contentTypes);
        }
    }
    function parseContentTypes(xml) {
        const doc = parseXml$2(xml);
        const defaults = new Map();
        const overrides = new Map();
        const defaultEls = doc.getElementsByTagName('Default');
        for (let i = 0; i < defaultEls.length; i++) {
            const el = defaultEls[i];
            const ext = el.getAttribute('Extension')?.toLowerCase();
            const ct = el.getAttribute('ContentType');
            if (ext && ct)
                defaults.set(ext, ct);
        }
        const overrideEls = doc.getElementsByTagName('Override');
        for (let i = 0; i < overrideEls.length; i++) {
            const el = overrideEls[i];
            const partName = el.getAttribute('PartName')?.replace(/^\/+/, '');
            const ct = el.getAttribute('ContentType');
            if (partName && ct)
                overrides.set(partName, ct);
        }
        return { defaults, overrides };
    }
    function resolveContentType(path, ct) {
        // Override 優先於 Default
        const override = ct.overrides.get(path);
        if (override)
            return override;
        const dotIdx = path.lastIndexOf('.');
        if (dotIdx === -1)
            return 'application/octet-stream';
        const ext = path.substring(dotIdx + 1).toLowerCase();
        return ct.defaults.get(ext) ?? 'application/octet-stream';
    }
    /**
     * 從 .rels 路徑反推它所屬 part 的路徑。
     *   "_rels/.rels"                    → ""                  (root)
     *   "word/_rels/document.xml.rels"   → "word/document.xml"
     *   "word/_rels/header1.xml.rels"    → "word/header1.xml"
     */
    function relsOwnerPath(relsPath) {
        // root rels：_rels/.rels
        if (relsPath === '_rels/.rels')
            return '';
        // 拆 dir/_rels/file.ext.rels → dir/file.ext
        const match = relsPath.match(/^(.*?)_rels\/(.+)\.rels$/);
        if (!match) {
            // 不符合預期格式，回傳本身去 .rels 後綴（fallback）
            return relsPath.replace(/\.rels$/, '');
        }
        const dir = match[1]; // 含結尾 "/" 或 ""
        const file = match[2];
        return `${dir}${file}`;
    }
    function parseRelationships(xml, ownerPart) {
        const doc = parseXml$2(xml);
        const out = new Map();
        const rels = doc.getElementsByTagName('Relationship');
        for (let i = 0; i < rels.length; i++) {
            const el = rels[i];
            const id = el.getAttribute('Id');
            const type = el.getAttribute('Type');
            const targetRaw = el.getAttribute('Target');
            const targetModeRaw = el.getAttribute('TargetMode');
            if (!id || !type || !targetRaw)
                continue;
            const targetMode = targetModeRaw === 'External' ? 'External' : 'Internal';
            const target = targetMode === 'External' ? targetRaw : resolveTarget(ownerPart, targetRaw);
            out.set(id, { id, type, target, targetMode });
        }
        return out;
    }
    /**
     * 把 relationship target（相對路徑）解析為絕對 part path。
     * ownerPart 為空字串（root rels）時，target 本來就是相對於套件根。
     *
     * 範例：
     *   ownerPart = "word/document.xml", target = "header1.xml"
     *     → "word/header1.xml"
     *   ownerPart = "word/document.xml", target = "media/image1.png"
     *     → "word/media/image1.png"
     *   ownerPart = "word/document.xml", target = "../customXml/item1.xml"
     *     → "customXml/item1.xml"
     *   ownerPart = "", target = "word/document.xml"
     *     → "word/document.xml"
     */
    function resolveTarget(ownerPart, target) {
        // target 開頭為 "/" 表示絕對路徑
        if (target.startsWith('/'))
            return target.replace(/^\/+/, '');
        // 取 ownerPart 的目錄（不含檔名）
        const lastSlash = ownerPart.lastIndexOf('/');
        const baseDir = lastSlash === -1 ? '' : ownerPart.substring(0, lastSlash + 1);
        // 拼接後正規化：處理 ".." 與 "."
        const combined = baseDir + target;
        return normalizePath(combined);
    }
    function normalizePath(path) {
        const parts = path.split('/');
        const stack = [];
        for (const part of parts) {
            if (part === '' || part === '.')
                continue;
            if (part === '..') {
                stack.pop();
                continue;
            }
            stack.push(part);
        }
        return stack.join('/');
    }
    /**
     * 統一 XML 解析入口。優先用 DOMParser（瀏覽器與 happy-dom/jsdom 環境）。
     * 若解析失敗（含 <parsererror>），丟錯。
     */
    function parseXml$2(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('PackageReader: DOMParser not available — Node tests must use happy-dom environment');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        // DOMParser 不會 throw；錯誤會放在 <parsererror>
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`PackageReader: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }
    function makePackage(parts, relationships, contentTypes) {
        return {
            parts,
            relationships,
            contentTypes: {
                defaults: contentTypes.defaults,
                overrides: contentTypes.overrides,
            },
            getPart(path) {
                return parts.get(path.replace(/^\/+/, ''));
            },
            getRelationships(partPath) {
                return relationships.get(partPath.replace(/^\/+/, '')) ?? new Map();
            },
            partAsText(path) {
                const p = parts.get(path.replace(/^\/+/, ''));
                if (!p)
                    return undefined;
                return strFromU8(p.data);
            },
            resolveRelationship(partPath, rId) {
                const rels = relationships.get(partPath.replace(/^\/+/, ''));
                return rels?.get(rId)?.target;
            },
        };
    }

    /**
     * LatentStylesParser — 解析 styles.xml `<w:latentStyles>`(OOXML §17.7.4.6)
     *
     * Sprint 153(capture-only、styles/ 子目錄延伸):
     *   - 41/42 fixture 有 latentStyles(Word 預設骨架、平均 ~147 lsdException)
     *   - layout / render 不消費(latent styles 是 Word UI 'Style Gallery' 顯示用)
     *   - 為將來 Phase 6 docx export 對稱性鋪路(export 端要原樣重建 latentStyles)
     *
     * 解析結構:
     *   <w:latentStyles
     *     w:defLockedState="0"
     *     w:defUIPriority="99"
     *     w:defSemiHidden="1"
     *     w:defUnhideWhenUsed="1"
     *     w:defQFormat="0"
     *     w:count="267">
     *     <w:lsdException w:name="Normal" w:uiPriority="0" w:qFormat="1"/>
     *     <w:lsdException w:name="heading 1" ... />
     *     ...
     *   </w:latentStyles>
     *
     * 設計決策:
     *   - 與 StyleResolver 平行(StyleResolver 處理 <w:style>、本 parser 處理 <w:latentStyles>)
     *   - 紀律 #21:屬性不存在 → undefined、不掛 key
     *   - 紀律 #18:exceptions 用 Map<name, LatentStyleException>、不展開為陣列(便於 lookup)
     *   - 重複 name(理論不應發生)→ 後者覆蓋前者
     *
     * 防禦:undefined / 空 / XML 失敗 / 缺 root → 回 {}(不阻塞 OoxmlParser)。
     */
    class LatentStylesParser {
        /**
         * 從 styles.xml 字串中找 `<w:latentStyles>` 並解析。
         *
         * @param xml styles.xml 完整字串;undefined / 空 / 無 latentStyles → 回 {}
         */
        parse(xml) {
            if (!xml || !xml.trim())
                return {};
            let doc;
            try {
                doc = parseXml$1(xml);
            }
            catch {
                return {};
            }
            const root = doc.documentElement;
            if (!root)
                return {};
            // 找 latentStyles 子元素(在 <w:styles> 下層)
            const latentEl = findDirectChildByLocalName(root, 'latentStyles');
            if (!latentEl)
                return {};
            const out = {};
            // root 級 defaults(5 個 toggle/integer + count)
            assignToggle(out, 'defLockedState', latentEl, 'defLockedState');
            assignInt$1(out, 'defUIPriority', latentEl, 'defUIPriority');
            assignToggle(out, 'defSemiHidden', latentEl, 'defSemiHidden');
            assignToggle(out, 'defUnhideWhenUsed', latentEl, 'defUnhideWhenUsed');
            assignToggle(out, 'defQFormat', latentEl, 'defQFormat');
            assignInt$1(out, 'count', latentEl, 'count');
            // exceptions(0..N 個 lsdException 子元素)
            const exceptions = new Map();
            for (let i = 0; i < latentEl.childNodes.length; i++) {
                const n = latentEl.childNodes[i];
                if (n.nodeType !== 1)
                    continue;
                const el = n;
                if (localName$2(el) !== 'lsdException')
                    continue;
                const name = readAttr(el, 'name');
                if (!name)
                    continue; // 紀律 #21:無 name 跳過
                const ex = {};
                assignToggle(ex, 'locked', el, 'locked');
                assignInt$1(ex, 'uiPriority', el, 'uiPriority');
                assignToggle(ex, 'semiHidden', el, 'semiHidden');
                assignToggle(ex, 'unhideWhenUsed', el, 'unhideWhenUsed');
                assignToggle(ex, 'qFormat', el, 'qFormat');
                // 紀律 #21:全空的 exception 仍掛 key(name 本身已是資訊、e.g. 區分「存在 latent style」與「不存在」)
                exceptions.set(name, ex);
            }
            if (exceptions.size > 0) {
                out.exceptions = exceptions;
            }
            return out;
        }
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    /** 用 w:* prefix 讀屬性、xmldom 部分版本不能直接用 namespace lookup */
    function readAttr(el, localAttrName) {
        // 先試 w:name、再試 localName (defensive、實際 fixture 都用 w: prefix)
        const v = el.getAttribute(`w:${localAttrName}`);
        if (v !== null)
            return v;
        return el.getAttribute(localAttrName);
    }
    function assignToggle(out, key, el, attrName) {
        const v = readAttr(el, attrName);
        if (v === null)
            return; // 紀律 #21:屬性不存在 → undefined
        // OOXML toggle:"0"/"false" = false、否則 true(包含 "1"/"true"/空字串)
        out[key] = v !== '0' && v.toLowerCase() !== 'false';
    }
    function assignInt$1(out, key, el, attrName) {
        const v = readAttr(el, attrName);
        if (v === null)
            return;
        if (!/^-?\d+$/.test(v))
            return;
        const n = parseInt(v, 10);
        if (!Number.isFinite(n))
            return;
        out[key] = n;
    }
    function localName$2(el) {
        const ln = el.localName;
        if (ln)
            return ln;
        const tag = el.tagName;
        const colon = tag.indexOf(':');
        return colon >= 0 ? tag.substring(colon + 1) : tag;
    }
    function findDirectChildByLocalName(parent, target) {
        for (let i = 0; i < parent.childNodes.length; i++) {
            const n = parent.childNodes[i];
            if (n.nodeType !== 1)
                continue;
            const el = n;
            if (localName$2(el) === target)
                return el;
        }
        return null;
    }
    function parseXml$1(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('LatentStylesParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`LatentStylesParser: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * SectionParser — 解析 <w:sectPr>
     *
     * 職責：
     *   - 取得頁面尺寸 / margins / orientation
     *   - 取得欄位設定（cols count / space / equalWidth）
     *   - 取得 header/footer 引用 rId（default / first / even）
     *   - 取得 titlePg / evenAndOddHeaders 旗標
     *
     * 目前實作層級（Phase A — Sprint 0 通電）：
     *   - parse(sectPrEl): 解析最常見屬性（pgSz / pgMar / headerReference / footerReference / cols 基本欄位）
     *   - 找不到的屬性套 A4 預設值（縱向、四邊界 1 inch）
     *
     * Phase B Sprint 1 將補完：
     *   - <w:pgBorders>、<w:pgNumType>、<w:docGrid>、<w:lnNumType>
     *   - 多 section（依文件中多個 <w:sectPr> 切節）
     *   - <w:cols> 不等寬欄、<w:sep>、<w:space>
     */
    const A4_WIDTH_PT = 595.3; // 210mm
    const A4_HEIGHT_PT = 841.9; // 297mm
    const DEFAULT_MARGIN_PT = 72; // 1 inch
    const DEFAULT_HEADER_FOOTER_PT = 36; // 0.5 inch
    class SectionParser {
        /**
         * 解析單一 <w:sectPr> 元素為 SectionNode（不含 body）。
         *
         * 設計：本函式只負責「節屬性」，body（BlockNode[]）由呼叫端從
         * DocumentParser 走訪結果填入，避免重造段落/表格走訪邏輯。
         *
         * @param sectPrEl w:sectPr 元素；可為 undefined（沒有節屬性時用全預設值）
         * @returns SectionNode，body 欄位為空陣列由呼叫端填入
         */
        parse(sectPrEl) {
            const page = parsePageSize(sectPrEl);
            const margins = parseMargins(sectPrEl);
            const columns = parseColumns(sectPrEl);
            const { headerRefs, footerRefs } = parseHeaderFooterRefs(sectPrEl);
            const titlePage = boolFlag(directChild$1(sectPrEl, 'w:titlePg'));
            const sectionBreakType = parseSectionBreakType(sectPrEl);
            const docGrid = parseDocGrid(sectPrEl);
            const node = {
                type: 'section',
                page,
                margins,
                headerRefs,
                footerRefs,
                titlePage,
                evenAndOddHeaders: false, // 來自 settings.xml，由 OoxmlParser 注入；此層先設 false
                body: [], // 由 OoxmlParser orchestrator 填入
            };
            if (columns)
                node.columns = columns;
            // 只在非預設值時寫入，避免影響 04_ast_snapshot 的 snapshot 穩定性
            if (sectionBreakType && sectionBreakType !== 'nextPage') {
                node.sectionBreakType = sectionBreakType;
            }
            if (docGrid)
                node.docGrid = docGrid;
            return node;
        }
    }
    /** Sprint 29：解析 `<w:docGrid w:type="lines" w:linePitch="364"/>` */
    function parseDocGrid(sectPr) {
        const dg = directChild$1(sectPr, 'w:docGrid');
        if (!dg)
            return undefined;
        const typeRaw = dg.getAttribute('w:type');
        let type = 'default';
        if (typeRaw === 'lines')
            type = 'lines';
        else if (typeRaw === 'linesAndChars')
            type = 'linesAndChars';
        else if (typeRaw === 'snapToChars')
            type = 'snapToChars';
        const linePitchRaw = dg.getAttribute('w:linePitch');
        const linePitchTwip = linePitchRaw ? parseInt(linePitchRaw, 10) : NaN;
        const linePitch = Number.isFinite(linePitchTwip) ? twipToPt(linePitchTwip) : 0;
        // 'default' type 對 layout 沒影響（linePitch 是否有值都不 snap）→ 不寫入，保 snapshot 穩定
        if (type === 'default')
            return undefined;
        return { type, linePitch };
    }
    /** 解析 <w:type w:val="continuous|evenPage|oddPage|nextPage">；undefined → 預設 nextPage */
    function parseSectionBreakType(sectPr) {
        const t = directChild$1(sectPr, 'w:type');
        if (!t)
            return undefined;
        const val = t.getAttribute('w:val');
        if (val === 'continuous' || val === 'evenPage' || val === 'oddPage' || val === 'nextPage') {
            return val;
        }
        return undefined;
    }
    // ── 內部解析 ──────────────────────────────────────────────────────────────────
    function parsePageSize(sectPr) {
        const pgSz = directChild$1(sectPr, 'w:pgSz');
        if (!pgSz) {
            return { width: A4_WIDTH_PT, height: A4_HEIGHT_PT, orientation: 'portrait' };
        }
        const w = attrInt(pgSz, 'w:w');
        const h = attrInt(pgSz, 'w:h');
        const orientRaw = pgSz.getAttribute('w:orient');
        const orientation = orientRaw === 'landscape' ? 'landscape' : 'portrait';
        return {
            width: w !== undefined ? twipToPt(w) : A4_WIDTH_PT,
            height: h !== undefined ? twipToPt(h) : A4_HEIGHT_PT,
            orientation,
        };
    }
    function parseMargins(sectPr) {
        const pgMar = directChild$1(sectPr, 'w:pgMar');
        if (!pgMar) {
            return {
                top: DEFAULT_MARGIN_PT,
                bottom: DEFAULT_MARGIN_PT,
                left: DEFAULT_MARGIN_PT,
                right: DEFAULT_MARGIN_PT,
                header: DEFAULT_HEADER_FOOTER_PT,
                footer: DEFAULT_HEADER_FOOTER_PT,
            };
        }
        const top = attrTwip(pgMar, 'w:top') ?? DEFAULT_MARGIN_PT;
        const bottom = attrTwip(pgMar, 'w:bottom') ?? DEFAULT_MARGIN_PT;
        const left = attrTwip(pgMar, 'w:left') ?? attrTwip(pgMar, 'w:start') ?? DEFAULT_MARGIN_PT;
        const right = attrTwip(pgMar, 'w:right') ?? attrTwip(pgMar, 'w:end') ?? DEFAULT_MARGIN_PT;
        const header = attrTwip(pgMar, 'w:header') ?? DEFAULT_HEADER_FOOTER_PT;
        const footer = attrTwip(pgMar, 'w:footer') ?? DEFAULT_HEADER_FOOTER_PT;
        const gutter = attrTwip(pgMar, 'w:gutter');
        const out = { top, bottom, left, right, header, footer };
        if (gutter !== undefined)
            out.gutter = gutter;
        return out;
    }
    function parseColumns(sectPr) {
        const cols = directChild$1(sectPr, 'w:cols');
        if (!cols)
            return undefined;
        const count = attrInt(cols, 'w:num') ?? 1;
        if (count <= 1)
            return undefined; // 單欄不寫入
        const space = attrTwip(cols, 'w:space');
        const equalWidthRaw = cols.getAttribute('w:equalWidth');
        const equalWidth = equalWidthRaw === '0' || equalWidthRaw === 'false' ? false : true;
        const sepRaw = cols.getAttribute('w:sep');
        const separator = sepRaw === '1' || sepRaw === 'true';
        const out = { count, equalWidth };
        if (space !== undefined)
            out.space = space;
        if (separator)
            out.separator = true;
        // Sprint 6：抓個別 <w:col w:w="..." w:space="..."/>
        const colEls = directChildren$1(cols).filter((c) => c.tagName === 'w:col');
        if (colEls.length > 0 && !equalWidth) {
            const colWidths = [];
            const colSpaces = [];
            for (let i = 0; i < colEls.length; i++) {
                const w = attrTwip(colEls[i], 'w:w');
                if (w !== undefined)
                    colWidths.push(w);
                if (i < colEls.length - 1) {
                    const s = attrTwip(colEls[i], 'w:space');
                    if (s !== undefined)
                        colSpaces.push(s);
                }
            }
            if (colWidths.length > 0)
                out.colWidths = colWidths;
            if (colSpaces.length > 0)
                out.colSpaces = colSpaces;
        }
        return out;
    }
    function parseHeaderFooterRefs(sectPr) {
        const headerRefs = {};
        const footerRefs = {};
        if (!sectPr)
            return { headerRefs, footerRefs };
        for (const child of directChildren$1(sectPr)) {
            if (child.tagName === 'w:headerReference') {
                const type = child.getAttribute('w:type') ?? 'default';
                const rId = child.getAttribute('r:id') ?? child.getAttribute('w:id');
                if (rId && (type === 'default' || type === 'first' || type === 'even')) {
                    headerRefs[type] = rId;
                }
            }
            else if (child.tagName === 'w:footerReference') {
                const type = child.getAttribute('w:type') ?? 'default';
                const rId = child.getAttribute('r:id') ?? child.getAttribute('w:id');
                if (rId && (type === 'default' || type === 'first' || type === 'even')) {
                    footerRefs[type] = rId;
                }
            }
        }
        return { headerRefs, footerRefs };
    }
    // ── 共用工具（精簡版） ──────────────────────────────────────────────────────
    function directChildren$1(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild$1(el, tagName) {
        for (const child of directChildren$1(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    function attrInt(el, name) {
        const v = el.getAttribute(name);
        if (v === null)
            return undefined;
        const n = parseInt(v, 10);
        return Number.isFinite(n) ? n : undefined;
    }
    function attrTwip(el, name) {
        const n = attrInt(el, name);
        return n !== undefined ? twipToPt(n) : undefined;
    }
    function boolFlag(el) {
        if (!el)
            return false;
        const v = el.getAttribute('w:val');
        if (v === null)
            return true;
        return v !== '0' && v.toLowerCase() !== 'false';
    }

    /**
     * StyleResolver — word/styles.xml 樣式繼承鏈展開
     *
     * 解析三層繼承鏈：docDefaults → parent chain (basedOn) → current。
     * Resolver 完成後輸出已展開的 StyleMap，供 ParagraphParser / TableParser 直接合併。
     *
     * 演算法：
     *   1. 解析 <w:docDefaults>：rPrDefault / pPrDefault → 全域預設
     *   2. 第一遍走訪 <w:style>：收集每個 style 的 raw props + basedOn ID（不展開）
     *   3. 第二遍對每個 styleId：
     *        - DFS 走 basedOn 鏈（cycle detection 用 Set）
     *        - 從最遠祖先往下逐層 merge：docDefaults → ... → parent → current
     *        - 結果存入 StyleMap
     *
     * 注意：
     *   - 缺失的 basedOn（指向不存在的 styleId）視為無 parent，不 throw
     *   - 偵測到迴圈（A.basedOn=B, B.basedOn=A）時，停在 A，不 throw
     *   - <w:style w:type> 不限定為 paragraph：character / table / numbering 也保留
     *     供未來 TableParser / NumberingResolver 使用，目前只展開 pPr / rPr
     */
    class StyleResolver {
        constructor() {
            /** Phase 4.1：themeColor 解析時用的 ThemeMap（OoxmlParser 注入）。 */
            this.themeMap = null;
        }
        /**
         * 注入 ThemeMap。flattenStyle 走 parseRunProps / parseParagraphProps 時，
         * 透過共用的 module-scope `themeMapForParser`（位於 ParagraphParser）
         * 自動取得 ThemeMap，但本 class 也在 resolve() 開始時主動 set 一次以保險。
         */
        setThemeMap(theme) {
            this.themeMap = theme;
            // 同步傳遞給 module-scoped variable，讓 parseRunProps / parseParagraphProps 也能解
            // themeColor。允許獨立用 StyleResolver（測試）時 themeColor 仍能解析。
            setThemeMapForParser(theme);
        }
        /**
         * 解析 styles.xml 字串為展開後的 StyleMap。
         *
         * @param xml word/styles.xml 內容；undefined 時回空 Map
         */
        resolve(xml) {
            if (!xml)
                return new Map();
            const doc = parseXml(xml);
            const root = doc.documentElement;
            if (!root)
                return new Map();
            // Step 1：docDefaults
            const docDefaults = parseDocDefaults(root);
            // Step 2：raw 收集
            const raw = new Map();
            const styleEls = root.getElementsByTagName('w:style');
            for (let i = 0; i < styleEls.length; i++) {
                const entry = parseRawStyle(styleEls[i]);
                if (entry)
                    raw.set(entry.id, entry);
            }
            // Step 3：對每個 styleId 展開繼承鏈，merge 後寫入 StyleMap
            const out = new Map();
            for (const id of raw.keys()) {
                const flat = flattenStyle(id, raw, docDefaults);
                out.set(id, flat);
            }
            return out;
        }
    }
    function parseDocDefaults(root) {
        const out = {};
        const docDefaultsEl = directChild(root, 'w:docDefaults');
        if (!docDefaultsEl)
            return out;
        const rPrDefault = directChild(docDefaultsEl, 'w:rPrDefault');
        if (rPrDefault) {
            const rPr = directChild(rPrDefault, 'w:rPr');
            if (rPr)
                out.rPr = parseRunProps(rPr);
        }
        const pPrDefault = directChild(docDefaultsEl, 'w:pPrDefault');
        if (pPrDefault) {
            const pPr = directChild(pPrDefault, 'w:pPr');
            if (pPr)
                out.pPr = parseParagraphProps(pPr);
        }
        return out;
    }
    // ── 單一 <w:style> 解析（不展開繼承） ────────────────────────────────────────
    function parseRawStyle(styleEl) {
        const id = styleEl.getAttribute('w:styleId');
        if (!id)
            return undefined;
        const type = styleEl.getAttribute('w:type') ?? undefined;
        let basedOn;
        let pPr;
        let rPr;
        let conditional;
        for (const child of directChildren(styleEl)) {
            switch (child.tagName) {
                case 'w:basedOn': {
                    const v = child.getAttribute('w:val');
                    if (v)
                        basedOn = v;
                    break;
                }
                case 'w:pPr':
                    pPr = parseParagraphProps(child);
                    break;
                case 'w:rPr':
                    rPr = parseRunProps(child);
                    break;
                case 'w:tblStylePr': {
                    // 表格條件樣式：依 w:type（firstRow/lastRow/etc.）分類
                    const condType = child.getAttribute('w:type');
                    if (!condType)
                        break;
                    const condPPr = directChild(child, 'w:pPr');
                    const condRPr = directChild(child, 'w:rPr');
                    const condTcPr = directChild(child, 'w:tcPr');
                    const entry = {};
                    if (condPPr)
                        entry.pPr = parseParagraphProps(condPPr);
                    if (condRPr)
                        entry.rPr = parseRunProps(condRPr);
                    if (condTcPr) {
                        // Sprint 131：提取 cell-level 條件 props（shading + vAlign）
                        const cPr = parseConditionalTcPr(condTcPr);
                        if (cPr)
                            entry.cPr = cPr;
                    }
                    if (entry.pPr || entry.rPr || entry.cPr) {
                        if (!conditional)
                            conditional = new Map();
                        conditional.set(condType, entry);
                    }
                    break;
                }
            }
        }
        const out = { id };
        if (type)
            out.type = type;
        if (basedOn)
            out.basedOn = basedOn;
        if (pPr)
            out.pPr = pPr;
        if (rPr)
            out.rPr = rPr;
        if (conditional && conditional.size > 0)
            out.conditional = conditional;
        return out;
    }
    // ── 繼承鏈展開 ────────────────────────────────────────────────────────────────
    function flattenStyle(id, raw, docDefaults) {
        // Step 1：走 basedOn 鏈，從遠祖到本身的順序
        const chain = [];
        const seen = new Set();
        let cursor = id;
        while (cursor && !seen.has(cursor)) {
            seen.add(cursor);
            const entry = raw.get(cursor);
            if (!entry)
                break;
            chain.unshift(entry); // 越早加入 = 越遠祖先（merge 從遠祖開始）
            cursor = entry.basedOn;
        }
        // Step 2：merge 順序 docDefaults → 遠祖 → ... → 本身
        let pProps;
        let rProps;
        if (docDefaults.pPr)
            pProps = mergePProps$1(pProps, docDefaults.pPr);
        if (docDefaults.rPr)
            rProps = mergeRProps(rProps, docDefaults.rPr);
        for (const entry of chain) {
            if (entry.pPr)
                pProps = mergePProps$1(pProps, entry.pPr);
            if (entry.rPr)
                rProps = mergeRProps(rProps, entry.rPr);
        }
        const self = raw.get(id);
        const out = {};
        if (pProps)
            out.pProps = pProps;
        if (rProps)
            out.rProps = rProps;
        if (self?.basedOn)
            out.basedOn = self.basedOn;
        // 條件樣式直接保留（不參與 basedOn 繼承鏈），把 raw 內部的 pPr/rPr/cPr 轉成 AST 的 pProps/rProps/cProps
        if (self?.conditional) {
            const out2 = new Map();
            for (const [type, entry] of self.conditional) {
                const conv = {};
                if (entry.pPr)
                    conv.pProps = entry.pPr;
                if (entry.rPr)
                    conv.rProps = entry.rPr;
                if (entry.cPr)
                    conv.cProps = entry.cPr;
                out2.set(type, conv);
            }
            out.conditional = out2;
        }
        return out;
    }
    /**
     * Sprint 131：解析 `<w:tblStylePr w:type="firstRow"><w:tcPr>...</w:tcPr></w:tblStylePr>`
     * 內的 cell-level 條件 props。
     *
     * 只提取最常用的兩個：
     *   - w:shd → shading（header row 背景色）
     *   - w:vAlign → 垂直對齊
     *
     * 其他 tcPr 子元素（tcBorders/tcMar/noWrap/textDirection）defer 到未來 sprint。
     *
     * 缺值或全空時回 undefined（caller 用 if (cPr) 檢查是否掛 key）。
     */
    function parseConditionalTcPr(tcPr) {
        const out = {};
        const shdEl = directChild(tcPr, 'w:shd');
        if (shdEl) {
            const fill = shdEl.getAttribute('w:fill');
            const color = shdEl.getAttribute('w:color');
            const pattern = shdEl.getAttribute('w:val');
            const shd = {};
            if (fill)
                shd.fill = fill;
            if (color)
                shd.color = color;
            if (pattern)
                shd.pattern = pattern;
            if (shd.fill || shd.color || shd.pattern)
                out.shading = shd;
        }
        const vAlignEl = directChild(tcPr, 'w:vAlign');
        if (vAlignEl) {
            const v = vAlignEl.getAttribute('w:val');
            if (v === 'top' || v === 'center' || v === 'bottom')
                out.vAlign = v;
        }
        // 空集合不掛 key（紀律 #21 候選）
        if (!out.shading && !out.vAlign)
            return undefined;
        return out;
    }
    /**
     * 段落屬性合併：override 的非 undefined 值覆蓋 base，否則保留 base。
     * 對巢狀物件（indent / spacing / borders / shading）做淺合併（per-key 覆寫）。
     */
    function mergePProps$1(base, override) {
        const out = { ...(base ?? {}) };
        for (const key of Object.keys(override)) {
            const v = override[key];
            if (v === undefined)
                continue;
            if (key === 'indent' || key === 'spacing' || key === 'borders' || key === 'shading') {
                // 巢狀物件 per-key 合併
                const baseSub = (base?.[key] ?? {});
                const overSub = v;
                out[key] = { ...baseSub, ...overSub };
            }
            else {
                out[key] = v;
            }
        }
        return out;
    }
    /**
     * Run 屬性合併：純扁平，override 值覆蓋 base。
     */
    function mergeRProps(base, override) {
        const out = { ...(base ?? {}) };
        for (const key of Object.keys(override)) {
            const v = override[key];
            if (v === undefined)
                continue;
            out[key] = v;
        }
        return out;
    }
    // ── 共用工具 ──────────────────────────────────────────────────────────────────
    function directChildren(el) {
        if (!el)
            return [];
        const out = [];
        const cs = el.childNodes;
        for (let i = 0; i < cs.length; i++) {
            const n = cs[i];
            if (n.nodeType === 1)
                out.push(n);
        }
        return out;
    }
    function directChild(el, tagName) {
        for (const child of directChildren(el)) {
            if (child.tagName === tagName)
                return child;
        }
        return undefined;
    }
    function parseXml(xml) {
        if (typeof DOMParser === 'undefined') {
            throw new Error('StyleResolver: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0) {
            throw new Error(`StyleResolver: XML parse error — ${errors[0].textContent}`);
        }
        return doc;
    }

    /**
     * ParagraphStyleMerger — Sprint 19
     *
     * 把 styles.xml 解析後的 StyleEntry.pProps 合併進 ParagraphNode.props。
     *
     * 為什麼：
     *   - ParagraphParser 只解析 inline `<w:pPr>` 內的屬性
     *   - 但 OOXML 規格容許段落只透過 `<w:pStyle w:val="X"/>` 引用 styles.xml 中的
     *     pPr 預設值（如 keepNext / spacing / fontSize 等）
     *   - 沒這層合併，下游 Paginator 看不到 style-defined keepNext，無法做 R6 黏連判斷
     *
     * 合併規則（與 StyleResolver.mergePProps 一致）：
     *   - inline props 覆寫 style props（per-key）
     *   - 巢狀物件 indent / spacing / borders / shading 做淺合併
     *   - 未被 inline 覆寫的 style key 會落到 paragraph.props
     *
     * 範圍：
     *   - 走訪 sections[*].body 與 cell.content（遞迴入 nested table）
     *   - 不處理 header / footer 的段落（HeaderFooterContent.content）— Sprint 19 範圍
     *     先聚焦 main body；header/footer 樣式合併留 Sprint 20+
     */
    /**
     * 對 DocumentNode 的所有 body 段落 in-place 合併樣式。
     *
     * 特性：
     *   - mutate paragraph.props（不複製整個 AST）
     *   - 沒有 styleId、或對應 style 不存在 → 跳過
     *   - 對應 style.pProps 為 undefined → 跳過
     *
     * @returns 處理過的段落數量（debug 用）
     */
    function mergeParagraphStyles(doc) {
        if (doc.styles.size === 0)
            return 0;
        let count = 0;
        for (const sec of doc.sections) {
            count += mergeBlocks(sec.body, doc.styles);
        }
        return count;
    }
    function mergeBlocks(blocks, styles) {
        let count = 0;
        for (const block of blocks) {
            if (block.type === 'paragraph') {
                if (mergeParagraph(block, styles))
                    count++;
            }
            else if (block.type === 'table') {
                for (const row of block.rows) {
                    for (const cell of row.cells) {
                        if (cell.content)
                            count += mergeBlocks(cell.content, styles);
                    }
                }
            }
        }
        return count;
    }
    /**
     * 對單一段落合併樣式。回 true 表示有實際合併動作。
     *
     * 規則：
     *   - 沒 styleId → 跳過
     *   - 樣式不存在 → 跳過
     *   - 樣式無 pProps → 跳過
     *   - 否則：para.props = mergePProps(stylePProps, para.props)
     */
    function mergeParagraph(para, styles) {
        if (!para.styleId)
            return false;
        const styleEntry = styles.get(para.styleId);
        if (!styleEntry || !styleEntry.pProps)
            return false;
        para.props = mergePProps(styleEntry.pProps, para.props);
        return true;
    }
    /**
     * pProps merge：override（inline）覆寫 base（style）。
     *
     * 與 StyleResolver.mergePProps 邏輯一致；複製到此檔案避免循環依賴
     * （StyleResolver import ParagraphParser；ParagraphStyleMerger 只 import types）。
     */
    function mergePProps(base, override) {
        const out = { ...base };
        for (const key of Object.keys(override)) {
            const v = override[key];
            if (v === undefined)
                continue;
            if (key === 'indent' || key === 'spacing' || key === 'borders' || key === 'shading') {
                const baseSub = (base[key] ?? {});
                const overSub = v;
                out[key] = { ...baseSub, ...overSub };
            }
            else {
                out[key] = v;
            }
        }
        return out;
    }

    /**
     * DocPropsParser — 解析 docProps/core.xml（Sprint 13）
     *
     * OOXML §22.2 + Dublin Core + Open Packaging Conventions：
     *   docProps/core.xml 內含文件 metadata，root = `<cp:coreProperties>`。
     *
     * 範例：
     *   <cp:coreProperties xmlns:cp="..." xmlns:dc="..." xmlns:dcterms="...">
     *     <dc:title>監造日誌</dc:title>
     *     <dc:creator>張三</dc:creator>
     *     <cp:lastModifiedBy>李四</cp:lastModifiedBy>
     *     <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-15T08:30:00Z</dcterms:created>
     *     <dcterms:modified>2026-05-08T10:00:00Z</dcterms:modified>
     *   </cp:coreProperties>
     *
     * 取值規則：
     *   - 找不到 docProps/core.xml → 空 docProps {}
     *   - XML 解析失敗 → 空 docProps（不 throw）
     *   - 欄位空字串 → undefined
     *
     * 為何不在 OoxmlParser.parse 內 inline：
     *   - 邏輯獨立：純 XML lookup，沒有 cross-part 依賴
     *   - 易於 mock / unit test
     *   - 未來擴展 docProps/app.xml（Application / Pages / Words 等）時加同檔即可
     */
    // 慣例：使用 global DOMParser（瀏覽器原生；vitest 由 tests/setup.ts 注入 @xmldom/xmldom）
    // 避免直接 import @xmldom/xmldom 造成 Element 型別與 DOM lib 衝突
    const REL_TYPE_CORE_PROPERTIES = 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties';
    /**
     * 從 OoxmlPackage 讀 docProps/core.xml（透過 root .rels 找路徑），回傳結構化 DocProps。
     *
     * 找不到 part 或解析失敗皆回 `{}`（不 throw）。
     */
    function parseDocProps(pkg) {
        const corePath = findCorePropertiesPath(pkg);
        if (!corePath)
            return {};
        const xml = pkg.partAsText(corePath);
        if (!xml)
            return {};
        try {
            return parseDocPropsXml(xml);
        }
        catch {
            return {};
        }
    }
    /** 純 XML 字串解析版本（測試用，不依賴 OoxmlPackage）。 */
    function parseDocPropsXml(xml) {
        if (!xml || !xml.trim())
            return {};
        if (typeof DOMParser === 'undefined') {
            throw new Error('DocPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        let doc;
        try {
            doc = new DOMParser().parseFromString(xml, 'text/xml');
        }
        catch {
            return {};
        }
        if (!doc || !doc.documentElement)
            return {};
        const root = doc.documentElement;
        const out = {};
        const title = pickText(root, ['dc:title', 'title']);
        if (title)
            out.title = title;
        const creator = pickText(root, ['dc:creator', 'creator']);
        if (creator)
            out.creator = creator;
        const subject = pickText(root, ['dc:subject', 'subject']);
        if (subject)
            out.subject = subject;
        const description = pickText(root, ['dc:description', 'description']);
        if (description)
            out.description = description;
        const keywords = pickText(root, ['cp:keywords', 'keywords']);
        if (keywords)
            out.keywords = keywords;
        const lastModifiedBy = pickText(root, ['cp:lastModifiedBy', 'lastModifiedBy']);
        if (lastModifiedBy)
            out.lastModifiedBy = lastModifiedBy;
        const created = pickText(root, ['dcterms:created', 'created']);
        if (created)
            out.created = created;
        const modified = pickText(root, ['dcterms:modified', 'modified']);
        if (modified)
            out.modified = modified;
        return out;
    }
    /**
     * 從 root .rels 中找 core-properties 關聯的 part path。
     *
     * Conventions：core.xml 通常在 `docProps/core.xml`，但 spec 不強制路徑，
     * 必須走 .rels 解析；若 rels 沒列就 fallback 慣例路徑。
     */
    function findCorePropertiesPath(pkg) {
        const rootRels = pkg.relationships.get('') ?? new Map();
        for (const rel of rootRels.values()) {
            if (rel.type === REL_TYPE_CORE_PROPERTIES && rel.targetMode === 'Internal') {
                return rel.target;
            }
        }
        // fallback 慣例路徑
        if (pkg.parts.has('docProps/core.xml'))
            return 'docProps/core.xml';
        return undefined;
    }
    /** 在 root 內找指定 tag（依序 try 多個候選名稱），回 trim 後文字內容。 */
    function pickText(root, candidates) {
        for (const name of candidates) {
            // 先試 qualified name（含 prefix），再試 localName
            const els = root.getElementsByTagName(name);
            if (els.length > 0 && els[0].textContent) {
                return els[0].textContent.trim();
            }
        }
        return '';
    }

    /**
     * AppPropsParser — 解析 docProps/app.xml(OOXML §22.2、extended-properties)
     *
     * Sprint 150(capture-only、autonomous-friendly §11.2 backlog):
     *   - 42/42 fixture 都有 app.xml(Word/WPS 預設骨架)、17 elements 出現頻率 100%
     *   - layout / render 不消費、為將來 Phase 6 docx export 對稱性鋪路
     *   - 沿用 Sprint 145-148 capture-only 9-step archetype
     *
     * 解析範圍(17 elements):
     *   字串:Template / Application / AppVersion / Company
     *   整數:Pages / Words / Characters / Lines / Paragraphs / TotalTime /
     *         CharactersWithSpaces / DocSecurity(enum、capture 階段以整數保留)
     *   布林:ScaleCrop / LinksUpToDate / SharedDoc / HyperlinksChanged
     *
     * 設計決策:
     *   - 與 DocPropsParser(core.xml)平行架構、不合併成同檔避免擴大 PR
     *   - 紀律 #21:空字串 / 0 long / 非數字 字串 → undefined(不掛 key)
     *   - 布林採嚴格 "true"/"false" 字串比對(不接受 "1"/"0"、依規格)
     *   - 與 ext-properties namespace 共存,但只認元素 local-name(忽略 ns prefix)
     *
     * 防禦:undefined / 空 / XML 失敗 → 回 {}(不阻塞 OoxmlParser)。
     */
    const REL_TYPE_EXTENDED_PROPERTIES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties';
    /**
     * 從 OoxmlPackage 讀 docProps/app.xml(透過 root .rels 找路徑),回傳結構化 DocPropsApp。
     *
     * 找不到 part 或解析失敗皆回 `{}`(不 throw、紀律 #21)。
     */
    function parseAppProps(pkg) {
        const path = findAppPropertiesPath(pkg);
        if (!path)
            return {};
        const xml = pkg.partAsText(path);
        if (!xml)
            return {};
        try {
            return parseAppPropsXml(xml);
        }
        catch {
            return {};
        }
    }
    /** 純 XML 字串解析版本(測試用、不依賴 OoxmlPackage)。 */
    function parseAppPropsXml(xml) {
        if (!xml || !xml.trim())
            return {};
        if (typeof DOMParser === 'undefined') {
            throw new Error('AppPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        let doc;
        try {
            doc = new DOMParser().parseFromString(xml, 'application/xml');
        }
        catch {
            return {};
        }
        if (!doc || !doc.documentElement)
            return {};
        // pParse 失敗:某些 DOMParser 不 throw、而是回傳含 parsererror 的 doc
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0)
            return {};
        const root = doc.documentElement;
        const out = {};
        for (let i = 0; i < root.childNodes.length; i++) {
            const n = root.childNodes[i];
            if (n.nodeType !== 1)
                continue;
            const el = n;
            const tag = localName$1(el);
            switch (tag) {
                case 'Template':
                    assignString(out, 'template', el);
                    break;
                case 'Application':
                    assignString(out, 'application', el);
                    break;
                case 'AppVersion':
                    assignString(out, 'appVersion', el);
                    break;
                case 'Company':
                    assignString(out, 'company', el);
                    break;
                case 'TotalTime':
                    assignInt(out, 'totalTime', el);
                    break;
                case 'Pages':
                    assignInt(out, 'pages', el);
                    break;
                case 'Words':
                    assignInt(out, 'words', el);
                    break;
                case 'Characters':
                    assignInt(out, 'characters', el);
                    break;
                case 'CharactersWithSpaces':
                    assignInt(out, 'charactersWithSpaces', el);
                    break;
                case 'Lines':
                    assignInt(out, 'lines', el);
                    break;
                case 'Paragraphs':
                    assignInt(out, 'paragraphs', el);
                    break;
                case 'DocSecurity':
                    assignInt(out, 'docSecurity', el);
                    break;
                case 'ScaleCrop':
                    assignBool(out, 'scaleCrop', el);
                    break;
                case 'LinksUpToDate':
                    assignBool(out, 'linksUpToDate', el);
                    break;
                case 'SharedDoc':
                    assignBool(out, 'sharedDoc', el);
                    break;
                case 'HyperlinksChanged':
                    assignBool(out, 'hyperlinksChanged', el);
                    break;
            }
        }
        return out;
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    /**
     * 從 root .rels 中找 extended-properties 關聯的 part path。
     *
     * Conventions:app.xml 通常在 `docProps/app.xml`、但 spec 不強制路徑、
     * 必須走 .rels 解析;若 rels 沒列就 fallback 慣例路徑。
     */
    function findAppPropertiesPath(pkg) {
        const rootRels = pkg.relationships.get('') ?? new Map();
        for (const rel of rootRels.values()) {
            if (rel.type === REL_TYPE_EXTENDED_PROPERTIES && rel.targetMode === 'Internal') {
                return rel.target;
            }
        }
        // fallback 慣例路徑
        if (pkg.parts.has('docProps/app.xml'))
            return 'docProps/app.xml';
        return undefined;
    }
    /** 取元素 local-name(忽略 namespace prefix);xmldom 部分版本 localName 為空字串 */
    function localName$1(el) {
        const ln = el.localName;
        if (ln)
            return ln;
        const tag = el.tagName;
        const colon = tag.indexOf(':');
        return colon >= 0 ? tag.substring(colon + 1) : tag;
    }
    function assignString(out, key, el) {
        const text = (el.textContent || '').trim();
        if (!text)
            return; // 紀律 #21
        out[key] = text;
    }
    function assignInt(out, key, el) {
        const text = (el.textContent || '').trim();
        if (!text)
            return;
        // 嚴格整數;不接受小數、不接受非數字字元
        if (!/^-?\d+$/.test(text))
            return;
        const n = parseInt(text, 10);
        if (!Number.isFinite(n))
            return;
        out[key] = n;
    }
    function assignBool(out, key, el) {
        const text = (el.textContent || '').trim().toLowerCase();
        if (text === 'true') {
            out[key] = true;
        }
        else if (text === 'false') {
            out[key] = false;
        }
        // 其他值(包含空字串)不掛 key、紀律 #21
    }

    /**
     * CustomPropsParser — 解析 docProps/custom.xml(OOXML §22.3、custom-properties)
     *
     * Sprint 151(capture-only、Sprint 150 doc-props 子目錄延續):
     *   - 25/42 fixture 有 custom.xml(WPS KSOProductBuildVer × 24 + Grammarly × 14)
     *   - 17 fixture 無此 part(無 SaaS app stamp、純 Word 預設)
     *   - 沿用 Sprint 150 doc-props 子目錄、結構單純(property bag)
     *
     * 解析結構:
     *   <Properties xmlns="...custom-properties" xmlns:vt="...docPropsVTypes">
     *     <property fmtid="..." pid="2" name="KSOProductBuildVer">
     *       <vt:lpwstr>1028-10.8.0.6003</vt:lpwstr>
     *     </property>
     *   </Properties>
     *
     * 支援 variant(scope-down、紀律 #18):
     *   - vt:lpwstr / vt:lpstr / vt:bstr → kind: 'string'
     *   - vt:i4 / vt:i8 / vt:int / vt:uint → kind: 'int'
     *   - vt:bool → kind: 'bool'
     *   - vt:r4 / vt:r8 / vt:decimal → kind: 'real'
     *   - vt:filetime / vt:date → kind: 'filetime'(原 ISO 字串、不轉 Date)
     *   - 其他 variant → kind: 'unknown'(保留 raw textContent)
     *
     * 設計決策:
     *   - fmtid / pid 不保留(紀律 #18 scope-down、name 已足以作為 key)
     *   - name 重複(理論上不該發生)時後者覆蓋前者(Map.set 行為)
     *   - 缺 name 屬性或 name 為空字串 → 跳過該 property(不掛 key、紀律 #21)
     *
     * 防禦:undefined / 空 / XML 失敗 → 回空 Map(不阻塞 OoxmlParser)。
     */
    const REL_TYPE_CUSTOM_PROPERTIES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties';
    /**
     * 從 OoxmlPackage 讀 docProps/custom.xml(透過 root .rels 找路徑),回傳結構化 DocPropsCustom。
     *
     * 找不到 part 或解析失敗皆回空 Map(不 throw)。
     */
    function parseCustomProps(pkg) {
        const path = findCustomPropertiesPath(pkg);
        if (!path)
            return new Map();
        const xml = pkg.partAsText(path);
        if (!xml)
            return new Map();
        try {
            return parseCustomPropsXml(xml);
        }
        catch {
            return new Map();
        }
    }
    /** 純 XML 字串解析版本(測試用、不依賴 OoxmlPackage)。 */
    function parseCustomPropsXml(xml) {
        const out = new Map();
        if (!xml || !xml.trim())
            return out;
        if (typeof DOMParser === 'undefined') {
            throw new Error('CustomPropsParser: DOMParser not available — Node tests must use vitest setup with @xmldom/xmldom');
        }
        let doc;
        try {
            doc = new DOMParser().parseFromString(xml, 'application/xml');
        }
        catch {
            return out;
        }
        if (!doc || !doc.documentElement)
            return out;
        const errors = doc.getElementsByTagName('parsererror');
        if (errors.length > 0)
            return out;
        const root = doc.documentElement;
        for (let i = 0; i < root.childNodes.length; i++) {
            const n = root.childNodes[i];
            if (n.nodeType !== 1)
                continue;
            const el = n;
            if (localName(el) !== 'property')
                continue;
            const name = (el.getAttribute('name') || '').trim();
            if (!name)
                continue; // 紀律 #21:無 name 跳過
            const variant = firstElementChild(el);
            if (!variant)
                continue; // 無 value 跳過
            const value = parseVariant(variant);
            if (value === null)
                continue;
            out.set(name, value);
        }
        return out;
    }
    // ── 內部 helpers ──────────────────────────────────────────────────────────
    /**
     * 從 root .rels 中找 custom-properties 關聯的 part path。
     *
     * 與 app.xml 同模式:走 root .rels、fallback 慣例路徑。
     */
    function findCustomPropertiesPath(pkg) {
        const rootRels = pkg.relationships.get('') ?? new Map();
        for (const rel of rootRels.values()) {
            if (rel.type === REL_TYPE_CUSTOM_PROPERTIES && rel.targetMode === 'Internal') {
                return rel.target;
            }
        }
        // fallback 慣例路徑
        if (pkg.parts.has('docProps/custom.xml'))
            return 'docProps/custom.xml';
        return undefined;
    }
    /** 把 vt:* 子元素解析為 CustomPropertyValue。 */
    function parseVariant(el) {
        const tag = localName(el);
        const text = (el.textContent || '').trim();
        switch (tag) {
            case 'lpwstr':
            case 'lpstr':
            case 'bstr':
                // 字串:空字串合法(允許「顯式設為空」、非紀律 #21 範圍)
                return { kind: 'string', value: text };
            case 'i4':
            case 'i8':
            case 'int':
            case 'uint': {
                if (!/^-?\d+$/.test(text))
                    return null;
                const n = parseInt(text, 10);
                return Number.isFinite(n) ? { kind: 'int', value: n } : null;
            }
            case 'bool': {
                const lc = text.toLowerCase();
                if (lc === 'true' || lc === '1')
                    return { kind: 'bool', value: true };
                if (lc === 'false' || lc === '0')
                    return { kind: 'bool', value: false };
                return null;
            }
            case 'r4':
            case 'r8':
            case 'decimal': {
                const n = parseFloat(text);
                return Number.isFinite(n) ? { kind: 'real', value: n } : null;
            }
            case 'filetime':
            case 'date':
                // 保留原 ISO 字串(紀律 #18 不轉 Date、避免 timezone 副作用)
                return text ? { kind: 'filetime', value: text } : null;
            default:
                // 其他 variant(vt:vector / vt:cy / vt:storage 等)降級保留 raw
                return { kind: 'unknown', raw: text };
        }
    }
    /** 取元素 local-name(忽略 namespace prefix);xmldom 部分版本 localName 為空 */
    function localName(el) {
        const ln = el.localName;
        if (ln)
            return ln;
        const tag = el.tagName;
        const colon = tag.indexOf(':');
        return colon >= 0 ? tag.substring(colon + 1) : tag;
    }
    /** 取第一個 Element 子節點(忽略 text node 與註解)。 */
    function firstElementChild(el) {
        for (let i = 0; i < el.childNodes.length; i++) {
            const n = el.childNodes[i];
            if (n.nodeType === 1)
                return n;
        }
        return null;
    }

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
    const REL_TYPE_OFFICE_DOCUMENT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument';
    const REL_TYPE_STYLES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles';
    const REL_TYPE_NUMBERING = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering';
    const REL_TYPE_HEADER = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header';
    const REL_TYPE_FOOTER = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer';
    const REL_TYPE_FOOTNOTES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes';
    const REL_TYPE_ENDNOTES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes';
    const REL_TYPE_COMMENTS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments';
    const REL_TYPE_SETTINGS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings';
    const REL_TYPE_FONT_TABLE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable';
    const REL_TYPE_WEB_SETTINGS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings';
    const REL_TYPE_IMAGE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image';
    const REL_TYPE_DIAGRAM_DATA = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData';
    const REL_TYPE_CHART = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart';
    const DEFAULT_DOC_PATH = 'word/document.xml';
    class OoxmlParser {
        constructor() {
            this.packageReader = new PackageReader();
            this.styleResolver = new StyleResolver();
            this.numberingResolver = new NumberingResolver();
            this.sectionParser = new SectionParser();
            // 共用 Document/Table/HeaderFooter 解析鏈：
            //   - DocumentParser 持有 TableParser（透過建構子注入）
            //   - TableParser 第一次 parse cell 時會 lazy 建立 own DocumentParser，
            //     反向把自己（this TableParser）注入該 DP，循環安全閉環，無無窮 new。
            //   - HeaderFooterParser 共用 OoxmlParser 持有的 DocumentParser，
            //     確保 header/footer 內表格也走同一條 TableParser 解析鏈。
            this.tableParser = new TableParser();
            this.documentParser = new DocumentParser(this.tableParser);
            this.headerFooterParser = new HeaderFooterParser(this.documentParser);
            /** Sprint 145：footnotes / endnotes 重用 documentParser、與 header/footer 對齊 */
            this.footnotesParser = new FootnotesParser(this.documentParser);
            /** Sprint 146：settings.xml capture-only */
            this.settingsParser = new SettingsParser();
            /** Sprint 147：fontTable.xml capture-only */
            this.fontTableParser = new FontTableParser();
            /** Sprint 148：webSettings.xml capture-only(結束 Phase 1 part 三連 cluster)*/
            this.webSettingsParser = new WebSettingsParser();
            /** Sprint 153：styles.xml `<w:latentStyles>` capture-only */
            this.latentStylesParser = new LatentStylesParser();
            /** Sprint 171：document.xml `<w:background>` 文件背景（Phase 5.6 浮水印 + 背景）*/
            this.backgroundParser = new BackgroundParser();
            /** Sprint 172：header VML 浮水印 shape capture（Phase 5.6 浮水印 + 背景）*/
            this.watermarkParser = new WatermarkParser();
            /** Sprint 176：comments.xml 註解 capture（Phase 5.5 註解）*/
            this.commentsParser = new CommentsParser();
            /** Sprint 181：SmartArt diagrams/dataN.xml capture（Phase 5.2 SmartArt、mc:Fallback 壓縮）*/
            this.diagramParser = new DiagramParser();
            /** Sprint 182：Chart charts/chartN.xml capture（Phase 5.3 Charts、mc:Fallback 壓縮）*/
            this.chartParser = new ChartParser();
        }
        /**
         * 把 .docx ArrayBuffer 解析為 DocumentNode。
         *
         * @throws Error 如果不是有效 OOXML 包（ZIP 損壞、缺 [Content_Types].xml、缺 mainDocument 關聯）
         */
        parse(buffer, _options = {}) {
            // Step 1：解 ZIP
            const pkg = this.packageReader.parse(buffer);
            // Step 2：找 mainDocument 路徑
            const mainDocPath = findMainDocumentPath(pkg) ?? DEFAULT_DOC_PATH;
            const documentXml = pkg.partAsText(mainDocPath);
            if (!documentXml) {
                throw new Error(`OoxmlParser: main document part not found at "${mainDocPath}"`);
            }
            // Step 2.5：注入 hyperlink rels lookup
            //   ParagraphParser.parseHyperlinkInfo 透過此函式把 rId → External URL
            //   - mainDoc rels：負責本文 hyperlink
            //   - 注意：header/footer 的 hyperlink 在各自 part 的 rels；目前 lookup 只覆蓋 mainDoc
            //     若 fixture 中出現 header hyperlink，可在 collectHeadersFooters 中 per-part 注入
            this.documentParser.setRelsLookup((rId) => readExternalUrl(pkg, mainDocPath, rId));
            // Step 2.6：解析 theme1.xml 並注入 ThemeMap（Phase 4.1）
            //   parser 階段把 themeColor/themeTint/themeShade reference 解為具體 hex
            //   缺檔 / 解析失敗：用 DEFAULT_THEME_MAP（Office 預設色）降級
            const themeMap = parseTheme(pkg) ?? DEFAULT_THEME_MAP;
            this.documentParser.setThemeMap(themeMap);
            this.styleResolver.setThemeMap(themeMap);
            // Step 3：Styles / Numbering（Phase A 為空 Map）
            const stylesXml = readRelatedPart(pkg, mainDocPath, REL_TYPE_STYLES);
            const styles = this.styleResolver.resolve(stylesXml);
            const numbering = this.numberingResolver.resolve(readRelatedPart(pkg, mainDocPath, REL_TYPE_NUMBERING));
            // Step 3.1（Sprint 153）：latentStyles capture — 與 StyleResolver 平行運作、不影響 active styles
            const latentStyles = this.latentStylesParser.parse(stylesXml);
            // Step 3.5：注入 StyleMap 給 TableParser（Phase 4.2 條件樣式套用用）
            this.tableParser.setStyleMap(styles);
            // Step 4-5：走訪 body 並切多 section
            const rawSections = this.documentParser.walkBodyAsSections(documentXml);
            const sections = rawSections.map((rs) => {
                const sec = this.sectionParser.parse(rs.sectPrEl);
                sec.body = rs.blocks;
                return sec;
            });
            // Step 6：Headers / Footers
            const headers = new Map();
            const footers = new Map();
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
            const doc = {
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
    function findMainDocumentPath(pkg) {
        const rootRels = pkg.relationships.get('') ?? new Map();
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
    function readRelatedPart(pkg, mainDocPath, relType) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return undefined;
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
    function readExternalUrl(pkg, partPath, rId) {
        const rels = pkg.relationships.get(partPath);
        if (!rels)
            return undefined;
        const rel = rels.get(rId);
        if (!rel)
            return undefined;
        return rel.targetMode === 'External' ? rel.target : undefined;
    }
    /**
     * 走訪 mainDoc 的 .rels，把所有 header*.xml / footer*.xml 解析為 HeaderFooterContent
     * 並以 rId 為 key 存入兩個 Map。
     */
    function collectHeadersFooters(pkg, mainDocPath, parser, headers, footers) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return;
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal')
                continue;
            if (rel.type === REL_TYPE_HEADER) {
                const xml = pkg.partAsText(rel.target);
                if (xml === undefined)
                    continue;
                headers.set(rel.id, parser.parse(xml, rel.id));
            }
            else if (rel.type === REL_TYPE_FOOTER) {
                const xml = pkg.partAsText(rel.target);
                if (xml === undefined)
                    continue;
                footers.set(rel.id, parser.parse(xml, rel.id));
            }
        }
    }
    /**
     * Sprint 176：走訪 mainDoc 的 .rels、抓 comments.xml part 並解析。
     *
     * @returns Map<id, CommentContent>；rels 沒指向 comments 時回空 Map
     */
    function collectComments(pkg, mainDocPath, parser) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return new Map();
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_COMMENTS)
                continue;
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
    function collectWatermark(pkg, mainDocPath, parser) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return undefined;
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_HEADER)
                continue;
            const xml = pkg.partAsText(rel.target);
            const wm = parser.parse(xml);
            if (wm)
                return wm;
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
    function collectSmartArts(pkg, mainDocPath, parser) {
        const out = [];
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return out;
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_DIAGRAM_DATA)
                continue;
            const node = parser.parse(pkg.partAsText(rel.target), rel.id);
            if (node)
                out.push(node);
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
    function collectCharts(pkg, mainDocPath, parser) {
        const out = [];
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return out;
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal' || rel.type !== REL_TYPE_CHART)
                continue;
            const node = parser.parse(pkg.partAsText(rel.target), rel.id);
            if (node)
                out.push(node);
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
    function collectNotes(pkg, mainDocPath, parser, relType) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return new Map();
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal')
                continue;
            if (rel.type !== relType)
                continue;
            const xml = pkg.partAsText(rel.target);
            return parser.parse(xml); // 找到第一個就回（footnotes/endnotes 各最多 1 個 part）
        }
        return new Map();
    }
    /**
     * Sprint 146：走訪 mainDoc 的 .rels、抓 settings.xml part 並解析。
     *
     * @returns DocumentSettings；rels 沒指向 settings 時回 {}（capture-only safety）
     */
    function collectSettings(pkg, mainDocPath, parser) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return {};
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal')
                continue;
            if (rel.type !== REL_TYPE_SETTINGS)
                continue;
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
    function collectFontTable(pkg, mainDocPath, parser) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return new Map();
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal')
                continue;
            if (rel.type !== REL_TYPE_FONT_TABLE)
                continue;
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
    function collectWebSettings(pkg, mainDocPath, parser) {
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return {};
        for (const rel of rels.values()) {
            if (rel.targetMode !== 'Internal')
                continue;
            if (rel.type !== REL_TYPE_WEB_SETTINGS)
                continue;
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
    function collectMedia(pkg, mainDocPath) {
        const out = new Map();
        const rels = pkg.relationships.get(mainDocPath);
        if (!rels)
            return out;
        for (const rel of rels.values()) {
            if (rel.type !== REL_TYPE_IMAGE || rel.targetMode !== 'Internal')
                continue;
            const part = pkg.parts.get(rel.target);
            if (!part)
                continue;
            out.set(rel.id, partToDataUrl(part));
        }
        return out;
    }
    /**
     * 把 PackagePart 編碼為 data URL。
     *
     * 兼容 Node（Buffer）與瀏覽器（btoa + Uint8Array → 字串）兩個環境。
     */
    function partToDataUrl(part) {
        const mime = part.contentType || guessImageMime(part.path) || 'application/octet-stream';
        const b64 = toBase64(part.data);
        return `data:${mime};base64,${b64}`;
    }
    function guessImageMime(path) {
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
    function toBase64(bytes) {
        // Node.js 環境
        const g = globalThis;
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
        const btoa = globalThis.btoa;
        if (typeof btoa === 'function')
            return btoa(bin);
        throw new Error('OoxmlParser: no base64 encoder available (need Buffer or btoa)');
    }
    // 旁路：方便外部探測 stub 是否已連通
    const __DOBTOR_OOXML_STUB__ = 'phase-a';

    /**
     * numberingCounter — 文件走訪時維護「numId × ilvl」清單編號計數器
     *
     * 純函式狀態機（無 side effect 對外、內部 Map 為 state holder）。
     *
     * 用途：
     *   走訪 DocumentNode.sections 時、對每個 paragraph 若帶 numId、
     *   呼叫 `state.advance(numId, ilvl, abstractNumbering)` 取得當前序號字串
     *   與展開後的 counter 序列（給 indent / pPr 套用）。
     *
     * OOXML 規則（ECMA-376 Part 1 §17.9）：
     *   - 每個 numId 維護 levels[ilvl] 0–8 的獨立計數器
     *   - 首次出現某 ilvl：counter = levels[ilvl].start
     *   - 再次出現同 ilvl 同 numId：counter += 1
     *   - 跳到較淺層（ilvl 變小）：保留淺層 counter、reset 所有「深層 ilvl > current」counters
     *     → 下次再出現深層 ilvl 時重新從 start 起算
     *   - `lvlRestart` 屬性：levels[X].lvlRestart = N 表示「遇到 ilvl < N 的段落時、ilvl X 重啟」
     *     - 預設行為 = lvlRestart 等於 ilvl（深層遇淺層自動 reset）
     *     - 顯式 lvlRestart = 0 表示「永不重啟」（編號跨章節連續）
     *
     * 不負責：
     *   - lvlText 模板展開（由 numberingFormatter.expandLvlText 處理）
     *   - bullet 字元產生（bullet numFmt 由 lvlText 直接給字元）
     *   - 縮排計算（由 caller 從 levels[ilvl].indent 取）
     *
     * 紀律 #21（optional 空集合不掛 key）：返回 counters 陣列只含 0..ilvl（不掛深層 undefined）
     */
    /**
     * 清單編號計數器狀態 holder。
     *
     * 每個 numId 維護 levels[ilvl] 0–8 的計數值 + 首次出現旗標（用於判定是否套 start）。
     * 跨 numId 的 counter 互相獨立（OOXML 規範）。
     *
     * Lifecycle：
     *   const counter = new NumberingCounterState();
     *   for each paragraph with numId:
     *     const result = counter.advance(numId, ilvl, abstractNum);
     *     // result.counters → expandLvlText(level.text, result.counters, result.numFmts)
     */
    class NumberingCounterState {
        constructor() {
            /** numId → counters[ilvl]（-1 = 未初始化、0+ = 已 set 過 counter）*/
            this.state = new Map();
        }
        /**
         * 推進一個 numbered paragraph 的計數器、回傳當前序號狀態。
         *
         * @param numId             paragraph.props.numId
         * @param ilvl              paragraph.props.ilvl（預設 0）
         * @param abstractNumbering NumberingMap.get(numId)；undefined 視為空清單 placeholder
         * @returns                 AdvanceResult；abstractNumbering 缺 ilvl 對應 level 時、
         *                          回傳 placeholder level (numFmt='decimal', text='%1.', start=1)
         */
        advance(numId, ilvl, abstractNumbering) {
            // 取得或初始化此 numId 的 counters 陣列
            let counters = this.state.get(numId);
            if (!counters) {
                counters = new Array(9).fill(-1); // -1 = 未初始化
                this.state.set(numId, counters);
            }
            // 取得 level 定義（缺失時用 placeholder、不污染 state）
            const level = findLevel(abstractNumbering, ilvl) ?? placeholderLevel(ilvl);
            // 計算 lvlRestart 規則：
            //   - 顯式 lvlRestart = 0 → 永不 reset 深層
            //   - 顯式 lvlRestart = N → 遇 ilvl < N 時 reset 此 level
            //   - 未指定 → 預設行為（深層遇淺層 reset、由本演算法的「reset 深層」step 處理）
            //
            // 本實作的 reset 是「advance 此 ilvl 時、reset 所有 ilvl' > ilvl 的 counter」。
            // 對應 OOXML 預設「深層遇淺層 reset」(lvlRestart undefined 等同於 lvlRestart = ilvl + 1)。
            // 顯式 lvlRestart=0 不影響本 step；要影響「淺層遇深層 reset 自己」需 caller 另查
            // levels[X].lvlRestart 並決定 — 本實作不主動套（避免複雜耦合、留給未來 sprint）。
            // 推進此 ilvl 的 counter
            if (counters[ilvl] < 0) {
                // 首次出現：用 start
                counters[ilvl] = level.start;
            }
            else {
                // 已出現過：+1
                counters[ilvl] += 1;
            }
            // Reset 所有「ilvl' > ilvl」的深層 counter（下次再出現重新從 start 起算）
            // 例外：顯式 lvlRestart = 0 的 level 不 reset（連續編號跨章節）
            for (let i = ilvl + 1; i < counters.length; i++) {
                if (counters[i] < 0)
                    continue; // 從未出現過、無需 reset
                const deeperLevel = findLevel(abstractNumbering, i);
                if (deeperLevel && deeperLevel.lvlRestart === 0)
                    continue;
                counters[i] = -1;
            }
            // 組裝 counters 結果（只取 0..ilvl、紀律 #21 空集合不掛 key）
            const resultCounters = [];
            const resultNumFmts = [];
            for (let i = 0; i <= ilvl; i++) {
                // 較淺層若從未出現過（如直接從 ilvl=2 開始）、視為 start - 1 + 1 = start
                // 不主動 advance 較淺層（OOXML 規範：淺層只在自己被 advance 時才 +1）
                if (counters[i] < 0) {
                    const shallow = findLevel(abstractNumbering, i);
                    // 用 start 當顯示值（不寫入 state、避免影響後續真正 advance）
                    resultCounters.push(shallow?.start ?? 1);
                    resultNumFmts.push(shallow?.numFmt ?? 'decimal');
                }
                else {
                    resultCounters.push(counters[i]);
                    const shallow = findLevel(abstractNumbering, i);
                    resultNumFmts.push(shallow?.numFmt ?? 'decimal');
                }
            }
            return { counters: resultCounters, numFmts: resultNumFmts, level };
        }
        /**
         * 完整重置所有 numId 的計數器（如：開始解析新文件時）。
         */
        reset() {
            this.state.clear();
        }
        /**
         * 重置單一 numId 的計數器（如：遇到 sectPr 強制重啟章節）。
         *
         * @param numId 要重置的 numId；未存在時 no-op
         */
        resetNum(numId) {
            this.state.delete(numId);
        }
        /**
         * （debug / test 用）取得目前 state snapshot。
         *
         * 回傳的 Map 是 deep copy、修改不影響內部 state。
         */
        snapshot() {
            const out = new Map();
            for (const [k, v] of this.state) {
                out.set(k, [...v]);
            }
            return out;
        }
    }
    // ── 內部 helper ──────────────────────────────────────────────────────────────
    function findLevel(abstractNumbering, ilvl) {
        if (!abstractNumbering)
            return undefined;
        // levels 陣列已由 NumberingResolver 按 ilvl 排序、但允許稀疏（缺中間層）
        return abstractNumbering.levels.find((l) => l.ilvl === ilvl);
    }
    function placeholderLevel(ilvl) {
        // 缺失 level 的 placeholder：標準 decimal "%1." 編號（不 crash 下游）
        return { ilvl, numFmt: 'decimal', text: '%1.', start: 1 };
    }

    /**
     * numberingFormatter — 把序號數字按 OOXML w:numFmt 規則格式化為顯示字串
     *
     * 用途：NumberingResolver 解析 `<w:lvl><w:numFmt val="chineseCounting"/></w:lvl>`
     * 後保留原始 `numFmt` 字串；Renderer / mapper 階段把計數器 number 透過此模組轉為
     * 「一」「二」「壹」「i」「I」「a」… 等實際顯示字元。
     *
     * 設計決策（Sprint 132、規畫書 §Phase 4.3）：
     *   - **純函式 + 無狀態**：好 cache、好測試（紀律 #3 / #5）
     *   - **不在 Renderer 內 inline**：保持「OOXML 知識」集中在 numbering 目錄
     *   - **fallback 為 decimal**：未知 numFmt 不 throw、回 `String(n)` 確保 render 不斷
     *   - **0 / 負數防禦**：依各 format 語意決定（如 decimal 直回；CN 序數的 0 = 〇）
     *
     * 涵蓋的 numFmt（ECMA-376 §17.18.59 ST_NumberFormat 子集，依規畫書 §Phase 4.3）：
     *
     * | numFmt | 範例（n=1, 2, 11） | 備註 |
     * |---|---|---|
     * | decimal | 1, 2, 11 | 預設 / fallback |
     * | decimalZero | 01, 02, 11 | 兩位數補 0（OOXML 標準 padding） |
     * | none | "" | 不渲染（OOXML 規定）|
     * | bullet | "" | 由 w:lvlText 直接給字元、formatter 不處理 |
     * | lowerLetter / upperLetter | a/A, b/B, aa/AA | base-26 |
     * | lowerRoman / upperRoman | i/I, ii/II, xi/XI | 1–3999 範圍 |
     * | ordinal | 1st, 2nd, 3rd, 11th | 英文序數 |
     * | ordinalText | first, second, eleventh | 英文序數文字（1–20）|
     * | cardinalText | one, two, eleven | 英文基數文字（1–20）|
     * | chineseCounting | 一, 二, 十一 | 繁/簡通用書寫形式（1–9999）|
     * | chineseCountingThousand | 一千零一 | 千分隔（1–9999）|
     * | chineseLegalSimplified | 壹, 貳, 拾壹 | 法定大寫（繁體寫法、簡體稍有差異）|
     * | ideographDigital | 〇, 一, 二, 一一 | 用作 digits（每位數獨立）|
     * | ideographZodiac | 子, 丑, 寅 | 12 地支循環 |
     * | ideographTraditional | 甲, 乙, 丙 | 10 天干循環 |
     * | japaneseCounting | 一, 二, 十一 | 與 chineseCounting 同（W 規格簡化）|
     * | japaneseDigitalTenThousand | 一万 | 萬分隔 |
     * | japaneseLegal | 壱, 弐, 参 | 日文法定大寫（與中文略異）|
     * | taiwaneseCounting | 一, 二, 十一 | 同 chineseCounting |
     * | taiwaneseCountingThousand | 一千, 二千 | 同 chineseCountingThousand |
     * | iroha | い, ろ, は, … | 47 字假名循環 |
     * | aiueo | あ, い, う, … | 46 字假名循環 |
     *
     * 規格參考：
     *   - ECMA-376 Part 1 §17.18.59 (ST_NumberFormat)
     *   - ECMA-376 Part 1 §17.9.27 (lvlText)
     *   - ECMA-376 Part 1 §17.9.30 (numFmt)
     */
    /**
     * 把計數 n 依 numFmt 格式化為顯示字串。
     *
     * @param n        計數值（通常 ≥ 1；0 / 負數依 format 各自處理）
     * @param numFmt   OOXML w:numFmt 字串（如 'chineseCounting'）
     * @returns 顯示字串；未知 numFmt 回 `String(n)`（fallback to decimal）
     *
     * @example
     *   formatNumber(1, 'chineseCounting')         // → "一"
     *   formatNumber(11, 'chineseCounting')        // → "十一"
     *   formatNumber(5, 'lowerRoman')              // → "v"
     *   formatNumber(28, 'lowerLetter')            // → "ab"
     *   formatNumber(3, 'ordinal')                 // → "3rd"
     *   formatNumber(2024, 'ideographDigital')     // → "二〇二四"
     *   formatNumber(101, 'chineseLegalSimplified')// → "壹佰零壹"
     */
    function formatNumber(n, numFmt) {
        // none / bullet：renderer 直接用 lvlText、不該 call 這裡；防禦回 ""
        if (numFmt === 'none' || numFmt === 'bullet')
            return '';
        if (!Number.isFinite(n))
            return '';
        switch (numFmt) {
            case 'decimal':
                return String(n);
            case 'decimalZero':
                return n < 10 && n >= 0 ? '0' + n : String(n);
            case 'lowerLetter':
                return toBase26Letter(n, false);
            case 'upperLetter':
                return toBase26Letter(n, true);
            case 'lowerRoman':
                return toRoman(n).toLowerCase();
            case 'upperRoman':
                return toRoman(n);
            case 'ordinal':
                return toOrdinal(n);
            case 'ordinalText':
                return toOrdinalText(n);
            case 'cardinalText':
                return toCardinalText(n);
            case 'chineseCounting':
            case 'japaneseCounting':
            case 'taiwaneseCounting':
                return toChineseCounting(n);
            case 'chineseCountingThousand':
            case 'taiwaneseCountingThousand':
                return toChineseCountingThousand(n);
            case 'chineseLegalSimplified':
                return toChineseLegal(n);
            case 'japaneseLegal':
                return toJapaneseLegal(n);
            case 'ideographDigital':
            case 'taiwaneseDigital':
                return toIdeographDigital(n);
            case 'japaneseDigitalTenThousand':
                return toJapaneseDigitalTenThousand(n);
            case 'ideographZodiac':
                return toZodiac(n);
            case 'ideographTraditional':
                return toHeavenlyStem(n);
            case 'iroha':
                return toIroha(n);
            case 'irohaFullWidth':
                return toIroha(n);
            case 'aiueo':
                return toAiueo(n);
            case 'aiueoFullWidth':
                return toAiueo(n);
            default:
                // 未知 format fallback to decimal — 不 throw、保 render 不斷
                return String(n);
        }
    }
    /**
     * 展開 lvlText 模板字串（如 `"%1.%2."`）為實際序號（如 `"1.2."`）。
     *
     * @param template       OOXML w:lvlText/@val 字串
     * @param counters       各 level 的目前計數值（counters[0] = ilvl 0 的計數、counters[1] = ilvl 1 的計數 ...）
     * @param numFmts        各 level 的 numFmt 字串（與 counters 同長、由 NumberingMap 提供）
     * @returns 展開後字串；缺對應 counter / numFmt 時該 placeholder 留空
     *
     * @example
     *   expandLvlText("%1.%2.", [3, 2], ['decimal', 'lowerLetter']) // → "3.b."
     *   expandLvlText("第%1章", [5], ['chineseCounting'])           // → "第五章"
     */
    function expandLvlText(template, counters, numFmts) {
        // 用單一 regex 取代 %1, %2, ..., %9 placeholder
        return template.replace(/%([1-9])/g, (_, digit) => {
            const idx = parseInt(digit, 10) - 1; // %1 → counters[0]
            const counter = counters[idx];
            const fmt = numFmts[idx];
            if (counter === undefined || fmt === undefined)
                return '';
            return formatNumber(counter, fmt);
        });
    }
    // ── 西式格式 ────────────────────────────────────────────────────────────────
    /** base-26：1=a, 26=z, 27=aa, 52=az, 53=ba, … */
    function toBase26Letter(n, uppercase) {
        if (n < 1)
            return uppercase ? 'A' : 'a';
        let v = Math.floor(n);
        let out = '';
        const base = uppercase ? 65 : 97; // 'A' or 'a'
        while (v > 0) {
            const rem = (v - 1) % 26;
            out = String.fromCharCode(base + rem) + out;
            v = Math.floor((v - 1) / 26);
        }
        return out;
    }
    const ROMAN_PAIRS = [
        [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
        [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
        [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
    ];
    /** 1–3999；範圍外回 decimal */
    function toRoman(n) {
        if (n < 1 || n > 3999)
            return String(n);
        let v = Math.floor(n);
        let out = '';
        for (const [val, sym] of ROMAN_PAIRS) {
            while (v >= val) {
                out += sym;
                v -= val;
            }
        }
        return out;
    }
    function toOrdinal(n) {
        const v = Math.floor(n);
        const mod100 = v % 100;
        if (mod100 >= 11 && mod100 <= 13)
            return v + 'th';
        switch (v % 10) {
            case 1: return v + 'st';
            case 2: return v + 'nd';
            case 3: return v + 'rd';
            default: return v + 'th';
        }
    }
    const ORDINAL_TEXT = [
        '', 'first', 'second', 'third', 'fourth', 'fifth',
        'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
        'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth',
        'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth',
    ];
    function toOrdinalText(n) {
        const v = Math.floor(n);
        return v >= 1 && v <= 20 ? ORDINAL_TEXT[v] : toOrdinal(v);
    }
    const CARDINAL_TEXT = [
        '', 'one', 'two', 'three', 'four', 'five',
        'six', 'seven', 'eight', 'nine', 'ten',
        'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
        'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
    ];
    function toCardinalText(n) {
        const v = Math.floor(n);
        return v >= 1 && v <= 20 ? CARDINAL_TEXT[v] : String(v);
    }
    // ── 中文格式 ────────────────────────────────────────────────────────────────
    const CN_DIGITS = ['〇', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
    /**
     * 繁體中文計數寫法（1–9999）：
     *   1=一, 10=十, 11=十一, 20=二十, 99=九十九,
     *   100=一百, 101=一百零一, 110=一百一十, 999=九百九十九,
     *   1000=一千, 9999=九千九百九十九
     *
     * 範圍外 fallback decimal。
     */
    function toChineseCounting(n) {
        if (n < 0)
            return '負' + toChineseCounting(-n);
        if (n === 0)
            return CN_DIGITS[0];
        if (n >= 10000)
            return String(n); // 超出 4 位 fallback decimal（萬以上由 chineseCountingThousand 處理）
        const v = Math.floor(n);
        if (v < 10)
            return CN_DIGITS[v];
        // 10–19：十、十一、…、十九（無「一十」前綴）
        if (v < 20)
            return v === 10 ? '十' : '十' + CN_DIGITS[v - 10];
        // 20–99
        if (v < 100) {
            const tens = Math.floor(v / 10);
            const ones = v % 10;
            return CN_DIGITS[tens] + '十' + (ones === 0 ? '' : CN_DIGITS[ones]);
        }
        // 100–999
        if (v < 1000) {
            const h = Math.floor(v / 100);
            const rest = v % 100;
            if (rest === 0)
                return CN_DIGITS[h] + '百';
            // 101–109：一百零一
            if (rest < 10)
                return CN_DIGITS[h] + '百零' + CN_DIGITS[rest];
            // 110, 120 ..：一百一十；111–199 → 一百一十一
            return CN_DIGITS[h] + '百' + toChineseCounting(rest);
        }
        // 1000–9999
        const k = Math.floor(v / 1000);
        const rest = v % 1000;
        if (rest === 0)
            return CN_DIGITS[k] + '千';
        if (rest < 100)
            return CN_DIGITS[k] + '千零' + toChineseCounting(rest);
        return CN_DIGITS[k] + '千' + toChineseCounting(rest);
    }
    /**
     * 千分隔變體：相對於 chineseCounting，本變體不省略「零」、適用法律 / 正式文書。
     * Sprint 132 簡化為 alias to chineseCounting；如未來 fixture 出現差異再分流。
     */
    function toChineseCountingThousand(n) {
        return toChineseCounting(n);
    }
    const CN_LEGAL_DIGITS = [
        '零', '壹', '貳', '參', '肆', '伍', '陸', '柒', '捌', '玖',
    ];
    /**
     * 中文法定大寫（繁體寫法）：
     *   1=壹, 10=拾, 11=拾壹, 100=壹佰, 1000=壹仟, 10000=壹萬
     *
     * 用於支票、財報、法律文件防竄改。範圍 1–99999999（億以下）。
     */
    function toChineseLegal(n) {
        if (n < 0)
            return '負' + toChineseLegal(-n);
        if (n === 0)
            return CN_LEGAL_DIGITS[0];
        const v = Math.floor(n);
        if (v < 10)
            return CN_LEGAL_DIGITS[v];
        // 10–19：拾、拾壹…（同 chineseCounting 不寫「壹拾」）
        if (v < 20)
            return v === 10 ? '拾' : '拾' + CN_LEGAL_DIGITS[v - 10];
        if (v < 100) {
            const tens = Math.floor(v / 10);
            const ones = v % 10;
            return CN_LEGAL_DIGITS[tens] + '拾' + (ones === 0 ? '' : CN_LEGAL_DIGITS[ones]);
        }
        if (v < 1000) {
            const h = Math.floor(v / 100);
            const rest = v % 100;
            if (rest === 0)
                return CN_LEGAL_DIGITS[h] + '佰';
            if (rest < 10)
                return CN_LEGAL_DIGITS[h] + '佰零' + CN_LEGAL_DIGITS[rest];
            return CN_LEGAL_DIGITS[h] + '佰' + toChineseLegal(rest);
        }
        if (v < 10000) {
            const k = Math.floor(v / 1000);
            const rest = v % 1000;
            if (rest === 0)
                return CN_LEGAL_DIGITS[k] + '仟';
            if (rest < 100)
                return CN_LEGAL_DIGITS[k] + '仟零' + toChineseLegal(rest);
            return CN_LEGAL_DIGITS[k] + '仟' + toChineseLegal(rest);
        }
        // 萬以上 — 簡化處理：直接 fallback decimal（超大金額罕用 ilvl 編號）
        return String(v);
    }
    /**
     * 日文法定大寫（與中文略異）：
     *   1=壱, 2=弐, 3=参, 10=拾, 100=百, 1000=千
     *
     * 日本對某些字使用簡化版（壱弐参）、其他字（肆伍）回退到普通寫法。
     * Sprint 132 簡化：用日文 1-3 + 普通 4-9、結構同 chineseLegal。
     */
    const JP_LEGAL_DIGITS = [
        '零', '壱', '弐', '参', '四', '五', '六', '七', '八', '九',
    ];
    function toJapaneseLegal(n) {
        if (n < 0)
            return '負' + toJapaneseLegal(-n);
        if (n === 0)
            return JP_LEGAL_DIGITS[0];
        const v = Math.floor(n);
        if (v < 10)
            return JP_LEGAL_DIGITS[v];
        if (v < 20)
            return v === 10 ? '拾' : '拾' + JP_LEGAL_DIGITS[v - 10];
        if (v < 100) {
            const tens = Math.floor(v / 10);
            const ones = v % 10;
            return JP_LEGAL_DIGITS[tens] + '拾' + (ones === 0 ? '' : JP_LEGAL_DIGITS[ones]);
        }
        return String(v);
    }
    /**
     * ideographDigital：把 n 的每位數獨立轉為中文數字（不含「十百千」）。
     *
     *   1 → 一
     *   23 → 二三
     *   100 → 一〇〇
     *   2024 → 二〇二四
     *
     * 適用「壹零壹」式編號（如電話號碼、年份）。
     */
    function toIdeographDigital(n) {
        if (n < 0)
            return '負' + toIdeographDigital(-n);
        const v = Math.floor(Math.abs(n));
        return String(v).split('').map((d) => CN_DIGITS[parseInt(d, 10)] ?? d).join('');
    }
    /**
     * 日文 ten-thousand：使用「万」分隔。
     *   1 → 一, 10000 → 一万, 12345 → 一万二千三百四十五
     *
     * Sprint 132 簡化：n < 10000 同 chineseCounting；n ≥ 10000 加「万」前綴。
     */
    function toJapaneseDigitalTenThousand(n) {
        if (n < 0)
            return '負' + toJapaneseDigitalTenThousand(-n);
        const v = Math.floor(n);
        if (v < 10000)
            return toChineseCounting(v);
        const man = Math.floor(v / 10000);
        const rest = v % 10000;
        const manStr = toChineseCounting(man) + '万';
        if (rest === 0)
            return manStr;
        return manStr + toChineseCounting(rest);
    }
    // ── 循環序列 ────────────────────────────────────────────────────────────────
    const ZODIAC = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'];
    function toZodiac(n) {
        if (n < 1)
            return ZODIAC[0];
        return ZODIAC[(Math.floor(n) - 1) % 12];
    }
    const HEAVENLY_STEM = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸'];
    function toHeavenlyStem(n) {
        if (n < 1)
            return HEAVENLY_STEM[0];
        return HEAVENLY_STEM[(Math.floor(n) - 1) % 10];
    }
    const IROHA_HW = [
        'い', 'ろ', 'は', 'に', 'ほ', 'へ', 'と', 'ち', 'り', 'ぬ',
        'る', 'を', 'わ', 'か', 'よ', 'た', 'れ', 'そ', 'つ', 'ね',
        'な', 'ら', 'む', 'う', 'ゐ', 'の', 'お', 'く', 'や', 'ま',
        'け', 'ふ', 'こ', 'え', 'て', 'あ', 'さ', 'き', 'ゆ', 'め',
        'み', 'し', 'ゑ', 'ひ', 'も', 'せ', 'す',
    ];
    /**
     * いろは 47 字假名循環。半形（katakana）目前 fall through to 平假名（OOXML 用
     * 全形 / 半形 hint 但實務上 fixture 罕見、defer）。
     */
    function toIroha(n, _fullWidth) {
        if (n < 1)
            return IROHA_HW[0];
        return IROHA_HW[(Math.floor(n) - 1) % IROHA_HW.length];
    }
    const AIUEO_HW = [
        'あ', 'い', 'う', 'え', 'お', 'か', 'き', 'く', 'け', 'こ',
        'さ', 'し', 'す', 'せ', 'そ', 'た', 'ち', 'つ', 'て', 'と',
        'な', 'に', 'ぬ', 'ね', 'の', 'は', 'ひ', 'ふ', 'へ', 'ほ',
        'ま', 'み', 'む', 'め', 'も', 'や', 'ゆ', 'よ', 'ら', 'り',
        'る', 'れ', 'ろ', 'わ', 'を', 'ん',
    ];
    function toAiueo(n, _fullWidth) {
        if (n < 1)
            return AIUEO_HW[0];
        return AIUEO_HW[(Math.floor(n) - 1) % AIUEO_HW.length];
    }

    /**
     * ToCanvasEditor — 把 DocumentNode 轉成 @hufe921/canvas-editor 的 IElement[] 格式
     *
     * canvas-editor 的輸入是「扁平 IElement 陣列」：
     *   - 每個字 / 字元 = 一個 IElement（type=text，value=char）
     *   - 段落結束 = 一個 IElement（value='\n'）
     *   - 圖片 = 一個 IElement（type=image，value=dataURL，width/height）
     *   - 表格 = 一個 IElement（type=table，colgroup + trList，內部 td.value 也是 IElement[]）
     *   - 超連結 = 一個 IElement（type=hyperlink，url + valueList = 子 IElement[]）
     *   - 分頁符 = 一個 IElement（type=pageBreak）
     *
     * 樣式（font / size / bold / color / italic / underline / strikeout / rowFlex / rowMargin）
     *   套用在每個字元 IElement 上；段落樣式（alignment / spacing）會被「複製」到該段所有 IElement。
     *
     * 範圍（Phase D.1）：
     *   ✅ Run 文字 + RunProps（font / size / bold / italic / underline / strike / color / highlight）
     *   ✅ 段落對齊（rowFlex）+ 段距（rowMargin）+ 段落結束 \n
     *   ✅ Break：line / page / column → \n（line）/ pageBreak（page/column 暫降級）
     *   ✅ Inline image：rId 透過 media map 解析成 dataURL → type=image
     *   ✅ Float image：暫降級為 inline image（canvas-editor 對浮動繞排支援有限，Phase 6+ 補）
     *   ✅ Hyperlink：type=hyperlink + url + valueList
     *   ✅ Table：colgroup + trList（gridSpan→colspan、vMerge anchor.rowSpan→rowspan、isContinuation cell 跳過）
     *   ✅ 段落間 page break（不同 section 之間插 pageBreak）
     *   ⚠️ Tab stops（pPr.tabs）：canvas-editor 的 type=tab 不接受位置陣列，只能放 '\t' 字元
     *   ⚠️ 列表編號（numId/ilvl）：canvas-editor 用獨立 listType/listStyle 系統，Phase D.1 暫不映射
     *   ⚠️ 字型 fallback（hAnsi/cs）：canvas-editor 只用單一 font，目前優先 fontFamilyEastAsia ?? fontFamily
     *
     * Phase D.2 / D.3：HarfBuzz metrics 整合 / pixelmatch e2e diff
     */
    // ── 對外 Mapper ───────────────────────────────────────────────────────────────
    class ToCanvasEditor {
        constructor() {
            /**
             * Sprint 183：SmartArt / Chart relId → 節點查表（render 用）。
             * 每次 `convert()` 開頭依當前 DocumentNode 重建，避免跨文件殘留。
             */
            this.smartArtsByRId = new Map();
            this.chartsByRId = new Map();
            /**
             * Sprint 184：註解 id → 內容查表（render 用）。
             * 每次 `convert()` 開頭依當前 DocumentNode 重設，避免跨文件殘留。
             */
            this.comments = new Map();
        }
        /**
         * 把整份 DocumentNode 轉為 IElement[]。
         *
         * @param doc 由 OoxmlParser.parse() 產出的 DocumentNode
         * @returns 可直接傳給 `new Editor(container, elements, options)` 的扁平陣列
         */
        convert(doc) {
            // Sprint 183：建 SmartArt / Chart 查表（graphic frame relId → 節點）
            this.smartArtsByRId = new Map((doc.smartArts ?? []).map((s) => [s.rId, s]));
            this.chartsByRId = new Map((doc.charts ?? []).map((c) => [c.rId, c]));
            // Sprint 184：註解查表（commentRefs id → 內容）
            this.comments = doc.comments;
            const elements = [];
            // Sprint 138：跨 section 共用 counter state（OOXML §17.9 預設行為、
            // sectPr 不強制重啟編號；若 fixture 需要可由 future sprint 加 hook）
            const counter = new NumberingCounterState();
            for (let i = 0; i < doc.sections.length; i++) {
                const section = doc.sections[i];
                // section 之間插 pageBreak（除了第一節前不需要）
                if (i > 0) {
                    elements.push({ type: 'pageBreak', value: '\n' });
                }
                this.appendBlocks(elements, section.body, doc.media, doc.numbering, counter);
            }
            return elements;
        }
        // ── BlockNode[] 走訪 ──────────────────────────────────────────────────────
        appendBlocks(out, blocks, media, numbering, counter) {
            for (const block of blocks) {
                if (block.type === 'paragraph') {
                    this.appendParagraph(out, block, media, numbering, counter);
                }
                else {
                    out.push(this.convertTable(block, media, numbering, counter));
                    // 表格後仍需段落終止符 \n（canvas-editor 規範）
                    out.push({ value: '\n' });
                }
            }
        }
        // ── Paragraph → IElement[]（含段尾 \n）────────────────────────────────────
        appendParagraph(out, para, media, numbering, counter) {
            const rowFlex = mapAlignment(para.props.alignment);
            const rowMargin = para.props.spacing?.before ?? para.props.spacing?.after;
            // 段落內 InlineNode → 各別 IElement
            const paraElements = [];
            // Sprint 138：若 paragraph 有 numId，emit 編號前綴（展開 lvlText + tab 分隔）
            // canvas-editor 無 listType/listStyle 對應、降級為「前綴字串 + tab」嵌入段首
            // - bullet numFmt：lvlText 直接是字元（如「•」）、counter advance 仍需推進避免污染深層
            // - decimal/letter/roman/CN/JP/...：用 expandLvlText 展開 counter 為字串
            // - lvlText='' 的 placeholder：跳過 emit（避免空 prefix）
            if (para.props.numId !== undefined) {
                const ilvl = para.props.ilvl ?? 0;
                const abstractNum = numbering.get(para.props.numId);
                const result = counter.advance(para.props.numId, ilvl, abstractNum);
                const prefix = expandLvlText(result.level.text, result.counters, result.numFmts);
                if (prefix !== '') {
                    // 用 paragraph 的 runProps 基底（從 level.runProps fallback）作為前綴樣式
                    // 取第一個 run 的 props 當前綴 baseStyle；若無 run、用 level.runProps 或空
                    const baseProps = (para.runs.find((r) => r.type === 'run')?.props) ??
                        result.level.runProps ??
                        {};
                    const baseStyle = mapRunProps(baseProps);
                    this.appendChars(paraElements, prefix, baseStyle);
                    // 編號與後續文字以 tab 分隔（OOXML 預設 lvlText suffix = tab）
                    paraElements.push({ ...baseStyle, type: 'tab', value: '\t' });
                }
            }
            for (const node of para.runs) {
                this.appendInlineNode(paraElements, node, media);
            }
            // Sprint 180（Phase 5.1 OMML render）：段落內數學公式（`para.math` 側陣列）
            //   以線性文字 fallback 渲染（分數 a/b、根號 √(x)、上下標 x_(n) 等）。
            //   capture-only 階段 math 未保留行內精確位置 → 一律 append 於段落 runs 之後
            //   （多數公式為 math-only 段落、此近似可接受；inline-mixed 精確位置 + KaTeX
            //   全保真排版留未來 optional sprint）。display / inline 皆同樣線性化。
            if (para.math && para.math.length > 0) {
                const mathBaseProps = (para.runs.find((r) => r.type === 'run')?.props) ?? {};
                const mathStyle = mapRunProps(mathBaseProps);
                for (const mathNode of para.math) {
                    const linear = ommlToLinearText(mathNode.omml);
                    if (linear !== '')
                        this.appendChars(paraElements, linear, mathStyle);
                }
            }
            // Sprint 184（Phase 5.5 註解 render）：被註解段落（`para.commentRefs` 側陣列）
            //   canvas-editor 無 Word 右側註解 panel 對應 → 線性文字 fallback：在段落 runs
            //   後 append `[註解 作者: 內容]` 標記（mc:Fallback 壓縮、degraded fidelity；
            //   精確錨點範圍 highlight + 互動 panel 留未來 optional sprint）。
            if (para.commentRefs && para.commentRefs.length > 0) {
                const cmtBaseProps = (para.runs.find((r) => r.type === 'run')?.props) ?? {};
                const cmtStyle = mapRunProps(cmtBaseProps);
                for (const id of para.commentRefs) {
                    const cmt = this.comments.get(id);
                    if (!cmt)
                        continue;
                    const body = commentToText(cmt);
                    const marker = cmt.author
                        ? `[註解 ${cmt.author}: ${body}]`
                        : `[註解: ${body}]`;
                    this.appendChars(paraElements, marker, cmtStyle);
                }
            }
            // 把 rowFlex / rowMargin 套用到段內所有 IElement（canvas-editor 段落樣式套法）
            if (rowFlex || rowMargin !== undefined) {
                for (const el of paraElements) {
                    if (rowFlex)
                        el.rowFlex = rowFlex;
                    if (rowMargin !== undefined)
                        el.rowMargin = rowMargin;
                }
            }
            // 段落終止符 \n（也帶段落樣式以確保最後一行對齊正確）
            const terminator = { value: '\n' };
            if (rowFlex)
                terminator.rowFlex = rowFlex;
            if (rowMargin !== undefined)
                terminator.rowMargin = rowMargin;
            paraElements.push(terminator);
            out.push(...paraElements);
        }
        // ── InlineNode → IElement[] ────────────────────────────────────────────────
        appendInlineNode(out, node, media) {
            switch (node.type) {
                case 'run':
                    this.appendRun(out, node);
                    break;
                case 'break':
                    if (node.breakType === 'line') {
                        out.push({ value: '\n' });
                    }
                    else {
                        // page / column break → canvas-editor 用 type=pageBreak
                        out.push({ type: 'pageBreak', value: '\n' });
                    }
                    break;
                case 'field': {
                    // Sprint 160 v2: <w:instrText> 複雜欄位 render 消費
                    // fldChar begin/separate/end 三段語意 → parser 產出 FieldNode
                    // renderer 根據 fieldType + instrText 決定輸出內容
                    const textToRender = node.cachedValue
                        ?? this.fieldPlaceholder(node.fieldType, node.instruction);
                    for (const ch of textToRender) {
                        out.push({ value: ch });
                    }
                    break;
                }
                case 'inlineImage':
                    this.appendImage(out, node, media);
                    break;
                case 'floatImage':
                    // Phase D.1：暫降級為 inline image（canvas-editor 浮動繞排支援不完整）
                    this.appendImage(out, node, media);
                    break;
            }
        }
        // ── Run → IElement[] ──────────────────────────────────────────────────────
        appendRun(out, run) {
            const baseStyle = mapRunProps(run.props);
            if (run.hyperlink && (run.hyperlink.url || run.hyperlink.anchor)) {
                // hyperlink 包裝：產出 valueList 為文字 IElement[]
                const innerElements = [];
                this.appendChars(innerElements, run.text, baseStyle);
                const linkEl = {
                    type: 'hyperlink',
                    value: '',
                    valueList: innerElements,
                };
                if (run.hyperlink.url)
                    linkEl.url = run.hyperlink.url;
                out.push(linkEl);
            }
            else {
                this.appendChars(out, run.text, baseStyle);
            }
        }
        /**
         * 把字串拆成字元 IElement，每個字元都帶 baseStyle。
         *
         * canvas-editor 規範：每個字（CJK / 西文）都是獨立的 IElement，
         * 樣式重複出現是預期行為（讓 row breaking / 字型 fallback 在 Renderer 內以字為單位）。
         */
        appendChars(out, text, baseStyle) {
            // 處理 \t / \n 特殊字元
            for (let i = 0; i < text.length; i++) {
                const ch = text[i];
                if (ch === '\t') {
                    out.push({ ...baseStyle, type: 'tab', value: '\t' });
                }
                else if (ch === '\n') {
                    out.push({ ...baseStyle, value: '\n' });
                }
                else {
                    // 用 spread 複製樣式（避免不同字元共用同一物件造成意外突變）
                    out.push({ ...baseStyle, value: ch });
                }
            }
        }
        // ── Field placeholder ──────────────────────────────────────────────────────
        /**
         * 根據 fieldType 和原始 instruction 產出佔位文字。
         * 無 cachedValue 時呼叫：讓 layout flow 有可見文字而非空白。
         */
        fieldPlaceholder(fieldType, instruction) {
            switch (fieldType) {
                case 'PAGE': return '[PAGE]';
                case 'NUMPAGES': return '[NUMPAGES]';
                case 'DATE': return '[DATE]';
                case 'TIME': return '[TIME]';
                case 'AUTHOR': return '[AUTHOR]';
                case 'FILENAME': return '[FILENAME]';
                case 'SEQ': return '[SEQ]';
                case 'TOC': return '[TOC]';
                case 'REF': return '[REF]';
                case 'STYLEREF': return '[STYLEREF]';
                case 'HYPERLINK':
                    // HYPERLINK 欄位通常有 anchor/url — 回退到 instruction 片段
                    return instruction.trim();
                case 'unknown':
                default:
                    // 未識別欄位：用 instruction 本身作可見文字
                    return instruction.trim() || '[FIELD]';
            }
        }
        // ── Image ─────────────────────────────────────────────────────────────────
        appendImage(out, img, media) {
            // Sprint 183（Phase 5.2/5.3 render）：SmartArt / Chart graphic frame —— 圖形不
            //   內嵌，以線性文字 fallback 取代（mc:Fallback 壓縮、degraded fidelity）。
            if (img.type === 'inlineImage' && img.graphic) {
                const text = this.graphicFallbackText(img.graphic);
                if (text !== undefined) {
                    // 查到對應節點：非空 → append 文字；空內容 → 不 emit（SmartArt/Chart 存在但無文字）
                    if (text !== '')
                        this.appendChars(out, text, mapRunProps({}));
                    return;
                }
                // text === undefined：查無對應 SmartArt/Chart 節點 → 落下方一般圖片路徑
            }
            const dataUrl = img.rId ? media.get(img.rId) : undefined;
            if (!dataUrl) {
                // 找不到圖片：放空 IElement（值=占位文字）避免下游 crash
                out.push({ value: '[圖片缺失]' });
                return;
            }
            out.push({
                type: 'image',
                value: dataUrl,
                width: img.width,
                height: img.height,
            });
        }
        /**
         * Sprint 183：SmartArt / Chart graphic frame 的線性文字 fallback。
         *
         * @returns 線性文字（可能為空字串＝節點存在但無內容）；
         *          undefined＝查無對應 SmartArt/Chart 節點（caller 落一般圖片路徑）
         */
        graphicFallbackText(graphic) {
            if (graphic.kind === 'diagram') {
                const sa = this.smartArtsByRId.get(graphic.relId);
                return sa ? smartArtToText(sa) : undefined;
            }
            const chart = this.chartsByRId.get(graphic.relId);
            return chart ? chartToText(chart) : undefined;
        }
        // ── Table → IElement (type='table') ───────────────────────────────────────
        convertTable(table, media, numbering, counter) {
            const colgroup = table.grid.map((w) => ({ width: w }));
            const trList = table.rows.map((row) => this.convertRow(row, media, numbering, counter));
            return {
                type: 'table',
                value: '',
                colgroup,
                trList,
            };
        }
        convertRow(row, media, numbering, counter) {
            const tdList = [];
            for (const cell of row.cells) {
                // vMerge continue 格子在 canvas-editor 中不出現（被 anchor 的 rowspan 吸收）
                if (cell.isContinuation)
                    continue;
                tdList.push(this.convertCell(cell, media, numbering, counter));
            }
            return {
                height: row.props.height ?? 0,
                tdList,
            };
        }
        convertCell(cell, media, numbering, counter) {
            // Sprint 5：cell.content 改為 BlockNode[]，paragraphs 直接 append；
            // 巢狀 TableNode 暫時降級成「[巢狀表格 N×M]」文字占位
            // （canvas-editor IElement 結構不支援 cell 內又包 type=table，需自寫 Renderer）。
            const value = [];
            for (const block of cell.content) {
                if (block.type === 'paragraph') {
                    this.appendParagraph(value, block, media, numbering, counter);
                }
                else if (block.type === 'table') {
                    const r = block.rows.length;
                    const c = block.grid.length;
                    value.push({ value: `[巢狀表格 ${r}×${c}]` });
                    value.push({ value: '\n' });
                }
            }
            // 空 cell 至少要有一個段落終止符（canvas-editor 規範）
            if (value.length === 0) {
                value.push({ value: '\n' });
            }
            const td = {
                colspan: cell.gridSpan,
                rowspan: cell.rowSpan,
                value,
            };
            if (cell.props.shading?.fill) {
                td.backgroundColor = '#' + cell.props.shading.fill;
            }
            if (cell.props.vAlign) {
                td.verticalAlign =
                    cell.props.vAlign === 'center'
                        ? 'middle'
                        : cell.props.vAlign;
            }
            return td;
        }
    }
    // ── 共用 mapper helper ───────────────────────────────────────────────────────
    function mapAlignment(a) {
        if (!a)
            return undefined;
        switch (a) {
            case 'left':
                return 'left';
            case 'center':
                return 'center';
            case 'right':
                return 'right';
            case 'justify':
                return 'justify';
            case 'distribute':
                return 'alignment'; // canvas-editor 對應「分散對齊」叫 alignment
            default:
                return undefined;
        }
    }
    function mapRunProps(props) {
        const out = { value: '' };
        // 字型優先序：fontFamilyEastAsia > fontFamily（CJK 文件多）
        // canvas-editor 只接受單一 font，取最具描述性的那個
        const font = props.fontFamilyEastAsia ?? props.fontFamily;
        if (font)
            out.font = font;
        if (props.fontSize !== undefined)
            out.size = props.fontSize;
        if (props.bold)
            out.bold = true;
        if (props.italic)
            out.italic = true;
        if (props.underline && props.underline !== 'none')
            out.underline = true;
        if (props.strike)
            out.strikeout = true;
        if (props.color && props.color !== 'auto') {
            out.color = props.color.startsWith('#') ? props.color : '#' + props.color;
        }
        if (props.highlight) {
            // w:highlight 是具名色（yellow / cyan / lightGray 等），canvas-editor 接受 hex
            // 先做最常見三色映射；其他名稱保留原字（canvas-editor 也接受 css 名）
            out.highlight = mapHighlightColor(props.highlight);
        }
        if (props.spacing !== undefined)
            out.letterSpacing = props.spacing;
        return out;
    }
    function mapHighlightColor(name) {
        switch (name.toLowerCase()) {
            case 'yellow':
                return '#FFFF00';
            case 'green':
                return '#00FF00';
            case 'cyan':
                return '#00FFFF';
            case 'magenta':
                return '#FF00FF';
            case 'blue':
                return '#0000FF';
            case 'red':
                return '#FF0000';
            case 'darkblue':
                return '#000080';
            case 'darkcyan':
                return '#008080';
            case 'darkgreen':
                return '#008000';
            case 'darkmagenta':
                return '#800080';
            case 'darkred':
                return '#800000';
            case 'darkyellow':
                return '#808000';
            case 'darkgray':
            case 'darkgrey':
                return '#808080';
            case 'lightgray':
            case 'lightgrey':
                return '#C0C0C0';
            case 'black':
                return '#000000';
            case 'white':
                return '#FFFFFF';
            default:
                return name;
        }
    }

    var index = /*#__PURE__*/Object.freeze({
        __proto__: null,
        EIGHTH_POINT_PER_PT: EIGHTH_POINT_PER_PT,
        EMU_PER_INCH: EMU_PER_INCH,
        EMU_PER_PT: EMU_PER_PT,
        HALF_POINT_PER_PT: HALF_POINT_PER_PT,
        PT_PER_INCH: PT_PER_INCH,
        TWIP_PER_PT: TWIP_PER_PT,
        eighthPointToPt: eighthPointToPt,
        emuToPt: emuToPt,
        halfPointToPt: halfPointToPt,
        ptToPx: ptToPx,
        twipToPt: twipToPt
    });

    exports.DocumentParser = DocumentParser;
    exports.DrawingParser = DrawingParser;
    exports.GridResolver = GridResolver;
    exports.HeaderFooterParser = HeaderFooterParser;
    exports.NumberingResolver = NumberingResolver;
    exports.OoxmlParser = OoxmlParser;
    exports.PackageReader = PackageReader;
    exports.ParagraphParser = ParagraphParser;
    exports.SectionParser = SectionParser;
    exports.StyleResolver = StyleResolver;
    exports.TableParser = TableParser;
    exports.ToCanvasEditor = ToCanvasEditor;
    exports.Units = index;
    exports.__DOBTOR_OOXML_STUB__ = __DOBTOR_OOXML_STUB__;
    exports.parseDocProps = parseDocProps;
    exports.parseDocPropsXml = parseDocPropsXml;

}));
//# sourceMappingURL=canvas-editor-custom.umd.js.map
