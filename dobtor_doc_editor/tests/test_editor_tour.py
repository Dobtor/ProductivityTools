"""編輯器面板的瀏覽器驗證（tour）。

這支存在的理由：模組的前端有約 7000 行 JS 與 2000 行 OWL 模板，Python 測試
一行都碰不到。而前端最常見的壞法是靜默的——模板引用了不存在的 getter、
inspector 分支的條件寫錯，OWL 會把渲染錯誤吞成一塊空白面板，使用者只會覺得
「點了沒反應」。

**跑之前先看懂 test_browser_available**：缺 chromium 或 websocket-client 時，
Odoo 會把 tour「跳過」而不是失敗——整份測試仍然全綠，但其實一步都沒跑。
所以這裡用一則獨立的測試把環境需求釘住，而不是讓它靜默略過。
"""

from importlib.util import find_spec

from odoo.tests.common import HttpCase, tagged
from odoo.tools.misc import find_in_path


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
