# dobtor_approval 完工後 — 對標國內外 BPM 服務之功能優劣分析

> 文件版本：v1.5 ｜ 撰寫日：2026-06-06（v1.5 收斂為 2 模組）
> 分析基準：`DESIGN.md`（M1–M7）+ `DESIGN_SELF_SERVICE_DESIGNER.md`（自助設計器）+ `DESIGN_PROGRESSIVE_TIERS.md`（T0–T6 能力分級）+ `DESIGN_MODULE_SPLIT.md`（設計/執行分層）全數完工的
> **僅 2 模組：`dobtor_approval`（基礎·簽核·BPM 引擎＋內建 BPMN 編輯器核心，含代簽核/加簽/DMN 求值，以能力開關分級啟用）+ `dobtor_bpmn`（擴充·流程設計圖庫，depends approval）**。
> **⚠️ 依賴已反轉（2026-06-07）**：`dobtor_approval` 自足（可獨立設計＋執行）；`dobtor_bpmn` 退為其上的設計圖庫。
> 本分析的對標主體為「簽核方案 `dobtor_approval`（自足，含編輯器核心）」。
> 對標對象：華苓 Agentflow、叡揚 Vitals ESP、**新人類 FlowMaster BPM**、鼎新 Workflow GP｜Camunda 8、Pega、Appian、Power Automate、Flowable/Bonita
>
> **v1.1 變更**：新增 BPMN/DMN 自助拖拉設計器（積木 + 精靈 + lint + 沙箱 + dmn-js），「公民開發」由 2/5 翻轉為 4/5、DMN 升為視覺化自助。
> **v1.2 變更**：① 導入「由簡入深 T0–T6 能力分級 + 預設關閉開關」，新增「上手簡單度/漸進式複雜度」為獨特優勢；
> ② 原弱項「BPMN 子集」改為「T5 可選補齊」（Timer/Boundary SLA、Error/Incident、真 Multi-instance、Call Activity 預設關閉、按需開啟）；詳見 §三-7、§四-2、§六雷達。
> **v1.3 變更**：新增成熟商用對手「新人類 FlowMaster BPM」全欄位對標（總表 + 雷達 + 場景 + 專節 §四之二），並新增「表單設計器/行動簽核App/產品成熟度」三個總表維度以反映其強項。詳見 §三之二。
> **v1.4 變更**：模組改名 —— 核心（純 BPMN/DMN 設計環境）= `dobtor_bpmn`；簽核（BPM 執行引擎）= `dobtor_approval`。原名 `dobtor_bpmn`（指整體方案）全面更名為 `dobtor_approval`。
> **v1.5 變更**：收斂為 **2 模組**——原子擴充 `dobtor_approval_activity`（代簽核/加簽）、`dobtor_approval_dmn`（DMN 求值）**併入 `dobtor_approval`**，改以模組內能力開關（T0–T6，預設關閉）控制，不再實體拆分子模組。

---

## 一、總體定位（一句話）

> **dobtor_approval = 「長在 Odoo 體內的 BPMN 簽核引擎」**。
> 它不跟 Camunda 比引擎規模、不跟 Pega 比 AI 決策、不跟華苓比品牌與服務體系；
> 它的決勝點是 **「與 Odoo ERP 業務動作零距離、又同時具備台灣簽核文化彈性」** 這個別人到不了的交集。

---

## 二、核心功能優劣總表

圖例：✅ 強項　🟡 堪用/部分　⚠ 弱項/缺　🔵 獨特優勢

