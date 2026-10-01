# dobtor_corpaas_knowledge_proposal — 服務建議書／評估報價／預估成本

CorPaaS 方案知識核心（`dobtor_corpaas_knowledge`）的出口三。規格：
`dobtor_corpaas_knowledge/IMPLEMENTATION_SPEC.md`「模組 C」。

## 流程

1. **痛點**：手動輸入，或「匯入痛點」上傳售前 xlsx。每張部門表第 1 列標題、第 2 列表頭、第 3 列起資料
   （`# | 客戶提問／痛點 | 現況說明 | 解決方案 | 現有 or 客製 | 對應原生功能／模組 | 報價重點`）；
   只匯入表頭有「痛點／客戶提問」與「現有 or 客製」欄的部門表（總覽及其改名、彙總、待確認事項、
   解決方案總表、延伸分析表都略過；表名含「總覽／彙總／總表／待確認事項／延伸」也略過）。
   以一般模式載入（不用 read_only），往下合併的「#／痛點」併成一筆痛點，其他欄位換行串起來。
   四色 🟢原生 🔵Dobtor現有 🟠客製微調 🔴客製開發 ⚪沿用現況；⚪待確認＝不給顏色（要判斷，不能當沿用現況被排除）；
   🟣企業版（Enterprise 專屬）＝客製（CorPaaS 是 CE）。組合標籤取最先出現的顏色。
2. **AI 比對能力**：痛點＋方案能力（pain/outcome/color/可用性）→ 對應提議（四色、客製參考人天區間寫進說明）。
   按鈕排入佇列（`corpaas.knowledge.ai.enqueue(self, '_ai_match_run', package)`），完成或失敗寫在紀錄裡。
   重跑只取代「未確認的 AI 提議」。能力在方案裡是 addon 時帶入**所有**缺的模組產品（同分支優先；可單賣但沒產品的列在說明）。
3. **計算估算**：只算「已確認且非沿用現況」的對應。每個能力取它的工時範本（能力 × 工項），
   再加通用工項（範本 capability 空白，每張一次）：
   `days = base_days + ceil(driver_qty / unit_size) × per_unit_days`。
   驅動量取自建議書欄位（公司數、使用者數、角色數、串接數、訓練場次），`records_100` 取資料移轉檢核表
   該能力主資料模型的筆數 ÷ 100。檢核表模型＝情境 `seed_models()` ∪ 能力 `master_data_models`。
   設定微調：能力有工時範本就只用範本（不再疊 AI 區間中位數）；沒有範本才取中位數。客製開發一律取中位數另計。
   `records_100`：能力沒宣告主資料模型時，退回情境示範資料的模型。
   工項分類沿用 CBMC：需求設定／資料移轉／教育訓練／上線部署／專案管理。
4. **建議書**：痛點對應表、方案能力（裝了行銷模組就用 pitch 的**核准上線快照** `_live()`，不讀草稿欄位；
   否則能力 pain/outcome）、報價表（加購模組每列金額＝合計用的首年金額）、
   資料移轉檢核表；只用 Bootstrap 5／snippet class。可列印「服務建議書」與「內部成本頁」PDF。
5. **建立報價單**：方案變體一行（`package_tier`、`concurrent_users`、`storage_gb`、`committed_*`，
   價格由 dobtor_corpaas_sale 的 `_compute_price_unit` → `compute_package_price` 算）、加購模組各一行、
   每筆估算明細一行「導入服務（人天）」產品（數量＝人天、單價＝日費率）。方案變體取自方案套件
   （套件指定變體優先；週期兄弟只在同 branch_name 找）。
   **不自動開通**：訂單記 `knowledge_proposal_id`、`knowledge_provision_state='hold'`，不標 `is_to_create_paas`；
   覆寫 `sale.order._maybe_provision_by_tier()`（`action_confirm` 對每張單都呼叫它）→ 擋下並留言。
   業務按「確認開通」（`corpaas.knowledge.provision.wizard`，繼承 `corpaas.order.wizard` 的欄位與
   new／stack／change_tier 三種模式）：報價階段把模式寫到這張單（確認時照常走開通／疊加／換層級鏈）；
   已確認的單只能放行為新平台（疊加與換層級的計價不同）。客戶已有平台時模式不給預設，必須明確選。
