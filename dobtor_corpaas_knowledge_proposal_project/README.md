# dobtor_corpaas_knowledge_proposal_project — 專案結案自動工時回寫

`dobtor_corpaas_knowledge_proposal`、`sale_project`、`hr_timesheet` 都裝了就自動安裝（`auto_install`）。

## 做什麼

導入專案結案時，自動對服務建議書執行「工時回寫」，用實際 timesheet 校正工時範本。

- **結案**＝`project.project.stage_id` 從非摺疊階段進到 `fold=True` 的階段（Odoo 18 摺疊階段即視為結案）。
  在 `write()` 比對前後判斷；已結案再換到另一個摺疊階段不會重跑。
- **找建議書**：專案 `sale_line_id.order_id`（即 `sale_order_id`）或 `reinvoiced_sale_order_id`
  → `sale_order_id` 是這張報價單的建議書。沒有關聯建議書的專案不理會。
- **回寫**：直接呼叫建議書的 `action_feedback_actuals()`（比對規則、移動平均、同一建議書同一範本只校正一次，
  都沿用建議書模組）。以 sudo 執行：結案的人不一定有建議書權限。
- **只跑一次**：成功後專案記 `knowledge_feedback_done`；重新打開（移到非摺疊階段）會重設，再結案會再跑。
- **失敗不擋結案**：每張建議書包在 savepoint，失敗就回滾該次回寫、在專案留言原因（例如建議書未送出），
  專案照樣結案，旗標不設。可到建議書手動按「工時回寫」，或重新打開再結案重試。

☠️ 專案 `stage_id` 需要「專案階段」功能（`project.group_project_stages`）才看得到；沒開階段就不會自動觸發，
請用建議書上的手動按鈕。