| 功能維度 | **dobtor_approval(完工)** | 華苓 Agentflow | 叡揚 Vitals ESP | 新人類 FlowMaster | Camunda 8 | Pega | Appian | Power Automate |
|---|---|---|---|---|---|---|---|---|
| BPMN 2.0 可執行引擎 | 🟡→✅ 子集+T5可選補齊 | ✅ | 🟡 | 🟡 自有引擎(非BPMN) | ✅✅ 標竿 | ✅ | ✅ | ⚠ 非BPMN |
| DMN 決策引擎 | ✅ dmn-js 視覺決策表(自助) | 🟡 | ⚠ | 🟡 條件判斷(AutoScript) | ✅✅ | ✅✅ | ✅ | 🟡 |
| 流程模擬/挖掘 | 🟡 T4沙箱dry-run(無挖掘) | ⚠ | ⚠ | ✅ Simulator+Monitor分析 | 🟡 | ✅ | ✅✅ | 🟡 |
| **上手簡單度/漸進式複雜度** | 🔵✅✅ 由簡入深(T0開箱·開關啟用) | 🟡 | 🟡 | 🟡 完整平台 | ⚠ 陡 | ⚠ 陡 | ✅ | ✅ |
| **與 ERP 業務動作整合** | 🔵✅✅ 原生零距離 | 🟡 需接 | 🟡 需接 | 🟡 需接(DPS/RFC) | ⚠ 需自寫 connector | 🟡 | 🟡 | 🟡 connector |
| **Action 攔截→簽核→回放** | 🔵✅✅ 內建閘門 | 🟡 | 🟡 | ⚠ 表單導向 | ⚠ 需自建 | ✅(Case) | ✅ | 🟡 |
| **HR 組織關係動態解析** | ✅✅(Odoo HR 原生) | ✅✅(OAB) | ✅ | ✅ 核決權限表+AD同步 | ⚠ 需自建 | ✅ | ✅ | 🟡 |
| **會簽/依序/任一** | ✅ | ✅✅ | ✅ | ✅✅ 含成批 | 🟡 需建模 | ✅ | ✅ | 🟡 |
| **職務代理(代簽核)** | ✅(delegation模型) | ✅✅ | ✅ | ✅✅ 代簽核/代核/回溯 | ⚠ | ✅ | ✅ | 🟡 |
| **個人化動態加簽/上呈** | 🔵✅✅ runtime 例外 | ✅✅ | ✅ | ✅ 加簽/徵詢/變動簽核權 | ⚠ 純圖難做 | ✅ ad-hoc | ✅ | ⚠ |
| 表單設計器 | ⚠ 靠 Odoo 既有表單 | 🟡 | ✅ | ✅✅ NTFB+101範本 | ⚠ | ✅ | ✅✅ | ✅ |
| 視覺流程編輯器 | ✅✅ bpmn-js+dmn-js+面板+lint+模擬 | ✅ 自有 | ✅ | ✅ Designer 自有 | ✅✅ bpmn-js原廠 | ✅ | ✅ | ✅ |
| 低碼/公民開發 | 🔵✅ 自助拖拉(積木+精靈+防呆) | 🟡 | 🟡 | ✅ NTFB(偏IT) | ⚠ 開發者向 | ✅✅ | ✅✅ | ✅✅ |
| 行動簽核 App | 🟡 靠 Odoo mobile | ✅ | ✅ | ✅✅ NT OneAPP/FaceID/Line | 🟡 | ✅ | ✅ | ✅ |
| 雲原生/多租戶 SaaS | ⚠ 隨 Odoo 部署 | 🟡 | 🟡 | 🟡 容器化(Matrix) | ✅✅ | ✅ | ✅✅ | ✅✅ |
| 水平擴展/高吞吐 | ⚠ Odoo 單體限制 | 🟡 | 🟡 | 🟡 64位元引擎 | ✅✅ | ✅ | ✅ | ✅ |
| Connector 生態 | ⚠ 僅 Odoo 內 | 🟡 在地 | 🟡 在地 | ✅ 多協定+SAP RFC/EDI | 🟡 | ✅ | ✅ | ✅✅ 數百 |
| 中文化/在地法遵 | ✅ | ✅✅ | ✅✅ | ✅✅ | ⚠ | 🟡 | 🟡 | 🟡 |
| 稽核軌跡 | ✅(history模型) | ✅✅ | ✅✅ | ✅✅ Monitor | ✅ | ✅✅ | ✅ | ✅ |
| AI/生成式流程 | ⚠ 無(可後加LLM) | 🟡 | 🟡 | ✅ 已上線(智慧精靈) | 🟡 | ✅✅ | ✅ | ✅ |
| 產品成熟度/案例 | ⚠ 自研新品 | ✅✅ | ✅✅ | ✅✅ 2003至今 | ✅✅ | ✅✅ | ✅✅ | ✅✅ |
| 導入成本 | 🔵✅ 極低(已有Odoo) | 中 | 中高 | 中 | 中(自建多) | ⚠ 極高 | ⚠ 高 | 🟡 |
| 授權費 | 🔵✅ 零授權(自有) | 中 | 中 | 中(商用授權) | 開源+雲費 | ⚠ 昂貴 | ⚠ 昂貴 | 訂閱 |

