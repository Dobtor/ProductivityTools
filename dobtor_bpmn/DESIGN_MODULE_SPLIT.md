# dobtor_bpmn / dobtor_approval — 模組分層架構：純設計環境（基礎） vs BPM 執行（擴充）

> 文件版本：v1.1 ｜ 撰寫日：2026-06-06 ｜ 目標 Odoo：18.0
> 核心訴求：**BPMN/DMN「設計編輯」與 BPM「簽核執行規格」徹底分離** —— 基礎模組 = demo.bpmn.io 等價的純繪圖環境；擴充模組 = 載入基礎設計再延伸成可執行流程，並能向基礎編輯器增加節點。
>
> **模組命名對照（v1.2 定版，僅 2 模組）**：
> | 角色 | 模組技術名 | 中文 | 說明 |
> |---|---|---|---|
> | 基礎·純設計 | **`dobtor_bpmn`** | 核心 | BPMN/DMN 純編輯器 + 設計圖庫（等同 demo.bpmn.io），無執行語意 |
> | 擴充·BPM 引擎 | **`dobtor_approval`** | 簽核 | 載入核心設計再延伸；角色/閘門/token/執行 + **代簽核/加簽 + DMN 求值**，全部以能力開關分級啟用 |
>
> **不再分子模組**：原 `dobtor_approval_activity`（代簽核/加簽）與 `dobtor_approval_dmn`（DMN 求值）**併入 `dobtor_approval`**，改用模組內 T0–T6 能力開關（預設關閉）控制，而非實體拆分。
>
> **🚫 非目標（Out of Scope）**：兩模組**皆不提供表單設計器 / 表單建構器**。核心 `dobtor_bpmn` 只畫 BPMN/DMN；簽核 `dobtor_approval` 走「動作/單據中心」，資料輸入一律用 **Odoo 原生 form view / 既有單據**。本專案只設計「流程與決策」，不設計表單。

---

## 0. 分層原則（為什麼要拆）

| 原則 | 說明 |
|------|------|
| **設計 ≠ 執行** | 「一張流程圖長什麼樣」是設計；「這張圖怎麼跑、誰簽、攔哪個 action」是執行規格。兩者生命週期、使用者、價值都不同 → 必須拆模組。 |
| **基礎可獨立成立** | 基礎模組自身就是一個有價值的工具：純 BPMN/DMN 繪圖器 + 設計圖庫，可拿來①記錄既有 Odoo 模組流程 ②畫尚未實作的客戶專案規格書。**不裝擴充也能用。** |
| **擴充只增不改基礎** | 擴充模組（BPM 引擎）依賴基礎、載入基礎設計、向基礎註冊新節點型別，但**不改基礎的核心資料與選單**（鬆耦合，可多個擴充並存）。 |
| **規格與引擎分離** | 規格書裡「BPMN/DMN 設計規格」歸基礎模組章節；「BPM 簽核/執行規格」歸擴充模組章節 —— 文件結構與程式碼結構一致。 |

---

## 1. 分層架構總圖

