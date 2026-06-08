# DESIGN_INLINE_APPROVAL — 單據內簽核 UX 完整規格

> 目標：被 Action 閘門攔截的原生 Odoo 單據畫面上，將「執行鈕 → 送簽鈕」、顯示「送簽中」、
> 讓可核准角色看到「批准/駁回」、讓相關人員看到**送簽狀態（到哪一關、給誰、何時送出、
> 何時批准、共幾關）**，並提供台灣習慣的**例外處理**（上簽/轉簽/加簽/會辦/退回/抽回）。
>
> 設計原則：**不改每個 model**（純前端 patch + 通用後端 API + 重用既有引擎動作），
> 對任何被閘門攔截的單據自動生效。

---

## 0. 與既有引擎的對映（不重造輪子）

| UX 元素（台灣習慣） | 引擎動作（已存在） | 模型/方法 |
|---|---|---|
| 送出簽核 | 起閘門實例 | `/dobtor_approval/start_gate` + `bpmn.action.gate` |
| 批准 | 核准 link | `bpmn.activity.link.action_bpmn_approve()` |
| 駁回 / 退回（可指定關卡） | 駁回 | `action_bpmn_reject()`（`reject_to_element`） |
| 上簽 / 上呈 | runtime 加簽（往上一級） | `action_event_escalate()` → escalate wizard |
| 加簽（簽完退回我續簽） | escalate `return_after=True` | escalate wizard（`return_after_escalate`） |
| 轉簽 / 改派 | 委派 | `action_event_delegate()` → delegate wizard |
| 會辦 / 協辦 / 徵詢 | 橫向送簽（等待/不等待） | `action_event_lateral()` → lateral wizard（`kind=lateral_consult`） |
| 抽回 / 收回 | 申請人取回 | `action_event_retrieve()` |
| 代簽核 | 職務代理 | `bpmn.delegation`（resolver 階段自動替換） |

> 既有 link 欄位可直接餵 UX：`phase`、`kind`、`decision`、`decided_by`、`reject_to_element`、
> `consult_reply`、`has_open_consult`、`date_deadline`、`approver_user_id`、`bpmn_element_id`。
> **新增需求欄位**：`bpmn.activity.link.decided_date`（Datetime，記實際決行時間，供「何時批准」）。

---

## 1. 角色 × 實例狀態 → 可見元件矩陣（核心）

觀看者相對於該單據簽核實例的身分（同一人可同時具多重身分）：
- **A 申請/操作者**（能點原生執行鈕者 / 實例 `applicant_user_id`）
- **B 當前簽核人**（有 `decision=pending` 且 `approver_user_id == uid` 的 link）
- **M 簽核人之主管 / 被授權角色**（節點 `allow_escalation`、被委派、security group）
- **O 旁觀者**（有單據讀權限，非上述）

| 狀態 \ 角色 | A 申請者 | B 當前簽核人 | M 主管/授權 | O 旁觀者 |
|---|---|---|---|---|
| **未送簽（gated）** | 原執行鈕**隱藏** → **「送出簽核」** | — | — | 原鈕隱藏（無權執行） |
| **送簽中（running）** | 狀態面板＋**抽回** | **批准／駁回**＋例外鈕 | 例外鈕（轉簽/代決） | 狀態面板（唯讀） |
| **已核准（approved）** | 原鈕恢復/已自動回放＋「已核准」徽章 | 「已核准」徽章 | 同 | 「已核准」徽章 |
| **已駁回（rejected）** | 「已駁回＋理由」＋**重送** | 徽章 | 同 | 徽章 |

> 「原執行鈕隱藏」＝把 `gated_methods` 內、且尚未核准的 object 按鈕在前端隱藏，避免使用者
> 誤點繞過簽核（後端 guard 仍是安全底線）。核准後該方法不再 gated → 按鈕自動恢復。

---

## 2. 按鈕狀態機（依角色）

