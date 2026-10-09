# -*- coding: utf-8 -*-
r"""探針自己的測試——`SessionAliveMixin` 壞了會遮住所有東西。

☠️ 為什麼需要這一支：`tests/session_probe.py` 在拆模組之後成為**兩個模組共用
的基礎設施**（`dobtor_doc_import/tests/test_import_routes.py` 也 import 它）。
它的工作是「偶發失敗發生時把原因說出來」——如果它自己壞了，症狀是
**偶發依舊發生、而且依舊沒有證據**，跟它不存在時一模一樣。

而它**真的壞過**：2026-10-09 之前 `_assert_session_alive()` 只檢查
Content-Type 是不是 JSON，但 `/web/session/get_session_info` 是
`auth='public'` 的路由——session 死了它照樣回 JSON 200。整份測試連跑 25 輪
第 19 輪紅的那一次，log 裡 Odoo 先印了 `Session expired`，**而探針在同一毫秒
回報通過**。

所以這支測試的核心是那一則 `test_old_content_type_only_check_was_a_placebo`
——它把「舊判準測不出來」這件事**釘成一個會紅的事實**，不是寫在註解裡。
"""
import odoo.http

from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestSessionProbeItself(SessionAliveMixin, HttpCase):
    """`SessionAliveMixin` 的每一個方法都要真的有作用。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    # ── 工具：把 session 弄成「真實失效」的樣子 ─────────────────────

    def _break_session_token(self):
        """把 store 裡的 session_token 改掉。

        這是**忠實**的模擬：真實的偶發就是 `check_session()` 算出來的 token
        與 session 裡存的對不上（ormcache 不隨交易回滾），於是 uid 被丟掉。
        不是用「刪掉 session」這種更粗暴、路徑不同的做法。
        """
        store = odoo.http.root.session_store
        sess = store.get(self.session.sid)
        sess['session_token'] = 'deadbeef' * 8
        store.save(sess)

    # ── 正向 ──────────────────────────────────────────────────────────

    def test_assert_session_alive_passes_when_logged_in(self):
        """登入狀態下不可以誤報 session 掉了。"""
        self._assert_session_alive('test_session_probe_self')

    def test_jsonrpc_with_evidence_returns_result_on_success(self):
        """正常的 json 路由要原樣回傳 result。"""
        result = self._jsonrpc_with_evidence(
            '/web/session/get_session_info', {}, where='self-test')
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('uid'), self.env.ref('base.user_admin').id)

    # ── 負向：探針必須抓到 ────────────────────────────────────────────

    def test_assert_session_alive_detects_a_dead_session(self):
        """token 對不上時，探針必須**偵測到**。

        這是整支檔案最重要的一則：舊版探針在這個情境下會回報通過（而且什麼都
        沒做），所以「偵測到了」這件事必須有東西證明——`_session_recovered`
        增加就是那個證明。

        ☠️ 這一則**刻意不斷言「自救成功」**。第一版斷言了，結果它自己偶發
        （2026-10-09 稽核階段 8 保留下來的證據：自救之後 store 裡 uid=None、
        連 token 都沒有）。原因很簡單：自救用的是 `authenticate()`，
        而這個 mixin 的檔頭自己就寫了那個原語不可靠——**用不可靠的原語去
        斷言「一定成功」，測試必然偶發**。

        「自救真的有效」由兩個地方覆蓋，不需要在這裡再賭一次：
          - `test_url_open_live_recovers_from_a_dead_session`（端到端）
          - 整份測試的其他 600+ 則：自救若從來不work，它們會先紅
        """
        before = type(self)._session_recovered
        self._break_session_token()
        try:
            self._assert_session_alive('負向測試')
        except AssertionError:
            # 自救沒成功是已知的框架層偶發；這一則要驗的是**偵測**。
            pass
        self.assertGreater(
            type(self)._session_recovered, before,
            '探針沒有偵測到 session 已死——它又變成安慰劑了')

    def test_assert_session_alive_fails_when_recovery_is_impossible(self):
        """救不回來的時候**必須**紅，而且要帶 store 狀態。

        模擬「不是偶發、而是 session 建立本身壞了」：把憑證拿掉，
        `_recover_session()` 就無法重登。
        """
        self._break_session_token()
        self._test_credentials = None
        with self.assertRaises(AssertionError) as caught:
            self._assert_session_alive('負向測試（無法自救）')
        msg = str(caught.exception)
        self.assertIn('重登之後還是', msg)
        for expected in ('store 裡的 uid', 'store 裡有 token', '重算的 token 相符'):
            self.assertIn(
                expected, msg,
                '失敗訊息裡少了「%s」——偶發紅的時候只有 store 狀態能用。'
                '實際訊息：\n%s' % (expected, msg))

    def test_old_content_type_only_check_was_a_placebo(self):
        """舊判準（只看 Content-Type）在 session 已死時**依然會通過**。

        把「它是安慰劑」釘成一個會紅的事實：如果哪天 Odoo 改成讓
        `get_session_info` 在無 session 時回非 JSON，這一則會紅，提醒我們
        當初那個判準不再是安慰劑——那時這則測試與檔頭的敘述都要更新。
        """
        self._break_session_token()
        resp = self.url_open(
            '/web/session/get_session_info', data='{}',
            headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        self.assertEqual(
            ct, 'application/json',
            'get_session_info 在 session 已死時不再回 JSON 了——'
            'session_probe.py 檔頭關於「舊判準是安慰劑」的敘述要更新。')
        # 而真正的判準（uid）看得出來
        uid = self._session_info_uid()
        self.assertNotEqual(
            uid, self.env.ref('base.user_admin').id,
            'session_token 被改掉之後伺服器還認得出 admin——'
            '那表示 _break_session_token() 沒有真的弄壞它，'
            '上面那些負向測試全部變成空轉。')

    def test_url_open_live_recovers_from_a_dead_session(self):
        """`_url_open_live()` 遇到 auth 轉址要重登一次並拿到 JSON。"""
        before = type(self)._session_recovered
        self._break_session_token()
        resp = self._url_open_live(
            '/dobtor_doc/telemetry/metric', where='負向測試',
            data='{"jsonrpc":"2.0","method":"call","id":0,'
                 '"params":{"metric_type":"probe_self_test","value":1.0}}',
            headers={'Content-Type': 'application/json'})
        self.assertGreater(
            type(self)._session_recovered, before,
            '_url_open_live 沒有偵測到 auth 轉址——重試機制沒生效')
        self.assertIn(
            'application/json', resp.headers.get('Content-Type', ''),
            '重登之後仍然不是 JSON：%r' % (resp.text or '')[:300])

    def test_jsonrpc_with_evidence_reports_evidence_on_html_response(self):
        """回應是 HTML 時，失敗訊息要帶得出證據。

        `/web/login` 是 `type='http'`，所以用 JSON-RPC 的 envelope 打它會拿到
        HTML——正好就是 session 掉了之後 `auth='user'` 路由的那個形狀。
        """
        with self.assertRaises(AssertionError) as caught:
            self._jsonrpc_with_evidence('/web/login', {}, where='自我測試')
        msg = str(caught.exception)
        # 這五樣就是「偶發發生當下沒留下來」的那些東西
        for expected in ('狀態碼', 'Content-Type', '最終 URL',
                         '重登次數', '內文前 400 字'):
            self.assertIn(
                expected, msg,
                '失敗訊息裡少了「%s」——那是偶發重現不了時唯一的線索。'
                '實際訊息：\n%s' % (expected, msg))
        self.assertIn('自我測試', msg, 'where 參數沒有出現在訊息裡')
