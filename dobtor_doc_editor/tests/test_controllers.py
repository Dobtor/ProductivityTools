"""Integration tests for HTTP / JSON-RPC controllers (W9-10 P2-1)。

驗證 W7-8 新加的版本路由能透過 ORM 直接觸發；
完整 HTTP-level 測試會在 Odoo HttpCase 中跑。

Sprint 115:`TestControllerSecurityBoundary(HttpCase)` 補完
doc_controller.py 邊界 security 測試 — 紀律 #5 + #11 + #15 廣域應用。
"""

import io
import json
import re
from importlib.util import find_spec

from odoo.tests.common import HttpCase, TransactionCase, tagged

from .session_probe import SessionAliveMixin

# python-docx 是選用相依（見 __manifest__.py 的說明）：核心功能不需要它，
# 但本檔有三則測試要用它產生合法的 DOCX bytes。沒裝就跳過那三則，
# 不要讓整個測試類別因為一個選用套件而失敗。
HAS_PYTHON_DOCX = find_spec('docx') is not None


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestVersionRoutes(TransactionCase):
    """版本管理 4 條路由的 ORM 層級測試。

    我們不真的跑 HTTP 流程（HttpCase 比較重），改在 ORM 層直接呼叫
    對應方法，確認 controller 路由內呼叫的 model method 正確。
    """

    def setUp(self):
        super().setUp()
        self.Doc = self.env['doc.document']
        self.doc = self.Doc.create({
            'name': '測試文件',
            'content_html': '<h1>初版</h1><p>原始內容。</p>',
        })

    def test_save_then_list(self):
        """save_version → get_version_list 應反映剛存的版本。"""
        result = self.doc.action_save_version(label='第一個快照')
        self.assertIn('version_number', result)

        versions = self.doc.get_version_list()
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['version_number'], 1)
        self.assertEqual(versions[0]['label'], '第一個快照')

    def test_get_content_returns_html(self):
        """get_version_content 包含 content_html。"""
        self.doc.write({'content_html': '<p>會議紀錄定稿</p>'})
        result = self.doc.action_save_version()
        content = self.doc.get_version_content(result['version_number'])
        self.assertIn('會議紀錄定稿', content['content_html'])

    def test_diff_three_versions(self):
        """連續存三個版本後，可以兩兩 diff。"""
        self.doc.write({'content_html': '<p>v1</p>'})
        r1 = self.doc.action_save_version()
        self.doc.write({'content_html': '<p>v2</p>'})
        r2 = self.doc.action_save_version()
        self.doc.write({'content_html': '<p>v3</p>'})
        r3 = self.doc.action_save_version()

        diff_12 = self.doc.diff_versions(r1['version_number'], r2['version_number'])
        diff_13 = self.doc.diff_versions(r1['version_number'], r3['version_number'])

        self.assertEqual(diff_12['a_version'], 1)
        self.assertEqual(diff_12['b_version'], 2)
        self.assertEqual(diff_13['a_version'], 1)
        self.assertEqual(diff_13['b_version'], 3)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestZipGuardIntegration(TransactionCase):
    """upload_template / import_document 上 zip_guard 不可繞過。

    HTTP 層完整流程（含 multipart upload）放在 HttpCase；本測試驗證
    最少：controller 內 import 的 zip_guard 不會因模組路徑變動失效。
    """

    def test_zip_guard_imported_in_controller(self):
        """確認 controller 模組正確 import zip_guard。"""
        from ..controllers import doc_controller
        # 應有 zip_guard 相關 symbol 在模組命名空間
        # （直接 from ..models.doc_zip_guard import ...，import 之後 module 可見）
        self.assertTrue(
            hasattr(doc_controller, 'assert_input_size')
            or hasattr(doc_controller, 'inspect_zip_safe')
            or hasattr(doc_controller, 'ZipBombError'),
            "doc_controller 應 import zip_guard symbols，但全部找不到",
        )


