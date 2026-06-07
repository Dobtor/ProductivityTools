# dobtor_approval — 全版簽核設定編輯器 改版規格建議

> 文件版本：v1.0 ｜ 撰寫日：2026-06-07 ｜ 目標 Odoo：18.0
> 定位：在 `dobtor_approval` 內提供「**簽核設定編輯器**」（process_editor，client action）——
> 直接編輯 `bpmn.executable.process` **自持的 BPMN XML**，並在每個物件上以**右側設定 Panel** 配置「動作插入點、部門/角色、簽核控制項」。
> 註（2026-06-07 依賴反轉）：BPMN 編輯器核心（bpmn-js / node registry / lib_loader）已內建於本模組；`dobtor_bpmn` 的純畫圖編輯器與本編輯器**共用此核心**。
> 對標國內外（華苓 Agentflow、新人類 FlowMaster、叡揚 Vitals ESP｜Camunda、Pega、Appian），目標：**更優**。

---

## 0. 與 dobtor_bpmn 編輯器的分工（為何要第二個編輯器）

| | `dobtor_bpmn` 編輯器 | `dobtor_approval` 簽核設定編輯器（本規格） |
|---|---|---|
| 目的 | 純畫 BPMN/DMN（demo.bpmn.io 等價） | **在圖上疊簽核執行設定** |
| 編輯對象 | 圖形結構（節點/連線/版面） | 每個物件的**簽核控制項**（角色/閘門/SLA/加簽…） |
| 右側 Panel | bpmn.io 標準屬性 | **Odoo 簽核設定 Panel**（部門/角色/動作插入點/條件） |
| 資料 | `bpmn.diagram.xml`（純設計） | `bpmn.executable.process.xml`（自持）+ `bpmn.node.config`（overlay，keyed by element id） |
| 改圖 | 可改結構 | **可改結構**（forked，自持 XML）＋加「簽核專屬節點」 |

> **核心理念（超越國內單檔式設計）**：國內 FlowMaster/Agentflow 是「畫圖 + 設屬性」綁死在同一份檔且無圖庫概念。我們以 `bpmn.node.config` overlay（keyed by element id）把「角色/閘門/SLA 執行規格」與「圖形結構」分層存放，發佈/版本/治理清晰；流程亦可由 `dobtor_bpmn` 設計圖庫 **forked 複製 XML** 帶入（一次性複製，之後獨立演進）。

---

## 1. 國內外對標：我們要超越的點

| 能力 | 新人類 FlowMaster | 華苓 Agentflow | Camunda/Pega | **dobtor_approval（目標）** |
|---|---|---|---|---|
| 視覺流程 + 屬性設定 | ✅ Designer + 屬性視窗（下拉） | ✅ | ✅ properties-panel | ✅ bpmn-js + **Odoo 原生右側 Panel** |
| 簽核人解析 | 核決權限表（人員/部門/自定層級，**靜態**） | OAB 組織職權 | 表達式/群組 | 🔵 **resolver 矩陣**（直屬/第N級/部門經理/職位/單據欄位/運算式）+ **即時預覽** |
| 動作介入（綁既有系統按鈕） | ⚠ 表單導向，難綁既有 ERP 動作 | ⚠ | ✅(Case) 需建模 | 🔵 **動作插入點**：直接綁 Odoo `model+method+按鈕`，攔截→簽核→回放 |
| 「誰會簽」事前預覽 | ⚠ 多需實際送單 | 🟡 | 🟡 | 🔵 **右側即時 dry-run**：選申請人秒算整鏈簽核人 |
| 條件/分級加簽 | AutoScript（寫碼） | 條件 | DMN/規則 | 🔵 **視覺條件 builder + DMN-lite 決策表**（免寫碼） |
| 個案加簽/上呈 | 變動簽核權 | 加簽/代理 | ad-hoc | 🔵 **runtime 加簽**，圖上標示、限深度、留軌跡 |
| 上手曲線 | 完整但偏 IT | 偏 IT | 陡 | 🔵 **由簡入深開關**：右側 Panel 依啟用能力動態長出 |
| 與 ERP 一致性 | connector | connector | connector | 🔵 **原生零距離**（同一 ORM、無雙寫） |

