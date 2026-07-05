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
      - 未知：res_known=False，顯示 target_ref 輸入；留空 → 建立無關聯的
        獨立待辦（需求七：不再 fallback 預設個人筆記本）。

    note_id 為獨立關聯，各情境皆可編輯。urgency / importance /
    estimated_hours / note_id 透過 activity_schedule 的 **act_values 寫入
    mail.activity（皆為本模組既有欄位）。
    """
    _name = 'mail.activity.create.wizard'
    _inherit = 'mail.activity.schedule'
    _description = 'Create To-do Wizard'

    # 需求七：res-less 獨立待辦。官方 mail.activity.schedule 把 res_model /
    # res_model_id 設為 required=True 且僅由 context 的 active_model 填值，但
    # systray「Create To-do」與編輯器 powerbox 入口皆不帶 active_model，會使
    # 這兩個必填欄位存 NULL → 存檔失敗。與 mail_activity.py 對 mail.activity 的
    # res_model_id 覆寫一致，此處放寬為非必填（留空 → fallback 個人待辦筆記）。
    res_model = fields.Char(required=False)
    # 覆寫為可寫（移除官方 _compute_res_model_id），供關聯圖 widget 回填 res_model_id
    res_model_id = fields.Many2one(
        'ir.model', required=False, compute=False, readonly=False)
    # 單一關聯文件 id（供關聯圖 widget 與 target_ref 同步）
    res_id = fields.Many2oneReference(
        string='Related Document ID', model_field='res_model')

    # ===== 客戶 / 專案（與 mail.activity form 一致；選 res 後可自動帶入）=====
    partner_id = fields.Many2one('res.partner', string='Customer')
    project_id = fields.Many2one('project.project', string='Project')

    # 關聯圖錨點（dummy Boolean，供 activity_relation_diagram widget 綁定）
    relation_diagram_anchor = fields.Boolean(default=False)

    # ===== 目標已知 / 未知 =====
    res_known = fields.Boolean(string='Target Known')
    res_display = fields.Char(string='Target Document', compute='_compute_res_display')
    target_ref = fields.Reference(
        string='Target Document',
        selection='_selection_target_model',
        help='Business document this activity is attached to. '
             'Leave empty to create a standalone to-do.',
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
        """覆寫官方：建立待辦預設截止日「今天」，不採活動類型的延遲天數
        （官方會用 activity_type._get_date_deadline()，To-Do 類型為今天+5）。
        僅在尚未設定時填今天，避免使用者手改後又換活動類型被 compute 覆蓋。"""
        for wiz in self:
            if not wiz.date_deadline:
                wiz.date_deadline = fields.Date.context_today(wiz)

    # ===== 關聯文件 ↔ target_ref 同步 + 客戶/專案連動 =====

    @api.onchange('res_model_id', 'res_id')
    def _onchange_wizard_res(self):
        """關聯圖選節點（設 res_model_id + res_id）→ 同步 res_model / target_ref，
        並由文件反推帶入 專案/客戶（僅填空欄，不覆蓋已選）。"""
        for wiz in self:
            model_name = wiz.res_model_id.model or False
            if wiz.res_model != model_name:
                wiz.res_model = model_name
            if model_name and wiz.res_id:
                ref = '%s,%s' % (model_name, wiz.res_id)
                if wiz.target_ref != ref:
                    wiz.target_ref = ref
                wiz._wizard_fill_project_partner()

    @api.onchange('target_ref')
    def _onchange_wizard_target_ref(self):
        """手動選 target_ref → 同步 res_model_id/res_id/res_model（供關聯圖標示），
        並反推帶入 專案/客戶。清空 target_ref → 一併清空 res。"""
        for wiz in self:
            if wiz.target_ref:
                model_rec = wiz.env['ir.model']._get(wiz.target_ref._name)
                if wiz.res_model_id.id != model_rec.id:
                    wiz.res_model_id = model_rec.id
                if wiz.res_id != wiz.target_ref.id:
                    wiz.res_id = wiz.target_ref.id
                wiz.res_model = wiz.target_ref._name
                wiz._wizard_fill_project_partner()
            elif wiz.res_id or wiz.res_model_id:
                wiz.res_model_id = False
                wiz.res_id = False
                wiz.res_model = False

    @api.onchange('project_id')
    def _onchange_wizard_project(self):
        """選/改專案 → 客戶空則以專案客戶帶入（不覆蓋已選客戶）。"""
        for wiz in self:
            if wiz.project_id and not wiz.partner_id and wiz.project_id.partner_id:
                wiz.partner_id = wiz.project_id.partner_id.id

    def _wizard_fill_project_partner(self):
        """選定 res 後：專案/客戶「空時」由文件反推帶入（不覆蓋使用者已選）。

        規則對照使用者確認之情境：
          選客戶先 → 選 doc → 帶入專案（客戶已填、保持）
          選專案先 → 選 doc → 帶入客戶（專案已填、保持）
        重用 mail.activity 的 _project_from_res / _partner_from_res。
        """
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return
        Act = self.env['mail.activity']
        if not self.project_id:
            project = Act._project_from_res(self.res_model, self.res_id)
            if project:
                self.project_id = project.id
        if not self.partner_id:
            partner_id = Act._partner_from_res(self.res_model, self.res_id)
            if partner_id:
                self.partner_id = partner_id

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

        # 需求七：未知情境不再回填預設筆記；未選 target_ref 即建立「獨立待辦」
        # （res 為空），由 _action_schedule_activities 直接建立 mail.activity。

        # note_id 預設（來源參考）：僅在 context 明確帶入、或編輯 note.note 時帶入
        if 'note_id' in fields_list and not res.get('note_id'):
            note_id = ctx.get('default_note_id')
            if note_id:
                res['note_id'] = note_id
            elif active_model == 'note.note' and active_id:
                res['note_id'] = active_id

        # 待辦類型預設：待辦事項
        if 'activity_type_id' in fields_list and not res.get('activity_type_id'):
            todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if todo:
                res['activity_type_id'] = todo.id

        return res

    def _get_applied_on_records(self):
        """未知情境且使用者已選 target_ref → 以其為建立目標；已知情境沿用官方。
        需求七：未知且未選 target_ref → 回傳空集合（建立獨立待辦，無關聯文件）。"""
        self.ensure_one()
        if not self.res_known and self.target_ref:
            return self.target_ref
        if not self.res_known:
            # 無目標文件 → 獨立待辦
            return self.env['mail.activity'].browse()
        return super()._get_applied_on_records()

    def _action_schedule_activities(self):
        """沿用官方建立路徑，額外帶入本模組自訂欄位與來源參考。

        需求七：無關聯文件時直接建立 res-less 的 mail.activity；
        需求五/八：帶入 partner_id（若 context/欄位有值）。"""
        act_values = {
            'urgency': self.urgency,
            'importance': self.importance,
            'estimated_hours': self.estimated_hours,
        }
        if self.note_id:
            act_values['note_id'] = self.note_id.id
        if self.source_message_id:
            act_values['source_message_id'] = self.source_message_id.id
        # 客戶/專案（wizard 上選定或由文件自動帶入）；兩條建立路徑皆帶入
        if self.project_id:
            act_values['project_id'] = self.project_id.id
        # 需求八：discuss 建立時 context 帶入 default_partner_id；wizard 選定者優先
        partner_id = self.partner_id.id or self.env.context.get('default_partner_id')
        if partner_id:
            act_values['partner_id'] = partner_id

        records = self._get_applied_on_records()
        if records:
            return records.activity_schedule(
                activity_type_id=self.activity_type_id.id,
                automated=False,
                summary=self.summary,
                note=self.note,
                user_id=self.activity_user_id.id,
                date_deadline=self.date_deadline,
                **act_values,
            )

        # 獨立待辦（無關聯文件）：直接建立 mail.activity
        # （partner_id/project_id 已含於 act_values）
        vals = {
            'activity_type_id': self.activity_type_id.id,
            'summary': self.summary,
            'note': self.note,
            'user_id': self.activity_user_id.id,
            'date_deadline': self.date_deadline,
            **act_values,
        }
        return self.env['mail.activity'].create(vals)

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
