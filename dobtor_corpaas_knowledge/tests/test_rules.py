# -*- coding: utf-8 -*-
"""環境規則表（計畫第 24、33 項）：值的檢查、套用範圍、接到各個使用處。"""
import json

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..services import scripts


@tagged('post_install', '-at_install')
class TestKnowledgeRules(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Rule = self.env['corpaas.knowledge.rule']

    def test_builtin_rules_loaded_and_tracks(self):
        kinds = set(self.Rule.search([('source', '=', 'builtin')]).mapped('kind'))
        self.assertTrue({'hide_selector', 'empty_selector', 'gate_allow_model', 'purge_reset_method',
                         'seed_forbid_model', 'seed_prompt', 'rank_keyword'} <= kinds)
        forbid = self.Rule.search([('kind', '=', 'seed_forbid_model'), ('source', '=', 'builtin')])
        prompt = self.Rule.search([('kind', '=', 'seed_prompt'), ('source', '=', 'builtin')])
        self.assertEqual((forbid.track, prompt.track), ('check', 'prompt'), '同一件事一軟一硬')

    def test_value_validation(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'x', 'kind': 'front_route', 'value': '{"url": "/a"}'})
        with self.assertRaises(ValidationError):
            self.Rule.create({'name': 'x', 'kind': 'purge_reset_method', 'value': 'unlink'})

    def test_scope_module_and_values(self):
        self.Rule.create({'name': '只給網站方案', 'kind': 'hide_selector', 'value': '.kb-only-web',
                          'scope_module': 'website_xyz'})
        self.assertNotIn('.kb-only-web', self.Rule.values('hide_selector'), '範圍外不套用')
        self.assertIn('#oe_neutralize_ribbon', self.Rule.payload()['hide'])

    def test_rule_forbid_applied_at_replay(self):
        """驗證版規則由系統在重播時執行：規則禁止的模型記錄被略過。"""
        src = scripts.seed_script('__doc_scenario_r1', [
            {'xmlid': 'tag1', 'model': 'res.partner.category', 'values': {'name': '不准'}}],
            [], 'pw-123456', forbid=[{'model': 'res.partner.category', 'allow_xmlids': []}])
        printed = []
        exec(compile(src.replace('env.cr.commit()', 'pass'), '<seed>', 'exec'),
             {'env': self.env, 'print': printed.append})
        res = json.loads(printed[-1][len(scripts.MARK):])
        self.assertEqual([s['xmlid'] for s in res['skipped']], ['tag1'])

    def test_rank_keyword_rule(self):
        from ..models.capability_order import module_rank
        extra = [{'keyword': 'kbloyal', 'like_module': 'sale', 'after': True}]
        self.assertEqual(module_rank('dobtor_kbloyal_x', extra), module_rank('sale') + 0.5)
