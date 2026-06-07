# Odoo 18 BPMN 簽核流程管理模組 — 完整設計建議規劃

> 文件版本：v1.0 ｜ 目標 Odoo 版本：18.0 ｜ 撰寫日：2026-06-06
> 整合對象：`dobtor_mail_activity`（Advanced Activity Management 18.0.1.0.0）
> 視覺編輯器：[bpmn-io / bpmn-js](https://github.com/bpmn-io)

---

## 0. 設計理念 — 借鏡國內外廠商優點

| 來源 | 借鏡的優點 | 落地在本模組的作法 |
|------|-----------|-------------------|
| **Camunda 8 (Zeebe)** | BPMN 2.0 token-based 可執行引擎、DMN 決策、流程與執行解耦 | 流程定義存 BPMN 2.0 XML；自建輕量 token 執行引擎（`bpmn.process.instance` + `bpmn.token`），節點解析與執行分離 |
| **華苓 Agentflow** | 組織職權 (OAB) 解析、會簽/加簽/代理、貼合台灣簽核文化 | 「簽核人解析引擎」與 HR `parent_id` / `department_id.manager_id` 動態綁定，支援會簽、加簽、職務代理人 |
| **叡揚 Vitals ESP** | 與既有業務模組（KM/表單）深度整合、稽核軌跡 | 流程節點直接綁定 Odoo 既有 `ir.actions`，全程稽核軌跡寫入 `assignment_history` 風格的歷史模型 |
| **Pega / Appian** | Model-driven、低碼、規則化例外處理 | 流程、角色、例外規則皆「設定而非寫死」；個人化加簽 = 執行期規則 (runtime rule) |
| **Odoo Studio Approvals** | 按鈕級簽核閘門 (approval gate)、攔截後放行 | 「Action 介入」採 approval-gate 模式：攔截 → 進 BPMN → 完成後回放原 action |

**核心定位**：本模組 = **BPMN 流程定義器** +（**簽核人解析引擎** + **Action 介入閘門** + **執行 Token 引擎**），人機互動一律下放給 `dobtor_mail_activity` 的 `mail.activity` 承載。

---

## 1. 整體架構分層

```
┌──────────────────────────────────────────────────────────────────┐
│  L5 視覺層   bpmn-js 編輯器 (OWL component) + 角色/節點屬性面板        │
├──────────────────────────────────────────────────────────────────┤
│  L4 定義層   bpmn.process.definition (BPMN XML)                      │
│             bpmn.node (解析後的節點) / bpmn.role / bpmn.transition   │
├──────────────────────────────────────────────────────────────────┤
│  L3 解析層   簽核人解析引擎 (Approver Resolver)                       │
│             ├─ HR 動態關係 (上級、部門經理、職務代理)                  │
│             └─ DMN-lite 條件路由 (decision gateway)                  │
├──────────────────────────────────────────────────────────────────┤
│  L2 執行層   bpmn.process.instance + bpmn.token (token 引擎)         │
│             ├─ 節點執行器 (UserTask/ServiceTask/Gateway)            │
│             └─ 個人化例外規則引擎 (runtime escalation/加簽)           │
├──────────────────────────────────────────────────────────────────┤
│  L1 整合層   ├─ Action 介入閘門 (approval gate, 攔截→回放)            │
│             ├─ dobtor_mail_activity 橋接 (簽核活動/代簽核)            │
│             └─ Odoo ir.actions 掃描器                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 模組拆分（僅 2 模組，子功能以開關控制）

> 命名：**基礎（簽核引擎＋編輯器核心）= `dobtor_approval`；擴充（流程設計圖庫）= `dobtor_bpmn`**。
> **⚠️ 依賴已反轉（2026-06-07，見 `DESIGN_MODULE_SPLIT.md` v2.0）**：`dobtor_approval` 內建 BPMN 編輯器核心、成為自足基礎（可獨立設計＋執行簽核流程）；`dobtor_bpmn` 退為疊在其上的設計圖庫、depends `dobtor_approval`。
> **僅 2 模組，不再分子模組**：原規劃的 `_activity`（代簽核/加簽）與 `_dmn`（DMN 求值）**併入 `dobtor_approval`**，改用模組內「能力開關（T0–T6，預設關閉）」控制啟用（見 `DESIGN_PROGRESSIVE_TIERS.md`）。
> 本文件描述的「角色解析、Action 介入、token 執行、代簽核、DMN 求值」皆屬 **簽核 `dobtor_approval`**。

| 模組 | 角色 | 依賴 | 內容 |
|------|------|------|------|
| `dobtor_approval` (簽核·BPM 引擎＋編輯器核心) | 基礎 | `web, mail, hr` | 內建 BPMN/DMN 編輯器核心（bpmn-js/dmn-js、節點 registry、process_editor）＋角色解析、token 執行、Action 介入、簽核活動橋接、**代簽核/加簽**、**DMN 求值**——全部以能力開關分級啟用；**可獨立設計＋執行** |
| `dobtor_bpmn` (流程設計圖庫) | 擴充 | `dobtor_approval` | `bpmn.diagram` 設計圖庫、版本、用途分類；重用核心編輯器；可 forked 把設計圖交給簽核引擎；**無執行語意** |

> 拆分理由：**簽核才是主產品** —— 編輯器核心與引擎同住自足的 `dobtor_approval`，裝它就能設計＋執行簽核流程，所有執行能力（含代簽核、DMN）用開關（由簡入深）取代「多模組」複雜度；`dobtor_bpmn` 退為「通用流程文件/規格圖庫」加值層，可把設計圖 forked 交給簽核引擎。

> ### 🚫 非目標（Out of Scope）
> - **不提供任何表單設計器 / 表單建構器（form builder）。** 本專案走「**動作/單據中心**」而非「表單中心」：資料輸入一律使用 **Odoo 原生 form view / 既有單據**；簽核只在既有畫面與按鈕上掛閘門，不自造表單。
> - 兩模組只設計 **流程（BPMN）與決策（DMN）**，不設計表單。需要新欄位/新畫面時，循 Odoo 標準模型與視圖開發，不在本專案範圍。

---

## 3. 核心資料模型設計

### 3.1 流程定義 `bpmn.process.definition`
```python
class BpmnProcessDefinition(models.Model):
    _name = 'bpmn.process.definition'
    _description = 'BPMN 流程定義'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True)              # 流程代碼，攔截時比對用
    version = fields.Integer(default=1, readonly=True)  # 版本控管：發佈即凍結
    state = fields.Selection([
        ('draft', '草稿'), ('published', '已發佈'), ('archived', '封存')],
        default='draft', tracking=True)
    bpmn_xml = fields.Text('BPMN 2.0 XML')         # bpmn-js 來源
    bpmn_svg = fields.Text('流程縮圖 SVG')          # 預覽用
    node_ids = fields.One2many('bpmn.node', 'definition_id')
    transition_ids = fields.One2many('bpmn.transition', 'definition_id')
    role_ids = fields.One2many('bpmn.role', 'definition_id')

    # Action 介入綁定（一個流程可掛在多個 action gate 上）
    gate_ids = fields.One2many('bpmn.action.gate', 'definition_id')

    # 發佈 = 解析 XML → 重建 node/transition/role；版本+1 並凍結舊版實例
    def action_publish(self): ...