---

## 三、dobtor_approval 的「壓倒性優勢」（別人到不了的點）

### 🔵 1. ERP 業務動作零距離整合 — 最大護城河
- 國際引擎（Camunda/Pega/Appian）要簽核一張「訂單確認」，必須：建 connector → 拉 Odoo 資料 → 簽完 → 回寫 Odoo。**跨系統、要維運、會延遲、資料雙寫易不一致**。
- dobtor_approval 直接攔 `sale.order.action_confirm`，簽完用同一個 ORM transaction 回放原方法。**無 connector、無資料同步、無第二套帳**。
- 連華苓/叡揚都做不到這點 —— 它們是獨立 BPM 平台，與 Odoo 之間仍是「系統間整合」。

### 🔵 2. Action 攔截閘門（approval-gate）開箱即用
- 「任何 Odoo 按鈕/方法都能掛簽核，核准後自動放行」這種 **Studio Approvals 等級的能力，在 Odoo Community 生態幾乎沒有對手**，而我們還把背後規則升級成完整 BPMN 流程 + HR 解析。

### 🔵 3. 個人化動態加簽 — 補國際純 BPMN 的死穴
- Camunda/Bonita 等 token 引擎，「臨時往上加一個沒畫在圖上的簽核人」非常痛苦（要改流程或寫複雜 ad-hoc subprocess）。
- 我們用 **runtime 例外規則 + 臨時 user_task 插入**，二級主管當場決定上呈一級、簽完退回續簽，流程圖完全不用動。**這是台灣簽核文化剛需，恰好是國際引擎最弱處。**

### 🔵 4. 成本結構
- 已有 Odoo 的客戶，導入 = 裝一個 addon，**零額外授權、零新平台、零新維運團隊**。Pega/Appian 動輒百萬級授權 + 顧問導入，完全不同量級。

### ✅ 5. 簽核待辦體驗站在 `dobtor_mail_activity` 肩膀上
- 直接複用既有的週排程 Kanban、工時、改派、異動歷史、提醒 —— **簽核人的待辦體驗一上線就成熟**，不像自建引擎還要從零做待辦中心。

### 🔵 6. 「自助拖拉 × Odoo 業務動作 × 台灣加簽文化」三合一（自助設計器加持）
- 用 bpmn.io 全家桶（bpmn-js + dmn-js + properties-panel + element-templates + bpmnlint + token-simulation）疊上 Odoo 鷹架：
  - **元素樣板積木**：拖「簽核任務」只露「誰簽/怎麼簽/可否加簽」，隱藏 BPMN 術語；下拉選項即時接 Odoo HR/角色資料。
  - **精靈模式**：完全不懂 BPMN 的員工填表單即生成可執行流程。
  - **防呆**：bpmnlint 即時驗證（未綁角色不能發佈）+ 沙箱 dry-run（發佈前預覽「誰會簽」）。
  - **DMN 自助**：金額分級加簽用決策表填寫，不必寫運算式。
- Appian/Power Automate 有自助但**不懂 Odoo 業務動作、不懂台灣加簽**；華苓/叡揚懂簽核但**自助拖拉與 ERP 整合較弱**。**三者交集只有 dobtor_approval**。

