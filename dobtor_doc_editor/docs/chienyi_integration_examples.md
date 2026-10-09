# ChienYi 整合範例（W5-6 P1-2）

**狀態**：W5-6 補強衝刺實作  
**對應漏項**：P1-2 — 與 ChienYi 整合接口完全沒設計  
**完成日期**：2026-05-06

---

## 1. 整合機制總覽

```
ChienYi 模型（construction.meeting.record / supervision.defect ...）
        │
        │ inherit = ['doc.linked.mixin']
        │
        ▼
doc.linked.mixin
        │
        │ 提供：linked_doc_id 欄位、action_open_linked_doc 按鈕
        │ 自動化：第一次點按鈕時建立文件 + 套樣板 + 加協作者
        │
        ▼
doc.document（dobtor_doc_editor 主模型）
        │
        │ 反向關聯：model_id + res_id 雙欄位
        │
        ▼
canvas-editor 線上編輯（後台）/ /my/documents/<id>（portal user）
```

關鍵設計：**ChienYi 模型不直接寫 `doc_id` 欄位**，全部走 mixin。
- 換 dobtor 引擎只需改 mixin
- ChienYi 模型保持輕量，只覆寫 hook methods

## 2. 範例 A：監造會議記錄

### 2.1 ChienYi 端修改

```python
# addons/construction_supervision_base/models/meeting_record.py（假想新模組）
from odoo import models, fields


class MeetingRecord(models.Model):
    _name = 'construction.meeting.record'
    _description = '監造會議記錄'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'doc.linked.mixin']

    name = fields.Char('會議名稱', required=True)
    meeting_date = fields.Date('會議日期', default=fields.Date.context_today)
    location = fields.Char('地點')
    chairperson_id = fields.Many2one('res.users', string='主席')
    recorder_id = fields.Many2one('res.users', string='記錄人',
                                  default=lambda self: self.env.user)
    attendee_ids = fields.Many2many('res.partner', string='出席者')
    project_id = fields.Many2one('supervision.project', string='工程案件')

    # ── 覆寫 doc.linked.mixin hook methods ─────────────────────

    def _doc_default_template_xml_id(self):
        return 'dobtor_doc_editor.template_meeting_record'

    def _doc_initial_name(self):
        return self.name or _('會議記錄_%s') % (self.meeting_date or '')

    def _doc_collaborators(self):
        """主席、記錄人、所有出席者中是 user 的，全部加為協作者。"""
        users = (self.chairperson_id | self.recorder_id)
        users |= self.attendee_ids.mapped('user_ids')
        return users

```

> ### ⚠️ 欄位值怎麼進文件：用藥丸，不要用 context dict
>
> 這份文件原本在這裡示範 `_doc_render_context()` 回一個 dict、範本用
> `{{ subject }}` 取值。**那個機制從來沒有生效**——`_render_template()` 只以
> `object=record` 與 `user` 求值，那個 dict 根本沒被餵進渲染器。實測把出貨
> 範本 render 一張出來，靠它填的格子就是空的。方法已於 2026-10-09 刪除。
>
> 正確做法：
>
> 1. 範本設**適用模型**（`model_id`）＝ 你的業務模型
> 2. 在編輯器左欄把欄位拖進文件 → 取值藥丸（`source='record'`）
> 3. 明細表用重複列（`source='repeat'` ＋ `source='line'`）
> 4. 要組合或計算的值：加 `compute` 欄位，或在模型上實作
>    `doc_report_values()` 回一個 dict，範本裡用 `data.<鍵>`（ADR-025）
>
> 藥丸會過型別格式表（date 走語言格式、monetary 帶幣別、selection 印標籤）、
> 跟著渲染語言、可以條件化、可以逐筆重複。context dict 一個都做不到。
>
> ⚠️ `dobtor_doc_editor_chienyi` 目前還有 6 個模型覆寫 `_doc_render_context()`
>（meeting_record / review_application / reservation_self_inspection /
> general_self_inspection / payment_estimate / supervision_defect）。
> 它們都沒有呼叫 `super()`，所以不會壞——但那 6 支已經是死碼，要在那個 repo
> 清掉並改成上面的做法。

### 2.2 後台 form view 加開啟按鈕

