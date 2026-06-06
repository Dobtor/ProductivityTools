# -*- coding: utf-8 -*-
"""職務代理 / 代簽核授權 — DESIGN.md §3.4 / §6.3。

解析簽核人時，若原簽核人正在代理區間，將其替換/改派給代理人。
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BpmnDelegation(models.Model):
    _name = 'bpmn.delegation'
    _description = '職務代理 / 代簽核授權'
    _order = 'date_start desc, id desc'

    delegator_id = fields.Many2one('res.users', string='原簽核人', required=True,
                                   index=True)
    delegate_id = fields.Many2one('res.users', string='代理人', required=True)
    date_start = fields.Date(string='開始日期', required=True)
    date_end = fields.Date(string='結束日期', required=True)
    definition_ids = fields.Many2many(
        'bpmn.executable.process', string='適用流程',
        help='留空 = 所有流程；指定 = 僅這些流程代理')
    active = fields.Boolean(default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_('結束日期不可早於開始日期。'))

    @api.constrains('delegator_id', 'delegate_id')
    def _check_distinct(self):
        for rec in self:
            if rec.delegator_id == rec.delegate_id:
                raise ValidationError(_('代理人不可與原簽核人相同。'))

    # ------------------------------------------------------------------
    # 解析輔助：將 recordset 中正在被代理的人替換為代理人
    # ------------------------------------------------------------------
    @api.model
    def _substitute_users(self, users, definition=False):
        """回傳替換後的 res.users（保留未被代理者，被代理者改為其代理人）。

        :param users: res.users recordset
        :param definition: bpmn.executable.process（限定流程的代理）
        """
        if not users:
            return users
        today = fields.Date.context_today(self)
        Users = self.env['res.users']
        result = Users
        for user in users:
            delegation = self._active_delegation_for(user, today, definition)
            if delegation:
                result |= delegation.delegate_id
            else:
                result |= user
        return result

    @api.model
    def _active_delegation_for(self, user, on_date, definition=False):
        """找 user 在 on_date 生效中的代理（限定流程則優先 match）。"""
        domain = [
            ('delegator_id', '=', user.id),
            ('active', '=', True),
            ('date_start', '<=', on_date),
            ('date_end', '>=', on_date),
        ]
        candidates = self.search(domain)
        if not candidates:
            return self.browse()
        if definition:
            scoped = candidates.filtered(
                lambda d: not d.definition_ids or definition in d.definition_ids)
            return scoped[:1]
        return candidates.filtered(lambda d: not d.definition_ids)[:1] \
            or candidates[:1]