### 🔵 7. 由簡入深 — 「開箱極簡」與「能力完整」同時成立
- 導入 T0–T6 能力分級 + **進階功能預設關閉的開關架構**（沿用 Dobtor-HR「開關 + Security Group」策略）：
  - **開箱 = T0**：只有「開始→簽核→結束」+ 精靈，5 分鐘建第一條請假流程，不被複雜度淹沒。
  - **按需長出**：要條件開 T1、要綁 ERP 開 T2、要自助開 T4、要 SLA/複雜引擎開 T5 —— 每一步一個開關。
- Pega/Appian **功能強但上手陡**（一進場全部複雜度砸臉）；華苓 **簡單但天花板低**。
- dobtor_approval 走 **第三條路**：用「漸進式複雜度」化解「完整 vs 簡單」的矛盾 —— **這個設計本身國內外大廠都沒有**，是把「導入簡單」從一次性優勢變成可持續的產品哲學。

---

## 三之二、與「新人類 FlowMaster BPM」正面對決（成熟商用對手）

> 新人類資訊科技（1988 創立、FlowMaster 自 2003 發表）是**比數位通強一個量級、接近華苓/叡揚等級**的老牌商用 BPM，不可輕看。以下為公平對決。

### 根本範式差異（比逐項功能更關鍵）
| | 新人類 FlowMaster | dobtor_approval |
|---|---|---|
| 範式 | **表單中心**：用 NTFB 工具打造新的簽核表單應用 | **動作/單據中心**：在既有 Odoo 業務動作上掛簽核閘門 |
| 引擎 | 自有專屬引擎（Designer + AutoScript），非 BPMN 標準 | BPMN 2.0 / DMN 開放標準（bpmn.io） |
| 與 ERP 關係 | 透過 DPS/REST/SAP RFC「系統間整合」拉資料 | 長在 Odoo 體內、零距離、同一 ORM transaction |
| 商業模式 | 商用授權（套裝/雲租用）、AI 按 Token 計費 | 自有 addon、零授權 |

> 一句話：**FlowMaster 是「打造簽核應用的獨立平台」；dobtor_approval 是「替既有 Odoo ERP 操作加上簽核閘門」——兩者不完全在同一條跑道。**

### FlowMaster 明顯較強的六塊（誠實面對，不宜硬碰）
1. **產品成熟度與案例**：20+ 年、國泰電業等大案、商用 SLA。
2. **表單設計器**：NTFB + 16 大類 101 張範本 + 紙本套印；dobtor 無表單設計器，靠 Odoo 既有表單。
3. **異質系統整合廣度**：SAP RFC/BAPI、AutoEDI、AD 同步、多協定 DPS；dobtor 僅 Odoo 邊界內。
4. **AI 已落地**：生成式 AI「智慧精靈」（附件摘要/表單計算/查找）已上線；dobtor 僅 Roadmap。
5. **原生行動 App**：NT OneAPP、FaceID、手寫簽名、Line/WeChat/Teams、防截屏；dobtor 靠 Odoo mobile。
6. **營運級流程監控**：Monitor（逾期分析、關卡效率、簽核時間統計）；dobtor 僅 T4 沙箱、無營運分析。

### dobtor_approval 結構性勝出的三點（FlowMaster 做不到）
1. **與 Odoo ERP 業務動作零距離** — FlowMaster 對 Odoo 永遠是 connector，會有雙寫、延遲、第二套帳。
2. **BPMN/DMN 開放標準** — FlowMaster 是自有引擎鎖定，可攜性與生態受限。
3. **零授權 + 由簡入深** — 已投資 Odoo 的客戶不必再買第二套平台。

### 對決結論
- **「通用簽核平台」戰場**：FlowMaster 明顯更強，**不要去比表單設計器、SAP 整合、行動 App、AI 成熟度**——那是它的主場。
- **「Odoo 內業務動作簽核」戰場**：FlowMaster 的整合退化為 connector，**dobtor_approval 反而占上風**。收斂戰場是致勝關鍵。

---

## 四、dobtor_approval 的「明確弱項」（要誠實面對）

