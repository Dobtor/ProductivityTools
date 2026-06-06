/** @odoo-module **/

import { loadJS, loadCSS } from "@web/core/assets";

/**
 * 動態載入 bpmn.io 函式庫（放於 dobtor_bpmn/static/lib/）。
 * 函式庫體積大且需另外取得（見 static/lib/bpmn-io/README.md），
 * 因此採執行期載入 + 優雅降級：缺檔時回傳 false，由元件顯示放置說明。
 */

const LIB_BASE = "/dobtor_bpmn/static/lib/bpmn-io";

let _bpmnPromise = null;
let _dmnPromise = null;

export async function ensureBpmnLib() {
    if (window.BpmnJS) {
        return true;
    }
    if (!_bpmnPromise) {
        _bpmnPromise = (async () => {
            try {
                await loadCSS(`${LIB_BASE}/bpmn-js.css`);
                await loadCSS(`${LIB_BASE}/bpmn-js-properties-panel.css`);
                await loadJS(`${LIB_BASE}/bpmn-modeler.production.min.js`);
                return !!window.BpmnJS;
            } catch {
                return false;
            }
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
            try {
                await loadCSS(`${LIB_BASE}/dmn-js.css`);
                await loadJS(`${LIB_BASE}/dmn-modeler.production.min.js`);
                return !!window.DmnJS;
            } catch {
                return false;
            }
        })();
    }
    return _dmnPromise;
}
