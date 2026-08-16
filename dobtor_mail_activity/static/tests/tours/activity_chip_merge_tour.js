/** @odoo-module **/

/**
 * 合併後「膠囊轉向」的端到端驗證。
 *
 * 這條路徑跨三層，Python 測試只涵蓋得到第一層：
 *   1. 後端 get_chip_data 沿 merged_into_id 解析到主待辦（test_merge.py 已測）
 *   2. utils/batch_loader 把同頁多顆膠囊的請求併成一次 RPC
 *   3. EmbeddedActivityChip 依回傳的 id/redirected_from 換內容與圖示
 *
 * 情境（資料由 tests/test_tour.py 建好）：
 *   筆記內文有一顆指向「被併入待辦」的膠囊，該待辦已被併進主待辦。
 *   膠囊的 HTML 仍寫著舊 id —— 畫面必須顯示主待辦的摘要並帶轉向圖示。
 */
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_service/tour_utils";

registry.category("web_tour.tours").add("dobtor_activity_chip_merge_tour", {
    url: "/odoo",
    steps: () => [
        ...stepUtils.goToAppSteps(
            "dobtor_mail_activity.menu_notebook_root",
            "開啟個人筆記 App"
        ),
        {
            content: "開啟含膠囊的測試筆記",
            trigger: ".o_data_row td:contains(Chip merge tour note)",
            run: "click",
        },
        {
            content: "筆記內文的膠囊已渲染完成",
            trigger: ".o_dobtor_activity_chip",
        },
        {
            content: "★ 關鍵：膠囊雖仍指向舊 id，內容必須換成主待辦的摘要",
            trigger: ".o_dobtor_activity_chip[title*='Chip tour master']",
        },
        {
            content: "★ 關鍵：帶轉向圖示（fa-compress），與一般膠囊區分",
            trigger: ".o_dobtor_activity_chip .o_dobtor_chip_merged",
        },
        {
            content: "不應顯示成「已刪除」（合併不是刪除）",
            trigger: ".o_dobtor_activity_chip:not(.o_chip_deleted):not(.o_chip_failed)",
        },
    ],
});