### ⚠ 1. 引擎規模與吞吐 — 受 Odoo 單體架構天花板限制
- Camunda 8 (Zeebe) 是雲原生、可水平擴展、每秒處理大量流程實例。
- dobtor_approval 跑在 Odoo worker / PostgreSQL 上，**高並發、百萬級實例場景會碰到 Odoo 本身的擴展瓶頸**。並行會簽 token 還需資料庫鎖序列化，吞吐不是強項。
- → **適用「企業內部簽核」量級，不適用「對外高頻交易流程編排」。**

### 🟡 2.（已部分補齊）BPMN 覆蓋度 — 核心子集 + T5 可選擴充
- **v1.0 原弱項**：只做 UserTask / ServiceTask / 三種 Gateway / Start-End。
- **v1.2 已由 T5 進階引擎補齊主要缺口**（預設關閉、按需開啟）：**Timer/Boundary Event（SLA 超時提醒/自動加簽/逾時核准）、Error/Incident（失敗重試）、真 Multi-instance（動態人數+比例通過）、Call Activity（子流程複用）、Event Subprocess、DMN 決策表**。
- **仍誠實不做**：Compensation（補償交易自動回滾）、Message Correlation/Choreography（事件驅動跨流程編排）、執行中實例 live migration —— 這幾項超出「企業內部簽核」定位，與 Camunda/Pega 仍有本質差距。
- → 結論：從「只做簽核子集」提升為「可開啟到接近企業級的 BPMN 能力，但仍非完整 conformance-class 引擎」。

### ⚠ 3. 流程挖掘 / 模擬 / AI 決策 全缺
- Celonis/Appian 的 Process Mining、Pega 的 AI Decisioning、流程模擬 —— **我們起步沒有**。
- → 只能「執行流程」，無法「分析流程瓶頸、預測、最佳化」。這是高階 BPM 的價值區，短期補不上。

### ⚠ 4. 整合生態 = Odoo 邊界內
- 強在 Odoo 內、**弱在 Odoo 外**。要簽核流程跨到外部 SaaS（Salesforce、SAP、簽外部電子簽章如 DocuSign），需自寫整合，沒有 Power Automate 的數百 connector 市集。
- → 「Odoo 是唯一/核心系統」的客戶完美；異質系統林立的大型集團不適合。

### ✅ 5.（原弱項已解除）低碼/公民開發 — 由自助設計器補平
- **v1.0 原列為弱項**：流程設計偏 IT、設定導向、非公民開發。
- **v1.1 已由 `DESIGN_SELF_SERVICE_DESIGNER.md`（M8–M12）解決**：元素樣板積木 + 精靈模式 + 即時驗證 + 沙箱 + dmn-js + 治理送審，達 Appian/Power Automate 級的業務人員自助。
- **殘留限制（誠實）**：自助範圍仍受「引擎支援的 BPMN 子集」與「治理 scope（公民只能綁低風險 model）」約束；極複雜流程仍需設計師（L3）介入。

### ⚠ 6. 品牌、服務體系、案例信任
- 華苓/叡揚有二十年品牌、政府金融大案、原廠顧問與維護 SLA。
- dobtor_approval 是**自研 addon**，導入大型客戶時的「廠商信任、長期支援承諾、案例背書」是商務劣勢（非技術問題，但真實存在）。

---

## 五、分場景勝負判定（什麼情況選誰）

| 場景 | 最佳選擇 | 理由 |
|------|---------|------|
| **已用 Odoo，要把 ERP 業務動作加簽核** | 🏆 **dobtor_approval** | 零距離整合、零授權，沒有對手 |
| 中小企業電子表單簽核、預算有限、要快 | 🏆 **dobtor_approval** / 數位通 | 成本與導入速度 |
| 純表單簽核、不碰 ERP、要在地原廠服務 | 華苓 / 叡揚 | 品牌與服務體系 |
| **要打造大量獨立簽核表單、跨 SAP/多系統、要成熟商用支援+行動App+已有AI** | 🏆 **新人類 FlowMaster** | 表單設計器、SAP RFC、NT OneAPP、AI 智慧精靈成熟 |
| 不用 Odoo、要老牌穩定 + 文管/EIP/ISO 一站式 | 新人類 / 叡揚 | 平台生態完整 |
| 製造業綁鼎新 ERP 的流程 | 鼎新 Workflow GP | 與 T100/A1 無縫 |
| 高頻、跨系統、雲原生流程編排(微服務) | Camunda 8 | 引擎規模與雲原生 |
| 大型集團、要 AI 決策+流程挖掘+跨國 | Pega / Appian | 平台廣度與智慧化 |
| 已在 M365、要公民開發跨 SaaS 自動化 | Power Automate | connector 生態 |
| 含補償交易/事件驅動的複雜 BPMN | Camunda / Pega | 完整 BPMN 標準 |

