# dobtor_approval — 簽核事件改版規格建議（解耦 dobtor_mail_activity）

> 文件版本：v1.0 ｜ 撰寫日：2026-06-07 ｜ 目標 Odoo：18.0
> 三大訴求：
> 1. **移除對 `dobtor_mail_activity` 的相依**（不再 depends，也不繼承其視圖/方法）。
> 2. 簽核**事件仍以 Odoo 原生 `mail.activity` 為基礎不變**（用原生欄位/方法/chatter/提醒/行動 App）。
> 3. 在**「簽核流程」選單下自建「簽核事件」畫面**：對事件執行核准/駁回，並支援**例外向上加簽、橫向送簽**。
> 對標國內外（新人類 FlowMaster、華苓 Agentflow、叡揚｜Pega、Appian、Camunda Tasklist），目標：**更優**。

---

## 0. 為何解耦 + 自建事件畫面

| 議題 | 現況（依賴 dobtor_mail_activity） | 改版後 |
|------|----------------------------------|--------|
| 相依 | `depends=['dobtor_bpmn','mail','hr','dobtor_mail_activity']` | **`['dobtor_bpmn','mail','hr']`**（原生 mail 即足夠） |
| 事件載體 | dobtor_mail_activity 擴充版 mail.activity | **原生 `mail.activity`**（欄位/方法不改、行為單純） |
| 簽核 UI | 借用 dobtor_mail_activity 的排程/看板/表單 | **自建「簽核事件」inbox 畫面**（專為簽核設計） |
| 耦合風險 | 受對方改版牽動（曾因繼承其 view 安裝失敗） | **零耦合**，獨立可裝可賣 |

> **原則**：`mail.activity` 只當「**待辦事件的最小載體**」（誰要簽、簽什麼單據、期限），所有「簽核語意」（核准/駁回/加簽/送簽/流程推進）由 `dobtor_approval` 自有模型與畫面承載。**不污染、不依賴**他人模組。

---

## 1. 國內外對標：簽核事件處理能力

| 能力 | 新人類 FlowMaster | 華苓 Agentflow | Pega/Appian/Camunda | **dobtor_approval（目標）** |
|------|------------------|----------------|----------------------|----------------------------|
| 待辦匣/工作清單 | ✅ 待辦匣 + NT OneAPP | ✅ 待辦匣 | ✅ worklist/tasklist | 🔵 **簽核事件 inbox**（native activity 為底，含流程圖定位） |
| 核准/駁回 | ✅ + 自定駁回步驟 | ✅ | ✅ | 🔵 核准/駁回**到指定關卡**/批次 |
| 加簽（向上） | ✅ 變動簽核權 | ✅ 前/後加簽 | ✅ ad-hoc | 🔵 **向上加簽**（runtime，圖上標示、限深度） |
| 會辦/徵詢（橫向） | ✅ 徵詢意見(等待/不等待) | ✅ 會簽/會辦 | 🟡 | 🔵 **橫向送簽**：會辦(需回覆才續) / 徵詢(不等待) |
| 代理/代簽 | ✅ 代簽核/代核 | ✅ 代理 | ✅ | 🔵 委派代簽（含職務代理自動） |
| 抽單/收回 | 🟡 | ✅ retrieve | 🟡 | 🔵 **收回/抽單**（申請人或前關卡） |
| 行動簽核 | ✅✅ NT OneAPP | ✅ | ✅ | ✅ **原生 Odoo 行動 App**（免自建，native activity） |
| 與 ERP/單據整合 | connector | connector | connector | 🔵 **原生 chatter / 單據即時連結** |

> **超越主張**：把國內「待辦匣 + 加簽 + 會辦/徵詢 + 代理 + 抽單」整套，做成**Odoo 原生 activity 為底、零外掛依賴、且與流程圖即時連動**的簽核事件中心；橫向送簽明確區分「會辦(等待)」與「徵詢(不等待)」並整合進 BPMN token 推進語意。

---

## 2. 架構

```
┌── 簽核流程（選單）────────────────────────────────────────────┐
│  ・流程設定（可執行流程 + 全版編輯器）                          │
│  ・★ 簽核事件（新畫面，本規格）                                 │
│  ・流程實例 / 角色 / 閘門 / 代理 / 設定                          │
└──────────────────────────────────────────────────────────────┘
        簽核事件 inbox（client action 或 list/kanban）
        ────────────────────────────────────────────
   待我簽 │ 我送出 │ 會辦中 │ 已完成        ← 分頁/篩選
   ┌──────────────┬──────────────────────────────────┐
   │ 事件清單      │ 事件詳情                          │
   │ ・單據摘要    │ ・單據連結(原生 chatter)          │
   │ ・流程/關卡   │ ・流程圖縮圖 + 目前關卡高亮        │
   │ ・期限/狀態   │ ・動作列：核准/駁回/向上/橫向/委派 │
   └──────────────┴──────────────────────────────────┘
        │ 動作                         │ 載體
        ▼                              ▼
 bpmn.activity.link（簽核語意）   mail.activity（原生事件，最小載體）
        │ 完成 → 推進                  │ 用 activity_schedule 建立
        ▼
 bpmn.process.instance + token 引擎
```