```
            ┌─────────── 未送簽(gated) ───────────┐
            │ A：[送出簽核:<原按鈕名>]            │
            └───────────────┬─────────────────────┘
                            │ start_gate
            ┌───────────────▼──────── 送簽中 ─────────────────┐
            │ A：[抽回]      （原鈕隱藏，顯示「送簽中…」）    │
            │ B：[批准] [駁回] [上簽] [加簽] [轉簽] [會辦]     │
            │ M：[轉簽] [代為批准/駁回]（依授權）              │
            │ 全體：狀態面板（到哪關/給誰/進度/時間軸）        │
            └───────┬───────────────┬─────────────┬──────────┘
          approve 全關過      reject            retrieve
            ┌───────▼───────┐ ┌────▼─────┐  ┌────▼────────┐
            │ 已核准         │ │ 已駁回    │  │ 回未送簽    │
            │ (自動回放原動作)│ │ A:[重送]  │  │ A:[送出簽核] │
            └────────────────┘ └──────────┘  └─────────────┘
```

- **批准**：`action_bpmn_approve`；若節點為會簽/依序/DMN 分階鏈 → 引擎自動判斷是否進下一關。
- **駁回**：開 reject wizard（可填理由、選退回去向關卡 `reject_to_element`）。
- **上簽/加簽**：開 escalate wizard（`return_after` 切換「直接上呈」或「加簽後退回我續簽」）。
- **轉簽**：開 delegate wizard（改派他人）。
- **會辦**：開 lateral wizard（等待/不等待；`kind=lateral_consult`）。
- **抽回**：`action_event_retrieve`（僅 A、且尚無人核准時可抽）。

---

## 3. 狀態資訊面板（讓相關人員「知道現況」）

### 3.1 摘要列（單據頂部 banner / 控制列）
`簽核中 · 第 2/4 關 · 待簽：王經理 · 送出 06/08 14:20`
- **到哪一關**：當前 active token 的節點名 + `第 n/N 關`。
- **給誰**：當前 `decision=pending` link 的 `approver_user_id`（多人＝會簽列出全部）。
- **何時送出**：`instance.create_date`。
- **共幾關 / 已過幾關**：見 §3.3 關卡推導。

### 3.2 時間軸 / 進度 stepper（展開）
```
●——●——◉——○——○
申請 關1 關2 關3 完成
✔   ✔  ⏳  ·   ·
王  李  (王經理待簽)
06/08 06/08 —
14:20 15:01
```
每關顯示：關名、簽核人、決行時間（`decided_date`）、狀態（✔過/⏳待/·未到/✖駁回）。
資料來源：依 `bpmn.activity.link` 依 `phase`/`sequence` 分組 + token 走訪序。

### 3.3 「共幾關」推導（依節點型別）
- **線性 user_task 串**：以流程圖 user_task 數為總關數。
- **DMN/核決權限表分階鏈**：以命中鏈的 `phase` 數為關數（如採購 60 萬＝3 關）。
- **會簽節點**：同一關內多簽核人並列（不算多關）。
- **加簽/會辦**：以子 link（`parent_link_id`/`kind`）為「插入的臨時關」標示於時間軸（非正式關數）。
- 動態鏈（DMN 依金額而定）→ 送簽後才能定關數；面板以「已知命中鏈」顯示。

---

## 4. 後端 API（通用，單一端點供前端取狀態）