```
┌──────────────────────────────────────────────────────────────┐
│  擴充層（可多個，各自選單與用途）                                  │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────┐ │
│  │ dobtor_approval        │  │ dobtor_<其他擴充>    │  │ 其他擴充  │ │
│  │ (BPM 簽核引擎)      │  │ (未來其他流程應用)  │  │          │ │
│  │ 選單「簽核流程」     │  │ 選單「…流程」       │  │          │ │
│  │ ・載入基礎設計再延伸 │  │                     │  │          │ │
│  │ ・註冊新節點型別     │  │                     │  │          │ │
│  │ ・角色/閘門/執行     │  │                     │  │          │ │
│  └─────────┬──────────┘  └─────────┬──────────┘  └────┬─────┘ │
│            │  載入/延伸/註冊節點      │                   │       │
│            ▼                         ▼                   ▼       │
├──────────────────────────────────────────────────────────────┤
│  基礎層  dobtor_bpmn （純設計環境，等同 demo.bpmn.io）        │
│  選單「流程設計圖」                                               │
│  ・BPMN Modeler + DMN Modeler（bpmn-js / dmn-js 純編輯）          │
│  ・bpmn.diagram 設計圖庫（存 XML、版本、用途分類）                 │
│  ・節點型別註冊表（base palette + 擴充可注入）                     │
│  ・對外 API / extension points                                   │
│  ・無執行、無簽核、無 Odoo 業務綁定                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 基礎模組 `dobtor_bpmn`（純設計環境）

### 2.1 定位 = 「Odoo 內的 demo.bpmn.io」
- 提供 **BPMN 2.0 Modeler** 與 **DMN Modeler**（bpmn-js / dmn-js 純編輯，含 properties-panel 標準屬性），**只畫圖、存圖、版本管理**。
- **不含**：角色解析、Action 攔截、token 執行、mail.activity、簽核 —— 這些全在擴充層。
- 自己的頂層選單 **「流程設計圖 (Process Diagrams)」**，與擴充模組的「簽核流程」選單完全分開。

### 2.2 核心模型 `bpmn.diagram`
```python
class BpmnDiagram(models.Model):
    _name = 'bpmn.diagram'
    _description = '流程設計圖（純設計，無執行語意）'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    diagram_type = fields.Selection([
        ('bpmn', 'BPMN 流程圖'),
        ('dmn', 'DMN 決策表/DRD')], required=True, default='bpmn')
    xml = fields.Text('設計 XML')          # bpmn-js / dmn-js 來源（標準，無 odoo: 擴充亦可）
    svg = fields.Text('縮圖 SVG')
    version = fields.Integer(default=1)
    state = fields.Selection([
        ('draft', '草稿'), ('reviewed', '已審閱'), ('frozen', '定版')],
        default='draft', tracking=True)

    # ★ 用途分類（規格書與三大使用情境的關鍵）
    purpose = fields.Selection([
        ('documentation', '既有 Odoo 模組流程記錄 (as-is)'),
        ('blueprint',     '客戶專案規格藍圖 (to-be，尚未實作)'),
        ('template',      '可複用樣板'),
        ('executable_src','供擴充模組衍生可執行流程的來源')],
        default='documentation', required=True, index=True)

    # 設計分類/歸檔（純文件管理用，非執行）
    category_id = fields.Many2one('bpmn.diagram.category')
    project_ref = fields.Char('關聯專案/客戶')          # blueprint 用
    odoo_module = fields.Char('關聯 Odoo 模組技術名')    # documentation 用，如 'sale'
    tag_ids = fields.Many2many('bpmn.diagram.tag')

    # 給擴充模組的反向關聯（One2many，但定義在擴充模組以保鬆耦合）
    # derived_process_ids ← 由 dobtor_approval 反向 inverse
```
> **關鍵**：`bpmn.diagram` 是「純設計成品」，可以完全不帶任何 Odoo 執行屬性。它能存標準 BPMN（給其他工具開）、也能存帶 `odoo:` 擴充屬性的（給擴充模組延伸）。

### 2.3 編輯器元件（基礎只給「標準」調色盤）
```
dobtor_bpmn/static/src/
  modeler/bpmn_modeler.js / .xml      # 純 bpmn-js modeler OWL 包裝
  modeler/dmn_modeler.js / .xml       # 純 dmn-js modeler OWL 包裝
  registry/node_type_registry.js      # ★ 節點型別註冊表（擴充注入點）
  registry/palette_provider.js        # 依註冊表動態生成調色盤
  registry/properties_registry.js     # 依註冊表動態生成屬性面板分組
```
- 基礎模組註冊「標準 BPMN/DMN 元素」到 registry。**擴充模組透過同一 registry 追加自訂節點型別**（見 §4）。

### 2.4 對外 API / Extension Points（給擴充用）
```python
# bpmn.diagram 公開方法
def get_xml(self): ...                        # 取設計 XML
def clone_for_extension(self, target_model):  # 衍生一份副本給擴充（forked 模式）
    """回傳新 record（含複製 XML），供擴充建立可執行流程"""
def register_derived(self, res_model, res_id):# 由擴充回報「我衍生了一個執行流程」

