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
"""

PROBE_JS = r'''() => {
  const vis = (el) => !!(el && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden');
  const txt = (el) => (el && el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const scope = document.querySelector('.o_action_manager') || document.body;
  const out = {buttons: [], fields: [], tabs: [], breadcrumbs: [], view_type: ''};
  const vt = scope.querySelector('.o_form_view, .o_list_view, .o_kanban_view');
  out.view_type = vt ? (vt.classList.contains('o_form_view') ? 'form'
                      : vt.classList.contains('o_list_view') ? 'list' : 'kanban') : '';
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

CALL_KW = re.compile(r'/web/dataset/call_kw/([^/]+)/([^/?]+)')


def _log(*args):
    print('[shot]', *args, flush=True)


def _field_locator(page, name):
    return page.locator('.o_content [name="%s"].o_field_widget, .o_content div[name="%s"]'
                        % (name, name)).first


def _button_locator(page, name):
    return page.locator('button[name="%s"]' % name).first


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
    try:
        page.wait_for_selector('.o_action_manager', timeout=15000)
    except Exception:  # noqa: BLE001 - 登入頁等非後台頁面沒有它
        pass
    try:
        page.wait_for_selector('.o_loading_indicator, .o_blockUI', state='detached',
                               timeout=15000)
    except Exception:  # noqa: BLE001 - 沒有這些元素就算穩定
        pass
    page.wait_for_timeout(extra_ms)


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


def login(page, base, login_name, password):
    page.goto(base + '/web/login')
    page.fill('input[name="login"]', login_name)
    page.fill('input[name="password"]', password)
    # ☠️ 不能點 `button[type="submit"]`：裝了 website 的庫，登入頁 header 還有一顆隱藏的
    #   搜尋送出鈕，選擇器先抓到它，等它可見等到逾時。直接在密碼欄按 Enter 送出登入表單。
    page.press('input[name="password"]', 'Enter')
    page.wait_for_selector('.o_action_manager, .alert-danger', timeout=30000)
    if page.locator('.alert-danger').count():
        raise RuntimeError('登入失敗：%s' % page.locator('.alert-danger').first.inner_text())
    _settle(page)


def run_steps(page, base, shot, out_dir, recorder):
    images, regions = [], []
    for idx, step in enumerate(shot.get('steps') or []):
        kind = next(iter(step))
        arg = step[kind]
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
            _locate(page, arg).click()
            _settle(page)
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
            box = _locate(page, arg).bounding_box()
            if not box:
                raise RuntimeError('步驟 %s：找不到要標註的元素 %r' % (idx, arg))
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
            page.screenshot(path=path, full_page=False)
            pairs, refs = recorder.dump()
            images.append({'name': name, 'file': os.path.relpath(path, OUT_DIR),
                           'regions': regions, 'records': pairs, 'refs': refs})
            regions = []
        else:
            raise ValueError('未知步驟：%s' % kind)
    return images


def main():
    with open(os.path.join(JOB_DIR, 'job.json'), encoding='utf-8') as fh:
        job = json.load(fh)
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {'shots': {}, 'started': time.time()}
    base = job['base_url'].rstrip('/')
    args = ['--host-resolver-rules=%s' % job['resolver_rule']] if job.get('resolver_rule') else []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        for shot in job['shots']:
            sid = shot['id']
            out_dir = os.path.join(OUT_DIR, sid)
            os.makedirs(out_dir, exist_ok=True)
            ctx = browser.new_context(
                viewport={'width': job.get('width', 1440), 'height': job.get('height', 900)},
                device_scale_factor=job.get('scale', 2),
                locale=job.get('locale', 'zh-TW'),
                timezone_id=job.get('tz', 'Asia/Taipei'),
                reduced_motion='reduce')
            page = ctx.new_page()
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
            recorder = Recorder()
            page.on('response', recorder.on_response)
            try:
                login(page, base, shot['login'], shot['password'])
                recorder.reset()
                images = run_steps(page, base, shot, out_dir, recorder)
                result['shots'][sid] = {'ok': True, 'images': images}
                _log(sid, 'ok', len(images))
            except Exception as e:  # noqa: BLE001
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
                    'trace': traceback.format_exc()[-3000:], 'url': page.url,
                    'dom_text': dom,
                    'error_image': os.path.relpath(err_png, OUT_DIR) if err_png else None}
                _log(sid, 'FAILED', e)
            finally:
                ctx.close()
        browser.close()
    result['finished'] = time.time()
    with open(os.path.join(OUT_DIR, 'result.json'), 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