```python
# bpmn.process.instance（@api.model）
def get_record_approval_state(self, res_model, res_id):
    """回傳該單據的簽核 UX 狀態（無實例則回 gated 資訊供顯示送簽鈕）。"""
    return {
        'gated_methods': [{'method': 'action_confirm', 'label': '確認'}],  # 來自 action.gate 比對(條件已評估)
        'instance': {                                  # 無進行中實例則為 None
            'id': int, 'state': 'running|approved|rejected',
            'process_name': str,
            'applicant': {'id': int, 'name': str},
            'submitted_at': iso,
            'total_steps': int, 'done_steps': int,
            'current': {'node_name': str, 'phase': int,
                        'approvers': [{'id','name'}]},
            'steps': [{'name','phase','status':'done|current|pending|rejected',
                       'approver': {'id','name'}, 'decided_at': iso|None,
                       'kind': 'normal|escalate|lateral_consult'}],
        },
        'my': {                                        # 觀看者可用動作（已守門）
            'role': 'applicant|approver|manager|observer',
            'link_id': int|None,                       # 我的待簽 link（B 角色）
            'can': {'submit','retrieve','approve','reject',
                    'escalate','add_sign','delegate','lateral'},
        },
    }
```

動作端點（薄包裝，多數直接呼叫既有 link/gate 方法，回傳更新後 state 或 wizard act_window）：
- `submit_gate(model, res_id, method)` → start_gate
- `approve_link(link_id, feedback)` / `reject_link(link_id)`（後者回 reject wizard act_window）
- `escalate_link / delegate_link / lateral_link (link_id)` → 各 wizard act_window
- `retrieve_instance(instance_id)`

> 守門：`can.*` 由後端依 link 歸屬、節點 `allow_escalation`、能力開關（`delegation`/`escalation`）、
> security group（`group_bpmn_implementer`/主管）計算，**前端只顯示後端說可以的鈕**（前端不自行判權）。

---

## 5. 前端架構

### 5.1 隱藏被攔原鈕
- 沿用 `form_gate_patch.js` 思路，擴充為：表單載入時呼叫 `get_record_approval_state` →
  取得 `gated_methods`（未核准者）→ patch **ViewButton**（或 statusbar 按鈕渲染）：
  若按鈕 `clickParams.name ∈ gated_methods` 且未核准 → `invisible`。
- 保留現有 `beforeExecuteActionButton` 後備攔截（雙保險）。

### 5.2 注入「簽核 Bar」元件（通用 OWL）
- 一個 OWL 元件 `ApprovalBar`，注入於**表單控制列**（近原生按鈕）或**sheet 頂部 banner**：
  - 左：狀態摘要（§3.1）+ 展開時間軸（§3.2）。
  - 右：角色對應動作鈕（§1 矩陣），點擊→呼叫 §4 動作端點；wizard 類用 `action.doAction`。
- 以 FormController patch 在 `onRecordLoad`/`record` 變更時 RPC 狀態，存於元件 state；
  動作完成後 reload 狀態 + 必要時 `model.load()` 重繪單據（按鈕恢復）。
- **跨 re-render 穩定**：用元件 + state 驅動，不直接操作 DOM；按鈕隱藏走 ViewButton patch（隨重繪自然套用）。

### 5.3 進入點與適用範圍
- 僅對「有 action.gate 設定、且當前使用者對單據有讀權」的表單顯示 ApprovalBar（無 gate → 完全不出現，零干擾）。
- 能力開關：整體受 `action_gate` 能力；例外鈕各受 `escalation`/`delegation` 能力 + 節點設定。

---

## 6. 周知 / 通知機制（多管道，避免漏簽）

1. **單據內 ApprovalBar**（本規格主體）——看單據即見現況。
2. **簽核事件 inbox**（既有 E0–E6）：待我簽/我送出/會辦中/已完成分頁。
3. **mail.activity**（既有）：當前簽核人收到待辦活動（含期限）。
4. **chatter 留痕**（既有）：送出/每關批准/駁回/加簽/會辦 message_post 於單據 chatter，**自動形成稽核時間軸**。
5. **（可選）即時通知**：送出、輪到你簽、最終核准/駁回 → bus/discuss 推播或 email。

---

## 7. 邊界情境

