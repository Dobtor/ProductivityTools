# dobtor_approval — 人員自助拖拉建流程（BPMN + DMN 自助設計器）設計

> 文件版本：v1.0 ｜ 撰寫日：2026-06-06 ｜ 目標 Odoo：18.0
> 補強對象：`COMPETITIVE_ANALYSIS.md` 弱項「⚠ 偏設定導向、非公民開發（雷達 2/5）」
> 技術底座：[bpmn.io](https://bpmn.io)（bpmn-js / dmn-js / properties-panel / element-templates / token-simulation / bpmnlint）

---

## 0. 核心認知 — 「自助」≠「把 bpmn.io 嵌進去就好」

直接內嵌 bpmn-js 只給了「**畫圖能力**」，但業務人員（公民開發者）會遇到三道牆：

1. **不懂 BPMN 語意**：什麼是 exclusive gateway？token？sequence flow 條件式怎麼寫？
2. **畫得出但跑不動**：缺結束節點、user_task 沒綁簽核人、gateway 沒設條件 → 發佈即爆。
3. **自助但失控**：員工把流程掛到「財務過帳」按鈕、或建出無限加簽 → 治理災難。

> **本設計的本質 = 在 bpmn-js / dmn-js 原生編輯器之上，疊一層「降門檻（積木化）+ 防呆（即時驗證/沙箱）+ 治理（草稿送審/權限範圍）」的鷹架。**
> 對標 Appian / Power Automate 的公民開發體驗，但長在 Odoo 內、用 bpmn.io 開放標準。

---

## 1. 三級使用者體驗（同一編輯器，不同露出）

| 層級 | 對象 | 編輯器形態 | 能做什麼 |
|------|------|-----------|---------|
| **L1 設定精靈** (Wizard) | 完全不懂 BPMN 的一般員工 | **設定精靈式**（Odoo 原生設定畫面，非設計表單）：第幾關→誰簽→條件，後端自動生成線性 BPMN | 建簡單序簽/會簽流程 |
| **L2 積木模式** (Guided Canvas) | 部門流程負責人（公民開發者） | bpmn-js **受限調色盤 + 元素樣板**，屬性面板只露業務欄位 | 拖拉建中等複雜流程、條件分歧、會簽 |
| **L3 專家模式** (Full Modeler) | 流程設計師 / IT | 完整 bpmn-js + dmn-js + 全屬性面板 | 完整 BPMN/DMN、綁 action gate、resolver 運算式 |

- **同一份 `bpmn_xml`**，三模式可互轉：精靈生成的圖能在積木模式打開續編；積木模式的圖能在專家模式精修。
- 模式由 `bpmn.process.definition.editor_level` + 使用者權限群組決定預設露出。

---

## 2. 技術整合 — bpmn-js / dmn-js 嵌入 Odoo 18 OWL

### 2.1 函式庫載入策略（避開 Odoo asset 打包地雷）
- bpmn.io 官方提供 **預打包 UMD/dist**（`bpmn-modeler.production.min.js`、`dmn-modeler.production.min.js`），含 diagram-js 等所有相依 → **直接放 `static/lib/bpmn-io/`，當一般 script 載入**，不丟進 Odoo 的 ES module 編譯，相容風險最低。
- properties-panel / element-templates / token-simulation / bpmnlint 同樣取 dist 或預先 rollup 成單一 bundle 放 `static/lib/`。
- CSS：bpmn-js / dmn-js / properties-panel 的 `.css` 一併放 `static/lib/` 並加入 `web.assets_backend`。

### 2.2 OWL 包裝元件
```
static/src/designer/
  bpmn_designer.js / .xml      # OWL 元件，掛載 BpmnModeler
  dmn_designer.js / .xml       # OWL 元件，掛載 DmnModeler
  odoo_properties_provider.js  # 自訂屬性面板 provider（接 Odoo RPC）
  odoo_palette_provider.js     # 受限/客製調色盤
  element_templates/*.json     # 元素樣板（積木定義）
  wizard/                      # L1 精靈模式元件
```
```javascript
/** @odoo-module **/
import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class BpmnDesigner extends Component {
    setup() {
        this.canvas = useRef("canvas");
        this.panel = useRef("panel");
        onMounted(async () => {
            // window.BpmnJS 來自 static/lib dist
            this.modeler = new window.BpmnJS({
                container: this.canvas.el,
                propertiesPanel: { parent: this.panel.el },
                additionalModules: [ /* properties, lint, tokenSim, odooProvider */ ],
                moddleExtensions: { odoo: ODOO_MODDLE },   // odoo: 命名空間
                elementTemplates: this.props.templates,
            });
            await this.modeler.importXML(this.props.xml || EMPTY_DIAGRAM);
        });
        onWillUnmount(() => this.modeler?.destroy());
    }
    async save() {
        const { xml } = await this.modeler.saveXML({ format: true });
        const { svg } = await this.modeler.saveSVG();
        await rpc("/web/dataset/call_kw", { /* write bpmn_xml/bpmn_svg */ });
    }
}
```
- 以 OWL field widget 形式掛在 `bpmn.process.definition` form 上（取代 `bpmn_xml` 的純文字欄位）。

### 2.3 Odoo 專屬命名空間（moddle extension）
延續 `DESIGN.md`，自訂 `odoo:` 屬性存進 BPMN XML `extensionElements`：
`odoo:roleRef`、`odoo:approvalMode`、`odoo:allowEscalation`、`odoo:serverAction`、`odoo:decisionRef`（連 DMN）、`odoo:condition`。

---

## 3. 降門檻機制（公民開發的核心）★

### 3.1 元素樣板 Element Templates（積木化）— 最關鍵
利用 bpmn.io 的 **element-templates** 機制，把抽象的 BPMN 元素封裝成「業務看得懂的積木」，屬性面板**只露業務欄位、隱藏 BPMN 技術細節**。

範例：「簽核任務」積木（`static/.../element_templates/approval_task.json`）
```json
{
  "name": "簽核任務",
  "id": "dobtor.approval_task",
  "appliesTo": ["bpmn:UserTask"],
  "icon": { "contents": "data:image/svg+xml,..." },
  "properties": [
    { "label": "簽核對象",
      "type": "Dropdown",                       // 業務人員只看到下拉
      "binding": { "type": "property", "name": "odoo:roleRef" },
      "choices": "@rpc:bpmn.role.options" },    // 自訂：即時從 Odoo 抓角色清單
    { "label": "簽核方式", "type": "Dropdown",
      "binding": { "type": "property", "name": "odoo:approvalMode" },
      "choices": [
        { "name": "任一人核准即過", "value": "any" },
        { "name": "全部核准(會簽)", "value": "all" },
        { "name": "依序簽核", "value": "sequential" } ] },
    { "label": "允許主管自行往上加簽", "type": "Boolean",
      "binding": { "type": "property", "name": "odoo:allowEscalation" } }
  ]
}
```
預設積木庫（拖拉即用）：
- **簽核任務** / **會簽任務** / **通知任務**（只發 activity 不卡關）
- **條件分歧**（exclusive gateway，屬性面板用下拉選「依單據欄位/依 DMN 決策表」）
- **平行會簽**（parallel gateway）
- **執行 Odoo 動作**（service task，下拉選已註冊的 server action / action gate）
- **開始 / 結束**

> 效果：業務人員拖一個「簽核任務」到畫布，右側只問「誰簽？怎麼簽？可否加簽？」，完全不碰 BPMN 術語。

### 3.2 屬性面板接 Odoo 即時資料（odoo_properties_provider）
- 自訂 properties provider，`choices: "@rpc:bpmn.role.options"` 這類動態選項，**透過 Odoo RPC 即時抓**：
  - 簽核對象下拉 → `bpmn.role.search_read()`（直屬主管、部門經理、指定職位…）
  - 「依單據欄位」下拉 → 取該 model 的 Many2one(res.users/hr.employee) 欄位清單
  - 「執行 Odoo 動作」下拉 → `bpmn.action.gate` / `ir.actions.server`
- 讓圖上的設定永遠對齊 Odoo 真實資料，避免填錯字。

### 3.3 流程樣板庫（Starter Templates）
- `bpmn.process.template` 模型，內建常見流程一鍵套用後再改：
  請假審批、加班申請、採購請款、報價核准、費用報銷、合約用印…
- L1 精靈 / L2 積木 模式進入時先問「從空白開始 or 套用樣板」。

### 3.4 設定精靈（L1，給最不懂的人）
> 註：此處的「精靈」是 **Odoo 設定精靈（`TransientModel` + 原生 form view）**，用來**填寫簽核設定**並自動產生 BPMN——**不是表單設計器**，使用者不設計任何表單。
- 設定精靈（Odoo 原生 wizard 畫面）：
  ```
  流程名稱：[請假審批]
  第 1 關：[直屬主管] 簽核方式[任一]  □可加簽
  第 2 關：[部門經理] 簽核方式[任一]  ☑可加簽
  條件：請假天數 > [3] 天 才需第 2 關
  完成後執行：[核准請假單 action_approve]
  ```
- 後端把精靈填寫的設定轉成線性/條件 BPMN XML（`bpmn.wizard._generate_xml()`）→ 存回 `bpmn_xml`。
- **雙向**：生成的圖可在 L2/L3 打開續編；反向不保證（複雜圖無法回退成精靈）。

### 3.5 受限調色盤（odoo_palette_provider）
- L1/L2 模式：調色盤只給「開始/簽核/會簽/條件/通知/Odoo動作/結束」，**移除** intermediate event、subprocess、boundary event 等業務人員會畫錯、引擎也未支援的元素。
- L3 專家模式才開放完整調色盤（在引擎支援範圍內）。

---

## 4. 防呆 — 即時驗證 + 沙箱測試（讓「畫得出」=「跑得動」）

### 4.1 即時驗證（bpmnlint + 自訂 Odoo 規則）
- 整合 **bpmnlint**，畫布即時紅點 + 問題清單面板。自訂規則（`static/.../lint-rules/`）：
  | 規則 | 說明 |
  |---|---|
  | `single-start` | 必須恰一個開始節點 |
  | `has-end` | 必須至少一個結束節點，且所有路徑可達 |
  | `usertask-has-role` | 每個簽核任務必須綁簽核對象（odoo:roleRef） |
  | `gateway-has-condition` | 互斥閘道每條出線必須有條件或預設線 |
  | `servicetask-has-action` | Odoo 動作節點必須綁有效 action gate |
  | `no-dangling` | 不可有孤立節點/未連線 |
  | `escalation-depth` | 加簽鏈深度上限（防無限上呈） |
- **未通過 lint → 「發佈」按鈕鎖定**（`action_publish` 後端二次驗證，前端只是 UX）。

### 4.2 沙箱模擬（發佈前 dry-run）
- 整合 **bpmn-js-token-simulation** 做視覺化 token 走訪 +（更重要）後端 **dry-run**：
  - 輸入假申請人（選一個員工）→ 引擎只跑 **解析**不真正攔截 action、不建真活動。
  - 輸出：每個簽核任務「實際會解析出誰簽」「會簽幾人」「走哪條 gateway」「最終回放哪個 action」。
  - 讓建流程的人**發佈前就看到「張三請假會送到誰」**，避免上線才發現主管解析成空。
- 模擬結果存 `bpmn.simulation.run`，可比對不同申請人情境。

---

## 5. DMN 自助設計（dmn-js）— 把「條件判斷」也交給業務人員

### 5.1 為什麼要 DMN
- 複雜條件（金額分級加簽、依職等決定關卡）若全塞進 gateway 條件式，業務人員看不懂也維護不了。
- **DMN 決策表 = 業務人員最熟悉的「if-then 表格」**，比寫運算式直覺一個量級。

### 5.2 整合方式
- `bmn.decision.definition` 模型存 `dmn_xml`；OWL 元件掛 `window.DmnJS`（dmn-js modeler，含 DRD + 決策表編輯器）。
- BPMN 端：「條件分歧」積木屬性面板可選「依 DMN 決策表」→ 下拉選 `bpmn.decision.definition`（寫入 `odoo:decisionRef`），或對應 `bpmn:businessRuleTask`。
- 後端 DMN 執行：用輕量 DMN 求值器（`bpmn.decision._evaluate(inputs)`，FEEL 子集或 hit-policy FIRST/UNIQUE），輸入取自單據欄位，輸出決定 gateway 走向 / 加簽對象。
- 決策表輸入欄位下拉同樣接 Odoo RPC，列出單據 model 的可用欄位（金額、天數、部門、職等）。

### 5.3 自助決策表範例（業務人員填表）
| 請款金額 | 申請人職等 | → 簽核層級 |
|---|---|---|
| < 1萬 | any | 直屬主管 |
| 1萬~10萬 | any | 直屬主管 + 部門經理 |
| > 10萬 | any | + 財務長 |

---

## 6. 治理 — 自助但不失控 ★（公民開發成敗關鍵）

| 機制 | 設計 |
|------|------|
| **生命週期送審** | `draft → submitted → approved → published`。L1/L2 公民建立的流程，**發佈前需 designer/manager 審核**（可依「綁定的 model 風險」決定是否強制送審） |
| **權限範圍 (scope)** | 公民開發者只能：建自己部門的流程、綁**白名單內的低風險 model/method**（如請假、報銷）；**高風險按鈕（過帳 `action_post`、付款）僅 IT 可綁** |
| **沙箱 vs 正式** | 草稿流程只能 dry-run，不會真的攔截正式單據；發佈才進正式 action gate |
| **版本凍結** | 沿用 `DESIGN.md`：發佈即凍結，進行中實例走舊版 |
| **稽核** | 誰建/誰改/誰發佈/誰審核，全寫 `mail.thread` 軌跡 |
| **加簽護欄** | `escalation-depth` lint + runtime 上限，防無限上呈 |

權限群組擴充：
- `group_bpmn_citizen`（公民開發者）：L1/L2、限定 scope、需送審
- `group_bpmn_designer`：L3、可發佈、可綁多數 model
- `group_bpmn_manager`：審核、綁高風險 model、管理樣板庫

---

## 7. 對 `COMPETITIVE_ANALYSIS.md` 的影響（弱項翻轉）

| 維度 | 完工前 | 本設計完工後 |
|------|--------|------------|
| 低碼/公民開發 | ⚠ 2/5（設定導向） | ✅ **4/5**（元素樣板 + 精靈 + 即時驗證 + 沙箱，達 Appian/Power Automate 級的「業務人員自助」） |
| DMN 決策 | 🟡 DMN-lite 選配 | ✅ **dmn-js 視覺決策表自助編輯** |
| 視覺編輯器 | ✅ bpmn-js | ✅✅ bpmn-js + dmn-js + 屬性面板 + lint + 模擬（bpmn.io 全家桶） |

> 翻轉後，dobtor_approval 在雷達上的「偏科」缺口（公民開發）補平，且**仍保有「ERP 零距離整合 + 台灣簽核文化」護城河**——
> 變成「**業務人員可自助拖拉、又能直接掛 Odoo 業務動作、又懂台灣加簽文化**」的組合，這個三合一國內外都沒有現成對手。

---

## 8. 開發 Roadmap 增補（接續 DESIGN.md M1–M7）

| 階段 | 內容 | 驗證 |
|------|------|------|
| **M1.5** | bpmn-js dist 嵌入 + OWL 包裝 + 存讀 XML（取代純文字欄位） | 能在 Odoo 內拖拉畫圖並存檔 |
| **M8 元素樣板** | element-templates 積木庫 + odoo_properties_provider（RPC 動態選項） | 拖「簽核任務」只露業務欄位、角色下拉接真資料 |
| **M9 防呆** | bpmnlint 自訂規則 + 發佈鎖 + dry-run 沙箱（解析模擬） | 未綁角色不能發佈；發佈前能預覽「誰會簽」 |
| **M10 設定精靈** | L1 設定精靈（Odoo wizard）→ 生成 BPMN XML，雙向開啟 | 不懂 BPMN 的人 5 分鐘建出請假流程 |
| **M11 DMN 自助** | dmn-js 嵌入 + 決策表編輯 + 後端 FEEL-lite 求值 + 綁 gateway | 業務人員填金額分級表，流程依表加簽 |
| **M12 治理** | 送審生命週期 + scope 權限 + 樣板庫管理 + 受限調色盤 | 公民只能建低風險流程、需審核才發佈 |

---

## 9. 技術風險與對策（自助設計器專屬）

| 風險 | 對策 |
|------|------|
| bpmn-js/dmn-js bundle 體積大、與 Odoo asset 衝突 | 用官方 dist UMD 放 `static/lib`，不進 Odoo ES 編譯；lazy-load 僅設計頁載入 |
| 屬性面板 RPC 動態選項效能 | 選項快取 + 進入設計器時一次預載角色/欄位清單 |
| 業務人員畫出引擎不支援的 BPMN 結構 | 受限調色盤 + lint 雙重攔截，發佈端二次驗證 |
| DMN FEEL 完整度 | 第一階段只支援 hit-policy FIRST/UNIQUE + 比較/區間運算，文件標清範圍 |
| 公民自助造成流程氾濫/重複 | 樣板庫引導複用 + manager 審核 + 命名/分類規範 |
| 精靈↔圖 雙向同步落差 | 明確規則：精靈→圖單向保證；圖過於複雜則鎖精靈模式，只允 L2/L3 編輯 |
```