- **事件 = 一筆原生 `mail.activity`**（user_id=簽核人、res_model/res_id=被簽單據、activity_type=「BPMN 簽核」、date_deadline=SLA）。
- **`bpmn.activity.link`** 連結 activity ↔ token ↔ instance，承載 decision/kind/軌跡（**簽核語意全在這**）。
- **簽核事件畫面**操作 link（核准/駁回/向上/橫向/委派），完成時呼叫原生 `activity._action_done()` 並推進 token。

---

## 3. 解耦規格（移除 dobtor_mail_activity）

| 項目 | 動作 |
|------|------|
| `__manifest__.py` depends | 移除 `dobtor_mail_activity` → `['dobtor_bpmn','mail','hr']` |
| `mail.activity` override | `_action_done(feedback, attachment_ids)` 改 override **原生** mail.activity（原生回傳 `(messages, next_activities)`，行為相容）；移除對 dobtor_mail_activity 行為的假設 |
| escalate wizard 視圖 | **不再繼承** `dobtor_mail_activity.mail_activity_view_form_schedule`；改為**自建簽核事件畫面內的動作**（不 inherit 任何他模組 view） |
| activity 建立 | 用原生 `record.activity_schedule(act_type_xmlid, user_id=, summary=, date_deadline=)` 或 `mail.activity.create()` |
| 既有 compute 欄位 | `is_bpmn_approval`/`bpmn_allow_escalation` 等保留在 `mail.activity`（自有 inherit，不依賴對方欄位） |
| 資料/權限 | activity_type、access、群組皆自有，無對方 XMLID 參照 |

> 驗證點：全模組 grep 無 `dobtor_mail_activity` 字串；安裝不需對方在場。

---

## 4. 簽核事件畫面（Approval Event Inbox）

### 4.1 進入點
「簽核流程 → **簽核事件**」（新選單項）。預設開啟「**待我簽**」。

### 4.2 版面（建議 client action 全版，或 list+form 簡版起步）
- **左：事件清單**（可切分頁/篩選）
  - 分頁：`待我簽` / `我送出的` / `會辦中` / `已完成`
  - 每列：單據摘要、流程名·目前關卡、申請人、期限(逾期紅標)、狀態徽章
  - 支援**批次勾選** → 批次核准/駁回
- **右：事件詳情**
  - 單據連結（點擊開原單，原生 chatter）
  - **流程圖縮圖 + 目前關卡高亮**（重用核心 svg / bpmn-js viewer）
  - **誰會簽追蹤**：本案整鏈各關卡與簽核人/狀態
  - **動作列**（見 §5、§6）
  - 意見輸入框（寫入 activity feedback + chatter）

### 4.3 「待我簽」資料來源
`bpmn.activity.link` where `approver_user_id = 當前user` and `decision = 'pending'`（join 原生 activity 取單據/期限）。

---

## 5. 簽核動作（核准 / 駁回 / 批次）

| 動作 | 行為 |
|------|------|
| **核准** | link.decision='approved'；原生 `activity._action_done(feedback)`；推進 token（依 approval_mode：任一/會簽/依序/比例） |
| **駁回** | link.decision='rejected'；token 走駁回路徑；**可選「駁回到指定關卡」**（對標 FlowMaster 自定駁回步驟）→ token 跳回該節點重簽 |
| **批次** | 對勾選的多筆 link 一次核准/駁回（對標成批簽核） |
| **加註意見** | 不結案，僅留 chatter（對標徵詢但不送出） |

---

## 6. 例外路由（向上加簽 / 橫向送簽 / 委派 / 收回）★核心

`bpmn.activity.link` 擴充 `kind`（normal/escalate/lateral/delegate）與 `parent_link_id`（串鏈）、`return_after`（完成後是否回到原簽核人）。

### 6.1 向上加簽（escalate，垂直）
- 當前簽核人「**上呈加簽**」→ 指定上級（直屬主管/指定人/角色）。
- 模式：
  - **加簽後退回我續簽**（`return_after=True`）：插入子事件給上級 → 上級核准 → 回到我 → 我才核准推進。
  - **直接上呈**（`return_after=False`）：我這關關閉，token 流向上級續走。
- 圖上以 `escalate` 徽章標示；限最大深度防無限上呈。

