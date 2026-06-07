# dobtor_approval — L1 簽核流程簡易精靈 設計與實作

> 文件版本：v1.0 ｜ 撰寫日：2026-06-07 ｜ 目標 Odoo：18.0
> 定位：讓不懂 BPMN 的人「填幾關→誰簽→會簽/依序」即一鍵產生可執行的線性簽核流程。

## 1. Context
反轉後 approval 已能獨立從零設計流程（process_editor + 空白 BPMN），但對一般員工仍需懂畫圖。本精靈提供**最低門檻入口**：純填表 → 後端自動產生線性 BPMN + node_config + role，再開啟編輯器微調/發佈。

## 2. 架構決策
- **前端＝自寫 OWL client action**（非 Odoo 原生 TransientModel form），**碼風格比照 `dobtor_finance_reports`**（modal 卡片 + section + `_t` + 品牌色票）。理由：步驟卡片／即時預覽鏈／inline 能力提示，原生 form 做不到；且與 approval 既有 `process_editor.js`（同為自寫 OWL）一致。
  - ⚠️ 此處刻意偏離 `DESIGN_SELF_SERVICE_DESIGNER.md §3.4`「精靈＝原生 wizard 畫面」的原註記。
- **後端傳輸＝`orm.call` 到 model 方法**（非 controller route），與 approval 既有編輯器一致、權限走 ORM ACL。

## 3. UI/UX（已實作）
單頁 modal：① 基本（流程名稱）② 簽核關卡（可上下移/刪除的清單）③ 進階（摺疊，選填）。底部：取消 / 產生流程。
- 「由誰簽」L1 精簡 5 項；參數欄依選擇動態切換（級數／職位下拉／人員多選）。
- 即時預覽鏈：`申請 → … → 完成`，邊填邊更新。
- 能力提示：用到會簽/依序(T1)、加簽(T3) 時黃字提醒（不阻擋產生，發佈時才守門）。

檔案（folder-per-component）：
```
static/src/components/flow_wizard/
  flow_wizard.js                 # FlowWizardDialog（Dialog 元件）
  flow_wizard_list_controller.js # 自訂 ListController + listView 註冊
  flow_wizard.xml                # Dialog 模板 + list buttonTemplate
  flow_wizard.scss
```

### 優化（2026-06-07 第二版）
- **真 Dialog over list**：改用 `Dialog` 元件，經自訂 `FlowWizardListController`（list `js_class="bpmn_executable_process_list"` + `buttonTemplate` 繼承 `web.ListView.Buttons`）以 dialog service 開在 list 之上，保留清單脈絡（取代原 client action 全螢幕）。
- **拖曳排序**：`useSortable`（手柄 `.o_appr_drag`）取代上下移按鈕。
- **m2o/m2m autocomplete**：職位/人員/dry-run 申請人改用 `AutoComplete` + `name_search`（取代全載 `<select>`）。
- **dry-run「誰會簽」**：`preview_wizard_approvers(step, applicant_id)` 以 NewId 暫存 role 重用真實解析邏輯；精靈內選申請人→試算→逐關顯示簽核人。

## 4. 後端產生器（`bpmn.executable.process`，在 bpmn_process_editor.py）
`generate_from_wizard(payload)`：
1. `_wizard_build_xml(steps)` 產生線性 BPMN（Start→UserTask×N→End）+ DI 版面（左→右排版、waypoint 接形狀邊界）。
2. 依選項推算 `capability_level`（會簽/依序→T1、加簽→T3，取最高）。
3. `create` 流程 → `_sync_node_configs_from_xml` 建 node_config。
4. 逐關建 `bpmn.role`（resolver 參數）＋寫回該關 node_config（role/mode/escalate/sla）。
5. 選填：綁定單據（傳模型技術名 → 解析 `ir.model` → 建 `bpmn.action.gate`）。
6. 回傳 `action_open_process_editor()` 直接開編輯器。

## 5. 精靈 → 後端對映
| 精靈輸入 | 後端 |
|----------|------|
| 流程名稱 | `bpmn.executable.process.name` |
| 關卡順序 | 線性 BPMN 串接 + node_config.sequence |
| 由誰簽 + 參數 | `bpmn.role`（direct_manager / department_manager / manager_level+level / job_position+job_id / specific_user+user_ids） |
| 簽核方式 | `node_config.approval_mode`（any/all/sequential） |
| 加簽 | `node_config.allow_escalation` |
| 每關期限/逾期 | `node_config.sla_hours / sla_action` |
| 綁定單據(技術名)+動作 | `bpmn.action.gate`（model_id 由技術名解析 + method_name） |

## 6. 入口
- 簽核流程定義 list（`js_class="bpmn_executable_process_list"`）控制面板的 **「精靈建立」按鈕**（buttonTemplate 注入）→ dialog service 開 `FlowWizardDialog` 於 list 之上。
- 入口收斂為此單一處（移除原 client action 與獨立選單，因 Dialog over list 已是主路徑；list 本身可由 流程設定 → 簽核流程定義 抵達）。

## 7. v1 範圍 vs roadmap
- **v1（本實作）**：線性多關 + 5 種簽核人 + 單人/會簽/依序 + 加簽 + SLA + 選配綁單據。
- **roadmap**：條件分歧（金額>X 加一關）、流程樣板庫（一鍵套請假/採購）、「誰會簽」dry-run 預覽（後端 `preview_approvers` 已可接）、職位/人員改用 m2o autocomplete widget。

## 8. 驗證
- 靜態：py_compile、XML well-formed（含 OWL 模板）、JS `node --check`、`_wizard_build_xml` 產出經 lxml 確認合法 BPMN（含引號標籤 quoteattr 逸出）。
- 實機（使用者）：簽核流程定義 → 精靈建立 → 填 2–3 關 → 產生 → 應開啟編輯器並見線性流程圖；含會簽且未開 T1 → 發佈被守門擋下。
