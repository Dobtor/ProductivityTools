# -*- coding: utf-8 -*-
"""方案知識 × 白標經銷商：範圍、建立專案知識、計畫事件、說明書匯出、AI 費用計費、API。"""
import json
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from odoo.addons.dobtor_corpaas_knowledge.tests.test_usage_flow import make_database
from odoo.addons.dobtor_corpaas_knowledge_manual.tests.common import ManualCase, png

API = 'odoo.addons.dobtor_corpaas_knowledge_reseller.controllers.knowledge_api'


class _ResellerProject:

    def _setup_project(self, number=9601):
        env = self.env
        self.reseller = env['res.partner'].create({'name': 'KB Reseller', 'is_reseller': True,
                                                   'is_company': True})
        self.db = make_database(env, number)
        self.inst = self.db.instance_id
        env.cr.execute("UPDATE infrastructure_instance SET state='active' WHERE id=%s", (self.inst.id,))
        env.cr.execute("UPDATE infrastructure_database SET state='active' WHERE id=%s", (self.db.id,))
        self.inst.invalidate_recordset(); self.db.invalidate_recordset()
        self.req = env['infrastructure.provision.request'].sudo().create({
            'reseller_id': self.reseller.id, 'external_ref': 'KB-%s' % number,
            'customer_name': 'C', 'database_id': self.db.id, 'state': 'done'})
        Pkg = type(env['infrastructure.solution.package'])
        with patch.object(Pkg, 'knowledge_enqueue_refresh', lambda s, full=False, reason='', **k: None):
            self.pkg = env['infrastructure.solution.package']._reseller_create_project(
                self.reseller, self.db, '合約第 9 條')


