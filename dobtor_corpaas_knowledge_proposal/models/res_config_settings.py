# -*- coding: utf-8 -*-
from odoo import api, fields, models

#: ICP 鍵 → (型別, 預設值)；proposal 端一律經 `proposal_settings()` 讀，預設值只寫這一份。
PARAMS = {
    'day_rate': ('float', 12000.0),
    'internal_day_cost': ('float', 6000.0),
    'hours_per_day': ('float', 8.0),
    'cost_per_ccu_monthly': ('float', 300.0),
    'cost_per_gb_monthly': ('float', 5.0),
    'cost_per_worker_monthly': ('float', 900.0),
    'worker_mb': ('float', 512.0),
    'third_party_default_monthly': ('float', 1000.0),
    'ai_point_cost': ('float', 1.0),
    'calibration_window': ('int', 5),
    'service_product_id': ('int', 0),
}
PREFIX = 'corpaas_proposal.'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    proposal_day_rate = fields.Float(
        string='對外日費率', config_parameter=PREFIX + 'day_rate', default=12000.0)
    proposal_internal_day_cost = fields.Float(
        string='內部人天成本', config_parameter=PREFIX + 'internal_day_cost', default=6000.0)
    proposal_hours_per_day = fields.Float(
        string='每人天工時', config_parameter=PREFIX + 'hours_per_day', default=8.0,
        help='工時回寫時把 timesheet 小時換成人天。')
    proposal_cost_per_ccu_monthly = fields.Float(
        string='每 CCU 月成本（估）', config_parameter=PREFIX + 'cost_per_ccu_monthly',
        default=300.0,
        help='共享環境沒有可信的主機成本（dobtor_infrastructure_cost）時的替代值。')
    proposal_cost_per_gb_monthly = fields.Float(
        string='每 GB 月成本', config_parameter=PREFIX + 'cost_per_gb_monthly', default=5.0)
    proposal_cost_per_worker_monthly = fields.Float(
        string='每 worker 月成本', config_parameter=PREFIX + 'cost_per_worker_monthly',
        default=900.0)
    proposal_worker_mb = fields.Float(
        string='每 worker 記憶體（MB）', config_parameter=PREFIX + 'worker_mb', default=512.0)
    proposal_third_party_default_monthly = fields.Float(
        string='第三方預設月費', config_parameter=PREFIX + 'third_party_default_monthly',
        default=1000.0, help='能力有寫第三方費用但沒寫金額時，以此估。')
    proposal_ai_point_cost = fields.Float(
        string='每 AI 點成本', config_parameter=PREFIX + 'ai_point_cost', default=1.0)
    proposal_calibration_window = fields.Integer(
        string='校正移動平均視窗', config_parameter=PREFIX + 'calibration_window', default=5)
    proposal_service_product_id = fields.Many2one(
        'product.product', string='導入服務產品',
        domain="[('type', '=', 'service')]",
        help='建立報價單時，工項明細用這個產品（數量＝人天）。')

    @api.model
    def get_values(self):
        res = super().get_values()
        res['proposal_service_product_id'] = self.env[
            'corpaas.knowledge.proposal']._service_product().id
        return res

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            PREFIX + 'service_product_id', self.proposal_service_product_id.id or '')

    @api.model
    def proposal_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        out = {}
        for key, (kind, default) in PARAMS.items():
            raw = icp.get_param(PREFIX + key)
            try:
                out[key] = (int if kind == 'int' else float)(raw) if raw not in (None, '', False) \
                    else default
            except ValueError:
                out[key] = default
        return out
