/** @odoo-module **/

/**
 * 編輯器活動功能的共享訊號中樞（模組級單例）。
 *
 * 用 OWL EventBus 取代原本的 DOM CustomEvent：
 *   - 跨文件/iframe 都能收到（同一 JS realm），解決時鐘（在工具列 overlay）與
 *     內嵌清單/膠囊（可能在 iframe 內）無法互通的問題。
 *   - 統一時鐘 RPC 快取，任何變更一次失效。
 *
 * 任何「活動已變更」（建立/完成/新增）都呼叫 notifyActivityChanged()，
 * 所有訂閱者（清單、膠囊、時鐘）即時重載，時鐘快取同步清空。
 */
import { EventBus } from "@odoo/owl";

const bus = new EventBus();

// 工具列時鐘 RPC 快取：鍵 = `resModel:resId`，短 TTL。
const CLOCK_CACHE = new Map();
const CLOCK_TTL = 15000; // ms

export function getClockCache(key) {
    const cached = CLOCK_CACHE.get(key);
    return cached && Date.now() - cached.ts < CLOCK_TTL ? cached : null;
}

export function setClockCache(key, value) {
    CLOCK_CACHE.set(key, { ...value, ts: Date.now() });
}

export function deleteClockCache(key) {
    CLOCK_CACHE.delete(key);
}

/** 廣播「活動已變更」：清空時鐘快取並通知所有訂閱者重載。 */
export function notifyActivityChanged() {
    CLOCK_CACHE.clear();
    bus.trigger("changed");
}

/** 訂閱變更；回傳取消訂閱函式（於 onWillUnmount 呼叫）。 */
export function subscribeActivityChanged(callback) {
    bus.addEventListener("changed", callback);
    return () => bus.removeEventListener("changed", callback);
}
