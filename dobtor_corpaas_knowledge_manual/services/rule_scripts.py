# -*- coding: utf-8 -*-
"""規則產生截圖腳本（A2：規則為主、AI 為輔）。

為什麼
------
2026-10-05 實機：94 個畫面全部請 AI 寫腳本，光探索就花約 14 美元，失敗主因卻是
AI 猜錯動作代號（拍到「缺漏動作」12 個）、清單畫面用表單寫法定位欄位（33 個）。
這些資訊功能點盤點時早就有了：動作 xmlid、模型、設定欄位名；畫面上實際有哪些欄位、
分頁，由一次批次探測（無頭瀏覽器真的打開畫面）取得。

規則
----
· 動作型：開動作 → 拍入口畫面（清單標前 3 欄、表單標前 4 個有標籤的欄位）；
  入口是清單／看板且情境有這個模型的示範記錄 → 打開記錄 → 拍表單 → 每個分頁拍一張（最多 2 個）。
· 設定型：開設定頁 → 捲到該設定 → 標註 → 拍。
· 只有「看」的動作（開畫面、點分頁），不按任何會改資料的按鈕：說明庫拍完不會變髒，可以沿用（R1）。
· 規則寫不出來（沒有動作、探測失敗）才退回 AI 探索；規則腳本拍失敗由既有的 AI 修補接手。
"""
import re

SETTINGS_ACTION = 'base_setup.action_general_configuration'
#: 拍入口畫面時要標註的欄位數
ENTRY_HIGHLIGHTS = 3
FORM_HIGHLIGHTS = 4
MAX_TABS = 2
#: 這些畫面拍入口就夠（沒有「打開一筆記錄」可言）
NO_RECORD_VIEWS = ('pivot', 'graph', 'calendar', 'activity', 'form')

#: 模組 → 情境角色代碼（角色要有權限看這個畫面；找不到對應角色就用第一個）
ROLE_BY_MODULE = (
    (('purchase', 'purchase_requisition', 'purchase_stock'), 'purchase'),
    (('stock', 'stock_account', 'stock_landed_costs', 'stock_picking_batch',
      'stock_dropshipping', 'delivery', 'uom', 'sale_stock'), 'stock'),
    (('account', 'account_payment', 'analytic', 'payment', 'base'), 'account'),
    (('sale', 'sale_management', 'sales_team', 'sale_pdf_quote_builder', 'loyalty',
      'product', 'contacts', 'mail', 'spreadsheet_dashboard'), 'sales'),
)


def is_front_path(path):
    """網站前台的路徑（可以用 goto url）：/ 開頭、不是後台（/odoo、/web/…，註冊與登入頁除外）。

    ☠️ 後台網址會被品牌過濾改寫（odoo 字樣被換掉），所以後台一律用動作 xmlid。"""
    if not isinstance(path, str) or not path.startswith('/') or 'odoo' in path:
        return False
    return not path.startswith('/web') or path.split('?')[0] in ('/web/signup', '/web/login')


def slug(text):
    return re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')[:40] or 'screen'


def pick_role(feature_kind, module, role_codes, anchor=None):
    """這個功能用哪個角色登入拍。設定頁要系統管理員（一般角色進不去設定）。

    ★ 前台頁：/my 開頭用會員帳號（情境要有 member 角色），其他用訪客（不登入）。"""
    if feature_kind == 'route':
        from odoo.addons.dobtor_corpaas_knowledge.models.feature import (
            ROUTE_VISITOR, route_audience)
        role = route_audience(anchor)
        # 情境沒有這個角色（會員、網站管理）就退回訪客：至少拍得到公開的樣子
        return role if role == ROUTE_VISITOR or role in (role_codes or []) else ROUTE_VISITOR
    from odoo.addons.dobtor_corpaas_knowledge.models.feature import ROUTE_MEMBER, ROUTE_VISITOR
    # ★ 後台畫面不用前台角色（會員是入口網站帳號，打不開後台）
    # ☠️ 實機（2026-10-11 社群電商從零）：情境第一個角色是 member，自訂模組 25 個畫面都退回它 → 後台沒有載入
    codes = [c for c in role_codes or [] if c not in (ROUTE_MEMBER, ROUTE_VISITOR)]
    if feature_kind == 'setting' and 'admin' in codes:
        return 'admin'
    for modules, code in ROLE_BY_MODULE:
        if module in modules and code in codes:
            return code
    # 對照表沒有的模組（多半是方案自訂模組）：系統管理員一定看得到；沒有才用第一個後台角色
    if 'admin' in codes:
        return 'admin'
    return codes[0] if codes else False


