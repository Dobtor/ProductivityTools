# -*- coding: utf-8 -*-
r"""全路由煙霧測試——稽核尺 3（2026-10-09）。

☠️ 量出來的缺口：核心 36 條路由裡，**22 條完全沒有任何驗證**。

怎麼量的（不是推論）：
  1. AST 列出所有 `@http.route` 的路徑
  2. 比對 `tests/` 底下有沒有提到那條路徑或那個方法名
  3. **跑一次 tour，從 werkzeug 的存取日誌看它實際打到哪些路由**

第 3 步是關鍵。tour 有 66 個 trigger、616 行，看起來「前端都走過了」，
實際只打到 5 條：

    telemetry/metric（6 次）、template_fields/load、save、load、fields

所以「有出貨 JS 在呼叫它」不等於「有東西驗過它」。沒有驗證的那 22 條包含
`/dobtor_doc/export`（文件匯出）、4 條版本路由、5 條 i18n 路由**全部**。

### 這一支驗什麼、不驗什麼

**驗**：每條路由都還活著，而且壞掉的時候**壞得像個 JSON API**
——不是 500、不是 HTML 錯誤頁。這擋的是最大的那一類：重構之後某條路由
ImportError / AttributeError，而沒有任何東西會紅。
（這個模組踩過：批次精靈在迴圈裡 import 已搬走的模組，ImportError 被
`except` 吞掉 → 建出 0 份文件卻回報成功。）

**不驗**：業務邏輯。每條路由的正確行為要各自寫測試，這支只是地板。
把地板跟天花板混為一談會給人虛假的安全感——所以這段話寫在這裡。

### 為什麼要有 `_UNVERIFIED` 清單

它是**分母**。新增一條路由而沒有為它寫行為測試時，這份清單會因為
`test_route_inventory_is_complete` 而紅——逼人明確決定「要補測試」或
「加進清單並寫明為什麼現在不補」。沒有分母的待辦等於沒有待辦。
"""
import ast
import os

from odoo.tests.common import HttpCase, TransactionCase, tagged

from .session_probe import SessionAliveMixin

CONTROLLERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'controllers')