### 6.2 橫向送簽（lateral，水平）★對標 FlowMaster 徵詢/會辦
- 當前簽核人「**橫向送簽**」給平行同事/他部門，分兩種：
  - **會辦（等待）**：需對方回覆意見後，**本關才可繼續**（token 暫停等會辦回覆）。
  - **徵詢（不等待）**：送出參考意見，**本關可同時繼續**（不阻塞 token）。
- 可一次送多人；回覆彙整顯示於事件詳情。
- 與「會簽(all)」不同：會辦/徵詢是**個案臨時**插入，不改流程定義。

### 6.3 委派代簽（delegate）
- 把本事件交給代理人簽（`kind='delegate'`、`decided_by=代理人`）。
- 與 `bpmn.delegation` 職務代理整合：代理期間自動委派；亦可臨時手動委派。

### 6.4 收回 / 抽單（retrieve）★對標 Agentflow retrieve
- **申請人**或**前一關簽核人**可「收回」尚未被下一關處理的事件 → token 退回、關閉待簽事件。
- 留軌跡，避免濫用（僅 pending 且下一關未動作時可收回）。

---

## 7. 資料模型擴充

```python
# bpmn.activity.link（既有）擴充
kind = fields.Selection([('normal','一般'),('escalate','向上加簽'),
                         ('lateral_consult','會辦(等待)'),('lateral_info','徵詢(不等待)'),
                         ('delegate','委派代簽')], default='normal')
parent_link_id = fields.Many2one('bpmn.activity.link')   # 加簽/送簽鏈
return_after = fields.Boolean()                          # escalate 後是否回原簽核人
reject_to_element = fields.Char()                        # 駁回到指定關卡 element id
consult_reply = fields.Text()                            # 會辦/徵詢回覆
# activity_id 仍指向「原生」 mail.activity
```

新精靈（自有，不 inherit 他模組）：
- `bpmn.escalate.wizard`（向上）：target 型別 + return_after + 理由
- `bpmn.lateral.wizard`（橫向）：對象多選 + 模式(會辦/徵詢) + 理由
- `bpmn.reject.wizard`（駁回）：去向(申請人/上一關/指定關卡) + 理由

---

## 8. 與流程圖整合（超越國內「看不到位置」）

- 事件詳情顯示**流程圖**並**高亮目前關卡**（重用 core svg 縮圖或 bpmn-js viewer + canvas marker）。
- **整鏈追蹤**：每關卡顯示「角色 → 實際簽核人 → 狀態(待/准/駁/會辦中)」。
- 國內待辦匣多為純清單；我們讓簽核人**看得到自己在流程的哪裡、後面還有誰**。

---

## 9. 原生 mail.activity 整合細節

- **建立**：token 進 user_task → `self.env['mail.activity'].create({...})` 或單據 `activity_schedule`，res_model/res_id 指向**被簽單據**（chatter 自然顯示）。
- **完成**：override 原生 `mail.activity._action_done(self, feedback=False, attachment_ids=None)` → `super()` 後查 link 推進；**駁回/向上/橫向**走自有按鈕（不靠原生完成）。
- **提醒/行動**：沿用 Odoo 原生 activity 的到期提醒、系統匣、行動 App——**免自建**。
- **activity_type**：自有 `dobtor_approval.activity_type_approval`（icon、預設期限）。

---

## 10. 超越國內外總結

1. **零外掛依賴**：原生 mail.activity 即可，獨立可裝（解耦後更穩、曾因繼承他模組 view 安裝失敗的問題消失）。
2. **簽核事件中心 + 流程圖定位**：看得到「我在流程哪裡、後面還有誰」。
3. **向上 / 橫向 / 委派 / 收回 一站式**，且每動作留軌跡、圖上標示。
4. **橫向送簽分會辦(等待)/徵詢(不等待)**並整合 token 推進（比國內更精確的語意）。
5. **駁回到指定關卡 + 批次簽核**（對標並整合）。
6. **原生 chatter / 提醒 / 行動 App**，免自建第二套通知體系。

---

## 11. Roadmap（建議交付順序）

| 波 | 內容 |
|----|------|
| **E0 解耦** | 移除 dobtor_mail_activity 相依；override 改原生 mail.activity；移除繼承其 view；改自建動作；全 grep 清乾淨 |
| **E1 事件 inbox** | 「簽核事件」選單 + 清單(待我簽/我送出/會辦中/已完成) + 詳情 + 核准/駁回/批次 |
| **E2 流程圖定位** | 詳情顯示流程圖縮圖 + 目前關卡高亮 + 整鏈追蹤 |
| **E3 向上加簽** | escalate wizard（自有）+ return_after + 深度限制 + 圖上標示 |
| **E4 橫向送簽** | lateral wizard：會辦(等待，阻塞 token)/徵詢(不等待) + 回覆彙整 |
| **E5 委派/收回** | delegate（含職務代理自動）+ retrieve 收回/抽單 |
| **E6 駁回強化** | 駁回到指定關卡 + 理由軌跡 |
```
