# -*- coding: utf-8 -*-
"""無頭截圖執行器（D8）——在一次性的 Playwright 官方容器裡執行。

    docker run --rm --network <net> -v <job>:/job mcr.microsoft.com/playwright/python:<ver> \
        python /job/run.py

只依賴 Playwright（映像內建）與標準函式庫。讀 /job/job.json，輸出到 /job/out/：
  · <shot_id>/<name>.png          原圖（不含任何標註）
  · result.json                   每張圖的元素座標、畫面上出現的記錄（D1 檢查用）、錯誤

★ 選庫：說明庫所在的共享母體依網址第一段選庫（dbfilter ^%d$）。Chromium 不允許
  覆寫 Host 標頭，所以用 --host-resolver-rules 把 `<庫名>.internal` 映射到母體容器名，
  網址本身就帶著庫名。nginx 與 DNS 都沒有這個名字，外部連不到。
"""
import json
import os
import re
import sys
import time
import traceback
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

JOB_DIR = os.environ.get('KB_JOB_DIR', '/job')
OUT_DIR = os.path.join(JOB_DIR, 'out')

HIDE_CSS = """
*, *::before, *::after { transition: none !important; animation: none !important;
  caret-color: transparent !important; }
.o_menu_systray .badge, .o_menu_systray .o-mail-ActivityMenu-counter,
.o_debug_manager, .o_notification_manager, .o-mail-ChatHub, .o_livechat_button,
.o-mail-Chatter-content, .o-mail-Message-date,
.o_activity_view .o_activity_cell_timestamp { visibility: hidden !important; }
#oe_neutralize_banner { display: none !important; }
/* 前台：說明庫的「已作失效處理」斜條、Cookie 同意列蓋住畫面（實機每張前台截圖都有） */
#oe_neutralize_ribbon, #website_cookies_bar, #cookies_bar { display: none !important; }
"""

#: 畫面上的說明庫內部網址（http://docsbx-….internal:8069）換成示意網址再拍
#: ☠️ 實機：會員「我的帳戶」的推薦連結拍出說明庫的內部主機名
DISPLAY_ORIGIN = 'https://www.example.com'
MASK_JS = r'''(args) => {
    const [origin, shown] = args;
    const host = new URL(origin).host;
    const fix = (s) => s && s.includes(host) ? s.split(origin).join(shown).split(host)
        .join(new URL(shown).host) : s;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) { const v = fix(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; }
    for (const el of document.querySelectorAll('input, textarea')) {
        const v = fix(el.value); if (v !== el.value) el.value = v;
    }
}'''

PROBE_JS = r'''() => {
  const vis = (el) => !!(el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden');
  const txt = (el) => (el && el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const scope = document.querySelector('.o_action_manager') || document.body;
  const out = {buttons: [], fields: [], tabs: [], breadcrumbs: [], columns: [], view_type: '',
               empty: !!scope.querySelector('.o_view_nocontent'), settings: !!scope.querySelector('.o_settings_container, .settings')};
  const kinds = [['o_form_view', 'form'], ['o_list_view', 'list'], ['o_kanban_view', 'kanban'],
                 ['o_pivot_view', 'pivot'], ['o_graph_view', 'graph'], ['o_calendar_view', 'calendar'],
                 ['o_activity_view', 'activity']];
  for (const [cls, name] of kinds) { if (scope.querySelector('.' + cls)) { out.view_type = name; break; } }
  scope.querySelectorAll('.o_list_view th[data-name]').forEach(th => { if (vis(th))
    out.columns.push({name: th.getAttribute('data-name'), label: txt(th)}); });
  scope.querySelectorAll('button[name]').forEach(b => { if (vis(b))
    out.buttons.push({name: b.getAttribute('name'), text: txt(b), type: b.getAttribute('type') || ''}); });
  scope.querySelectorAll('.o_field_widget[name], div[name].o_field_widget').forEach(f => { if (vis(f)) {
    const name = f.getAttribute('name');
    const inp = f.querySelector('input,select,textarea');
    const wrap = f.closest('.o_wrap_field, .o_inner_group > div, .o_cell');
    const label = (inp && inp.id && scope.querySelector('label[for="' + inp.id + '"]'))
      || (wrap && wrap.parentElement && wrap.parentElement.querySelector('.o_wrap_label label, label.o_form_label'));
    out.fields.push({name, label: txt(label), widget: (f.className.match(/o_field_([a-z0-9_]+)/) || [])[1] || ''}); } });
  scope.querySelectorAll('.o_notebook a.nav-link').forEach(t => { if (vis(t))
    out.tabs.push({name: t.getAttribute('name') || '', text: txt(t)}); });
  scope.querySelectorAll('.o_breadcrumb li, .o_breadcrumb .o_last_breadcrumb_item').forEach(b => out.breadcrumbs.push(txt(b)));
  const seen = new Set();
  out.fields = out.fields.filter(f => !seen.has(f.name) && seen.add(f.name));
  return out;
}'''

