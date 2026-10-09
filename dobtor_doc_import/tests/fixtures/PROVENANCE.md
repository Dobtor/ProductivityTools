# fixtures 的來源憑證

82MB、11 個目錄、352 份 .docx ＋ 126 張 golden PNG。**每一個目錄都被 8–41 支
vitest 引用**（2026-10-09 量過），沒有閒置的。

| 目錄 | 大小 | 來源 | 產生／取得方式 |
|---|---|---|---|
| `01_simple` ~ `06_template` | 65MB | 真實台灣工程／監造文件（監造會議記錄、自主檢查表、估驗計價單…） | 人工收集 |
| `07_chart`、`08_smartart`、`09_omml` | 148KB | 從工程資料的 xlsx / pptx 抽出真實 Chart / SmartArt OOXML part 重新打包；OMML 無真實來源，以 synthetic 補齊 | **`tools/build_phase5_fixtures.py`** |
| `10_ooxml_libreoffice` | 6.6MB | LibreOffice/core 的 Writer OOXML 回歸語料庫 | **`tools/fetch_ooxml_fixtures.py`**（見該目錄的 `PROVENANCE.md`） |
| `11_perf_synthetic_large` | 44KB | synthetic 大檔，給效能量測 | `tools/build_phase5_fixtures.py` |

## 為什麼要有這份

`tools/build_phase5_fixtures.py` **沒有任何地方引用它**——它的產出（07/08/09/11）
已經 commit 了，所以日常不會再跑。2026-10-09 清理時它因此被列為「無人引用」的
刪除候選，但它其實是那四個目錄**唯一的來源憑證**：沒有它就無法重現、也無法
稽核那些 fixture 是怎麼來的。

同樣的狀況 `10_ooxml_libreoffice` 早就有自己的 `PROVENANCE.md` 記著，所以
`fetch_ooxml_fixtures.py` 沒被誤判。這份補的就是另外四個目錄缺的那一塊。

**不要因為「grep 不到引用」就刪掉 `tools/` 下的 fixture 產生器。**

## golden PNG 怎麼產

`make fixtures-golden` → 容器內 LibreOffice headless + pdftoppm。
視覺回歸拿 canvas 渲染結果與它們 pixelmatch 比對。

`.visual_regression_tmp/` 是每次 VR 跑出來的渲染結果與 diff 圖，已被
`.gitignore`；可以隨時刪，下次跑會重生。
