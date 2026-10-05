# -*- coding: utf-8 -*-
"""P0／P1：外部 RPC 改已上線內容要退回草稿、說明庫沿用（R1）、執行紀錄（A5）。"""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models import content_mixin


@tagged('post_install', '-at_install')
class TestExternalRpcGuard(TransactionCase):

    def test_rpc_write_on_published_reverts_to_draft(self):
        sc = self.env['corpaas.knowledge.scenario'].sudo().create(
            {'name': 'RPC 防護', 'code': 'kb_rpc_guard', 'narrative': 'a'})
        sc._do_publish('new')
        self.assertEqual(sc.state, 'published')
        token = content_mixin._EXTERNAL_RPC_METHOD.set('write')
        try:
            sc.write({'narrative': 'b'})
        finally:
            content_mixin._EXTERNAL_RPC_METHOD.reset(token)
        self.assertEqual(sc.state, 'draft',
                         '外部 RPC 改了上線內容的文字：退回草稿，重新核准前對外仍是上一版')

    def test_rpc_button_call_is_not_a_client_write(self):
        token = content_mixin._EXTERNAL_RPC_METHOD.set('action_approve')
        try:
            self.assertFalse(self.env['corpaas.knowledge.scenario']._kb_client_write())
        finally:
            content_mixin._EXTERNAL_RPC_METHOD.reset(token)

    def test_dispatch_is_wrapped(self):
        import odoo.service.model as svc
        self.assertTrue(getattr(svc.dispatch, '_kb_wrapped', False))


@tagged('post_install', '-at_install')
class TestSandboxReuse(TransactionCase):

    def test_reusable_rules(self):
        Sandbox = self.env['corpaas.knowledge.sandbox']
        sb = Sandbox.new({'state': 'ready', 'ready_at': fields.Datetime.now(),
                          'inputs_sig': 'abc', 'dirty': False})
        with patch.object(type(Sandbox), '_inputs_signature', lambda s: 'abc'):
            self.assertTrue(sb._reusable())
            sb.dirty = True
            self.assertFalse(sb._reusable(), '被拍攝改過資料：一定重建')
            sb.dirty = False
            sb.state = 'failed'
            self.assertFalse(sb._reusable())
        with patch.object(type(Sandbox), '_inputs_signature', lambda s: 'xyz'):
            sb.state = 'ready'
            self.assertFalse(sb._reusable(), '輸入變了要重建')


@tagged('post_install', '-at_install')
class TestRunRecord(TransactionCase):

    def test_stages_and_stats(self):
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create(
                {'name': 'RUN', 'type': 'service'}).id})
        run = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': pkg.id, 'token': 'tok-run', 'reason': 'manual', 'full': True})
        run.begin_stage('prepare')
        run.add_stats(sandboxes_reused=1)
        run.end_stage()
        run.begin_stage('shoot')
        run.add_stats(shots_planned=10, shots_skipped=84)
        run.add_stats(shots_planned=2)
        run.mark_done()
        self.assertEqual(run.state, 'done')
        self.assertEqual(run.stats()['shots_planned'], 12)
        self.assertIn('沿用截圖 84', run.summary)
        import json
        log = json.loads(run.log_json)
        self.assertEqual([x['stage'] for x in log], ['prepare', 'shoot'])
        self.assertTrue(all('seconds' in x for x in log))

    def test_failed_run_resumes_failed_stage(self):
        pkg = self.env['infrastructure.solution.package'].sudo().create({
            'product_tmpl_id': self.env['product.template'].create(
                {'name': 'RUN2', 'type': 'service'}).id})
        run = self.env['corpaas.knowledge.run'].sudo().create(
            {'package_id': pkg.id, 'token': 'tok-run2'})
        run.begin_stage('shoot')
        run.mark_failed('boom')
        calls = []
        Pkg = type(pkg)
        with patch.object(Pkg, '_knowledge_enqueue_stage',
                          lambda s, r, stage: calls.append(stage)):
            run.action_resume()
        self.assertEqual(calls, ['shoot'])
        self.assertEqual(run.state, 'running')
