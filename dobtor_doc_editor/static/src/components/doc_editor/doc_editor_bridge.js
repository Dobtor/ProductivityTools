/** @odoo-module **/
/**
 * 編輯器對外的「穩定介面」（外部整合用，例如 AI 助理面板）。
 *
 * 為什麼存在：外部不該依賴 `window._docEditor`（除錯用的全域，隨時可改名）或元件內部欄位。
 * 編輯器元件在 mounted 時把這個物件登記進 `registry.category("dobtor_doc_editor.bridge")` 的
 * 'active' 鍵，unmount 時移除。沒有人使用時它什麼都不做。
 *
 * 介面（全部可安全呼叫；編輯器不在編輯「文件」時 docId 為 null）：
 *   docId()                → 目前編輯的 doc.document id；範本／輸出紀錄模式為 null
 *   isReadonly()           → 唯讀模式
 *   isDirty()              → 有尚未存回伺服器的變更
 *   getSelectionText()     → 目前選取的文字（沒有選取為 ""）
 *   flush()                → Promise<boolean>：把未存變更存回；false＝存不了（衝突、失敗），不可繼續
 *   reload()               → Promise<void>：從伺服器重新載入內容（不觸發自動儲存）
 *
 * ☠️ reload 以 `_suppressAutoSave` 包住 executeSetValue（與預覽模式同一個機制）：
 *    程式注入的內容不是使用者編輯，不能被當成變更寫回。
 */
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export const BRIDGE_CATEGORY = "dobtor_doc_editor.bridge";
export const BRIDGE_KEY = "active";

const SUPPRESS_MS = 200;

export function makeEditorBridge(cmp) {
    return {
        docId() {
            return cmp.state.editTarget === "document" ? cmp.state.docId || null : null;
        },
        isReadonly() {
            return !!cmp._isReadonly;
        },
        isDirty() {
            return !!(cmp._autoSave && cmp._autoSave.isDirty());
        },
        getSelectionText() {
            try {
                return (cmp.editor && cmp.editor.command.getRangeText()) || "";
            } catch {
                return "";
            }
        },
        async flush() {
            if (!cmp.editor || cmp._isReadonly || !cmp.targetId || cmp._loadFailed) {
                return true;
            }
            // 自動儲存正在送出時先等它（最多 ~3 秒），避免兩個存檔互相用舊的 write_date 打架
            for (let i = 0; i < 30 && cmp._autoSave._saving; i++) {
                await new Promise((resolve) => setTimeout(resolve, 100));
            }
            if (!cmp._autoSave.isDirty()) {
                return true;
            }
            const json = JSON.stringify(cmp.editor.command.getValue().data);
            cmp._autoSave.cancel();
            let result;
            try {
                result = await rpc("/dobtor_doc/save", {
                    ...cmp.targetRpcParams,
                    content_json: json,
                    content_html: cmp._mainHtml(),
                    if_unmodified_since: cmp._lastSyncedWriteDate,
                });
            } catch {
                return false;
            }
            cmp._handleSaveResult(result, json);
            if (!result || result.conflict || result.success === false) {
                return false;
            }
            cmp._autoSave.markClean(json);
            return true;
        },
        async reload() {
            if (!cmp.editor || !cmp.targetId) {
                return;
            }
            await cmp._loadTarget();
            if (!cmp.editor || !cmp._loadedContentJson) {
                return;
            }
            cmp._suppressAutoSave = true;
            try {
                cmp.editor.command.executeSetValue(JSON.parse(cmp._loadedContentJson));
                cmp._autoSave.markClean(JSON.stringify(cmp.editor.command.getValue().data));
            } finally {
                setTimeout(() => {
                    cmp._suppressAutoSave = false;
                }, SUPPRESS_MS);
            }
        },
    };
}

export function registerEditorBridge(cmp) {
    const bridge = makeEditorBridge(cmp);
    registry.category(BRIDGE_CATEGORY).add(BRIDGE_KEY, bridge, { force: true });
    return bridge;
}

export function unregisterEditorBridge(bridge) {
    const category = registry.category(BRIDGE_CATEGORY);
    // 只移除自己登記的那一個（快速切換文件時，新元件可能已經登記了新的）
    if (bridge && category.get(BRIDGE_KEY, null) === bridge) {
        category.remove(BRIDGE_KEY);
    }
}