---

## 六、競爭力雷達（質化評分，滿分 5）

| 維度 | dobtor_approval | 華苓 | 新人類 FlowMaster | Camunda 8 | Pega |
|---|---|---|---|---|---|
| ERP 業務整合深度 | **5** 🔵 | 3 | 3 | 2 | 3 |
| 台灣簽核文化貼合 | **5** 🔵 | 5 | **5** | 2 | 3 |
| 引擎規模/擴展 | 2 ⚠ | 3 | 3 | **5** | 4 |
| BPMN 標準完整度 | **4** *(v1.0:3, T5補齊)* | 4 | 3 *(自有引擎)* | **5** | 4 |
| 智慧化(挖掘/AI) | 1 ⚠ | 2 | 3 *(智慧精靈+Monitor)* | 3 | **5** |
| 整合生態 | 2 ⚠ | 3 | **4** *(SAP/EDI)* | 3 | **5** |
| 導入成本(越低越高分) | **5** 🔵 | 3 | 3 | 3 | 1 |
| 公民開發 | **4** 🔵 *(v1.0:2)* | 2 | 3 *(NTFB偏IT)* | 1 | **5** |
| 上手簡單度/漸進式複雜度 | **5** 🔵 | 3 | 3 | 2 | 2 |
| 產品成熟度/案例 | 2 ⚠ | 5 | **5** | 5 | 5 |
| 表單設計器/行動App | 2 ⚠ | 4 | **5** | 2 | 4 |
| **加權總評(內部簽核情境)** | **高** | 高 | **高** | 中 | 中高 |

> 雷達形狀說明（v1.3）：新增「新人類 FlowMaster」欄與「產品成熟度/案例」「表單設計器/行動App」兩列，誠實揭露 dobtor_approval 在這兩列僅 2 分——FlowMaster 是成熟商用對手，在表單/行動/成熟度/生態明顯領先。
> 但 dobtor_approval 仍在 **「ERP整合(5) / 在地簽核(5) / 低成本(5) / 公民開發(4) / 漸進式上手(5)」五軸領先全場**；落後集中在「引擎規模 / 智慧化 / 生態 / 成熟度 / 表單行動」。
> 與 FlowMaster 的勝負取決於戰場：**通用簽核平台→FlowMaster 勝；Odoo 內業務動作簽核→dobtor_approval 勝。** 定位不變：**不做通用 BPM 平台，只做「Odoo 簽核 + 業務自助 + 開箱即簡、深用不限」的最佳解。**

---

## 七、結論與策略建議

1. **不要在錯的戰場競爭**：別宣稱要取代 Camunda/Pega。打「Odoo 簽核 + 台灣簽核文化」這個沒人佔的縫隙，這裡我們是第一名。

2. **把弱項轉成 Roadmap 而非否認**：
   - 引擎規模 → 明確定位「企業內部簽核」量級，不承諾高頻交易編排。
   - BPMN 子集 → 文件清楚標示支援範圍，避免客戶期待落空。
   - AI/挖掘 → M7 之後可接 LLM 做「流程設定助手 / 簽核摘要」作為差異化加值，而非硬做 mining。

3. **最大化護城河**：持續深化 Action 攔截覆蓋面與 HR 解析彈性（resolver_type 越多、加簽規則越細），把「Odoo 內簽核」做到別人連模仿都嫌不划算。

4. **商務劣勢補強**：用「開源/自有、可客製、無授權鎖定」對打華苓/叡揚的品牌優勢，主攻「已投資 Odoo、不想再買第二套 BPM 平台」的客戶。
