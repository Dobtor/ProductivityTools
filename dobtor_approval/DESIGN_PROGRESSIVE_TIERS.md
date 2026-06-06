# dobtor_approval — 由簡入深能力分級 + 功能開關設計（Progressive Disclosure）

> 文件版本：v1.0 ｜ 撰寫日：2026-06-06 ｜ 目標 Odoo：18.0
> 整合檢討對象：`DESIGN.md`（核心引擎 M1–M7）、`DESIGN_SELF_SERVICE_DESIGNER.md`（自助設計器 M8–M12）、`COMPETITIVE_ANALYSIS.md`（v1.1）、BPMN 引擎不足分析
> 設計範式：沿用 Dobtor-HR「功能模組開關 + Security Group」策略 — **進階功能預設關閉，用戶由簡入深逐步啟用**

---

## 0. 設計目標與原則

1. **功能完善**：把先前 BPMN 引擎缺口（Timer/Boundary SLA、Error/Incident、真 Multi-instance、Call Activity…）全數納入規劃，使能力對標完整。
2. **預設極簡**：全新安裝只開「Tier 0 入門」，畫面只剩「開始 → 簽核 → 結束」，5 分鐘能建第一條請假簽核。
3. **由簡入深**：每組進階能力 = 一個開關，預設 **OFF**；開啟後對應的調色盤元素、屬性欄位、選單才「長出來」。
4. **不可越級**：開關有相依關係，高階開關需先開其前置（避免畫出引擎處理不了的圖）。
5. **雙層控管**：`res.config.settings` 布林（這個資料庫是否啟用此能力）＋ Security Group（哪些使用者能用）。
6. **發佈端守門**：流程定義若用到未啟用的能力 → `action_publish` 阻擋並明確提示，前端只是 UX 第一道。

---

## 1. 能力分級總表（Tier 0 → Tier 6，由簡入深）

| Tier | 名稱 | 一句話 | 預設 | 主要新增能力 | 對應里程碑 |
|------|------|--------|------|-------------|-----------|
| **T0** | 入門·線性簽核 | 開箱即用，最簡單序簽 | **✅ ON** | 精靈模式、直屬主管/部門經理、任一核准、mail.activity 待辦、開始/簽核/結束 | M1–M4 子集 |
| **T1** | 條件與會簽 | 加條件分歧、會簽、HR 多解析 | OFF | exclusive gateway、會簽(all)/依序、HR 全 resolver_type、職務代理(代簽核) | M2,M4 |
| **T2** | 業務動作整合 | 把簽核掛上 Odoo 按鈕 | OFF | Action 攔截閘門、ServiceTask、攔截→簽核→回放 | M5 |
| **T3** | 彈性例外 | 主管自主加簽/上呈、平行會簽 | OFF | 個人化 runtime 加簽、parallel/inclusive gateway | M6 |
| **T4** | 自助設計器 | 業務人員拖拉建流程 | OFF | bpmn-js 積木模式、元素樣板、屬性面板接 RPC、bpmnlint 即時驗證、沙箱 dry-run | M8–M10 |
| **T5** | 進階引擎 | 補齊 BPMN 完整能力 | OFF | **SLA Timer/Boundary、Error/Incident 重試、真 Multi-instance、DMN 決策表、Call Activity、Event Subprocess** | M11 + 引擎補強 |
| **T6** | 治理與專家 | 大型組織治理、專家全功能 | OFF | L3 專家全調色盤、送審生命週期、scope 權限、流程版本遷移/實例修改 | M12 + 進階 |

> **由簡入深路徑**：客戶從 T0 開箱 → 需要條件就開 T1 → 要綁 ERP 開 T2 → 要彈性加簽開 T3 → 要交給業務自助開 T4 → 要 SLA/複雜引擎開 T5 → 大型治理開 T6。**每一步都是一個開關，永遠不會被用不到的複雜度淹沒。**

---

## 2. 功能開關目錄（Feature Toggle Catalog）

開關存於 `res.config.settings`（落 `res.company` 或 `ir.config_parameter`，依多公司需求）。命名 `bpmn_enable_*`。

