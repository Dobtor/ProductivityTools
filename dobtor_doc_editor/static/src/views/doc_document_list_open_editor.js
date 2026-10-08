/** @odoo-module **/

/**
 * 清單：點一筆直接進編輯器。
 *
 * 為什麼：文件／範本的內容就是編輯器裡那一份。原本點一筆開表單，使用者看到
 * 的是一堆設定欄位，還要再按一次「開啟編輯器」——他想做的事在第二層。
 * 表單上真正只有表單才有的東西（關聯記錄、協作者、版本、適用模型、外框）是
 * 設定、不是內容，所以留在清單的「設定」按鈕後面。
 *
 * 做法沿用 dobtor_xmind 的 static/src/views/list_open_editor.js。
 *
 * ☠️ 文件與範本在「新增」這一步**刻意不同**，理由見 DocTemplate… 那一段。
 */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/** 點一筆 → 編輯器。文件與範本共用。 */
export class DocOpenEditorListController extends ListController {
    async openRecord(record) {
        const action = await this.orm.call(
            record.resModel, "action_open_editor", [[record.resId]]
        );
        await this.actionService.doAction(action);
    }
}

/**
 * 文件：連「新增」也直接進編輯器。
 *
 * 一份新文件立刻就能編輯（內容就是它的全部），所以建立與開啟兩個入口一致。
 */
export class DocDocumentOpenEditorListController extends DocOpenEditorListController {
    async createRecord() {
        const action = await this.orm.call(
            this.props.resModel, "action_new_and_open_editor", [[]]
        );
        await this.actionService.doAction(action);
    }
}

registry.category("views").add("doc_document_list_open_editor", {
    ...listView,
    Controller: DocDocumentOpenEditorListController,
});

/**
 * 範本：只改「點開」，**新增照舊走表單**。
 *
 * 看起來不一致，但這是刻意的：一張新範本沒有「適用模型」就沒有欄位可拖，
 * 編輯器左欄只會顯示「請先設定適用模型，才會列出可拖曳的欄位」
 *（doc_editor.xml 的 !_loadedModelName 分支）——也就是進去第一件事是再出來。
 * 而編輯器本身沒有選模型的介面。
 *
 * 範本的表單上還有角色（內容／外框）、外框、紙張格式這些**設計時才決定一次**
 * 的東西，先在表單上決定再進編輯器才是對的順序。
 * 要讓這裡也一致的前提是先在編輯器裡做一個選模型的介面。
 */
registry.category("views").add("doc_template_list_open_editor", {
    ...listView,
    Controller: DocOpenEditorListController,
});
