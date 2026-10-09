r"""HttpCase 的 session 健康檢查與重試——共用 mixin。

為什麼需要：這些測試打的是 `auth='user'` 的路由。session 沒建立時 Odoo 不會
回 4xx，而是把請求**轉址到 `/web/login`**，於是回應變成 HTML 200。那時失敗會
出現在「回應不是 JSON」或「KeyError: 'result'」這類斷言上，**看起來像被測的
路由壞了**，其實是登入沒成立。

☠️ 檔名刻意**不**用 `test_` 開頭：`tests/__init__.py` 只 import 有測試類別的
檔案，而這支沒有類別。叫 `test_session_probe.py` 的話，「有類別卻沒 import」
那條檢查就要為它開例外（`test_pill_helpers.py` 已經讓 CI 誤判過一次）。

════════════════════════════════════════════════════════════════════════════
2026-10-09：這支探針原本是**安慰劑**，而且有 log 可以證明
════════════════════════════════════════════════════════════════════════════

整份測試連跑 25 輪，第 19 輪紅了一次
（`TestControllerSecurityBoundary.test_upload_template_path_traversal_filename_handled`）。
log 寫得一清二楚：

    ,203  Login successful ... admin               ← setUp 的 authenticate()
    ,214  odoo.http: Session expired               ← **探針那個請求自己**被判過期
    ,214  POST /web/session/get_session_info 200 - 1   ← 但探針通過了
    ,224  odoo.http: Session expired
    ,224  POST /dobtor_doc/upload_template   303   ← 轉址
    ,268  GET /web/login?redirect=...        200   ← 測試拿到 HTML

原本的 `_assert_session_alive()` 只檢查 Content-Type 是不是 `application/json`
——而 `/web/session/get_session_info` 是 **`auth='public'`** 的路由，session 死了
它照樣回 JSON 200（只是從 66 個 query 變成 1 個）。也就是說**它永遠不可能
偵測到 session 掉了**。它「從沒觸發過」不是因為沒發生，是因為它測不出來。

這就是本模組一整天反覆出現的失效模式套在診斷工具上的版本：
**工具存在、被呼叫、回報通過，而它量的東西跟它聲稱的不是同一件事。**

修法：比對伺服器回報的 `uid` 與 `self.session.uid`——那才是「session 還活著」
的定義。

### 為什麼 session 會在 10 毫秒內失效

`res.users._compute_session_token()` 掛了 `@tools.ormcache('sid')`，而 ormcache
是 **registry 層的快取、不隨交易回滾**。整份測試裡每個 `TransactionCase` 都
在自己的交易裡建記錄然後回滾（本模組有三支測試會 `create` res.users），
而 `check_session()` 比的是「存在 session 裡的 token」對「當下算出來的 token」。
快取與 DB 的真實狀態一旦錯開，`check_session()` 回 False → uid 被丟掉 →
`ir_http._auth_method_user()` 丟 SessionExpiredException → 303 到 /web/login。

這是 Odoo 框架在測試情境下的行為，**不是被測路由的缺陷**。而這些測試要驗的
是路由行為、不是 session 壽命——所以本 mixin 的請求 helper 偵測到 auth 層
轉址時會重登一次再試，並且**大聲記錄**（`_session_recovered` 計數 ＋
logger.warning），不是靜靜吞掉。

重現率：整份測試 25 輪裡 1 次（約 4%）。
"""
import json
import logging

_logger = logging.getLogger(__name__)

# auth 層把請求導去登入頁的痕跡
_LOGIN_PATH = '/web/login'