@tagged('post_install', '-at_install')
class TestResellerProject(_ResellerProject, ManualCase):

    def setUp(self):
        super().setUp()
        self._setup_project()

    def test_project_belongs_to_reseller(self):
        self.assertEqual(self.pkg.knowledge_kind, 'project')
        self.assertEqual(self.pkg.knowledge_reseller_id, self.reseller)
        self.assertEqual(self.pkg.knowledge_project_database_id, self.db)
        self.assertIn('KB Reseller', self.pkg.knowledge_project_consent_note)

    def test_consent_and_uniqueness(self):
        db2 = make_database(self.env, 9602)
        self.env.cr.execute("UPDATE infrastructure_database SET state='active' WHERE id=%s", (db2.id,))
        db2.invalidate_recordset()
        with self.assertRaises(UserError):
            self.env['infrastructure.solution.package']._reseller_create_project(
                self.reseller, db2, '  ')
        with self.assertRaises(UserError):
            self.env['infrastructure.solution.package']._reseller_create_project(
                self.reseller, self.db, 'again')

    def test_plan_review_and_done_emit_webhooks(self):
        self.reseller.write({'reseller_webhook_url': 'https://example.com/h',
                             'reseller_webhook_secret': 's'})
        plan = self.env['corpaas.knowledge.plan'].sudo().search([('package_id', '=', self.pkg.id)], limit=1)
        Ev = self.env['reseller.webhook.event'].sudo()
        plan.with_context(knowledge_plan_system=True).write({'state': 'review'})
        plan.with_context(knowledge_plan_system=True).write({'state': 'done'})
        types = Ev.search([('reseller_id', '=', self.reseller.id)]).mapped('event_type')
        self.assertIn('knowledge_plan_review', types)
        self.assertIn('knowledge_published', types)
        ev = Ev.search([('event_type', '=', 'knowledge_published')], limit=1)
        self.assertEqual(ev.external_ref, self.req.external_ref)

    def test_manual_export_rewrites_images(self):
        att = self.env['ir.attachment'].sudo().create({
            'name': 's.png', 'raw': png(), 'mimetype': 'image/png', 'public': True})
        channel = self.env['slide.channel'].sudo().create({'name': '專案說明書'})
        slide = self.env['slide.slide'].sudo().create({
            'name': '開立訂單', 'channel_id': channel.id, 'slide_category': 'article',
            'html_content': '<p>步驟</p><img src="/web/image/%s/800x600"/>' % att.id,
            'is_published': True})
        art = self._article(self.f1)
        self.env['corpaas.knowledge.placement'].sudo().create({
            'article_id': art.id, 'channel_id': channel.id, 'package_id': self.pkg.id})
        self.env['corpaas.knowledge.placement'].sudo().search(
            [('channel_id', '=', channel.id)]).write({'slide_id': slide.id})
        payload, images = self.pkg._reseller_manual_export()
        self.assertEqual(images, {att.id})
        html = payload['channels'][0]['slides'][0]['html']
        self.assertIn('corpaas-image:%s' % att.id, html)
        self.assertNotIn('/web/image/', html)

    def test_ai_cost_billed_to_reseller(self):
        self.env['ir.config_parameter'].sudo().set_param('corpaas.reseller.knowledge_ai_markup', '1.5')
        Call = self.env['corpaas.knowledge.ai.call'].sudo()
        c1 = Call.create({'purpose': 'x', 'package_id': self.pkg.id, 'cost_usd': 2.0, 'ok': True})
        c2 = Call.create({'purpose': 'y', 'package_id': self.pkg.id, 'cost_usd': 9.0, 'ok': True,
                          'cached': True})
        self.env.cr.execute("UPDATE corpaas_knowledge_ai_call SET create_date='2026-09-10' "
                            "WHERE id IN %s", (tuple((c1 | c2).ids),))
        St = self.env['reseller.billing.statement'].sudo()
        St._apply_knowledge_costs(date(2026, 9, 1), date(2026, 9, 30))
        st = St.search([('reseller_id', '=', self.reseller.id), ('period_start', '=', date(2026, 9, 1))])
        line = st.line_ids.filtered(lambda l: l.line_type == 'knowledge')
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.base_price, 3.0)
        St._apply_knowledge_costs(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(len(st.line_ids.filtered(lambda l: l.line_type == 'knowledge')), 1)


@tagged('post_install', '-at_install')
class TestResellerKnowledgeApi(_ResellerProject, ManualCase, HttpCase):

    def setUp(self):
        super().setUp()
        self._setup_project(9611)

    def _call(self, path, body=None, reseller=None):
        with patch('%s._authenticate' % API, return_value=reseller or self.reseller):
            if body is None:
                return self.url_open(path)
            return self.url_open(path, data=json.dumps(body),
                                 headers={'Content-Type': 'application/json'})

    def test_list_and_scope(self):
        r = self._call('/api/v1/knowledge')
        self.assertEqual(r.status_code, 200, r.text)
        ids = [k['id'] for k in r.json()['knowledge']]
        self.assertIn(self.pkg.id, ids)
        other = self.env['res.partner'].create({'name': 'Other', 'is_reseller': True})
        self.assertNotIn(self.pkg.id, [k['id'] for k in self._call(
            '/api/v1/knowledge', reseller=other).json()['knowledge']])
        self.assertEqual(self._call('/api/v1/knowledge/%s/manual' % self.pkg.id,
                                    reseller=other).status_code, 404)

    def test_approve_requires_review_state(self):
        plan = self.env['corpaas.knowledge.plan'].sudo().search([('package_id', '=', self.pkg.id)], limit=1)
        r = self._call('/api/v1/knowledge/%s/plan/%s/approve' % (self.pkg.id, plan.id), {})
        self.assertEqual(r.status_code, 409)
        plan.with_context(knowledge_plan_system=True).write({'state': 'review'})
        Plan = type(plan)
        with patch.object(Plan, 'run_checks', lambda s, m: type('C', (), {'state': 'pass'})()), \
                patch.object(Plan, '_plan_approve', lambda s, mode: s.with_context(
                    knowledge_plan_system=True).write({'state': 'approved'})):
            r = self._call('/api/v1/knowledge/%s/plan/%s/approve' % (self.pkg.id, plan.id), {})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(plan.state, 'approved')

    def test_image_only_if_referenced(self):
        att = self.env['ir.attachment'].sudo().create({
            'name': 'x.png', 'raw': png(), 'mimetype': 'image/png'})
        r = self._call('/api/v1/knowledge/%s/image/%s' % (self.pkg.id, att.id))
        self.assertEqual(r.status_code, 404)

    def test_create_project_via_api_needs_own_service(self):
        r = self._call('/api/v1/knowledge/project', {'external_ref': 'nope', 'consent_note': 'x'})
        self.assertEqual(r.status_code, 404)
        r = self._call('/api/v1/knowledge/project',
                       {'external_ref': self.req.external_ref, 'consent_note': 'x'})
        self.assertEqual(r.status_code, 409)   # 已經有專案知識


@tagged('post_install', '-at_install')
class TestOwnHubNotBilled(_ResellerProject, ManualCase):

    def setUp(self):
        super().setUp()
        self._setup_project(9621)

    def test_own_hub_costs_not_billed(self):
        self.pkg.write({'knowledge_hub_url': 'https://ai.reseller.example', 'knowledge_hub_key': 'k'})
        c = self.env['corpaas.knowledge.ai.call'].sudo().create(
            {'purpose': 'x', 'package_id': self.pkg.id, 'cost_usd': 5.0, 'ok': True})
        self.env.cr.execute("UPDATE corpaas_knowledge_ai_call SET create_date='2026-09-10' WHERE id=%s", (c.id,))
        made = self.env['reseller.billing.statement'].sudo()._apply_knowledge_costs(
            date(2026, 9, 1), date(2026, 9, 30))
        self.assertFalse(made)


@tagged('post_install', '-at_install')
class TestResellerPlanStart(_ResellerProject, ManualCase):

    def setUp(self):
        super().setUp()
        Plan = type(self.env['corpaas.knowledge.plan'])
        self._p = patch.object(Plan, 'action_build_ledger', lambda s: s.with_context(
            knowledge_plan_system=True).write({'state': 'ledger'}))
        self._p.start()
        self.addCleanup(self._p.stop)
        self._setup_project(9631)

    def test_project_opens_initial_plan_once(self):
        plans = self.env['corpaas.knowledge.plan'].search([('package_id', '=', self.pkg.id)])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans.state, 'ledger')
        self.assertFalse(self.pkg._reseller_ensure_plan(), '已有計畫不再開')
