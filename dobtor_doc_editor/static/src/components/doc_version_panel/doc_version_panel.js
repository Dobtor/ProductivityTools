/** @odoo-module **/

/**
 * DocVersionPanel — 版本管理面板（W7-8 P1-1）
 *
 * 功能：
 *   - 列出所有版本快照（呼叫 /dobtor_doc/versions/list）
 *   - 點任一版本可預覽
 *   - 點「還原」按鈕回退到指定版本（自動先存還原前快照）
 *   - 點「對比」可選兩個版本做段落 diff
 *
 * 整合方式（W7-8 簡版）：
 *   doc_editor.js 加 toolbar 按鈕「版本歷史」→ 切換 state.showVersionPanel
 *   template 內條件渲染 <DocVersionPanel/>
 *
 * 設計取捨：
 *   - 不用 Modal — 想做 side panel（佔右側 300px），但本次 W7-8 先做基本版
 *     做 Modal 形式，等 W11+ UI 整體升級時再改
 */

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class DocVersionPanel extends Component {
    static template = "dobtor_doc_editor.DocVersionPanel";
    static props = {
        docId: { type: Number },
        onClose: { type: Function, optional: true },
        onRestore: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            loading: false,
            versions: [],
            error: null,
            // 對比模式
            compareMode: false,
            compareA: null,
            compareB: null,
            diffResult: null,
            // 預覽
            previewMessageId: null,
            previewContent: null,
        });

        onMounted(() => this.loadVersions());
    }

    async loadVersions() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await rpc("/dobtor_doc/versions/list", {
                doc_id: this.props.docId,
            });
            this.state.versions = result.versions || [];
        } catch (e) {
            this.state.error = `載入版本失敗：${e.message || e}`;
        } finally {
            this.state.loading = false;
        }
    }

    async previewVersion(messageId) {
        this.state.previewMessageId = messageId;
        try {
            const result = await rpc("/dobtor_doc/versions/get", {
                doc_id: this.props.docId,
                version_id: messageId,
            });
            if (result.error) {
                this.state.error = result.error;
                return;
            }
            this.state.previewContent = result;
        } catch (e) {
            this.state.error = `載入預覽失敗：${e.message || e}`;
        }
    }

    async restoreVersion(messageId) {
        if (!confirm(
            "還原此版本將覆蓋當前內容（會自動建立還原前快照）。確定？"
        )) {
            return;
        }
        try {
            const result = await rpc("/dobtor_doc/versions/restore", {
                doc_id: this.props.docId,
                version_id: messageId,
            });
            if (result.error) {
                this.state.error = result.error;
                return;
            }
            // 通知 parent component 重新載入文件
            if (this.props.onRestore) {
                this.props.onRestore(result);
            }
            await this.loadVersions();
        } catch (e) {
            this.state.error = `還原失敗：${e.message || e}`;
        }
    }

    toggleCompareMode() {
        this.state.compareMode = !this.state.compareMode;
        this.state.compareA = null;
        this.state.compareB = null;
        this.state.diffResult = null;
    }

    pickForCompare(messageId) {
        if (!this.state.compareA) {
            this.state.compareA = messageId;
        } else if (this.state.compareA === messageId) {
            this.state.compareA = null;
        } else if (!this.state.compareB) {
            this.state.compareB = messageId;
            this.runDiff();
        } else if (this.state.compareB === messageId) {
            this.state.compareB = null;
        } else {
            // 兩個都選了，覆蓋 B
            this.state.compareB = messageId;
            this.runDiff();
        }
    }

    async runDiff() {
        if (!this.state.compareA || !this.state.compareB) return;
        try {
            const result = await rpc("/dobtor_doc/versions/diff", {
                doc_id: this.props.docId,
                version_id_a: this.state.compareA,
                version_id_b: this.state.compareB,
            });
            if (result.error) {
                this.state.error = result.error;
                return;
            }
            this.state.diffResult = result;
        } catch (e) {
            this.state.error = `比對失敗：${e.message || e}`;
        }
    }

    getDiffOpClass(op) {
        return {
            equal: "diff-equal text-muted",
            insert: "diff-insert text-success",
            delete: "diff-delete text-danger",
            replace: "diff-replace text-warning",
        }[op] || "";
    }

    getDiffOpLabel(op) {
        return {
            equal: "未變動",
            insert: "新增",
            delete: "刪除",
            replace: "修改",
        }[op] || op;
    }

    onClose() {
        if (this.props.onClose) this.props.onClose();
    }
}
