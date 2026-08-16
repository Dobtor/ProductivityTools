/** @odoo-module **/

/**
 * 端到端 tour：多分頁切換。
 *
 * 為什麼專門為這條路徑寫 tour —— 這個前後端交界連續出過三個資料遺失等級的
 * bug，而且三個都是「畫面看起來正常、資料被寫到別張分頁」，純後端測試抓不到：
 *
 *   1. ``save_mindmap_data`` 寫死 ``sheet_ids[0]`` → 從分頁 2 切回分頁 1，
 *      分頁 2 的畫布被寫進分頁 1，分頁 1 的內容當場消失。
 *   2. ``action_restore`` 同樣寫死第一張分頁。
 *   3. 特徵層（關聯線／邊界／摘要）切分頁時沒跟著換 → 畫的是新分頁的樹、
 *      關聯線卻是上一張的，下次存檔就把它們寫進新分頁。
 *
 * 涵蓋切換、新增、刪除。原本只能測「切換」—— ``onAddSheet`` / ``onDeleteSheet``
 * 當時用瀏覽器原生 ``prompt()`` / ``confirm()``，原生視窗不在 DOM 裡，tour 停在
 * 那裡就過不去；改成 Odoo Dialog 之後這兩條路徑才變成可測的。
 *
 * 初始的兩張分頁仍由 Python 在後端建好（見 tests/test_sheet_tour.py），這樣
 * 前面那段切換斷言的資料才是可預期的。
 */
import { registry } from "@web/core/registry";

/** 分頁上的節點文字（與 test_sheet_tour.py 的資料一致）。 */
const SHEET_A_TOPIC = "Alpha Root";
const SHEET_B_TOPIC = "Beta Root";

/** jsMind 把節點畫進 .o_mindmap_canvas .xmind-nodes，每顆是
 *  .xmind-node > .xmind-topic-text（見 static/lib/jsmind/jsmind.js:1479）。 */
function topicVisible(text) {
    return `.o_mindmap_canvas .xmind-node .xmind-topic-text:contains("${text}")`;
}

/** 「畫布上不可以有這個節點」。
 *  刻意不用 `:not(:has(:contains(...)))` —— :contains 是 hoot-dom 的自訂
 *  pseudo，巢狀在原生 :not() 裡不保證解析得到；用 run 直接斷言最可靠。 */
function expectTopicGone(text) {
    return () => {
        const found = [...document.querySelectorAll(
            ".o_mindmap_canvas .xmind-node .xmind-topic-text"
        )].some((el) => el.textContent.trim() === text);
        if (found) {
            throw new Error(`上一張分頁的節點「${text}」殘留在畫布上`);
        }
    };
}

registry.category("web_tour.tours").add("dobtor_xmind_sheet_switch_tour", {
    // 起點由 Python 端指定（要帶動態的 workbook id 才能直接落在表單上；
    // 這個 action 預設是 kanban，從清單點進去反而不可靠）。
    steps: () => [
        {
            content: "進入視覺化編輯器",
            trigger: "button[name='action_open_editor']",
            run: "click",
        },
        {
            content: "分頁列已載入，且停在第一張分頁",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab.active:contains('Sheet A')",
        },
        {
            content: "第一張分頁顯示自己的內容",
            trigger: topicVisible(SHEET_A_TOPIC),
        },
        {
            content: "切到第二張分頁",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab:contains('Sheet B')",
            run: "click",
        },
        {
            content: "第二張分頁顯示的是自己的內容",
            trigger: topicVisible(SHEET_B_TOPIC),
        },
        {
            // 舊 bug 的直接症狀：切過去之後仍看得到上一張的節點。
            content: "上一張分頁的節點不可以殘留在畫布上",
            trigger: topicVisible(SHEET_B_TOPIC),
            run: expectTopicGone(SHEET_A_TOPIC),
        },
        {
            content: "切回第一張分頁",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab:contains('Sheet A')",
            run: "click",
        },
        {
            // 這一步就是 bug #1 的回歸點：切回來時，第一張分頁的內容曾經被
            // 第二張的畫布覆蓋掉而變成空白。
            content: "第一張分頁的內容必須原封不動",
            trigger: topicVisible(SHEET_A_TOPIC),
        },
        {
            content: "第二張分頁的節點不可以殘留",
            trigger: topicVisible(SHEET_A_TOPIC),
            run: expectTopicGone(SHEET_B_TOPIC),
        },
        {
            content: "分頁列的高亮跟著回到第一張",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab.active:contains('Sheet A')",
        },
        // ── 以下為新增／刪除分頁：改用 Odoo Dialog 之後才測得到 ──
        {
            content: "按分頁列的「＋」新增分頁",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_add",
            run: "click",
        },
        {
            content: "跳出的是 Odoo 對話框（不是原生 prompt），且預先帶了名稱",
            trigger: ".modal .o_mindmap_prompt input#o_mindmap_prompt_name",
            run: "edit Sheet C",
        },
        {
            content: "建立",
            trigger: ".modal .modal-footer .btn-primary",
            run: "click",
        },
        {
            content: "新分頁出現在分頁列上",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab:contains('Sheet C')",
        },
        {
            content: "切到新分頁",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab:contains('Sheet C')",
            run: "click",
        },
        {
            // 新分頁的根主題用分頁名建立（見 controllers/main.py create_sheet）；
            // 前兩張分頁的節點都不可以跟著過來。
            content: "新分頁上看不到別張分頁的節點",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab.active:contains('Sheet C')",
            run: expectTopicGone(SHEET_A_TOPIC),
        },
        {
            // tour 的 run 沒有「右鍵」這個動作，自己派發 contextmenu 事件。
            content: "右鍵分頁 → 觸發刪除",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab:contains('Sheet C')",
            run(helpers) {
                helpers.anchor.dispatchEvent(
                    new MouseEvent("contextmenu", { bubbles: true, cancelable: true })
                );
            },
        },
        {
            content: "確認刪除（Odoo 的 ConfirmationDialog）",
            trigger: ".modal .modal-footer .btn-danger",
            run: "click",
        },
        {
            content: "分頁已從分頁列消失，且焦點回到第一張",
            trigger: ".o_xmind_sheet_tabs .o_xmind_sheet_tab.active:contains('Sheet A')",
            run() {
                const still = [...document.querySelectorAll(
                    ".o_xmind_sheet_tabs .o_xmind_sheet_tab"
                )].some((el) => el.textContent.trim() === "Sheet C");
                if (still) {
                    throw new Error("刪除後分頁「Sheet C」仍在分頁列上");
                }
            },
        },
        {
            // 刪掉「當前」分頁時，畫布原本會停在那張已消失的分頁上，而
            // _currentSheetId 已指向第一張 —— 自動存檔一醒來就把被刪分頁的內容
            // 寫進第一張。畫布必須換成新的當前分頁，這一步就是那個回歸點。
            content: "畫布已換成第一張分頁的內容（不是被刪那張）",
            trigger: topicVisible(SHEET_A_TOPIC),
            run: expectTopicGone("Sheet C"),
        },
    ],
});
