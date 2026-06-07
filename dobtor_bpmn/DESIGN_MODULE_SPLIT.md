# dobtor_approval / dobtor_bpmn — 模組分層架構：簽核引擎＋編輯器核心（基礎） vs 流程設計圖庫（擴充）

> 文件版本：v2.0 ｜ 撰寫日：2026-06-06（v1.x）／**架構反轉：2026-06-07（v2.0）** ｜ 目標 Odoo：18.0
>
> ## ⚠️ v2.0 重大變更：依賴方向已反轉
> v1.x 的分層為「`dobtor_bpmn`（純設計）= 基礎，`dobtor_approval`（簽核）= 擴充、depends bpmn」。
> **v2.0 起反轉**：`dobtor_approval` 內建 BPMN 編輯器核心、成為**自足基礎**，可獨立安裝後直接設計＋執行簽核流程；`dobtor_bpmn` 變成**疊在 approval 之上的流程設計圖庫**（depends `dobtor_approval`），提供 documentation/blueprint 等通用設計圖，並能把設計圖**複製 XML（forked）**交給簽核引擎建立可執行流程。
>
> 反轉動機：簽核才是主產品；要讓「裝了簽核就能直接畫＋跑」，編輯器核心必須與引擎同在一個自足模組，避免「簽核引擎缺了另一個模組就無法設計」。`dobtor_bpmn` 退居為「通用流程文件/規格圖庫」加值層。
>
> **模組命名對照（v2.0 定版，僅 2 模組）**：
> | 角色 | 模組技術名 | 中文 | 說明 |
> |---|---|---|---|
> | 基礎·簽核引擎＋編輯器核心 | **`dobtor_approval`** | 簽核 | 內建 bpmn-js/dmn-js 編輯器核心 + 角色/閘門/token/執行 + 代簽核/加簽/DMN（T0–T6 能力開關分級啟用）。**可獨立安裝＝可設計＋可執行的簽核工具** |
> | 擴充·流程設計圖庫 | **`dobtor_bpmn`** | 流程圖庫 | `bpmn.diagram` 設計圖庫（用途分類 documentation/blueprint/template/executable_src），重用 approval 的編輯器核心；可把設計圖 forked 交給簽核引擎 |
>
> **不再分子模組**：原 `dobtor_approval_activity`（代簽核/加簽）與 `dobtor_approval_dmn`（DMN 求值）**併入 `dobtor_approval`**，改用模組內 T0–T6 能力開關（預設關閉）控制，而非實體拆分。
>
> **🚫 非目標（Out of Scope）**：兩模組**皆不提供表單設計器 / 表單建構器**。只畫 BPMN/DMN「流程與決策」；簽核 `dobtor_approval` 走「動作/單據中心」，資料輸入一律用 **Odoo 原生 form view / 既有單據**。

---

## 0. 分層原則（為什麼這樣分）

| 原則 | 說明 |
|------|------|
| **設計 ≠ 執行** | 「一張流程圖長什麼樣」是設計；「這張圖怎麼跑、誰簽、攔哪個 action」是執行規格。兩者生命週期、使用者、價值都不同。**v2.0 起兩者同住 `dobtor_approval`**：編輯器核心畫圖、引擎跑圖，但程式上仍以「編輯器核心 / 執行引擎」清楚分層。 |
| **基礎可獨立成立** | 基礎模組 `dobtor_approval` 自身即完整：內建 BPMN/DMN 編輯器 + 簽核引擎，**裝它就能直接設計並執行簽核流程**，不需要 `dobtor_bpmn`。 |
| **擴充只增不改基礎** | 擴充模組 `dobtor_bpmn` 依賴基礎、重用基礎的編輯器核心、提供自己的設計圖庫，但**不改基礎的核心資料、選單、引擎**（鬆耦合）。設計圖交給引擎一律走 forked 複製 XML，不反向硬綁基礎模型。 |
| **規格與引擎分離** | 「BPMN/DMN 設計規格」可由 `dobtor_bpmn` 的設計圖庫承載（文件/藍圖）；「BPM 簽核/執行規格」歸 `dobtor_approval`。 |