> **超越主張**：把 FlowMaster 的「核決權限表」升級為**動態 resolver + 即時預覽**；把「AutoScript 寫碼條件」換成**視覺條件/決策表**；把它做不到的「**綁既有 Odoo 業務按鈕的動作插入點**」變成內建一級功能。

---

## 2. 整體架構

```
┌─ dobtor_approval 簽核設定編輯器（client action, 全版）──────────────┐
│  Toolbar：返回 / 流程名 / 模式(設定·預覽) / 驗證狀態 / 發佈 / 儲存       │
├───────────────────────────────┬───────────────────────────────────┤
│  Canvas（bpmn-js）             │  右側 Odoo 簽核設定 Panel（動態）       │
│  ・載入本流程自持 XML(forked)   │  ・依選取物件型別切換內容              │
│  ・節點上疊「設定狀態」徽章      │  ・部門/角色解析、動作插入點、SLA、加簽  │
│  ・點節點→右側帶出該節點設定     │  ・「誰會簽」即時預覽                  │
│  ・增刪節點(原生palette,已存回)  │  ・條件 builder / DMN-lite            │
├───────────────────────────────┴───────────────────────────────────┤
│  底部：問題清單(lint) / dry-run 申請人選擇器 / 流程說明                  │
└────────────────────────────────────────────────────────────────────┘
        │ 讀/寫 XML                   │ 寫 overlay
        ▼                             ▼
 bpmn.executable.process.xml   bpmn.executable.process + bpmn.node.config
 （同一筆流程自持，forked）      （node.config keyed by element id）
```

- **Canvas**：用 bpmn-js Modeler 渲染本流程**自持的 BPMN XML（forked）**；可增刪節點/連線，「儲存」或「發佈」時以 `saveXML()` → `save_xml` 存回 `process.xml`（結構持久化）。標準 BPMN 元素由 bpmn-js 原生 palette 提供；**專屬「簽核任務/動作」palette 積木為 roadmap（見 DESIGN_MODULE_SPLIT §4.1，目前以原生 UserTask/ServiceTask + 右側面板設定取代）**。
- **節點徽章**：每個 user_task 顯示「✅ 已設定 / ⚠ 未設簽核人」小圖示；service_task 顯示「⚡ 動作插入點」；gateway 顯示「◆ 條件」。一眼看出哪裡還沒設定（國內少見）。
- **右側 Panel**：選取物件 → 帶出對應設定表單（Odoo OWL 表單元件，欄位接 RPC 動態選項）。

---

## 3. 右側設定 Panel 規格（依物件型別動態切換）

### 3.1 簽核節點（UserTask）
| 區塊 | 控制項 | 說明（超越點） |
|------|--------|---------------|
| **簽核對象** | resolver 型別下拉 | 直屬主管 / 往上第 N 級 / 部門經理 / 指定部門經理 / 指定職位 / 指定人員 / 權限群組 / **取單據欄位**(如 sale.order.user_id) / 運算式 |
| | 參數（依型別動態） | level、部門、職位、人員多選、欄位下拉（**即時列出該單據 model 的 user/employee 欄位**） |
| | **即時預覽** | 「以〔申請人下拉〕試算 → 此關會送給：張三、李四」**就地顯示**（dry-run） |
| **簽核方式** | 任一 / 全部會簽 / 依序 / **比例通過(N/M)** | 比例通過超越國內 any/all |
| **期限 SLA** | 期限(天/時) + 逾時動作 | 逾時提醒 / 自動加簽上級 / 逾時視為核准 / 退回（T5 Timer） |
| **加簽** | ☑ 允許主管自主上呈 + 最大深度 | runtime 個案彈性 |
| **駁回** | 駁回去向（回申請人 / 回上一關 / 指定節點） | |
| **通知** | 通知範本 / Email / 站內 | 用 mail.activity.type 客製 |
| **表單可編欄位** | 此關可編輯的單據欄位（白名單） | 控管各關卡可改什麼（對標 FlowMaster 欄位隱藏/唯讀） |

