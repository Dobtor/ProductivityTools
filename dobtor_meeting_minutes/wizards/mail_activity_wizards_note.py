# -*- coding: utf-8 -*-
"""待辦精靈 × 筆記（自 dobtor_mail_activity 搬入）。"""

from odoo import api, fields, models


class MailActivityActionWizardMixin(models.AbstractModel):
    """完成／取消／延期／轉移／改派精靈共用：顯示待辦的來源筆記。"""
    _inherit = 'mail.activity.action.wizard.mixin'

    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        related='activity_id.note_id',
        readonly=True,
    )


class MailActivityCreateWizard(models.TransientModel):
    _inherit = 'mail.activity.create.wizard'

    # ===== 獨立關聯筆記 =====
    note_id = fields.Many2one(
        'note.note',
        string='Related Note',
        help='Note whose to-do list will show this activity '
             '(independent of the target document).',
    )

    @api.model
    def default_get(self, fields_list):
        """note_id 預設（來源參考）：僅在 context 明確帶入、或編輯 note.note 時帶入"""
        res = super().default_get(fields_list)
        if 'note_id' in fields_list and not res.get('note_id'):
            ctx = self.env.context
            note_id = ctx.get('default_note_id')
            if note_id:
                res['note_id'] = note_id
            elif ctx.get('active_model') == 'note.note' and ctx.get('active_id'):
                res['note_id'] = ctx['active_id']
        return res

    def _prepare_extra_activity_values(self):
        vals = super()._prepare_extra_activity_values()
        # 一律明寫（清空時為 False），避免 context 的 default_note_id 又被 ORM 套回去
        vals['note_id'] = self.note_id.id or False
        return vals


class MailActivityMergeWizard(models.TransientModel):
    _inherit = 'mail.activity.merge.wizard'

    merged_note_count = fields.Integer(
        string='Notes to Attach',
        compute='_compute_merged_note_count',
    )

    @api.depends('activity_ids', 'master_id')
    def _compute_merged_note_count(self):
        for wizard in self:
            sources = wizard.activity_ids - wizard.master_id
            notes = sources.mapped('note_ids') | sources.mapped('note_id')
            wizard.merged_note_count = len(notes - wizard.master_id.note_ids)


class MailActivityReassignWizard(models.TransientModel):
    _inherit = 'mail.activity.reassign.wizard'

    def _prepare_new_activity_values(self, reassign_note):
        """改派產生的新待辦保留筆記關聯"""
        vals = super()._prepare_new_activity_values(reassign_note)
        if self.activity_id.note_id:
            vals['note_id'] = self.activity_id.note_id.id
        return vals


class MailActivityTransferWizard(models.TransientModel):
    _inherit = 'mail.activity.transfer.wizard'

    def _prepare_transfer_values(self):
        """來源是 note.note 時，保留 note_id 關聯"""
        vals = super()._prepare_transfer_values()
        if self.source_model == 'note.note':
            vals['note_id'] = self.source_id
        return vals
