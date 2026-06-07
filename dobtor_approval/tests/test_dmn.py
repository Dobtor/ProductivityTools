# -*- coding: utf-8 -*-
# Copyright 2026 Dobtor Systems Integration — License LGPL-3
"""DMN 子系統測試：XML 解析、DRD 求值、hit policy、條件 row、可達性。

執行：odoo -i dobtor_approval --test-enable  或  --test-tags /dobtor_approval
本機無 Odoo 環境，故以 Odoo TransactionCase 撰寫，由使用者實例執行。
"""
from odoo.tests.common import TransactionCase, tagged

# 含 DRD（風險評等 UNIQUE → 核決層級鏈 COLLECT approver）+ BKM 的決策集
DRD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             id="defn_t" name="t" namespace="http://dobtor/dmn">
  <decision id="Decision_risk" name="風險評等">
    <decisionTable id="DT_risk" hitPolicy="UNIQUE">
      <input id="ri" label="金額"><inputExpression typeRef="number"><text>amount</text></inputExpression></input>
      <output id="ro" name="risk" typeRef="string"/>
      <rule><inputEntry><text>&lt; 50000</text></inputEntry><outputEntry><text>"low"</text></outputEntry></rule>
      <rule><inputEntry><text>[50000..500000)</text></inputEntry><outputEntry><text>"mid"</text></outputEntry></rule>
      <rule><inputEntry><text>&gt;= 500000</text></inputEntry><outputEntry><text>"high"</text></outputEntry></rule>
    </decisionTable>
  </decision>
  <businessKnowledgeModel id="BKM_g" name="職等對照">
    <encapsulatedLogic><literalExpression><text>if amount &gt;= 500000 then "高階" else "一般"</text></literalExpression></encapsulatedLogic>
  </businessKnowledgeModel>
  <decision id="Decision_chain" name="核決層級鏈">
    <informationRequirement><requiredDecision href="#Decision_risk"/></informationRequirement>
    <knowledgeRequirement><requiredKnowledge href="#BKM_g"/></knowledgeRequirement>
    <decisionTable id="DT_chain" hitPolicy="COLLECT">
      <input id="ca" label="金額"><inputExpression typeRef="number"><text>amount</text></inputExpression></input>
      <input id="cr" label="風險"><inputExpression typeRef="string"><text>風險評等</text></inputExpression></input>
      <output id="cres" name="resolver" typeRef="string"/>
      <output id="clvl" name="level" typeRef="number"/>
      <rule><inputEntry><text>&gt;= 0</text></inputEntry><inputEntry><text>-</text></inputEntry>
            <outputEntry><text>"direct_manager"</text></outputEntry><outputEntry><text>1</text></outputEntry></rule>
      <rule><inputEntry><text>&gt;= 50000</text></inputEntry><inputEntry><text>-</text></inputEntry>
            <outputEntry><text>"department_manager"</text></outputEntry><outputEntry><text>1</text></outputEntry></rule>
      <rule><inputEntry><text>-</text></inputEntry><inputEntry><text>"high"</text></inputEntry>
            <outputEntry><text>"manager_level"</text></outputEntry><outputEntry><text>2</text></outputEntry></rule>
    </decisionTable>
  </decision>
  <inputData id="InputData_amount" name="amount"/>
