# DESIGN_DMN — dmn-js 決策編輯器整合完整設計

> 目標：在 `dobtor_approval` 內加入完整的 **DMN 決策層**（dmn-js 編輯器 + FEEL 求值引擎 +
> 與簽核引擎整合），把現有「核決權限表」泛化為通用決策子系統。
>
> 既有決策（沿用 memory `dobtor_bpmn_approval_status`）：**不拆子模組**、lib 動態載入、
> 不做表單建構器。本設計一律落在 `dobtor_approval`（base），與現有 BPMN 編輯器同層共存。

---

## 0. 名詞與現況對接

| DMN 標準 | 本系統現況 | 整合後定位 |
|---|---|---|
| Decision Table | `bpmn.authority.matrix`（特化單表，僅輸出簽核人） | 升級為通用決策表的一個 *preset*（向後相容） |
| FEEL 運算式 | `expression`（safe_eval Python）、`field_on_record` | 由 FEEL 子集引擎取代，business-readable |
| DRD（決策需求圖） | 無 | 新增：多決策依賴編排 |
| Business Knowledge Model | 無 | 新增：可複用決策函式 |
| Business Rule Task | `bpmn:businessRuleTask` 節點型別已註冊、`dmn` feature 已存在但無編輯器 | 補上編輯器與求值，閉環 |

對接的現有程式錨點（務必相容）：
- `bpmn.role.resolver_type`：已有 `authority_matrix / expression / field_on_record`，**新增 `dmn_decision`**。
- `feature_registry.EXPERT_FEATURES`：已含 `'dmn'`（`FEATURE_DEPS['dmn']=['conditional']`）。
- `NODE_FEATURE['bpmn:businessRuleTask']='dmn'`。
- 分階簽核引擎：`_enter_matrix_node` / `_on_matrix_link_approved` / `bpmn.activity.link.phase` ——
  泛化為 `_enter_decision_node` 共用。
- 編輯器載入樣式：`static/src/modeler/lib_loader.js`（本地 lib + CDN fallback）、
  `js_class` list 按鈕、OWL 掛載——DMN 編輯器完全比照。

---

## 1. 設計原則

1. **流程層 / 決策層分離**：BPMN 管「做事的順序」，DMN 管「依資料下判斷」。流程圖不再塞一堆
   gateway 條件與 Python，判斷集中到可維護、可稽核的決策表。
2. **XML 為真相、relational 為投影**：dmn-js 編輯 DMN XML 存為真相；存檔時解析成關聯表
   （shadow models）供求值、查詢、覆蓋分析使用——與現有「BPMN XML + `bpmn.node.config`」一致。
3. **求值不用 eval**：自建 FEEL 子集 AST 直譯器，白名單函式，無任意 Python 執行。
4. **簽核人鏈是一種「輸出型別」**：DMN 輸出泛化為任意值；當輸出符合「approver 慣例結構」時，
   接回現有分階簽核鏈引擎。核決權限表＝此慣例的 preset。
5. **分級治理**：客戶 L1–L4 只「消費」決策結果；專家 / SI 才能「設計」決策（DRD/FEEL）。

---

## 2. 整體架構

