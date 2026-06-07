# -*- coding: utf-8 -*-
"""res.company — 能力開關狀態查詢 — DESIGN_PROGRESSIVE_TIERS.md §8。"""
from odoo import api, fields, models

from . import feature_registry as FR


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _bpmn_enabled_features(self):
        """回傳目前啟用的能力 key set（含永遠啟用的 BASE_FEATURES）。

        開關存於 ir.config_parameter（全域），多公司目前共用全域參數；
        若未來需 per-company，可改存 res.company 欄位。
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = set()
        for key in FR.ALL_FEATURES:
            val = ICP.get_param('dobtor_approval.%s' % key)
            if key in FR.BASE_FEATURES:
                # 介面/基本核心：未明確關閉（'False'）即啟用
                if val != 'False':
                    enabled.add(key)
            elif val == 'True':
                enabled.add(key)
        return enabled

    def _bpmn_feature_enabled(self, feature_key):
        """便捷判斷單一能力是否啟用。"""
        self.ensure_one()
        return feature_key in self._bpmn_enabled_features()
