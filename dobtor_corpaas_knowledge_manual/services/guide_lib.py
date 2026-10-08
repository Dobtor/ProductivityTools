# -*- coding: utf-8 -*-
"""說明書的規則產生頁（導讀、開始前必設定、狀態速查、訊息與狀況對照）。

★ 這些頁不經 AI 起草、不送審：內容全部來自說明庫實機探測與流程結構，AI 只補兩種短文
  （狀態的意思、訊息的原因與處理），各自有文字檢查；系統訊息一律保留原文。
★ 這裡只放純函式（探測腳本產生器、HTML 組裝），方便單元測試；寫 slide 在 models/guide.py。
"""
import html as html_mod
import json
import re

from odoo.addons.dobtor_corpaas_knowledge.services import scripts

from . import layout_lib as L

#: 開始前必設定的檢查項。model 不在說明庫（模組沒裝）就不列。
#: count_min：至少要幾筆才算「已設定」（外幣：本國幣之外至少一種）。
SETUP_ITEMS = [
    {'key': 'company', 'label': '公司資料', 'model': 'res.company', 'required': True,
     'why': '報價單、發票與報表的抬頭、統編、幣別會是空白或錯的'},
    {'key': 'users', 'label': '使用者帳號與權限', 'model': 'res.users', 'required': True,
     'domain': [['share', '=', False], ['active', '=', True]],
     'why': '沒有帳號或權限不足，就看不到對應的選單與按鈕'},
    {'key': 'warehouse', 'label': '倉庫', 'model': 'stock.warehouse', 'required': True,
     'why': '沒有倉庫就無法收貨、出貨與調撥'},
    {'key': 'accounts', 'label': '會計科目表', 'model': 'account.account', 'required': True,
     'count_only': True, 'why': '沒有會計科目就無法過帳，發票與付款都會失敗'},
    {'key': 'journals', 'label': '日記帳（銷售、採購、銀行、現金）', 'model': 'account.journal',
     'required': True, 'label_field': 'type',
     'why': '沒有銷售或採購日記帳就不能開發票與帳單；沒有銀行或現金日記帳就不能登記收付款'},
    {'key': 'taxes', 'label': '預設銷項稅與進項稅', 'model': 'account.tax', 'required': True,
     'company_fields': ['account_sale_tax_id', 'account_purchase_tax_id'],
     'why': '新建立的商品不會自動帶稅，發票稅額會算錯'},
    {'key': 'payment_terms', 'label': '付款條件', 'model': 'account.payment.term',
     'required': False, 'why': '沒設就一律以發票日當到期日，應收帳齡與催收不準'},
    {'key': 'pricelist', 'label': '價目表', 'model': 'product.pricelist', 'required': False,
     'why': '所有客戶都用商品的銷售價，無法給不同客戶不同價格'},
    {'key': 'sales_team', 'label': '銷售團隊', 'model': 'crm.team', 'required': False,
     'why': '報價與訂單無法依團隊分派、統計業績'},
    {'key': 'product_category', 'label': '商品類別', 'model': 'product.category',
     'required': False, 'why': '商品都落在預設類別，庫存計價與入帳科目都用預設值'},
    {'key': 'currency', 'label': '外幣與匯率', 'model': 'res.currency', 'required': False,
     'domain': [['active', '=', True]], 'count_min': 2,
     'why': '只能用本國幣交易；有外幣進出時要先啟用幣別並設定匯率'},
]

#: 探測訊息時不按的按鈕（會寄信、列印、連外或下載）
BUTTON_DENY = r'(?i)send|mail|print|sms|whatsapp|export|sync|upload|download|portal|preview|report'
#: 狀態速查不列的按鈕（列印、預覽、匯出不會推進狀態；靜態分析偶爾把它們推成別的路徑）
STATUS_DENY = r'(?i)print|preview|report|export|download'
#: 一次探測最多按幾次按鈕（說明庫很小，但流程多時仍要有上限）
PROBE_LIMIT = 150


def esc(value):
    return html_mod.escape(str(value or ''))


def _table(headers, rows):
    head = ''.join('<th>%s</th>' % esc(h) for h in headers)
    body = ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % c for c in row) for row in rows)
    return ('<table class="table table-bordered table-striped align-middle">'
            '<thead class="table-light"><tr>%s</tr></thead><tbody>%s</tbody></table>') % (head, body)


