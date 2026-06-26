# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MailActivityTransferWizard(models.TransientModel):
    """待辦轉移精靈

    功能說明:
    - 將待辦從一個文件轉移到另一個文件
    - 使用 Reference 欄位選擇目標（依 transfer.config 配置）
    - 記錄轉移來源以供追蹤
    - 標記待辦來源為「轉移」
    """
    _name = 'mail.activity.transfer.wizard'
    _inherit = 'mail.activity.action.wizard.mixin'
    _description = 'Transfer Activity Wizard'

    # 待辦資訊（含 res_display = 來源文件）由
    # mail.activity.action.wizard.mixin 提供。

    # ===== 來源（轉移用，隱藏；res_display 已供顯示）=====
    source_model = fields.Char(
        string='Source Model',
        readonly=True,
    )
    source_id = fields.Integer(
        string='Source Record ID',
        readonly=True,
    )

    # ===== 目標選擇 =====
    target_ref = fields.Reference(
        string='Target Record',
        selection='_selection_target_model',
        required=True,
    )

    @api.model
    def _selection_target_model(self):
        """取得允許的目標模型選項（使用共用方法）"""
        return self.env['mail.activity.transfer.config'].get_target_model_selection()

    @api.model
    def default_get(self, fields_list):
        """預設值處理：取得 activity_id（mixin）後補來源資訊"""
        res = super().default_get(fields_list)

        # 從 context 取得來源資訊
        if self.env.context.get('default_source_model'):
            res['source_model'] = self.env.context.get('default_source_model')
        if self.env.context.get('default_source_id'):
            res['source_id'] = self.env.context.get('default_source_id')

        # 若有 activity_id 但沒有來源資訊，從待辦取得
        if res.get('activity_id') and not res.get('source_model'):
            activity = self.env['mail.activity'].browse(res['activity_id'])
            if activity.exists():
                res['source_model'] = activity.res_model
                res['source_id'] = activity.res_id

        return res

    def _validate_transfer(self):
        """驗證轉移操作"""
        self.ensure_one()

        if not self.target_ref:
            raise UserError(_('Please select a target record.'))

        # 檢查目標記錄存在
        if not self.target_ref.exists():
            raise UserError(_('Target record does not exist.'))

        # 檢查待辦存在且有效
        if not self.activity_id.exists():
            raise UserError(_('Activity record does not exist.'))

        if not self.activity_id.active:
            raise UserError(_('This activity is archived and cannot be transferred.'))

        # 檢查目標不是同一個記錄
        target_model = self.target_ref._name
        target_id = self.target_ref.id
        if target_model == self.source_model and target_id == self.source_id:
            raise UserError(_('Target record is the same as source, no need to transfer.'))

    def _prepare_transfer_values(self):
        """準備轉移更新值"""
        self.ensure_one()

        target_model = self.target_ref._name
        target_id = self.target_ref.id
        target_model_id = self.env['ir.model']._get(target_model)

        vals = {
            'res_model_id': target_model_id.id,
            'res_id': target_id,
            'transferred_from_model': self.source_model,
            'transferred_from_id': self.source_id,
            'schedule_origin': 'transferred',  # 標記為轉移來源
        }

        # 如果來源是 note.note，保留 note_id 關聯
        if self.source_model == 'note.note':
            vals['note_id'] = self.source_id

        return vals

    def action_transfer(self):
        """執行轉移"""
        self.ensure_one()
        self._validate_transfer()

        # 更新待辦
        self.activity_id.write(self._prepare_transfer_values())

        # 刷新視圖
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
