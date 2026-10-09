"""HttpCase 的 session 健康檢查——共用 mixin。

為什麼需要：這些測試打的是 `auth='user'` 的路由。session 沒建立時 Odoo 不會
回 4xx，而是把請求**轉址到 `/web/login`**，於是回應變成 HTML 200。那時失敗會
出現在「回應不是 JSON」或「KeyError: 'result'」這類斷言上，**看起來像被測的
路由壞了**，其實是登入沒成立。

☠️ 檔名刻意**不**用 `test_` 開頭：`tests/__init__.py` 只 import 有測試類別的
檔案，而這支沒有類別。叫 `test_session_probe.py` 的話，「有類別卻沒 import」
那條檢查就要為它開例外（`test_pill_helpers.py` 已經讓 CI 誤判過一次）。

歷史：2026-10-09 追一則偶發失敗時，這段原本只寫在
`TestControllerSecurityBoundary` 裡。同一天驗證另一件事時，
**`TestTelemetryRoutes` 也偶發了一次**（1 failed + 1 error，隨後連跑三次全綠）
——那個類別沒有這段檢查，所以那一次的原因沒有留下任何證據。抽成共用就是為了
讓下一次自己說出原因。見 docs/qweb_converter_coverage.md §7.9。
"""


class SessionAliveMixin:
    """提供 `_assert_session_alive()`。與 HttpCase 一起繼承。"""

    def _assert_session_alive(self, where):
        resp = self.url_open(
            '/web/session/get_session_info', data='{}',
            headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        self.assertEqual(
            ct, 'application/json',
            'session 在 %s 時不可用（回應 %s / %s）——後面的失敗都是這個造成的，'
            '不是被測路由的問題' % (where, resp.status_code, ct))
