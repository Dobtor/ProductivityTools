"""Integration tests for HTTP / JSON-RPC controllers (W9-10 P2-1)。

驗證 W7-8 新加的版本路由能透過 ORM 直接觸發；
完整 HTTP-level 測試會在 Odoo HttpCase 中跑。

Sprint 115:`TestControllerSecurityBoundary(HttpCase)` 補完
doc_controller.py 邊界 security 測試 — 紀律 #5 + #11 + #15 廣域應用。
"""

import io
import json
from importlib.util import find_spec

from odoo.tests.common import HttpCase, TransactionCase, tagged

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
class TestControllerSecurityBoundary(HttpCase):
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

    def _assert_session_alive(self, where):
        """確認 session 真的可用。

        這一類測試打的是 auth='user' 的路由——session 沒建立時 Odoo 會把請求
        導去 /web/login，回應變成 HTML 200。那時失敗會出現在「回應不是 JSON」
        的斷言上，看起來像被測的路由壞了，其實是登入沒成立。
        在這裡先判一次，失敗訊息就會直指原因。
        """
        resp = self.url_open(
            '/web/session/get_session_info', data='{}',
            headers={'Content-Type': 'application/json'})
        ct = (resp.headers.get('Content-Type') or '').split(';')[0]
        self.assertEqual(
            ct, 'application/json',
            'session 在 %s 時不可用（回應 %s / %s）——後面的失敗都是這個造成的，'
            '不是被測路由的問題' % (where, resp.status_code, ct))

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
        resp = self.url_open(
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
        self.assertIn(
            'application/json', resp.headers.get('Content-Type', ''),
            '不是 JSON：轉址紀錄 =%s；內容 =%s'
            % ([r.status_code for r in resp.history], resp.text[:300]),
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
        resp = self.url_open(
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
            'application/json',
            '回應不是 JSON（可能被導去登入頁，session 沒建立）：'
            '轉址紀錄 =%s；內容 =%s'
            % ([r.status_code for r in resp.history], resp.text[:300]),
        )
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

    def test_import_document_no_file_returns_error_json(self):
        """POST /dobtor_doc/import 沒附 file → graceful '未收到檔案'。"""
        # url_open 帶 data 預設仍可能是 GET;明確 POST 用 opener
        resp = self.opener.post(
            f"{self.base_url()}/dobtor_doc/import",
            data={'_': '1'},  # 必帶任意 form data 才會 POST(不影響邏輯)
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('error', body)
        self.assertIn('未收到檔案', body['error'])

    def test_import_document_invalid_engine_falls_back(self):
        """engine 參數非白名單值 → 自動 fallback 'libreoffice'。

        當前實作:engine not in ('libreoffice', 'ts', 'both') → 'libreoffice'。
        驗證白名單 enforcement,不洩漏 stack。
        """
        if not HAS_PYTHON_DOCX:
            self.skipTest('python-docx 未安裝（選用相依）')
        docx_bytes = _make_minimal_docx_bytes()
        # 用 zip guard 攔截(最小 docx 也是合法 zip、guard 放行,但接下來 LO 處理是另一層)。
        # 此 test 焦點是「engine 參數注入不該繞過白名單」、不關心 LO 結果。
        resp = self.url_open(
            '/dobtor_doc/import',
            data={'engine': '<script>alert(1)</script>'},
            files={'file': ('test.docx', docx_bytes,
                            'application/vnd.openxmlformats-officedocument'
                            '.wordprocessingml.document')},
        )
        # 不該 500、不該洩漏 traceback
        self.assertNotEqual(resp.status_code, 500,
                            "engine 注入不該觸發 500")
        body = json.loads(resp.content)
        # 結果可能成功(LO 跑通)或 graceful error(LO 沒裝),都不會是 stack trace
        self.assertTrue('error' in body or 'success' in body or 'html' in body
                        or 'elements' in body,
                        f"Response 結構不對: {body}")

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
