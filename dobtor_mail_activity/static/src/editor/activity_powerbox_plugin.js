/** @odoo-module **/

/**
 * 富文字編輯器「待辦 / 活動」powerbox 外掛。
 *
 * 在 "/" 斜線選單新增一個分類，含兩個指令：
 *   - 建立待辦：把游標所在段落（"/" 之前的整段文字）帶入摘要，開啟 wizard。
 *   - 活動清單：在頁面內插入一個「即時內嵌活動清單」區塊（embedded component）。
 *
 * 依情境決定關聯（與後端 wizard 預設一致）：
 *   - 在 note.note 內：清單綁 note_id、wizard note_id 預設此筆記。
 *   - 在業務記錄內：清單綁 res_id、wizard target 預設此記錄、note_id 預設個人筆記。
 *   - 無對應記錄：綁個人待辦筆記。
 */
import { Plugin } from "@html_editor/plugin";
import { _t } from "@web/core/l10n/translation";
import { withSequence } from "@html_editor/utils/resource";
import { closestBlock } from "@html_editor/utils/blocks";
import { renderToElement } from "@web/core/utils/render";
import { ActivityClockToolbarButton } from "@dobtor_mail_activity/editor/activity_clock_toolbar";
import { ActivityPickerDialog } from "@dobtor_mail_activity/editor/activity_picker_dialog";
import { notifyActivityChanged } from "@dobtor_mail_activity/editor/activity_signal";

export class ActivityPowerboxPlugin extends Plugin {
    static id = "dobtorMailActivity";
    static dependencies = ["embeddedComponents", "dom", "selection", "history"];

    resources = {
        user_commands: [
            {
                id: "dobtorCreateTodo",
                title: _t("Create To-do"),
                description: _t("Turn this line into a to-do activity"),
                icon: "fa-tasks",
                run: this.openCreateTodoWizard.bind(this),
            },
            {
                id: "dobtorInsertActivityList",
                title: _t("Activity List"),
                description: _t("Insert a live to-do list for this document"),
                icon: "fa-clock-o",
                run: this.insertActivityList.bind(this),
            },
            {
                id: "dobtorLinkTodo",
                title: _t("Link To-do"),
                description: _t("Re-insert a chip for an existing to-do of this document"),
                icon: "fa-link",
                run: this.openLinkTodoPicker.bind(this),
            },
        ],
        // sequence < 10 → 排在原生「頁面結構(structure=10)」之上，置於選單最頂。
        powerbox_categories: withSequence(5, {
            id: "dobtor_activity",
            name: _t("To-do / Activity"),
        }),
        powerbox_items: [
            { categoryId: "dobtor_activity", commandId: "dobtorCreateTodo" },
            { categoryId: "dobtor_activity", commandId: "dobtorInsertActivityList" },
            { categoryId: "dobtor_activity", commandId: "dobtorLinkTodo" },
        ],
        // 工具列時鐘：選取文字時於浮動工具列出現，顏色依最近 deadline 著色，
        // 點開原生活動清單 popover（時鐘清單 + 打勾完成）。
        toolbar_groups: withSequence(55, { id: "dobtor_activity_tb" }),
        toolbar_items: [
            {
                id: "dobtorActivityClock",
                groupId: "dobtor_activity_tb",
                title: _t("Activities"),
                Component: ActivityClockToolbarButton,
                // getRecordInfo 以閉包延後取值，元件渲染時 this.config 已就緒。
                props: { getRecordInfo: this.getRecordInfo.bind(this) },
            },
        ],
    };

    /** 取得編輯器目前所在記錄（可能為空）。 */
    getRecordInfo() {
        return (this.config.getRecordInfo && this.config.getRecordInfo()) || {};
    }

    /**
     * 依目前所在記錄推導綁定參數（與後端 wizard / get_editor_activities 預設一致）：
     *   - note.note      → bind=note，綁本筆記
     *   - 其他業務記錄   → bind=res，綁該記錄
     *   - 無對應記錄     → bind=personal（個人待辦筆記，由後端解析）
     */
    bindParams() {
        const { resModel, resId } = this.getRecordInfo();
        if (resModel === "note.note" && resId) {
            return { bind: "note", noteId: resId };
        }
        if (resModel && resId) {
            return { bind: "res", resModel, resId };
        }
        return { bind: "personal" };
    }

    /** 此編輯器是否位於 chatter 訊息編輯框（composer）內。 */
    isInComposer() {
        return !!(this.editable && this.editable.closest && this.editable.closest(".o-mail-Composer"));
    }

    /** 廣播「活動已變更」：重載頁面內清單/膠囊/時鐘，並失效時鐘 RPC 快取。 */
    notifyReload() {
        notifyActivityChanged();
    }

    /** 指令①：建立待辦 —— 摘要取自「/」之前整段文字。
     *  依需求：powerbox 一律顯示 target 輸入、不帶入當前 res（不傳 active_model）。 */
    openCreateTodoWizard() {
        const selection = this.dependencies.selection.getEditableSelection();
        const block = closestBlock(selection.anchorNode);
        const summary = (block ? block.textContent : "").trim();

        this.services.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Create To-do"),
                res_model: "mail.activity.create.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_summary: summary,
                },
            },
            {
                // wizard.action_create_activity 回傳 infos.activity_id；
                // 建立成功後於游標處插入 inline 膠囊，並通知清單重載。
                onClose: (infos) => {
                    this.notifyReload();
                    // chatter 訊息框為一次性內容，不插入會被送出的 inline 膠囊。
                    if (infos && infos.activity_id && !this.isInComposer()) {
                        this.insertActivityChip(infos.activity_id, selection);
                    }
                },
            }
        );
    }

    /** 建立後於原游標處插入 inline 活動膠囊（embedded，可點開完成）。 */
    insertActivityChip(activityId, selection) {
        try {
            this.dependencies.selection.setSelection(selection);
        } catch (e) {
            // 游標還原失敗則沿用目前選取位置插入。
        }
        const chip = renderToElement("dobtor_mail_activity.ActivityChipBlueprint", {
            embeddedProps: JSON.stringify({ activityId }),
        });
        this.dependencies.dom.insert(chip);
        this.dependencies.history.addStep();
    }

    /** 指令②：在頁面插入即時內嵌活動清單區塊。 */
    insertActivityList() {
        // 無對應記錄時 bind=personal，實際 note 由後端
        // get_editor_activities('personal') 解析當前使用者的預設筆記，
        // 不需在此 await，避免插入前游標位置遺失。
        const block = renderToElement("dobtor_mail_activity.ActivityListBlueprint", {
            embeddedProps: JSON.stringify(this.bindParams()),
        });
        this.dependencies.dom.insert(block);
        this.dependencies.history.addStep();
    }

    /**
     * 指令③：關聯待辦 —— 列出本文件既有活動，挑一筆把膠囊重新插回游標處。
     * 用於膠囊在編輯器中被誤刪後，想將已建立的待辦加回文字後方。
     */
    openLinkTodoPicker() {
        // 先記住目前游標：對話框互動會移走焦點，選定後需還原插入點。
        const selection = this.dependencies.selection.getEditableSelection();
        this.services.dialog.add(ActivityPickerDialog, {
            ...this.bindParams(),
            onSelect: (activityId) => this.insertActivityChip(activityId, selection),
        });
    }
}