| 情境 | 處理 |
|---|---|
| 一張單多個被攔動作（確認＋過帳） | 每方法各一顆「送出簽核:<動作>」；各自獨立實例 |
| 閘門帶條件（金額>X 才攔） | `get_record_approval_state` 已逐筆評估條件 → 不符即不顯示送簽鈕 |
| 駁回後重送 | 實例 rejected → A 見「重送」→ 起新實例（或回原動作） |
| 會簽（同關多人） | stepper 該關並列多簽核人；全簽完才進下一關 |
| 並行/包容閘道 | 摘要顯示「多分支進行中」；stepper 分支並列 |
| DMN/核決權限表分階鏈 | 關數＝命中鏈 phase 數；逐關 phase 推進反映於 stepper |
| 加簽/會辦子鏈 | 以「插入關」樣式顯示於時間軸（標 `kind`），不影響正式關數 |
| 抽回時機 | 僅「尚無任何 link 被核准」時允許；已有人核准則只能走駁回/退回 |
| 代簽核 | resolver 階段已替換 approver；ApprovalBar 顯示實際代理人 |

---

## 8. 落地檔案清單

```
models/
  bpmn_activity_link.py     # +decided_date(Datetime)；動作回傳 act_window 既有
  bpmn_process_instance.py  # +get_record_approval_state() + 動作薄包裝
  bpmn_action_gate.py       # 既有 _match（條件評估）重用
controllers/
  main.py                   # +狀態/動作 JSON 端點（或全走 orm.call）
static/src/gate/
  form_gate_patch.js        # 擴充：載入查狀態 + ViewButton 隱藏 gated 鈕
  approval_bar.js / .xml / .scss   # 新增：通用簽核 Bar 元件
views/
  bpmn_activity_link_views.xml     # （既有事件 inbox 不變）
```

---

## 9. 已拍板決策（2026-06-08）

1. **原鈕＝隱藏**（非變灰）：被攔且未核准的 object 按鈕完全隱藏，避免誤點繞過。
2. **送簽鈕＝每被攔方法一顆**：`送出簽核：<原按鈕名>`，各自獨立實例。
3. **ApprovalBar 位置＝控制列 + 可展開時間軸**（近原生按鈕）。
4. **例外鈕授權＝以人資架構設定開放**（見 §11）：「主管/可代操作者」由 HR 組織（`employee.parent_id` 直屬鏈 / `department_id.manager_id`）＋每個例外動作的**開放層級設定**決定，非寫死 security group。
5. **即時通知**：已整合 `mail.activity`（待辦/systray，近即時）＋ chatter（留痕/信）；**可選**加 `bus.bus` 即時彈窗於「送出/輪到你/核准或駁回」三時點（首版可後補）。
6. **decided_date**：`bpmn.activity.link` **新增 `decided_date`(Datetime)**，精準記「何時批准」。
7. **核准後執行＝預設自動連動（A）+ 每閘門可切交回送簽人（B）+ A 三道防護**（見 §10）。

---

## 10. 核准後原動作的執行（回放）設計

### 10.1 兩種模式（`bpmn.action.gate.execution_mode`）
- **A `auto_replay`（預設）**：實例核准 → 引擎以 `bpmn_approved=True` 自動回放原 `(model, method, res_ids)`。無縫、不會「核准了卻沒人執行」。
- **B `manual_by_submitter`**：核准 → 通知申請人「已核准，請執行」→ **原鈕恢復**（guard 偵測到「已核准實例」即放行）→ 申請人點一下執行。適合**高風險/不可逆動作**（過帳、付款、開發票）：核准＝授權，執行由經辦當下確認。

### 10.2 模式 A 必備三道防護（缺一不可）
1. **以申請人身分回放**：`_replay_pending_action` 改以 `applicant_user_id` 身分（`with_user`/受控 sudo）執行，**不以「觸發最後核准的人」執行**——權限與語意才正確（現況以觸發者執行＝潛在越權/語意風險，須修）。
2. **變動防護（核准的是「當時」那張單）**：送簽時於 `bpmn.process.instance` 快照閘門條件相關欄位值（或關鍵欄位 hash，存 `gate_snapshot` JSON）；回放前重新評估閘門條件 + 比對快照——若單據已實質變動（如金額由 10 萬被改為 20 萬、超出已核准範圍）→ **不自動執行**，標記 incident、通知申請人「單據已變動，請重新送簽」。**杜絕「批准 A、執行 B」。**
3. **回放失敗處理**：執行期錯誤（庫存不足、期間已關…）→ incident + 通知申請人，不靜默吞掉。

