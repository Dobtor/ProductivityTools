"""編輯器面板的瀏覽器驗證（tour）。

這支存在的理由：模組的前端有約 7000 行 JS 與 2000 行 OWL 模板，Python 測試
一行都碰不到。而前端最常見的壞法是靜默的——模板引用了不存在的 getter、
inspector 分支的條件寫錯，OWL 會把渲染錯誤吞成一塊空白面板，使用者只會覺得
「點了沒反應」。

**跑之前先看懂 test_browser_available**：缺 chromium 或 websocket-client 時，
Odoo 會把 tour「跳過」而不是失敗——整份測試仍然全綠，但其實一步都沒跑。
所以這裡用一則獨立的測試把環境需求釘住，而不是讓它靜默略過。
"""

import glob
import os
import re
from importlib.util import find_spec

from odoo.tests.common import HttpCase, tagged
from odoo.tools.misc import find_in_path

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _chrome_available():
    for name in ('google-chrome', 'chromium', 'chromium-browser',
                 'chrome', 'chrome-browser'):
        try:
            if find_in_path(name):
                return name
        except IOError:
            continue
    return None


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestBrowserAvailable(HttpCase):
    """環境自檢：沒有這則，tour 被跳過時整份測試還是綠的。"""

    def test_browser_requirements_are_reported(self):
        chrome = _chrome_available()
        has_ws = find_spec('websocket') is not None
        if chrome and has_ws:
            return
        missing = []
        if not chrome:
            missing.append('chromium（apt-get install chromium）')
        if not has_ws:
            missing.append('websocket-client（pip install websocket-client）')
        # 用 skipTest 而不是 fail：CI 以外的環境不該因為缺瀏覽器就紅。
        # 但訊息要明講「tour 沒跑」，否則看到綠燈會以為前端驗過了。
        self.skipTest(
            '瀏覽器 tour 未執行（前端未驗證）。缺：%s' % '、'.join(missing)
        )


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocEditorPanelsTour(HttpCase):
    """左右面板與各 inspector 分支的實際渲染。"""

    def setUp(self):
        super().setUp()
        self.Template = self.env['doc.template']
        # 用 res.partner 當適用模型：它同時有 one2many（child_ids）、
        # binary（image_1920）與 html（comment），左欄的三個對應群組才會出現。
        # 挑 sale.order 的話測試就綁死在 sale 有沒有安裝上。
        self.template = self.Template.create({
            'name': 'Tour 範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'content_json': self._tour_content(),
        })
        base = self.env.ref('dobtor_doc_editor.action_doc_editor_client')
        # client action 把 template_id 寫進 context：編輯器是 client action，
        # 而 context 沒辦法從網址帶進去，所以建一筆專用的 action 給 tour 開。
        self.action = self.env['ir.actions.client'].create({
            'name': 'Tour 編輯器',
            'tag': base.tag,
            'target': 'fullscreen',
            'context': "{'template_id': %d}" % self.template.id,
        })

    def _tour_content(self):
        import json
        # 內容裡先放一個重複列標記，開檔時 _recoverRepeatContext 才會把
        # repeatContext 還原出來，左欄「分組與流水」那一組才會出現
        pill = {
            'type': 'label', 'value': '明細',
            'label': {'backgroundColor': '#e3f2fd'},
            'extension': {'dobtorField': {
                'source': 'repeat', 'path': 'child_ids',
                'relation': 'res.partner', 'repeatId': 'rp1',
                'labelText': '明細',
            }},
        }
        return json.dumps({
            'header': [],
            'main': [
                {'value': '這段是可以被抽出成多語文字的靜態文字'},
                {'value': '\n'},
                {'type': 'table', 'value': '',
                 'colgroup': [{'width': 300}],
                 'trList': [{'tdList': [{
                     'colspan': 1, 'rowspan': 1,
                     'value': [pill, {'value': '\n'}],
                 }]}]},
                {'value': '\n'},
            ],
            'footer': [],
        }, ensure_ascii=False)

    def test_panels_tour(self):
        if not _chrome_available() or find_spec('websocket') is None:
            self.skipTest('缺瀏覽器或 websocket-client，tour 未執行')
        self.start_tour(
            '/odoo/action-%d' % self.action.id,
            'doc_editor_panels_tour',
            login='admin',
            timeout=180,
        )


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestListOpensEditorTour(HttpCase):
    """從清單進編輯器的四條路（點一筆／按新增 × 文件／範本）。

    ☠️ 為什麼要有這一組：TestDocEditorPanelsTour 從編輯器的 client action
    直接進去，**繞過清單**。所以清單的 js_class
    （static/src/views/doc_document_list_open_editor.js）一行都沒被測過——
    2026-10-12 正式機上點清單任一筆就炸（Odoo 18 的 ListController 沒有
    this.orm），而 678 則測試全綠。
    """

    def setUp(self):
        super().setUp()
        # 清單至少要有一筆才點得到。名字帶 id 只是讓失敗訊息好認。
        # ☠️ 以 admin 身分建：文件清單的 action 預設套「我的文件」
        #    （search_default_my_docs ＝ create_uid = uid），超級使用者建的
        #    那筆 admin 登入後看不到，清單是空的、「點一筆」根本沒東西點。
        admin = self.env.ref('base.user_admin')
        self.env = self.env(user=admin)
        self.Template = self.env['doc.template']
        self.template = self.Template.create({
            'name': 'tour 清單範本 %s' % self.id(),
            'model_id': self.env.ref('base.model_res_partner').id,
        })
        self.document = self.env['doc.document'].create({
            'name': 'tour 清單文件 %s' % self.id(),
        })

    def _run(self, action_xmlid, tour):
        if not _chrome_available() or find_spec('websocket') is None:
            self.skipTest('缺瀏覽器或 websocket-client，tour 未執行')
        action = self.env.ref(action_xmlid)
        self.start_tour('/odoo/action-%d' % action.id, tour,
                        login='admin', timeout=120)

    def test_document_list_click_opens_editor(self):
        self._run('dobtor_doc_editor.action_doc_document_list',
                  'doc_document_list_click_tour')

    def test_document_list_new_opens_editor(self):
        self._run('dobtor_doc_editor.action_doc_document_list',
                  'doc_document_list_new_tour')

    def test_template_list_click_opens_editor(self):
        self._run('dobtor_doc_editor.action_doc_template_list',
                  'doc_template_list_click_tour')

    def test_template_list_new_opens_editor(self):
        self._run('dobtor_doc_editor.action_doc_template_list',
                  'doc_template_list_new_tour')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestPortalEditorMountsTour(HttpCase):
    """Portal 協作者打開 /my/documents/<id>，編輯器真的在瀏覽器裡掛起來。

    ☠️ 這個頁面的 HTTP 回應早就有測（test_route_remaining.py），但頁面上的
    JS 從沒執行過。Portal 是 DocEditor 唯一沒有 action／dialog service 的
    環境，那些 null 分支只有在這裡會跑到。
    """

    def setUp(self):
        super().setUp()
        # start_tour(login=X) 內部是 self.authenticate(X, X)——密碼必須等於帳號。
        login = 'tour_portal_doc'
        self.portal_user = self.env['res.users'].create({
            'name': 'tour portal 協作者',
            'login': login,
            'password': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('dobtor_doc_editor.group_doc_portal').id,
            ])],
        })
        self.document = self.env['doc.document'].create({
            'name': 'tour portal 文件',
            'collaborator_ids': [(6, 0, [self.portal_user.id])],
        })

    def test_portal_editor_mounts(self):
        if not _chrome_available() or find_spec('websocket') is None:
            self.skipTest('缺瀏覽器或 websocket-client，tour 未執行')
        self.start_tour('/my/documents/%d' % self.document.id,
                        'doc_portal_editor_mount_tour',
                        login=self.portal_user.login, timeout=120)


