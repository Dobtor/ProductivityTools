/** @odoo-module **/

/**
 * 畫布底部的分頁列。
 *
 * 原本是 `_renderSheetTabs()` 用 `document.createElement` 一顆一顆造出來、再
 * `insertBefore` 塞進狀態列前面的 45 行命令式程式碼；每次分頁有變動就整條
 * `innerHTML = ''` 重建，連帶把事件監聽器也重綁一輪。
 *
 * 與 MindmapProjectBar、MindmapPager 同樣的分工：反應式狀態放在這裡，變動時
 * 只重繪這一列，永遠不會動到畫布（畫布是命令式掛在原生 DOM ref 上的）。
 *
 * 分頁角色（主圖／子圖／發想頁）：順序由父層用 orderSheets() 排好（主圖 →
 * 子圖依樹狀、每層前面一個「›」→ 發想頁，虛線框）。右鍵是選單：改名、
 * 合併回上層（子圖）、掛到主題…（發想頁）、刪除。
 */
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { depthPrefix } from "@dobtor_xmind/js/mindmap_sheet_tree";

export class MindmapSheetTabs extends Component {
    static template = "dobtor_xmind.MindmapSheetTabs";
    static props = {
        /** [{ id, name, sheet_role, depth }]，順序即顯示順序（orderSheets 排好）。 */
        sheets: { type: Array },
        /** 目前顯示的分頁 id；false = 尚未載入。 */
        currentId: { type: [Number, Boolean], optional: true },
        /** 專案已鎖定：主圖分頁顯示鎖頭與說明。 */
        projectLocked: { type: Boolean, optional: true },
        onSwitch: { type: Function },
        onRename: { type: Function },
        onDelete: { type: Function },
        onAdd: { type: Function },
        onMerge: { type: Function, optional: true },
        onAttach: { type: Function, optional: true },
    };

    setup() {
        this.menu = useState({ open: false, x: 0, y: 0, sheetId: false, tree: false });
        this._close = () => {
            if (this.menu.open || this.menu.tree) {
                this.menu.open = false;
                this.menu.tree = false;
            }
        };
        onMounted(() => document.addEventListener("click", this._close));
        onWillUnmount(() => document.removeEventListener("click", this._close));
    }

    get addLabel() {
        return _t("New Sheet");
    }

    get treeLabel() {
        return _t("Sheet Tree");
    }

    get lockTitle() {
        return _t("This mind map is synced with its project: the main sheet and the project link are locked.");
    }

    roleTitle(sheet) {
        if (sheet.sheet_role === "main") {
            return _t("Main sheet — synced with the project");
        }
        if (sheet.sheet_role === "sub") {
            return _t("Sub sheet of topic “%s”", sheet.anchor_topic_title || "");
        }
        return _t("Idea sheet — never synced with the project");
    }

    prefix(sheet) {
        return depthPrefix(sheet.depth || 0);
    }

    tabClass(sheet) {
        // o_xmind_sheet_tab 是 tour 的選取掛點 —— 沒有它就只剩 .badge，
        // 連「哪一個分頁」都無法可靠指名。
        const active = sheet.id === this.props.currentId;
        return "o_xmind_sheet_tab badge o_xmind_sheet_role_" + (sheet.sheet_role || "idea") + " "
            + (active ? "text-bg-primary active" : "text-bg-light text-dark");
    }

    get menuSheet() {
        return this.props.sheets.find((s) => s.id === this.menu.sheetId) || null;
    }

    get menuItems() {
        const sheet = this.menuSheet;
        if (!sheet) {
            return [];
        }
        const items = [{ id: "rename", icon: "fa-pencil", label: _t("Rename") }];
        if (sheet.sheet_role === "sub" && this.props.onMerge) {
            items.push({ id: "merge", icon: "fa-compress", label: _t("Merge into parent sheet") });
        }
        if (sheet.sheet_role === "idea" && this.props.onAttach) {
            items.push({ id: "attach", icon: "fa-link", label: _t("Attach to topic…") });
        }
        items.push({ id: "delete", icon: "fa-trash", label: _t("Delete"), danger: true });
        return items;
    }

    onContextMenu(ev, sheet) {
        ev.preventDefault();
        ev.stopPropagation();
        Object.assign(this.menu, {
            open: true, tree: false, sheetId: sheet.id,
            x: ev.clientX || 0, y: ev.clientY || 0,
        });
    }

    menuStyle() {
        // 分頁列在畫面底部：選單往上長
        return `position: fixed; left: ${this.menu.x}px; bottom: ${Math.max(
            0, window.innerHeight - this.menu.y)}px; z-index: 10000;`;
    }

    onMenuClick(item) {
        const sheetId = this.menu.sheetId;
        this.menu.open = false;
        if (item.id === "rename") {
            this.props.onRename(sheetId);
        } else if (item.id === "merge") {
            this.props.onMerge(sheetId);
        } else if (item.id === "attach") {
            this.props.onAttach(sheetId);
        } else if (item.id === "delete") {
            this.props.onDelete(sheetId);
        }
    }

    toggleTree(ev) {
        ev.stopPropagation();
        this.menu.open = false;
        // 分頁列是 overflow-x:auto，絕對定位的選單會被裁掉 —— 用 fixed 定位在按鈕上方
        const rect = ev.currentTarget.getBoundingClientRect();
        this.menu.x = rect.left;
        this.menu.y = rect.top;
        this.menu.tree = !this.menu.tree;
    }

    onTreeClick(sheet) {
        this.menu.tree = false;
        this.props.onSwitch(sheet.id);
    }

    treeIndent(sheet) {
        return "padding-left: " + (12 + 16 * (sheet.depth || 0)) + "px";
    }

    roleIcon(sheet) {
        if (sheet.sheet_role === "main") {
            return "fa fa-star text-warning";
        }
        if (sheet.sheet_role === "sub") {
            return "fa fa-level-up fa-rotate-90 text-muted";
        }
        return "fa fa-lightbulb-o text-muted";
    }
}