# 註冊表（Python 端，給後端解析用；前端另有 JS registry）
class BpmnNodeTypeRegistry(models.AbstractModel):
    _name = 'bpmn.node.type.registry'
    def _get_node_types(self):
        """收集所有已註冊節點型別；擴充模組 _inherit 此模型 super() 後追加"""
        return BASE_NODE_TYPES
```

---

## 3. 擴充模組 `dobtor_approval`（BPM 簽核引擎）

### 3.1 定位
- `depends = ['dobtor_bpmn', 'mail', 'hr']`
- 自己的頂層選單 **「簽核流程 (Approval Workflows)」**，與基礎「流程設計圖」分開。
- 把基礎的純設計圖**載入並延伸**為可執行流程，疊上 §DESIGN.md 全部執行能力（角色解析、Action 閘門、token、mail.activity、加簽/代理…）。
- 向基礎編輯器**註冊執行專屬節點型別**（簽核任務、Odoo 動作、條件閘門…）。

### 3.2 可執行流程模型 `bpmn.executable.process`
```python
class BpmnExecutableProcess(models.Model):
    _name = 'bpmn.executable.process'
    _description = '可執行簽核流程（執行規格，疊在設計圖之上）'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    # ★ 與基礎設計的關聯（兩種模式）
    source_diagram_id = fields.Many2one('bpmn.diagram', string='來源設計圖')
    link_mode = fields.Selection([
        ('linked', '連動：追蹤來源設計（不可改結構，只加執行規格）'),
        ('forked', '分支：複製來源後獨立延伸（可增刪節點）')],
        default='forked', required=True)

    xml = fields.Text('執行用 XML')   # forked 模式存自己的（含 odoo: 擴充 + 新節點）
                                       # linked 模式為空，渲染時即時合併 source + overlay
    # 執行 overlay：以 bpmn element id 為鍵的逐節點執行規格（linked 模式核心）
    node_config_ids = fields.One2many('bpmn.node.config', 'process_id')
    # 其餘執行能力（角色/閘門/實例…）沿用 DESIGN.md
    role_ids = fields.One2many('bpmn.role', 'process_id')
    gate_ids = fields.One2many('bpmn.action.gate', 'process_id')

    def action_pull_from_source(self):
        """從來源設計圖重新拉取結構（linked），或 diff 提示（forked）"""

class BpmnNodeConfig(models.Model):
    _name = 'bpmn.node.config'
    process_id = fields.Many2one('bpmn.executable.process', ondelete='cascade')
    bpmn_element_id = fields.Char(required=True)   # 對應設計圖中的元素 id
    role_id = fields.Many2one('bpmn.role')
    approval_mode = fields.Selection([...])
    server_action_id = fields.Many2one('ir.actions.server')
    # …執行規格，全部 keyed by 設計圖的 element id
```

### 3.3 兩種延伸模式（核心設計）
| 模式 | 結構來源 | 執行規格存哪 | 適用 | 設計圖改了會怎樣 |
|------|---------|------------|------|----------------|
| **linked 連動** | 即時讀 `source_diagram_id.xml` | `node_config_ids`（overlay，keyed by element id） | 設計圖是 single source of truth，執行只是「貼規格」 | 設計圖更新 → 執行流程結構同步；新節點需補 config |
| **forked 分支** | 複製來源 XML 到自己的 `xml`，可增刪節點 | 直接寫進自己的 `xml`（`odoo:` 擴充屬性） | 需要在設計外「增加流程節點」、或獨立演進 | 與來源脫鉤；提供 `action_pull_from_source` 做 diff 合併 |

> **「規格分離」的精髓 = linked 模式**：基礎設計圖只描述「流程長什麼樣」（純 BPMN/DMN），擴充的 `node_config` 才描述「每個節點怎麼執行」（角色/閘門）。渲染時把 overlay 疊到設計圖上 → 完全分離又能合一呈現。

---

## 4. 「擴充可向基礎增加流程節點」的註冊機制 ★

擴充模組要能在**基礎編輯器**裡多出「簽核任務」「Odoo 動作」等積木，需雙端註冊：

### 4.1 前端 JS 註冊表（調色盤 / 屬性面板 / element-template）
```javascript
// dobtor_bpmn 提供
export const nodeTypeRegistry = {
    types: [],
    register(def) { this.types.push(def); },   // 擴充呼叫
    all() { return this.types; },
};
// 基礎註冊標準元素
nodeTypeRegistry.register({ id: 'bpmn:Task', group: 'standard', ... });