# ----------------------------------------------------------------------
# 探測腳本（在說明庫執行，一律結尾 rollback）
# ----------------------------------------------------------------------
def setup_probe_script(items, groups, lang='zh_TW'):
    """開始前必設定：各檢查項目前有什麼、去哪個選單設定；角色群組的顯示名稱。

    回傳 {'items': {key: {count, names, menu}}, 'groups': {xmlid: 顯示名稱}}。"""
    return scripts._HEAD + (
        "ITEMS = json.loads(%r)\n"
        "GROUPS = json.loads(%r)\n"
        "LANG = _lang(%r)\n"
    ) % (json.dumps(items), json.dumps(groups), lang) + r"""
E = env(context=dict(env.context, lang=LANG))
company = E.company
def menu_path(model):
    acts = E['ir.actions.act_window'].sudo().search([('res_model', '=', model)])
    if not acts:
        return ''
    menus = E['ir.ui.menu'].sudo().search(
        [('action', 'in', ['ir.actions.act_window,%d' % a.id for a in acts])])
    names = sorted((m.complete_name or '' for m in menus), key=lambda n: (n.count('/'), len(n)))
    return names[0] if names else ''
def label(rec, field):
    f = rec._fields.get(field)
    if not f:
        return rec.display_name
    v = rec[field]
    if f.type == 'selection':
        v = dict(f._description_selection(E)).get(v, v)
    elif f.type == 'many2one':
        v = v.display_name
    return '%s（%s）' % (rec.display_name, v) if v else rec.display_name
out = {}
for it in ITEMS:
    model = it['model']
    if model not in E:
        continue
    M = E[model].sudo()
    if it.get('company_fields'):
        recs = E[model].sudo().browse()
        for fname in it['company_fields']:
            if fname in company._fields:
                recs |= company[fname]
        names = [r.display_name for r in recs]
        out[it['key']] = {'count': len(recs), 'names': names, 'menu': menu_path(model)}
        continue
    dom = [tuple(d) for d in it.get('domain') or []]
    if 'company_id' in M._fields and model != 'res.company':
        dom.append(('company_id', 'in', [False, company.id]))
    try:
        count = M.search_count(dom)
        recs = M.browse() if it.get('count_only') else M.search(dom, limit=6)
    except Exception:
        continue
    names = [label(r, it['label_field']) if it.get('label_field') else r.display_name for r in recs]
    if model == 'res.company':
        extra = []
        if company.vat:
            extra.append('統編 %s' % company.vat)
        if company.currency_id:
            extra.append('幣別 %s' % company.currency_id.name)
        names = [company.name + ('（%s）' % '，'.join(extra) if extra else '')]
    out[it['key']] = {'count': count, 'names': names, 'menu': menu_path(model)}
gnames = {}
for x in GROUPS:
    g = E.ref(x, raise_if_not_found=False)
    if g:
        gnames[x] = g.full_name
env.cr.rollback()
print(MARK + json.dumps({'items': out, 'groups': gnames}))
"""


def message_probe_script(spec, lang='zh_TW', limit=PROBE_LIMIT):
    """訊息與狀況對照：在說明庫的真實單據上按流程按鈕，收集系統跳出的訊息原文。

    spec: [{flow, model, field, first, buttons: [{name, label, from}]}]（from 空＝任何狀態都看得到）。
    兩種情況各試一次：照示範單據按（缺前置資料的訊息），以及複製一張、把明細清空再按
    （「沒有明細」類的訊息——只在流程第一個狀態試：已過帳的單據不會有人把明細刪光）。
    每次都在 savepoint 裡做、做完回滾，結尾整個 rollback。
    ★ 按成功時記下單據實際從哪個狀態到哪個狀態（observed）：靜態分析推不出終點的按鈕，
      狀態速查與情境教學就不用猜。
    回傳 {'messages': [{flow, button, label, from, variant, message}], 'observed': [{flow, button, from, to}]}。"""
    return scripts._HEAD + (
        "import re\n"
        "SPEC = json.loads(%r)\n"
        "LANG = _lang(%r)\n"
        "LIMIT = %d\n"
        "DENY = re.compile(%r)\n"
    ) % (json.dumps(spec), lang, limit, BUTTON_DENY) + r"""
from odoo.exceptions import UserError
class _Undo(Exception):
    pass
E = env(context=dict(env.context, lang=LANG, tracking_disable=True, mail_notrack=True,
                     mail_create_nolog=True, mail_auto_subscribe_no_notify=True))
out, seen, calls, observed = [], set(), 0, []
def press(rec, name):
    ctx = dict(rec.env.context, active_id=rec.id, active_ids=rec.ids, active_model=rec._name)
    getattr(rec.with_context(ctx), name)()
def empty_copy(rec):
    dup = rec.copy()
    for fname, fld in dup._fields.items():
        if fld.type == 'one2many' and fld.store and 'line' in fname:
            dup[fname].unlink()
    return dup
for f in SPEC:
    if f['model'] not in E or f['field'] not in E[f['model']]._fields:
        continue
    M = E[f['model']].sudo().with_context(active_test=False)
    for b in f['buttons']:
        if calls >= LIMIT:
            break
        if DENY.search(b['name']) or not hasattr(M, b['name']) or b['name'].startswith('_'):
            continue
        dom = [(f['field'], '=', b['from'])] if b.get('from') else []
        rec = M.search(dom, limit=1, order='id')
        if not rec:
            continue
        variants = ('as_is', 'empty') if (b.get('from') or '') in ('', f.get('first')) else ('as_is',)
        for variant in variants:
            calls += 1
            try:
                with E.cr.savepoint():
                    target = empty_copy(rec) if variant == 'empty' else rec
                    if variant == 'empty' and b.get('from') and target[f['field']] != b['from']:
                        raise _Undo()
                    before = target[f['field']]
                    press(target, b['name'])
                    E.flush_all()
                    target.invalidate_recordset()
                    after = target[f['field']]
                    if variant == 'as_is' and after != before and isinstance(after, str):
                        observed.append({'flow': f['flow'], 'model': f['model'], 'button': b['name'],
                                         'from': str(before), 'to': after})
                    raise _Undo()
            except _Undo:
                pass
            except UserError as e:
                msg = str(e.args[0] if e.args else e).strip()
                key = (f['flow'], msg)
                if msg and key not in seen:
                    seen.add(key)
                    out.append({'flow': f['flow'], 'button': b['name'], 'label': b.get('label') or '',
                                'from': b.get('from') or '', 'variant': variant, 'message': msg[:600]})
            except Exception:
                pass
            E.invalidate_all()
env.cr.rollback()
print(MARK + json.dumps({'messages': out, 'observed': observed}))
"""


