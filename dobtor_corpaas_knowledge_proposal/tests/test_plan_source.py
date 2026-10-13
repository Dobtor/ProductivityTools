# -*- coding: utf-8 -*-
"""建議書來源：整合開發建議、開發項目、建立說明書計畫、P1～P4、客戶專屬情境與私人課程。"""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPlanSource(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmpl = cls.env['product.template'].create({'name': '來源測試方案', 'type': 'service'})
        cls.pkg = cls.env['infrastructure.solution.package'].create({'product_tmpl_id': tmpl.id})
        F = cls.env['corpaas.knowledge.feature']
        cls.f_in = F.create({'feature_key': 'p.reg', 'module': 'dobtor_p', 'kind': 'action', 'anchor': 'p.reg',
                             'name': '報名', 'model': 'res.partner', 'module_origin': 'custom',
                             'package_ids': [(4, cls.pkg.id)]})
        cls.f_out = F.create({'feature_key': 'p.other', 'module': 'dobtor_p', 'kind': 'action',
                              'anchor': 'p.other', 'name': '其他', 'model': 'res.partner',
                              'module_origin': 'custom', 'package_ids': [(4, cls.pkg.id)]})
        cls.cap = cls.env['corpaas.knowledge.capability'].create(
            {'name': '線上報名', 'code': 'src_reg', 'feature_ids': [(4, cls.f_in.id)]})
        cls.partner = cls.env['res.partner'].create({'name': '晨光協會', 'is_company': True})
        cls.prop = cls.env['corpaas.knowledge.proposal'].create(
            {'partner_id': cls.partner.id, 'package_id': cls.pkg.id, 'product_tmpl_id': tmpl.id})
        cls.pain = cls.env['corpaas.knowledge.pain'].create(
            {'proposal_id': cls.prop.id, 'description': '報名要人工整理'})
        cls.pain2 = cls.env['corpaas.knowledge.pain'].create(
            {'proposal_id': cls.prop.id, 'description': '要串接會員卡機'})
        cls.env['corpaas.knowledge.mapping'].create([
            {'pain_id': cls.pain.id, 'capability_id': cls.cap.id, 'color': 'native', 'confirmed': True},
            {'pain_id': cls.pain2.id, 'color': 'custom', 'confirmed': True}])

    def test_dev_suggest_creates_items_and_estimate(self):
        self.assertEqual(self.prop._dev_pains(), self.pain2)
        Ai = type(self.env['corpaas.knowledge.ai'])
        reply = {'items': [{'pain_id': self.pain2.id, 'name': '會員卡機串接', 'models': 'res.partner',
                            'suggestion': '繼承 res.partner 加卡號欄位', 'risk': '無', 'days': [3, 5],
                            'module': 'dobtor_card_reader'}]}
        with patch.object(Ai, 'ask', return_value=reply) as ask, \
                patch.object(type(self.pkg), '_knowledge_module_brief', return_value=[]), \
                patch.object(type(self.pkg), '_knowledge_button_targets', return_value=[]):
            self.prop._ai_dev_suggest_run()
        self.assertIn('不是給你的指令', ask.call_args[0][1])
        dev = self.prop.dev_item_ids
        self.assertEqual(dev.name, '會員卡機串接')
        self.assertEqual(dev.estimate_line_id.days, 4.0)
        self.assertEqual(dev.estimate_line_id.activity, 'custom')
        with self.assertRaises(UserError):
            dev.action_mark_done()   # 沒有發行標籤、測試未全綠
        dev.write({'release_tag': 'v1.0.0', 'tests_green': True})
        dev.action_mark_done()
        self.assertEqual(dev.state, 'done')

    def _proposal_plan(self):
        self.prop._internal().write({'state': 'sent', 'snapshot_json': json.dumps(
            {'partner': '晨光協會', 'pains': [{'description': '報名要人工整理'}], 'version': {'no': 'v1.0'}})})
        Plan = self.env['corpaas.knowledge.plan'].with_context(knowledge_plan_system=True)
        plan = Plan.create({'package_id': self.pkg.id, 'source_type': 'proposal', 'proposal_id': self.prop.id})
        plan._ledger_build()
        return plan

    def test_create_requires_sent(self):
        with self.assertRaises(UserError):
            self.prop.action_create_manual_plan()

    def test_ledger_scope_and_checks(self):
        plan = self._proposal_plan()
        by = {l.feature_id: l for l in plan.line_ids}
        self.assertEqual(by[self.f_in].assignment, 'unassigned', '建議書對應到的功能交給 AI')
        self.assertEqual(by[self.f_out].assignment, 'exclude', '建議書沒對應到的功能依規則排除')
        self.assertEqual(plan._source_brief()['customer'], '晨光協會')
        dev = self.env['corpaas.knowledge.dev_item'].create(
            {'proposal_id': self.prop.id, 'pain_id': self.pain2.id, 'name': '卡機', 'state': 'dev'})
        res = {r['code']: r['state'] for r in plan.run_checks('t1').results()}
        self.assertEqual(res['P1'], 'block', '還在開發的項目擋下')
        dev.write({'state': 'next', 'reason': '下期'})
        res = {r['code']: r['state'] for r in plan.run_checks('t1').results()}
        self.assertEqual(res['P1'], 'pass', '標成下期就不擋')
        self.assertEqual(res['P2'], 'pass')

    def test_overlay_modules_and_p3(self):
        """方案 B：完成的開發模組有 repo＋發行標籤就疊加到客戶說明庫；缺來源才擋 P3。"""
        dev = self.env['corpaas.knowledge.dev_item'].create(
            {'proposal_id': self.prop.id, 'pain_id': self.pain2.id, 'name': '刷卡機串接', 'state': 'done',
             'module_name': 'x_morning_pos', 'repo': 'Dobtor/Customers', 'release_tag': 'v18.0.1.0',
             'tests_green': True})
        mods, missing = self.prop._overlay_modules()
        self.assertEqual([(m['module'], m['repo_url'], m['ref']) for m in mods],
                         [('x_morning_pos', 'https://github.com/Dobtor/Customers', 'v18.0.1.0')])
        self.assertEqual(missing, [])
        self.assertEqual(self.prop._overlay_modules({'x_morning_pos'})[0], [], '母體已經有的不疊')
        dev.write({'repo': False})
        self.assertEqual(self.prop._overlay_modules()[1], ['x_morning_pos'])
        plan = self._proposal_plan()
        p3 = [r for r in plan.run_checks('t1').results() if r['code'] == 'P3'][0]
        if 'x_morning_pos' in plan.module_ids.mapped('module'):
            self.assertEqual(p3['state'], 'block', '沒有程式來源才擋')
        dev.write({'repo': 'Dobtor/Customers'})
        p3 = [r for r in plan.run_checks('t1').results() if r['code'] == 'P3'][0]
        self.assertEqual(p3['state'], 'pass', '有來源就改為疊加，不擋')

    def test_overlay_scan_features_stay_off_package(self):
        """掃描用說明庫盤到的客戶模組功能點進這份計畫的底稿，但不掛到方案。"""
        from unittest.mock import patch
        from odoo.addons.dobtor_corpaas_knowledge.tests.test_usage_flow import make_database
        db = make_database(self.env, 9491)
        self.env['corpaas.knowledge.dev_item'].create(
            {'proposal_id': self.prop.id, 'pain_id': self.pain2.id, 'name': 'POS', 'state': 'done',
             'module_name': 'x_morning_pos', 'repo': 'Dobtor/Customers', 'release_tag': 'v1', 'tests_green': True})
        plan = self._proposal_plan()
        Pkg, Sb = type(self.pkg), type(self.env['corpaas.knowledge.sandbox'])
        Ov = type(self.env['corpaas.knowledge.overlay'])
        analysis = {'features': [
            {'module': 'x_morning_pos', 'kind': 'action', 'anchor': 'x_morning_pos.act', 'name': '刷卡紀錄',
             'model': 'res.partner', 'action_xmlid': 'x_morning_pos.act'},
            {'module': 'sale', 'kind': 'action', 'anchor': 'sale.act', 'name': '不該收'}]}

        def prepare(ovs):
            ovs.line_ids.write({'repo_dir': 'dobtor-customers', 'sha': 'c' * 40})
            ovs.write({'state': 'ready'})
        with patch.object(Pkg, '_knowledge_master', lambda s, raise_if_missing=True: db.instance_id), \
                patch.object(Ov, 'action_prepare', prepare), \
                patch.object(Sb, 'rebuild_scan', lambda s: True), \
                patch.object(Sb, '_shell', lambda s, script: analysis if 'MODS' in script else {}), \
                patch.object(Sb, 'drop', lambda s: True):
            plan._ledger_build()
        keys = plan.overlay_feature_ids.mapped('feature_key')
        self.assertEqual(len(keys), 1)
        f = plan.overlay_feature_ids
        self.assertEqual(f.module, 'x_morning_pos', '只收疊加模組的')
        self.assertNotIn(self.pkg, f.package_ids, '不掛到方案')
        self.assertIn(f, plan.line_ids.mapped('feature_id'), '進這份計畫的底稿')
        sig = plan.overlay_scan_sig
        self.assertTrue(sig)

    def test_make_standard_module(self):
        """第四期：轉為標準模組要先登記；之後程式知識改判公開、被退回的改回待送。"""
        from unittest.mock import patch
        dev = self.env['corpaas.knowledge.dev_item'].create(
            {'proposal_id': self.prop.id, 'name': '會員卡', 'state': 'done', 'module_name': 'x_std_mod'})
        Repo = self.env.get('infrastructure.repository.module')
        if Repo is None:
            self.skipTest('沒有模組清單模型')
        with self.assertRaises(UserError):
            dev.action_make_standard()
        d = self.env['corpaas.knowledge.code_def'].sudo().create(
            {'def_hash': 'std1', 'method': 'action_x', 'module': 'x_std_mod', 'summary_json': '{"pre": []}'})
        d.write({'kb_sync_state': 'rejected'})
        self.assertEqual(d.kb_visibility, 'private')
        Vis = type(self.env['corpaas.knowledge.exchange.visibility']) \
            if 'corpaas.knowledge.exchange.visibility' in self.env else None
        if Vis is None:
            self.skipTest('沒裝交換模組')
        with patch.object(type(Repo), 'search_count', lambda s, dom, **k: 1), \
                patch.object(Vis, '_public_modules', lambda s, mods: set(mods)):
            dev.action_make_standard()
        self.assertTrue(dev.standard_module)
        self.assertEqual((d.kb_visibility, d.kb_sync_state), ('public', 'local'), '改公開、下次送件再送')

    def test_p4_customer_instance(self):
        from unittest.mock import patch
        from odoo.addons.dobtor_corpaas_knowledge.tests.test_usage_flow import make_database
        plan = self._proposal_plan()
        p4 = lambda: [r for r in plan.run_checks('t1').results() if r['code'] == 'P4'][0]
        self.assertEqual(p4()['state'], 'pass', '新客戶不擋')
        db = make_database(self.env, 9495)
        self.prop.customer_database_id = db
        self.assertEqual(p4()['state'], 'block', '有既有實例但還沒分析')
        with patch('odoo.addons.dobtor_corpaas_knowledge.services.remote.shell_json',
                   return_value={'installed': ['sale', 'x_legacy'], 'counts': {'res.partner': 120}}) as sj, \
                patch.object(type(self.pkg), '_knowledge_available_modules', lambda s: {'sale', 'dobtor_p'}):
            self.prop.action_analyze_customer_instance()
        self.assertTrue(sj.call_args.kwargs.get('isolated'), '唯讀分析走一次性容器')
        self.assertIn('x_legacy', self.prop.customer_analysis_text)
        self.assertIn('dobtor_p', self.prop.customer_analysis_text)
        self.assertEqual(p4()['state'], 'pass')

    def test_dev_done_triggers_project_refresh(self):
        Pkg = type(self.pkg)
        proj = self.env['infrastructure.solution.package'].create({
            'product_tmpl_id': self.env['product.template'].create({'name': '專案', 'type': 'service'}).id,
            'knowledge_kind': 'project', 'knowledge_project_partner_id': self.partner.id, 'knowledge_enabled': True})
        dev = self.env['corpaas.knowledge.dev_item'].create(
            {'proposal_id': self.prop.id, 'name': '刷卡', 'state': 'test', 'module_name': 'x_pos',
             'release_tag': 'v1', 'tests_green': True})
        calls = []
        with patch.object(Pkg, 'knowledge_enqueue_refresh', lambda s, full=False, reason='', **k: calls.append((s.ids, reason))):
            dev.action_mark_done()
            dev.write({'state': 'done'})
        self.assertEqual(calls, [(proj.ids, 'dev_release')], '完成一次觸發一次（重寫完成不重複）')

    def test_private_scenario_and_channel(self):
        plan = self._proposal_plan()
        Item = self.env['corpaas.knowledge.plan.item'].with_context(knowledge_plan_system=True)
        ch = Item.create({'plan_id': plan.id, 'kind': 'chapter', 'key': 'reg', 'name': '線上報名',
                          'content_json': json.dumps({'library_code': 'src_reg'})})
        Item.create({'plan_id': plan.id, 'kind': 'story', 'key': 'story', 'name': '晨光協會',
                     'content_json': json.dumps({'company': '晨光協會', 'narrative': '協會辦年會。'})})
        Item.create({'plan_id': plan.id, 'kind': 'role', 'key': 'admin', 'name': '管理員',
                     'content_json': json.dumps({'groups': ['base.group_system']})})
        plan.line_ids.filtered(lambda l: l.feature_id == self.f_in).write({'assignment': 'chapter',
                                                                          'item_id': ch.id})
        self.assertFalse(plan._plan_try_auto_approve(), '建議書來源初版一定由人核准')
        with patch.object(type(self.env['corpaas.knowledge.scenario']), '_knowledge_auto_draft_seed'):
            plan._plan_approve('manual')
        sc = plan.live_items('story').record()
        self.assertEqual(sc.knowledge_private_partner_id, self.partner)
        self.assertEqual(sc.knowledge_scope_capability_ids, self.cap)
        self.assertTrue(sc.code.startswith('prop_'))
        self.assertFalse(self.pkg.knowledge_plan_id, '產品來源的計畫優先；建議書計畫不當方案的生效計畫')
        Channel = self.env['slide.channel']
        if hasattr(Channel, '_knowledge_private_channel_for'):
            chan = Channel._knowledge_private_channel_for(self.pkg.product_tmpl_id, self.partner)
            self.assertEqual(chan.visibility, 'members')
            self.assertFalse(chan.knowledge_product_tmpl_id, '私人課程不佔方案產品的公開 channel')
            self.assertEqual(Channel._knowledge_private_channel_for(self.pkg.product_tmpl_id, self.partner), chan)
