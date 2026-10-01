# -*- coding: utf-8 -*-
"""content_run：主控台送知識內容工作進來的那條路。

★ 派工一律 mock 掉：測試裡 postcommit 本來就不會觸發（TestCursor 不跑），
  但 mock 讓「有排派工」這件事可以被斷言，也不必依賴那個實作細節。
"""
import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

from odoo.addons.dobtor_ai_hub.models import ai_hub_route

PATH = '/ai_hub/api/v1/content_run'


@tagged('post_install', '-at_install')
class TestContentRun(HttpCase):

    def setUp(self):
        super().setUp()
        # ★ L0：知識內容不寫對方系統，專給主控台的來源不需要 bridge。
        self.source = self.env['ai.hub.source'].create({
            'name': 'CorPaaS 主控台', 'source_path': '/instances/console',
            'content_enabled': True,
        })
        self.source.action_generate_uplink_key()
        self.key = self.source.sudo().uplink_key
        patcher = patch.object(type(self.env['ai.hub.run']), '_schedule_dispatch')
        self.dispatch = patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, path, params, key=None):
        headers = {'Content-Type': 'application/json'}
        if key is not False:
            headers['X-AI-Hub-Key'] = key or self.key
        resp = self.url_open(path, data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'params': params}), headers=headers)
        data = resp.json()
        # ☠️ 例外在 `error` 不在 `result`：只取 result 的話失敗訊息會是空的 {}。
        if data.get('error') and not data.get('result'):
            info = (data['error'] or {}).get('data') or {}
            return {'ok': False, 'error': 'jsonrpc_error',
                    'detail': '%s: %s' % (info.get('name'), info.get('message'))}
        return data.get('result') or {}

    def _runs(self):
        return self.env['ai.hub.run'].search([('session_id.source_id', '=', self.source.id)])

    # ------------------------------------------------------------------
    def test_selection_and_requirements(self):
        for model, field in (('ai.hub.session', 'mode'), ('ai.hub.run', 'mode'),
                             ('ai.hub.artifact', 'type'), ('ai.hub.route.rule', 'mode')):
            values = dict(self.env[model]._fields[field].selection)
            self.assertIn('content', values, '%s.%s 少了 content' % (model, field))
        self.assertEqual(ai_hub_route.MODE_REQUIREMENTS.get('content'), ('has_agent_loop',))

    def test_no_key_rejected(self):
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'hi'}, key=False)
        self.assertEqual(res.get('error'), 'unauthorized')
        self.assertFalse(self._runs())

    def test_disabled_source_rejected(self):
        self.source.content_enabled = False
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'hi'})
        self.assertEqual(res.get('error'), 'content_disabled')
        self.assertFalse(self._runs())

    def test_prompt_too_long(self):
        self.source.content_max_chars = 10
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'x' * 11})
        self.assertEqual(res.get('error'), 'prompt_too_long')
        self.assertFalse(self._runs())

    def test_empty_prompt(self):
        res = self._post(PATH, {'purpose': 'x', 'prompt': '  '})
        self.assertEqual(res.get('error'), 'invalid_prompt')

    def test_quota_applies(self):
        self.source.uplink_daily_limit = 1
        self.assertTrue(self._post(PATH, {'purpose': 'a', 'prompt': 'one'}).get('ok'))
        second = self._post(PATH, {'purpose': 'b', 'prompt': 'two'})
        self.assertEqual(second.get('error'), 'quota_exceeded')

    def test_happy_path_creates_content_run(self):
        res = self._post(PATH, {'purpose': 'catalog_capabilities',
                                'prompt': '請回 JSON', 'context': {'package': 1}})
        self.assertTrue(res.get('ok'), res)
        run = self.env['ai.hub.run'].browse(res['run_id'])
        self.assertEqual(run.mode, 'content')
        self.assertEqual(run.origin, 'uplink', '不標 uplink 就不算配額')
        self.assertEqual(run.session_id.mode, 'content')
        self.assertEqual(run.session_id.name, 'catalog_capabilities')
        self.assertEqual(run.session_id.source_id, self.source)
        self.assertEqual(self.dispatch.call_count, 1)
        self.assertEqual(self.source.uplink_used_today, 1)
        # ★ 每次都是新 Session：續用會帶 --resume，上一件工作的上下文會混進來。
        again = self._post(PATH, {'purpose': 'catalog_capabilities', 'prompt': '再一次'})
        self.assertNotEqual(again['conversation'], res['conversation'])
        # 結果沿用既有的 run_status。
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertTrue(status.get('ok'), status)
        self.assertFalse(status.get('done'))

    def test_other_source_cannot_read_status(self):
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'hi'})
        other = self.env['ai.hub.source'].create({
            'name': 'Other', 'source_path': '/instances/other'})
        other.action_generate_uplink_key()
        peek = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']},
                          key=other.sudo().uplink_key)
        self.assertEqual(peek.get('error'), 'not_found')

    def test_content_status_not_brand_sanitized(self):
        """content 的 JSON 原文交回：品牌過濾會把 /odoo/ 路徑改壞。"""
        self.env['ir.config_parameter'].sudo().set_param('ai_hub.brand_filter', 'True')
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'hi'})
        run = self.env['ai.hub.run'].browse(res['run_id'])
        raw = '{"goto": {"url": "/odoo/action-sale.action_quotations"}, "note": "Odoo 18"}'
        run.sudo().write({'result_text': raw, 'stream_buffer': raw})
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertEqual(status.get('text'), raw)
        # 非 content 的 Run 仍照常過濾
        run.sudo().write({'mode': 'website'})
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertNotIn('Odoo', status.get('text'))


    def test_status_reports_done_for_terminal_states(self):
        """主控台靠 `done` 停止輪詢；沒有它就一路等到逾時。"""
        res = self._post(PATH, {'purpose': 'x', 'prompt': 'hi'})
        run = self.env['ai.hub.run'].browse(res['run_id'])
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertIs(status.get('done'), False)
        run.sudo().write({'state': 'done', 'result_text': '{}'})
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertIs(status.get('done'), True)
        run.sudo().write({'state': 'failed'})
        status = self._post('/ai_hub/api/v1/run_status', {'run_id': res['run_id']})
        self.assertIs(status.get('done'), True)
