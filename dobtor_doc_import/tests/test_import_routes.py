"""匯入路由的測試。

拆模組步驟 3（2026-10-09）從 dobtor_doc_editor 的 tests/test_controllers.py
切出來——那三個類別原本是混的（upload_template 與 import 同一組），
按「打的是哪一條路由」切。

共用的 session 健康檢查沿用核心的 mixin，不複製一份：
`from odoo.addons.dobtor_doc_editor.tests.session_probe import SessionAliveMixin`
——☠️ 核心的 tests/ 是一個 Python 套件（有 __init__.py），所以跨模組 import
得到；但這也意味著核心那支檔案是**公開介面**，改它要想到這裡。
"""
import io
import json
from importlib.util import find_spec

from odoo.tests.common import HttpCase, tagged

from odoo.addons.dobtor_doc_editor.tests.session_probe import SessionAliveMixin

# 選用套件：缺 python-docx 時匯入會走 LibreOffice，那幾則斷言的前提不成立。
# ☠️ 原本是核心 tests/test_controllers.py 的模組層常數，搬測試時漏帶，
#    結果 NameError 被報成「測試錯誤」而不是「少一個常數」。
HAS_PYTHON_DOCX = find_spec('docx') is not None


def _make_minimal_docx_bytes():
    """產出最小合法 DOCX bytes。

    ☠️ 與 HAS_PYTHON_DOCX 一樣原本是核心 tests/test_controllers.py 的模組層
    helper，搬測試時漏帶。症狀是 NameError 被報成「測試錯誤」——看起來像被測的
    路由壞了，其實是測試檔少了一個函式。
    用 python-docx 產完整 docx（含 _rels / officeDocument relationship），
    不然 controller 內 python-docx open 時會 KeyError。
    """
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph('hello')
    doc.save(buf)
    return buf.getvalue()


