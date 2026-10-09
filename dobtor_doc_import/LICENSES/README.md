# 內附第三方程式碼與其授權

本模組以 **OPL-1** 散布（見模組根目錄的 `LICENSE`）。本目錄保存隨附第三方
程式碼的授權全文。

☠️ **為什麼這個目錄原本不存在**：核心模組在改用 OPL-1 時（ADR-030）建了
`dobtor_doc_editor/LICENSES/`，登記了它隨附的 canvas-editor 等。但拆模組
（ADR-033）把 **OOXML 建置鏈與它的 npm 相依整批搬到本模組**，而授權登記
留在核心——於是本模組出貨第三方程式碼、宣告 OPL-1、卻沒有任何登記。
2026-10-09 的全檔案稽核（階段 5）量到。

## 對應表

登記的依據是「**在產物裡實際找到那個函式庫的實作符號**」，不是 package.json
寫了什麼——`package.json` 的 `dependencies` 有四個，但其中兩個並沒有被打進
出貨產物（見下方「沒有內嵌的相依」）。

| 隨附檔案 | 進版控？ | 內嵌的第三方 | 授權 | 全文 |
|---|---|---|---|---|
| `static/src/lib/canvas_editor/canvas-editor-custom.umd.js` | 是（`__manifest__` 的 `web.assets_backend`） | fflate 0.8.2 | MIT | `fflate.LICENSE` |
| `tools/dist/parse_docx_cli.cjs` | 是（production 的 `engine=ts` 在用；部署端容器只有 node 沒有 npm） | fflate 0.8.2、@xmldom/xmldom 0.9.10 | MIT | `fflate.LICENSE`、`xmldom.LICENSE` |
| `tools/dist/visual_regression_pipeline.iife.js` | **不是**（只有開發端量測腳本在用，`.gitignore` 排除） | — | — | — |

判定用的符號：fflate → `strFromU8` / `inflateSync` / `unzipSync`；
@xmldom/xmldom → `__DOMHandler` / `DOMImplementation` / `appendElement` /
`ParseError`。

## 沒有內嵌的相依（package.json 有，但產物裡沒有）

| 相依 | 為什麼沒進去 |
|---|---|
| `opentype.js` 1.3.5（MIT） | 只有 `core/ooxml/font/FontMetrics.ts` 用它，而那支只在 **VR pipeline**（不進版控的產物）與 vitest 裡被走到。瀏覽器 bundle 與 node CLI 都沒有它的字型表符號（實測 `glyf` / `cmap` / `hhea` 皆 0）。若哪天把字型度量接進出貨路徑，這一列要搬到上面那張表並補 `opentype.js.LICENSE`。 |
| `harfbuzzjs` 0.10.3（MIT／Apache-2.0 雙授權） | `ShapingEngine` 目前不可達（ADR-034 的 `import` 軸宣告，附啟動條件），WASM 沒有被任何產物打包。接上線時同樣要補登記。 |

## 測試資料的第三方內容

`tests/fixtures/10_ooxml_libreoffice/` 的 **290 支 .docx** 來自 LibreOffice
專案的 Writer OOXML 回歸測試語料庫，以 **MPL-2.0** 散布（部分歷史檔 LGPLv3+）。
來源 repo、pinned commit 與授權說明在該目錄的 `PROVENANCE.md` 與
`manifest.json`。那些檔案**不隨出貨程式碼執行**，但它們隨本模組散布，
所以一併記在這裡。

## 加新相依時的規矩

1. 先確認它**會不會被打進進版控的產物**（用特徵符號查產物，不要只看
   package.json——那是「宣告」不是「事實」）。
2. 會的話：把授權全文放進本目錄，並在上面的對應表加一列（含判定符號）。
3. 不會的話：記進「沒有內嵌的相依」那張表，寫明為什麼，以及什麼情況下要
   搬到上面那張表。

**不要**只做 package.json 那一半。本模組就是那樣漏掉一整個目錄的。
