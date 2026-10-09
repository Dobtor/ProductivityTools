# -*- coding: utf-8 -*-
"""探針自己的測試——`SessionAliveMixin` 壞了會遮住所有東西。

☠️ 為什麼需要這一支：`tests/session_probe.py` 在拆模組之後成為**兩個模組共用
的基礎設施**（`dobtor_doc_import/tests/test_import_routes.py` 也 import 它）。
它的工作是「偶發失敗發生時把原因說出來」——如果它自己壞了，症狀是
**偶發依舊發生、而且依舊沒有證據**，跟它不存在時一模一樣。

這正是本模組反覆出現的失效模式套在診斷工具上的版本：
診斷工具存在、被呼叫，但它的產出到不了任何人眼前。

驗 `_jsonrpc_with_evidence()` 的兩個方向：
  1. 正常路由 → 回 result（不可以把成功當失敗）
  2. 回應不是 JSON → 失敗訊息裡要**真的帶著證據**
     （狀態碼、Content-Type、最終 URL、內文片段）
"""
from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSessionProbeItself(SessionAliveMixin, HttpCase):
    """`SessionAliveMixin` 的兩個方法都要真的有作用。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def test_assert_session_alive_passes_when_logged_in(self):
        """登入狀態下不可以誤報 session 掉了。"""
        self._assert_session_alive('test_session_probe_self')

    def test_jsonrpc_with_evidence_returns_result_on_success(self):
        """正常的 json 路由要原樣回傳 result。"""
        result = self._jsonrpc_with_evidence(
            '/web/session/get_session_info', {}, where='self-test')
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('uid'), self.env.ref('base.user_admin').id)

    def test_jsonrpc_with_evidence_reports_evidence_on_html_response(self):
        """回應是 HTML 時，失敗訊息要帶得出證據。

        `/web/login` 是 `type='http'`，所以用 JSON-RPC 的 envelope 打它會拿到
        HTML——正好就是 session 掉了之後 `auth='user'` 路由的那個形狀。
        """
        with self.assertRaises(AssertionError) as caught:
            self._jsonrpc_with_evidence('/web/login', {}, where='自我測試')
        msg = str(caught.exception)
        # 這四樣就是「偶發發生當下沒留下來」的那些東西
        for expected in ('狀態碼', 'Content-Type', '最終 URL', '內文前 400 字'):
            self.assertIn(
                expected, msg,
                '失敗訊息裡少了「%s」——那是偶發重現不了時唯一的線索。'
                '實際訊息：\n%s' % (expected, msg))
        self.assertIn('自我測試', msg, 'where 參數沒有出現在訊息裡')
