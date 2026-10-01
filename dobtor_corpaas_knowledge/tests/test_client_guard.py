# -*- coding: utf-8 -*-
"""用戶端直接寫入的防護：經由真正的 /web/dataset/call_kw 送出。"""
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestClientWriteGuard(HttpCase):

    def setUp(self):
        super().setUp()
        self.editor = new_test_user(
            self.env, 'cg_editor', password='cg_editor_pw',
            groups='base.group_user,dobtor_corpaas_knowledge.group_knowledge_editor')
        self.cap = self.env['corpaas.knowledge.capability'].create(
            {'name': '能力', 'code': 'cg', 'outcome': '核准版'})
        self.cap.knowledge_propose('new')
        self.cap.action_approve()

    def _rpc(self, method, args):
        self.authenticate('cg_editor', 'cg_editor_pw')
        return self.make_jsonrpc_request('/web/dataset/call_kw', {
            'model': self.cap._name, 'method': method, 'args': args, 'kwargs': {}})

    def test_state_write_rejected(self):
        with self.assertRaises(Exception):
            self._rpc('write', [[self.cap.id], {'state': 'published', 'published_rev_no': 99}])
        self.cap.invalidate_recordset()
        self.assertEqual(self.cap.state, 'published')

    def test_text_edit_returns_to_draft(self):
        self._rpc('write', [[self.cap.id], {'outcome': '沒審過的新文字'}])
        self.cap.invalidate_recordset()
        self.assertEqual(self.cap.state, 'draft')
        self.cap.knowledge_reshoot_done()
        self.assertEqual(self.cap.state, 'draft', '純重拍不能把沒審過的文字發佈出去')
        self.assertEqual(self.cap._last_published_snapshot().get('outcome'), '核准版')

    def test_server_side_flows_unaffected(self):
        self.cap.knowledge_mark_stale('畫面變了')
        self.assertEqual(self.cap.state, 'stale')
        self.cap._knowledge_retire()
        self.assertEqual(self.cap.state, 'retired')