# ----------------------------------------------------------------------
# HTML 組裝（純函式：輸入都是已整理好的 dict）
# ----------------------------------------------------------------------
def _p(text, cls=''):
    return '<p%s>%s</p>' % (' class="%s"' % cls if cls else '', esc(text))


def render_setup(data):
    """開始前必設定：每個設定項一個手風琴（標題列＝名稱＋必要／建議＋狀態，展開＝現況／沒設會怎樣／去哪裡）。

    ★ 表格儲存格放不下「沒設定會怎樣」這種一兩句的說明 → 改手風琴，長說明放展開內容。"""
    parts = [_p('本說明的畫面都在已經設定好的系統上拍攝。', 'lead'),
             _p('在新的系統照著做之前，請先逐項確認；標示「必要」的沒有設定，後面的操作會卡住。')]
    items = []
    first_open = False
    for it in data.get('items') or []:
        now = '、'.join(esc(n) for n in (it.get('names') or [])[:5])
        if it.get('count_only') and it.get('count'):
            now = esc('已有 %s 筆' % it['count'])
        need = L.badge('必要', 'danger') if it.get('required') else L.badge('建議', 'secondary')
        state = ('<span class="ms-auto me-3 small text-success"><i class="fa fa-check-circle me-1">'
                 '</i>已設定</span>') if it.get('ok') else (
            '<span class="ms-auto me-3 small text-warning-emphasis"><i class="fa fa-exclamation-triangle '
            'me-1"></i>尚未設定</span>')
        title = '<span class="fw-semibold me-2">%s</span>%s%s' % (esc(it['label']), need, state)
        body = ('<dl class="row mb-0"><dt class="col-sm-3">示範系統目前</dt><dd class="col-sm-9">%s</dd>'
                '<dt class="col-sm-3">沒設定會怎樣</dt><dd class="col-sm-9">%s</dd>'
                '<dt class="col-sm-3">去哪裡設定</dt><dd class="col-sm-9 mb-0">%s</dd></dl>') % (
            now or '—', esc(it.get('why') or ''),
            L.menu_path(it['menu']) if it.get('menu') else '—')
        items.append((title, body))
        if it.get('required') and not it.get('ok'):
            first_open = first_open or len(items) == 1
    if items:
        parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3>' % esc('設定項目'))
        parts.append(L.accordion('kbsetup', items, open_first=first_open))
    roles = data.get('roles') or []
    if roles:
        parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3>' % esc('使用者與權限'))
        parts.append(_p('本說明以下列角色的帳號操作拍攝。請替每位使用者勾選對應的權限群組，'
                        '否則看到的選單和按鈕會跟說明不同。'))
        cards = ''.join(
            '<div class="col-12 col-md-6 col-lg-4"><div class="card h-100"><div class="card-body">'
            '<h4 class="h6 card-title"><i class="fa fa-user me-1"></i>%s</h4><div class="d-flex '
            'flex-wrap gap-1">%s</div></div></div></div>' % (
                esc(r['name']), ''.join(L.outline_badge(g) for g in r.get('groups') or []) or '—')
            for r in roles)
        parts.append('<div class="row g-3 mb-3">%s</div>' % cards)
    toggles = data.get('toggles') or []
    if toggles:
        parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3>' % esc('要先開啟的進階功能'))
        parts.append(_p('下列功能預設是關閉的，本方案已經開啟；在新的系統要先到設定頁打開。'))
        groups = {}
        for t in toggles:
            segs = [x.strip() for x in re.split(r'\s*›\s*', t['path']) if x.strip()]
            app = segs[1] if len(segs) > 2 and segs[0] in ('設定', 'Settings') else (segs[0] if segs else '')
            groups.setdefault(app, []).append(t)
        acc = []
        for app, ts in groups.items():
            body = '<ul class="mb-0">%s</ul>' % ''.join(
                '<li>%s<span class="text-body-secondary">：%s</span></li>' % (
                    L.menu_path(t['path']), esc('、'.join(t.get('features') or [])))
                for t in ts)
            acc.append(('<span class="fw-semibold me-2">%s</span>%s' % (
                esc(app or '其他'), L.badge(str(len(ts)), 'secondary')), body))
        parts.append(L.accordion('kbtoggle', acc))
    return L.page('<div class="o_kb_guide o_kb_setup">%s</div>' % ''.join(parts))


