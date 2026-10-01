# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import time
from unittest.mock import MagicMock, patch

import requests

from odoo.tests.common import HttpCase, TransactionCase, tagged

from odoo.addons.dobtor_ai_bridge_help.lib import fingerprint_lib
from odoo.addons.dobtor_ai_bridge_help.models import ai_help_links

POST = 'odoo.addons.dobtor_ai_bridge_help.models.ai_help_links._post_json'
ELEMENTS = [{'field': 'name'}, {'field': 'email'}]


@tagged('post_install', '-at_install')
class TestHelpLinks(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Links = self.env['ai.help.links']
        # 主控台以 zh_TW 拍攝；只啟用語言、不載翻譯就夠讓 get_views 跑起來。
        self.env['res.lang']._activate_lang('zh_TW')
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('dobtor_ai_help.console_url', 'https://admin.corpaas.com')
        icp.set_param('dobtor_ai_help.public_domains', 'www.corpaas.com')
        patcher = patch.object(type(self.Links), '_report_divergence', autospec=True)
        self.report = patcher.start()
        self.addCleanup(patcher.stop)

    def _expected_hash(self):
        """獨立算一次（不走受測的方法），模擬主控台在黃金庫算出的值。"""
        data = self.env['res.partner'].with_context({'lang': 'zh_TW'}).get_views(
            [(False, 'form')])
        archs = {vt: v['arch'] for vt, v in data['views'].items()}
        return fingerprint_lib.scope_hash(archs, ELEMENTS, '聯絡人', 'form')[0]

    def _console(self, results):
        return {'ok': True, 'package': '方案', 'results': results}

    def _item(self, scope_hash, url='https://www.corpaas.com/slides/1', **fp):
        fingerprint = dict({'model': 'res.partner', 'elements': ELEMENTS,
                            'scope_hash': scope_hash, 'views': [[False, 'form']],
                            'menu_path': '聯絡人', 'view_mode': 'form', 'lang': 'zh_TW',
                            'version': fingerprint_lib.FINGERPRINT_VERSION}, **fp)
        return {'feature_key': 'contacts.action:contacts.action_contacts',
                'title': '聯絡人', 'url': url, 'kind': 'manual',
                'scenario': '標準情境', 'anchor': 'x', 'fingerprint': fingerprint}

    # ------------------------------------------------------------------
    def test_console_unreachable_returns_empty(self):
        with patch(POST, side_effect=requests.ConnectionError('down')):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertEqual(res['results'], [])
        self.assertFalse(res['ok'])
        self.assertEqual(res['error'], 'unreachable')

    def test_console_refusal_returns_empty(self):
        with patch(POST, return_value={'ok': False, 'error': 'unknown_database'}):
            res = self.Links.fetch_links(query='怎麼建聯絡人')
        self.assertEqual(res['results'], [])
        self.assertEqual(res['error'], 'unknown_database')

    def test_nothing_to_ask_skips_console(self):
        with patch(POST) as post:
            res = self.Links.fetch_links()
        post.assert_not_called()
        self.assertEqual(res['results'], [])

    def test_request_params(self):
        action = self.env.ref('base.action_res_users')
        with patch(POST, return_value=self._console([])) as post:
            self.Links.fetch_links(action=action.id, model='res.users', view_type='list')
        url, params, timeout = post.call_args[0]
        self.assertEqual(url, 'https://admin.corpaas.com/corpaas/knowledge/v1/help')
        self.assertEqual(params['action_xmlid'], 'base.action_res_users')
        self.assertEqual(params['database'], self.env.cr.dbname)
        self.assertEqual(timeout, 8)
        self.env['ir.config_parameter'].sudo().set_param('dobtor_ai_help.database', 'cust-a')
        with patch(POST, return_value=self._console([])) as post:
            self.Links.fetch_links(query='x')
        self.assertEqual(post.call_args[0][1]['database'], 'cust-a')

    def test_action_xmlid_conversion(self):
        action = self.env.ref('base.action_res_users')
        self.assertEqual(self.Links._action_xmlid(action.id), 'base.action_res_users')
        self.assertEqual(self.Links._action_xmlid(str(action.id)), 'base.action_res_users')
        self.assertEqual(self.Links._action_xmlid('base.action_res_users'),
                         'base.action_res_users')
        self.assertEqual(self.Links._action_xmlid(0), '')
        self.assertEqual(self.Links._action_xmlid(False), '')
        self.assertEqual(self.Links._action_xmlid(99999999), '')
        self.assertEqual(self.Links._action_xmlid('not an xmlid'), '')

    def test_unsafe_urls_dropped(self):
        good = self._item('x', url='https://www.corpaas.com/slides/1')
        items = [good,
                 self._item('x', url='http://www.corpaas.com/slides/1'),
                 self._item('x', url='javascript:alert(1)'),
                 self._item('x', url='https://evil.example.com/'),
                 self._item('x', url='https://user:pw@www.corpaas.com/'),
                 self._item('x', url='https://admin.corpaas.com/knowledge/2')]
        with patch(POST, return_value=self._console(items)):
            res = self.Links.fetch_links(query='聯絡人', limit=10)
        urls = [r['url'] for r in res['results']]
        self.assertEqual(urls, ['https://www.corpaas.com/slides/1',
                                'https://admin.corpaas.com/knowledge/2'])
        self.assertIn('www.corpaas.com', res['hosts'])

    def test_matching_fingerprint_not_diverged(self):
        item = self._item(self._expected_hash())
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertEqual(len(res['results']), 1)
        self.assertFalse(res['results'][0]['diverged'])
        self.assertEqual(res['results'][0]['scenario'], '標準情境')
        self.report.assert_not_called()

    def test_different_fingerprint_diverged_and_reported(self):
        item = self._item('0' * 32)
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertTrue(res['results'][0]['diverged'])
        self.report.assert_called_once()
        _self, key, expected, actual = self.report.call_args[0]
        self.assertEqual(key, item['feature_key'])
        self.assertEqual(expected, '0' * 32)
        self.assertEqual(actual, self._expected_hash())

    def test_any_role_hash_matches_not_diverged(self):
        """★ 多角色：租戶算出的雜湊落在任一角色的那份就不算分歧；
        都不在才分歧，回報的 expected 取 scope_hashes 第一個。"""
        mine = self._expected_hash()
        item = self._item('f' * 32, scope_hashes=['a' * 32, mine, 'f' * 32])
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertFalse(res['results'][0]['diverged'])
        self.report.assert_not_called()
        item = self._item(mine, scope_hashes=['a' * 32, 'b' * 32])
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertTrue(res['results'][0]['diverged'],
                        '有 scope_hashes 時以清單為準，不看 scope_hash')
        _self, _key, expected, actual = self.report.call_args[0]
        self.assertEqual((expected, actual), ('a' * 32, mine))

    def test_missing_element_on_tenant_is_diverged(self):
        """黃金庫有、本庫沒有的欄位 → MISSING → 不一致。"""
        item = self._item(self._expected_hash(),
                          elements=ELEMENTS + [{'field': 'x_not_here'}])
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertTrue(res['results'][0]['diverged'])

    def test_no_fingerprint_or_other_version_not_diverged(self):
        bare = dict(self._item('x'), fingerprint={})
        future = self._item('0' * 32, version=fingerprint_lib.FINGERPRINT_VERSION + 1)
        with patch(POST, return_value=self._console([bare, future])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertEqual([r['diverged'] for r in res['results']], [False, False])
        self.report.assert_not_called()

    def test_language_not_installed_not_compared(self):
        """本庫沒裝拍攝時的語言：差異來自語言而不是畫面，不標也不回報。"""
        item = self._item('0' * 32, lang='fr_BE')
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(model='res.partner', view_type='form')
        self.assertFalse(res['results'][0]['diverged'])
        self.report.assert_not_called()

    def test_query_does_not_borrow_screen_model(self):
        """自然語言查到的功能點可能在別的畫面：沒給 model 就不比，免得假警報。"""
        item = self._item('0' * 32, model=None)
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(query='聯絡人', model='res.partner')
        self.assertFalse(res['results'][0]['diverged'])
        item = self._item('0' * 32, model='res.partner')
        with patch(POST, return_value=self._console([item])):
            res = self.Links.fetch_links(query='聯絡人', model='sale.order')
        self.assertTrue(res['results'][0]['diverged'])


    def test_groups_param(self):
        """★ groups：目前使用者群組的 xmlid，排序、去空、上限 MAX_GROUPS。"""
        user = self.env['res.users'].create({
            'name': 'G', 'login': 'g_help',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        nameless = self.env['res.groups'].create({'name': '沒有 xmlid 的群組'})
        user.groups_id = [(4, nameless.id)]
        with patch(POST, return_value=self._console([])) as post:
            self.Links.with_user(user).fetch_links(query='x')
        groups = post.call_args[0][1]['groups']
        self.assertIn('base.group_user', groups)
        self.assertEqual(groups, sorted(groups))
        self.assertTrue(all(g and '.' in g for g in groups))
        expected = sorted(x for x in user.groups_id.get_external_id().values() if x)
        self.assertEqual(groups, expected)
        with patch.object(ai_help_links, 'MAX_GROUPS', 2), \
                patch(POST, return_value=self._console([])) as post:
            self.Links.with_user(user).fetch_links(query='x')
        self.assertEqual(len(post.call_args[0][1]['groups']), 2)


KEY = 'test-secret-key-0123456789abcdef'


def _fake_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


@tagged('post_install', '-at_install')
class TestHelpSigning(TransactionCase):
    """修正第二輪 1：送出的 bytes 就是被簽的 bytes。攔 requests.Session.post 取實際送出內容。"""

    def setUp(self):
        super().setUp()
        self.Links = self.env['ai.help.links']
        self.icp = self.env['ir.config_parameter'].sudo()
        self.icp.set_param('dobtor_ai_help.console_url', 'https://admin.corpaas.com')
        self.icp.set_param('dobtor_ai_help.database', 'cust-a')
        self.icp.set_param('dobtor_ai_help.console_key', KEY)

    def _call(self, payload=None, **kw):
        payload = payload or {'jsonrpc': '2.0', 'id': 1,
                              'result': {'ok': True, 'results': []}}
        with patch.object(requests.Session, 'post',
                          return_value=_fake_response(payload)) as post:
            res = self.Links.fetch_links(**(kw or {'query': '聯絡人'}))
        post.assert_called_once()
        return res, post.call_args

    def test_signature_matches_sent_bytes(self):
        before = int(time.time())
        _res, call = self._call()
        url = call.args[0]
        body, headers = call.kwargs['data'], call.kwargs['headers']
        self.assertEqual(url, 'https://admin.corpaas.com/corpaas/knowledge/v1/help')
        self.assertNotIn('json', call.kwargs, '要用 data= 送自己序列化的 bytes')
        self.assertIsInstance(body, bytes)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['X-KB-Database'], 'cust-a')
        ts = headers['X-KB-Timestamp']
        self.assertTrue(before <= int(ts) <= int(time.time()) + 1)
        expected = hmac.new(KEY.encode(), ts.encode() + b'.' + body,
                            hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-KB-Signature'], expected)
        params = json.loads(body)['params']
        self.assertEqual(params['database'], 'cust-a')
        self.assertIn('base.group_user', params['groups'])
        # 改一個 byte 簽章就對不上。
        tampered = hmac.new(KEY.encode(), ts.encode() + b'.' + body + b' ',
                            hashlib.sha256).hexdigest()
        self.assertNotEqual(headers['X-KB-Signature'], tampered)

    def test_divergence_post_signed(self):
        with patch.object(requests.Session, 'post',
                          return_value=_fake_response({'result': {'ok': True}})) as post:
            ai_help_links._post_json(
                'https://admin.corpaas.com/corpaas/knowledge/v1/divergence',
                {'database': 'cust-a', 'feature_key': 'k', 'expected': 'a', 'actual': 'b'},
                5, database='cust-a', key=KEY)
        kw = post.call_args.kwargs
        ts = kw['headers']['X-KB-Timestamp']
        self.assertEqual(kw['headers']['X-KB-Signature'], hmac.new(
            KEY.encode(), ts.encode() + b'.' + kw['data'], hashlib.sha256).hexdigest())

    def test_report_divergence_thread_uses_key(self):
        ai_help_links._REPORTED.clear()
        with patch.object(ai_help_links, '_post_json') as post, \
                patch.object(ai_help_links.threading, 'Thread') as thread:
            self.assertTrue(self.Links._report_divergence('k', 'a' * 32, 'b' * 32))
            thread.call_args.kwargs['target']()
        self.assertEqual(post.call_args.kwargs, {'database': 'cust-a', 'key': KEY})

    def test_unsigned_when_no_key(self):
        self.icp.set_param('dobtor_ai_help.console_key', False)
        res, call = self._call({'result': {'ok': False, 'error': 'unsigned'}})
        headers = call.kwargs['headers']
        self.assertEqual(headers['X-KB-Database'], 'cust-a')
        self.assertNotIn('X-KB-Signature', headers)
        self.assertNotIn('X-KB-Timestamp', headers)
        self.assertEqual((res['ok'], res['error'], res['results']), (False, 'unsigned', []))

    def test_key_status_in_settings(self):
        self.assertTrue(self.env['res.config.settings'].new({}).ai_help_key_set)
        self.icp.set_param('dobtor_ai_help.console_key', False)
        self.assertFalse(self.env['res.config.settings'].new({}).ai_help_key_set)

    def test_key_never_logged(self):
        logger = 'odoo.addons.dobtor_ai_bridge_help'
        with self.assertLogs(logger, level=logging.DEBUG) as logs, \
                patch.object(requests.Session, 'post',
                             side_effect=requests.ConnectionError('down')):
            res = self.Links.fetch_links(query='x')
        self.assertEqual(res['error'], 'unreachable')
        with self.assertLogs(logger, level=logging.DEBUG) as logs2:
            self._call({'result': {'ok': False, 'error': 'bad_signature'}})
        for line in logs.output + logs2.output:
            self.assertNotIn(KEY, line)
        self.assertTrue(any('bad_signature' in line for line in logs2.output))


@tagged('post_install', '-at_install')
class TestHelpRoute(HttpCase):

    def test_route_survives_unreachable_console(self):
        self.authenticate('admin', 'admin')
        with patch(POST, side_effect=requests.Timeout('slow')):
            res = self.make_jsonrpc_request('/dobtor_ai/help/links', {
                'action': self.env.ref('base.action_res_users').id,
                'model': 'res.users', 'view_type': 'list'})
        self.assertEqual(res['results'], [])
        self.assertEqual(res['error'], 'unreachable')

    def test_route_requires_assistant_group(self):
        self.env['res.users'].create({
            'name': 'Plain', 'login': 'plain_help', 'password': 'plain_help_pw',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.authenticate('plain_help', 'plain_help_pw')
        with patch(POST) as post:
            res = self.make_jsonrpc_request('/dobtor_ai/help/links', {'query': 'x'})
        post.assert_not_called()
        self.assertEqual(res['error'], 'forbidden')
