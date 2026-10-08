/** @odoo-module **/

/**
 * 文件清單：點一筆直接進編輯器，「新增」也直接進編輯器。
 *
 * 為什麼：文件的內容就是編輯器裡那一份。原本點一筆開表單，使用者看到的是
 * 一堆設定欄位，還要再按一次「開啟編輯器」——而他想做的事（改文件）在第二層。
 * 表單上真正只有表單才有的東西（關聯記錄、協作者、版本、保留政策）是設定、
 * 不是內容，所以留在清單的「設定」按鈕後面。
 *
 * 建立與開啟兩個入口要一致：只改點開、不改新增的話，「新增」給表單、
 * 「點開」給編輯器，使用者會以為那是兩種東西。
 *
 * 做法沿用 dobtor_xmind 的 static/src/views/list_open_editor.js
 *（那邊只改了 createRecord；這裡連 openRecord 一起改）。
 */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

export class DocDocumentOpenEditorListController extends ListController {
    /** 點一筆 → 那份文件的編輯器（不是表單）。 */
    async openRecord(record) {
        const action = await this.orm.call(
            record.resModel, "action_open_editor", [[record.resId]]
        );
        await this.actionService.doAction(action);
    }

    /** 新增 → 建一份空白文件後直接進編輯器。 */
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
