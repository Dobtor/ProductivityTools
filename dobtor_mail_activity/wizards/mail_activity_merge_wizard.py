# -*- coding: utf-8 -*-

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class MailActivityMergeWizard(models.TransientModel):
    """合併待辦精靈

    功能說明:
    - 從清單多選數筆待辦，指定其中一筆為「主待辦」
    - 其餘待辦的筆記引用（note_ids）併入主待辦
    - 其餘待辦封存並留下 merged_into_id 指標（不刪除，可解除合併）
    - 筆記內指向被併入者的膠囊改寫成主待辦；改不到的由讀取時轉向兜底

    合併規則（已定案）：
      預估工時 → 取主待辦；截止日/緊急/重要 → 取最嚴重；
      筆記引用 → 聯集；待辦註記與完成回饋 → 附加不覆蓋；
      工時表記錄 → 搬到主待辦（actual_hours 是 stored compute 會自動重算）。
    """
    _name = 'mail.activity.merge.wizard'
    _description = 'Merge Activities Wizard'

    activity_ids = fields.Many2many(
        'mail.activity',
        string='Activities to Merge',
        required=True,
        help='All selected activities, including the master.',
    )
    master_id = fields.Many2one(
        'mail.activity',
        string='Master Activity',
        required=True,
        domain="[('id', 'in', activity_ids)]",
        help='The activity that survives; everything else is merged into it.',
    )
    activity_count = fields.Integer(
        string='Activity Count',
        compute='_compute_merge_preview',
    )
    merged_note_count = fields.Integer(
        string='Notes to Attach',
        compute='_compute_merge_preview',
    )
    # 警示：跨負責人 / 跨關聯文件
    other_assignee_warning = fields.Char(compute='_compute_merge_preview')
    other_document_warning = fields.Char(compute='_compute_merge_preview')

    @api.model
    def default_get(self, fields_list):
        """批次入口（清單多選）傳 default_activity_ids 或 active_ids。

        主待辦預設挑「截止日最早、其次 id 最小」的那一筆 —— 合併多半是把零碎
        的重複待辦收攏到最早要交的那一張，但使用者仍可自行改選。
        """
        res = super().default_get(fields_list)

        ids = list(self.env.context.get('default_activity_ids') or [])
        if not ids and self.env.context.get('active_model') == 'mail.activity':
            ids = list(self.env.context.get('active_ids') or [])
        if not ids:
            return res

        activities = self.env['mail.activity'].browse(ids).exists()
        res['activity_ids'] = [Command.set(activities.ids)]
        if not res.get('master_id'):
            candidates = activities.filtered('active') or activities
            master = min(
                candidates,
                key=lambda a: (a.date_deadline or fields.Date.today(), a.id),
                default=False,
            )
            if master:
                res['master_id'] = master.id
        return res

    @api.depends('activity_ids', 'master_id')
    def _compute_merge_preview(self):
        for wizard in self:
            sources = wizard.activity_ids - wizard.master_id
            wizard.activity_count = len(wizard.activity_ids)
            notes = sources.mapped('note_ids') | sources.mapped('note_id')
            wizard.merged_note_count = len(notes - wizard.master_id.note_ids)

            others = sources.filtered(
                lambda a: a.user_id and a.user_id != wizard.master_id.user_id)
            wizard.other_assignee_warning = ', '.join(
                sorted(set(others.mapped('user_id.name')))) if others else False

            docs = sources.filtered(
                lambda a: (a.res_model, a.res_id) != (
                    wizard.master_id.res_model, wizard.master_id.res_id)
                and a.res_model)
            wizard.other_document_warning = ', '.join(
                sorted(set(d.res_document_display for d in docs if d.res_document_display))
            ) if docs else False

    @api.onchange('activity_ids')
    def _onchange_activity_ids(self):
        """選取範圍縮小後，主待辦若已不在其中則清空，避免送出時才報錯。"""
        if self.master_id and self.master_id not in self.activity_ids:
            self.master_id = False

    def action_merge(self):
        self.ensure_one()
        if len(self.activity_ids) < 2:
            raise UserError(_('Select at least two activities to merge.'))
        if self.master_id not in self.activity_ids:
            raise UserError(_('The master activity must be one of the selected activities.'))

        self.activity_ids.action_merge(self.master_id)

        # 回到主待辦，讓使用者確認合併結果
        return {
            'type': 'ir.actions.act_window',
            'name': _('Merged Activity'),
            'res_model': 'mail.activity',
            'res_id': self.master_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'dobtor_mail_activity.mail_activity_view_form_schedule').id, 'form')],
            'target': 'current',
        }
