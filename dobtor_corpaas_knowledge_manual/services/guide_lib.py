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
def render_setup(data):
    """開始前必設定。data = {'items': [...], 'toggles': [...], 'roles': [...]}。"""
    parts = ['<p>%s</p>' % esc(
        '這一頁列出開始使用前必須先設定好的項目。本說明的畫面都在已經設定好的系統上拍攝，'
        '在新的系統照著做之前，請先逐項確認；標示「必要」的沒有設定，後面的操作會卡住。')]
    rows = []
    for it in data.get('items') or []:
        now = '、'.join(esc(n) for n in (it.get('names') or [])[:5])
        if it.get('count_only') and it.get('count'):
            now = esc('已有 %s 筆' % it['count'])
        if not it.get('ok'):
            now = '<strong>%s</strong>' % esc('尚未設定') + ((' ' + now) if now else '')
        rows.append([
            esc(it['label']), esc('必要' if it.get('required') else '建議'), now or '—',
            esc(it.get('why') or ''), esc(it.get('menu') or '—')])
    if rows:
        parts.append(_table(['設定項目', '是否必要', '示範系統目前的設定', '沒設定會怎樣', '去哪裡設定'],
                            rows))
    roles = data.get('roles') or []
    if roles:
        parts.append('<p><strong>%s</strong></p>' % esc('使用者與權限'))
        parts.append('<p>%s</p>' % esc('本說明以下列角色的帳號操作拍攝。請替每位使用者勾選對應的權限群組，'
                                       '否則看到的選單和按鈕會跟說明不同：'))
        parts.append(_table(['角色', '權限群組'], [
            [esc(r['name']), '、'.join(esc(g) for g in r.get('groups') or []) or '—'] for r in roles]))
    toggles = data.get('toggles') or []
    if toggles:
        parts.append('<p><strong>%s</strong></p>' % esc('要先開啟的進階功能'))
        parts.append('<p>%s</p>' % esc('下列功能預設是關閉的，本方案已經開啟；在新的系統要先到設定頁打開：'))
        parts.append('<ul>%s</ul>' % ''.join(
            '<li>%s：%s</li>' % (esc(t['path']), esc('、'.join(t.get('features') or [])))
            for t in toggles))
    return '<div class="o_kb_guide o_kb_setup">%s</div>' % ''.join(parts)


def render_howto(data):
    """本說明怎麼用。data = {product, chapters: [{name, url}], setup_url, roles: [{name, chapters}],
    updated}。"""
    kinds = set(data.get('kinds') or [])
    tail = '、'.join('「%s」' % n for k, n in (('status', '狀態速查'), ('messages', '訊息與狀況對照'))
                    if k in kinds)
    parts = ['<p>%s</p>' % esc(
        '這是「%s」的操作說明。每一章是一個工作領域：章首的「整體流程」用流程圖說明這一章的事情'
        '怎麼串起來%s，接著是日常操作（每個畫面一篇），最後是報表與設定畫面%s。' % (
            data.get('product') or '',
            '，「情境教學」用同一張示範單據從頭做到尾' if 'tutorial' in kinds else '',
            ('；章末有%s，遇到問題時可以直接查' % tail) if tail else ''))]
    steps = []
    if data.get('setup_url'):
        steps.append('<li>%s<a href="%s">%s</a>%s</li>' % (
            esc('先看「'), esc(data['setup_url']), esc('開始前必設定'), esc('」，確認系統已經設定好。')))
    chapters = [c for c in data.get('chapters') or [] if c.get('url')]
    if chapters:
        steps.append('<li>%s%s</li>' % (esc('依序看各章的「整體流程」：'), '、'.join(
            '<a href="%s">%s</a>' % (esc(c['url']), esc(c['name'])) for c in chapters)))
    steps.append('<li>%s</li>' % esc('要做某件事時，到對應的章節找那個畫面的說明，照步驟操作，'
                                     '做完對照「完成後會看到」確認結果。'))
    parts.append('<p><strong>%s</strong></p><ol>%s</ol>' % (esc('第一次使用'), ''.join(steps)))
    roles = [r for r in data.get('roles') or [] if r.get('chapters')]
    if roles:
        parts.append('<p><strong>%s</strong></p>' % esc('誰該看哪幾章'))
        parts.append(_table(['角色', '跟你最相關的章節'], [
            [esc(r['name']), esc('、'.join(r['chapters']))] for r in roles]))
    if data.get('updated'):
        parts.append('<p><em>%s</em></p>' % esc(
            '本說明的畫面都在實際系統上、以上表角色的帳號操作拍攝；畫面改版時會自動重拍。'
            '最近更新：%s。' % data['updated']))
    return '<div class="o_kb_guide o_kb_howto">%s</div>' % ''.join(parts)


def render_status(flows):
    """狀態速查。flows = [{name, steps: [{label, meaning, next, back, roles}]}]。"""
    parts = ['<p>%s</p>' % esc('單據停在某個狀態、不知道下一步要做什麼時，查這張表。')]
    for flow in flows:
        rows = []
        has_back = any(s.get('back') for s in flow['steps'])
        for s in flow['steps']:
            last = s is flow['steps'][-1]
            row = [esc(s['label']), esc(s.get('meaning') or '—'),
                   '<br/>'.join(esc(x) for x in s.get('next') or [])
                   or esc('（流程終點）' if last else '—')]
            if has_back:
                row.append('<br/>'.join(esc(x) for x in s.get('back') or []) or '—')
            row.append(esc('、'.join(s.get('roles') or [])) or '—')
            rows.append(row)
        parts.append('<p><strong>%s</strong></p>' % esc(flow['name']))
        parts.append(_table(['狀態', '意思', '怎麼往下一步'] + (['取消或退回'] if has_back else [])
                            + ['誰負責往下推'], rows))
    return '<div class="o_kb_guide o_kb_status">%s</div>' % ''.join(parts)


def render_messages(groups):
    """訊息與狀況對照。groups = [{name, items: [{message, when, cause, fix}]}]。"""
    parts = ['<p>%s</p>' % esc('操作時系統跳出下列訊息，先照「怎麼處理」做；訊息是系統畫面上的原文。')]
    for g in groups:
        rows = [[esc(i['message']), esc(i.get('when') or ''), esc(i.get('cause') or '—'),
                 esc(i.get('fix') or '—')] for i in g['items']]
        parts.append('<p><strong>%s</strong></p>' % esc(g['name']))
        parts.append(_table(['系統訊息', '什麼時候會出現', '為什麼', '怎麼處理'], rows))
    return '<div class="o_kb_guide o_kb_messages">%s</div>' % ''.join(parts)


#: 常見簡體字：AI 補的短文含這些字就不用（跟文章的文字檢查同一份精神）
_SIMPLIFIED = re.compile('[这为们说时发开关过还进单应个对会来么经现实务样点让认识计记设调导选择]')


def clean_short(text, limit=120):
    """AI 補的短文：去掉 HTML、截長度；含簡體字或技術欄位名就丟掉（回空字串）。"""
    t = re.sub(r'<[^>]+>', '', str(text or '')).strip()
    if not t or _SIMPLIFIED.search(t) or re.search(r'\b[a-z]+(?:_[a-z0-9]+)+\b', t):
        return ''
    return t[:limit]