---

## 1. 分層架構總圖

```
┌──────────────────────────────────────────────────────────────┐
│  擴充層（可多個，各自選單與用途）                                  │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────┐ │
│  │ dobtor_bpmn        │  │ dobtor_<其他擴充>    │  │ 其他擴充  │ │
│  │ (流程設計圖庫)      │  │ (未來其他流程應用)  │  │          │ │
│  │ 選單「流程設計圖」   │  │ 選單「…流程」       │  │          │ │
│  │ ・bpmn.diagram 庫   │  │                     │  │          │ │
│  │ ・重用核心編輯器     │  │                     │  │          │ │
│  │ ・forked → 簽核流程  │  │                     │  │          │ │
│  └─────────┬──────────┘  └─────────┬──────────┘  └────┬─────┘ │
│            │  depends / 重用編輯器核心 / forked 交付       │       │
│            ▼                         ▼                   ▼       │
├──────────────────────────────────────────────────────────────┤
│  基礎層  dobtor_approval （簽核引擎 ＋ 內建 BPMN 編輯器核心）     │
│  選單「簽核流程」                                                │
│  ・BPMN/DMN 編輯器核心（bpmn-js / dmn-js、lib_loader、節點 registry）│
│  ・簽核設定編輯器 process_editor（設計簽核流程）                  │
│  ・bpmn.executable.process 可執行流程（forked，自持 XML）         │
│  ・角色解析 / Action 閘門 / token 執行 / mail.activity 橋接       │
│  ・代簽核 / 加簽 / 職務代理 / DMN（T0–T6 能力開關）              │
│  ・編輯器/設計群組 group_bpmn_diagram_user/manager               │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 基礎模組 `dobtor_approval`（簽核引擎 ＋ 編輯器核心）

### 2.1 定位 = 「自足的簽核設計＋執行工具」
- `depends = ['web', 'mail', 'hr']`（**不依賴 dobtor_bpmn**）。
- 內建 **BPMN 2.0 / DMN 編輯器核心**：`bpmn-js` / `dmn-js` 動態載入、節點型別 registry、簽核設定編輯器 `process_editor`，裝它就能直接畫＋設定簽核流程。
- 疊上全部執行能力：角色解析、Action 閘門、token、mail.activity 橋接、加簽/代理、代簽核/DMN（以 §DESIGN_PROGRESSIVE_TIERS T0–T6 開關分級）。
- 自己的頂層選單 **「簽核流程 (Approval Workflows)」**。

### 2.2 編輯器核心（v2.0 移入本模組）
```
dobtor_approval/static/
  lib/bpmn-io/                          # bpmn-js / dmn-js 函式庫放置處（動態載入，缺檔 CDN 後援）
  src/modeler/lib_loader.js             # ★ 函式庫載入器；LOCAL = /dobtor_approval/static/lib/bpmn-io
  src/registry/node_type_registry.js    # ★ 前端節點型別註冊表（擴充注入點）
  src/registry/approval_node_types.js   # 簽核專屬節點型別（簽核任務/會簽/Odoo 動作/條件閘…）
  src/designer/odoo_properties_provider.js  # 屬性面板 RPC 動態選項
  src/editor/process_editor.js / .xml / .scss  # 簽核設定編輯器（client action）
```
- 後端 `bpmn.node.type.registry`（AbstractModel）：定義標準 BPMN 元素 `BASE_NODE_TYPES` ＋簽核節點 `APPROVAL_NODE_TYPES`，`_get_node_types()` 回傳合併清單。其他模組可 `_inherit` 此模型 super() 後追加（仍為擴充注入點，見 §4）。

### 2.3 可執行流程模型 `bpmn.executable.process`（forked-only）
```python
class BpmnExecutableProcess(models.Model):
    _name = 'bpmn.executable.process'
    _description = '可執行簽核流程'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    xml = fields.Text('執行用 BPMN XML')   # ★ 自持 XML（可由設計圖複製帶入後獨立增刪節點）
    # 執行 overlay：以 bpmn element id 為鍵的逐節點執行規格
    node_config_ids = fields.One2many('bpmn.node.config', 'process_id')
    role_ids = fields.One2many('bpmn.role', 'process_id')
    gate_ids = fields.One2many('bpmn.action.gate', 'process_id')

    def _effective_xml(self):
        """回傳實際用於解析/執行的 XML（forked：即自持 xml）。"""
        self.ensure_one()
        return self.xml or ''