#: 狀態列目前的值（流程的「截圖觀察」證據：點按鈕前後不同＝看到一次狀態轉換）
STATUS_JS = r'''() => {
  const b = document.querySelector('.o_statusbar_status [aria-checked="true"], '
                                   + '.o_statusbar_status .o_arrow_button_current');
  return b ? (b.getAttribute('data-value') || (b.innerText || '').trim()) : null;
}'''

CALL_KW = re.compile(r'/web/dataset/call_kw/([^/]+)/([^/?]+)')


def _log(*args):
    print('[shot]', *args, flush=True)


#: 欄位在各種畫面上的樣子：表單元件、清單表頭／儲存格、看板卡片
#: ☠️ 原本只認表單（.o_field_widget）：AI 在清單畫面標註欄位時全部逾時（實機 33 個）。
FIELD_SELECTORS = (
    '.o_content [name="{n}"].o_field_widget',
    '.o_content div[name="{n}"]',
    '.o_content th[data-name="{n}"]',
    '.o_content td[name="{n}"]',
    '.o_content .o_kanban_record [name="{n}"]',
)


def _field_locator(page, name):
    n = str(name).replace('\\', '').replace('"', '')
    loc = page.locator(', '.join(s.format(n=n) for s in FIELD_SELECTORS)).first
    try:
        loc.wait_for(state='visible', timeout=4000)
        return loc
    except Exception:  # noqa: BLE001 - 退回用畫面上的標籤文字找（AI 有時給的是中文標籤）
        pass
    return page.locator('.o_content label.o_form_label, .o_content th').filter(
        has_text=str(name)).first


def _button_locator(page, name):
    # ★ 只找看得到的：精靈對話框開著時，背後表單也有同名按鈕（隱藏），取第一個會點不到
    return page.locator('button[name="%s"]:visible' % name).first


def _page_locator(page, name):
    loc = page.locator('.o_notebook a.nav-link[name="%s"]' % name)
    if loc.count():
        return loc.first
    return page.locator('.o_notebook a.nav-link', has_text=name).first


def _locate(page, spec):
    if 'field' in spec:
        return _field_locator(page, spec['field'])
    if 'button' in spec:
        return _button_locator(page, spec['button'])
    if 'page' in spec:
        return _page_locator(page, spec['page'])
    if 'selector' in spec:
        return page.locator(spec['selector']).first
    if 'text' in spec:
        return page.get_by_text(spec['text'], exact=False).first
    raise ValueError('無法定位：%r' % (spec,))


def _settle(page, extra_ms=400):
    # ☠️ 不能無上限等 networkidle：後台的 bus（websocket／longpolling）一直開著，
    #   實測永遠等不到，每一步都卡滿 30 秒逾時。改成「最多等 5 秒」再看 Odoo 自己的載入指示。
    try:
        page.wait_for_load_state('networkidle', timeout=5000)
    except Exception:  # noqa: BLE001
        pass
    if _is_backend(page):
        # 網站前台沒有 .o_action_manager：不等（否則前台每一步白等 15 秒）
        try:
            page.wait_for_selector('.o_action_manager', timeout=15000)
        except Exception:  # noqa: BLE001
            pass
    try:
        page.wait_for_selector('.o_loading_indicator, .o_blockUI', state='detached',
                               timeout=15000)
    except Exception:  # noqa: BLE001 - 沒有這些元素就算穩定
        pass
    page.wait_for_timeout(extra_ms)
    _fail_on_error_dialog(page)