```
**版本策略**：發佈後 XML 凍結，新增節點需發佈新版本；執行中的舊實例仍走舊版定義（`instance.definition_version`），避免「改流程把進行中的簽核改壞」。

### 3.2 節點 `bpmn.node`（解析 BPMN XML 後產生）
```python
class BpmnNode(models.Model):
    _name = 'bpmn.node'
    definition_id = fields.Many2one('bpmn.process.definition', ondelete='cascade')
    bpmn_id = fields.Char(required=True)   # BPMN element id（與 XML 對應）
    name = fields.Char()
    node_type = fields.Selection([
        ('start', '開始'), ('end', '結束'),
        ('user_task', '人工簽核'),          # → 產生 mail.activity
        ('service_task', '系統動作'),        # → 執行 Odoo action / server action
        ('exclusive_gw', '互斥閘道(XOR)'),   # 條件擇一
        ('parallel_gw', '並行閘道(AND)'),    # 會簽 / 平行
        ('inclusive_gw', '包容閘道(OR)'),
    ])
    # UserTask 專用：簽核人解析
    role_id = fields.Many2one('bpmn.role')
    approval_mode = fields.Selection([
        ('any', '任一人核准即過'),
        ('all', '全部核准(會簽)'),
        ('sequential', '依序簽核')], default='any')
    allow_escalation = fields.Boolean('允許往上加簽', default=True)  # 個人化例外開關
    # ServiceTask 專用：綁定 Odoo action
    server_action_id = fields.Many2one('ir.actions.server')
    bound_method = fields.Char()   # 或直接綁 model 上的 method 名