</definitions>"""


@tagged('post_install', '-at_install')
class TestDmn(TransactionCase):

    def setUp(self):
        super().setUp()
        self.defn = self.env['dmn.definitions'].create({'name': 't', 'dmn_xml': DRD_XML})

    # ---- 解析 ----
    def test_parse_drd(self):
        self.assertEqual(len(self.defn.decision_ids), 2)
        self.assertEqual(len(self.defn.bkm_ids), 1)
        chain = self.defn.decision_ids.filtered(lambda d: d.dmn_id == 'Decision_chain')
        self.assertTrue(chain.is_approver_output, '輸出含 resolver/level 應判為 approver')
        self.assertIn('Decision_risk', chain.requires_ids.mapped('dmn_id'),
                      '核決層級鏈應依賴風險評等（資訊需求）')
        risk = self.defn.decision_ids.filtered(lambda d: d.dmn_id == 'Decision_risk')
        self.assertEqual(len(risk.table_id.rule_ids), 3)

    def _chain(self, amount):
        """以試算（input_json 覆寫）取核決層級鏈的 resolver 清單。"""
        pv = self.env['dmn.decision.preview'].create({
            'definitions_id': self.defn.id,
            'decision_id': self.defn.decision_ids.filtered(
                lambda d: d.dmn_id == 'Decision_chain').id,
            'input_json': '{"amount": %d}' % amount,
        })
        pv.action_run()
        return pv.result_html or ''

    # ---- DRD 求值：金額階梯 → 風險 → 鏈長 ----
    def test_chain_low(self):
        html = self._chain(10000)
        self.assertIn('direct_manager', html)
        self.assertNotIn('department_manager', html)
        self.assertNotIn('manager_level', html)

    def test_chain_mid(self):
        html = self._chain(100000)
        self.assertIn('direct_manager', html)
        self.assertIn('department_manager', html)
        self.assertNotIn('manager_level', html)

    def test_chain_high(self):
        html = self._chain(600000)
        self.assertIn('direct_manager', html)
        self.assertIn('department_manager', html)
        self.assertIn('manager_level', html)  # 由 risk='high'（上游決策）觸發

    # ---- 直接求值 API ----
    def test_evaluate_decision_risk(self):
        # 無 record，改以 preview 覆寫；此處驗 _eval_table 直接呼叫
        risk = self.defn.decision_ids.filtered(lambda d: d.dmn_id == 'Decision_risk')
        self.assertEqual(self.defn._eval_table(risk.table_id, {'amount': 600000}), 'high')
        self.assertEqual(self.defn._eval_table(risk.table_id, {'amount': 100000}), 'mid')
        self.assertEqual(self.defn._eval_table(risk.table_id, {'amount': 10000}), 'low')

    def test_collect_chain_list(self):
        chain = self.defn.decision_ids.filtered(lambda d: d.dmn_id == 'Decision_chain')
        out = self.defn._eval_table(chain.table_id, {'amount': 600000, '風險評等': 'high'})
        self.assertEqual([o['resolver'] for o in out],
                         ['direct_manager', 'department_manager', 'manager_level'])

    # ---- 發佈校驗 ----
    def test_publish_requires_decisions(self):
        from odoo.exceptions import UserError
        empty = self.env['dmn.definitions'].create({
            'name': 'e', 'dmn_xml':
            '<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="e"/>'})
        with self.assertRaises(UserError):
            empty.action_publish()

    # ---- 條件 row（AND / OR 群組）----
    def test_condition_rows(self):
        inst = self.env['bpmn.process.instance'].new({})
        # (a > 3 且 b = x) → True
        self.assertTrue(inst._eval_cond_rows(
            [{'field': 'a', 'op': '>', 'value': '3'},
             {'field': 'b', 'op': '=', 'value': 'x', 'join': 'and'}],
            {'a': 5, 'b': 'x'}, False))
        # (a > 9) 或 (b = x) → True（第二群組）
        self.assertTrue(inst._eval_cond_rows(
            [{'field': 'a', 'op': '>', 'value': '9'},
             {'field': 'b', 'op': '=', 'value': 'x', 'join': 'or'}],
            {'a': 5, 'b': 'x'}, False))
        # (a > 9 且 b = x) → False（全 AND）
        self.assertFalse(inst._eval_cond_rows(
            [{'field': 'a', 'op': '>', 'value': '9'},
             {'field': 'b', 'op': '=', 'value': 'x', 'join': 'and'}],
            {'a': 5, 'b': 'x'}, False))

    def test_cmp_row(self):
        inst = self.env['bpmn.process.instance'].new({})
        self.assertTrue(inst._cmp_row(60000, '>=', '50000'))
        self.assertFalse(inst._cmp_row(40000, '>=', '50000'))
        self.assertTrue(inst._cmp_row('差旅', 'in', '差旅,交際'))
        self.assertTrue(inst._cmp_row(5, 'set', None))
        self.assertFalse(inst._cmp_row(0, 'set', None))

    # ---- 閘道可達性 ----
    def test_can_reach(self):
        inst = self.env['bpmn.process.instance'].new({})
        flows = [{'source': 'A', 'target': 'B'}, {'source': 'B', 'target': 'J'},
                 {'source': 'X', 'target': 'Y'}]
        self.assertTrue(inst._can_reach('A', 'J', flows))
        self.assertFalse(inst._can_reach('X', 'J', flows))  # 獨立區不可達
        self.assertTrue(inst._can_reach('J', 'J', flows))   # 自身