| 開關 key | Tier | 預設 | 相依前置 | 開啟後「長出」什麼 | 守門點 |
|----------|------|------|---------|-------------------|--------|
| `bpmn_enable_wizard` | T0 | **ON** | — | 精靈建立流程 | — |
| `bpmn_enable_basic_approval` | T0 | **ON** | — | 開始/簽核/結束、任一核准、direct_manager/department_manager | — |
| `bpmn_enable_conditional` | T1 | OFF | basic | exclusive gateway、條件出線屬性 | publish 驗證 gateway |
| `bpmn_enable_cosign` | T1 | OFF | basic | 會簽(all)/依序簽核 approval_mode | — |
| `bpmn_enable_hr_resolvers` | T1 | OFF | basic | manager_level/job/field_on_record/expression 等進階 resolver | safe_eval 白名單 |
| `bpmn_enable_delegation` | T1 | OFF | basic | 職務代理(代簽核)模型與選單 | — |
| `bpmn_enable_action_gate` | T2 | OFF | basic | Action 掃描器、ServiceTask、前端攔截+後端 guard | guard 安全底線 |
| `bpmn_enable_escalation` | T3 | OFF | cosign | 「上呈加簽」按鈕、escalate wizard、allow_escalation 屬性 | escalation-depth 上限 |
| `bpmn_enable_parallel_gw` | T3 | OFF | cosign | parallel/inclusive gateway 調色盤 | join 同步驗證 |
| `bpmn_enable_designer` | T4 | OFF | conditional | bpmn-js 積木模式、屬性面板、元素樣板 | 受限調色盤 |
| `bpmn_enable_lint` | T4 | OFF | designer | bpmnlint 即時驗證 + 發佈鎖 | — |
| `bpmn_enable_sandbox` | T4 | OFF | designer | 沙箱 dry-run 模擬「誰會簽」 | — |
| `bpmn_enable_sla_timer` | T5 | OFF | action_gate | **Timer/Boundary 超時事件**（逾時提醒/自動加簽/逾時核准）+ cron 驅動 | — |
| `bpmn_enable_incident` | T5 | OFF | action_gate | **Error/Incident 狀態 + 重試政策 + 重試 UI** | — |
| `bpmn_enable_multi_instance` | T5 | OFF | cosign | **真 Multi-instance**：動態人數 + completionCondition(比例通過) | — |
| `bpmn_enable_dmn` | T5 | OFF | conditional | dmn-js 決策表、businessRuleTask、FEEL-lite 求值 | — |
| `bpmn_enable_call_activity` | T5 | OFF | designer | **Call Activity** 子流程複用、Event Subprocess | — |
| `bpmn_enable_governance` | T6 | OFF | designer | 送審生命週期 draft→submitted→approved→published | 審核權限 |
| `bpmn_enable_scope` | T6 | OFF | governance | 公民 scope 限制（部門/低風險 model 白名單） | 高風險 model 鎖 IT |
| `bpmn_enable_expert_mode` | T6 | OFF | designer | L3 完整 BPMN 調色盤（引擎支援範圍內） | — |
| `bpmn_enable_migration` | T6 | OFF | governance | 執行中實例遷移到新版定義、實例修改(跳 token) | manager 限定 |

> **相依鎖**：UI 上未滿足前置的開關呈灰階且不可勾；後端 `write` 時二次校驗（開 X 必先開其 depends），避免設定不一致。

---

## 3. 開關的「守門」機制（三層）

### 3.1 前端 — 編輯器動態長出 / 收合
設計器載入時一次 RPC 取得 `enabled_features`，據以：
- **調色盤 (palette)**：只列已啟用元素。T0 只有「開始/簽核/結束」；開 `conditional` 才出現「條件分歧」；開 `sla_timer` 才出現「逾時邊界」。
- **屬性面板 (properties panel)**：欄位分組依開關顯隱。如 `escalation` 關 → 不顯示「允許往上加簽」；`multi_instance` 關 → 簽核方式只到 any/all/sequential，不顯示「比例通過」。
- **元素樣板 (element-templates)**：載入的積木清單依開關過濾。
- **選單 (menuitem)**：DMN 設計、代理設定、Action 閘門、流程遷移等選單用 `groups` 屬性 + 開關連動顯隱。