```

### 3.3 角色 / 簽核人解析來源 `bpmn.role`（**最關鍵的 HR 整合**）
```python
class BpmnRole(models.Model):
    _name = 'bpmn.role'
    definition_id = fields.Many2one('bpmn.process.definition', ondelete='cascade')
    name = fields.Char(required=True)          # 例：「直屬主管」「部門經理」「財務長」
    resolver_type = fields.Selection([
        ('direct_manager',   '申請人直屬主管 (employee.parent_id)'),
        ('manager_level',    '往上第 N 級主管'),        # level 欄位
        ('department_manager','申請人部門經理'),         # department_id.manager_id
        ('department_specific','指定部門之經理'),        # specific_department_id
        ('job_position',     '指定職位'),               # job_id
        ('specific_user',    '指定使用者'),             # user_ids
        ('group',            '指定權限群組'),            # group_id 全員
        ('field_on_record',  '取單據上的欄位'),         # 例：sale.order.user_id
        ('expression',       'Python 運算式'),          # 進階：safe_eval
    ], required=True)

    level = fields.Integer(default=1)          # manager_level 用
    specific_department_id = fields.Many2one('hr.department')
    job_id = fields.Many2one('hr.job')
    user_ids = fields.Many2many('res.users')
    group_id = fields.Many2one('res.groups')
    record_field = fields.Char()               # field_on_record 用，如 'user_id'
    expression = fields.Text()                 # expression 用

    # 職務代理：解析出的人若不在，自動轉代理人
    apply_substitute = fields.Boolean('啟用職務代理人', default=True)
```

**解析引擎核心方法**（`bpmn.role.resolve()`）：
```python
def resolve(self, instance):
    """回傳 res.users recordset（可能多人 = 會簽）"""
    applicant = instance.applicant_user_id
    employee = applicant.employee_id
    if self.resolver_type == 'direct_manager':
        users = employee.parent_id.user_id
    elif self.resolver_type == 'manager_level':
        emp = employee
        for _ in range(self.level):
            emp = emp.parent_id          # 往上爬 N 級
        users = emp.user_id
    elif self.resolver_type == 'department_manager':
        users = employee.department_id.manager_id.user_id
    elif self.resolver_type == 'field_on_record':
        users = instance.res_record[self.record_field]  # 動態取單據欄位
    # ... 其餘略
    # 職務代理人替換
    if self.apply_substitute:
        users = self._apply_substitutes(users, instance)
    return users
