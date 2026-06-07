# dmn-js（vendored）

本資料夾為 **dmn-js（dmn-modeler）正式發行版，直接打包進模組**，
由 `__manifest__.py` 的 `web.assets_backend` 載入；**不再 runtime load / CDN fallback**。

- 版本：dmn-js v16.8.2（dmn-modeler）
- 來源：https://unpkg.com/dmn-js@16.8.2/dist/
- 授權：bpmn.io license（MIT 風格，Camunda Services GmbH）。詳見檔頭授權標註。
- 全域：UMD 載入後掛 `window.DmnJS`（= DmnModeler）。

## 內容
```
dmn-modeler.production.min.js     主程式（DRD + 決策表 + literal）
assets/dmn-js-shared.css
assets/dmn-js-drd.css
assets/dmn-js-decision-table.css
assets/dmn-js-decision-table-controls.css
assets/dmn-js-literal-expression.css
assets/dmn.css                    圖示字型（url 參照 ../font/）
font/dmn.{eot,svg,ttf,woff,woff2} 圖示字型檔
```

## 升級
重新自 unpkg 下載對應版本覆蓋本資料夾；`assets/dmn.css` 的字型相對路徑
`../font/` 需對齊 `dmn-io/font/`。