### 3.2 動作插入點（ServiceTask / 綁定既有 Odoo 動作）★核心創新
| 控制項 | 說明 |
|--------|------|
| **插入時機** | `before`（攔截：先簽核後執行）/ `after`（執行後觸發）/ `replace`（核准後才執行原動作） |
| **目標模型** | 下拉選 Odoo model（含本流程綁定的單據 model 預設） |
| **目標方法/按鈕** | **掃描該 model 的 form 按鈕（`type=object`）+ server actions + 常見白名單**，下拉勾選（如 `action_confirm` / `action_post` / `button_approve`） |
| **觸發條件** | 視覺條件（金額 > X、欄位 = Y）；複雜走 DMN |
| **回放標記** | 自動帶 `context.bpmn_approved` 放行（閉環） |
| **失敗處理** | incident + 重試（T5） |

> **這是國內 FlowMaster/Agentflow 結構上做不到的**：它們是表單中心，無法「攔截既有 ERP 模組的原生按鈕」。我們在簽核圖的物件上**直接指定 Odoo 動作插入點**，達成「任何 Odoo 操作都能掛簽核閘門」。

### 3.3 閘道（Gateway）
- **條件 builder**（視覺）：欄位 + 運算子 + 值，多條件 AND/OR；每條出線一組。
- **依 DMN 決策表**：下拉選 `bpmn.decision`（金額分級加簽等），免寫 AutoScript。
- 預設線標示。

### 3.4 流程全域設定（點畫布空白）
- **申請人來源**：觸發者 / 單據欄位（如 create_uid）。
- **綁定單據模型**：本流程作用的 model（驅動欄位/動作下拉的選項來源）。
- **版本/狀態**、**啟用能力上限（capability_level）**。
- **整體 dry-run**：選申請人 → 全圖每關預覽簽核人（鏈視圖）。

---

## 4. 「動作插入點」資料與互動設計

`bpmn.node.config` 擴充（overlay，keyed by `bpmn_element_id`）新增：
```python
gate_timing = fields.Selection([('before','攔截先簽'),('after','後置觸發'),('replace','核准後執行')])
gate_model_id = fields.Many2one('ir.model')
gate_method = fields.Char()          # 由掃描器選定
gate_condition = fields.Text()       # 視覺條件序列化
```
- 編輯器右側「動作插入點」面板的方法下拉，呼叫 controller `/dobtor_approval/scan_actions?model=` → 回傳 `[{name, label, source}]`（form 按鈕 / server action / 白名單）。
- 設定後，發佈時生成對應 `bpmn.action.gate` 並安裝 guard。

---

## 5. 部門/角色簽核控制項（OAB 超越版）

把 FlowMaster「核決權限表（靜態層級）」升級為**動態解析矩陣**：
- 來源維度：**HR 組織**（parent_id 主管鏈、department_id.manager_id、hr.job 職位）＋**單據關係**（業務員、建立人、自訂 M2O）＋**權限群組**＋**運算式**。
- **職務代理**內建：解析出的人在代理期間自動轉代理人（`bpmn.delegation`），右側 Panel 顯示「實際將由代理人 X 簽」。
- **即時預覽**消除國內「設了不知道誰簽」的痛點。
- **組織異動免改流程**：因為是動態解析（抓即時 HR 關係），人事異動不必重設流程——對標 OAB 但用 Odoo HR 原生達成。

---

## 6. 即時驗證 + dry-run 預覽（超越國內關鍵體驗）

- **即時驗證（bpmnlint + Odoo 規則）**：未設簽核人、gateway 無條件、動作插入點綁無效方法、加簽無上限 → 底部問題清單紅點，**未通過不可發佈**。
- **dry-run 沙箱**：右側/底部選一個「假申請人」→ **不實際送單**即算出：每關簽核人、會簽幾人、走哪條 gateway、最終回放哪個動作。
- 國內多需「實際開單測試」才知道結果；我們**設定當下即見**。