### 10.3 模式對 ApprovalBar 的呈現
- **A**：核准 → 「已核准，已自動執行」；變動防護擋下 → 「已核准但單據已變動，請重新送簽」。
- **B**：核准 → 「已核准，請執行」+ 原鈕**醒目恢復**；執行後 → 「已完成」。

### 10.4 為何不採「純 B」
- 一律手動會產生「已核准但沒人回來按」的懸置單，且多一步易遺漏。故 **A 為預設、B 為高風險動作的選項**。

---

## 11. 例外處理按鈕的授權（以人資架構設定）

> 決策 #4：不寫死 security group，改由 **HR 組織關係 + 動作開放層級** 決定誰能用哪個例外鈕。

### 11.1 可操作者判定（後端 `can.*` 計算）
- **當前簽核人本人**（B）：恆可 批准/駁回；例外鈕（上簽/加簽/轉簽/會辦）受節點設定（`allow_escalation`）＋能力開關（`escalation`/`delegation`）。
- **簽核人之主管鏈**（M）：以 `decided 對象.employee_id.parent_id` 往上 N 級 / `department_id.manager_id`，可被授權「代為操作」特定例外鈕（如代為轉簽、代為批准——「主管代決」台灣常見）。
- **申請人**（A）：抽回（限尚無人核准）、重送。

### 11.2 開放層級設定（新增設定，掛 `bpmn.node.config` 或全域）
```
exception_policy（每節點或流程層級）：
  escalate_allowed_by : 'approver' | 'approver+manager'   # 上簽/加簽誰能發動
  delegate_allowed_by : 'approver' | 'approver+manager'   # 轉簽
  manager_act_levels  : Integer (0=不開放主管代決, 1=直屬, 2=上兩級…)  # 主管代批准/駁回的層級
  lateral_allowed     : Boolean                            # 會辦是否開放
```
- 「主管」一律由 **HR `employee.parent_id` 直屬鏈** 推導（與 resolver 同一套組織關係，語意一致）。
- 後端依當前使用者是否落在「簽核人的主管鏈 ≤ `manager_act_levels`」決定 `can.*`，前端只渲染後端許可的鈕。

---

## 12. 落地檔案清單（更新）

```
models/
  bpmn_activity_link.py     # +decided_date(Datetime)（決行寫入）
  bpmn_process_instance.py  # +get_record_approval_state() + 動作薄包裝
                            #  + _replay_pending_action 改「以申請人身分 + 變動防護」
  bpmn_action_gate.py       # +execution_mode(auto_replay/manual_by_submitter)
  bpmn_node_config.py       # +exception_policy 欄位（escalate/delegate/manager_act_levels/lateral）
  bpmn_process_instance.py  # +gate_snapshot(JSON) 快照（送簽時寫、回放前比對）
controllers/main.py         # +狀態/動作 JSON 端點（或全走 orm.call）
static/src/gate/
  form_gate_patch.js        # 擴充：載入查狀態 + ViewButton 隱藏 gated 鈕
  approval_bar.{js,xml,scss}# 新增：通用簽核 Bar（摘要列＋可展開時間軸＋角色動作鈕）
（可選）bus 即時通知：instance 送出/輪到你/結案時 _bus_notify
```

---

> 本規格全部重用既有引擎動作（approve/reject/escalate/lateral/delegate/retrieve），
> 主要新增＝① 通用狀態 API ② ApprovalBar 前端元件 ③ ViewButton 隱藏 ④ `decided_date`
> ⑤ `execution_mode` + 回放三防護 ⑥ HR 架構例外授權 `exception_policy`。
