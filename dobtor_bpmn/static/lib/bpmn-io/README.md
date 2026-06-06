# bpmn.io 函式庫放置說明

本模組的視覺編輯器使用 [bpmn.io](https://bpmn.io) 的 **bpmn-js** 與 **dmn-js**。

## 載入策略（`static/src/modeler/lib_loader.js`）
**本地優先 → CDN 後援**：
1. 先試本地 `static/lib/bpmn-io/`（若你放了 dist 檔，離線可用、不依賴外網）。
2. 本地沒有 → 自動改用 **CDN（unpkg）** 載入 `bpmn-js@17` / `dmn-js@16`。
3. 兩者皆失敗（離線且無本地檔、或 CSP 擋外連）→ 編輯器顯示提示，可改用「XML 原始碼」分頁編輯。

> 連外的環境**通常不必放任何檔案**，CDN 後援會自動讓編輯器運作。
> **離線 / 內網 / 有嚴格 CSP** 的環境，請依下方放置本地 dist 檔。
> 若 CSP 擋下 unpkg：放本地檔即可，或在反向代理放行 `unpkg.com`。

## 需要的檔案（放在 `dobtor_bpmn/static/lib/bpmn-io/`）

| 檔名 | 來源 |
|------|------|
| `bpmn-modeler.production.min.js` | bpmn-js dist（UMD，會掛載 `window.BpmnJS`） |
| `bpmn-js.css` | bpmn-js `dist/assets/bpmn-js.css` |
| `bpmn-js-properties-panel.css` | `@bpmn-io/properties-panel` 的 CSS（選用，屬性面板樣式） |
| `dmn-modeler.production.min.js` | dmn-js dist（UMD，會掛載 `window.DmnJS`） |
| `dmn-js.css` | dmn-js 的 shared/drd/decision-table CSS 合併檔 |

## 取得方式（擇一）

### A. 直接下載官方 dist
- bpmn-js：https://github.com/bpmn-io/bpmn-js（releases 內 `bpmn-modeler.production.min.js`）
- dmn-js：https://github.com/bpmn-io/dmn-js

### B. 用 npm 取出 dist（建議，含 properties-panel）
```bash
npm i bpmn-js dmn-js @bpmn-io/properties-panel bpmn-js-properties-panel
# 取出：
#   node_modules/bpmn-js/dist/bpmn-modeler.production.min.js
#   node_modules/bpmn-js/dist/assets/bpmn-js.css
#   node_modules/dmn-js/dist/dmn-modeler.production.min.js
#   node_modules/dmn-js/dist/assets/*.css  → 合併成 dmn-js.css
#   node_modules/@bpmn-io/properties-panel/dist/assets/*.css → bpmn-js-properties-panel.css
```

放好後重新整理瀏覽器（必要時清快取 / 升級模組）即可使用視覺編輯器。

## 為何不內附
- 函式庫更新頻繁、體積大，內附會讓本倉庫臃腫且難維護版本。
- 採執行期動態載入（見 `static/src/modeler/lib_loader.js`），缺檔優雅降級，不影響模組安裝。
