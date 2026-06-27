# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityCreateWizard(models.TransientModel):
    """統一「建立待辦」精靈 —— 繼承官方 mail.activity.schedule 擴充。

    所有建立待辦入口共用此單一畫面：
      - 編輯器 powerbox /建立待辦、編輯器內嵌清單 Add to-do
      - chatter 訊息「建立待辦」
      - 各視圖（My Activities…）的 New
      - 文件 chatter 原生「排程活動」(由 store.scheduleActivity 導向)

    以原型繼承（_name 不同於 _inherit）建立獨立模型，沿用官方所有欄位與
    建立路徑（activity_schedule），但不動到官方模型/視圖（避免全域影響
    plan/batch 與其他模組的排程活動）。

    目標文件（res）兩種情境：
      - 已知（context 帶 active_model/active_id）：res_known=True，唯讀顯示
        目標，不顯示輸入。
      - 未知：res_known=False，顯示 target_ref 輸入；留空 → fallback 使用者
        個人待辦筆記（與舊 editor wizard 一致）。

    note_id 為獨立關聯，各情境皆可編輯。urgency / importance /
    estimated_hours / note_id 透過 activity_schedule 的 **act_values 寫入
    mail.activity（皆為本模組既有欄位）。
    """
    _name = 'mail.activity.create.wizard'
    _inherit = 'mail.activity.schedule'
    _description = 'Create To-do Wizard'

    # ===== 目標已知 / 未知 =====
    res_known = fields.Boolean(string='Target Known')
    res_display = fields.Char(string='Target Document', compute='_compute_res_display')
    target_ref = fields.Reference(
        string='Target Document',
        selection='_selection_target_model',
        help='Business document this activity is attached to. '
             'Leave empty to use your personal to-do note.',
    )
    # 由 note.note 編輯器建立時：不自動帶入 res，但要求必選目標文件（res_id 必填）。
    target_required = fields.Boolean(
        string='Target Required',
        help='When set (e.g. created from a note editor), a target document '
             'must be chosen instead of falling back to the personal note.',
    )

    # ===== 獨立關聯筆記 =====
    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        help='Note whose to-do list will show this activity '
             '(independent of the target document).',
    )

    # ===== 來源訊息（由訊息建立時保留追蹤）=====
    source_message_id = fields.Many2one('mail.message', string='Source Message')

    # ===== 自訂待辦欄位 =====
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

    @api.model
    def _selection_target_model(self):
        """允許的目標模型（與其他 wizard 共用同一份設定）。"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.depends('res_model', 'res_ids')
    def _compute_res_display(self):
        """已知情境下唯讀顯示目標文件名稱。"""
        for wiz in self:
            names = []
            if wiz.res_model and wiz.res_ids:
                try:
                    recs = wiz.env[wiz.res_model].browse(wiz._evaluate_res_ids()).exists()
                    names = [n for n in recs.mapped('display_name') if n]
                except Exception:
                    names = []
            wiz.res_display = ', '.join(names)

    @api.depends('activity_type_id')
    def _compute_date_deadline(self):
        """覆寫官方：建立待辦預設截止日固定為「今天」，不採活動類型的延遲天數
        （官方會用 activity_type._get_date_deadline()，To-Do 類型為今天+5）。"""
        for wiz in self:
            wiz.date_deadline = fields.Date.context_today(wiz)

    @api.model
    def default_get(self, fields_list):
        ctx = self.env.context
        active_model = ctx.get('active_model')
        active_id = ctx.get('active_id')
        # context 明確帶入真實文件即「已知 res」（原生 chatter / 內嵌清單 / 訊息）；
        # 排除泛型清單與 wizard 自身（各視圖 New / systray / 編輯器 → 未知，顯示輸入）。
        # 不限縮在 allowed 目標清單，以免原生 chatter 在未列入清單的模型上遺失目標。
        blacklist = ('mail.activity', 'mail.activity.create.wizard', 'mail.activity.schedule')
        is_known = bool(
            active_model and active_id
            and active_model not in blacklist
        )

        res = super().default_get(fields_list)
        res['res_known'] = is_known

        if not is_known:
            # 未知：res 先放個人待辦筆記，確保官方 res_model(required)/res_model_id
            # compute 不出錯；建立時若使用者選了 target_ref 會以其為準。
            note = self.env.user._get_or_create_default_activity_note()
            if note:
                if 'res_model' in fields_list:
                    res['res_model'] = 'note.note'
                if 'res_ids' in fields_list:
                    res['res_ids'] = str([note.id])

        # note_id 預設（獨立關聯）
        if 'note_id' in fields_list and not res.get('note_id'):
            note_id = ctx.get('default_note_id')
            if note_id:
                res['note_id'] = note_id
            elif active_model == 'note.note' and active_id:
                res['note_id'] = active_id
            else:
                note = self.env.user._get_or_create_default_activity_note()
                res['note_id'] = note.id if note else False

        # 待辦類型預設：待辦事項
        if 'activity_type_id' in fields_list and not res.get('activity_type_id'):
            todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if todo:
                res['activity_type_id'] = todo.id

        return res

    def _get_applied_on_records(self):
        """未知情境且使用者已選 target_ref → 以其為建立目標；否則沿用官方
        （res_model/res_ids，未選時即個人待辦筆記）。"""
        self.ensure_one()
        if not self.res_known and self.target_ref:
            return self.target_ref
        return super()._get_applied_on_records()

    def _action_schedule_activities(self):
        """沿用官方建立路徑，額外帶入本模組自訂欄位與獨立關聯筆記。"""
        act_values = {
            'urgency': self.urgency,
            'importance': self.importance,
            'estimated_hours': self.estimated_hours,
        }
        if self.note_id:
            act_values['note_id'] = self.note_id.id
        if self.source_message_id:
            act_values['source_message_id'] = self.source_message_id.id
        return self._get_applied_on_records().activity_schedule(
            activity_type_id=self.activity_type_id.id,
            automated=False,
            summary=self.summary,
            note=self.note,
            user_id=self.activity_user_id.id,
            date_deadline=self.date_deadline,
            **act_values,
        )

    def action_create_todo(self):
        """建立待辦並回傳新待辦 id（供編輯器插入回饋膠囊 / 清單刷新）。"""
        self.ensure_one()
        if not self.activity_type_id:
            raise UserError(_('Please select an activity type.'))
        if not self.date_deadline:
            raise UserError(_('Please select a deadline.'))
        if self.target_required and not self.res_known and not self.target_ref:
            raise UserError(_('Please select a target document.'))
        if not self.res_known and self.target_ref and not self.target_ref.exists():
            raise UserError(_('Target record does not exist.'))

        activities = self._action_schedule_activities()
        activity = activities[:1]
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {
                'activity_id': activity.id,
                'res_model': activity.res_model,
                'res_id': activity.res_id,
                'note_id': activity.note_id.id,
            },
        }