```
┌──────────────────────────────────────────────────────────────┐
│ 前端 (OWL + bpmn.io)                                          │
│  process_editor (bpmn-js)        dmn_editor (dmn-js)          │
│   └ 節點:簽核對象=DMN決策 ──────►  ├ DRD 檢視 (決策依賴圖)     │
│   └ 節點:商業規則任務 ──────────►  ├ Decision Table 編輯器     │
│   └ gateway 條件=DMN決策 ───────►  └ Literal Expression 編輯器 │
└───────────────┬──────────────────────────────┬───────────────┘
                │ orm.call (save_dmn_xml)       │ get_dmn_data
┌───────────────▼──────────────────────────────▼───────────────┐
│ Odoo Models (dobtor_approval)                                 │
│  dmn.definitions (DMN XML 真相 + 版本/狀態)                   │
│   └─ parse on save ─► dmn.decision / .table / .input / .output│
│                       .rule / .rule.entry / dmn.input.data /  │
│                       dmn.bkm / dmn.requirement (shadow 投影)  │
│  binding: dmn.input.binding (DMN 變數 ⇄ Odoo 欄位)            │
└───────────────┬──────────────────────────────────────────────┘
                │ evaluate(decision, context)
┌───────────────▼──────────────────────────────────────────────┐
│ FEEL 求值引擎 (純 Python)                                     │
│  lexer → parser(AST) → interpreter(型別系統 + 白名單函式)     │
│  DRD 拓樸求值 + 結果快取                                       │
└───────────────┬──────────────────────────────────────────────┘
                │ outputs
┌───────────────▼──────────────────────────────────────────────┐
│ 簽核引擎整合 (既有)                                           │
│  role.resolver_type='dmn_decision' → approver 鏈 → 分階 link  │
│  gateway 條件 → boolean → token 路由                          │
│  businessRuleTask → 寫回 instance context / record            │
│  流程路由 → 決定套用哪個 executable.process 範本              │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 資料模型（Odoo 18）

### 3.1 決策定義與版本

```
dmn.definitions                 一份 DMN 檔（一張 DRD）
  name                Char      決策集名稱（如「採購核決決策」）
  dmn_xml             Text      dmn-js 來源 XML（真相）
  state               Selection draft / published / archived
  version             Integer   發佈遞增
  company_id          M2O       多公司
  decision_ids        O2M ─► dmn.decision   (解析投影)
  input_data_ids      O2M ─► dmn.input.data
  bkm_ids             O2M ─► dmn.bkm
  requirement_ids     O2M ─► dmn.requirement (DRD 邊)
  active              Boolean

dmn.decision                    DRD 中一個決策節點
  definitions_id      M2O
  dmn_id              Char      DMN element id（對應 XML，鍵）
  name                Char
  logic_type          Selection decision_table / literal_expression
  output_type_ref     Selection number/string/boolean/date/... | 'approver'
  table_id            M2O ─► dmn.decision.table  (logic_type=table)
  literal_expression  Text      (logic_type=literal_expression, FEEL)
  requires_ids        M2M self  資訊需求（依賴的其他 decision / input.data）
  is_approver_output  Boolean   compute：output 結構符合 approver 慣例
```

### 3.2 決策表本體（DMN 標準四要素）

```
dmn.decision.table
  decision_id   M2O
  hit_policy    Selection  unique/any/priority/first/collect/rule_order/output_order
  aggregation   Selection  none/sum/min/max/count   (collect 專用)
  input_ids     O2M ─► dmn.decision.table.input    (輸入欄/clause)
  output_ids    O2M ─► dmn.decision.table.output   (輸出欄/clause)
  rule_ids      O2M ─► dmn.decision.table.rule     (規則列)

dmn.decision.table.input        輸入欄（clause）
  table_id      M2O
  sequence      Integer
  label         Char       顯示名（如「金額」）
  expression    Char       FEEL 取值式（如 amount_total、record.amount_total）
  type_ref      Selection  number/string/boolean/date/...
  allowed_values Char      (可選) 列舉約束，供 UI 下拉 + 覆蓋分析

dmn.decision.table.output       輸出欄（clause）
  table_id      M2O
  sequence      Integer
  name          Char       輸出變數名（如 approver_resolver、sla_hours）
  label         Char
  type_ref      Selection
  default_value Char       FEEL（無命中時）

dmn.decision.table.rule         規則列
  table_id      M2O
  sequence      Integer
  description   Char
  input_entry_ids  O2M ─► dmn.rule.entry (kind=input)
  output_entry_ids O2M ─► dmn.rule.entry (kind=output)

dmn.rule.entry                  規則格（每列 × 每欄一格）
  rule_id       M2O
  clause_input_id  M2O (kind=input)   對映哪個輸入欄
  clause_output_id M2O (kind=output)  對映哪個輸出欄
  kind          Selection input/output
  text          Char  FEEL：input 為 unary test（如 ">= 50000"、"[1000..5000]"、"-"）
                      output 為 FEEL 運算式（如 "department_manager"、"amount*0.05"）
```

### 3.3 輸入資料、知識模型、需求邊、綁定

```
dmn.input.data                  DRD 輸入資料節點（被決策引用的外部資料）
  definitions_id M2O
  dmn_id        Char
  name          Char            （如「採購單」「申請人」）
  type_ref      Selection

