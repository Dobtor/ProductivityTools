# bpmn-js（vendored）

本資料夾為 **bpmn-js（bpmn-modeler）正式發行版，直接打包進模組**，
由 `__manifest__.py` 的 `web.assets_backend` 載入；**不再 runtime load / CDN fallback**。

- 版本：bpmn-js v17.11.1（bpmn-modeler）
- 來源：https://unpkg.com/bpmn-js@17.11.1/dist/
- 授權：bpmn.io license（MIT 風格，Camunda Services GmbH）。詳見檔頭授權標註。
- 全域：UMD 載入後掛 `window.BpmnJS`（= BpmnModeler）。

## 內容
```
bpmn-modeler.production.min.js     主程式
assets/diagram-js.css
assets/bpmn-js.css
assets/bpmn.css                    圖示字型（url 參照 ../font/）
font/bpmn.{eot,svg,ttf,woff,woff2} 圖示字型檔
```

## 升級
重新自 unpkg 下載對應版本覆蓋本資料夾；`assets/bpmn.css` 的字型相對路徑
`../font/` 需對齊 `bpmn-io/font/`。

> 註：`static/src/modeler/lib_loader.js`（舊的動態載入器）已無人引用，保留僅為相容。
> dmn-js 同樣已 vendored，見 `../dmn-io/README.md`。
