# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectCloseFeedback(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        for key, value in {'calibration_window': 5, 'hours_per_day': 8}.items():
            icp.set_param('corpaas_proposal.%s' % key, value)
        cls.partner = cls.env['res.partner'].create({'name': '結案測試客戶'})
        cls.cap = cls.env['corpaas.knowledge.capability'].create({
            'name': '結案測試能力', 'code': 'close_cap', 'color': 'native'})
        cls.tpl = cls.env['corpaas.knowledge.effort_template'].create({
            'capability_id': cls.cap.id, 'activity': 'migration', 'base_days': 2,
            'driver': 'none'})
        Stage = cls.env['project.project.stage']
        cls.st_open = Stage.create({'name': '進行中', 'sequence': 1, 'fold': False})
        cls.st_done = Stage.create({'name': '結案', 'sequence': 90, 'fold': True})
        cls.st_done2 = Stage.create({'name': '歸檔', 'sequence': 99, 'fold': True})
        cls.employee = cls.env['hr.employee'].create({'name': '導入顧問'})
        cls.service = cls.env['product.product'].create({
            'name': '導入服務（測試）', 'type': 'service', 'list_price': 100})

    def _linked_project(self):
        prop = self.env['corpaas.knowledge.proposal'].create({
            'partner_id': self.partner.id, 'ccu': 1})
        pain = self.env['corpaas.knowledge.pain'].create({
            'proposal_id': prop.id, 'description': '資料要轉'})
        self.env['corpaas.knowledge.mapping'].create({
            'pain_id': pain.id, 'capability_id': self.cap.id, 'color': 'native',
            'confirmed': True})
        prop.action_compute_estimate()
        prop.action_send()
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'knowledge_proposal_id': prop.id,
            'order_line': [(0, 0, {'product_id': self.service.id, 'product_uom_qty': 1})]})
        prop.sale_order_id = order
        project = self.env['project.project'].create({
            'name': '導入專案', 'stage_id': self.st_open.id, 'allow_timesheets': True,
            'partner_id': self.partner.id, 'sale_line_id': order.order_line[:1].id})
        self.assertEqual(project.sale_order_id, order)
        self.env['account.analytic.line'].create({
            'project_id': project.id, 'employee_id': self.employee.id,
            'name': '[close_cap] 資料移轉', 'unit_amount': 24.0})  # 3 人天
        return prop, project

    def _patch_feedback(self, **kw):
        cls = type(self.env['corpaas.knowledge.proposal'])
        return patch.object(cls, 'action_feedback_actuals', autospec=True, **kw)

    def test_close_triggers_calibration_once(self):
        prop, project = self._linked_project()
        project.stage_id = self.st_done
        self.assertTrue(project.knowledge_feedback_done)
        self.assertTrue(prop.feedback_date)
        self.assertEqual(self.tpl.calibration_count, 1)
        # (2 + 3) / 2
        self.assertEqual(self.tpl.base_days, 2.5)
        self.assertIn('已回寫', project.message_ids[:1].body)
        # 已結案再換到另一個摺疊階段：不再觸發
        with self._patch_feedback() as mocked:
            project.stage_id = self.st_done2
            project.write({'name': '導入專案（改名）'})
        mocked.assert_not_called()

    def test_reopen_and_close_again_triggers_again(self):
        prop, project = self._linked_project()
        with self._patch_feedback(return_value=True) as mocked:
            project.stage_id = self.st_done
            self.assertEqual(mocked.call_count, 1)
            project.stage_id = self.st_open
            self.assertFalse(project.knowledge_feedback_done)
            self.assertEqual(mocked.call_count, 1)
            project.stage_id = self.st_done
            self.assertEqual(mocked.call_count, 2)
        self.assertEqual(mocked.call_args[0][0], prop)
        self.assertTrue(project.knowledge_feedback_done)

    def test_failure_does_not_block_close(self):
        prop, project = self._linked_project()
        with self._patch_feedback(side_effect=UserError('範本壞了')):
            project.stage_id = self.st_done
        self.assertEqual(project.stage_id, self.st_done)
        self.assertFalse(project.knowledge_feedback_done)
        self.assertIn('範本壞了', project.message_ids[:1].body)
        # 非 UserError 也不擋，且 savepoint 回滾了失敗那次的寫入
        project.stage_id = self.st_open

        def boom(proposal):
            proposal.feedback_date = '2020-01-01 00:00:00'
            raise ValueError('爆炸')
        logger = 'odoo.addons.dobtor_corpaas_knowledge_proposal_project.models.project_project'
        with self._patch_feedback(side_effect=boom), self.assertLogs(logger, level='ERROR'):
            project.stage_id = self.st_done
        self.assertEqual(project.stage_id, self.st_done)
        self.assertFalse(prop.feedback_date)
        self.assertIn('爆炸', project.message_ids[:1].body)
        self.assertEqual(self.tpl.calibration_count, 0)

    def test_draft_proposal_failure_posted(self):
        """真實路徑：建議書不是已送出／成交 → 回寫方法丟 UserError → 留言、照樣結案。"""
        prop, project = self._linked_project()
        prop.action_mark_lost()
        project.stage_id = self.st_done
        self.assertEqual(project.stage_id, self.st_done)
        self.assertFalse(project.knowledge_feedback_done)
        self.assertIn('只有已送出或成交', project.message_ids[:1].body)
        self.assertEqual(self.tpl.calibration_count, 0)

    def test_proposal_found_via_order_project(self):
        """報價單直接指定專案（sale.order.project_id，沒有 sale_line_id）也要找得到建議書。"""
        prop, _linked = self._linked_project()
        project = self.env['project.project'].create({
            'name': '既有專案', 'stage_id': self.st_open.id, 'allow_billable': True,
            'partner_id': self.partner.id})
        prop.sale_order_id.project_id = project
        self.assertEqual(project._knowledge_proposals(), prop)
        with self._patch_feedback(return_value=True) as mocked:
            project.stage_id = self.st_done
        self.assertEqual(mocked.call_args[0][0], prop)
        self.assertTrue(project.knowledge_feedback_done)

    def test_default_service_creates_project(self):
        service = self.env.ref('dobtor_corpaas_knowledge_proposal.product_implementation_service')
        self.assertEqual(service.service_tracking, 'project_only',
                         '預設導入服務要建專案，結案回寫才接得起來')

    def test_unlinked_project_ignored(self):
        project = self.env['project.project'].create({
            'name': '內部專案', 'stage_id': self.st_open.id})
        with self._patch_feedback() as mocked:
            project.stage_id = self.st_done
        mocked.assert_not_called()
        self.assertFalse(project.knowledge_feedback_done)
