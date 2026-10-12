/** @odoo-module **/
/**
 * 從**清單**進編輯器的四條路：文件／範本 × 點一筆／按新增。
 *
 * ☠️ 為什麼要有這支：doc_editor_panels_tour 是直接從編輯器的 client action
 *    進去的（/odoo/action-<編輯器>），完全繞過清單——所以清單的 js_class
 *    （static/src/views/doc_document_list_open_editor.js）在任何測試裡都
 *    沒有被執行過。2026-10-12 admin.dobtor.com 上點清單任一筆就是
 *    「Cannot read properties of undefined (reading 'call')」：Odoo 18 的
 *    ListController 沒有 this.orm，而那支控制器直接拿來用。一行都沒測到的
 *    程式碼，壞了也不會有任何東西變紅。
 *
 * 斷言只有一件事：真的進到編輯器（左欄分頁出現）。Odoo 的 tour 本來就會
 * 因為未捕捉的前端錯誤而失敗，所以「點下去就炸」會直接紅在這裡。
 */
import { registry } from "@web/core/registry";

const editorMounted = {
    content: "應該進到編輯器（不是表單、也不是錯誤畫面）",
    trigger: ".o_dobtor_doc_editor .doc-left-tabs",
    run: () => {},
};

const clickFirstRow = {
    content: "點清單第一筆",
    trigger: ".o_list_view .o_data_row .o_data_cell",
    run: "click",
};

const clickNew = {
    content: "按「新增」",
    trigger: ".o_list_view .o_list_button_add",
    run: "click",
};

for (const [name, firstStep] of [
    ["doc_document_list_click_tour", clickFirstRow],
    ["doc_document_list_new_tour", clickNew],
    ["doc_template_list_click_tour", clickFirstRow],
    ["doc_template_list_new_tour", clickNew],
]) {
    registry.category("web_tour.tours").add(name, {
        steps: () => [firstStep, editorMounted],
    });
}

/**
 * Portal 前台：/my/documents/<id> 上的編輯器真的掛得起來。
 *
 * ☠️ 同一個盲點的第二個實例：test_route_remaining.py 打過這個頁面的 HTTP
 *    回應，但頁面上的 JS（public_components → DocEditor）**從沒在瀏覽器裡
 *    掛載過**。而 Portal 是 DocEditor 唯一一個沒有 action／dialog service 的
 *    環境（doc_editor.js 的 setup 會把它們設成 null）——那些分支只有這裡會走到。
 */
registry.category("web_tour.tours").add("doc_portal_editor_mount_tour", {
    steps: () => [
        {
            content: "Portal 頁上的編輯器應該掛載完成（不是一直停在載入中）",
            trigger: "owl-component .o_dobtor_doc_editor .doc-left-tabs",
            run: () => {},
        },
        {
            // ☠️ 不能寫成「找不到 .fa-spinner」：編輯器自己裡面也有 spinner。
            //    要精準指 fallback，而且 tour 的 trigger 預設只認看得見的元素，
            //    所以從編輯器出發、在 run 裡檢查 fallback 是否還看得見。
            content: "「載入中」的 fallback 應該已經藏起來",
            trigger: "owl-component .o_dobtor_doc_editor",
            run: () => {
                const fb = document.querySelector("owl-component .o_doc_portal_fallback");
                if (fb && fb.offsetParent !== null) {
                    throw new Error(
                        "編輯器已掛載，但「載入文件編輯器…」的 fallback 還顯示在畫面上");
                }
            },
        },
    ],
});