```
> **多變化選擇**正是來自 `resolver_type` 的組合 + `level` + 單據欄位 + 運算式，把「華苓 OAB」那種彈性用 Odoo HR 既有關係 (`hr.employee.parent_id`、`hr.department.manager_id`、`hr.job`) 表達出來。

### 3.4 職務代理人 `bpmn.delegation`（新建，補 `dobtor_mail_activity` 沒有的部分）
```python
class BpmnDelegation(models.Model):
    _name = 'bpmn.delegation'
    _description = '職務代理 / 代簽核授權'
    delegator_id = fields.Many2one('res.users', '原簽核人', required=True)
    delegate_id  = fields.Many2one('res.users', '代理人', required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    definition_ids = fields.Many2many('bpmn.process.definition',
        help='留空=所有流程；指定=僅這些流程代理')
    active = fields.Boolean(default=True)
    # 解析期間若 delegator 正好在代理區間 → 簽核活動同時/改派給 delegate
```

### 3.5 執行期：流程實例與 Token
```python
class BpmnProcessInstance(models.Model):
    _name = 'bpmn.process.instance'
    _inherit = ['mail.thread']
    definition_id = fields.Many2one('bpmn.process.definition', required=True)
    definition_version = fields.Integer()       # 凍結走哪一版定義
    state = fields.Selection([
        ('running','進行中'),('approved','核准完成'),
        ('rejected','駁回'),('cancelled','取消')], default='running', tracking=True)
    applicant_user_id = fields.Many2one('res.users', '申請人')
    res_model = fields.Char()                    # 介入的單據模型
    res_id = fields.Integer()                    # 介入的單據 id
    res_record = fields.Reference(...)           # 動態取單據
    token_ids = fields.One2many('bpmn.token', 'instance_id')
    activity_link_ids = fields.One2many('bpmn.activity.link', 'instance_id')
    # 攔截放行：流程完成後要回放的原 action
    pending_action = fields.Char()               # JSON: {model, method, args}

class BpmnToken(models.Model):
    _name = 'bpmn.token'
    instance_id = fields.Many2one('bpmn.process.instance', ondelete='cascade')
    node_id = fields.Many2one('bpmn.node')
    state = fields.Selection([('active','活躍'),('consumed','已消耗')])
    # token 抵達 user_task → 產生 mail.activity；活動完成 → 推進 token
```

### 3.6 BPMN ↔ Activity 橋接 `bpmn.activity.link`
```python
class BpmnActivityLink(models.Model):
    _name = 'bpmn.activity.link'
    instance_id = fields.Many2one('bpmn.process.instance', ondelete='cascade')
    token_id = fields.Many2one('bpmn.token')
    node_id = fields.Many2one('bpmn.node')
    activity_id = fields.Many2one('mail.activity', ondelete='set null')
    approver_user_id = fields.Many2one('res.users')
    decision = fields.Selection([
        ('pending','待簽'),('approved','核准'),
        ('rejected','駁回'),('escalated','上呈加簽'),
        ('delegated','已代簽')])
    decided_by = fields.Many2one('res.users')    # 實際簽核人（可能是代理人）
    feedback = fields.Text()
```

---

## 4. bpmn-js 視覺編輯器整合

### 4.1 前端資產
- 透過 npm 取 `bpmn-js`（Modeler）打包，或放 `static/lib/bpmn-js/`，以 OWL 元件包裝。
- OWL 元件 `BpmnModeler`（`static/src/bpmn_modeler/`）：
  - `onMounted`：`new BpmnJS({ container })`，載入 `record.data.bpmn_xml`。
  - 自訂 **Properties Panel** 擴充：點節點 → 右側面板顯示 Odoo 專屬屬性（角色解析、approval_mode、綁定 action）。這是 bpmn-js 的 `PropertiesPanel` extension 機制。
  - 儲存：`modeler.saveXML()` + `saveSVG()` → 寫回 `bpmn_xml` / `bpmn_svg`。
- 自訂 **Palette / Moddle Extension**：定義命名空間 `odoo:` 擴充屬性（`odoo:roleRef`、`odoo:approvalMode`、`odoo:serverAction`、`odoo:allowEscalation`），存進 BPMN XML 的 `extensionElements`。

### 4.2 後端解析
`action_publish()` 用 Python `lxml` 解析 BPMN XML：
- `bpmn:userTask` → `bpmn.node(node_type='user_task')`，讀 `odoo:roleRef` → 連 `bpmn.role`。
- `bpmn:serviceTask` → 讀 `odoo:serverAction` → 連 `ir.actions.server`。
- `bpmn:sequenceFlow` → `bpmn.transition`，條件式存 `conditionExpression`。
- `bpmn:exclusiveGateway` 等 → gateway 節點。

---

## 5. Action 介入機制（攔截 → BPMN → 回放）★技術核心

借鏡 **Odoo Studio Approvals 的 approval-gate 模式**，但用 BPMN 取代簡單規則。

### 5.1 Action 掃描器 `bpmn.action.gate`
```python
class BpmnActionGate(models.Model):
    _name = 'bpmn.action.gate'
    _description = 'Action 簽核閘門'
    name = fields.Char()
    model_id = fields.Many2one('ir.model', required=True)   # 選 Odoo 既有模組模型
    method_name = fields.Char(required=True)   # 攔截的方法/按鈕，如 'action_confirm'
    definition_id = fields.Many2one('bpmn.process.definition', required=True)
    condition = fields.Text()    # 觸發條件 domain/expression，如金額 > 10000 才簽
    active = fields.Boolean(default=True)
```

**掃描器 UI**：選定 model → 後端列出可攔截的方法供勾選。來源：
1. **按鈕方法**：解析該 model 的 form view，抓 `<button type="object" name="...">`。
2. **Server actions**：`ir.actions.server` where `model_id = 選定模型`。
3. **已知白名單**：`action_confirm` / `action_post` / `button_approve` 等常見方法。

### 5.2 攔截實作（兩種，建議併用）

**(A) JS 前端攔截（按鈕級，UX 最佳，推 studio 模式）**
- Patch `web` 的按鈕點擊：表單按鈕被按 → 先 RPC `check_bpmn_gate(model, method, res_id)`。
- 若該 (model, method) 有 gate 且 condition 成立且**尚未核准** → 攔下，不執行原方法，改：
  - `bpmn.process.instance.start(definition, res_model, res_id, applicant)`，並記 `pending_action = {model, method, args}`。
  - 提示「已送出簽核」。
- 若**已有核准完成的實例** → 放行，正常執行原方法。

**(B) Python 後端攔截（保險層，防 API/直呼）**
- 對受管方法做 override（用 `_register_hook` 動態包裝，或在常見基底方法如 `action_confirm` 上加 mixin）：
```python
def _bpmn_guard(self, method_name):
    gate = self.env['bpmn.action.gate']._match(self._name, method_name, self)
    if gate and not self._bpmn_already_approved(gate):
        self.env['bpmn.process.instance'].start(gate, self)
        raise BpmnPendingApproval()   # 阻止原動作，提示送簽中
```

### 5.3 回放（走完 BPMN 再走回 Odoo）
- 流程實例 `state → approved` 時，執行 `_replay_pending_action()`：
```python
def _replay_pending_action(self):
    data = json.loads(self.pending_action)
    record = self.env[data['model']].browse(data['res_id'])
    # 用 context 標記放行，避免再次被攔截
    getattr(record.with_context(bpmn_approved=True), data['method'])()
```
- 攔截層檢查 `if self.env.context.get('bpmn_approved'): return super()` → 直接放行，閉環完成。
- **駁回**：`state → rejected`，不回放，並把單據退回原狀態（可選綁一個「駁回 server action」）。

> 這就是你要的「對 action 以流程介入，走完 BPMN 後再走回 odoo」的完整閉環：**攔截 → 起實例 → 簽核 → 核准回放原 action / 駁回不回放**。

---

## 6. 與 `dobtor_mail_activity` 整合 — 簽核活動 + 代簽核

`dobtor_mail_activity` 已具備：活動生命週期、改派 (`reassign`)、轉移 (`transfer`)、完成精靈 (`action_done_wizard`)、`assignment_history`。我們**疊加**而非重寫。

### 6.1 token 抵達 user_task → 產生簽核活動
```python
def _enter_user_task(self, token):
    node = token.node_id
    approvers = node.role_id.resolve(self)          # 解析簽核人(可多人)
    approvers = self._apply_delegation(approvers)   # 代簽核：套職務代理
    for user in approvers:
        activity = self.env['mail.activity'].create({
            'res_model_id': ..., 'res_id': self.res_id,  # 掛在原單據上
            'activity_type_id': self.env.ref('dobtor_approval.activity_type_approval').id,
            'user_id': user.id,
            'summary': f'[簽核] {node.name}',
            'date_deadline': ...,
        })
        self.env['bpmn.activity.link'].create({
            'instance_id': self.id, 'token_id': token.id, 'node_id': node.id,
            'activity_id': activity.id, 'approver_user_id': user.id,
            'decision': 'pending'})
```
- 新增一個 `mail.activity.type`「BPMN 簽核」，用其 `default_description` / `notify_template_id`（模組既有欄位）客製通知。

### 6.2 簽核動作（核准 / 駁回）
- 簽核人在 `dobtor_mail_activity` 的活動 Kanban / 完成精靈裡操作。
- 我們 patch `mail.activity._action_done()`（模組已 override 此方法，archive + chaining），加 hook：
```python
def _action_done(self, feedback=False, attachment_ids=None):
    res = super()._action_done(feedback, attachment_ids)
    link = self.env['bpmn.activity.link'].search([('activity_id','in',self.ids)])
    if link:
        link._on_activity_done(feedback)   # → 推進 token
    return res
```
- 駁回則提供獨立按鈕（活動表單上加 `action_bpmn_reject`），設 `decision='rejected'` → token 走駁回路徑。
- `approval_mode`：`any` 任一核准即消活動其他簽、推進；`all` 等全簽；`sequential` 依序產生下一張。

### 6.3 代簽核（職務代理）
- 簽核人解析時即套 `bpmn.delegation`：原簽核人在代理區間 → 活動 `user_id` 直接給代理人，`bpmn.activity.link.decision='delegated'`、`decided_by=代理人`，並在 `assignment_history` 留軌跡（模組既有機制）。
- 亦支援「臨時代簽」：簽核人用模組既有 `action_reassign_activity` 改派 → 我們監聽 `assignment_history` 同步更新 `bpmn.activity.link.approver_user_id`。

---

## 7. 個人化簽核例外 — 主管自主加簽 / 上呈 ★你的關鍵情境

情境：流程只設計到二級主管，但二級主管認為事件特殊，要自行往上送一級主管。

### 7.1 設計：執行期動態加簽 (runtime ad-hoc escalation)
- `bpmn.node.allow_escalation = True` 時，該簽核活動表單**多一顆按鈕「上呈加簽」**。
- 按下 → 開 wizard `bpmn.escalate.wizard`：
```python
class BpmnEscalateWizard(models.TransientModel):
    _name = 'bpmn.escalate.wizard'
    link_id = fields.Many2one('bpmn.activity.link')
    target_type = fields.Selection([
        ('direct_manager','送我的直屬主管'),
        ('specific_user','指定人員'),
        ('role','指定角色')], default='direct_manager')
    target_user_id = fields.Many2one('res.users')
    return_after = fields.Boolean('加簽後退回我續簽', default=True)
    reason = fields.Text(required=True)
```
- 行為：在**不改流程定義**的前提下，於該 token 上「插入一個臨時 user_task」：
  - `return_after=True`（加簽後回我）：產生新活動給上級 → 上級核准 → **回到原二級主管**再次確認 → 才推進。等於 token 暫停、嵌入子簽核。
  - `return_after=False`（直接上呈）：原二級主管活動關閉，token 改流向上級，上級核准後續走原流程。
- `bpmn.activity.link.decision='escalated'`，並串一條 `parent_link_id` 形成加簽鏈，稽核可追。

### 7.2 為何用「執行期規則」而非改 BPMN 圖
- 借鏡 Pega/Appian 的 **ad-hoc routing**：把「制度化流程」與「個案彈性」分離。BPMN 圖保持乾淨（只畫到二級），例外用 runtime rule 處理，不污染流程版本。這正是台灣簽核「加簽/職代」文化最需要、而國際純 BPMN 引擎較弱的點 → 我們補上。

### 7.3 制度化的條件加簽（選配，DMN）
- 若某些「例外」其實有規律（如金額 > 100萬一律加簽財務長），則用 `exclusive_gateway` + 條件，或啟用 `dobtor_approval` 的 **DMN 求值能力（T5 開關）** 以決策表處理，免得靠人工判斷。

---

## 8. 安全與權限

| 群組 | 權限 |
|------|------|
| `group_bpmn_user` | 看自己參與的流程實例、簽自己的活動 |
| `group_bpmn_designer` | 設計/發佈流程定義、設定 action gate、角色 |
| `group_bpmn_manager` | 看所有實例、強制終止、改派、稽核 |

- Record rule：實例只有申請人、簽核人（含代理）、designer/manager 可見。
- **沿用 `dobtor_mail_activity` 既有 rule**：簽核活動本身受其 `mail_activity_rule_*` 管控，不重造。
- `expression` / `condition` 一律走 `safe_eval`，白名單變數（`record`, `user`, `applicant`），禁任意 import。
- Action gate 攔截需防權限繞過：後端攔截 (5.2-B) 是安全底線，前端 (5.2-A) 只是 UX。

---

## 9. 開發 Roadmap（階段交付）

| 階段 | 內容 | 可交付驗證 |
|------|------|-----------|
| **M1 定義與編輯器** | `dobtor_approval` 骨架、bpmn-js OWL 元件、定義/節點/角色模型、`action_publish` XML 解析 | 能畫流程、存 XML、發佈解析出 node/role |
| **M2 解析引擎** | 簽核人 resolver（HR 各 resolver_type）、職務代理模型 | 給定申請人能正確算出各角色簽核人 |
| **M3 執行引擎** | instance + token、user_task→activity、gateway 路由 | 手動起實例能跑完一條簽核鏈 |
| **M4 Activity 橋接** | `dobtor_approval` 簽核活動橋接、`_action_done` hook、核准/駁回、會簽 (`all/any/sequential`) | 簽核人在活動介面完成簽核能推進流程 |
| **M5 Action 介入** | gate 掃描 UI、前端按鈕攔截 + 後端 guard、回放閉環 | 按 `sale.order.action_confirm` → 進簽核 → 核准後真的確認訂單 |
| **M6 個人化例外** | escalate wizard、加簽鏈、代簽核軌跡 | 二級主管能自主上呈一級主管並回簽 |
| **M7 強化** | DMN 決策表(選配)、流程監控儀表板、稽核報表、SLA 逾時提醒 | 監控、報表 |

---

## 10. 技術風險與對策

| 風險 | 對策 |
|------|------|
| Action 攔截覆蓋面（按鈕/API/server action 多入口） | 前端攔 UX + 後端 guard 雙層；guard 用 `_register_hook` 統一包裝受管方法 |
| 流程改版影響進行中實例 | 版本凍結：實例綁 `definition_version`，舊實例走舊定義 |
| 簽核人解析爬 `parent_id` 出現斷鏈/無 user | resolver 回傳空時走 fallback（指定 manager 群組）+ 設計期校驗告警 |
| bpmn-js 與 Odoo 18 OWL/asset 打包相容 | 以 OWL 包裝、走 `web.assets_backend`；bpmn-js 為純前端 lib 風險低 |
| 並行會簽 token 競態（同時核准） | `bpmn.token` 狀態機 + 資料庫鎖（`for update`）序列化推進 |
| 個人化加簽造成流程失控/無限上呈 | 加簽鏈限制最大深度；`bpmn.delegation` 與加簽皆留稽核軌跡 |

---

## 11. 與既有 `dobtor_mail_activity` 的明確分工

| 能力 | 由誰負責 |
|------|---------|
| 流程定義、BPMN 圖、版本 | `dobtor_approval`（新） |
| 簽核人「是誰」的解析 | `dobtor_approval`（新，HR 整合） |
| 流程推進、token、閘道 | `dobtor_approval`（新） |
| Action 攔截與回放 | `dobtor_approval`（新） |
| 簽核「待辦」的承載、Kanban、排程、提醒 | **`dobtor_mail_activity`（既有，直接用）** |
| 改派、轉移、完成精靈、異動歷史 | **`dobtor_mail_activity`（既有，直接用）** |
| 代簽核（職務代理）、個人化加簽 | `dobtor_approval`（代簽核/加簽能力開關，疊加在 activity 之上） |

---

## 附錄 A：關鍵整合點對照（`dobtor_mail_activity` 既有 API）

- 產生簽核活動：`mail.activity.create()`（已處理 target_ref / 預設 note）
- 完成 hook：override `mail.activity._action_done(feedback, attachment_ids)` ← 已被模組 override，需 super 後加鉤
- 改派軌跡：`mail.activity.assignment.history`（代簽核可直接複用）
- 通知客製：`mail.activity.type.default_description / notify_template_id / use_custom_notify`
- 完成精靈：`mail.activity.done.wizard.action_done()`（簽核可走此 UI，或自建駁回按鈕）
