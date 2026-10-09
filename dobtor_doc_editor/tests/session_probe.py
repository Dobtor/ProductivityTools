"""HttpCase 的 session 健康檢查——共用 mixin。

為什麼需要：這些測試打的是 `auth='user'` 的路由。session 沒建立時 Odoo 不會
回 4xx，而是把請求**轉址到 `/web/login`**，於是回應變成 HTML 200。那時失敗會
出現在「回應不是 JSON」或「KeyError: 'result'」這類斷言上，**看起來像被測的
路由壞了**，其實是登入沒成立。

☠️ 檔名刻意**不**用 `test_` 開頭：`tests/__init__.py` 只 import 有測試類別的
檔案，而這支沒有類別。叫 `test_session_probe.py` 的話，「有類別卻沒 import」
那條檢查就要為它開例外（`test_pill_helpers.py` 已經讓 CI 誤判過一次）。

除了 `_assert_session_alive()`（setUp 時的一次性檢查），本 mixin 另提供
`_jsonrpc_with_evidence()`——**偶發失敗發生的當下**把證據留下來。

☠️ 為什麼需要後者：`HttpCase.make_jsonrpc_request()` 在回應不是 JSON 時會丟
`JSONDecodeError`，而那個例外**不帶回應內文**。於是測試報告只看得到
「JSON 解析失敗」，看不出到底是轉址到 /web/login、500 的 HTML 錯誤頁，
還是別的東西——也就是說偶發發生了一次，卻什麼都沒留下。
`TestTelemetryRoutes` 的 error 形狀偶發（2026-10-09，3 次）就是這樣跑掉的：
事後連跑 30 輪全綠，無法重現，而當時沒有任何證據。

歷史：2026-10-09 追一則偶發失敗時，這段原本只寫在
`TestControllerSecurityBoundary` 裡。同一天驗證另一件事時，
**`TestTelemetryRoutes` 也偶發了一次**（1 failed + 1 error，隨後連跑三次全綠）
——那個類別沒有這段檢查，所以那一次的原因沒有留下任何證據。抽成共用就是為了
讓下一次自己說出原因。見 docs/qweb_converter_coverage.md §7.9。
"""


import json


class SessionAliveMixin:
    """提供 session 檢查與帶證據的 JSON-RPC 呼叫。與 HttpCase 一起繼承。"""

    def _assert_session_alive(self, where):
        resp = self.url_open(
            '/web/session/get_session_info', data='{}',
            headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        self.assertEqual(
            ct, 'application/json',
            'session 在 %s 時不可用（回應 %s / %s）——後面的失敗都是這個造成的，'
            '不是被測路由的問題' % (where, resp.status_code, ct))

    def _jsonrpc_with_evidence(self, route, params, where=''):
        """打 `type='json'` 路由，失敗時**把證據寫進失敗訊息**。

        與 `make_jsonrpc_request()` 的語意相同（路由回 JSON-RPC error 就讓測試
        失敗、成功就回 `result`），差別只在失敗訊息的內容：

            狀態碼 / Content-Type / **最終 URL**（轉址到 /web/login 會在這裡
            現形）/ 回應內文前 400 字 / Odoo 放在 error.data.debug 的 traceback

        為什麼要自己組 envelope 而不是包在 make_jsonrpc_request 外面：
        失敗之後**不能重發**請求（會改變狀態，而且偶發的那一次就錯過了），
        所以證據必須在同一次呼叫裡取得。
        """
        payload = json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 0, 'params': params,
        })
        resp = self.url_open(
            route, data=payload, headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        tag = ' @%s' % where if where else ''
        if ct != 'application/json':
            self.fail(
                '%s%s 的回應不是 JSON——這**不是**被測路由的邏輯問題。\n'
                '  狀態碼      : %s\n'
                '  Content-Type: %s\n'
                '  最終 URL    : %s   ← 是 /web/login 就代表 session 掉了\n'
                '  內文前 400 字: %r'
                % (route, tag, resp.status_code, ct or '(無)',
                   resp.url, (resp.text or '')[:400]))
        body = resp.json()
        if 'error' in body:
            err = body['error'] or {}
            data = err.get('data') or {}
            self.fail(
                '%s%s 回了 JSON-RPC error。\n'
                '  message: %s\n'
                '  name   : %s\n'
                '  debug  :\n%s'
                % (route, tag, err.get('message'), data.get('name'),
                   (data.get('debug') or '(Odoo 沒附 traceback)')))
        return body.get('result')
