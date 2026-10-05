# -*- coding: utf-8 -*-
"""成本規劃器（D3）的操作說明部分：截圖腳本、修補、起草各要幾件。"""
from odoo import _, models

from .hooks import MAX_REPAIRS


class SolutionPackageManualCost(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_cost_lines(self, full=False):
        lines = super()._knowledge_cost_lines(full)
        hooks = self.env['corpaas.knowledge.hooks']
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Article = self.env['corpaas.knowledge.article'].sudo()
        rule = hooks._manual_script_mode() == 'rule'
        no_script = draft = 0
        for feature, cap in hooks._manual_sorted_candidates(self):
            if not Template._latest_for(feature):
                no_script += 1
            for scenario in hooks._manual_scenarios_for(self, cap):
                if not Article.search_count([('feature_id', '=', feature.id),
                                             ('scenario_id', '=', scenario.id)]):
                    draft += 1
        repair = self.env['corpaas.knowledge.shot_binding'].sudo().search_count([
            # ★ 已被規則腳本取代（封存）的 AI 範本不會再修：不算進去（實機曾因此多估 29 件）
            ('template_id.active', '=', True),
            ('template_id.feature_id.package_ids', 'in', self.id), ('state', '=', 'failed'),
            ('needs_repair', '=', True), ('repair_attempts', '<', MAX_REPAIRS)])
        lines += [
            {'key': 'script', 'count': no_script, 'deferrable': not rule,
             'label': _('產生截圖腳本（規則產生，免費）') if rule else _('AI 探索畫面產生截圖腳本'),
             'purposes': [] if rule else ['manual_explore', 'manual_bind']},
            {'key': 'repair', 'count': repair, 'deferrable': True,
             'label': _('AI 修補失敗的截圖腳本'), 'purposes': ['manual_repair']},
            {'key': 'draft', 'count': draft, 'deferrable': True,
             'label': _('起草參考篇（步驟＋情境說明）'),
             'purposes': ['manual_step_block', 'manual_scenario']},
        ]
        return lines