def _fail_on_error_dialog(page):
    """畫面跳出 Odoo 的錯誤對話框（動作不存在、權限不足…）就讓這張圖失敗。

    ☠️ 沒有這道檢查時，AI 猜錯動作代號拍到的「缺漏動作」對話框照樣被採用（實機 5 張）。
    """
    dlg = page.locator('.o_error_dialog')
    if dlg.count():
        title = ''
        try:
            title = dlg.first.locator('.modal-title').inner_text(timeout=1000)
            body = dlg.first.locator('.modal-body').inner_text(timeout=1000)[:200]
        except Exception:  # noqa: BLE001
            body = ''
        raise RuntimeError('畫面出現錯誤對話框：%s %s' % (title.strip(), body.strip()))


class Recorder:
    """收集畫面上出現過的記錄（D1 檢查用）。

    pairs：{model: ids}（查詢的主記錄）；refs：{"model|field": ids}（記錄上的關聯值——
    many2one 的業務員、客戶，x2many 的明細；comodel 由主控台查）。
    ★ 登入後一路累積、不在每張圖之間清空：同一頁先前載入的記錄仍在畫面上，
      清空會漏檢（寧可多檢）。
    """

    def __init__(self):
        self.pairs = {}
        self.refs = {}

    def reset(self):
        self.pairs = {}
        self.refs = {}

    @staticmethod
    def _add(bucket, key, ids):
        bucket.setdefault(key, set()).update(i for i in ids if isinstance(i, int))

    def _walk(self, model, rec, depth=0):
        """主記錄進 pairs；關聯值進 refs。x2many 的明細列（dict）要往下走：
        明細上的產品、業務員一樣會出現在畫面上。"""
        if not isinstance(rec, dict) or depth > 4:
            return
        if depth == 0 and isinstance(rec.get('id'), int):
            self._add(self.pairs, model, [rec['id']])
        for field, val in rec.items():
            if field == 'id':
                continue
            key = '%s|%s' % (model, field)
            if isinstance(val, dict) and isinstance(val.get('id'), int):
                self._add(self.refs, key, [val['id']])
            elif isinstance(val, (list, tuple)) and val:
                first = val[0]
                if isinstance(first, dict):
                    self._add(self.refs, key, [v.get('id') for v in val if isinstance(v, dict)])
                    for sub in val:
                        # 明細列本身的欄位：以「明細欄位」為前綴記，comodel 由主控台解析
                        self._walk_line(key, sub, depth + 1)
                elif isinstance(first, int) and field.endswith(('_id', '_ids')):
                    self._add(self.refs, key, [val[0]] if field.endswith('_id') else list(val))

    def _walk_line(self, parent_key, line, depth):
        if not isinstance(line, dict) or depth > 4:
            return
        for field, val in line.items():
            if field == 'id':
                continue
            key = '%s>%s' % (parent_key, field)
            if isinstance(val, dict) and isinstance(val.get('id'), int):
                self._add(self.refs, key, [val['id']])
            elif isinstance(val, (list, tuple)) and val and isinstance(val[0], dict):
                self._add(self.refs, key, [v.get('id') for v in val if isinstance(v, dict)])

    def _walk_groups(self, model, groups):
        """分組清單的群組標題：many2one 分組值是 [id, name] 或 {id, display_name}。"""
        for g in groups or []:
            if not isinstance(g, dict):
                continue
            for field, val in g.items():
                name = field.split(':')[0]
                if isinstance(val, (list, tuple)) and len(val) == 2 and isinstance(val[0], int):
                    self._add(self.refs, '%s|%s' % (model, name), [val[0]])
                elif isinstance(val, dict) and isinstance(val.get('id'), int):
                    self._add(self.refs, '%s|%s' % (model, name), [val['id']])

    def on_response(self, response):
        m = CALL_KW.search(response.url)
        if not m or response.status != 200:
            return
        model, method = m.group(1), m.group(2)
        if method not in ('web_search_read', 'web_read', 'read', 'search_read',
                          'web_read_group', 'name_search', 'web_search_read_group',
                          'onchange', 'web_save'):
            return
        try:
            result = (response.json() or {}).get('result')
        except Exception:  # noqa: BLE001
            return
        records = []
        if isinstance(result, dict):
            self._walk_groups(model, result.get('groups'))
            records = result.get('records') or ([result['value']] if isinstance(
                result.get('value'), dict) else [])
        elif isinstance(result, list):
            records = result
        for rec in records:
            if isinstance(rec, dict):
                self._walk(model, rec)
            elif isinstance(rec, (list, tuple)) and rec and isinstance(rec[0], int):
                self._add(self.pairs, model, [rec[0]])

    def dump(self):
        return ({k: sorted(v) for k, v in self.pairs.items()},
                {k: sorted(v) for k, v in self.refs.items()})