---

## 7. 編輯器版面與模式

- **模式切換**：`設定模式`（點物件設簽核）/ `預覽模式`（dry-run token 走訪動畫，仿 token-simulation）。
- **節點狀態徽章**：已設定/缺設定/有動作插入點/有條件，色彩標示。
- **右側 Panel** 可收合；**底部抽屜**放問題清單 + dry-run。
- **由簡入深**：Panel 區塊依 T0–T6 能力開關顯隱（如未開 T5，不顯示 SLA/比例通過）。

---

## 8. 技術實作要點

- **元件**：`dobtor_approval` client action `dobtor_approval.process_editor`（全版 OWL），canvas 用 bpmn-js（lib 沿用 dobtor_bpmn 的 loader），右側 Panel 為 OWL 子元件（非 bpmn.io properties-panel，改用 **Odoo 原生表單元件**以接 RPC 動態選項、many2one 下拉、可重用 Odoo widget）。
- **選取同步**：監聽 bpmn-js `selection.changed` → 載入該 element 的 `node.config` → 綁右側 Panel；Panel 變更 → ORM write overlay（即時或按儲存）。
- **動態選項 RPC**：`scan_actions`（model→可攔截方法）、`field_options`（model→user/employee 欄位）、`role_resolve_preview`（role+applicant→簽核人）。
- **加簽核專屬節點**（roadmap）：核心 `nodeTypeRegistry` 已註冊「簽核任務/動作插入點/條件閘道」定義，但動態 palette 消費端尚未落地；目前以原生 UserTask/ServiceTask + 右側面板設定達成同等功能。
- **儲存**：overlay 寫 `bpmn.node.config`；結構（forked）寫回 process.xml；發佈生成 role/gate 並校驗能力開關。

---

## 9. 與既有規劃的關係

- 取代 `DESIGN_SELF_SERVICE_DESIGNER.md` 中「屬性面板接 RPC」的構想，**具體化為 dobtor_approval 專屬全版編輯器**。
- 沿用 `DESIGN_MODULE_SPLIT.md`（v2.0）的 **node.config overlay**（執行規格與結構分層）與 `DESIGN_PROGRESSIVE_TIERS.md` 的**能力開關**（Panel 動態長出）。流程 XML 為**自持（forked）**，不再 linked 連動 `bpmn.diagram`。
- 與 `dobtor_bpmn` 編輯器**共用編輯器核心**：`dobtor_bpmn` 畫通用設計圖、本編輯器設簽核；設計圖可 forked 交付為簽核流程。

---

## 10. 超越國內外的差異化總結

1. **動作插入點**：在圖物件上直接綁「既有 Odoo 業務按鈕」攔截→簽核→回放（國內表單中心做不到）。
2. **動態 resolver + 即時「誰會簽」預覽**（升級 FlowMaster 靜態核決權限表）。
3. **視覺條件 / DMN-lite**取代 AutoScript 寫碼。
4. **設計/執行分離**（同圖多流程複用、改設定不動圖）。
5. **由簡入深**：右側 Panel 依能力開關動態長出，新手不被淹沒。
6. **原生零距離**：同一 ORM、無 connector、無雙寫。

---

## 11. Roadmap（建議交付順序）

| 波 | 內容 |
|----|------|
| A1 | 全版 client action 編輯器框架（canvas 載核心圖 + 右側 Panel 殼 + 選取同步） |
| A2 | UserTask 設定 Panel（resolver 全型別 + 簽核方式）+ 節點徽章 |
| A3 | 動作插入點 Panel + scan_actions + 發佈生成 gate（T2） |
| A4 | dry-run「誰會簽」即時預覽 + bpmnlint 驗證 |
| A5 | Gateway 條件 builder / DMN-lite（T5）+ SLA/加簽 Panel（T3/T5） |
| A6 | 預覽模式 token 動畫 + 由簡入深 Panel 開關連動 |
