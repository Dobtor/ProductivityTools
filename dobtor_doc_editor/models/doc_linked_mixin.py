"""doc.linked.mixin（W5-6 P1-2）

讓任何 ChienYi 模型可以「關聯」一份 dobtor_doc_editor 文件，並提供：
- 文件自動建立（從預設樣板或指定樣板）
- 欄位自動填充（透過 Jinja context）
- 協作者自動加入（如：會議記錄出席者自動成為協作者）

使用方式：
    # construction_supervision_base/models/meeting_record.py
    class MeetingRecord(models.Model):
        _name = 'construction.meeting.record'
        _inherit = ['mail.thread', 'doc.linked.mixin']

        meeting_date = fields.Date()
        attendees = fields.Many2many('res.partner')

        # 覆寫 mixin method 提供樣板選擇與協作者
        def _doc_default_template_xml_id(self):
            return 'dobtor_doc_editor.template_meeting_record'

        def _doc_collaborators(self):
            return self.attendees.user_ids

欄位值怎麼進文件：**用藥丸，不要用 context dict**。
    1. 範本設「適用模型」= construction.meeting.record
    2. 在編輯器左欄把 meeting_date / name 這些欄位拖進去（取值藥丸）
    3. 要組合或計算的值，加 compute 欄位，或在模型上實作
       doc_report_values() 回一個 dict，範本裡用 data.<鍵>

藥丸會過型別格式表（date 走語言格式、monetary 帶幣別）、跟著渲染語言、
可以條件化。這些都是 Jinja context dict 做不到的——而且舊的
_doc_render_context() 從來沒有被餵進渲染器，靠它填的格子一直是空的。

設計原則：
    - 「pull-on-demand」：使用者點「開啟線上文件」才建立，避免一堆空文件
    - mixin 不知道 ChienYi 業務細節：所有 ChienYi 邏輯走 hook method 由 inheriting model 覆寫
    - 不破壞既有 QWeb 報表：mixin 不接管 print 流程，只新增「線上編輯」入口
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DocLinkedMixin(models.AbstractModel):
    """讓任何模型可關聯一份 doc.document 文件。

    繼承此 mixin 的模型會獲得：
        - linked_doc_id: Many2one to doc.document
        - linked_doc_count: Integer compute（給 button 顯示「1 份線上文件」）
        - action_open_linked_doc(): 開啟（必要時建立）線上文件
    """

    _name = 'doc.linked.mixin'
    _description = '可連結 dobtor_doc_editor 文件的 mixin'

    linked_doc_id = fields.Many2one(
        'doc.document',
        string='線上文件',
        help='與此記錄關聯的 dobtor_doc_editor 線上文件。'
             '第一次點「開啟線上文件」按鈕時自動建立。',
        copy=False,
        ondelete='set null',
    )
    linked_doc_count = fields.Integer(
        compute='_compute_linked_doc_count',
        string='線上文件數',
    )

    @api.depends('linked_doc_id')
    def _compute_linked_doc_count(self):
        for rec in self:
            rec.linked_doc_count = 1 if rec.linked_doc_id else 0

    # ─── 報表輸出紀錄（報表引擎）────────────────────────────────────
    #
    # 刻意不在業務表上新增欄位：輸出紀錄用 res_model + res_id 反查即可。
    # 這裡只提供一個非儲存的計數與一個動作，讓繼承本 mixin 的模型
    # 可以在 form view 掛智慧按鈕。
    #
    # 沒有自動 patch sale.order / purchase.order——那會讓本模組相依 sale / purchase。
    # 要在銷售單上看到按鈕，在該模型加一行 _inherit = ['doc.linked.mixin'] 即可。

    doc_output_count = fields.Integer(
        string='列印紀錄數',
        compute='_compute_doc_output_count',
    )

    # ─── 這一筆記錄自己的報表設定（報表引擎）────────────────────────
    #
    # 綁定（doc.report）管的是「這張報表用哪張範本、附哪幾頁」，依報表＋語言＋
    # 公司決定。但有些事只有**這一筆**知道：
    #
    #   * 這張單要附它自己上傳的檢驗報告（每筆不同）
    #   * 只有這一張合約要附標準條款（其他不要）
    #   * 這一筆用特別的範本（客戶指定的版面）
    #
    # 三個都走「約定方法」，所以沒有繼承本 mixin 的模型也能自己實作；
    # 本 mixin 只是順便提供欄位與預設實作，讓繼承者有現成的 UI 開關。
    # 約定方法的名字在 doc.report 那邊（_RECORD_HOOKS），要改一起改。

    doc_append_pages = fields.Boolean(
        string='附加附頁',
        default=True,
        copy=False,
        help='這一筆列印時要不要接上綁定設定的附頁。\n'
             '只有在綁定的「附頁適用範圍」設成依記錄決定時才會被看。',
    )
    doc_report_template_id = fields.Many2one(
        'doc.template',
        string='指定列印範本',
        domain="[('role', '=', 'content')]",
        copy=False,
        ondelete='set null',
        help='只有這一筆改用別的範本（客戶指定的版面）。\n'
             '留空＝用綁定設定的那一張。模型對不上時會被忽略並留下伺服器紀錄。',
    )

    def doc_report_append_enabled(self):
        """這一筆要不要接附頁。預設讀 doc_append_pages 欄位。"""
        self.ensure_one()
        return bool(self.doc_append_pages)

    def doc_report_template(self):
        """這一筆要用的範本；回空＝用綁定那一張。"""
        self.ensure_one()
        return self.doc_report_template_id

    def doc_report_append_pdfs(self):
        """這一筆自己要附的 PDF。

        預設回空——「哪些附件該印」是業務問題，猜錯會把不該外流的檔案印進
        客戶拿到的單據裡。繼承者自己覆寫，例如：

            def doc_report_append_pdfs(self):
                return self.attachment_ids.filtered(
                    lambda a: a.mimetype == 'application/pdf'
                              and a.name.startswith('檢驗報告'))

        回傳可以是 ir.attachment 的 recordset，也可以是一串 bytes。
        """
        return self.env['ir.attachment'].browse()

    def _compute_doc_output_count(self):
        Output = self.env['doc.output']
        if not self.ids:
            for rec in self:
                rec.doc_output_count = 0
            return
        data = Output._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)],
            groupby=['res_id'],
            aggregates=['__count'],
        )
        mapped = dict(data)
        for rec in self:
            rec.doc_output_count = mapped.get(rec.id, 0)

    # ⚠️ 下面兩支 action 本模組內沒有呼叫者，它們是**給整合者的 API**：
    # 繼承本 mixin 的模型在自己的 form view 上掛智慧按鈕時用名稱引用。
    # 死碼稽核會列出來——判斷依據是「有沒有別的模組引用」，不是「本模組有沒有」。
    def action_view_doc_outputs(self):
        """開啟此記錄的列印紀錄清單。

        看得到哪些由 record rule 決定：一般使用者只看自己列印的，
        管理者看全部（見 security/doc_security.xml 的取捨說明）。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('列印紀錄'),
            'res_model': 'doc.output',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
            'context': {'create': False},
        }

    # ─── Hook methods（由繼承的 model 覆寫）──────────────────────────

    def _doc_default_template_xml_id(self):
        """回傳預設樣板的 XML id（如 'dobtor_doc_editor.template_meeting_record'）。

        若 None → 建立空白文件
        若 model 已 commit 一個樣板，直接覆寫此方法回傳 xml_id 即可。
        """
        self.ensure_one()
        return None

    def _doc_collaborators(self):
        """回傳要自動加入為協作者的 res.users recordset。

        預設：只有建立者；繼承的 model 可覆寫加入更多。
        例：會議記錄回傳 attendees.user_ids、缺失改善回傳 responsible_user_id 等
        """
        self.ensure_one()
        return self.env.user

    # ─── 刻意**沒有** _doc_render_context() ─────────────────────────
    #
    # 2026-10-09 刪掉。它的 docstring 寫著「回傳 Jinja 填充用的 context dict」，
    # 但**從來沒有任何消費者**：_render_template() 只以 object=record 與
    # user 求值，那個 dict 根本沒有被餵進去。實測把出貨範本 render 一張出來，
    # 靠它填的那幾格就是空的。
    #
    # 正確做法是藥丸：給範本設「適用模型」，再用取值藥丸綁欄位路徑
    #（source='record' / 'line'），複雜的計算走模型自己的 compute 欄位或
    # doc_report_values()。藥丸會過型別格式表、跟著渲染語言、可以條件化，
    # 這些 context dict 一個都做不到。
    #
    # 刪除前確認過：外部模組對這支的覆寫都是「完全取代、不呼叫 super()」，
    # 所以拿掉基底實作不會讓它們壞；那些覆寫只是變成各自模組裡的死碼。
    # 本模組不追蹤誰覆寫了它——那是各整合模組自己的事。

    def _doc_initial_name(self):
        """新建立的文件名稱。"""
        self.ensure_one()
        return self.display_name or _('未命名文件')

    # ─── 主要對外方法 ──────────────────────────────────────────────

    def action_open_linked_doc(self):
        """打開（必要時建立）線上文件。

        回傳 ir.actions.act_window，後台 form 上 button 直接 type="object"
        + name="action_open_linked_doc" 即可。
        """
        self.ensure_one()
        if not self.linked_doc_id:
            self.linked_doc_id = self._create_linked_doc()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'doc.document',
            'res_id': self.linked_doc_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_linked_doc_portal(self):
        """portal user 用：回傳 redirect 到 /my/documents/<id>。"""
        self.ensure_one()
        if not self.linked_doc_id:
            # portal user 不能 create，必須由 internal user 先觸發
            raise UserError(_(
                '此記錄尚未建立線上文件，請聯絡系統內部人員先建立。'
            ))
        return {
            'type': 'ir.actions.act_url',
            'url': '/my/documents/%d' % self.linked_doc_id.id,
            'target': 'self',
        }

    # ─── 內部建立邏輯 ─────────────────────────────────────────────

    def _create_linked_doc(self):
        """根據 hook methods 建立 doc.document。

        步驟：
            1. 取樣板（若 _doc_default_template_xml_id 有回傳）
            2. 建立 doc.document，套樣板內容
            3. 加 collaborators
            4. 把當前 record 的 model+id 寫入 doc 的 metadata（之後可雙向 lookup）
        """
        self.ensure_one()
        Doc = self.env['doc.document'].sudo()

        vals = {
            'name': self._doc_initial_name(),
            'company_id': self.env.company.id,
        }

        # 從樣板複製 content（若有）
        # 走 template_id：doc.document.create 內 _onchange-style 邏輯會自動把
        # template.content_html / page_format 複製到新文件（見 doc_document.py:375-381）
        # 比直接 vals['content_html'] = template.body 更穩（doc.template 欄位是
        # content_html 不是 body；Sprint 21 修正）
        template_xml_id = self._doc_default_template_xml_id()
        if template_xml_id:
            template = self.env.ref(template_xml_id, raise_if_not_found=False)
            if template and 'template_id' in Doc._fields:
                vals['template_id'] = template.id

        # 把關聯 metadata 寫進文件（允許未來反查 doc → record）
        if 'model_id' in Doc._fields:
            model_record = self.env['ir.model'].sudo().search(
                [('model', '=', self._name)], limit=1
            )
            if model_record:
                vals['model_id'] = model_record.id
        if 'res_id' in Doc._fields:
            vals['res_id'] = self.id

        doc = Doc.create(vals)

        # Phase 3（藥丸改版）：建立時快照。
        # 決策一——值在此凍結一次，之後改業務記錄不會動到已產生的文件。
        # create() 內的 onchange 邏輯已把範本的 content_json 複製過來，
        # 此時才有東西可以求值，順序不可對調。
        try:
            doc._apply_value_snapshot(record=self)
        except Exception as e:
            # 快照失敗不該讓「建立文件」整個失敗——文件仍可用，
            # 使用者可在編輯器按「重新帶值」補救。
            _logger.warning(
                "[doc.linked.mixin] value snapshot failed for %s(%s): %s",
                self._name, self.id, e,
            )

        # 加協作者
        try:
            collaborators = self._doc_collaborators()
            if collaborators:
                doc.collaborator_ids = [(6, 0, collaborators.ids)]
        except Exception as e:
            _logger.warning(
                "[doc.linked.mixin] _doc_collaborators failed for %s(%s): %s",
                self._name, self.id, e,
            )

        return doc

    # ─── 反向 lookup（doc → record） ──────────────────────────────

    @api.model
    def _get_record_from_linked_doc(self, doc_id):
        """從 doc_id 反查回原始 record。

        前提：建立時 _create_linked_doc() 有寫入 model_id + res_id 到 doc.document。

        ⚠️ **本模組內沒有呼叫者，但它是給整合模組用的公開 API**（有外部模組
        在用）。死碼稽核會把它列出來——判斷依據是「**本模組之外**有沒有引用」，
        不是「本模組內有沒有」。要刪之前先掃過所有相依模組。
        """
        Doc = self.env['doc.document'].sudo()
        if 'model_id' not in Doc._fields or 'res_id' not in Doc._fields:
            return self.browse()
        doc = Doc.browse(doc_id).exists()
        if not doc or not doc.res_id or not doc.model_id:
            return self.browse()
        if doc.model_id.model != self._name:
            return self.browse()
        return self.browse(doc.res_id).exists()