dmn.bkm                         Business Knowledge Model（可複用函式 / 子決策表）
  definitions_id M2O
  dmn_id        Char
  name          Char            （如「職等對照」）
  logic_type    Selection decision_table / literal_expression
  table_id / literal_expression  同 decision

dmn.requirement                 DRD 邊（依賴）
  definitions_id M2O
  source_dmn_id  Char
  target_dmn_id  Char
  req_type       Selection information / knowledge / authority

dmn.input.binding               DMN 變數 ⇄ Odoo 來源（執行期注入）
  definitions_id M2O
  variable       Char           DMN input data / 變數名
  source_kind    Selection record_field / applicant / instance_ctx / constant
  record_field   Char           source_kind=record_field（如 amount_total、partner_id.country_id.code）
  constant_value Char
```

> **同步策略**：`dmn_xml` 為真相。`write(dmn_xml)` 觸發 `_parse_dmn()` 重建上述 shadow records
> （先刪後建，比照 `bpmn.executable.process` 的 node_config 重建）。shadow 提供：求值輸入、
> 後台搜尋/報表、覆蓋與重疊分析、權限稽核。**使用者不直接編輯 shadow（readonly）**。

---

## 4. FEEL 求值引擎（核心工程）

dmn-js 只產 XML、不含求值；Camunda 的 FEEL 引擎是 Java。**Python 端必須自建 FEEL 子集直譯器。**

### 4.1 子集範圍（涵蓋 90% 簽核決策需求）

**Unary test（規則格 input entry）**
- `-`（任意 / 不限）
- 比較：`<, <=, >, >=, =, !=` 接字面值
- 區間：`[a..b] (a..b] [a..b) (a..b)`
- 串列：`a, b, c`（命中其一）、`not(a, b)`
- 字面：number / string（`"差旅"`）/ boolean / date `date("2026-01-01")`
- 否定：`not(...)`

**輸出 / Literal expression**
- 算術 `+ - * / **`、字串 `+`（串接）
- `if … then … else …`
- 變數參照（輸入欄、上游決策輸出、BKM 結果、注入的 record 欄位）
- 白名單函式：`date/time/duration/now/today`、`string/upper/lower/contains/starts with`、
  `number/abs/floor/ceiling`、`list contains/count/sum/min/max`、`substring`

**型別系統**：number(Decimal) / string / boolean / date / time / duration / list / context / null。
型別轉換明確化，避免 Python 隱式轉型誤差（金額用 `Decimal`）。

### 4.2 架構

```
dmn.feel (TransientModel / 純函式服務)
  tokenize(src)        → tokens
  parse(tokens)        → AST node
  evaluate(ast, ctx)   → value         # ctx: dict 變數環境
  unary_test(src, val, ctx) → bool      # 規則格命中判斷
```

- AST node 類別：Literal / Var / BinOp / UnaryOp / Interval / List / FunCall / IfThenElse / Negation。
- Interpreter 為純遞迴下降，**無 `eval`/`exec`**，函式表白名單，無屬性逃逸（`__...__` 禁用）。
- 例外→`FeelError`，求值期捕捉後標記「該格無法求值」，不讓單一錯誤炸掉整張表。

### 4.3 安全

- 不可呼叫白名單外的函式；不可存取 Python 物件方法。
- record 欄位以「點路徑」唯讀解析（`amount_total`、`partner_id.country_id.code`），由 binding 限定
  可讀欄位集合，避免任意 ORM 走訪。
- 求值有步數/深度上限（防惡意巢狀）。

---

## 5. Runtime 評估流程

```
evaluate_definitions(definitions, record, applicant, instance):
  1. 解析 binding → 建立根 ctx（record 欄位、applicant、instance 變數、常數）
  2. 依 requirement(information) 對 decisions 做拓樸排序
  3. 逐一求值：
       - decision_table → 比對所有 rule input_entry（unary_test），套 hit_policy
       - literal_expression → 直接 evaluate
       - 結果寫回 ctx[decision.name]，供下游決策引用
  4. 回傳「根決策」輸出（或指定 decision 的輸出）
  5. 快取：同一 instance + 同一輸入指紋 → 命中快取（避免重複求值）