def _labelled(fields, limit):
    """有標籤的欄位優先（截圖上看得懂），依畫面順序取前 limit 個。"""
    out = [f for f in fields or [] if f.get('name') and f.get('label')]
    return out[:limit]


def build_steps(feature, entry=None, record=None, has_record=False):
    """回傳 (steps, placeholders)；寫不出來回 (None, [])。

    feature: dict（kind、action_xmlid、anchor、key）；entry／record: 探測結果（可為 None）。
    has_record: 情境裡有這個模型的示範記錄（佔位符 rec）。
    """
    key = slug(feature.get('key') or feature.get('anchor') or 'screen')
    kind = feature.get('kind')
    if kind == 'route':
        from odoo.addons.dobtor_corpaas_knowledge.models.feature import (
            ROUTE_EDITOR, route_audience, route_path)
        path = route_path(feature.get('anchor'))
        if not is_front_path(path):
            return None, []
        # 前台頁：直接開網址拍整個可視範圍（網站沒有欄位名可以標註）
        steps = [{'goto': {'url': path}}, {'wait': {'ms': 1200}}]
        if route_audience(feature.get('anchor')) == ROUTE_EDITOR:
            # 內部使用者在前台看到的「回後台／編輯此內容」工具列，再拍按下編輯後的網站編輯器
            steps += [{'highlight': {'selector': '.o_frontend_to_backend_edit_btn', 'n': 1}},
                      {'shot': '%s_page' % key},
                      {'goto': {'url': '/@' + path}}, {'wait': {'ms': 2500}},
                      {'shot': '%s_editor' % key}]
            return steps, []
        return steps + [{'shot': '%s_page' % key}], []
    if kind == 'setting':
        anchor = feature.get('anchor')
        if not anchor:
            return None, []
        return ([{'goto': {'action': SETTINGS_ACTION}},
                 {'wait': {'ms': 800}},
                 {'highlight': {'field': anchor, 'n': 1}},
                 {'shot': '%s_setting' % key}], [])
    action = feature.get('action_xmlid')
    if not action:
        return None, []
    steps = [{'goto': {'action': action}}, {'wait': {'ms': 600}}]
    entry = entry or {}
    view = entry.get('view_type') or ''
    if view == 'list':
        cols = _labelled(entry.get('columns'), ENTRY_HIGHLIGHTS)
        for i, col in enumerate(cols, 1):
            steps.append({'highlight': {'field': col['name'], 'n': i}})
    elif view == 'form':
        for i, f in enumerate(_labelled(entry.get('fields'), FORM_HIGHLIGHTS), 1):
            steps.append({'highlight': {'field': f['name'], 'n': i}})
    steps.append({'shot': '%s_entry' % key})
    placeholders = []
    if has_record and view not in NO_RECORD_VIEWS:
        placeholders = ['rec']
        steps += [{'open': '{rec}'}, {'wait': {'ms': 600}}]
        record = record or {}
        for i, f in enumerate(_labelled(record.get('fields'), FORM_HIGHLIGHTS), 1):
            steps.append({'highlight': {'field': f['name'], 'n': i}})
        steps.append({'shot': '%s_form' % key})
        tabs = [t for t in record.get('tabs') or [] if t.get('name') or t.get('text')]
        for i, tab in enumerate(tabs[1:MAX_TABS + 1], 1):
            # 第一個分頁是表單預設顯示的那個，上一張已經拍到
            ref = {'page': tab.get('name') or tab.get('text')}
            steps += [{'click': ref}, {'wait': {'ms': 400}}, {'shot': '%s_tab%d' % (key, i)}]
    return steps, placeholders


def mutates(steps):
    """腳本會不會改到說明庫的資料：按物件按鈕或填欄位＝會；開畫面、點分頁＝不會。"""
    for step in steps or []:
        if not isinstance(step, dict) or not step:
            continue
        kind = next(iter(step))
        arg = step[kind]
        if kind == 'fill':
            return True
        if kind == 'click' and isinstance(arg, dict) and arg.get('button'):
            return True
    return False
