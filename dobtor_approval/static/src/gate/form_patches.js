/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration — License LGPL-3
/**
 * 表單層 patch：
 * ① FormRenderer 註冊 ApprovalBar 子元件（供模板 t-inherit 注入）。
 * ② ViewButton：被攔且未核准的 object 按鈕隱藏（讀 approval_store）。
 */
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";
import { ViewButton } from "@web/views/view_button/view_button";
import { ApprovalBar } from "./approval_bar";
import { isGatedMethod } from "./approval_store";

FormRenderer.components = { ...FormRenderer.components, ApprovalBar };

patch(ViewButton.prototype, {
    get isBpmnGatedHidden() {
        const cp = this.props.clickParams || {};
        const rec = this.props.record;
        if (cp.type !== "object" || !cp.name || !rec || !rec.resId) {
            return false;
        }
        return isGatedMethod(rec.resModel, rec.resId, cp.name);
    },
});