#: 每個前端進入點 → 從它進去的 tour（必須存在於 static/tests/tours/）。
#: 新增 js_class／client action／public component 時，這張表要跟著加一列，
#: 而且要真的寫一支從那裡進去的 tour——否則 TestEveryEntryPointHasATour 會紅。
ENTRY_POINT_TOURS = {
    ('actions', 'dobtor_doc_editor.action_doc_editor'): 'doc_editor_panels_tour',
    ('views', 'doc_document_list_open_editor'): 'doc_document_list_click_tour',
    ('views', 'doc_template_list_open_editor'): 'doc_template_list_click_tour',
    ('public_components', 'dobtor_doc_editor.DocEditor'): 'doc_portal_editor_mount_tour',
}


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestEveryEntryPointHasATour(HttpCase):
    """前端每個進入點都要有一支**從那裡進去**的 tour。

    ☠️ 2026-10-12 一天裡抓到的三個正式機缺陷，根因是同一個：
      - 清單點一筆就炸（ListController 沒有 this.orm）
      - 清單「新增」就炸（@api.model 方法被傳了 [[]]）
      - Portal 編輯器永遠停在「載入中」（doc_field_picker 不在前台 bundle）
    三個進入點都**存在，但沒有任何測試從那裡進去**——唯一的 tour 是直接從
    編輯器的 client action 開始的。進入點跟 tour 的對應表就是這一則的分母；
    registry 多一個進入點、表沒跟上，這裡就紅。
    """

    _ADD_RE = re.compile(
        r'registry\s*\.category\(\s*"(views|actions|public_components|fields|systray)"\s*\)'
        r'\s*\.add\(\s*"([^"]+)"')
    _TOUR_RE = re.compile(
        r'web_tour\.tours"\)\s*\.add\(\s*(?:"([^"]+)"|name)')

    def _registered_entry_points(self):
        found = set()
        for path in glob.glob(os.path.join(MODULE_ROOT, 'static', 'src', '**', '*.js'),
                              recursive=True):
            if os.sep + 'lib' + os.sep in path:
                continue
            with open(path, encoding='utf-8') as fh:
                found.update(self._ADD_RE.findall(fh.read()))
        return found

    def _defined_tours(self):
        names = set()
        for path in glob.glob(os.path.join(MODULE_ROOT, 'static', 'tests', 'tours', '*.js')):
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
            names.update(n for n in self._TOUR_RE.findall(src) if n)
            # 用迴圈註冊的那幾支：[["name", step], …] 形式
            names.update(re.findall(r'\[\s*"([a-z_]+_tour)"\s*,', src))
        return names

    def test_entry_points_are_found(self):
        """先確認抽得到——抽到 0 個的話下一則會空轉過關。"""
        self.assertGreaterEqual(len(self._registered_entry_points()), 3)
        self.assertGreaterEqual(len(self._defined_tours()), 3)

    def test_every_entry_point_is_mapped_to_a_tour(self):
        found = self._registered_entry_points()
        mapped = set(ENTRY_POINT_TOURS)
        self.assertFalse(
            sorted(found - mapped),
            '這些前端進入點沒有對應的 tour：%s\n'
            '——請寫一支從那裡進去的 tour，並在 ENTRY_POINT_TOURS 加一列。'
            % sorted(found - mapped))
        self.assertFalse(
            sorted(mapped - found),
            'ENTRY_POINT_TOURS 列了已不存在的進入點：%s' % sorted(mapped - found))

    def test_every_mapped_tour_exists(self):
        tours = self._defined_tours()
        missing = sorted(t for t in ENTRY_POINT_TOURS.values() if t not in tours)
        self.assertFalse(missing, '對應表指向不存在的 tour：%s' % missing)
