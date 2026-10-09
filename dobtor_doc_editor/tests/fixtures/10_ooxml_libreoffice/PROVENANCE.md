# OOXML 測試 fixture 來源說明

本目錄 `10_ooxml_libreoffice/` 下的 `.docx` 檔**並非本專案產出**，
而是從 LibreOffice 專案的 Writer OOXML 回歸測試語料庫下載，
做為 dobtor_doc_editor parser 的廣域回歸測試 fixture。

## 來源

- 專案：LibreOffice / core
- Repo：https://github.com/LibreOffice/core
- Commit（pinned）：`52d51655e3cdfe92893a823545f596f33f1731db`
- 目錄：
  - `sw/qa/extras/ooxmlimport/data`
  - `sw/qa/extras/ooxmlexport/data`

## 授權

LibreOffice 專案以 **MPL-2.0** 授權（部分歷史檔 LGPLv3+）。
這些測試檔隨專案散布，沿用同一授權。本目錄檔案**請勿修改**，
維持與上游一致；如需更新請重跑 `tools/fetch_ooxml_fixtures.py`。

## 注意

- 部分檔案為**故意畸形 / 加密 / 邊界**的負向測試案例，
  parser 對它們應「優雅失敗」而非崩潰——這正是測試目的。
- 檔案依檔名關鍵字粗分到各 category 子目錄，分類僅供瀏覽方便，
  不代表上游的權威分類。
- 完整檔案清單與分類見同目錄 `manifest.json`。

## 重新產生

```
python3 tools/fetch_ooxml_fixtures.py --out tests/fixtures
```
