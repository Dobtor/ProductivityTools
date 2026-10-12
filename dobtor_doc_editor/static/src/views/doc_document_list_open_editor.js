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
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/** 點一筆 → 編輯器。文件與範本共用。 */
export class DocOpenEditorListController extends ListController {
    setup() {
        super.setup();
        // ☠️ Odoo 18 的 ListController 只注入 action 與 dialog，**沒有 this.orm**
        //    （list_controller.js:79-80）。FormController、GanttController 有，
        //    所以從那些地方抄來的 this.orm.call 在這裡會是
        //    「Cannot read properties of undefined (reading 'call')」
        //    ——2026-10-12 admin.dobtor.com 點清單任一筆就炸。
        //    dobtor_xmind 的 list_open_editor.js 沒事，是因為它只用 actionService。
        this.orm = useService("orm");
    }

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
            // ☠️ args 是 []，不是 [[]]：後端是 @api.model，不吃 ids。
            //    傳 [[]] 的話那個空陣列會變成第二個位置參數 →
            //    「takes 1 positional argument but 2 were given」。
            //    這個錯跟 this.orm 那個一起活到正式機，因為「新增」一樣沒有測試。
            this.props.resModel, "action_new_and_open_editor", []
        );
        await this.actionService.doAction(action);
    }
}

registry.category("views").add("doc_document_list_open_editor", {
    ...listView,
    Controller: DocDocumentOpenEditorListController,
});

/**
 * 範本：和文件一樣，點開與新增都進編輯器。
 *
 * 這裡原本刻意不一致，理由是「一張新範本沒有適用模型就沒有欄位可拖，編輯器
 * 只會叫使用者去表單設」——進去第一件事是再出來。那個前提已經不成立：左欄
 * 在沒有模型時提供就地選單（onOpenModelPicker → /dobtor_doc/set_model）。
 *
 * 角色（內容／外框）、外框、紙張格式這些仍然只在表單上，靠清單的「設定」鈕
 * 進去——那是設計時決定一次的設定，不是內容。
 */
export class DocTemplateOpenEditorListController extends DocOpenEditorListController {
    async createRecord() {
        const action = await this.orm.call(
            // ☠️ args 是 []，不是 [[]]：後端是 @api.model，不吃 ids。
            //    傳 [[]] 的話那個空陣列會變成第二個位置參數 →
            //    「takes 1 positional argument but 2 were given」。
            //    這個錯跟 this.orm 那個一起活到正式機，因為「新增」一樣沒有測試。
            this.props.resModel, "action_new_and_open_editor", []
        );
        await this.actionService.doAction(action);
    }
}

registry.category("views").add("doc_template_list_open_editor", {
    ...listView,
    Controller: DocTemplateOpenEditorListController,
});