def _declared_routes():
    """AST 列出 (路徑, 方法名, type, auth)。☠️ 不能用 grep：同一類誤判在本模組
    出現過三次，最後一次把 docstring 裡的文字也數進去了。"""
    out = []
    for name in sorted(os.listdir(CONTROLLERS_DIR)):
        if not name.endswith('.py') or name == '__init__.py':
            continue
        with open(os.path.join(CONTROLLERS_DIR, name), encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if (getattr(dec.func, 'attr', None)
                        or getattr(dec.func, 'id', None)) != 'route':
                    continue
                paths = []
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        paths.append(arg.value)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        paths += [e.value for e in arg.elts
                                  if isinstance(e, ast.Constant)]
                kw = {k.arg: (k.value.value if isinstance(k.value, ast.Constant)
                              else '?') for k in dec.keywords}
                for p in paths:
                    out.append((p, node.name, kw.get('type', 'http'),
                                kw.get('auth', 'user')))
    return out


#: 2026-10-09 量到「完全沒有驗證」的 22 條（無 Python 測試、tour 也沒走到）。
#: 每補一條行為測試就從這裡拿掉一條——這份清單縮短的速度就是進度。
_UNVERIFIED = set()        # ← 2026-10-09：**清到 0 了**
#: ☠️ 這份清單曾經是 25 條（`make audit` 的路由覆蓋尺量出來的：核心 36 條
#:    路由裡 25 條完全沒有任何驗證，而 tour 只打到 5 條）。
#:
#:    優化 3 分四批補完：版本面板 5 條、範本欄位 6 條＋匯出、i18n 5 條、
#:    剩下的 10 條（含 3 條回 HTML 頁面的）。
#:
#:    **清空不代表這些路由被驗得很好**——它代表「每一條都至少有一則真的呼叫
#:    它並檢查結果的測試」。那是地板，不是天花板。
#:
#:    補的過程掉出一個真缺陷：`set_edit_target_model` 用了
#:    `ir.model.abstract`（Odoo 18 沒有這個欄位）→ AttributeError，
#:    那條路由在 production 一直是壞的。**同一個缺陷在 list_models 上兩輪前
#:    就修過了，而我當時只修了手上那個實例、沒有 grep 同一類。**
#:    `TestNoReferencesToMissingIrModelFields` 就是為此而加——它擋整類。
#:
#:    下次新增路由時這份清單會被 `test_route_inventory_is_complete` 與
#:    `test_unverified_list_only_shrinks` 盯著：新路由沒有測試就要加進來，
#:    加進來之後有了測試就要拿掉。


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRouteSmoke(SessionAliveMixin, HttpCase):
    """每條 `type='json'` 的路由都要活著，而且壞得像個 JSON API。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.doc = self.env['doc.document'].sudo().create({
            'name': '煙霧測試文件',
            'content_html': '<p>x</p>',
        })

    def test_route_inventory_is_complete(self):
        """`_UNVERIFIED` 裡的每條路徑都要真的存在。

        擋的是「路由改名或刪掉了，清單沒清」——那會讓分母悄悄失真。
        """
        declared = {p for p, _m, _t, _a in _declared_routes()}
        stale = sorted(_UNVERIFIED - declared)
        self.assertFalse(
            stale,
            '_UNVERIFIED 裡這些路徑已經不存在了：%s\n'
            '路由改名或刪除時要同步清這份清單，否則分母會失真。' % stale)

    #: 送最小（多半不合法）參數時，這些例外是**合法回應**——它們代表路由
    #: 活著而且在做輸入驗證。其他任何例外型別都代表路由壞了。
    EXPECTED_EXCEPTIONS = {
        'odoo.exceptions.UserError',
        'odoo.exceptions.MissingError',
        'odoo.exceptions.AccessError',
        'odoo.exceptions.AccessDenied',
        'odoo.exceptions.ValidationError',
    }

    def test_every_json_route_survives_a_minimal_call(self):
        """每條 `type='json'`、`auth='user'` 的路由打一次都不可以**壞掉**。

        ☠️ 第一版只檢查 `status_code >= 500` 與 Content-Type。實測在
        `i18n_languages` 裡塞一句 `raise RuntimeError` ——**測試照樣全綠**。
        原因：`type='json'` 的路由拋例外時 Odoo 回的是 **HTTP 200 ＋
        JSON-RPC error**，不是 500。那一版是裝飾品。

        所以判準改成看 `error.data.name`：
          - UserError / MissingError / AccessError…  → 合法（路由在驗輸入）
          - RuntimeError / AttributeError / ImportError… → 路由壞了

        這才擋得住最大的那一類：重構之後某條路由 ImportError 而沒有任何東西
        會紅。（這個模組踩過：批次精靈在迴圈裡 import 已搬走的模組，
        ImportError 被 `except` 吞掉 → 建出 0 份文件卻回報成功。）
        """
        broken = []
        for path, meth, rtype, auth in _declared_routes():
            if rtype != 'json' or auth != 'user' or '<' in path:
                continue
            resp = self._url_open_live(
                path, where='smoke:%s' % path,
                data='{"jsonrpc":"2.0","method":"call","id":0,'
                     '"params":{"doc_id":%d}}' % self.doc.id,
                headers={'Content-Type': 'application/json'})
            ct = (resp.headers.get('Content-Type') or '').split(';')[0]
            if resp.status_code >= 500:
                broken.append('%s（%s）→ HTTP %s' % (path, meth, resp.status_code))
                continue
            if ct != 'application/json':
                broken.append('%s（%s）→ Content-Type %s，不是 JSON：%r'
                              % (path, meth, ct, (resp.text or '')[:120]))
                continue
            body = resp.json()
            if not isinstance(body, dict) or 'error' not in body:
                continue                      # 成功回應，沒話說
            name = (((body.get('error') or {}).get('data') or {})
                    .get('name') or '(沒有 name)')
            if name not in self.EXPECTED_EXCEPTIONS:
                debug = (((body.get('error') or {}).get('data') or {})
                         .get('debug') or '')
                broken.append('%s（%s）→ %s\n      %s'
                              % (path, meth, name,
                                 debug.strip().split('\n')[-1][:160]))
        self.assertFalse(
            broken,
            '下列路由打一次就壞了（不是業務例外，是真的壞）：\n  %s\n'
            '——這一類壞法不會被任何其他測試抓到，因為它們沒有行為測試。'
            % '\n  '.join(broken))

    def test_unverified_list_only_shrinks(self):
        """`_UNVERIFIED` 是分母：有了行為測試的路由不可以還留在裡面。

        判準是「tests/ 底下有沒有提到那條路徑」。提到了就代表有人為它寫了
        東西，那它就不該還掛在「完全沒有驗證」的清單上。
        """
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        corpus = []
        for name in sorted(os.listdir(tests_dir)):
            if not name.endswith('.py') or name == os.path.basename(__file__):
                continue
            with open(os.path.join(tests_dir, name), encoding='utf-8') as fh:
                corpus.append(fh.read())
        corpus = '\n'.join(corpus)
        now_covered = sorted(
            p for p in _UNVERIFIED if p.split('<')[0] in corpus)
        self.assertFalse(
            now_covered,
            '這些路由已經有測試提到它們了，請從 _UNVERIFIED 移除：%s\n'
            '——清單縮短的速度就是進度，留著過期項目會讓分母失真。'
            % now_covered)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestListModelsBehaviour(SessionAliveMixin, HttpCase):
    r"""`/dobtor_doc/models` 的真行為測試。

    ☠️ 這條路由（編輯器的「選適用模型」選單）**一直是壞的**：domain 寫了
    `('abstract', '=', False)`，而 Odoo 18 的 `ir.model` 有 `transient` 卻
    **沒有 `abstract` 欄位** → 每次呼叫都 `ValueError: Invalid field
    ir.model.abstract`。

    而它**有「測試」**：`test_report_engine.py::test_model_picker_endpoints_exist`
    ——那一則只斷言 `hasattr(DocTemplateController, 'list_models')`，
    **從沒呼叫過它**。「斷言方法存在」不等於「斷言它會動」，
    這是本模組反覆出現的那個失效模式最乾淨的一個例子。

    所以這一支真的打那條路由，而且驗它該做的過濾。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def test_returns_concrete_models(self):
        """回得出東西，而且每一筆都是真的 model。"""
        result = self._jsonrpc_with_evidence(
            '/dobtor_doc/models', {'limit': 10}, where='list_models')
        self.assertIsInstance(result, list)
        self.assertTrue(result, '一個 model 都沒回——過濾條件把全部都濾掉了？')
        for row in result:
            for key in ('id', 'model', 'name'):
                self.assertIn(key, row, '少了 %s：%r' % (key, row))
            self.assertIn(
                row['model'], self.env,
                '%r 不在 registry 裡——那是 ir.model 的殘留列，應該被濾掉'
                % row['model'])

    def test_excludes_transient_and_abstract_models(self):
        """精靈（transient）與抽象模型都不可以出現。

        它們沒有「存得住的記錄」可指，列出來就是誤導。
        抽象模型要用 `_abstract` 在 Python 端判——**不能寫進 domain**，
        那正是這條路由壞掉的原因。
        """
        result = self._jsonrpc_with_evidence(
            '/dobtor_doc/models', {'limit': 200}, where='list_models')
        bad = []
        for row in result:
            model = self.env[row['model']]
            if model._transient:
                bad.append('%s（transient）' % row['model'])
            if model._abstract:
                bad.append('%s（abstract）' % row['model'])
        self.assertFalse(bad, '這些不該出現在可選模型清單裡：%s' % bad)

    def test_query_filters_by_name_or_model(self):
        """帶 query 時要真的過濾（不是忽略參數）。"""
        result = self._jsonrpc_with_evidence(
            '/dobtor_doc/models', {'query': 'res.partner', 'limit': 20},
            where='list_models(query)')
        self.assertTrue(
            any(r['model'] == 'res.partner' for r in result),
            'query=res.partner 竟然沒回出 res.partner：%r' % result[:5])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestNoReferencesToMissingIrModelFields(TransactionCase):
    r"""不可以引用 `ir.model` 上不存在的欄位——擋**整類**缺陷。

    ☠️ 這一支的由來：`ir.model` 在 Odoo 18 有 `transient` 但**沒有 `abstract`
    欄位**，而本模組在**兩個地方**都用了它：

        list_models           domain 寫 ('abstract', '=', False)
                              → ValueError，選模型的選單一直不能用
        set_edit_target_model `model.abstract`
                              → AttributeError，設定適用模型一直不能用

    第一個在稽核尺 3 修掉了。第二個是**兩輪之後**補路由測試時才掉出來的
    ——因為我當時只修了手上那個實例，沒有去 grep 同一類。

    所以這一支不盯特定路由，它掃**整個模組的原始碼**有沒有引用 `ir.model`
    上不存在的欄位。判準用執行期的 registry（`self.env['ir.model']._fields`），
    不是寫死的名單——Odoo 版本間欄位會變，寫死的名單自己就會過期。
    """

    #: 常被誤用的名字 → 正確做法
    SUSPECT_FIELDS = {
        'abstract': "ir.model 沒有這個欄位；抽象模型要用 env[model]._abstract 判",
    }

    def test_no_source_references_a_missing_ir_model_field(self):
        """原始碼不可以出現 `ir.model` 上不存在的欄位名。"""
        import os
        import re
        ir_model_fields = set(self.env['ir.model']._fields)
        bad = []
        for sub in ('models', 'controllers', 'wizards'):
            base = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), sub)
            if not os.path.isdir(base):
                continue
            for dirpath, _d, files in os.walk(base):
                for f in sorted(files):
                    if not f.endswith('.py'):
                        continue
                    path = os.path.join(dirpath, f)
                    with open(path, encoding='utf-8') as fh:
                        lines = fh.read().split('\n')
                    for no, line in enumerate(lines, 1):
                        stripped = line.strip()
                        if stripped.startswith('#'):
                            continue        # 註解裡提到它是在解釋這個坑
                        for name, why in self.SUSPECT_FIELDS.items():
                            if name in ir_model_fields:
                                continue    # 這個 Odoo 版本真的有，不用擋
                            if re.search(r"""(\.%s\b|['"]%s['"])""" % (name, name),
                                         stripped):
                                bad.append('%s/%s:%d  %s\n         → %s'
                                           % (sub, f, no, stripped[:90], why))
        self.assertFalse(
            bad,
            '下列地方引用了 `ir.model` 上不存在的欄位：\n  %s\n'
            '——這一類缺陷的症狀是 ValueError／AttributeError，'
            '而且只有在那條路由真的被呼叫時才會出現。' % '\n  '.join(bad))
