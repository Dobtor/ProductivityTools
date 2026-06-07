# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 決策試算（設計期，不需真實單據）。

直接給輸入變數值（JSON），對指定決策求值，顯示命中規則、輸出值、
覆蓋警示；approver 慣例時顯示依序簽核人鏈與解析出的人。
"""
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import dmn_feel


class DmnDecisionPreview(models.TransientModel):
    _name = 'dmn.decision.preview'
    _description = 'DMN 決策試算'

    definitions_id = fields.Many2one('dmn.definitions', required=True, ondelete='cascade')
    decision_id = fields.Many2one(
        'dmn.decision', string='決策', required=True,
        domain="[('definitions_id','=',definitions_id)]")
    input_json = fields.Text(
        string='輸入變數 (JSON)', default='{}',
        help='以 binding 變數名為鍵，如 {"amount": 600000, "category": "差旅"}')
    applicant_id = fields.Many2one('res.users', string='測試申請人')
    result_html = fields.Html(string='試算結果', readonly=True, sanitize=False)

    def action_run(self):
        self.ensure_one()
        try:
            overrides = json.loads(self.input_json or '{}')
        except ValueError as e:
            raise UserError(_('輸入 JSON 格式錯誤：%s', e))
        if not isinstance(overrides, dict):
            raise UserError(_('輸入須為 JSON 物件。'))

        defn = self.definitions_id
        ctx = defn.build_context(applicant=self.applicant_id)
        ctx.update(overrides)
        ctx['__today__'] = fields.Date.context_today(self)

        dec = self.decision_id
        body_parts = []
        try:
            if dec.logic_type == 'decision_table' and dec.table_id:
                body_parts.append(self._render_table(defn, dec, ctx))
            else:
                val = dmn_feel.evaluate(dec.literal_expression or 'null', ctx)
                body_parts.append('<p>輸出：<b>%s</b></p>' % dmn_feel._to_str(val))
        except dmn_feel.FeelError as e:
            body_parts.append('<p class="text-danger">求值失敗：%s</p>' % e)

        warns = defn.coverage_warnings(dec.dmn_id)
        if warns:
            body_parts.append(
                '<div class="alert alert-warning mt-2">覆蓋提醒：<br/>%s</div>'
                % '<br/>'.join(warns))

        self.result_html = ''.join(body_parts)
        return {
            'type': 'ir.actions.act_window', 'name': _('DMN 決策試算'),
            'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'new',
        }

    def _render_table(self, defn, dec, ctx):
        hits = defn._hit_rules(dec.table_id, ctx)
        if not hits:
            return '<p class="text-danger">無命中規則 → 此輸入解析不到輸出。</p>'
        if dec.is_approver_output:
            return self._render_approver(defn, dec, ctx)
        items = []
        for idx, (rule, out) in enumerate(hits, 1):
            kv = ', '.join('%s=%s' % (k, dmn_feel._to_str(v)) for k, v in out.items())
            items.append('<li>命中規則 %s（序 %s）：<b>%s</b></li>'
                         % (idx, rule.sequence, kv))
        return '<p>命中規則：</p><ol>%s</ol>' % ''.join(items)

    def _render_approver(self, defn, dec, ctx):
        # 直接用 ctx（已含試算覆寫）算鏈，避免重算 binding 蓋掉覆寫值
        raw = defn._eval_table(dec.table_id, ctx)
        Role = self.env['bpmn.role']
        instance = self.env['bpmn.process.instance'].new({
            'applicant_user_id': self.applicant_id.id if self.applicant_id else False})
        items = []
        for i, item in enumerate(raw or [], 1):
            if not isinstance(item, dict):
                continue
            vals = {
                'resolver_type': dmn_feel._to_str(item.get('resolver')) or 'direct_manager',
                'level': int(item['level']) if item.get('level') is not None else 1,
            }
            role = Role.new(self._role_vals_from(vals))
            try:
                users = role.resolve(instance)
                names = ', '.join(users.mapped('name')) or '（解析不到簽核人）'
            except Exception as e:
                names = '（解析失敗：%s）' % e
            items.append('<li>第 %s 關 %s：<b>%s</b></li>'
                         % (i, vals['resolver_type'], names))
        return '<p>依序核決鏈：</p><ol>%s</ol>' % ''.join(items)

    def _role_vals_from(self, vals):
        return {
            'name': 'preview',
            'resolver_type': vals['resolver_type'],
            'level': vals.get('level', 1),
        }
