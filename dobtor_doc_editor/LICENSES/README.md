# 內附第三方程式碼與其授權

本模組以 **OPL-1** 散布（見模組根目錄的 `LICENSE`）。本目錄保存隨附第三方
程式碼的授權全文。

## 對應表

| 隨附檔案 | 來源 | 授權 | 全文在哪 |
|---|---|---|---|
| `static/src/lib/canvas_editor/canvas-editor.umd.min.js` | `@hufe921/canvas-editor` 0.9.128（經 jsDelivr/Terser 壓縮，來源標記保留在檔首） | MIT | `canvas-editor.LICENSE` |
| `static/src/lib/canvas_editor/canvas-editor-plugin-docx.umd.js` | 同專案的 docx plugin（打包檔，內嵌相依見下） | MIT（內嵌相依各自授權） | 授權橫幅原樣保留在該檔內 |
| `static/src/lib/canvas_editor/canvas-editor-shim.js` | 本模組自有 | OPL-1 | 模組根目錄 `LICENSE` |

## plugin-docx 內嵌的相依（從打包檔的授權橫幅實際讀出）

| 相依 | 授權 | 備註 |
|---|---|---|
| JSZip 3.10.1 | MIT **或** GPLv3 雙授權 | **本模組選用 MIT** |
| pako | MIT | JSZip 的授權聲明中載明 |
| ieee754 | BSD-3-Clause | 橫幅：`/*! ieee754. BSD-3-Clause License. Feross Aboukhadijeh */` |
| `String.fromCodePoint` shim | MIT | 橫幅：`/*! http://mths.be/fromcodepoint v0.1.0 by @mathias */` |

⚠️ 該檔中另出現 `http://schemas.zwobble.org/mammoth/style-map` 命名空間與
style-map 讀寫函式。這**可能**表示內嵌了 mammoth（或其衍生）的程式碼，但從
打包後的檔案無法確認範圍與授權。要完整盤點，應回 upstream
`@hufe921/canvas-editor` 的 plugin-docx 專案查其 `package.json`。

## 自己重查一次的方法

```bash
# 列出打包檔裡所有 /*! … */ 授權橫幅
grep -o "/\*![^*]\{0,200\}\*/" static/src/lib/canvas_editor/canvas-editor-plugin-docx.umd.js

# 找 GPL / MIT / BSD 字樣的上下文（確認是哪一支、是不是雙授權）
grep -o ".\{220\}GPL.\{220\}" static/src/lib/canvas_editor/canvas-editor-plugin-docx.umd.js
```

## 已移除的（2026-10-09）

`fflate.LICENSE` / `opentype.js.LICENSE` / `harfbuzzjs.LICENSE` 三份已刪除。
它們是**已移除的 TS OOXML 子系統**（ADR-029）的 npm 相依，會被打包進
`canvas-editor-custom.umd.js`——而那個 bundle 從頭到尾沒有掛進 manifest，且已
連同整個子系統刪除。模組現在完全沒有隨附這三個程式庫（實測 `grep -rli` 在
`static/` 下 0 筆）。

要取回：`git checkout doc-editor-before-ts-removal -- dobtor_doc_editor/LICENSES`