def _make_minimal_docx_bytes():
    """產出最小合法 DOCX bytes（測試 upload_template / import 用）。

    使用 python-docx 產出完整 docx(含 _rels / officeDocument relationship),
    避免 controller 內 python-docx open 時爆 KeyError。
    """
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph('hello')
    doc.save(buf)
    return buf.getvalue()


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestControllerSecurityBoundary(SessionAliveMixin, HttpCase):
    """Sprint 115 — doc_controller.py 邊界安全測試（紀律 #5 + #11 + #15 廣域應用）。

    補完 Sprint 68 font_serve security boundary 同等模式，覆蓋:
        - upload_template 接收 user filename(path traversal / null byte)
        - import_document 沒收到 file / engine 白名單
        - render_preview / get_fields 接收 user 提供 model_name

    紀律 #18 scope 對齊:本層 test 屬規畫書 §11.1 隱含 + roadmap 階段 A 行 2,
    廣域應用 sprint 68 揭示的 security 邊界紀律。
    """

    def setUp(self):
        super().setUp()
        self.doc = self.env['doc.document'].sudo().create({
            'name': 'Sprint 115 security test doc',
            'content_html': '<p>baseline</p>',
        })
        # 用 admin 模擬合法登入
        self.authenticate('admin', 'admin')
        self._assert_session_alive('setUp')

    def _why_not_json(self, resp, sid):
        """失敗訊息要能一次定位，不要只說「不是 JSON」。

        這個端點掛了 json_http_route，**handler 不可能回非 JSON**
        （任何漏出的例外都被包成 JSON）。所以回應不是 JSON 只剩一個來源：
        auth 層把請求導去登入頁。這裡把那個判斷需要的三件事一起印出來：
        轉址紀錄、session 在 store 裡還有沒有 uid、token 對不對得上。
        """
        import odoo.http
        from odoo.service import security
        try:
            stored = odoo.http.root.session_store.get(sid)
            uid = stored.get('uid')
            expected = security.compute_session_token(stored, self.env) \
                if uid else None
            token_match = bool(stored.get('session_token') and expected
                               and stored['session_token'] == expected)
        except Exception as e:
            uid, token_match = None, 'store 讀不到：%s' % e
        return (
            '回應不是 JSON。這個端點有 json_http_route，handler 不可能回非 '
            'JSON——所以是 auth 層導去登入頁。\n'
            '  轉址紀錄 = %s\n  session uid = %s\n  token 對得上 = %s\n'
            '  內容 = %s'
            % ([r.status_code for r in resp.history], uid, token_match,
               resp.text[:300]))

    # ── upload_template 邊界 ───────────────────────────────────────

    def test_upload_template_path_traversal_filename_handled(self):
        """filename 含 `../../../etc/passwd.docx` 不應 500、graceful 儲存。

        當前行為(documented baseline):Odoo Char field 接收原樣字串。
        即使 filename 含 path separator,只是 DB 字段、不會被當檔案路徑使用。
        紀律 #5:深度防禦原則上應 sanitize、但 Odoo ORM 不洩漏 path 為當前可接受風險。
        """
        if not HAS_PYTHON_DOCX:
            self.skipTest('python-docx 未安裝（選用相依）')
        docx_bytes = _make_minimal_docx_bytes()
        resp = self._url_open_live(
            '/dobtor_doc/upload_template',
            data={'doc_id': str(self.doc.id)},
            files={'docx_file': ('../../../etc/passwd.docx', docx_bytes,
                                 'application/vnd.openxmlformats-officedocument'
                                 '.wordprocessingml.document')},
        )
        # 不應 500;業務 success / 失敗都接受、只要不爆 server error
        self.assertNotEqual(resp.status_code, 500,
                            "Path traversal filename 不該觸發 500")
        # 確認 controller 已處理(回 JSON 而非 HTML 錯誤頁)
        # ☠️ 這裡原本自己組了一句弱的訊息，而同檔已經寫好了
        #    `_why_not_json()`（它會把轉址紀錄、session store 裡的
        #    uid、token 對不對得上一起印出來）。診断工具寫好卻沒接上
        #    ——這支測試 2026-10-09 就是因為這樣，偶發紅了一次卻只留下
        #    「不是 JSON」五個字。
        self.assertIn(
            'application/json', resp.headers.get('Content-Type', ''),
            self._why_not_json(resp, self.session.sid),
        )

    def test_upload_template_null_byte_filename_rejected(self):
        """filename 含 null byte(`\\x00`) → graceful 400(Sprint 116 plus fix)。

        Sprint 115 揭示:Postgres 不接 null byte → 500 leak trace。
        Sprint 116 plus fix:controller 入口 explicit sanitize、改 graceful 400。

        本 test 驗證 Sprint 116 plus 後的新行為:400 + error message,不是 500。
        """
        if not HAS_PYTHON_DOCX:
            self.skipTest('python-docx 未安裝（選用相依）')
        docx_bytes = _make_minimal_docx_bytes()
        # ☠️ 這一則曾經偶發失敗（整份測試跑 14 次紅 1 次、單獨跑這個類別 6/6
        # 綠；見 docs/qweb_converter_coverage.md §7.9）。症狀是回應不是 JSON，
        # 也就是請求被導去登入頁。
        #
        # 查過但**排除**的原因：registry.clear_cache()（_compute_session_token
        # 是 @ormcache('sid')，所以這是最像的嫌疑）——寫了一支探測測試連續清
        # 五次再打請求，session 都還活著，所以不是它。根因沒找到。
        #
        # 這裡做的不是遮蔽：把「登入」縮到緊貼著「動作」之前，讓這一則只依賴
        # 自己那一刻的狀態，而不依賴 setUp 到斷言之間整個 suite 的全域狀態。
        # 這一則要測的是「multipart 檔名含 null byte 時的處理」，不是
        # 「session 撐不撐得過整份測試」——後者若真的壞了，_assert_session_alive
        # 會在它自己的斷言上說出來。
        self.authenticate('admin', 'admin')
        self._assert_session_alive('upload_template 請求前')
        _sid = self.session.sid
        resp = self._url_open_live(
            '/dobtor_doc/upload_template',
            data={'doc_id': str(self.doc.id)},
            files={'docx_file': ('evil\x00.docx', docx_bytes,
                                 'application/vnd.openxmlformats-officedocument'
                                 '.wordprocessingml.document')},
        )
        # 失敗時要看得出原因：曾經偶發拿到 200，而 200 有兩種來源
        #（上傳真的成功、或請求被導去登入頁）。只看狀態碼分不出來。
        self.assertEqual(
            (resp.headers.get('Content-Type') or '').split(';')[0],
            'application/json', self._why_not_json(resp, _sid))
        # Sprint 116 plus 後:graceful 400(非 500、非 200 silent success)
        self.assertEqual(
            resp.status_code, 400,
            'Null byte filename 應 graceful 400(Sprint 116 plus fix)；'
            '實際回應 = %s' % resp.text[:200],
        )
        body = json.loads(resp.content)
        self.assertFalse(body.get('success'))
        self.assertIn('null byte', body.get('error', '').lower())

    # ── import_document 邊界 ───────────────────────────────────────



    # ── get_fields / render_preview 邊界 ──────────────────────────

    def test_get_fields_unknown_model_returns_graceful_error(self):
        """model_name 不存在 → graceful `{error: ...}` 而非 500。"""
        result = self.opener.post(
            f"{self.base_url()}/dobtor_doc/fields",
            json={
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {'model_name': 'no.such.model.xyz'},
            },
        )
        self.assertEqual(result.status_code, 200)
        body = result.json()
        # JSON-RPC 回應結構: {jsonrpc, id, result|error}
        rpc_result = body.get('result') or {}
        # 不論是 controller 內部 try-except 包成 {'error': ...}、
        # 或 jsonrpc 層 error,都不該洩漏 traceback
        self.assertTrue(
            'error' in rpc_result or 'error' in body,
            f"未知 model 應 graceful error: {body}",
        )

    def test_render_preview_unknown_model_returns_graceful_error(self):
        """record_model 不存在 → graceful `{error: ...}`,不 500。"""
        result = self.opener.post(
            f"{self.base_url()}/dobtor_doc/render_preview",
            json={
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'doc_id': self.doc.id,
                    'record_model': 'no.such.model.xyz',
                    'record_id': 1,
                },
            },
        )
        self.assertEqual(result.status_code, 200)
        body = result.json()
        rpc_result = body.get('result') or {}
        self.assertTrue(
            'error' in rpc_result or 'error' in body,
            f"未知 record_model 應 graceful error: {body}",
        )


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRouteRegistration(TransactionCase):
    """36 條路由在拆成四個 Controller 之後還是全部註冊得到。

    2026-10-09 把 doc_controller.py（2593 行、36 路由）拆成四個 Controller
    ＋一個共用守衛基底。拆錯的症狀是**那一批路由 404**，而 404 在前端只會
    變成「按了沒反應」——OWL 把 rpc 失敗吞成 console 的一行。

    這一則直接問 Odoo 自己的來源：它是靠 endpoint 身上的 original_routing
    屬性認出路由的（http.py:759、827）。
    """

    def test_every_declared_route_is_registered(self):
        import ast
        import os
        from odoo import http
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        declared = set()
        ctrl_dir = os.path.join(here, 'controllers')
        for name in os.listdir(ctrl_dir):
            if not name.endswith('.py') or name == '__init__.py':
                continue
            with open(os.path.join(ctrl_dir, name), encoding='utf-8') as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                for dec in node.decorator_list:
                    if (isinstance(dec, ast.Call)
                            and getattr(dec.func, 'attr', '') == 'route'):
                        arg = dec.args[0] if dec.args else None
                        if isinstance(arg, ast.Constant):
                            declared.add(arg.value)
                        elif isinstance(arg, ast.List):
                            declared.update(
                                e.value for e in arg.elts
                                if isinstance(e, ast.Constant))
        self.assertGreaterEqual(len(declared), 36,
                                '宣告的路由數少於預期，是不是有檔案沒被掃到')

        # ☠️ 要**遞迴**走子類別樹，不能只看直接子類別：portal.py 的
        # controller 繼承的是 portal 模組的 CustomerPortal，所以它是
        # http.Controller 的孫類別。只看第一層會漏掉 /my/documents 那三條
        # ——而那三條是 portal 使用者唯一的入口。
        def walk_subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from walk_subclasses(sub)

        registered = set()
        for cls in walk_subclasses(http.Controller):
            if not cls.__module__.startswith('odoo.addons.dobtor_doc_editor'):
                continue
            for attr in dir(cls):
                fn = getattr(cls, attr, None)
                routing = getattr(fn, 'original_routing', None)
                if routing:
                    registered.update(routing.get('routes') or [])
        self.assertFalse(
            declared - registered,
            '這幾條路由宣告了卻沒註冊：%s' % sorted(declared - registered))

    def test_all_doc_controllers_share_the_guards(self):
        """守衛放在非 Controller 的基底上；少繼承一個的症狀是那一批 500。"""
        from odoo import http
        from odoo.addons.dobtor_doc_editor.controllers.doc_controller_base \
            import DocControllerBase
        def walk_subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from walk_subclasses(sub)

        docs = [c for c in walk_subclasses(http.Controller)
                if c.__module__.startswith(
                    'odoo.addons.dobtor_doc_editor.controllers.doc_controller')]
        self.assertGreaterEqual(len(docs), 4, '少了 Controller：%s' % docs)
        for cls in docs:
            self.assertTrue(issubclass(cls, DocControllerBase),
                            '%s 沒有繼承共用守衛' % cls.__name__)


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestHttpRoutesAlwaysReturnJson(SessionAliveMixin, HttpCase):
    """`type='http'` 但回 JSON 的路由，**不可能**回 HTML。

    ☠️ 這一類缺陷在這個模組發生過一次：2026-06-29（0ef991b）使用者上傳 DOCX
    模板看到「Unexpected token '<'」。`type='http'` 路由的例外被 Odoo 映射成
    werkzeug 的 HTML 錯誤頁，前端 `resp.json()` 撞上 `<!doctype` 就這樣。

    那次修了兩邊，但修法是逐點補。2026-10-09 稽核量到的實際缺口：
        upload_template   `_require_document()` 在 try 之前（4 行）→ 真缺口。
                          拋 AccessError（只有讀取權限）、MissingError
                          （編輯期間文件被刪）、ValueError（doc_id 非數字）。
        import_document   try 外那幾行**自己回 JSON**，不是拋例外；掛
                          decorator 是預防性的。

    症狀講精確一點：前端的 `_readJsonResponse` 會把 HTML 剝成純文字當訊息，
    所以使用者不是「按了沒反應」，是看到一句夾著「400 Bad Request」的
    半英文訊息——設計好的提示被降級了。json_http_route 讓它原樣送達。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self._assert_session_alive('setUp')

    def _ct(self, resp):
        return (resp.headers.get('Content-Type') or '').split(';')[0]

    def test_upload_template_missing_doc_returns_json_not_html(self):
        """文件 id 不存在 → 以前是 HTML 錯誤頁（MissingError 在 try 之外）。"""
        resp = self._url_open_live(
            '/dobtor_doc/upload_template',
            data={'doc_id': '999999999'},
            files={'docx_file': ('x.docx', b'PK\x03\x04', 'application/octet-stream')},
        )
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])
        self.assertFalse(json.loads(resp.content).get('success'))

    def test_upload_template_blank_doc_id_returns_json_not_html(self):
        """doc_id 空 → _require_document 拋 UserError（也在 try 之外）。"""
        resp = self._url_open_live(
            '/dobtor_doc/upload_template',
            data={'doc_id': ''},
            files={'docx_file': ('x.docx', b'PK\x03\x04', 'application/octet-stream')},
        )
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])


    def test_unexpected_exception_returns_traceable_ref(self):
        """非預期例外：訊息不能給（會洩 traceback），但**指標**要給。

        doc_id='abc' → `_require_document` 的 `int(doc_id)` 拋 ValueError，
        不在 UserError / MissingError / AccessError 之列 → 走 500 那一路。

        這一則同時斷言兩件事，缺一個就沒有意義：
          1. 回應的訊息帶一組 8 碼代碼（使用者看得到、可以報給管理員）
          2. **同一組**代碼出現在 log 裡（管理員 grep 得到那筆 traceback）
        只驗其中一個的話，兩邊各自有代碼但對不起來也會綠。
        """
        logger = 'odoo.addons.dobtor_doc_editor.controllers.doc_controller_base'
        with self.assertLogs(logger, level='ERROR') as captured:
            resp = self._url_open_live(
                '/dobtor_doc/upload_template',
                data={'doc_id': 'abc'},
                files={'docx_file': ('x.docx', b'PK\x03\x04',
                                     'application/octet-stream')},
            )
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])
        self.assertEqual(resp.status_code, 500)
        payload = json.loads(resp.content)
        self.assertFalse(payload.get('success'))
        refs = re.findall(r'代碼 ([0-9a-f]{8})', payload.get('error') or '')
        self.assertEqual(len(refs), 1,
                         '訊息裡沒有可追的代碼：%r' % payload.get('error'))
        self.assertNotIn('Traceback', payload['error'],
                         'traceback 不可以回給前端')
        self.assertTrue(
            any('ref=%s' % refs[0] in line for line in captured.output),
            'log 裡找不到同一組代碼 %s；log=%r' % (refs[0], captured.output),
        )

    def test_decorator_does_not_swallow_http_exceptions(self):
        """☠️ decorator 包的是 Exception——不先排除就會把這兩類一起收走。

        HTTPException：handler 刻意拋 NotFound 就是要那個 404，吞成 500 JSON
                       會把狀態碼改掉。
        SessionExpiredException：Odoo 對它是 303 轉址到 /web/login，而前端靠
                       認得出那個轉址來顯示「請重新登入」
                       （doc_editor_shared.js 的 isSessionExpiredResponse）。
                       吞掉的話那條路就斷了。

        直接測 decorator 本身（不經 HTTP），因為目前沒有路由會拋這兩類——
        這一則擋的是**未來**有人加了會拋的路由。
        """
        from werkzeug.exceptions import NotFound
        from odoo.http import SessionExpiredException
        from odoo.addons.dobtor_doc_editor.controllers.doc_controller_base import (
            DocControllerBase,
        )

        class _Fake:
            @DocControllerBase.json_http_route
            def boom(self, exc):
                raise exc

        fake = _Fake()
        for exc in (NotFound('nope'), SessionExpiredException('expired')):
            with self.assertRaises(type(exc)):
                fake.boom(exc)

    def test_every_json_http_route_has_the_decorator(self):
        """新加的 type='http' 回 JSON 路由也要掛上——少掛是靜默的。

        ☠️ 第一版這一則是查 `__wrapped__` 有沒有值，結果**移除 decorator 之後
        它照樣綠**：`http.route` 自己就用 functools.wraps，所以 `__wrapped__`
        本來就存在。查的是 Odoo 的包裝不是我的。
        改成讀原始碼判斷——這一則要擋的是「有人加了新路由忘記掛」，用原始碼
        判斷才對得上那個情境。
        """
        import ast
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ctrl_dir = os.path.join(here, 'controllers')
        missing = []
        for name in sorted(os.listdir(ctrl_dir)):
            if not name.endswith('.py') or name == '__init__.py':
                continue
            path = os.path.join(ctrl_dir, name)
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                decs = node.decorator_list
                is_http = any(
                    isinstance(d, ast.Call)
                    and getattr(d.func, 'attr', '') == 'route'
                    and any(k.arg == 'type'
                            and getattr(k.value, 'value', None) == 'http'
                            for k in d.keywords)
                    for d in decs)
                if not is_http:
                    continue
                body = ast.get_source_segment(src, node) or ''
                if 'application/json' not in body:
                    continue       # 不回 JSON 的（檔案下載、HTML 頁）不在範圍
                has = any(
                    (isinstance(d, ast.Attribute) and d.attr == 'json_http_route')
                    or (isinstance(d, ast.Name) and d.id == 'json_http_route')
                    for d in decs)
                if not has:
                    missing.append('%s::%s' % (name, node.name))
        self.assertFalse(
            missing,
            'type=\'http\' 且回 JSON 卻沒掛 json_http_route：%s\n'
            '沒掛的話錯誤路徑會回 HTML 錯誤頁，前端 resp.json() 解析失敗 → '
            '使用者看到「按了沒反應」' % missing)