```

**Hit policy 實作**
| policy | 行為 |
|---|---|
| unique | 命中須唯一，否則錯誤 |
| any | 多命中但輸出須相同 |
| first | 取規則序第一條 |
| priority | 依 output 的 allowed_values 優先序取最高 |
| collect | 收集全部（簽核鏈即用此）；可加 aggregation sum/min/max/count |
| rule/output order | 依序輸出清單 |

> 現有 `bpmn.authority.matrix` 的 collect/priority/unique 與 `_coverage_warnings` 直接對映過來，
> 泛化為 `dmn.decision.table` 的覆蓋/重疊分析。

---

## 6. 與簽核引擎整合（四個出口）

### 6.1 簽核人鏈（approver 輸出慣例）— 最重要
約定一種輸出結構：決策表 output 欄為 `(resolver, level, job, users, phase)`（或單欄 `approver` 回 JSON）。
`is_approver_output` 為真的決策即可當簽核人來源。

- `bpmn.role.resolver_type` 新增 `dmn_decision` + `decision_id`（M2O `dmn.decision`）。
- `role.resolve(instance)`：呼叫 `evaluate_definitions` → 取 collect 鏈 → 每列轉 `_role_vals()` →
  沿用既有 `Role.new(...).resolve()` 解析 users。
- **分階引擎泛化**：把 `_enter_matrix_node` 改名/抽象為 `_enter_decision_node`，
  `phase` 來自決策回傳鏈的列序——核決權限表變成「DMN 決策的一個 preset」，引擎共用一套。

### 6.2 Gateway 條件
- exclusive/inclusive gateway 的出線條件 `resolver=dmn` → 決策輸出 boolean → token 路由。
- 取代散落各 gateway 的 Python 條件，集中治理。

### 6.3 Business Rule Task（`bpmn:businessRuleTask`）
- 節點求值 DMN 決策，輸出值**寫回 instance context 或 record 欄位**（如自動分類、算 SLA、定信用額度）。
- 補上目前「有節點型別、`dmn` feature、卻無編輯器與執行」的缺口，閉環。

### 6.4 流程路由（pre-routing）
- 送單前先跑一個 DMN 決策，**決定要實例化哪一個 `bpmn.executable.process` 範本 / 走哪條分支**。

---

## 7. 前端 dmn-js 整合

- **lib 載入**：`static/lib/dmn-io/`（dmn-js DRD + decision-table + literal modeler 打包），
  `static/src/modeler/dmn_lib_loader.js` 比照 `lib_loader.js`（本地優先、404 → CDN fallback）。
- **OWL 元件**：`static/src/dmn_editor/dmn_editor.js` + `.xml` + `.scss`，掛載 `DmnModeler`；
  DRD 檢視切換 ↔ 決策表檢視（dmn-js 原生支援雙檢視）。
- **Odoo 屬性面板**（自寫，非 dmn-js 預設）：
  - input data → `dmn.input.binding`（綁 Odoo 欄位 / applicant / 常數）
  - 決策 output → 標記是否 approver 慣例、type_ref
  - resolver 子選單（approver 輸出時，輸出格用「直屬/部門經理/職位/指定人」下拉，產生對應 FEEL）
- **儲存**：序列化 DMN XML → `orm.call(save_dmn_xml)` → 後端 `_parse_dmn()` 重建 shadow + 校驗。
- **入口**：選單 **流程設定 → 決策（DMN）** 清單（list `js_class` 加「新增決策」按鈕，
  比照 flow_wizard list controller）；發佈鈕、版本徽章比照 process editor。
- **試算**：泛化現有 `bpmn.authority.matrix.preview` → `dmn.decision.preview`：給輸入 → 顯示命中規則、
  輸出值、覆蓋/重疊警示、（approver 時）依序鏈與解析出的人。

---

## 8. 能力分級整合

`EXPERT_FEATURES` 已含 `dmn`。細分並補相依：

```
新增 / 細分 feature key（皆 expert 級，僅 implementer 可開）：
  dmn                  （保留，總開關＝決策求值執行期）
  dmn_decision_table   FEEL 決策表編輯器          deps: ['dmn']
  dmn_drd              DRD 多決策編排              deps: ['dmn_decision_table']
  dmn_feel             FEEL 運算式（進階）         deps: ['dmn_decision_table']
  dmn_business_rule    Business Rule Task 求值寫回 deps: ['dmn_decision_table','action_gate']
