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

        # 覆寫 mixin method 提供樣板選擇與 context
        def _doc_default_template_xml_id(self):
            return 'dobtor_doc_editor.template_meeting_record'

        def _doc_collaborators(self):
            return self.attendees.user_ids

        def _doc_render_context(self):
            self.ensure_one()
            return {
                'meeting_date': self.meeting_date.strftime('%Y-%m-%d'),
                'attendees': self.attendees.mapped('name'),
                'subject': self.name,
            }

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

    def _doc_render_context(self):
        """回傳 Jinja 填充用的 context dict。

        繼承的 model 覆寫此方法把自己的欄位塞進去。
        """
        self.ensure_one()
        return {
            'record_id': self.id,
            'record_model': self._name,
            'record_name': self.display_name or '',
        }

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