### 3.2 後端 — 發佈守門 (`action_publish`)
```python
def action_publish(self):
    used = self._scan_used_features()          # 解析 XML 用到哪些能力
    enabled = self.env.company._bpmn_enabled_features()
    missing = used - enabled
    if missing:
        raise UserError(_(
            "此流程用到尚未啟用的功能：%s。請先至『設定 → BPMN 簽核』開啟，"
            "或移除這些元素。", ", ".join(FEATURE_LABELS[f] for f in missing)))
    return super().action_publish()
```
- **執行引擎**也檢查：token 抵達需要某能力的節點而該能力被關 → 標 incident 而非靜默錯誤。

### 3.3 權限 — Security Group（誰能用）
雙層：開關決定「資料庫有沒有這能力」，Group 決定「誰能操作」。
| Group | 對應能力 |
|-------|---------|
| `group_bpmn_citizen` | T4 自助（受 scope 限制） |
| `group_bpmn_designer` | T1–T5 設計、發佈 |
| `group_bpmn_manager` | T6 治理、遷移、綁高風險 model、審核 |
- 開啟某 Tier 開關時，設定頁提供「同時授權給 designer/manager 群組」的便捷選項（沿用 Dobtor-HR 開關套 group 的做法）。

---

## 4. 設定頁 UI 佈局（由上而下 = 由簡入深）

`設定 → BPMN 簽核` 頁面分區，**順序即難度**，每區一個 Tier 標題 + 子開關，未開前置的區塊整區灰階摺疊：

```
┌─ ⚙ BPMN 簽核設定 ───────────────────────────────────┐
│ [T0] 入門·線性簽核              ✅ 已啟用(預設,不可關) │
│   ☑ 精靈建立  ☑ 基本簽核                              │
├──────────────────────────────────────────────────────┤
│ [T1] 條件與會簽                          ▸ 展開        │
│   ☐ 條件分歧  ☐ 會簽/依序  ☐ 進階HR解析  ☐ 職務代理   │
├──────────────────────────────────────────────────────┤
│ [T2] 業務動作整合                        ▸ 展開        │
│   ☐ Action 攔截閘門                                   │
├──────────────────────────────────────────────────────┤
│ [T3] 彈性例外            (需先開 T1 會簽)  🔒灰階      │
│   ☐ 主管自主加簽  ☐ 平行會簽                          │
├──────────────────────────────────────────────────────┤
│ [T4] 自助設計器          (需先開 T1 條件)  🔒灰階      │
│   ☐ 積木設計器  ☐ 即時驗證  ☐ 沙箱模擬                │
├──────────────────────────────────────────────────────┤
│ [T5] 進階引擎            (需先開 T2/T1)    🔒灰階      │
│   ☐ SLA超時  ☐ 失敗重試  ☐ 真會簽(比例)  ☐ DMN決策表 │
│   ☐ 子流程複用                                        │
├──────────────────────────────────────────────────────┤
│ [T6] 治理與專家          (需先開 T4)       🔒灰階      │
│   ☐ 送審流程  ☐ scope限制  ☐ 專家模式  ☐ 實例遷移    │
└──────────────────────────────────────────────────────┘
```
- 每個開關旁附「這會啟用什麼 / 適合誰」的 tooltip，引導用戶判斷是否需要。
- 提供 **「能力套裝」快速鈕**：`中小企業簽核(開 T1)` / `ERP整合簽核(開 T1+T2)` / `自助公民開發(開 T1+T2+T4)` / `企業完整(全開)` — 一鍵套一組常見組合，降低逐項勾選負擔。

---

## 5. 流程定義層級的能力上限（per-definition capability）

除全域開關外，每個 `bpmn.process.definition` 有 `capability_level`（T0–T6），**不可超過公司全域已開的最高 Tier**：
- 用途：同一資料庫，給「簡單流程」鎖在 T0/T1（即使全域開了 T5，這條流程的編輯器也只露低階元素，避免設計者誤用）。
- 公民開發者建立的流程，`capability_level` 預設鎖在其 group 允許的上限。
- 守門：`action_publish` 同時校驗「全域開關」與「本流程 capability_level」。

---

## 6. 整份規劃檢討結果（三份文件的調和）