```

- `authority_matrix` 保留為「快速樣板」——其實是 `dmn_decision_table` 的友善子集 preset。
- 分級對應：**L1–L4 客戶＝消費**（送單自動帶決策結果）；**專家包 / `group_bpmn_implementer`＝設計**。
- `NODE_FEATURE['bpmn:businessRuleTask']` 由 `'dmn'` 細化為 `'dmn_business_rule'`。
- XML/決策掃描（`_scan_used_features`）擴充：掃出流程引用了哪些 DMN 能力 → 發佈期能力校驗。

---

## 9. 安全與權限

- `ir.model.access.csv`：所有 `dmn.*` 模型——designer 讀寫、implementer 讀寫、一般 user 唯讀
  （執行期求值用 sudo 在引擎內受控進行）。
- 設計權限：編輯 `dmn.definitions` 限 `group_bpmn_approval_designer` / `group_bpmn_implementer`。
- `record rule`：多公司 `company_id` 隔離。
- FEEL 沙箱（§4.3）：白名單函式、欄位點路徑唯讀、步數上限、禁屬性逃逸。
- 發佈閘：`validate_for_publish()` 泛化——欄位存在性、型別一致、hit_policy 完整性、approver 慣例完整。

---

## 10. 版本控管、治理、分析

- **版本**：`state` draft/published/archived + `version` 遞增（比照 executable.process）。流程綁的是
  「已發佈決策」；改決策須重新發佈，執行中實例維持舊版（搭配 `migration` 能力可遷移）。
- **稽核**：每次執行期求值，把 `(輸入快照 → 命中規則 → 輸出)` 記到 instance chatter，符合台灣核決留痕需求。
- **覆蓋 / 重疊分析**（泛化自 `_coverage_warnings`）：
  - 缺口：列舉型輸入的值域是否被規則覆蓋；數值階梯是否有斷層
  - 重疊：unique/any policy 下多規則命中衝突偵測
  - 死規則：永不命中的規則列
- **試算 / 模擬**：`dmn.decision.preview`（§7）。

---

## 11. 核決權限表 → DMN 共存與遷移

- **共存**：`resolver_type='authority_matrix'` 與 `'dmn_decision'` 並存；舊資料不動。
- **一鍵轉換**：`bpmn.authority.matrix.action_to_dmn()` → 產生等價 `dmn.definitions`
  （單一決策、collect、輸出 approver 慣例）。轉換後可在 dmn-js 進一步加欄位/FEEL/串接子決策。
- **核決權限表表單**保留為「精靈樣板」入口：適合不需 FEEL 的常見金額階梯；複雜情境再升級到 DMN 編輯器。
- 引擎統一：核決權限表執行期內部改走 `evaluate_definitions`（或維持現有路徑、僅新增 DMN 路徑），
  分階 link 引擎一套共用。

---

## 12. 模組與檔案結構（落在 dobtor_approval，不拆子模組）

```
dobtor_approval/
  models/
    dmn_definitions.py        # dmn.definitions + _parse_dmn + save_dmn_xml + evaluate_definitions
    dmn_decision.py           # dmn.decision / .table / .input / .output / .rule / .rule.entry
    dmn_input_data.py         # dmn.input.data / dmn.bkm / dmn.requirement / dmn.input.binding
    dmn_feel.py               # FEEL lexer/parser/interpreter（純 Python）
    dmn_decision_preview.py   # 試算 TransientModel
    bpmn_role.py              # +resolver_type 'dmn_decision' +decision_id +_resolve_dmn_decision
    bpmn_process_instance.py  # _enter_matrix_node → 泛化 _enter_decision_node
    feature_registry.py       # 細分 dmn_* features + deps + labels
  views/
    dmn_definitions_views.xml # list(js_class 按鈕)/form/發佈/版本徽章 + 選單
    dmn_decision_preview_views.xml
    res_config_settings_views.xml  # 能力分級 UI 補 dmn_* 開關
  security/
    dobtor_approval_security.xml   # （沿用既有群組）
    ir.model.access.csv            # dmn.* 權限列
  static/
    lib/dmn-io/                     # dmn-js 打包 + README（CDN fallback）
    src/modeler/dmn_lib_loader.js
    src/dmn_editor/dmn_editor.{js,xml,scss}
    src/dmn_editor/dmn_list_controller.js
    src/dmn_editor/properties/*.js  # Odoo 綁定屬性面板
  data/
    dmn_demo.xml                    # 範例：採購核決 DRD（風險→額度→層級）
  DESIGN_DMN.md                     # 本文件
__manifest__.py                     # assets_backend 加入 dmn_editor / dmn_lib_loader；data 加 views/security
```

---

## 13. 端到端範例：採購核決 DRD

```
[輸入資料] 採購單 ── information ──►┐
[輸入資料] 申請人 ── information ──►├─► [決策] 風險評等  ──┐
                                    │   (table: 金額×類別  │ information
                                    │    → high/mid/low)   ▼
                                    └─► [決策] 核決層級鏈 ──► 輸出 approver 鏈
                                        (table: 風險×金額×部門
                                         → collect: 直屬/部門經理/上層/總經理)
              [BKM] 職等對照 ── knowledge ──► 核決層級鏈
```

- 流程編輯器：簽核節點「核決」簽核對象 = **DMN 決策（核決層級鏈）**。
- 送單（金額 60 萬、海外、研發部）→ 風險評等=high → 核決層級鏈 collect 命中四列 →
  依序鏈：直屬 → 部門經理 → 上層 → 總經理（分階逐關，沿用既有 phase 引擎）。
- chatter 留痕：輸入快照 + 命中規則 + 解析簽核人。

---

## 14. 風險與取捨

| 風險 | 評估 / 緩解 |
|---|---|
| **FEEL 引擎工程量**（最大） | 自建子集直譯器，範圍收斂在簽核決策需求（§4.1）；先求正確再求完整；以單元測試覆蓋每種 unary test 與型別 |
| DMN XML ↔ shadow 同步漂移 | 單向：XML 為真相、存檔重建 shadow；shadow 唯讀；比照已驗證的 BPMN node_config 模式 |
| DRD 對一般使用者過複雜 | 預設只開決策表（`dmn_decision_table`）；DRD（`dmn_drd`）限 expert/SI；核決權限表樣板照顧 80% |
| 效能（執行期求值） | 拓樸排序 + 結果快取 + 求值步數上限；決策表規則數實務上不大 |
| 與既有核決權限表重疊 | 共存 + 一鍵轉換 + 引擎統一，不破壞既有已發佈流程 |
| dmn-js 版本/CDN 依賴 | 比照 bpmn-js：本地 lib 優先、CDN fallback、lib_loader 動態載入 |

---

## 15. 已拍板決策（2026-06-07）

1. **FEEL 範圍：完整子集**（§4.1 全做——unary test 全套 + 輸出運算式 + 白名單函式 + 完整型別系統）。
2. **核決權限表：保留**為友善樣板入口（非技術使用者用），與 DMN 編輯器共存、可一鍵轉 DMN。
3. **DRD：納入首版**（多決策依賴編排 + BKM 複用 + DRD 檢視，不延後）。
4. **求值欄位邊界：限 binding 白名單**——FEEL 只能讀 `dmn.input.binding` 宣告過的 record 欄位點路徑。
5. **無遷移負擔**：`dobtor_approval` 為全新開發，發佈即採最新版；**不實作執行中實例遷移 / 凍結舊版**機制。
   §10「版本」僅保留 draft/published/archived 與稽核留痕，不做 in-flight 版本綁定。

---

## 16. 施工清單（逐檔，依相依排序）

> 全新開發、無遷移。先做可單元測試的純 Python 核心（A、B），再做引擎整合與分級（C、D），
> 最後做需 lib 打包、較難本機驗證的前端（F）。E/G/H 收尾。

### Layer A — FEEL 求值引擎（純 Python，stdlib only，可獨立單元測試）
- `models/dmn_feel.py`：lexer → recursive-descent parser → AST → interpreter；型別系統
  （Decimal/str/bool/date/time/duration/list/context/null）；unary test 全套；白名單函式表；
  `FeelError`；`evaluate(ast, ctx)`、`unary_test(src, value, ctx)`。**核心抽成 pure functions**（不 import odoo），
  另以薄 `AbstractModel` 包裝供 ORM 呼叫 → 可在 3.9 跑 standalone 測試。
- `tests/test_feel.py`：每種 unary test、區間、清單、否定、型別、if-then-else、函式、安全邊界。

### Layer B — 資料模型（ORM）
- `models/dmn_definitions.py`：`dmn.definitions`；`save_dmn_xml()`；`_parse_dmn()`（XML→shadow，先刪後建）；
  `evaluate_definitions(record, applicant, instance)`（binding→ctx、拓樸排序、逐決策求值、快取、回根輸出）；
  `validate_for_publish()`；`get_dmn_data()`。
- `models/dmn_decision.py`：`dmn.decision / .table / .input / .output / .rule / .rule.entry`（§3.1–3.2）。
- `models/dmn_input_data.py`：`dmn.input.data / dmn.bkm / dmn.requirement / dmn.input.binding`（§3.3）。
- `models/dmn_decision_preview.py`：`dmn.decision.preview` 試算（命中規則 + 輸出 + 覆蓋/重疊 + approver 鏈）。

### Layer C — 簽核引擎整合
- `models/bpmn_role.py`：`resolver_type` 加 `('dmn_decision','DMN 決策')` + `decision_id` + `_resolve_dmn_decision`。
- `models/bpmn_process_instance.py`：`_enter_matrix_node`→泛化 `_enter_decision_node`；
  `_on_matrix_link_approved`→`_on_decision_link_approved`（核決權限表與 DMN 共用分階 link）。
- gateway 出線條件支援 `dmn` 決策回 boolean；`bpmn:businessRuleTask` 求值寫回 ctx/record。

### Layer D — 能力分級
- `models/feature_registry.py`：細分 `dmn_decision_table / dmn_drd / dmn_feel / dmn_business_rule` + deps + labels；
  `NODE_FEATURE['bpmn:businessRuleTask']='dmn_business_rule'`；`RESOLVER_FEATURE['dmn_decision']='dmn_decision_table'`；
  `_scan_used_features` 掃 DMN 引用。
- `models/res_config_settings.py` + `views/res_config_settings_views.xml`：dmn_* 開關（專家包區）。

### Layer E — 安全 / 視圖 / 選單
- `security/ir.model.access.csv`：`dmn.*` designer/implementer 讀寫、user 唯讀。
- `views/dmn_definitions_views.xml`：list（js_class 按鈕）/ form（編輯器入口 + 發佈 + 版本徽章）/ 選單「流程設定 → 決策（DMN）」。
- `views/dmn_decision_preview_views.xml`：試算表單。

### Layer F — 前端 dmn-js
- `static/lib/dmn-io/`：dmn-js（DRD + decision-table + literal）打包 + README + CDN fallback。
- `static/src/modeler/dmn_lib_loader.js`：比照 `lib_loader.js`。
- `static/src/dmn_editor/dmn_editor.{js,xml,scss}`：掛載 `DmnModeler`、DRD↔表雙檢視、儲存 XML。
- `static/src/dmn_editor/dmn_list_controller.js`：list 按鈕→開編輯器。
- `static/src/dmn_editor/properties/*.js`：Odoo 屬性面板（binding 綁欄位、output approver 慣例、resolver 子選單）。

### Layer G — 核決權限表共存
- `models/bpmn_authority_matrix.py`：`action_to_dmn()` 轉換器；保留矩陣表單為樣板；執行期分階引擎共用一套。

### Layer H — Demo / manifest / DESIGN
- `data/dmn_demo.xml`：採購核決 DRD（風險評等 → 核決層級鏈 + 職等對照 BKM，§13）。
- `__manifest__.py`：`assets_backend` 加 dmn_editor / dmn_lib_loader；`data` 加 views/security/demo。
- 交叉更新 `DESIGN_APPROVAL_EDITOR.md` / `DESIGN_PROGRESSIVE_TIERS.md`。

> 工程主體在 A–C；A 為最高風險（FEEL）且可獨立驗證，**首先完成並單元測試**。