class SessionAliveMixin:
    """session 檢查、帶證據的 JSON-RPC、以及 session 失效時的一次重試。

    與 HttpCase 一起繼承，而且要放在 HttpCase **前面**（它覆寫
    `authenticate()` 來記住憑證，好在 session 掉了之後重登）。
    """

    #: 被 auth 層轉址而重登的次數。測試可以斷言它是 0，
    #: 但預設不斷言——重登是為了讓測試驗它真正要驗的東西。
    _session_recovered = 0

    def authenticate(self, user, password):
        """記住憑證，好讓 `_url_open_live()` 在 session 掉了之後重登。

        覆寫而不是另開一個 `authenticate_for_test()`，是為了讓既有的
        `self.authenticate('admin', 'admin')` 呼叫點**一個都不用改**。
        """
        self._test_credentials = (user, password)
        return super().authenticate(user, password)

    # ── 檢查 ──────────────────────────────────────────────────────────

    def _assert_session_alive(self, where, expected_uid=None):
        """確認 session 真的活著；死了就先自救，救不回來才紅。

        ☠️ 只看 Content-Type 的版本是安慰劑，見檔頭。`get_session_info` 是
        `auth='public'`，session 死了它照樣回 JSON 200、只是 uid 變成公開
        使用者。

        ☠️ 為什麼偵測到不直接紅：量過了——**`authenticate()` 本身就會偶發
        產出一個伺服器看不到的 session**。整份測試 7 輪裡 2 次，log 的形狀是

            ,879  Login successful ... admin        ← authenticate()
            ,882  odoo.http: Session expired
            ,882  POST get_session_info 200 - 0     ← 0 個 query ＝ 沒載到 session

        根因在 Odoo 的測試 session 機制（`HttpCase.authenticate()` 內部做
        `self.cr.flush()` ＋ `self.cr.clear()`，再用 `@ormcache('sid')` 的
        `_compute_session_token()` 算 token，而 ormcache 不隨交易回滾），
        **不在被測路由**。這些測試要驗的是路由行為、不是 session 壽命，
        所以偵測到就重登再確認一次，並且**大聲記錄**。
        救不回來才紅——那時就不是偶發，而是 session 建立本身壞了。
        """
        want = expected_uid if expected_uid is not None else \
            getattr(getattr(self, 'session', None), 'uid', None)
        self.assertTrue(
            want,
            '_assert_session_alive(%r) 在還沒 authenticate() 之前被呼叫——'
            '那時它什麼都驗不到。' % where)
        uid = self._session_info_uid()
        # ☠️ 有界重試 2 次，不是 1 次。2026-10-09 稽核階段 8 保留下來的失敗證據
        #    顯示：自救呼叫的 `authenticate()` **本身**偶發產出空 session
        #    （store 裡 uid=None、連 token 都沒有），所以「重登一次」會失敗在
        #    同一個不可靠的原語上。探針的工作是「建立一個能用的 session」，
        #    而不是測 session 壽命，所以多試一次是對的；但要有界，
        #    否則真的壞掉時會變成無限迴圈而不是紅燈。
        for _attempt in range(2):
            if uid == want:
                break
            if not self._recover_session('%s（探針第 %d 次）'
                                         % (where, _attempt + 1)):
                break
            want = getattr(self.session, 'uid', want)
            uid = self._session_info_uid()
        self.assertEqual(
            uid, want,
            'session 在 %s 時已經不是登入狀態，而且**重登之後還是**'
            '（伺服器回報 uid=%r，預期 %r，累計重登 %d 次）。\n'
            '這時候就不是偶發的 ormcache 競態，而是 session 建立本身有問題。\n'
            '%s\n見 tests/session_probe.py 檔頭。'
            % (where, uid, want, type(self)._session_recovered,
               self._session_store_state(
                   getattr(getattr(self, 'session', None), 'sid', None))))

    def _session_store_state(self, sid):
        """把 session store 裡的實際狀態印出來——偶發紅的時候只有這個能用。

        原本這段只存在於 `test_controllers.py` 的 `_why_not_json()` 裡，
        而那支診斷**那時還沒接到會紅的那則測試上**。搬進 mixin，兩邊共用。
        """
        if not sid:
            return '  （沒有 sid 可查）'
        import odoo.http
        from odoo.service import security
        try:
            stored = odoo.http.root.session_store.get(sid)
            uid = stored.get('uid')
            expected = security.compute_session_token(stored, self.env) \
                if uid else None
            match = bool(stored.get('session_token') and expected
                         and stored['session_token'] == expected)
            return ('  store 裡的 uid   = %r\n'
                    '  store 裡有 token = %r\n'
                    '  重算的 token 相符 = %r'
                    % (uid, bool(stored.get('session_token')), match))
        except Exception as e:
            return '  session store 讀不到：%s' % e

    def _session_info_uid(self):
        """問伺服器「你現在認為我是誰」。認不出來就回 None。"""
        resp = self.url_open(
            '/web/session/get_session_info', data='{}',
            headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        if ct != 'application/json':
            return None
        try:
            return ((resp.json() or {}).get('result') or {}).get('uid')
        except ValueError:
            return None

    # ── 請求（session 掉了就重登一次）─────────────────────────────────

    @staticmethod
    def _is_auth_redirect(resp):
        """`type='http'` 路由的 session 失效形狀：最終落在 /web/login。

        ☠️ 只認「最終 URL 是登入頁」這一個訊號。第一版寫成「history 裡有任何
        轉址就算」，結果 POST /web/login 自己也會轉一次 → 被誤判成 session
        失效 → 白白重登。**本模組自己的測試抓到了這個誤判。**
        """
        return _LOGIN_PATH in (getattr(resp, 'url', '') or '')

    @staticmethod
    def _is_session_expired_json(resp):
        """`type='json'` 路由的 session 失效形狀——**和 http 路由不一樣**。

        ☠️ 這是 2026-10-09 寫重試機制時量到的：`type='json'` 路由遇到
        SessionExpiredException **不會轉址**，它回 HTTP 200 + JSON-RPC error，
        `error.data.name` 是 `odoo.http.SessionExpiredException`。
        只看轉址的偵測器對 json 路由完全無效——而本模組的遙測、匯入路由
        全都是 `type='json'`。
        """
        if 'application/json' not in (resp.headers.get('Content-Type') or ''):
            return False
        try:
            body = resp.json()
        except ValueError:
            return False
        # ☠️ resp.json() 不一定是 dict。本模組的 `type='http'` 路由有幾條
        #    回的是 JSON 字串（json.dumps 了一個字串），第一版直接
        #    `.get()` 下去 → AttributeError: 'str' object has no attribute 'get'
        #    ——本模組自己的 4 則測試當場抓到。
        if not isinstance(body, dict):
            return False
        err = body.get('error')
        if not isinstance(err, dict):
            return False
        data = err.get('data')
        if not isinstance(data, dict):
            return False
        return 'SessionExpired' in (data.get('name') or '')

    @classmethod
    def _looks_session_expired(cls, resp):
        return cls._is_auth_redirect(resp) or cls._is_session_expired_json(resp)

    def _recover_session(self, where):
        """重登。回 True＝重登了，False＝沒有憑證可用。"""
        creds = getattr(self, '_test_credentials', None)
        if not creds:
            return False
        type(self)._session_recovered += 1
        _logger.warning(
            '[session_probe] %s：session 在測試中途失效，重登 %r 後重試一次。'
            '這不是被測路由的缺陷——見 tests/session_probe.py 檔頭'
            '（ormcache 不隨交易回滾）。本類別累計重登 %d 次。',
            where, creds[0], type(self)._session_recovered)
        self.authenticate(*creds)
        return True

    def _url_open_live(self, url, where='', **kw):
        """`url_open`，但 session 中途失效時重登一次再試。

        ☠️ 只重試**一次**。第二次還是被導去登入頁就讓測試失敗——那代表問題
        不是偶發的 session 失效，蓋掉它只會換成更難查的症狀。
        """
        resp = self.url_open(url, **kw)
        if self._looks_session_expired(resp) and self._recover_session(where or url):
            resp = self.url_open(url, **kw)
        return resp

    def _jsonrpc_with_evidence(self, route, params, where=''):
        """打 `type='json'` 路由，失敗時**把證據寫進失敗訊息**。

        與 `make_jsonrpc_request()` 的語意相同（路由回 JSON-RPC error 就讓測試
        失敗、成功就回 `result`），差別只在失敗訊息的內容：

            狀態碼 / Content-Type / **最終 URL**（轉址到 /web/login 會在這裡
            現形）/ 回應內文前 400 字 / Odoo 放在 error.data.debug 的 traceback

        為什麼要自己組 envelope 而不是包在 make_jsonrpc_request 外面：
        後者在回應不是 JSON 時丟的 JSONDecodeError **不帶回應內文**，而失敗
        之後**不能重發**請求（會改變狀態，而且偶發的那一次就錯過了），
        所以證據必須在同一次呼叫裡取得。
        """
        payload = json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 0, 'params': params,
        })
        headers = {'Content-Type': 'application/json'}
        resp = self._url_open_live(
            route, where=where or route, data=payload, headers=headers)
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        tag = ' @%s' % where if where else ''
        if ct != 'application/json':
            self.fail(
                '%s%s 的回應不是 JSON——這**不是**被測路由的邏輯問題。\n'
                '  狀態碼      : %s\n'
                '  Content-Type: %s\n'
                '  最終 URL    : %s   ← 是 /web/login 就代表 session 掉了\n'
                '  重登次數    : %s（重登一次之後還是這樣，就不是偶發）\n'
                '  內文前 400 字: %r'
                % (route, tag, resp.status_code, ct or '(無)', resp.url,
                   type(self)._session_recovered, (resp.text or '')[:400]))
        body = resp.json()
        if not isinstance(body, dict):
            self.fail(
                '%s%s 回的 JSON 不是物件（JSON-RPC 的回應一定是物件）：%r'
                % (route, tag, body))
        if 'error' in body:
            err = body['error'] or {}
            data = err.get('data') or {}
            if 'SessionExpired' in (data.get('name') or ''):
                # 重登一次之後還是過期 → 不是偶發，別把它報成「路由回了錯誤」
                self.fail(
                    '%s%s：重登之後 session 依然過期（累計重登 %d 次）。'
                    '這不是偶發的 ormcache 競態，而是 session 建立本身有問題'
                    '——見 tests/session_probe.py 檔頭。'
                    % (route, tag, type(self)._session_recovered))
            self.fail(
                '%s%s 回了 JSON-RPC error。\n'
                '  message: %s\n'
                '  name   : %s\n'
                '  debug  :\n%s'
                % (route, tag, err.get('message'), data.get('name'),
                   (data.get('debug') or '(Odoo 沒附 traceback)')))
        return body.get('result')