#: 後台沒有載入的錯誤開頭（呼叫端據此判斷：不是腳本的錯、不叫 AI 修）
BACKEND_DOWN = '後台沒有載入'
#: 這一頁的 console 錯誤與經過的網址（診斷後台為什麼沒載入）
_CONSOLE = []
_NAVS = []
#: 說明庫的庫名（有就用 API 登入）
_DB = [None]


def _backend_diag(page):
    """後台沒載入時留下看得出原因的線索：停在哪、標題、後台骨架有沒有出來、console 錯誤。"""
    info = {'url': page.url}
    for key, fn in (('title', lambda: page.title()),
                    ('navbar', lambda: page.locator('.o_main_navbar').count()),
                    ('action_manager', lambda: page.locator('.o_action_manager').count()),
                    ('body', lambda: page.locator('body').inner_text(timeout=2000)[:300])):
        try:
            info[key] = fn()
        except Exception as e:  # noqa: BLE001
            info[key] = 'ERR %s' % str(e)[:80]
    info['console'] = _CONSOLE[-8:]
    info['navigations'] = _NAVS[-12:]
    return json.dumps(info, ensure_ascii=False)


def _is_backend(page):
    return urlparse(page.url).path.startswith(('/odoo', '/web')) \
        and not urlparse(page.url).path.startswith(('/web/login', '/web/signup'))


def _api_login(page, base, login_name, password):
    """用 /web/session/authenticate 登入（cookie 跟著瀏覽器內容走）。

    ☠️ 實機：社群電商方案把 /web/login 改成首頁的登入彈窗（/?popup=login），照登入頁填帳密
      從來沒登入成功，87 張全卡在「後台沒有載入」。API 登入不管登入畫面長什麼樣。"""
    # ☠️ 不能用 page.request：它走 Node 端的網路，不吃瀏覽器的 --host-resolver-rules，
    #   說明庫的 <庫名>.internal 解析不到（實機 ENOTFOUND）。先開同源的小頁，再在頁面裡 fetch。
    try:
        page.goto(base + '/robots.txt')
        data = page.evaluate('''async (p) => {
            const r = await fetch('/web/session/authenticate', {method: 'POST',
                headers: {'Content-Type': 'application/json'}, credentials: 'include',
                body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: p})});
            try { return await r.json(); } catch (e) { return {status: r.status}; }
        }''', {'db': _DB[0], 'login': login_name, 'password': password})
    except Exception as e:  # noqa: BLE001 — 連不上說明庫＝執行環境的錯，不是腳本的錯
        raise RuntimeError('%s（登入時連不上說明庫：%s）：%s' % (
            BACKEND_DOWN, str(e).splitlines()[0][:160], _backend_diag(page)))
    data = data or {}
    if data.get('error') or not (data.get('result') or {}).get('uid'):
        raise RuntimeError('登入失敗：%s' % str((data.get('error') or {}).get('data', {})
                                                .get('message') or data.get('status'))[:200])


