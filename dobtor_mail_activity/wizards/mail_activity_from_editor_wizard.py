# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityFromEditorWizard(models.TransientModel):
    """從富文字編輯器斜線選單建立待辦精靈

    功能說明:
    - 由 html_editor 的 powerbox（/ 斜線選單）「建立待辦」指令開啟
    - 摘要由游標所在段落（"/" 之前的整段文字）帶入 default_summary
    - 支援「目標文件」(target_ref → res_model/res_id) 與「關聯筆記」(note_id)
      兩個各自獨立的關聯，依建立情境給不同預設值：

      情境 A（在待辦筆記 note.note 內建立）：
        target_ref 預設 = 這本筆記（可另選其他 res_model/res_id）
        note_id    預設 = 這本筆記
        → 待辦永遠出現在這本筆記的內嵌清單（清單綁 note_id）

      情境 B（在非待辦筆記記錄如 sale.order 內建立）：
        target_ref 預設 = 該記錄（chatter 看得到）
        note_id    預設 = 使用者個人待辦筆記（可另選其他筆記）
        → 雙關聯：記錄 chatter + 個人待辦清單兩邊都看得到

      情境 C（編輯器無對應記錄，如 settings/新建未存檔）：
        target_ref 留空、note_id 預設 = 個人待辦筆記
    """
    _name = 'mail.activity.from.editor.wizard'
    _description = 'Create Activity from Rich Text Editor Wizard'

    # ===== 目標與筆記（兩個獨立關聯）=====
    target_ref = fields.Reference(
        string='Target Document',
        selection='_selection_target_model',
        help='Business document this activity is attached to (its chatter shows the clock).',
    )
    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        help='Note whose to-do list will show this activity (independent of the target document).',
    )

    # ===== 待辦設定 =====
    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string='Activity Type',
        required=True,
        default=lambda self: self._default_activity_type(),
    )
    summary = fields.Char(string='Summary')
    note = fields.Html(string='Note')
    date_deadline = fields.Date(
        string='Deadline',
        required=True,
        default=fields.Date.context_today,
    )
    estimated_hours = fields.Float(string='Estimated Hours', default=1.0)
    urgency = fields.Selection([
        ('urgent', 'Urgent'),
        ('standard', 'Standard'),
        ('flexible', 'Flexible'),
    ], string='Urgency', default='standard', required=True)
    importance = fields.Selection([
        ('important', 'Important'),
        ('normal', 'Normal'),
    ], string='Importance', default='normal', required=True)
    user_id = fields.Many2one(
        'res.users',
        string='Assign To',
        help='If not assigned, activity will wait to be claimed',
    )

    @api.model
    def _default_activity_type(self):
        """預設待辦類型：待辦事項"""
        return self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

    @api.model
    def _selection_target_model(self):
        """取得允許的目標模型選項（與其他 wizard 共用同一份設定）"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.model
    def default_get(self, fields_list):
        """依編輯器情境帶入 summary / note 與 target_ref / note_id 預設值

        編輯器（powerbox 指令）透過 context 傳入：
          - default_summary：游標所在段落（"/" 之前的整段文字）
          - default_note：可選的備註 HTML
          - default_editor_res_model / default_editor_res_id：編輯器所在記錄
        """
        res = super().default_get(fields_list)
        ctx = self.env.context

        res_model = ctx.get('default_editor_res_model')
        res_id = ctx.get('default_editor_res_id')
        try:
            res_id = int(res_id) if res_id else False
        except (ValueError, TypeError):
            res_id = False

        allowed_models = {m for m, _n in self._selection_target_model()}

        if res_model and res_id and res_model in allowed_models:
            # 確認記錄存在再帶入，避免 Reference 指向不存在記錄
            target = self.env[res_model].browse(res_id)
            if target.exists():
                if 'target_ref' in fields_list:
                    res['target_ref'] = '%s,%s' % (res_model, res_id)
                # 關聯筆記預設：A 情境=本筆記、B 情境=個人筆記
                if 'note_id' in fields_list and not res.get('note_id'):
                    res['note_id'] = res_id if res_model == 'note.note' \
                        else self._default_personal_note_id()

        # 情境 C、無來源、或來源模型不在允許清單：關聯筆記退回個人待辦筆記
        if 'note_id' in fields_list and not res.get('note_id'):
            res['note_id'] = self._default_personal_note_id()

        return res

    @api.model
    def _default_personal_note_id(self):
        """使用者的個人待辦筆記 id（無則建立）"""
        note = self.env.user._get_or_create_default_activity_note()
        return note.id if note else False

    def _validate_create(self):
        """驗證建立操作"""
        self.ensure_one()
        if not self.activity_type_id:
            raise UserError(_('Please select an activity type.'))
        if not self.date_deadline:
            raise UserError(_('Please select a deadline.'))
        if self.target_ref and not self.target_ref.exists():
            raise UserError(_('Target record does not exist.'))

    def _prepare_activity_values(self):
        """準備建立待辦的值（資料關聯與既有設計一致：target_ref→res + note_id）

        - 有選 target_ref → res_model/res_id = 該文件，note_id = 所選筆記
        - 未選 target_ref 但有 note_id → res = 該筆記（避免 create() fallback 蓋掉所選筆記）
        - 兩者皆空 → 不設 res，交由 mail.activity.create() 自動掛個人待辦筆記

        partner_id / res_name 由 mail.activity 依 res 自動衍生，不在此設定。
        """
        self.ensure_one()
        vals = {
            'activity_type_id': self.activity_type_id.id,
            'summary': self.summary,
            'note': self.note,
            'date_deadline': self.date_deadline,
            'estimated_hours': self.estimated_hours,
            'urgency': self.urgency,
            'importance': self.importance,
        }
        if self.user_id:
            vals['user_id'] = self.user_id.id
        # note_id 為獨立關聯，無論目標為何都一併寫入
        if self.note_id:
            vals['note_id'] = self.note_id.id

        if self.target_ref:
            model_id = self.env['ir.model']._get(self.target_ref._name)
            vals['res_model_id'] = model_id.id
            vals['res_id'] = self.target_ref.id
        elif self.note_id:
            # 僅有筆記、無目標文件：把目標也設為該筆記，避免 create() 自動 fallback
            vals['res_model_id'] = self.env['ir.model']._get('note.note').id
            vals['res_id'] = self.note_id.id
        # else：res 全空 → create() 自動關聯個人待辦筆記

        return vals

    def action_create_activity(self):
        """建立待辦並回傳新待辦 id（供前端插入回饋膠囊/刷新清單）"""
        self.ensure_one()
        self._validate_create()
        activity = self.env['mail.activity'].create(self._prepare_activity_values())
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {
                'activity_id': activity.id,
                'res_model': activity.res_model,
                'res_id': activity.res_id,
                'note_id': activity.note_id.id,
            },
        }