```
> **v2.0 變更**：移除 `source_diagram_id`（→ bpmn.diagram）與 `link_mode`（linked/forked）。流程一律**自持 XML**（forked 語意）；不再有「即時連動來源設計圖」的 linked 模式。引擎不認得 `bpmn.diagram`，保持基礎乾淨。

---

## 3. 擴充模組 `dobtor_bpmn`（流程設計圖庫）

### 3.1 定位
- `depends = ['dobtor_approval']`（取得編輯器核心、群組、`bpmn.executable.process` 模型）。
- 自己的頂層選單 **「流程設計圖 (Process Diagrams)」**，與基礎「簽核流程」分開。
- 提供 `bpmn.diagram` 設計圖庫：純流程文件/規格圖（用途分類），可拿來①記錄既有 Odoo 模組流程 ②畫客戶專案規格藍圖 ③可複用樣板。
- **重用 approval 編輯器核心**：`bpmn_editor_action.js` import 自 `@dobtor_approval/modeler/lib_loader`，不自帶 bpmn-js。

### 3.2 核心模型 `bpmn.diagram`（純設計，無執行語意）
```python
class BpmnDiagram(models.Model):
    _name = 'bpmn.diagram'
    _description = '流程設計圖（純設計，無執行語意）'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, tracking=True)
    diagram_type = fields.Selection([('bpmn', 'BPMN'), ('dmn', 'DMN')], default='bpmn')
    xml = fields.Text('設計 XML')
    svg = fields.Text('縮圖 SVG')
    version = fields.Integer(default=1)
    state = fields.Selection([('draft','草稿'),('reviewed','已審閱'),('frozen','定版')], default='draft')

    # ★ 用途分類
    purpose = fields.Selection([
        ('documentation', '既有 Odoo 模組流程記錄 (as-is)'),
        ('blueprint',     '客戶專案規格藍圖 (to-be，尚未實作)'),
        ('template',      '可複用樣板'),
        ('executable_src','供簽核引擎衍生可執行流程的來源')],
        default='documentation', required=True, index=True)
    category_id = fields.Many2one('bpmn.diagram.category')
    tag_ids = fields.Many2many('bpmn.diagram.tag')

    def get_xml(self): ...                 # 取設計 XML

    def action_create_executable_process(self):
        """★ handoff（forked-only）：複製本設計圖 XML，
        在 dobtor_approval 建立 bpmn.executable.process 並開啟。"""
        self.ensure_one()
        process = self.env['bpmn.executable.process'].create({
            'name': self.name, 'xml': self.get_xml()})
        return {'type': 'ir.actions.act_window', 'res_model': 'bpmn.executable.process',
                'res_id': process.id, 'view_mode': 'form', 'target': 'current'}
