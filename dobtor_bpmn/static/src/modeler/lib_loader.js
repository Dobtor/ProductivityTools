/** @odoo-module **/

import { loadJS, loadCSS } from "@web/core/assets";

/**
 * 載入 bpmn.io 函式庫（bpmn-js / dmn-js）。
 * 策略：本地優先（static/lib/bpmn-io/）→ 失敗則 CDN 後援（unpkg）。
 * 只對「JS 載入成功的來源」載入其對應 CSS，避免對不存在的本地 CSS 發出
 * 404 → 觸發瀏覽器 "Refused to apply style (MIME text/html)" 噪音。
 * 兩來源皆失敗（離線 + 無本地檔 + CSP 擋外連）才回傳 false，由元件顯示放置說明。
 */

const LOCAL = "/dobtor_bpmn/static/lib/bpmn-io";
const CDN_BPMN = "https://unpkg.com/bpmn-js@17/dist";
const CDN_DMN = "https://unpkg.com/dmn-js@16/dist";

let _bpmnPromise = null;
let _dmnPromise = null;

/** 依序嘗試各來源的 JS，第一個成功者回傳其設定（含對應 css 清單）。 */
async function loadFirstSource(candidates) {
    for (const cand of candidates) {
        try {
            await loadJS(cand.js);
            return cand;
        } catch {
            // 換下一個來源
        }
    }
    return null;
}

async function bestEffortCSS(urls) {
    for (const url of urls) {
        try {
            await loadCSS(url);
        } catch {
            // CSS 缺失不致命（圖仍可運作，僅樣式略缺）
        }
    }
}

export async function ensureBpmnLib() {
    if (window.BpmnJS) {
        return true;
    }
    if (!_bpmnPromise) {
        _bpmnPromise = (async () => {
            const src = await loadFirstSource([
                {
                    js: `${LOCAL}/bpmn-modeler.production.min.js`,
                    css: [
                        `${LOCAL}/bpmn-js.css`,
                        `${LOCAL}/bpmn-js-properties-panel.css`,
                    ],
                },
                {
                    js: `${CDN_BPMN}/bpmn-modeler.production.min.js`,
                    css: [
                        `${CDN_BPMN}/assets/diagram-js.css`,
                        `${CDN_BPMN}/assets/bpmn-js.css`,
                        `${CDN_BPMN}/assets/bpmn-font/css/bpmn.css`,
                    ],
                },
            ]);
            if (!src || !window.BpmnJS) {
                return false;
            }
            await bestEffortCSS(src.css);
            return true;
        })();
    }
    return _bpmnPromise;
}

export async function ensureDmnLib() {
    if (window.DmnJS) {
        return true;
    }
    if (!_dmnPromise) {
        _dmnPromise = (async () => {
            const src = await loadFirstSource([
                {
                    js: `${LOCAL}/dmn-modeler.production.min.js`,
                    css: [`${LOCAL}/dmn-js.css`],
                },
                {
                    js: `${CDN_DMN}/dmn-modeler.production.min.js`,
                    css: [
                        `${CDN_DMN}/assets/dmn-js-shared.css`,
                        `${CDN_DMN}/assets/dmn-js-drd.css`,
                        `${CDN_DMN}/assets/dmn-js-decision-table.css`,
                        `${CDN_DMN}/assets/dmn-js-decision-table-controls.css`,
                        `${CDN_DMN}/assets/dmn-font/css/dmn.css`,
                    ],
                },
            ]);
            if (!src || !window.DmnJS) {
                return false;
            }
            await bestEffortCSS(src.css);
            return true;
        })();
    }
    return _dmnPromise;
}
