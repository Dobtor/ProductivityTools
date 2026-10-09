# 這個目錄裡的 14 支 `.ts` **不是匯入功能**

它們是規畫書 Phase 8 的 **Phase 2.2（overlay 絕對定位）** 的前置程式碼
（`Overlay*` / `alignment_guide_*` / `overlay_geometry*`），而 Phase 2.2 在
規畫書 §5 是 `[ ]` **未啟動**（「僅當 Phase 2.1 實測明確不滿意才啟動」）。

查證（2026-10-09）：
- 三個 rollup entry 的 import 圖**一支都到不了** → 沒有被任何 bundle 打包
- 出貨的 `.js` 沒有任何一支引用它們
- 只有彼此、以及自己的 14 支 vitest 在引用

## 為什麼放在 `dobtor_doc_import` 而不是核心

拆模組之後**唯一有 TS 工具鏈的模組是這一個**（rollup / tsconfig / vitest /
package.json 都在這裡）。留在 `dobtor_doc_editor` 會變成：核心有 2,088 行
TypeScript、沒有任何東西能建它、它的 14 支測試還在別的模組裡。為那些程式碼
在核心複製一整套工具鏈，代價明顯不對。

## 所以這是「寄放」，不是歸屬

兩個選項留給將來：
1. Phase 2.2 真的啟動時，連同它的 UI 一起搬回核心（那時核心要嘛自備工具鏈，
   要嘛那些檔案改寫成 `.js`）
2. 確定不做 Phase 2.2 就連測試一起刪——`git log` 取回得到

**不要因為它在這個模組裡，就以為它跟 DOCX 匯入有關。**