| 議題 | 原規劃 | 本次調整 |
|------|--------|---------|
| BPMN 引擎缺口（Timer/Incident/Multi-instance/Call Activity） | `COMPETITIVE_ANALYSIS.md` 列為「明確弱項·不做」 | **改為「T5 進階引擎·預設關閉的可選能力」** — 功能補上但不強迫，維持開箱簡單 |
| 自助設計器 | `DESIGN_SELF_SERVICE_DESIGNER.md` 預設啟用 | **降為 T4 開關·預設 OFF** — 入門用戶用精靈即可，需要才開設計器 |
| 三級使用者體驗(L1/L2/L3) | 設計器內三模式 | **對齊 Tier**：L1=T0精靈、L2=T4積木、L3=T6專家，由開關+group 控制露出 |
| Roadmap M1–M12 | 線性里程碑 | **重映射為 Tier 交付**：每完成一個 Tier 即可上線給對應成熟度客戶，不必等全做完 |
| 競爭定位 | 怕「功能多=複雜」傷及「導入簡單」優勢 | **由簡入深正面解決此矛盾**：對外可同時主張「開箱極簡」與「能力完整」，因兩者由開關分離 |

> **關鍵結論**：先前「功能完整」與「導入簡單」是衝突的；**能力分級 + 預設關閉的開關架構，讓兩個優點同時成立** — 這本身就是對標 Pega/Appian「功能強但上手陡」與華苓「簡單但天花板低」的差異化第三條路。

---

## 7. 對 `COMPETITIVE_ANALYSIS.md` 的再影響

| 維度 | v1.1 | 本設計後 |
|------|------|---------|
| BPMN 2.0 可執行引擎 | 🟡 子集 | 🟡→✅ **T5 補齊主要缺口**（Timer/Incident/Multi-instance/Call Activity 可選開啟） |
| 上手簡單度（新增維度） | 未列 | 🔵✅✅ **由簡入深·開箱 T0 最簡**，國際大廠無此「漸進式複雜度」設計 |
| 流程模擬 | ⚠ 無 | 🟡 T4 沙箱 dry-run（解析模擬，非完整 simulation） |

---

## 8. 實作要點（Feature Toggle 技術骨架）

```python
class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    bpmn_enable_conditional = fields.Boolean(config_parameter='dobtor_approval.conditional')
    bpmn_enable_action_gate = fields.Boolean(config_parameter='dobtor_approval.action_gate')
    bpmn_enable_sla_timer   = fields.Boolean(config_parameter='dobtor_approval.sla_timer')
    # ... 其餘開關

    # 相依校驗
    @api.constrains(...)
    def _check_feature_dependencies(self):
        deps = {'sla_timer': ['action_gate'], 'escalation': ['cosign'], ...}
        for feat, requires in deps.items():
            if self._is_on(feat) and not all(self._is_on(r) for r in requires):
                raise ValidationError(_("啟用「%s」需先啟用：%s", ...))

class ResCompany(models.Model):
    _inherit = 'res.company'
    def _bpmn_enabled_features(self):
        """回傳 set(feature_keys)，供前端 RPC 與 publish 守門共用"""
        ICP = self.env['ir.config_parameter'].sudo()
        return {k for k in ALL_FEATURES if ICP.get_param(f'dobtor_approval.{k}') == 'True'} \
               | BASE_FEATURES   # T0 永遠在
```
- 前端 RPC：`/dobtor_approval/enabled_features` 回傳 set → 設計器據以過濾調色盤/面板/樣板。
- `FEATURE_LABELS` / `FEATURE_DEPS` / `FEATURE_TIER` 集中於一個 `feature_registry.py`，UI、守門、文件單一來源。

---

## 9. Roadmap 重映射（Tier 交付，可分批上線）

| 交付波 | 內容 | 可賣給誰 |
|--------|------|---------|
| **波 1 (T0)** | 精靈 + 基本線性簽核 + mail.activity | 要最快上線的中小企業 |
| **波 2 (T1+T2)** | 條件/會簽/HR解析/代理 + Action 閘門 | 要綁 Odoo 業務動作的主流客戶 |
| **波 3 (T3+T4)** | 個人化加簽 + 自助設計器 | 要業務自助、台灣加簽文化客戶 |
| **波 4 (T5)** | SLA Timer / Incident / 真會簽 / DMN / 子流程 | 流程複雜、要 SLA 的中大型客戶 |
| **波 5 (T6)** | 治理送審 / scope / 專家 / 遷移 | 大型組織、合規要求高者 |

> 每一波都是「可獨立上線、預設關閉、由客戶按需開啟」的完整段落 —— 不必等全做完才有商品。
