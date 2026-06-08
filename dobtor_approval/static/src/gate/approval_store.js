/** @odoo-module **/
// Copyright 2026 Dobtor Systems Integration — License LGPL-3
/**
 * 單據簽核狀態共享 store：ApprovalBar 取狀態後寫入，ViewButton 讀取以隱藏被攔且未核准的原鈕。
 * key = `${resModel}:${resId}`。
 */
import { reactive } from "@odoo/owl";

export const approvalStore = reactive({ byKey: {} });

export function gateKey(model, resId) {
    return `${model}:${resId}`;
}

export function setGatedMethods(model, resId, methods) {
    approvalStore.byKey[gateKey(model, resId)] = methods || [];
}

export function isGatedMethod(model, resId, method) {
    const m = approvalStore.byKey[gateKey(model, resId)];
    return !!(m && m.some((x) => x.method === method));
}