// dobtor_approval（擴充）載入時註冊執行節點
import { nodeTypeRegistry } from "@dobtor_bpmn/registry/node_type_registry";
nodeTypeRegistry.register({
    id: 'odoo:approvalTask', label: '簽核任務', group: 'odoo',
    appliesTo: 'bpmn:UserTask', moddle: 'odoo:roleRef',
    template: APPROVAL_TASK_ELEMENT_TEMPLATE,   // element-template JSON
    propertiesProvider: odooApprovalProps,      // 屬性面板 RPC 動態選項
});
```
- 基礎的 `palette_provider` / `properties_registry` **讀 registry 動態渲染** → 裝了擴充就「長出」執行節點；沒裝就只有標準元素。

### 4.2 後端 Python 註冊（moddle 擴充 + 解析）
```python
# 擴充 _inherit 基礎的註冊抽象模型，super() 後追加
class BpmnNodeTypeRegistry(models.AbstractModel):
    _inherit = 'bpmn.node.type.registry'
    def _get_node_types(self):
        types = super()._get_node_types()
        types += [APPROVAL_TASK, ODOO_ACTION_TASK, ...]   # 擴充節點
        return types
```
- `odoo:` moddle 命名空間由基礎宣告，擴充往其中加屬性 → 設計圖 XML 能合法承載擴充節點。

### 4.3 隔離保證
- 基礎不認識任何擴充節點的「執行意義」，只認得它是個合法 BPMN 元素（有 `odoo:` 擴充屬性）。
- 拔掉擴充模組 → 設計圖仍可在基礎開啟（擴充屬性被當未知 extensionElements 保留/略過），不會壞檔。

---

## 5. 基礎設計圖的三大用途（呼應你的需求）

| 用途 (`purpose`) | 內容 | 誰用 | 後續去向 |
|------------------|------|------|---------|
| **documentation（既有 Odoo 模組流程記錄）** | 用 BPMN/DMN 把 `sale`/`purchase`/`account` 等**原生模組的實際流程**畫出來（as-is），當技術文件/教育訓練/交接 | 顧問、IT | 可升級為 `executable_src` 給擴充掛簽核 |
| **blueprint（客戶專案規格藍圖）** | 客戶 Odoo 開發案**尚未實作**的流程設計（to-be），當**規格書的流程章節**、與客戶確認範圍 | 售前、PM、架構師 | 開發完成後對照驗收；或衍生為可執行流程 |
| **executable_src（執行來源）** | 確定要上線簽核的設計，標記為可被擴充衍生 | 設計師 | 擴充以 linked/forked 載入 → 加執行規格 → 發佈 |
| **template（樣板）** | 通用流程樣板庫 | 全體 | 一鍵套用為新設計圖 |

> **規格書對應**：規格書「流程設計」章節 = 基礎模組產出的 `blueprint` 設計圖（純流程，客戶看得懂）；「簽核執行規格」章節 = 擴充模組的執行規格（角色/閘門/SLA）。**兩章節對應兩模組，互不污染。**

### 5.1 工作流：從規格藍圖到上線
```
基礎模組：畫 blueprint 設計圖（純 BPMN/DMN，客戶確認規格）
   │  （專案開發 Odoo 模組…）
   ▼
標記 purpose = executable_src（定版 frozen）
   │
   ▼
擴充模組：bpmn.executable.process 載入該設計（linked/forked）
   │  ・linked：只貼 node_config（角色/閘門）
   │  ・forked：再增加簽核/動作節點
   ▼