def login(page, base, login_name, password, frontend=False):
    """登入。frontend：前台頁的會員帳號（入口網站使用者進不了後台），登入後回網站首頁。"""
    if _DB[0]:
        _api_login(page, base, login_name, password)
        if frontend:
            return   # 前台頁的步驟自己開網址
        page.goto(base + '/odoo')
        try:
            page.wait_for_selector('.o_action_manager', timeout=30000)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError('%s（%s）：%s' % (BACKEND_DOWN, str(e).splitlines()[0][:120],
                                               _backend_diag(page)))
        _settle(page)
        return
    page.goto(base + '/web/login')
    page.fill('input[name="login"]', login_name)
    page.fill('input[name="password"]', password)
    # ☠️ 不能點 `button[type="submit"]`：裝了 website 的庫，登入頁 header 還有一顆隱藏的
    #   搜尋送出鈕，選擇器先抓到它，等它可見等到逾時。直接在密碼欄按 Enter 送出登入表單。
    page.press('input[name="password"]', 'Enter')
    if frontend:
        try:
            page.wait_for_url(lambda u: '/web/login' not in u, timeout=30000)
        except Exception as e:  # noqa: BLE001
            if page.locator('.alert-danger').count():
                raise RuntimeError('登入失敗：%s' % page.locator('.alert-danger').first.inner_text())
            raise RuntimeError('會員登入後沒有離開登入頁：%s' % str(e).splitlines()[0][:120])
        _settle(page)
        return
    try:
        try:
            page.wait_for_url(lambda u: '/web/login' not in u, timeout=15000)
        except Exception:  # noqa: BLE001 - 帳密錯誤會留在登入頁，下面等 .alert-danger
            pass
        try:
            page.wait_for_load_state('load', timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        path = urlparse(page.url).path
        if '/web/login' not in path and not path.startswith(('/odoo', '/web')):
            # ☠️ 實機：社群電商方案登入後被導回網站首頁（「Home | 94愛分享」），
            #   不是進後台——自己開 /odoo，不靠登入後的導向
            # ☠️ 實機：登入後的導向還沒走完就開 /odoo，被「另一個導向」打斷：等載入完、重試一次
            for attempt in range(2):
                try:
                    page.goto(base + '/odoo')
                    break
                except Exception:  # noqa: BLE001
                    if attempt:
                        raise
                    page.wait_for_timeout(1500)
        page.wait_for_selector('.o_action_manager, .alert-danger', timeout=30000)
    except Exception as e:  # noqa: BLE001
        # ☠️ 實機：社群電商方案 87 張全卡在這裡，AI 每張修一次腳本（$7.84）——
        #   後台根本沒載入，改腳本修不好
        raise RuntimeError('%s（%s）：%s' % (BACKEND_DOWN, str(e).splitlines()[0][:120],
                                           _backend_diag(page)))
    if page.locator('.alert-danger').count():
        raise RuntimeError('登入失敗：%s' % page.locator('.alert-danger').first.inner_text())
    _settle(page)


def _status(page):
    try:
        return page.evaluate(STATUS_JS)
    except Exception:  # noqa: BLE001 - 觀察失敗不影響拍攝
        return None


def run_steps(page, base, shot, out_dir, recorder, observed=None, warnings=None, images=None):
    """依序執行步驟。

    ★ 步驟可帶 "optional": true 與 "grp": "<組名>"：選用步驟失敗不讓整張失敗，同組後面的
      步驟一起略過（情境教學：按鈕在這張單據的狀態下沒出現，就跳過這一步的整組截圖）。
      "req": [<組名>…]：這些組有任何一組被略過，這一步也略過。
    ★ images 由呼叫端傳入：中途失敗時，已經拍好的圖照樣回傳。"""
    images = images if images is not None else []
    regions = []
    warnings = warnings if warnings is not None else []
    observed = observed if observed is not None else []
    skipped = set()
    for idx, step in enumerate(shot.get('steps') or []):
        grp = step.get('grp')
        if grp and grp in skipped:
            continue
        if any(r in skipped for r in step.get('req') or []):
            # 前面的組失敗（例如沒打開下游單據）：這組也不做，免得在錯的畫面按到同名按鈕
            if grp:
                skipped.add(grp)
            continue
        kind = next(k for k in step if k not in ('optional', 'grp', 'req'))
        arg = step[kind]
        if step.get('optional'):
            try:
                res = _run_step(page, base, kind, arg, idx, out_dir, recorder, observed, warnings,
                                images, regions)
                if isinstance(res, dict) and res.get('page'):
                    page = res['page']
            except Exception as e:  # noqa: BLE001
                try:
                    where = '%s｜%s' % (page.url, page.locator('body').inner_text(timeout=2000)[:120]
                                       .replace('\n', ' '))
                except Exception:  # noqa: BLE001
                    where = ''
                warnings.append('步驟 %s（選用）略過：%s（%s）' % (
                    idx, str(e).splitlines()[0][:160], where))
                if grp:
                    skipped.add(grp)
                regions.clear()
            continue
        res = _run_step(page, base, kind, arg, idx, out_dir, recorder, observed, warnings, images,
                        regions)
        if isinstance(res, dict) and res.get('page'):
            page = res['page']
    return images


#: remember／recall 步驟記下的網址（每張重設）：情境教學打開下游單據後，換角色再回到那張
_SAVED = {}
#: 每個帳號一個已登入的分頁（每張重設）；_MAKE_PAGE[0]() 開一個設定好的新瀏覽器內容
_ROLE_PAGES = {}
_MAKE_PAGE = [None]


def _new_page(browser, job):
    ctx = browser.new_context(
        viewport={'width': job.get('width', 1440), 'height': job.get('height', 900)},
        device_scale_factor=job.get('scale', 2),
        locale=job.get('locale', 'zh-TW'),
        timezone_id=job.get('tz', 'Asia/Taipei'),
        reduced_motion='reduce')
    page = ctx.new_page()
    # ☠️ 實機：按過按鈕的表單離開時跳「離開此頁？」（beforeunload）；Playwright 預設取消。
    page.on('dialog', lambda d: d.accept())
    # 找不到元素要快點失敗：錯誤交給 AI 修，不值得每步等 30 秒。
    page.set_default_timeout(10000)
    if job.get('frozen_time'):
        try:
            # ★ set_fixed_time 讓 Date.now() 固定，計時器照常跑（install 只設起點，
            #   時間仍會前進，「幾分鐘前」之類的字每次都不同）。
            page.clock.set_fixed_time(job['frozen_time'])
        except Exception:  # noqa: BLE001 - 舊版 Playwright 沒有 clock
            pass
    page.add_init_script(
        "document.addEventListener('DOMContentLoaded',()=>{const s=document."
        "createElement('style');s.textContent=%s;document.head.appendChild(s);});"
        % json.dumps(HIDE_CSS + (job.get('extra_css') or '')))
    return page


def _run_step(page, base, kind, arg, idx, out_dir, recorder, observed, warnings, images, regions):
    if kind == 'login':
        # 換角色：清掉這個瀏覽器的 session 再登入（同一張單據由不同角色往下推）
        # ☠️ 實機：GET /web/session/logout 之後仍是登入狀態，/web/login 直接轉回後台，找不到帳號欄
        # ☠️ 實機：同一個瀏覽器內容清 cookie 再登入（原分頁或新分頁都一樣）第二次一定找不到
        #   帳號欄。改成每個帳號一個獨立的瀏覽器內容，第一次用到才登入，之後直接切過去——
        #   跟每張截圖一開始的登入完全同一條路。
        user = arg['user']
        if user not in _ROLE_PAGES:
            fresh = _MAKE_PAGE[0]()
            fresh.on('response', recorder.on_response)
            login(fresh, base, user, arg['password'])
            _ROLE_PAGES[user] = fresh
        return {'page': _ROLE_PAGES[user]}
    if kind == 'remember':
        _SAVED[arg] = page.url
        return None
    if kind == 'recall':
        if arg not in _SAVED:
            raise RuntimeError('沒有記下的畫面：%s' % arg)
        page.goto(_SAVED[arg])
        _settle(page)
        return None
    if True:
        if kind == 'goto':
            if 'url' in arg:
                page.goto(base + arg['url'])
            elif 'action' in arg:
                url = '/odoo/action-%s' % arg['action']
                if arg.get('res_id'):
                    url += '/%s' % arg['res_id']
                page.goto(base + url)
            elif 'menu_id' in arg:
                page.goto(base + '/odoo?menu_id=%s' % arg['menu_id'])
            _settle(page)
        elif kind == 'open':
            page.goto(base + '/odoo/%s/%s' % (arg['model'], arg['res_id']))
            _settle(page)
        elif kind == 'click':
            before = _status(page) if isinstance(arg, dict) and arg.get('button') else None
            _locate(page, arg).click()
            _settle(page)
            if before is not None:
                after = _status(page)
                if after and after != before:
                    observed.append({'button': arg['button'], 'from': before, 'to': after})
        elif kind == 'fill':
            target = _locate(page, arg)
            inner = target.locator('input, textarea').first
            (inner if inner.count() else target).fill(str(arg.get('value', '')))
            _settle(page, 200)
        elif kind == 'wait':
            if 'selector' in arg:
                page.wait_for_selector(arg['selector'], timeout=arg.get('timeout', 15000))
            else:
                page.wait_for_timeout(int(arg.get('ms', 500)))
        elif kind == 'highlight':
            # ★ 標註找不到不讓整張圖失敗：截圖本身仍可用，少一個編號框而已；
            #   缺的標註記在 warnings，由控制台決定要不要請 AI 修腳本。
            try:
                target = _locate(page, arg)
                # 設定頁、長表單：元素可能在畫面外，先捲進來（截圖只拍可視範圍）
                try:
                    target.scroll_into_view_if_needed(timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
                box = target.bounding_box(timeout=5000)
            except Exception as e:  # noqa: BLE001
                box = None
                warnings.append('步驟 %s：找不到要標註的元素 %r（%s）'
                                % (idx, arg, str(e).splitlines()[0][:120]))
            if not box:
                if not any(str(idx) in w for w in warnings):
                    warnings.append('步驟 %s：要標註的元素沒有大小 %r' % (idx, arg))
                return
            regions.append({'n': arg.get('n', len(regions) + 1),
                            'x': round(box['x']), 'y': round(box['y']),
                            'w': round(box['width']), 'h': round(box['height'])})
        elif kind == 'probe':
            # ★ AI 探索用：把畫面上「實際渲染出來」的互動元素交給 AI，而不是讓 AI 自己開瀏覽器。
            #   view arch 看不到的東西（群組隱藏、條件隱藏、模組繼承後的實際位置）這裡都看得到。
            name = arg if isinstance(arg, str) else arg.get('name')
            path = os.path.join(out_dir, '%s.png' % name)
            page.screenshot(path=path, full_page=False)
            images.append({'name': name, 'file': os.path.relpath(path, OUT_DIR),
                           'probe': page.evaluate(PROBE_JS), 'is_probe': True})
        elif kind == 'shot':
            name = arg if isinstance(arg, str) else arg.get('name')
            path = os.path.join(out_dir, '%s.png' % name)
            _fail_on_error_dialog(page)
            try:
                page.evaluate(MASK_JS, [urlparse(page.url).scheme + '://' + urlparse(page.url).netloc,
                                        DISPLAY_ORIGIN])
            except Exception:  # noqa: BLE001 - 遮不到就照拍
                pass
            page.screenshot(path=path, full_page=False)
            pairs, refs = recorder.dump()
            # 空白引導頁（沒有資料的清單／看板／報表）：照拍，但標記出來由控制台決定不採用
            empty = bool(page.locator('.o_view_nocontent:visible').count())
            if not empty and not _is_backend(page):
                # 前台空白頁：入口網站「目前沒有訂單／發票」只有一個黃色提示、沒有資料表
                # ☠️ 實機：會員的「我的訂單」拍成「您的帳戶目前沒有銷售訂單」照樣採用
                empty = bool(page.locator('main .alert-warning:visible').count()) and \
                    not page.locator('main table tbody tr').count()
            images.append({'name': name, 'file': os.path.relpath(path, OUT_DIR),
                           'regions': list(regions), 'records': pairs, 'refs': refs,
                           'empty': empty})
            regions.clear()
        else:
            raise ValueError('未知步驟：%s' % kind)
    return None


def main():
    with open(os.path.join(JOB_DIR, 'job.json'), encoding='utf-8') as fh:
        job = json.load(fh)
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {'shots': {}, 'started': time.time()}
    # 自我檢查：容器裡有沒有中文字型（沒掛字型時中文會變方框，截圖看得出來但流程不會失敗）
    try:
        import subprocess
        out = subprocess.run(['fc-list', ':lang=zh-tw', 'family'], capture_output=True,
                             text=True, timeout=20).stdout
        result['cjk_fonts'] = sorted({l.split(',')[0].strip() for l in out.splitlines()
                                      if l.strip()})[:20]
    except Exception as e:  # noqa: BLE001
        result['cjk_fonts_error'] = str(e)[:300]
    base = job['base_url'].rstrip('/')
    _DB[0] = job.get('db')
    args = ['--host-resolver-rules=%s' % job['resolver_rule']] if job.get('resolver_rule') else []
    down = {}   # 每個帳號各自算：一個角色打不開，不該連累其他角色
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        for shot in job['shots']:
            sid = shot['id']
            if down.get(shot.get('login'), 0) >= 3:
                # 同一個帳號連續三張後台都沒載入：這個帳號的其餘不拍了（每張白等 30 秒，結果一樣）
                # ☠️ 實機：不分帳號時，三張「會員」帳號拍後台失敗，把同批其他角色 17 張也略過
                result['shots'][sid] = {'ok': False, 'images': [], 'transitions': [],
                                        'error': '%s（前 3 張都打不開，其餘略過）' % BACKEND_DOWN}
                continue
            out_dir = os.path.join(OUT_DIR, sid)
            os.makedirs(out_dir, exist_ok=True)
            _MAKE_PAGE[0] = lambda: _new_page(browser, job)
            page = _new_page(browser, job)
            ctx = page.context
            recorder = Recorder()
            _SAVED.clear()
            _ROLE_PAGES.clear()
            if shot.get('login'):
                _ROLE_PAGES[shot['login']] = page
            page.on('response', recorder.on_response)
            _CONSOLE.clear()
            _NAVS.clear()
            page.on('framenavigated', lambda f: f == f.page.main_frame and _NAVS.append(
                urlparse(f.url).path + ('?' + urlparse(f.url).query if urlparse(f.url).query else '')))
            page.on('console', lambda m: m.type in ('error', 'warning') and _CONSOLE.append(
                '%s: %s' % (m.type, m.text[:200])))
            page.on('pageerror', lambda e: _CONSOLE.append('pageerror: %s' % str(e)[:300]))
            try:
                images, observed = [], []
                if shot.get('login'):
                    login(page, base, shot['login'], shot['password'],
                          frontend=bool(shot.get('frontend')))
                # 沒有帳號＝網站訪客：不登入，直接照步驟開前台頁
                recorder.reset()
                observed = []
                warnings = []
                images = []
                run_steps(page, base, shot, out_dir, recorder, observed, warnings, images)
                result['shots'][sid] = {'ok': True, 'images': images, 'transitions': observed,
                                        'warnings': warnings}
                _log(sid, 'ok', len(images))
                down[shot.get('login')] = 0
            except Exception as e:  # noqa: BLE001
                key = shot.get('login')
                down[key] = down.get(key, 0) + 1 if str(e).startswith(BACKEND_DOWN) else 0
                err_png = os.path.join(out_dir, '_error.png')
                try:
                    page.screenshot(path=err_png)
                except Exception:  # noqa: BLE001
                    err_png = None
                try:
                    dom = page.locator('.o_content').first.inner_text(timeout=3000)[:6000]
                except Exception:  # noqa: BLE001
                    dom = ''
                result['shots'][sid] = {
                    'ok': False, 'error': str(e)[:2000],
                    # 中途失敗前已經拍好的圖（情境教學：做到哪一步就教到哪一步）
                    'images': [i for i in images if not i.get('is_probe')],
                    'transitions': observed,
                    'trace': traceback.format_exc()[-3000:], 'url': page.url,
                    'dom_text': dom,
                    'error_image': os.path.relpath(err_png, OUT_DIR) if err_png else None}
                _log(sid, 'FAILED', e)
            finally:
                ctx.close()
                for other in list(_ROLE_PAGES.values()):
                    if other.context is not ctx:
                        try:
                            other.context.close()
                        except Exception:  # noqa: BLE001
                            pass
                _ROLE_PAGES.clear()
        browser.close()
    result['finished'] = time.time()
    with open(os.path.join(OUT_DIR, 'result.json'), 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