```
> **設計圖交付＝forked-only**：`action_create_executable_process()` 把設計圖 XML 複製進新的可執行流程後，兩者即脫鉤；設計圖之後修改不影響已建立的流程（無 linked 連動）。

### 3.3 權限
- `bpmn.diagram` 的 access/rule/menu 一律重用基礎的群組 **`dobtor_approval.group_bpmn_diagram_user` / `…_manager`**（編輯器/設計群組已隨編輯器核心移入 approval）。

---

## 4. 編輯器核心的「節點型別 registry」擴充機制 ★

簽核專屬積木（簽核任務、Odoo 動作、條件閘…）需在編輯器裡長出，靠雙端註冊。**v2.0 後基礎＝approval，registry 與其消費者同住 approval**；機制仍開放給未來模組擴充。

### 4.1 前端 JS 註冊表
```javascript
// dobtor_approval 提供（編輯器核心）
import { nodeTypeRegistry } from "@dobtor_approval/registry/node_type_registry";
// approval 自身註冊簽核節點（approval_node_types.js）
nodeTypeRegistry.register({ id: 'odoo:approvalTask', label: '簽核任務', group: 'odoo', ... });
```
- 其他擴充模組亦可 import 同一 registry 追加節點。
- **⚠️ 現況（roadmap，尚未落地）**：「`palette_provider` / `properties_registry` 讀 registry 動態渲染」目前**未實作**——`process_editor` 用 bpmn-js 原生 palette 與右側硬寫死的 OWL 設定面板，前端 `nodeTypeRegistry` 暫無 UI 消費端（僅後端 `_get_node_types()` 有消費端）。此為預留擴充注入點，待 T4 自助設計器階段再落地動態 palette。

### 4.2 後端 Python 註冊（moddle 擴充 + 解析）
```python
# 基礎（approval）即定義 base + approval 節點於同一 AbstractModel：
class BpmnNodeTypeRegistry(models.AbstractModel):
    _name = 'bpmn.node.type.registry'
    def _get_node_types(self):
        types = list(BASE_NODE_TYPES)         # 標準 BPMN
        types += APPROVAL_NODE_TYPES          # 簽核節點（去重）
        return types
# 未來其他模組仍可 _inherit 'bpmn.node.type.registry' super() 後追加
```

### 4.3 隔離保證
- 編輯器核心只認得節點是合法 BPMN 元素（帶 `odoo:` 擴充屬性），不耦合特定業務。
- `dobtor_bpmn` 的後端控制器 `/dobtor_bpmn/node_types` 仍透過 `bpmn.node.type.registry`（由基礎提供）取得節點清單。

---

## 5. 設計圖的三大用途（`dobtor_bpmn`）

| 用途 (`purpose`) | 內容 | 誰用 | 後續去向 |
|------------------|------|------|---------|
| **documentation（既有 Odoo 模組流程記錄）** | 用 BPMN/DMN 把 `sale`/`purchase`/`account` 等**原生模組實際流程**畫出來（as-is），當技術文件/教育訓練/交接 | 顧問、IT | 可升級為 `executable_src`，forked 交簽核引擎 |
| **blueprint（客戶專案規格藍圖）** | 客戶 Odoo 開發案**尚未實作**的流程設計（to-be），當規格書流程章節、與客戶確認範圍 | 售前、PM、架構師 | 開發後對照驗收；或 forked 衍生為可執行流程 |
| **executable_src（執行來源）** | 確定要上線簽核的設計，標記為可被衍生 | 設計師 | 按「建立簽核流程」forked → approval 加執行規格 → 發佈 |
| **template（樣板）** | 通用流程樣板庫 | 全體 | 一鍵套用為新設計圖 |

### 5.1 工作流：從規格藍圖到上線
```
dobtor_bpmn：畫 blueprint 設計圖（純 BPMN/DMN，客戶確認規格）
   │  （專案開發 Odoo 模組…）標記 purpose = executable_src（定版 frozen）
   ▼
按「建立簽核流程」→ forked 複製 XML 至 dobtor_approval.bpmn.executable.process
   ▼
