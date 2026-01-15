# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MailActivityTransferConfig(models.Model):
    """待辦轉移配置

    用途:
    - 定義允許作為待辦目標的模型
    - 控制 target_ref Reference 欄位的可選模型
    - 限制待辦可以轉移到哪些文件類型
    """
    _name = 'mail.activity.transfer.config'
    _description = '待辦轉移配置'
    _order = 'sequence, id'

    name = fields.Char(
        string='名稱',
        compute='_compute_name',
        store=True,
    )
    sequence = fields.Integer(
        string='順序',
        default=10,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='模型',
        required=True,
        ondelete='cascade',
        domain=[('is_mail_thread', '=', True), ('transient', '=', False)],
        help='允許作為待辦目標的模型。只能選擇繼承 mail.thread 的模型。',
    )
    model = fields.Char(
        string='模型名稱',
        related='model_id.model',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(
        string='啟用',
        default=True,
    )

    _sql_constraints = [
        ('model_unique', 'unique(model_id)', '每個模型只能配置一次！')
    ]

    @api.depends('model_id', 'model_id.name')
    def _compute_name(self):
        """自動計算名稱"""
        for record in self:
            if record.model_id:
                record.name = record.model_id.name
            else:
                record.name = _('新配置')

    @api.constrains('model_id')
    def _check_model_is_mail_thread(self):
        """確保選擇的模型繼承 mail.thread"""
        for record in self:
            if record.model_id and not record.model_id.is_mail_thread:
                raise ValidationError(_(
                    '模型「%s」未繼承 mail.thread，無法作為待辦目標。',
                    record.model_id.name
                ))

    @api.model
    def get_target_model_selection(self):
        """取得允許的目標模型選項列表

        Returns:
            list: [(model, name), ...] 格式的選項列表

        此方法供 mail.activity 的 target_ref Reference 欄位使用
        """
        configs = self.search([('active', '=', True)])
        selection = []
        for config in configs:
            if config.model_id:
                selection.append((config.model, config.model_id.name))
        return selection

    @api.model
    def get_allowed_models(self):
        """取得允許的模型名稱列表

        Returns:
            list: 模型名稱字串列表
        """
        configs = self.search([('active', '=', True)])
        return configs.mapped('model')

    @api.model
    def is_model_allowed(self, model_name):
        """檢查模型是否在允許列表中

        Args:
            model_name: 模型的技術名稱（如 'res.partner'）

        Returns:
            bool: 是否允許
        """
        return bool(self.search_count([
            ('model', '=', model_name),
            ('active', '=', True),
        ]))

    @api.model
    def create_default_configs(self):
        """建立預設配置（供模組安裝時使用）

        預設允許的模型:
        - note.note: 筆記本
        - res.partner: 聯絡人
        - crm.lead: CRM 商機
        - project.project: 專案
        - project.task: 任務
        - sale.order: 銷售訂單
        - purchase.order: 採購訂單
        - account.move: 會計分錄（發票）
        - helpdesk.ticket: 服務台工單
        """
        default_models = [
            'note.note',
            'res.partner',
            'crm.lead',
            'project.project',
            'project.task',
            'sale.order',
            'purchase.order',
            'account.move',
            'helpdesk.ticket',
        ]

        created = self.env['mail.activity.transfer.config']
        for sequence, model_name in enumerate(default_models, start=10):
            # 檢查模型是否存在
            model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
            if not model:
                continue

            # 檢查是否已有配置
            existing = self.search([('model', '=', model_name)])
            if existing:
                continue

            # 建立配置
            created |= self.create({
                'model_id': model.id,
                'sequence': sequence,
            })

        return created
