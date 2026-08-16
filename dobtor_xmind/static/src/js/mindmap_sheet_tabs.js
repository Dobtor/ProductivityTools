/** @odoo-module **/

/**
 * 畫布底部的分頁列。
 *
 * 原本是 `_renderSheetTabs()` 用 `document.createElement` 一顆一顆造出來、再
 * `insertBefore` 塞進狀態列前面的 45 行命令式程式碼；每次分頁有變動就整條
 * `innerHTML = ''` 重建，連帶把事件監聽器也重綁一輪。
 *
 * 會挑這一塊改寫成 OWL 子元件（而不是像右鍵選單那樣只是搬檔），是因為它有
 * 端到端測試護欄 —— tour 已經涵蓋切換／新增／刪除三條路徑，改壞了跑得出來。
 *
 * 與 MindmapProjectBar、MindmapPager 同樣的分工：反應式狀態放在這裡，變動時
 * 只重繪這一列，永遠不會動到畫布（畫布是命令式掛在原生 DOM ref 上的）。
 */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class MindmapSheetTabs extends Component {
    static template = "dobtor_xmind.MindmapSheetTabs";
    static props = {
        /** [{ id, name }]，順序即顯示順序（後端已依 sequence 排好）。 */
        sheets: { type: Array },
        /** 目前顯示的分頁 id；null = 尚未載入。 */
        currentId: { type: [Number, Boolean], optional: true },
        onSwitch: { type: Function },
        onRename: { type: Function },
        onDelete: { type: Function },
        onAdd: { type: Function },
    };

    get addLabel() {
        return _t("New Sheet");
    }

    tabClass(sheet) {
        // o_xmind_sheet_tab 是 tour 的選取掛點 —— 沒有它就只剩 .badge，
        // 連「哪一個分頁」都無法可靠指名。
        const active = sheet.id === this.props.currentId;
        return "o_xmind_sheet_tab badge " + (active
            ? "text-bg-primary active"
            : "text-bg-light text-dark");
    }

    /** 右鍵 = 刪除。確認對話框由父層出（它才知道「剩最後一張」的規則）。 */
    onContextMenu(ev, sheet) {
        ev.preventDefault();
        this.props.onDelete(sheet.id);
    }
}
