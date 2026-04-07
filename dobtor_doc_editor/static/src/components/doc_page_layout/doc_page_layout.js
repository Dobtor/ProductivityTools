/** @odoo-module **/

import { Component, useState, useRef, useExternalListener, onMounted, onWillUnmount } from "@odoo/owl";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";

// 頁面尺寸 @ 96 dpi（px）
const PAGE_SIZES = {
    A4:     { width: 794,  height: 1123 },
    A3:     { width: 1123, height: 1587 },
    A5:     { width: 559,  height: 794  },
    letter: { width: 816,  height: 1056 },
    Letter: { width: 816,  height: 1056 },
    legal:  { width: 816,  height: 1344 },
    Legal:  { width: 816,  height: 1344 },
};

/**
 * DocPageLayout — 頁面容器。
 *
 * Google Docs 正確模型：
 * - 頁首/頁尾在「邊距區域」內（絕對定位），不佔用內容空間
 * - 預設 readonly（顯示 innerHTML）
 * - 雙擊進入 edit mode（掛載 Wysiwyg）
 * - 點擊外部退出 edit mode
 *
 * 結構：
 * .doc-page-sheet (position: relative; padding: marginTop...marginBottom)
 *   .doc-header-area  (position: absolute; top: 0; height: marginTop)
 *   .doc-content-wrapper (normal flow, fills full padding area)
 *   .doc-footer-area  (position: absolute; bottom: 0; height: marginBottom)
 */
export class DocPageLayout extends Component {
    static template = "dobtor_doc_editor.DocPageLayout";
    static components = { Wysiwyg };
    static props = {
        pageFormat:     { type: String, default: "A4" },
        marginTop:      { type: Number, default: 96 },
        marginBottom:   { type: Number, default: 96 },
        marginLeft:     { type: Number, default: 96 },
        marginRight:    { type: Number, default: 96 },
        headerHtml:     { type: String, optional: true },
        footerHtml:     { type: String, optional: true },
        editorConfig:   { type: Object, optional: true },
        onHeaderChange: { type: Function, optional: true },
        onFooterChange: { type: Function, optional: true },
    };

    setup() {
        this.contentRef  = useRef("pageContent");
        this.headerRef   = useRef("headerArea");
        this.footerRef   = useRef("footerArea");

        this.state = useState({
            editingHeader: false,
            editingFooter: false,
            pageBreaks:    [],   // [{ pageIndex, topPx }]
            totalPages:    1,
        });

        // 頁首 Wysiwyg 設定（預先建立，editingHeader 時才掛載）
        this.headerEditorConfig = {
            Plugins: MAIN_PLUGINS,
            content: this.props.headerHtml || "",
            onChange: (html) => {
                if (this.props.onHeaderChange) this.props.onHeaderChange(html);
            },
            placeholder: "頁首...",
        };

        // 頁尾 Wysiwyg 設定
        this.footerEditorConfig = {
            Plugins: MAIN_PLUGINS,
            content: this.props.footerHtml || "",
            onChange: (html) => {
                if (this.props.onFooterChange) this.props.onFooterChange(html);
            },
            placeholder: "頁尾...",
        };

        // 點擊頁首/頁尾外部時退出 edit mode
        useExternalListener(document, "mousedown", (ev) => {
            if (this.state.editingHeader) {
                const el = this.headerRef.el;
                if (el && !el.contains(ev.target)) {
                    this.state.editingHeader = false;
                }
            }
            if (this.state.editingFooter) {
                const el = this.footerRef.el;
                if (el && !el.contains(ev.target)) {
                    this.state.editingFooter = false;
                }
            }
        });

        this._resizeObserver = null;

        onMounted(() => {
            this._resizeObserver = new ResizeObserver(() => this._recalcPages());
            if (this.contentRef.el) {
                this._resizeObserver.observe(this.contentRef.el);
            }
        });

        onWillUnmount(() => {
            if (this._resizeObserver) this._resizeObserver.disconnect();
        });
    }

    // ── 頁首/頁尾 edit mode ─────────────────────────────────────

    onHeaderDblClick() {
        this.state.editingHeader = true;
    }

    onFooterDblClick() {
        this.state.editingFooter = true;
    }

    // ── 尺寸計算 ────────────────────────────────────────────────

    get pageSize() {
        return PAGE_SIZES[this.props.pageFormat] || PAGE_SIZES.A4;
    }

    get pageWidthMm() {
        const mm = { A4: 210, A3: 297, A5: 148, letter: 216, Letter: 216, legal: 216, Legal: 216 };
        return mm[this.props.pageFormat] || 210;
    }

    /** 紙張容器：relative + padding 形成邊距 + 固定最小頁面高度 */
    get pageStyle() {
        const { marginTop, marginRight, marginBottom, marginLeft } = this.props;
        const { height } = this.pageSize;
        return [
            `position: relative`,
            `padding: ${marginTop}px ${marginRight}px ${marginBottom}px ${marginLeft}px`,
            `min-height: ${height}px`,
            `display: flex`,
            `flex-direction: column`,
            `box-sizing: border-box`,
        ].join("; ");
    }

    /** 頁首絕對定位至上邊距區域 */
    get headerStyle() {
        const { marginTop, marginLeft, marginRight } = this.props;
        return [
            `position: absolute`,
            `top: 0`,
            `left: 0`,
            `right: 0`,
            `height: ${marginTop}px`,
            `padding: 4px ${marginRight}px 4px ${marginLeft}px`,
            `box-sizing: border-box`,
        ].join("; ");
    }

    /** 頁尾絕對定位至下邊距區域 */
    get footerStyle() {
        const { marginBottom, marginLeft, marginRight } = this.props;
        return [
            `position: absolute`,
            `bottom: 0`,
            `left: 0`,
            `right: 0`,
            `height: ${marginBottom}px`,
            `padding: 4px ${marginRight}px 4px ${marginLeft}px`,
            `box-sizing: border-box`,
        ].join("; ");
    }

    /** 計算視覺分頁線位置 */
    _recalcPages() {
        const el = this.contentRef.el;
        if (!el) return;

        const { height } = this.pageSize;
        // 頁首/頁尾在邊距內，不佔用內容高度
        const pageH = height - this.props.marginTop - this.props.marginBottom;
        if (pageH <= 0) return;

        const editable = el.querySelector('[contenteditable="true"]')
            || el.querySelector('.odoo-editor-editable')
            || el;
        const contentHeight = editable.scrollHeight;

        if (contentHeight <= pageH) {
            this.state.pageBreaks = [];
            this.state.totalPages = 1;
            return;
        }

        const totalPages = Math.ceil(contentHeight / pageH);
        const breaks = [];
        for (let i = 1; i < totalPages; i++) {
            breaks.push({ pageIndex: i, topPx: i * pageH });
        }

        this.state.pageBreaks = breaks;
        this.state.totalPages = totalPages;
    }
}
