# 方案知識案例檔

本目錄放「實機驗證 → 方案知識案例庫」的匯入檔（格式 `corpaas.case/1`，說明見知識模組
`dobtor_corpaas_knowledge/services/case_lib.py` 的 `FORMAT_DOC`）。

## finance_tw_2026_11.json

2026-11-01 demo-accounting 八個財會自定模組全面驗證整理成的案例與政策。

| 模組 | 案例 |
| --- | --- |
| dobtor_accounting（付款／收款沖帳單、差額、全域捨入、應收對帳單） | 12 |
| dobtor_account_reconcile（網銀匯入） | 6 |
| dobtor_account_voucher（傳票送審、複核、主管簽核、裝訂） | 12 |
| dobtor_account_close（關帳檢查、年度結轉） | 12 |
| dobtor_account_asset（折舊表、除帳、第二軌帳簿） | 11 |
| dobtor_account_check（收票、託收、兌現、退票、應付票據、套印） | 12 |
| dobtor_account_payment_request（付款請款、客戶請款） | 12 |
| dobtor_uniform_invoice（本機字軌開立、作廢、折讓、統編檢查碼） | 9 |

共 86 個案例（source=verification，65 個 narrative_ok）、10 條方案層政策。

## 用匯入精靈匯入

1. 主控台：基礎設施 → 方案知識 → 事實層 → **匯入案例（實機驗證）**（要有知識管理員群組）。
2. 選方案（財務會計方案）；客戶留空（政策會匯成方案層；填了客戶就變成該客戶的客戶層政策）。
3. 上傳 `finance_tw_2026_11.json` → 按「檢查」。預期：合格 86、不合格 0。
4. 按「匯入」。案例以（模組, 代碼）、政策以（方案, 代碼）upsert，重匯不會重複；內容沒變的案例保留上次執行結果。
5. 在方案表單按「執行案例」，在說明庫的一次性容器裡跑。跑完一律回滾。

## 說明庫要先準備的東西

- **角色帳號**：案例用的角色有 `accountant`、`preparer`、`reviewer`、`reviewer2`、`approver`。說明庫的 role_logins 要把這五個角色對應到帳號，群組如下。
  - accountant：會計管理員，加上八模組各自的主管群組（資產、關帳、票據、請款核准、客戶請款核准、銀行對帳、傳票主管、沖帳主管、發票主管）。
  - preparer：會計使用者，加上各模組的作業群組（傳票製票、請款、客戶請款、沖帳、票據、關帳、資產、發票）。
  - reviewer、reviewer2：會計管理員加傳票複核。要兩個不同的人，職務分工的案例才測得到。
  - approver：會計管理員，加上傳票主管、請款核准、客戶請款核准。
  - 注意：沒有對應時，執行器會改用「群組裡第一個使用者」。這樣製票和複核可能落到同一個人，職務分工的案例會失準。
- **台灣科目表**：公司國家要是台灣、科目表要是 `tw`。沖帳案例用到 613400 等科目代碼。
- **不串接電子發票服務商**：要有一筆 `tw.einvoice.provider`，code=`offline`、狀態啟用（enabled／test），而且**不帶字軌**。原因有兩個。
  - 服務商的啟用狀態存在 state 欄位，案例不能直接寫，所以發票案例用 domain 找這一筆。
  - 「沒有字軌時開立被擋」這個案例要靠這筆服務商沒有字軌。
  - 案例不會呼叫任何真實電子發票平台。
- **wkhtmltopdf**：關帳案例會封存報表包 PDF，說明庫容器要裝 wkhtmltopdf，否則有 4 個關帳案例會失敗。

## 2026-11-02 本機實跑結果

- 環境：本機資料庫 kbcase，安裝八模組、l10n_tw 與 dobtor_corpaas_knowledge，科目表 tw。
- 結果：85 pass、1 fail。
- 失敗的是 `dobtor_account_close:close_manager_runs_setup_wizard`，屬於**產品缺陷**：
  - 關帳主管不是系統管理員時，按關帳設定精靈的「套用」會被 res.company 寫入權限擋下（AccessError）。
  - 位置：`dobtor_account_close/wizard/tw_close_setup.py` 的 `action_apply`，對公司 write 時沒有 sudo。
  - 選單和 ACL 都只開給關帳主管。

## 格式限制（寫新案例時要知道）

- given 不能帶 context。所以「新增傳票」存檔即建草稿傳票（`tw_voucher_draft_on_create`）沒有直接案例，只驗了送審和複核那兩步。
- 沒有記錄就叫不到的模型層方法，例如銀行對帳工作台 `tw.reconcile.workbench` 的 apply／undo，寫不成案例。
- 設定值一律用 `res.config.settings` 的 values，再加上 via `execute` 寫入。沖帳案例會先呼叫 `action_tw_offset_load_defaults`，ADVKEEP 等差額原因才會存在。