發佈 → 可執行簽核流程上線（DESIGN.md 引擎接手）
```

---

## 6. 與既有規劃（DESIGN / SELF_SERVICE / TIERS）的調和

| 既有規劃 | 原歸屬 | 拆分後歸屬 |
|----------|--------|-----------|
| bpmn-js / dmn-js 純編輯器、modeler OWL | dobtor_approval | **→ 基礎 `dobtor_bpmn`** |
| 設計圖儲存、版本、SVG | dobtor_approval | **→ 基礎** |
| 角色解析、Action 閘門、token 執行、mail.activity 橋接、加簽/代理 | dobtor_approval / _activity | 擴充 `dobtor_approval`（不變） |
| 元素樣板積木、屬性面板 RPC、精靈、lint、沙箱（自助設計器） | DESIGN_SELF_SERVICE | **拆兩半**：①「動態調色盤/面板/registry 機制」屬基礎；②「簽核專屬積木/角色 RPC/lint Odoo 規則/沙箱解析」屬擴充 |
| DMN 純編輯（dmn-js） | （原 _dmn） | **→ 基礎 `dobtor_bpmn`**（純 DMN 編輯）；DMN 求值執行 → `dobtor_approval`（T5 開關） |
| 代簽核/加簽（原 _activity） | （原 _activity） | **→ `dobtor_approval`**（能力開關，不再獨立模組） |
| T0–T6 能力分級開關 | DESIGN_PROGRESSIVE_TIERS | 開關屬 `dobtor_approval`（執行能力）；基礎只負責「能畫什麼元素」由 registry 決定 |

> **修訂後模組清單（僅 2 模組）**：
> - `dobtor_bpmn`（基礎·純設計）← 可單獨安裝
> - `dobtor_approval`（簽核·BPM 引擎，含代簽核/加簽/DMN 求值，能力開關分級）← 依賴 `dobtor_bpmn` + `dobtor_mail_activity`

---

## 7. 依賴與發佈策略

```
dobtor_bpmn   (無業務依賴，可單獨安裝＝純設計工具)
   ▲
   │ depends
dobtor_approval   (BPM 引擎，含代簽核/加簽/DMN 求值；亦 depends dobtor_mail_activity)
```
- **基礎可單獨販售/部署**：純流程設計與文件工具（畫 Odoo 模組流程、畫客戶規格藍圖），不需要簽核引擎。
- **簽核按需加裝**：要簽核才裝 `dobtor_approval`；代簽核/加簽/DMN 等進階能力以模組內 **T0–T6 開關**（預設關閉）按需開啟，不需再裝額外模組。

---

## 8. Roadmap 調整（基礎優先）

| 波 | 模組 | 內容 |
|----|------|------|
| **波 0（新增·最先）** | `dobtor_bpmn` | bpmn-js + dmn-js 純 modeler、`bpmn.diagram` 庫、用途分類、版本、節點型別 registry、選單「流程設計圖」 |
| 波 1 | `dobtor_approval` | 載入基礎設計（linked/forked）、node_config overlay、註冊簽核節點、角色解析、基本執行 |
| 波 2 | `dobtor_approval` | Action 閘門、token、mail.activity 橋接（DESIGN.md M4–M5） |
| 波 3 | `dobtor_approval`（開關） | 代簽核、個人化加簽（T3 能力開關） |
| 波 4 | `dobtor_approval`（開關） | DMN 求值執行、綁 gateway（T5 能力開關） |
| 波 5 | `dobtor_approval`（開關） | T5 進階引擎、治理、自助設計器強化 |

> **先交付基礎模組**：它本身就能用來「記錄既有 Odoo 模組流程」與「畫客戶專案規格藍圖」，立即產生價值，且不必等簽核引擎完成。

---

## 9. 關鍵設計決策摘要

1. **基礎 = 純設計（demo.bpmn.io 等價）**，無執行；擴充 = 載入基礎再疊執行規格。
2. **兩條延伸路徑**：`linked`（規格 overlay，真正的設計/執行分離）與 `forked`（複製後可增節點）。
3. **節點型別 registry**：擴充透過前端 JS registry + 後端 `_inherit` 雙端註冊，向基礎編輯器「增加流程節點」，且拔掉擴充不壞檔。
4. **用途分類 `purpose`**：documentation（as-is）/ blueprint（to-be 規格）/ executable_src / template，讓基礎同時是「文件工具」與「執行來源」。
5. **規格書對應**：流程設計章節 ↔ 基礎模組；簽核執行章節 ↔ 擴充模組，文件與程式碼結構一致。
6. **基礎可獨立成立**：單裝即為流程設計/規格工具，擴充按需加裝。
