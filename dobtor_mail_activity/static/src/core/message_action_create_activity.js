/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useComponent } from "@odoo/owl";

const messageActionsRegistry = registry.category("mail.message/actions");

/**
 * 移除「加入表情回應」動作
 * 以「建立待辦」取代其位置
 */
if (messageActionsRegistry.contains("reaction")) {
    messageActionsRegistry.remove("reaction");
}

/**
 * 從訊息建立待辦事項的動作
 *
 * 此動作取代原本的「加入表情回應」按鈕，
 * 點擊後會開啟 wizard 讓用戶從訊息內容建立待辦事項。
 */
messageActionsRegistry.add("create-activity-from-message", {
    // 顯示條件：訊息必須有有效的 ID
    condition: (component) => {
        const message = component.props?.message;
        return !!(message && message.id);
    },
    // 圖示（使用 FA4 相容圖示）
    icon: "fa fa-calendar-plus-o",
    // 標題
    title: _t("Create Activity"),
    // 點擊處理
    onClick: async (component) => {
        try {
            const message = component.props.message;
            const messageId = message.id;

            if (!messageId) {
                console.warn("dobtor_mail_activity: No message ID");
                return;
            }

            // 呼叫後端方法開啟 wizard
            const action = await component.orm.call(
                "mail.message",
                "action_create_activity_from_message",
                [[messageId]]
            );
            // 執行返回的 action（開啟 wizard）
            await component.actionService.doAction(action, {
                onClose: async () => {
                    // wizard 關閉後重新載入已建立的待辦
                    if (component.reloadCreatedActivities) {
                        await component.reloadCreatedActivities();
                    }
                },
            });
        } catch (e) {
            console.error("dobtor_mail_activity: onClick failed", e);
        }
    },
    // 設定：注入所需的服務
    setup: () => {
        const component = useComponent();
        component.orm = useService("orm");
        component.actionService = useService("action");
    },
    // 排序順序：10（取代原本 reaction 的位置，成為第一個圖示）
    sequence: 10,
    // 手機版點擊後關閉選單
    mobileCloseAfterClick: true,
});
