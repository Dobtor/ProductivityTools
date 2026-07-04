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
    _description = 'Transfer Configuration'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        domain=[('is_mail_thread', '=', True), ('transient', '=', False)],
        help='Model allowed as activity target. Only models inheriting mail.thread can be selected.',
    )
    model = fields.Char(
        string='Model Name',
        related='model_id.model',
        store=True,
        readonly=True,
    )
    partner_field = fields.Char(
        string='Partner Field',
        help='Technical name of the field on this model that points to the related '
             'customer (res.partner), e.g. "partner_id". Leave empty to auto-detect '
             'a "partner_id" field. Used by activities to derive their related customer '
             'without hard-coding any specific module.',
    )
    project_field = fields.Char(
        string='Project Field',
        help='Technical name of the field on this model that points to a '
             'project.project, e.g. "project_id". Used to build the FK relation '
             'diagram (project -> related records) and to derive an activity\'s '
             'project from its linked document, without hard-coding any module. '
             'For project.project itself, leave empty (it is its own project).',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )

    _sql_constraints = [
        ('model_unique', 'unique(model_id)', 'Each model can only be configured once!')
    ]

    @api.depends('model_id', 'model_id.name')
    def _compute_name(self):
        """自動計算名稱"""
        for record in self:
            if record.model_id:
                record.name = record.model_id.name
            else:
                record.name = _('New Configuration')

    @api.constrains('model_id')
    def _check_model_is_mail_thread(self):
        """確保選擇的模型繼承 mail.thread"""
        for record in self:
            if record.model_id and not record.model_id.is_mail_thread:
                raise ValidationError(_(
                    'Model "%s" does not inherit mail.thread and cannot be used as activity target.',
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
    def _get_relation_map(self):
        """回傳 {model_name: {'partner_field': ..., 'project_field': ...}}
        供 mail.activity 設定驅動派生關聯（客戶）、專案關聯與關聯圖。

        只回傳啟用中的設定；partner_field 為空表示讓 mail.activity 自動探測。
        project_field 為空表示該模型無專案 FK（或它本身即 project.project）。
        """
        result = {}
        for config in self.search([('active', '=', True)]):
            if config.model:
                result[config.model] = {
                    'partner_field': config.partner_field or False,
                    'project_field': config.project_field or False,
                }
        return result

    @api.model
    def get_allowed_models(self):
        """取得允許的模型名稱列表

        Returns:
            list: 模型名稱字串列表
        """
        configs = self.search([('active', '=', True)])
        return configs.mapped('model')

    @api.model
    def create_default_configs(self):
        """建立預設配置（供模組安裝時使用）

        預設允許的模型（含指向 project.project 的 FK 欄位 project_field，
        供關聯圖 / 客戶推導 / 專案推導使用）:
        - note.note / res.partner / purchase.order / account.move /
          helpdesk.ticket：無專案 FK
        - crm.lead / project.task / sale.order：project_id
        - project.project：本身即專案（project_field 留空）

        升級既有設定時，會補填尚未設定的 project_field（不覆蓋使用者手改值）。
        """
        # (model_name, project_field)
        default_models = [
            ('note.note', False),
            ('res.partner', False),
            ('crm.lead', 'project_id'),
            ('project.project', False),
            ('project.task', 'project_id'),
            ('sale.order', 'project_id'),
            ('purchase.order', False),
            ('account.move', False),
            ('helpdesk.ticket', False),
        ]

        created = self.env['mail.activity.transfer.config']
        for sequence, (model_name, project_field) in enumerate(default_models, start=10):
            # 檢查模型是否存在
            model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
            if not model:
                continue

            # 檢查是否已有配置（含已停用者，避免升級時重複建立）
            existing = self.with_context(active_test=False).search([('model', '=', model_name)])
            if existing:
                # 升級補填 project_field（僅在尚未設定時），不覆蓋使用者手改
                if project_field and not existing.project_field:
                    existing.project_field = project_field
                continue

            # 建立配置
            created |= self.create({
                'model_id': model.id,
                'sequence': sequence,
                'project_field': project_field or False,
            })

        return created
