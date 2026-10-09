# 完工判準（`make done`）

這份文件存在的理由很具體：2026-10-09 當天「全部修正優化完成了嗎？」被問了四次，
而我每次回答之後都還能再找到東西。原因不是程式越改越糟，是**「完成」當時沒有
判定方法**：

1. 「沒有缺陷」不可證明——只能說「用哪幾把尺量過」。
2. 每換一把新尺就量到新東西，是因為**尺是新的**，不是程式變差了。
3. 沒有東西讓它「保持」完成。CI 已依指示撤掉（ADR-028），所以今天全綠只代表
   今天有人跑了。

所以「完成」在這裡被定義成**一組有限、可機器判定的判準**，而不是一種感覺。
從此「完成了嗎」的答案是：

```bash
cd dobtor_doc_editor && make done; echo "判決 = $?"
```

退出碼：`0` 全部通過／`1` 有判準沒過／`2` 環境不具備（容器沒跑、缺工具）。
**`2` 不是通過**——「環境不具備」與「通過」必須分得出來，這是本模組反覆抓到的
失效模式（見 [static_check_silent_pass_patterns 的五種形狀](architecture_decision.md#adr-034不可達-ts-子系統按軸分類不按-phase)
與 `tests/unit/measurement_gates.test.ts`）。

## 判準清單

每條判準有一個 **ID**。`tests/scripts/run_done_check.sh` 必須實作**同一組** ID
——這件事由 `tests/test_done_criteria.py` 強制（文件多一條、腳本少一條，
或反過來，都會紅）。沒有那道測試，這份文件就會變成另一個「宣告了但沒人執行」。

| ID | 判準 | 為什麼它在清單裡 |
|---|---|---|
| `git-clean` | 工作樹沒有未提交變更 | 有未提交的東西就不叫完成 |
| `git-pushed` | 本機沒有未推送的提交 | 只在本機的完成不是完成 |
| `core-static` | 核心 `make ci-all` 退出 0 | flake8 / manifest / XML / JS 單測 |
| `import-static` | 匯入 `make ci-all` 退出 0 | typecheck ＋ vitest ＋ 三產物 ＋ manifest ＋ XML |
| `core-tests` | 核心後端測試 0 失敗且**測試數 > 0** | 0 則不算過（打錯 tag 會回「0 failed of 0 tests」） |
| `import-tests` | 匯入模組 Odoo 測試 0 失敗且測試數 > 0 | 測試數 > 0 的理由同上；另外這個模組的 `ci-python` 曾經**從拆模組起就必定失敗**（scope 寫死已搬走的 `models/`），所以它的測試有沒有在跑要獨立確認 |
| `core-standalone` | **只裝核心**（獨立資料庫）0 失敗，且 `dobtor_doc_import` 為 uninstalled | 拆模組（ADR-033）仍然乾淨的證明 |
| `tour` | 瀏覽器 tour 真的跑完（不是被 skip） | 後端容器沒瀏覽器時 Odoo 會「跳過」而不是失敗 |
| `artifacts-present` | 三個 build 產物都存在 | `parse_docx_cli.cjs` 曾被 `.gitignore` 排除，`engine=ts` 從沒運作過 |
| `artifacts-reproducible` | 重建產物後版控仍乾淨（byte-identical） | 產物漂移＝出貨的與版控的不是同一份 |
| `upgrade-path` | 既有資料庫升得上來，而且 migration 真的改到資料 | 到 2026-10-09 之前**所有**驗證都是乾淨安裝或同版 `-u`，那兩種都跑不到 migration。而 security 與出貨範本的資料檔都是 `<data noupdate="1">`——改 XML 對既有資料庫無效，修正只能靠 migration 送達。少了這條判準，「新安裝拿得到修正、既有資料庫拿不到」這種最糟的半修好狀態不會有任何東西發現 |
| `no-public-routes` | 兩模組 `auth='public'` 路由數 = 0（AST 判定，不用 grep） | 2026-10-09 收緊 fonts 兩條之後的現況；要新增就改這條判準 |

## 這份清單**不**保證什麼

不保證「沒有缺陷」。它保證的是：**這 11 條判準今天成立，而且任何一條退步都會
有東西變紅。** 稽核面的窮舉是另一份文件的事（見 `AUDIT_LENSES.md`）——
那份列的是「還沒用過的尺」，分母在那裡，不在這裡。

## 新增判準的規矩

1. 這份表加一列（含 ID 與「為什麼它在清單裡」）。
2. `run_done_check.sh` 實作同一個 ID。
3. 跑 `tests/test_done_criteria.py` 確認兩邊對得上。

**不要**只做 1 或只做 2。只做 1 會得到一份沒人執行的宣言；只做 2 會得到一個
沒人知道為什麼存在的檢查——這兩種形狀本模組都踩過。