def render_howto(data):
    """本說明怎麼用。data = {product, chapters: [{name, url}], setup_url, roles: [{name, chapters}],
    updated, kinds}。"""
    kinds = set(data.get('kinds') or [])
    parts = [_p('這是「%s」的操作說明。' % (data.get('product') or ''), 'lead'),
             _p('每一章是一個工作領域：章首的「整體流程」用流程圖說明這一章的事情怎麼串起來%s，'
                '接著是日常操作（每個畫面一篇），最後是報表與設定畫面。' % (
                    '，「情境教學」用同一張示範單據從頭做到尾' if 'tutorial' in kinds else ''))]
    tail = '、'.join('「%s」' % n for k, n in (('status', '狀態速查'), ('messages', '訊息與狀況對照'))
                    if k in kinds)
    if tail:
        parts.append(_p('章末有%s，遇到問題時可以直接查。' % tail))
    chapters = [c for c in data.get('chapters') or [] if c.get('url')]
    steps = []
    if data.get('setup_url'):
        steps.append('<a href="%s">%s</a><div class="small text-body-secondary">%s</div>' % (
            esc(data['setup_url']), esc('先看「開始前必設定」'), esc('確認系統已經設定好')))
    if chapters:
        steps.append('%s<div class="d-flex flex-wrap gap-2 mt-2">%s</div>' % (
            esc('依序看各章的「整體流程」'), ''.join(
                '<a class="btn btn-sm btn-outline-primary" href="%s">%s</a>' % (
                    esc(c['url']), esc(c['name'])) for c in chapters)))
    steps.append('%s<div class="small text-body-secondary">%s</div>' % (
        esc('要做某件事時，到對應章節找那個畫面的說明'), esc('照步驟操作，做完對照「完成後會看到」')))
    parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3><ol class="list-group list-group-numbered '
                 'mb-3">%s</ol>' % (esc('第一次使用'), ''.join(
                     '<li class="list-group-item">%s</li>' % x for x in steps)))
    roles = [r for r in data.get('roles') or [] if r.get('chapters')]
    if roles:
        urls = {c['name']: c['url'] for c in chapters}
        parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3>' % esc('誰該看哪幾章'))
        parts.append(L.tabs('kbroles', [(r['name'], '<div class="d-flex flex-wrap gap-2">%s</div>' % ''.join(
            ('<a class="btn btn-sm btn-outline-primary" href="%s">%s</a>' % (esc(urls[c]), esc(c)))
            if urls.get(c) else L.outline_badge(c) for c in r['chapters'])) for r in roles]))
    if data.get('updated'):
        parts.append('<p class="small text-body-secondary mt-3"><i class="fa fa-camera me-1"></i>%s</p>'
                     % esc('畫面都在實際系統上、以上述角色的帳號操作拍攝；畫面改版時會自動重拍。'
                           '最近更新：%s。' % data['updated']))
    return L.page('<div class="o_kb_guide o_kb_howto">%s</div>' % ''.join(parts))


_NEXT = re.compile(r'^按「(.+?)」(?:\s*→\s*(.+)|開出「(.+)」)?$')