6. **送出**：寫入 `snapshot_json`（能力、敘事、工項、價格、成本、HTML），之後建議書與痛點／對應／估算／
   檢核表一律唯讀（`write()` 擋）；只能改狀態（成交／未成交）、連報價單、工時回寫時間。要改就「複製新版」。
   送出後金額與成本欄位（stored compute）一律從快照讀，工時回寫校正範本、設定調價都不會改到。
7. **工時回寫**（需 hr_timesheet）：讀報價單關聯專案的 timesheet，以工時說明＋任務名稱（依空白與括號標點斷詞）
   ＋任務標籤（整個標籤一個詞）**整詞**比對能力 code 與工項（代碼、中文名或別名）；沒有能力 code 的工時不列入
   （通用工項要明確標「通用」），同一筆寫了兩個工項也不列入。小時 ÷ 每人天工時＝實際人天；反推基礎人天（扣掉驅動量那段）後以
   簡單移動平均（種子＝初始 base_days，視窗見設定）更新 `base_days`，留下校正歷史。同一建議書對同一範本只校正一次。
   ★ 專案結案自動回寫：本模組不依賴 `project`，自動觸發在橋接模組
   `dobtor_corpaas_knowledge_proposal_project`（auto_install，depends 本模組＋sale_project＋hr_timesheet）：
   專案 `stage_id` 進到摺疊（fold）階段時對關聯建議書呼叫 `action_feedback_actuals()`，失敗只留言不擋結案。
   沒裝橋接模組（或沒開專案階段）時仍用手動按「工時回寫」。
8. **成本與毛利**（首年）：`internal_cost = Σ 人天 × 內部人天成本 ＋ 12 × (基礎設施 ＋ 第三方 ＋ AI 點數)`。
   基礎設施＝CCU × 每 CCU 月成本（共享層且裝了 dobtor_infrastructure_cost、環境成本可信時用
   `infrastructure.environment.cost_per_ccu`）＋ 能力資源特徵（`storage_per_record_kb` × 筆數 → GB × 每 GB；
   `extra_worker_mb` ÷ worker MB ＋ `heavy_cron` 半個 worker → × 每 worker）＋ 儲存 GB × 每 GB。
   任一來源是估的（資源特徵沒標 `"calibrated": true`、工時範本未校正、主機成本用設定值、第三方沒寫金額）
   → `cost_is_estimate`，成本頁標「估算值」並列出原因。

## 訂閱價格

不自己算：`product.template.compute_package_price(tier, concurrent_users, committed_qty, storage_gb,
cycle, committed_usage)`（dobtor_corpaas_product）。週期取方案變體的 `recurring_rule_type`（有週期變體時先用
`_corpaas_cycle_variant()` 挑），與 SO 行 `_paas_cycle()` 同一來源；首年＝`cycle_total × 12 / months`。
加購模組以產品牌價估（訂閱產品依 `recurring_rule_type` 換算成一年）。

## 權限

- 業務（`sales_team.group_sale_salesman`）：建議書全權、工時範本／校正歷史唯讀、能力／情境唯讀；
  入口在「銷售 › 訂單 › 服務建議書」。
- 知識編輯：另可維護工時範本、執行工時回寫；入口在「方案知識 › 出口 › 建議書」。
- 知識管理：可刪工時範本與校正歷史。

## 設定

設定 › CorPaaS 基礎設施 › 方案知識區塊下方「服務建議書」：日費率、內部人天成本、導入服務產品、
每 CCU／GB／worker 月成本、第三方預設月費、每 AI 點成本、每人天工時、移動平均視窗。