dobtor_approval：process_editor 加 node_config（角色/閘門）→ 發佈 → 簽核上線
```
> 註：也可完全不裝 `dobtor_bpmn`，直接在 `dobtor_approval` 的 process_editor 從零設計簽核流程。設計圖庫是「加值的文件/規格層」，非簽核必要前置。

---

## 6. 與既有規劃（DESIGN / SELF_SERVICE / TIERS）的調和

| 既有規劃 | v2.0 歸屬 |
|----------|-----------|
| bpmn-js / dmn-js 編輯器核心、lib_loader、節點 registry | **`dobtor_approval`（編輯器核心）** |
| 簽核設定編輯器 process_editor、簽核專屬積木、角色 RPC、lint | `dobtor_approval` |
| 角色解析、Action 閘門、token 執行、mail.activity 橋接、加簽/代理 | `dobtor_approval`（引擎） |
| 代簽核/加簽（原 _activity）、DMN 求值（原 _dmn） | `dobtor_approval`（T3 / T5 能力開關，不再獨立模組） |
| `bpmn.diagram` 設計圖庫、版本、SVG、用途分類 | **`dobtor_bpmn`（設計圖庫）** |
| T0–T6 能力分級開關 | `dobtor_approval` |

> **修訂後模組清單（僅 2 模組）**：
> - `dobtor_approval`（基礎·簽核引擎＋編輯器核心，含代簽核/加簽/DMN，能力開關分級）← 可單獨安裝
> - `dobtor_bpmn`（擴充·流程設計圖庫）← 依賴 `dobtor_approval`

---

## 7. 依賴與發佈策略

```
dobtor_approval   (自足：簽核引擎＋編輯器核心，可單獨安裝＝可設計＋可執行)
   ▲
   │ depends
dobtor_bpmn   (流程設計圖庫，疊在 approval 編輯器核心之上)
```
- **基礎可單獨販售/部署**：裝 `dobtor_approval` 即可設計並執行簽核流程；代簽核/加簽/DMN 等進階能力以 **T0–T6 開關**（預設關閉）按需開啟。
- **設計圖庫按需加裝**：要把「畫 Odoo 模組流程 / 客戶規格藍圖 / 樣板庫」做成正式文件管理，再加裝 `dobtor_bpmn`，並可一鍵把設計圖 forked 成簽核流程。

---

## 8. Roadmap（基礎優先）

| 波 | 模組 | 內容 |
|----|------|------|
| **波 0（最先）** | `dobtor_approval` | 編輯器核心（bpmn-js/dmn-js、registry、lib_loader）、process_editor、`bpmn.executable.process`、選單「簽核流程」 |
| 波 1 | `dobtor_approval` | node_config overlay、角色解析、基本 token 執行 |
| 波 2 | `dobtor_approval` | Action 閘門、token、mail.activity 橋接（DESIGN.md M4–M5） |
| 波 3 | `dobtor_approval`（開關） | 代簽核、個人化加簽（T3） |
| 波 4 | `dobtor_approval`（開關） | DMN 求值執行、綁 gateway（T5） |
| 波 5 | `dobtor_bpmn` | `bpmn.diagram` 設計圖庫、用途分類、版本、forked handoff 按鈕、選單「流程設計圖」 |

> v2.0 順序調整：編輯器核心與引擎同屬基礎，故波 0 即在 `dobtor_approval` 完成；設計圖庫 `dobtor_bpmn` 為後續加值層。

---

## 9. 關鍵設計決策摘要（v2.0）

1. **依賴反轉**：`dobtor_approval` = 自足基礎（編輯器核心＋引擎，可獨立設計＋執行）；`dobtor_bpmn` = 疊加設計圖庫，depends approval。
2. **forked-only 交付**：設計圖→簽核流程一律複製 XML（`action_create_executable_process`），移除 linked 連動與 `source_diagram_id`；引擎自持 XML、不認得 `bpmn.diagram`。
3. **編輯器核心在 approval**：bpmn-js/dmn-js、lib_loader、node_type_registry（JS＋Python AbstractModel）、編輯器群組皆在 approval；`dobtor_bpmn` import `@dobtor_approval/...` 重用。
4. **節點型別 registry**：標準＋簽核節點同住 approval 的 AbstractModel；仍是 `_inherit` 擴充注入點，拔掉擴充不壞檔。
5. **用途分類 `purpose`**：documentation / blueprint / executable_src / template，讓 `dobtor_bpmn` 同時是「文件工具」與「執行來源」。
6. **基礎可獨立成立**：單裝 `dobtor_approval` 即可設計並執行簽核流程；`dobtor_bpmn` 為按需加值。
