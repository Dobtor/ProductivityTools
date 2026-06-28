/** @odoo-module **/

/**
 * Telemetry — 前端錯誤回報 + 效能指標收集（P2-4）
 *
 * 設計：
 *   - reportError(type, payload)：呼叫 /dobtor_doc/telemetry/error
 *   - reportMetric(type, value, extra)：呼叫 /dobtor_doc/telemetry/metric
 *   - install(component)：自動掛 window.onerror / unhandledrejection / WebVitals
 *   - uninstall()：unmount 時呼叫，清掉 listener
 *
 * 失敗策略：
 *   - 所有 RPC 失敗都靜默吞掉，遙測絕不擾斷使用者體驗
 *   - 上報前去重 + rate limit（避免短時間重複錯誤洗爆 DB）
 */

import { rpc } from "@web/core/network/rpc";

const ERROR_RATE_LIMIT_MS = 5000; // 同樣訊息 5 秒內只送一次
const _recentErrors = new Map(); // key=signature → ts

// Sprint Y12.2：canvas-editor 庫內部 mousedown 計算 table 位置時偶發 throw
// （`getTablePositionList`/`getPositionList`/`getIsPointInRange`），與本模組無關。
// stack 中含這些 frame 就不上報、避免噪音洗爆 telemetry。
const _NOISE_STACK_PATTERNS = [
    /getTablePositionList/,
    /getPositionList/,
    /getIsPointInRange/,
];
function _isLibraryNoise(stack) {
    if (!stack) return false;
    return _NOISE_STACK_PATTERNS.some(re => re.test(stack));
}

function _sigOf(type, message) {
    return `${type}::${(message || "").slice(0, 120)}`;
}

function _shouldThrottle(sig) {
    const now = Date.now();
    const last = _recentErrors.get(sig);
    if (last && now - last < ERROR_RATE_LIMIT_MS) {
        return true;
    }
    _recentErrors.set(sig, now);
    // GC：保持 map < 100
    if (_recentErrors.size > 100) {
        const oldestKey = _recentErrors.keys().next().value;
        _recentErrors.delete(oldestKey);
    }
    return false;
}

export async function reportError({
    type = "other",
    message = "",
    stackTrace = "",
    docId = null,
    extra = null,
} = {}) {
    // Sprint Y12.2：跳過 canvas-editor 庫內部 mousedown 噪音
    if (_isLibraryNoise(stackTrace)) return;
    if (_shouldThrottle(_sigOf(type, message))) return;
    try {
        await rpc("/dobtor_doc/telemetry/error", {
            error_type: type,
            message: String(message || "").slice(0, 500),
            stack_trace: String(stackTrace || "").slice(0, 8000),
            user_agent: (typeof navigator !== "undefined" && navigator.userAgent) || "",
            url: (typeof location !== "undefined" && location.href) || "",
            doc_id: docId,
            extra: extra || {},
        });
    } catch {
        // 遙測失敗 → 靜默
    }
}

export async function reportMetric(metricType, value, { docId = null, pageCount = null, extra = null } = {}) {
    if (typeof value !== "number" || !Number.isFinite(value)) return;
    try {
        await rpc("/dobtor_doc/telemetry/metric", {
            metric_type: metricType,
            value: value,
            doc_id: docId,
            page_count: pageCount,
            extra: extra || {},
        });
    } catch {
        // 遙測失敗 → 靜默
    }
}

/**
 * 計時器：用法
 *   const stop = mark("load_doc_ms");
 *   ... do work ...
 *   stop({ docId, pageCount });    // 自動上報耗時
 */
export function mark(metricType) {
    const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    return (opts = {}) => {
        const t1 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        reportMetric(metricType, t1 - t0, opts);
    };
}

/**
 * Install：在 doc_editor.js setup 時呼叫，自動掛全域 listener。
 *
 * 回傳一個 cleanup function，給 onWillUnmount 用。
 */
export function installGlobalErrorReporting({ docIdGetter = () => null } = {}) {
    const onError = (event) => {
        const docId = docIdGetter();
        reportError({
            type: "js_error",
            message: event?.message || String(event),
            stackTrace: event?.error?.stack || "",
            docId,
            extra: {
                filename: event?.filename,
                lineno: event?.lineno,
                colno: event?.colno,
            },
        });
    };
    const onRejection = (event) => {
        const docId = docIdGetter();
        const reason = event?.reason;
        reportError({
            type: "promise_rejection",
            message: (reason && reason.message) || String(reason || "unknown"),
            stackTrace: (reason && reason.stack) || "",
            docId,
        });
    };

    // Sprint Y14.1：capture-phase suppressor — Odoo backend 的 error_service
    // 用 bubble 階段監聽 window 'error'、會把任何 uncaught error 彈成紅色 modal。
    // canvas-editor library 內部 mousedown 算 table 位置時偶發 throw（已在 Y12.2 telemetry
    // filter 過濾上報、但 dialog 仍會跳）。capture-phase 攔截、stack 符合 library 噪音時
    // 整段 preventDefault + stopImmediatePropagation，徹底擋掉 Odoo error_service。
    const onErrorCapture = (event) => {
        const stack = event?.error?.stack || "";
        if (_isLibraryNoise(stack)) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    };

    if (typeof window !== "undefined") {
        window.addEventListener("error", onErrorCapture, true);  // capture
        window.addEventListener("error", onError);                // bubble (telemetry)
        window.addEventListener("unhandledrejection", onRejection);
    }

    // Web Vitals 觀測（LCP / FID / CLS）— 用 PerformanceObserver
    let lcpObserver, clsObserver, fidObserver;
    let cumulativeCLS = 0;
    if (typeof PerformanceObserver !== "undefined") {
        try {
            lcpObserver = new PerformanceObserver((list) => {
                const entries = list.getEntries();
                const last = entries[entries.length - 1];
                if (last) {
                    reportMetric("web_vitals_lcp_ms", last.renderTime || last.loadTime || last.startTime, {
                        docId: docIdGetter(),
                    });
                }
            });
            lcpObserver.observe({ type: "largest-contentful-paint", buffered: true });
        } catch {
            lcpObserver = null;
        }
        try {
            clsObserver = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (!entry.hadRecentInput) {
                        cumulativeCLS += entry.value;
                    }
                }
            });
            clsObserver.observe({ type: "layout-shift", buffered: true });
        } catch {
            clsObserver = null;
        }
        try {
            fidObserver = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    reportMetric("web_vitals_fid_ms", entry.processingStart - entry.startTime, {
                        docId: docIdGetter(),
                    });
                }
            });
            fidObserver.observe({ type: "first-input", buffered: true });
        } catch {
            fidObserver = null;
        }
    }

    return function uninstall() {
        if (typeof window !== "undefined") {
            window.removeEventListener("error", onErrorCapture, true);   // Y14.1
            window.removeEventListener("error", onError);
            window.removeEventListener("unhandledrejection", onRejection);
        }
        // CLS 在 unmount 時上報最終值
        if (cumulativeCLS > 0) {
            reportMetric("web_vitals_cls", cumulativeCLS, { docId: docIdGetter() });
        }
        try { lcpObserver?.disconnect(); } catch (e) { void e; }
        try { clsObserver?.disconnect(); } catch (e) { void e; }
        try { fidObserver?.disconnect(); } catch (e) { void e; }
    };
}
