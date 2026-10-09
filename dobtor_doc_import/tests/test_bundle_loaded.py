"""瀏覽器真的載到自寫的 OOXML Parser bundle 了嗎。

☠️ 為什麼需要在**真瀏覽器**裡問這一句：`canvas-editor-custom.umd.js` 在
2026-10-09 之前從未掛進任何 manifest（ADR-032）——rollup 產得出來、git 也追蹤
著，但沒有 bundle 載它，所以瀏覽器端的 parser 從頭到尾沒被執行過。

那種「存在但不載入」的狀態**不會報錯**：
- 後端測試碰不到 assets
- 靜態檢查也抓不到——manifest 裡本來就沒有那一行，沒有「缺檔」可報
- 唯一的消費者是驗收用的方法，沒人呼叫就不會出錯

所以只有「載完 assets 之後問那個全域在不在」擋得住。

用 `browser_js` 而不是 tour：這一則不需要編輯器掛載、不需要 context 帶
template_id，只需要 backend 的 assets 載完。tour 的啟動骨架（專用 action、
_tour_content）是為了那些需求存在的，這裡用不到。
"""
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestCustomBundleLoaded(HttpCase):

    def test_dobtor_canvas_editor_global_is_present(self):
        """載完 web.assets_backend 之後，window.DobtorCanvasEditor 必須存在。"""
        self.browser_js(
            '/odoo',
            """
            (async () => {
                const lib = window.DobtorCanvasEditor;
                if (!lib) {
                    throw new Error(
                        "window.DobtorCanvasEditor 不存在——"
                        + "canvas-editor-custom.umd.js 沒被 dobtor_doc_import 的 "
                        + "web.assets_backend 載入");
                }
                for (const name of ["OoxmlParser", "ToCanvasEditor"]) {
                    if (typeof lib[name] !== "function") {
                        throw new Error(
                            "DobtorCanvasEditor." + name + " 不是 function（是 "
                            + typeof lib[name] + "）——bundle 版本不對");
                    }
                }
                // patch 也要真的生效——bundle 載了卻沒有消費者等於白載 425KB
                const cmp = window._docEditorCmp;
                if (cmp && typeof cmp.importViaBrowserParser !== "function") {
                    throw new Error(
                        "DocEditor 沒有 importViaBrowserParser——"
                        + "patch_doc_editor_import.js 沒載入或 patch 失敗");
                }
                console.log("test successful");
            })();
            """,
            login='admin',
        )
