/** @odoo-module **/

import { browser } from "@web/core/browser/browser";

/**
 * 建立一個「去抖批次載入器」。
 *
 * 同一個 `delay` 時間窗內，所有對不同 id 的請求會被合併成單一次後端呼叫，
 * 避免「N 個元件 = N 次往返」。用於同頁多顆活動膠囊、多則訊息等場景。
 *
 * @param {(orm: object, ids: number[]) => Promise<object|Map>} fetchBatch
 *        實際抓取函式，回傳一個 id → 值 的對映（物件或 Map）。
 * @param {{delay?: number, fallback?: any}} [options]
 *        delay：合併時間窗（毫秒，預設 50）；fallback：對映中缺該 id 時回傳值。
 * @returns {(orm: object, id: number) => Promise<any>} 對單一 id 請求的函式。
 */
export function createBatchLoader(fetchBatch, { delay = 50, fallback = null } = {}) {
    let pending = new Map(); // id -> [resolve, ...]
    let timer = null;
    let lastOrm = null;

    async function flush() {
        const waiters = pending;
        const orm = lastOrm;
        pending = new Map();
        timer = null;

        const ids = [...waiters.keys()];
        let mapping = {};
        if (ids.length && orm) {
            try {
                mapping = await fetchBatch(orm, ids);
            } catch (e) {
                mapping = {};
            }
        }
        const get =
            mapping instanceof Map ? (id) => mapping.get(id) : (id) => mapping[id];

        for (const [id, resolvers] of waiters) {
            const value = get(id);
            for (const resolve of resolvers) {
                resolve(value === undefined ? fallback : value);
            }
        }
    }

    return function request(orm, id) {
        lastOrm = orm;
        return new Promise((resolve) => {
            if (!pending.has(id)) {
                pending.set(id, []);
            }
            pending.get(id).push(resolve);
            if (!timer) {
                timer = browser.setTimeout(flush, delay);
            }
        });
    };
}