@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestImportRoutes(SessionAliveMixin, HttpCase):
    """`/dobtor_doc/import` 的入口行為（沒檔案 / 壞副檔名 / 壞 engine）。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self._assert_session_alive('setUp')

    def _ct(self, resp):
        return (resp.headers.get('Content-Type') or '').split(';')[0]

    def test_import_document_no_file_returns_400_with_message(self):
        """POST /dobtor_doc/import 沒附 file → **400** ＋ 可讀訊息。

        ☠️ 2026-10-09 改過：原本這一則斷言 `status_code == 200`。那是因為錯誤
        路徑走的是本地的 `_json_resp`（不帶 status），而同一條路由掛的
        `json_http_route` 給的是 400／500——**同一條路由兩套錯誤慣例**。
        現在錯誤一律 `raise UserError` → decorator 統一成 400。
        """
        resp = self.opener.post(
            f"{self.base_url()}/dobtor_doc/import",
            data={'_': '1'},  # 必帶任意 form data 才會 POST（不影響邏輯）
        )
        self.assertEqual(resp.status_code, 400,
                         '錯誤路徑應該回 400，不是 %s' % resp.status_code)
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])
        body = resp.json()
        self.assertFalse(body.get('success'))
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
        resp = self._url_open_live(
            '/dobtor_doc/import',
            data={'engine': '<script>alert(1)</script>'},
            files={'file': ('test.docx', docx_bytes,
                            'application/vnd.openxmlformats-officedocument'
                            '.wordprocessingml.document')},
        )
        # 不該 500、不該洩漏 traceback。LO 跑通 → 200；LO 轉不動 → 400。
        self.assertIn(resp.status_code, (200, 400),
                      'engine 注入導致 %s' % resp.status_code)
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])
        body = json.loads(resp.content)
        self.assertTrue('error' in body or 'html' in body or 'elements' in body,
                        f"Response 結構不對: {body}")
        # ☠️ 不可以把 LibreOffice 的 stderr 原樣送到前端（2026-10-09 修的）。
        if 'error' in body:
            for leak in ('soffice', 'Traceback', '/tmp/', '/usr/lib'):
                self.assertNotIn(leak, body['error'],
                                 '錯誤訊息洩漏了內部細節：%s' % body['error'])


    def test_import_document_bad_extension_returns_json_not_html(self):
        resp = self.opener.post(
            '%s/dobtor_doc/import' % self.base_url(),
            files={'file': ('x.exe', b'MZ', 'application/octet-stream')},
        )
        self.assertEqual(self._ct(resp), 'application/json',
                         '回了非 JSON：%s' % resp.text[:200])




@tagged('post_install', '-at_install', 'dobtor_doc_import')
class TestTsEngineChannel(SessionAliveMixin, HttpCase):
    """`/dobtor_doc/import?engine=ts` 真的回得出 IElement[]。

    ☠️ 這組測試要擋的是一個**存在很久的空洞**：這條通道依賴
    `tools/dist/parse_docx_cli.cjs`，而那個產物原本被 `.gitignore` 的 `dist/`
    排除、**從來沒進過 git**。部署端的容器只有 node、沒有 npm，不可能在機器上
    build，所以 `_ts_parse_docx_to_elements()` 永遠找不到 CLI、記一行 warning
    回 `None`——**這條通道在任何部署上都沒有真的運作過**，而且因為它優雅降級，
    沒有任何東西會報錯。

    2026-10-09 取回 TS 子系統時補上：`.gitignore` 加 `!tools/dist/` 例外、產物
    進版控、再加這組測試。沒有這組測試的話，下一次 rebase/clean 又把產物弄掉
    時，一樣沒人會知道（見 ADR-032）。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self._assert_session_alive('setUp')

    def _fixture_bytes(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root = os.path.join(here, 'tests', 'fixtures', '01_simple')
        names = sorted(f for f in os.listdir(root) if f.endswith('.docx'))
        self.assertTrue(names, 'tests/fixtures/01_simple 下沒有 .docx')
        with open(os.path.join(root, names[0]), 'rb') as fp:
            return names[0], fp.read()

    def test_cli_bundle_is_in_the_repo(self):
        """產物必須在版控裡——這是整條通道唯一的部署前提。"""
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cli = os.path.join(here, 'tools', 'dist', 'parse_docx_cli.cjs')
        self.assertTrue(
            os.path.isfile(cli),
            'tools/dist/parse_docx_cli.cjs 不存在——engine=ts 會靜默降級回 None。'
            '重建：npm install && npm run build:cli')
        self.assertGreater(os.path.getsize(cli), 100_000,
                           'CLI 產物太小，可能不是完整 bundle')

    def test_engine_ts_returns_elements(self):
        """端到端：送 engine=ts，要拿到 elements 陣列。"""
        import shutil
        if not shutil.which('node'):
            self.skipTest('容器內沒有 node——engine=ts 的執行期前提')
        name, blob = self._fixture_bytes()
        resp = self.opener.post(
            '%s/dobtor_doc/import' % self.base_url(),
            data={'engine': 'ts'},
            files={'file': (name, blob,
                            'application/vnd.openxmlformats-officedocument'
                            '.wordprocessingml.document')},
        )
        self.assertEqual(
            (resp.headers.get('Content-Type') or '').split(';')[0],
            'application/json', '回了非 JSON：%s' % resp.text[:200])
        payload = json.loads(resp.content)
        self.assertNotIn('error', payload, payload.get('error'))
        self.assertIsInstance(
            payload.get('elements'), list,
            'engine=ts 沒有回 elements——CLI 沒 build 或執行失敗。payload=%s'
            % {k: (v if k != 'html' else '<html %d 字>' % len(v or ''))
               for k, v in payload.items()})
        self.assertGreater(len(payload['elements']), 0, 'elements 是空陣列')

    def test_engine_both_returns_html_and_elements_with_audit(self):
        """engine=both：兩條都跑，而且帶比對用的 audit。"""
        import shutil
        if not shutil.which('node') or not shutil.which('soffice'):
            self.skipTest('engine=both 需要 node 與 LibreOffice 都在')
        name, blob = self._fixture_bytes()
        resp = self.opener.post(
            '%s/dobtor_doc/import' % self.base_url(),
            data={'engine': 'both'},
            files={'file': (name, blob, 'application/octet-stream')},
        )
        payload = json.loads(resp.content)
        self.assertEqual(payload.get('engine'), 'both')
        self.assertIn('audit', payload, 'engine=both 要帶 audit')
        self.assertIn('ts_element_count', payload['audit'],
                      'audit 沒有 TS 的元素數——TS 那條沒跑成功')


@tagged('post_install', '-at_install', 'dobtor_doc_import', 'security')
class TestHarnessRoutesRequireManager(SessionAliveMixin, HttpCase):
    """視覺回歸 harness 的兩條路由只開放給文件管理者。

    ☠️ 它們會讀 `tests/fixtures/` 底下的 .docx——那些是**真實的台灣企業／政府
    文件樣本**。原本只有 `auth='user'`，也就是任何登入者都打得到；在已安裝的
    production 上等於把模組隨附的樣本文件開放給全體內部使用者。

    路徑防護（normpath + startswith + 只收 .docx）擋的是 traversal；
    這一組擋的是另一件事：**誰可以看**。
    """

    def setUp(self):
        super().setUp()
        self.plain = self.env['res.users'].create({
            'name': '普通內部使用者',
            'login': 'harness_plain_user',
            'password': 'harness_plain_user',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    def test_plain_user_cannot_reach_test_data(self):
        """只有 base.group_user 的人打 test_data → 不可以拿到 elements。"""
        from odoo.tests.common import JsonRpcException
        self.authenticate('harness_plain_user', 'harness_plain_user')
        self._assert_session_alive('以普通使用者登入後')
        # ☠️ `type='json'` 的路由拋 AccessError 時，make_jsonrpc_request 會丟
        #    JsonRpcException 而**不是**回傳帶 error 的 dict。第一版我寫成
        #    「斷言回應裡沒有 elements」，結果測試以 ERROR 收場——守衛其實是
        #    生效的，是斷言的形狀不對。
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request(
                '/dobtor_doc_editor/test_data', {'fixture': '01_simple/x.docx'})

    def test_plain_user_cannot_reach_test_render(self):
        """同上，HTML 那一條。"""
        self.authenticate('harness_plain_user', 'harness_plain_user')
        resp = self._url_open_live('/dobtor_doc_editor/test?fixture=01_simple/x.docx')
        self.assertNotEqual(
            resp.status_code, 200,
            '普通使用者成功渲染了 fixture 頁面（status 200）')

    def test_manager_can_still_reach_it(self):
        """收緊不可以把 harness 弄壞——它都是以 admin（doc manager）跑的。"""
        self.authenticate('admin', 'admin')
        self._assert_session_alive('以 admin 登入後')
        result = self.make_jsonrpc_request(
            '/dobtor_doc_editor/test_data', {'fixture': 'does/not/exist.docx'})
        # 管理者要能「通過守衛」——會停在「fixture not found」而不是權限錯誤。
        self.assertIn('error', result)
        self.assertIn('fixture not found', result['error'],
                      '管理者被權限擋住了：%s' % result.get('error'))