```xml
<!-- addons/construction_supervision_base/views/meeting_record_views.xml -->
<record id="view_meeting_record_form" model="ir.ui.view">
    <field name="name">construction.meeting.record.form</field>
    <field name="model">construction.meeting.record</field>
    <field name="arch" type="xml">
        <form>
            <header>
                <button name="action_open_linked_doc"
                        type="object"
                        string="開啟線上文件"
                        class="oe_highlight"
                        icon="fa-file-text-o"/>
            </header>
            <sheet>
                <div class="oe_button_box" name="button_box">
                    <button name="action_open_linked_doc"
                            type="object"
                            class="oe_stat_button"
                            icon="fa-file-text-o"
                            invisible="linked_doc_count == 0">
                        <field name="linked_doc_count" widget="statinfo"
                               string="線上文件"/>
                    </button>
                </div>
                <!-- ... 其他欄位 ... -->
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

### 2.3 使用流程

1. Internal user 在後台建立會議記錄、填入出席者
2. 點「開啟線上文件」 → mixin 自動：
   - 從 `template_meeting_record` 複製內容到新 doc.document
   - Jinja 把欄位填入（會議日期、出席者、主席...）
   - 把出席者中的 user 全部加為 `collaborator_ids`
3. portal user（出席的承包商代表）登入 → `/my/documents` 看到此文件 → 線上補充討論內容
4. 會後 internal user 確認 → 用既有版本管理鎖定（W7-8 補完）

## 3. 範例 B：自主檢查表

### 3.1 ChienYi 端修改

```python
# addons/construction_quality/models/general_self_inspection.py（擴充既有 model）
class GeneralSelfInspection(models.Model):
    _name = 'general.self.inspection'
    _inherit = ['general.self.inspection', 'doc.linked.mixin']  # 多重繼承

    def _doc_default_template_xml_id(self):
        return 'dobtor_doc_editor.template_self_inspection'

    def _doc_collaborators(self):
        """檢查人員 + 承包商代表全部加為協作者。"""
        return (self.inspector_id | self.contractor_company_id.user_ids)

    # 欄位值不要在這裡組 dict（見 §2.1 的框）。
    # project_name / inspection_date / inspector / contractor 都是欄位路徑，
    # 直接在編輯器裡拖成取值藥丸就好——而且 date 會自動走語言格式、
    # timing 這種 selection 會自動印標籤，不必自己 dict(...).get()。
```

### 3.2 與既有 QWeb 報表並存

self.inspection 既有的 QWeb PDF 報表**不動**：
- QWeb 報表用於「定稿後簽核列印」（依決策 §3 表格第二列：範本欄位固定+簽核 → 用 QWeb）
- dobtor 整合用於「現場檢查當下協作填表」（範本欄位固定+簽核但**也需要協作** → 用 dobtor）
- 兩者並存：使用者依場景選

## 4. 範例 C：缺失改善通知（不整合，保留 QWeb）

依 [scope_decision.md](scope_decision.md) §7：

> | 缺失改善通知書 | QWeb | 若需照片現場標註才轉 dobtor |

**目前不做整合**。若未來決定加上去，照範例 A 模式覆寫 hook 即可（樣板已備：`template_defect_improvement`）。

## 5. 反向 lookup 範例

需求：portal 控制器要從 doc_id 反查回「這份文件對應的會議記錄」做權限二次驗證。

```python
# 在 portal controller 內
@http.route(['/my/documents/<int:doc_id>'], type='http', auth='user', website=True)
def portal_document_view(self, doc_id, **kw):
    doc = request.env['doc.document'].browse(doc_id).exists()
    if not doc or not doc.model_id:
        return super().portal_document_view(doc_id, **kw)

    # 反向 lookup
    target_model = doc.model_id.model  # e.g., 'construction.meeting.record'
    Model = request.env.get(target_model)
    if Model and 'doc.linked.mixin' in Model._inherit:
        record = Model.browse(doc.res_id).exists()
        if record:
            # 額外的業務權限檢查（如：會議記錄需是出席者）
            ...

    return super().portal_document_view(doc_id, **kw)
```

## 6. 整合驗收條件（給 QA / W11+ 用）

- [ ] `construction.meeting.record` 後台建立後可一鍵生成線上文件
- [ ] 樣板欄位（會議日期、出席者）正確填入
- [ ] 出席者中的 user 自動成為協作者
- [ ] portal user 登入 `/my/documents` 看到文件
- [ ] 第二次點「開啟線上文件」不會建立新文件，而是開既有的
- [ ] 把出席者移除後，已建立的協作者**不**被自動移除（避免誤刪歷史）
- [ ] 反向 lookup `doc.model_id` + `doc.res_id` 能回查到原始 record

## 7. 後續整合候選清單

依 scope_decision §7 與監造系統實際需求，整合優先順序：

| 優先 | ChienYi 模型 | 樣板 | W11+ 啟用 |
|---|---|---|---|
| P0 | construction.meeting.record（待建） | template_meeting_record | ✅ 必做 |
| P1 | general.self.inspection | template_self_inspection | ✅ 建議做 |
| P2 | reservation.self.inspection | template_self_inspection | 看用量 |
| P3 | payment.estimate | template_payment_estimate | 觀察期 |
| P4 | supervision.defect | template_defect_improvement | 預設不做（QWeb 為主） |

---

**附註**：此設計對應規劃文件 `dobtor_doc_editor_高保真匯入開發規劃.md` 的 §5.5b Phase 4.5 P1-2，與 plan `d-work-doc-editor-pure-duckling.md` 的 W5-6 段。實際 ChienYi 端 model 改動屬於 W11+ 主線範圍，本次只提供 mixin + 樣板 + 整合範例。