def _action(line, primary=True):
    """「按『確認』→ 完成」→ 按鈕外觀＋狀態徽章；看不懂的照原文。"""
    m = _NEXT.match(line or '')
    if not m:
        return esc(line)
    out = L.button(m.group(1), primary)
    if m.group(2):
        out += ' <i class="fa fa-long-arrow-right text-body-secondary"></i> ' + L.outline_badge(m.group(2))
    elif m.group(3):
        out += ' <span class="small text-body-secondary">開出</span> ' + L.outline_badge(m.group(3))
    return '<div class="mb-1">%s</div>' % out


def render_status(flows):
    """狀態速查：每個流程一個手風琴項目（主線預設展開），狀態用徽章、按鈕用按鈕外觀。"""
    parts = [_p('單據停在某個狀態、不知道下一步要做什麼時，查這張表。', 'lead')]
    items = []
    for fi, flow in enumerate(flows):
        steps = flow['steps']
        has_back = any(s.get('back') for s in steps)
        rows = []
        for i, s in enumerate(steps):
            tone = 'secondary' if i == 0 else ('success' if i == len(steps) - 1 else 'info')
            last = i == len(steps) - 1
            row = ['<td class="text-nowrap">%s</td>' % L.badge(s['label'], tone),
                   '<td>%s</td>' % esc(s.get('meaning') or '—'),
                   '<td>%s</td>' % (''.join(_action(x) for x in s.get('next') or [])
                                    or esc('（流程終點）' if last else '—'))]
            if has_back:
                row.append('<td>%s</td>' % (''.join(_action(x, False) for x in s.get('back') or [])
                                            or '—'))
            row.append('<td class="small">%s</td>' % (esc('、'.join(s.get('roles') or [])) or '—'))
            rows.append('<tr>%s</tr>' % ''.join(row))
        heads = ['狀態', '意思', '怎麼往下一步'] + (['取消或退回'] if has_back else []) + ['誰負責往下推']
        table = ('<div class="table-responsive"><table class="table table-sm align-middle mb-0">'
                 '<thead class="table-light"><tr>%s</tr></thead><tbody>%s</tbody></table></div>') % (
            ''.join('<th>%s</th>' % esc(h) for h in heads), ''.join(rows))
        items.append(('<span class="fw-semibold me-2">%s</span>%s' % (
            esc(flow['name']), L.badge('%s 個狀態' % len(steps), 'secondary')), table))
    parts.append(L.accordion('kbstatus', items, open_first=True))
    return L.page('<div class="o_kb_guide o_kb_status">%s</div>' % ''.join(parts))


def render_messages(groups):
    """訊息與狀況對照：每則訊息一個手風琴項目；標題列就是系統訊息原文（讀者拿訊息來查）。"""
    parts = [_p('操作時系統跳出下列訊息，先照「怎麼處理」做。', 'lead'),
             _p('訊息是系統畫面上的原文，可以直接用瀏覽器的「尋找」搜尋。', 'small text-body-secondary')]
    for gi, g in enumerate(groups):
        items = []
        for it in g['items']:
            title = '<i class="fa fa-times-circle text-danger me-2"></i><span>%s</span>' % esc(it['message'])
            body = ('<p class="small text-body-secondary mb-2"><i class="fa fa-clock-o me-1"></i>%s</p>'
                    '<p><span class="fw-semibold">為什麼：</span>%s</p>'
                    '<div class="alert alert-success mb-0 py-2"><i class="fa fa-wrench me-1"></i>'
                    '<span class="fw-semibold">怎麼處理：</span>%s</div>') % (
                esc(it.get('when') or ''), esc(it.get('cause') or '—'), L.inline(esc(it.get('fix') or '—')))
            items.append((title, body))
        parts.append('<h3 class="h5 fw-semibold mt-4">%s</h3>' % esc(g['name']))
        parts.append(L.accordion('kbmsg%s' % gi, items))
    return L.page('<div class="o_kb_guide o_kb_messages">%s</div>' % ''.join(parts))


#: 常見簡體字：AI 補的短文含這些字就不用（跟文章的文字檢查同一份精神）
_SIMPLIFIED = re.compile('[这为们说时发开关过还进单应个对会来么经现实务样点让认识计记设调导选择]')


def clean_short(text, limit=120):
    """AI 補的短文：去掉 HTML、截長度；含簡體字或技術欄位名就丟掉（回空字串）。"""
    t = re.sub(r'<[^>]+>', '', str(text or '')).strip()
    if not t or _SIMPLIFIED.search(t) or re.search(r'\b[a-z]+(?:_[a-z0-9]+)+\b', t):
        return ''
    return t[:limit]
