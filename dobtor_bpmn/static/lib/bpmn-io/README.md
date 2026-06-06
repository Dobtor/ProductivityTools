# bpmn.io 函式庫放置說明

本模組的視覺編輯器使用 [bpmn.io](https://bpmn.io) 的 **bpmn-js** 與 **dmn-js**。
這些函式庫體積大、且非本模組授權範圍，需自行取得官方 dist 檔放於此資料夾。
模組在缺檔時仍可安裝（編輯器會顯示本說明、並可改用 XML 原始碼分頁編輯）。

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
