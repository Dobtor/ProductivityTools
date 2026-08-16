/** @odoo-module **/

/**
 * 週次選擇器 × 搜尋 facet 的共存驗證。
 *
 * 這條路徑無法用 Python 測到 —— 它的正確性完全取決於前端資料流：
 * 週次條件住在 ActivityWeekSearchModel._getDomain()，與 facet 一起經由
 * searchModel.domain → props.domain → model.load() 下傳。
 *
 * 舊版把週次寫在 Controller 事後 model.root.load({domain})，位在資料流下游：
 *   - 改 facet → props.domain 變 → model 以新 domain 重載 → 週次條件被沖掉
 *   - 再切週次 → 用的是掛載時的 _baseDomain 快照 → 剛選的 facet 又被沖掉
 * 本 tour 就是釘死「兩者不再互相破壞」。
 */
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_service/tour_utils";

registry.category("web_tour.tours").add("dobtor_activity_week_selector_tour", {
    url: "/odoo",
    steps: () => [
        ...stepUtils.goToAppSteps(
            "project_todo.menu_todo_todos",
            "開啟待辦事項 App"
        ),
        {
            content: "切到清單檢視（週次選擇器與批次動作都在控制面板上）",
            trigger: ".o_switch_view.o_list",
            run: "click",
        },
        {
            content: "週次選擇器應存在且已載入（isLoading 結束才會解除 disabled）",
            trigger: ".o_activity_week_selector select:not([disabled])",
        },
        {
            content: "切到「下週」",
            trigger: ".o_activity_week_selector select",
            run: "select 1",
        },
        {
            content: "確認選擇器停在下週",
            trigger: ".o_activity_week_selector select option[value='1']:checked",
        },
        {
            content: "打開篩選選單",
            trigger: ".o_searchview_dropdown_toggler, .o_filter_menu > button",
            run: "click",
        },
        {
            content: "勾選「Urgent」facet",
            trigger: ".o_filter_menu .dropdown-item:contains(Urgent)",
            run: "click",
        },
        {
            content: "facet 已出現在搜尋列",
            trigger: ".o_searchview .o_facet_values:contains(Urgent)",
        },
        {
            content: "★ 關鍵：加了 facet 之後，週次仍停在下週（舊版會被沖回本週）",
            trigger: ".o_activity_week_selector select option[value='1']:checked",
        },
        {
            content: "切回「本週」",
            trigger: ".o_activity_week_selector select",
            run: "select 0",
        },
        {
            content: "★ 關鍵：切完週次之後，Urgent facet 仍在（舊版會被沖掉）",
            trigger: ".o_searchview .o_facet_values:contains(Urgent)",
        },
        {
            content: "確認週次已切到本週",
            trigger: ".o_activity_week_selector select option[value='0']:checked",
        },
        {
            content: "切到「全部」應清掉週次條件而不影響 facet",
            trigger: ".o_activity_week_selector select",
            run: "select all",
        },
        {
            content: "facet 依然存在",
            trigger: ".o_searchview .o_facet_values:contains(Urgent)",
        },
    ],
});
