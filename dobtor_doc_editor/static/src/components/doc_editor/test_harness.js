/**
 * test_harness.js — Phase F 視覺回歸測試啟動腳本
 *
 * 使用流程：
 *   1. /dobtor_doc_editor/test?fixture=<rel> 回傳 clean HTML（test_layout.xml）
 *   2. 此 harness 讀 fixture name → fetch /dobtor_doc_editor/test_data → 取 IElement[]
 *   3. 用 IElement[] 建立 canvas-editor instance（不走 Owl Component）
 *   4. 等待 canvas 元素出現 + 字型 ready → 設 window.__canvasEditorReady = true
 *   5. puppeteer 等到 ready flag 再 screenshot.element('canvas')
 *
 * 為何不走 Owl：
 *   - test 頁面是 clean HTML（無 Odoo backend webclient），Owl runtime 沒載入
 *   - 此 harness 只負責「啟動 canvas-editor + 設 ready flag」單一目的，不涉及 AutoSave/Offline
 *
 * 與 doc_editor.js 的差異：
 *   - doc_editor.js 是完整編輯器（AutoSave / Offline / Leader Election）
 *   - test_harness.js 純展示用，給 puppeteer 截圖比對
 */
(function () {
    'use strict';

    function setReadyFlag() {
        // 雙 rAF 確保 canvas-editor 真的把 pixel 畫上去
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                window.__canvasEditorReady = true;
                console.log('[Phase F] window.__canvasEditorReady = true');
            });
        });
    }

    function showError(msg) {
        var container = document.getElementById('ce-test-container');
        if (container) {
            container.innerHTML = '<pre style="color:red;padding:1em;">[Phase F] ' + msg + '</pre>';
        }
        console.error('[Phase F]', msg);
        // 仍設 ready flag 讓 puppeteer 不會卡死，由它讀 console error
        window.__canvasEditorReady = true;
    }

    function bootEditor(elements) {
        var container = document.getElementById('ce-test-container');
        if (!container) {
            showError('#ce-test-container not found');
            return;
        }

        var CE = window['canvas-editor'];
        if (!CE) {
            showError('canvas-editor library not loaded (window["canvas-editor"] is undefined)');
            return;
        }

        // canvas-editor UMD 暴露介面：CE.Editor（與 doc_editor.js 用同一 pattern）
        var Editor = CE.Editor || CE.default;
        var PageMode = CE.PageMode;

        if (typeof Editor !== 'function') {
            showError('canvas-editor Editor constructor not found in window["canvas-editor"]');
            return;
        }

        try {
            var editor = new Editor(container, { main: elements }, {
                pageMode: PageMode ? PageMode.PAGING : undefined,
            });
            window._docEditor = editor;
        } catch (e) {
            showError('canvas-editor init failed: ' + (e && e.message ? e.message : String(e)));
            return;
        }

        // 等待 canvas 元素出現 + 字型 ready
        var fontsReady = (document.fonts && document.fonts.ready)
            ? document.fonts.ready
            : Promise.resolve();

        // 觀察 container 內 canvas 出現
        var canvasAppeared = new Promise(function (resolve) {
            if (container.querySelector('canvas')) { resolve(); return; }
            var obs = new MutationObserver(function () {
                if (container.querySelector('canvas')) {
                    obs.disconnect();
                    resolve();
                }
            });
            obs.observe(container, { childList: true, subtree: true });
            // 5 秒 timeout fallback
            setTimeout(function () { obs.disconnect(); resolve(); }, 5000);
        });

        Promise.all([fontsReady, canvasAppeared]).then(setReadyFlag);
    }

    function fetchAndBoot() {
        // 從 data attribute 取 fixture（test_layout.xml 設定）
        var container = document.getElementById('ce-test-container');
        var fixture = container && container.getAttribute('data-fixture');
        if (!fixture) {
            // fallback：從 URL query string 取
            var params = new URLSearchParams(location.search);
            fixture = params.get('fixture');
        }
        if (!fixture) {
            showError('missing fixture parameter');
            return;
        }

        // Odoo type='json' 路由要求 JSON-RPC 2.0 包裝
        fetch('/dobtor_doc_editor/test_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: { fixture: fixture },
            }),
        }).then(function (resp) {
            if (!resp.ok) {
                throw new Error('HTTP ' + resp.status);
            }
            return resp.json();
        }).then(function (data) {
            if (data.error) {
                showError('JSON-RPC error: ' + JSON.stringify(data.error));
                return;
            }
            var result = data.result || {};
            if (result.error) {
                showError('test_data error: ' + result.error);
                return;
            }
            if (!result.elements || !Array.isArray(result.elements)) {
                showError('test_data: missing or invalid elements');
                return;
            }
            bootEditor(result.elements);
        }).catch(function (err) {
            showError('fetch failed: ' + (err && err.message ? err.message : String(err)));
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fetchAndBoot);
    } else {
        fetchAndBoot();
    }
})();
