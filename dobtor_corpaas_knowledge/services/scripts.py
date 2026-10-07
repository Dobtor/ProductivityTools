# -*- coding: utf-8 -*-
"""送進 odoo shell 執行的腳本產生器。

每支腳本都 `print(MARK + json.dumps(...))` 回傳結果。除了明確標示「會 commit」的
（purge、seed、roles），其他一律結尾 rollback——黃金庫不能留下任何痕跡。
"""
import json
import os

MARK = '__CORPAAS_SHELL__:'

_HERE = os.path.dirname(os.path.abspath(__file__))


def _lib_source():
    """把 fingerprint_lib 的原始碼整段嵌進腳本：兩側用同一份定義。"""
    with open(os.path.join(_HERE, 'fingerprint_lib.py'), encoding='utf-8') as fh:
        return fh.read()


_HEAD = (
    "import json\n"
    "MARK = %r\n"
    "def _xid(rec):\n"
    "    return (rec.get_external_id() or {}).get(rec.id) or ''\n"
    # ★ 截圖與指紋必須同語言。黃金庫沒裝 zh_TW 時截圖本來就是英文，指紋也跟著用英文，
    #   否則 get_views 直接拋「Invalid language code」。
    "def _lang(code):\n"
    "    ok = env['res.lang'].sudo().search_count([('code', '=', code), ('active', '=', True)])\n"
    "    return code if ok else 'en_US'\n"
) % MARK


def inventory_script(modules, lang='zh_TW', official=()):
    """盤點功能點（唯讀）。

    ★ 以「畫面」為單位：一個視窗動作＝一個功能點；選單、按鈕（type=action）、智慧按鈕
      都只是走進這個畫面的「入口」（entries）。同一個畫面被三個選單打開仍是一筆，
      指紋、截圖、文章也都對著畫面。非視窗動作的選單（儀表板、client action）
      另成 kind=client：沒有模型、不算指紋。

    modules: 方案 BOM 的技術名清單——全部種類都盤。
    official: 範圍內的 Odoo 官方模組（不在 BOM 裡、相依或手動裝進來的）——只盤
      使用者會從選單走進去的畫面。技術選單（整條路徑上有一層只開給 技術功能／設定
      群組）不算；報表、按鈕、精靈、設定也不盤，否則一個 sale 就是上百個功能點，
      淹掉方案自己的功能。
    """
    return _HEAD + (
        "MODS = set(json.loads(%r))\n"
        "OFFICIAL = set(json.loads(%r)) - MODS\n"
        "LANG = _lang(%r)\n"
    ) % (json.dumps(sorted(modules)), json.dumps(sorted(official or ())), lang) + _INVENTORY_BODY


_INVENTORY_BODY = r"""
import xml.etree.ElementTree as ET
TECH = {'base.group_no_one', 'base.group_system', 'base.group_erp_manager'}
E = env(context=dict(env.context, lang=LANG, active_test=False))
Imd = E['ir.model.data'].sudo()
feats = {}

def _groups(recs):
    return sorted(filter(None, (_xid(g) for g in recs)))

def _ids(model, mods):
    return Imd.search([('model', '=', model), ('module', 'in', list(mods))])

def _technical(m):
    while m:
        g = set(_groups(m.groups_id))
        if g and g <= TECH:
            return True
        m = m.parent_id
    return False

def _feat(kind, anchor, module, **vals):
    d = feats.setdefault((module, kind, anchor), {
        'kind': kind, 'module': module, 'anchor': anchor, 'entries': []})
    for k, v in vals.items():
        if v and not d.get(k):
            d[k] = v
    return d

def _act_feature(act):
    axid = _xid(act)
    if not axid:
        return None
    return _feat('action', axid, axid.split('.', 1)[0], name=act.name,
                 model=act.res_model or '', view_mode=act.view_mode or '',
                 view_xmlid=_xid(act.view_id) if act.view_id else '',
                 action_xmlid=axid, groups=_groups(act.groups_id))

def _resolve_action(name):
    if not name:
        return None
    if name.isdigit():
        a = E['ir.actions.actions'].sudo().browse(int(name)).exists()
        return E[a.type].sudo().browse(a.id) if a and a.type in E else None
    if name.startswith('%(') and name.endswith(')d'):
        return E.ref(name[2:-2], raise_if_not_found=False)
    return None

# 選單 → 入口
for d in _ids('ir.ui.menu', MODS | OFFICIAL):
    m = E['ir.ui.menu'].browse(d.res_id).exists()
    if not m or not m.action:
        continue
    if d.module in OFFICIAL and _technical(m):
        continue
    act = m.action
    entry = {'kind': 'menu', 'anchor': d.module + '.' + d.name, 'module': d.module,
             'name': m.name, 'path': m.complete_name or m.name,
             'groups': _groups(m.groups_id)}
    if act._name == 'ir.actions.act_window':
        f = _act_feature(act)
    else:
        axid = _xid(act) or entry['anchor']
        f = _feat('client', axid, axid.split('.', 1)[0], name=m.name,
                  action_xmlid=_xid(act))
    if f is not None:
        f['entries'].append(entry)

# 方案模組自己的視窗動作（沒有選單、只從按鈕打開的也算畫面）
for d in _ids('ir.actions.act_window', MODS):
    a = E['ir.actions.act_window'].browse(d.res_id).exists()
    if a:
        _act_feature(a)

# 報表
for d in _ids('ir.actions.report', MODS):
    r = E['ir.actions.report'].browse(d.res_id).exists()
    if r:
        _feat('report', d.module + '.' + d.name, d.module, name=r.name,
              model=r.model or '', groups=_groups(r.groups_id))

# 按鈕：表單、清單、看板視圖（含繼承）裡的具名按鈕。
#   type=action → 那個畫面的入口（智慧按鈕／一般按鈕）；type=object → 按鈕功能點。
for d in _ids('ir.ui.view', MODS):
    v = E['ir.ui.view'].browse(d.res_id).exists()
    if not v or v.type not in ('form', 'list', 'kanban'):
        continue
    try:
        root = ET.fromstring(v.arch_db or '<x/>')
    except ET.ParseError:
        continue
    vx = d.module + '.' + d.name
    base = v
    while base.inherit_id and base.mode != 'primary':
        base = base.inherit_id
    for b in root.iter('button'):
        name = b.attrib.get('name')
        if not name:
            continue
        label = b.attrib.get('string') or b.attrib.get('title') or name
        groups = sorted(filter(None, (b.attrib.get('groups') or '').split(',')))
        anchor = '%s/button[%s]' % (vx, name)
        if b.attrib.get('type') == 'action':
            act = _resolve_action(name)
            if act is not None and act._name == 'ir.actions.act_window':
                f = _act_feature(act)
                if f is not None:
                    smart = 'oe_stat_button' in (b.attrib.get('class') or '')
                    f['entries'].append({
                        'kind': 'smart_button' if smart else 'button', 'anchor': anchor,
                        'module': d.module, 'name': label, 'path': _xid(base) or vx,
                        'groups': groups})
            continue
        _feat('button', anchor, d.module, name=label, model=v.model or '',
              view_xmlid=_xid(base), button_name=name, view_mode=v.type,
              button_type=b.attrib.get('type') or '', groups=groups)

# 精靈
for m in E['ir.model'].sudo().search([('transient', '=', True)]):
    mods = set((m.modules or '').replace(' ', '').split(','))
    hit = sorted(mods & MODS)
    if hit:
        _feat('wizard', m.model, hit[0], name=m.name, model=m.model)

# 設定：不在這裡盤。只有「已開啟」的參數型開關才是功能點（toggle_script，進階）；
#   沒勾的設定不屬於方案預設範圍。

# 前台：方案模組的網站選單
if 'website.menu' in E:
    for d in _ids('website.menu', MODS):
        wm = E['website.menu'].browse(d.res_id).exists()
        if wm and wm.url and wm.url not in ('/', '#'):
            _feat('route', wm.url, d.module, name=wm.name, menu_path=wm.name)

out = []
for d in feats.values():
    uniq = {}
    for e in d['entries']:
        uniq.setdefault((e['kind'], e['anchor']), e)  # 同一顆按鈕在一張視圖裡出現多次
    entries = sorted(uniq.values(), key=lambda e: (e['kind'] != 'menu', len(e['path'] or '')))
    if not d.get('menu_path') and entries and entries[0]['kind'] == 'menu':
        d['menu_path'] = entries[0]['path']
    d['entries'] = entries
    out.append(d)
env.cr.rollback()
print(MARK + json.dumps({'features': out}))
"""


def fingerprint_script(items, roles, lang='zh_TW'):
    """計算指紋（唯讀：暫存角色使用者建在交易內，結尾 rollback）。

    items: [{'key', 'model', 'views': [[view_xmlid_or_False, type], …],
             'elements': [...], 'menu_path', 'view_mode'}]
    roles: [{'code', 'groups': [xmlid, …]}]
    """
    return _lib_source() + "\n" + _HEAD + (
        "ITEMS = json.loads(%r)\n"
        "ROLES = json.loads(%r)\n"
        "LANG = _lang(%r)\n"
        "import uuid\n"
        "res = {}\n"
        "Users = env['res.users'].sudo().with_context(no_reset_password=True,\n"
        "    mail_create_nosubscribe=True, tracking_disable=True)\n"
        "users = {}\n"
        "for r in ROLES:\n"
        "    gids = []\n"
        "    for gx in r.get('groups') or []:\n"
        "        g = env.ref(gx, raise_if_not_found=False)\n"
        "        if g:\n"
        "            gids.append(g.id)\n"
        # ★ login 加亂數：萬一上一次的交易沒回滾乾淨，固定 login 會撞唯一鍵。
        "    users[r['code']] = Users.create({'name': 'kbfp ' + r['code'],\n"
        "        'login': 'kbfp_%%s_%%s' %% (r['code'], uuid.uuid4().hex[:8]),\n"
        "        'groups_id': [(6, 0, gids)]})\n"
        "Imd = env['ir.model.data'].sudo()\n"
        "V = env['ir.ui.view'].sudo()\n"
        "mods_of = {}\n"
        "parts_of = {}\n"
        "import xml.etree.ElementTree as ET\n"
        "for it in ITEMS:\n"
        "    per = {}\n"
        "    for code, u in users.items():\n"
        "        try:\n"
        "            Model = env[it['model']].with_user(u).with_context(lang=LANG)\n"
        "            views = []\n"
        "            for vx, vt in it.get('views') or [[False, 'form']]:\n"
        "                vid = env.ref(vx).id if vx else False\n"
        "                views.append((vid, vt))\n"
        "            data = Model.get_views(views)\n"
        "            archs = {vt: data['views'][vt]['arch'] for vt in data.get('views', {})}\n"
        # 畫面涉及的模組（主視圖＋所有繼承視圖），角色無關，每個功能點算一次
        "            if it['key'] not in mods_of:\n"
        "                vids = [v.get('id') for v in data.get('views', {}).values() if v.get('id')]\n"
        "                vs = V.browse(vids).exists()\n"
        "                vs |= vs._get_inheriting_views()\n"
        "                imds = Imd.search([('model', '=', 'ir.ui.view'), ('res_id', 'in', vs.ids)])\n"
        "                mods_of[it['key']] = sorted(set(imds.mapped('module')))\n"
        "                mod_by_view = {d.res_id: d.module for d in imds}\n"
        "                parts = {}\n"
        "                for iv in vs.filtered(lambda x: x.inherit_id):\n"
        "                    try:\n"
        "                        r = ET.fromstring(iv.arch_db or '<x/>')\n"
        "                    except ET.ParseError:\n"
        "                        continue\n"
        "                    els = parts.setdefault(mod_by_view.get(iv.id, ''), set())\n"
        "                    for n in r.iter():\n"
        "                        if n.tag in ('field', 'button') and n.attrib.get('name') \\\n"
        "                                and 'position' not in n.attrib:\n"
        "                            els.add('%%s:%%s' %% (n.tag, n.attrib['name']))\n"
        "                parts_of[it['key']] = {m: sorted(e) for m, e in parts.items() if m and e}\n"
        "            sh, found = scope_hash(archs, it.get('elements') or [],\n"
        "                                   it.get('menu_path') or '', it.get('view_mode') or '')\n"
        "            per[code] = {'form': form_hash(archs), 'scope': sh,\n"
        "                         'found': found, 'sig': signature(archs)}\n"
        "        except Exception as e:\n"
        "            per[code] = {'error': str(e)[:300]}\n"
        "    res[it['key']] = per\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps({'version': FINGERPRINT_VERSION, 'lang': LANG, 'items': res,\n"
        "                         'modules': mods_of, 'parts': parts_of}))\n"
    ) % (json.dumps(items), json.dumps(roles), lang)


#: D1：清除時不動的模型前綴（系統、設定、身分）。
PURGE_SKIP_PREFIXES = (
    'ir.', 'base', 'bus.', 'res.users', 'res.groups', 'res.company', 'res.lang',
    'res.currency', 'res.country', 'res.partner.title', 'res.partner.industry',
    'res.config', 'res.bank', 'decimal.precision', 'uom.', 'mail.template',
    'mail.alias', 'mail.message.subtype', 'mail.activity.type', 'web_editor.',
    'website', 'theme.', 'report.', 'digest.', 'iap.', 'auth_', 'spreadsheet',
)


#: 設定類模型：D1 清除時保留、截圖前檢查時放行。
#: ☠️ 這些記錄多半是模組在安裝或建倉庫時「以程式建立」的，沒有自己的 xmlid：
#:   清掉補貨規則／作業類型後，說明庫連確認銷售訂單都失敗（找不到補貨規則）；
#:   截圖檢查又把路線、規則、作業類型、郵件別名畫面判成「非示範資料」（實機 6 張）。
#:   它們是設定，不含客戶個資。
CONFIG_MODELS = (
    'stock.warehouse', 'stock.location', 'stock.route', 'stock.rule', 'stock.picking.type',
    'stock.putaway.rule', 'stock.storage.category', 'stock.package.type',
    'account.journal', 'account.account', 'account.tax', 'account.tax.group',
    'account.tax.repartition.line', 'account.fiscal.position', 'account.payment.term',
    'account.payment.term.line', 'account.payment.method', 'account.payment.method.line',
    'account.reconcile.model', 'account.analytic.plan', 'res.currency', 'res.company',
    'uom.uom', 'uom.category', 'product.category', 'product.pricelist', 'mail.alias',
    'mail.activity.type', 'mail.activity.plan', 'crm.team', 'delivery.carrier',
    'payment.provider', 'payment.method', 'res.lang', 'res.country', 'res.country.state',
)


def purge_script(models):
    """D1：刪除客戶的業務記錄（會 commit）。回報刪除數、殘留、匿名化的使用者數。

    ★ 只清「要拍的畫面會用到的業務模型」（models：方案功能點的模型＋情境示範資料的
      模型＋res.partner）。☠️ 曾經掃全部模型、刪掉所有沒有 xmlid 的記錄：模組安裝時
      以程式建立的設定明細（稅的分配行、付款條件明細、工作時間、產品變體、PDF 欄位）
      都沒有自己的 xmlid，全被刪掉，說明庫的設定當場壞掉。
    ★ 保留：模組 xmlid、__doc_scenario_*、以及「必填且串聯刪除的上層」是保留記錄的明細。
    ★ 其他畫面上的漏網之魚由截圖前檢查（gate_script）擋下。
    """
    return _HEAD + (
        "SKIP = %r\n"
        "TARGET = [m for m in json.loads(%r) if m in env and not m.startswith(SKIP)]\n"
        "mods = set(env['ir.module.module'].sudo().search([('state', '=', 'installed')]).mapped('name'))\n"
        "Imd = env['ir.model.data'].sudo()\n"
        "keep_partner = set(env['res.users'].sudo().with_context(active_test=False).search([]).mapped('partner_id').ids)\n"
        "keep_partner |= set(env['res.company'].sudo().search([]).mapped('partner_id').ids)\n"
        "def _kept_ids(name, ids):\n"
        "    keep = set(Imd.search([('model', '=', name), ('res_id', 'in', ids),\n"
        "        '|', ('module', 'in', list(mods)), ('module', '=like', '__doc_scenario_%%')]).mapped('res_id'))\n"
        "    if name == 'res.partner':\n"
        "        keep |= keep_partner\n"
        "    Model = env[name].sudo().with_context(active_test=False)\n"
        "    parents = [f for f in Model._fields.values() if f.type == 'many2one' and f.required\n"
        "               and f.ondelete == 'cascade' and f.store]\n"
        "    for f in parents:\n"
        "        rows = Model.browse([i for i in ids if i not in keep]).read([f.name])\n"
        "        pids = [r[f.name][0] for r in rows if r[f.name]]\n"
        "        pkeep = set(Imd.search([('model', '=', f.comodel_name), ('res_id', 'in', pids),\n"
        "            ('module', 'in', list(mods))]).mapped('res_id'))\n"
        "        keep |= {r['id'] for r in rows if r[f.name] and r[f.name][0] in pkeep}\n"
        "    return keep\n"
        "deleted, residual = {}, {}\n"
        "for _pass in range(3):\n"
        "    for name in TARGET:\n"
        "        Model = env[name].sudo().with_context(active_test=False, tracking_disable=True)\n"
        "        if Model._abstract or not Model._auto:\n"
        "            continue\n"
        "        ids = Model.search([]).ids\n"
        "        if not ids:\n"
        "            continue\n"
        "        keep = _kept_ids(name, ids)\n"
        "        for rid in [i for i in ids if i not in keep]:\n"
        "            try:\n"
        "                with env.cr.savepoint():\n"
        "                    Model.browse(rid).unlink()\n"
        "                deleted[name] = deleted.get(name, 0) + 1\n"
        "            except Exception:\n"
        "                pass\n"
        "for name in TARGET:\n"
        "    Model = env[name].sudo().with_context(active_test=False)\n"
        "    if Model._abstract or not Model._auto:\n"
        "        continue\n"
        "    ids = Model.search([]).ids\n"
        "    left = [i for i in ids if i not in _kept_ids(name, ids)] if ids else []\n"
        "    if left:\n"
        "        residual[name] = len(left)\n"
        # ★ 使用者刪不掉（外鍵），但客戶員工的姓名會出現在「業務員」「負責人」欄位上：
        #   沒有模組 xmlid 的使用者一律匿名化＋封存；其 partner 只匿名化——
        #   ☠️ Odoo 不准在同一步把「仍連著啟用中使用者」的 partner 封存（RedirectWarning）。
        "anon = 0\n"
        "Users = env['res.users'].sudo().with_context(active_test=False)\n"
        "keep_u = set(Imd.search([('model', '=', 'res.users'), '|', ('module', 'in', list(mods)),\n"
        "    ('module', '=like', '__doc_scenario_%%')]).mapped('res_id'))\n"
        "for u in Users.search([('id', 'not in', list(keep_u))]):\n"
        "    if u.id in (1, 2):\n"
        "        continue\n"
        "    try:\n"
        "        with env.cr.savepoint():\n"
        "            label = '已移除使用者 %%s' %% u.id\n"
        "            u.partner_id.write({'name': label, 'email': False, 'phone': False,\n"
        "                                'mobile': False, 'street': False, 'street2': False})\n"
        "            u.write({'login': 'removed_%%s' %% u.id, 'active': False})\n"
        "        anon += 1\n"
        "    except Exception:\n"
        "        pass\n"
        "env.cr.commit()\n"
        "print(MARK + json.dumps({'deleted': deleted, 'residual': residual, 'anonymized_users': anon}))\n"
    ) % (PURGE_SKIP_PREFIXES + ('mail.',), json.dumps(sorted(set(models or []))))


def seed_script(module, records, roles, password):
    """重播情境示範資料（會 commit）。

    records: [{'xmlid': 'name', 'model', 'values': {...}}]，values 裡
      '__ref__:<xmlid>' 會解析成 id；list of refs 解析成 [(6,0,ids)]。
      xmlid 不含點時自動加上 module 前綴。
      動作：{'xmlid': '<步驟名>', 'model', 'call': 'action_confirm', 'ref': '<xmlid>'}
        依序呼叫記錄的方法（確認訂單、過帳發票…）；方法名只允許 action_／button_ 開頭。
        ☠️ 只能建記錄時，示範庫裡沒有已確認訂單、已過帳發票、已完成移動，
          銷售／採購分析、日記帳項目這類畫面全是空的（實機約 35 張空白引導頁）。
    roles: [{'code', 'name', 'groups': [...]}] → 建 res.users（xmlid user_<code>）。
      ★ 先建帳號再建記錄：單據才能指定給角色帳號（__ref__:user_sales），
        否則「我的報價單」這類預設篩選拍出來是空的。
    """
    return _HEAD + (
        "import re\n"
        "MODULE = %r\n"
        "RECORDS = json.loads(%r)\n"
        "ROLES = json.loads(%r)\n"
        "PASSWORD = %r\n"
        "def _full(x):\n"
        "    return x if '.' in x else MODULE + '.' + x\n"
        "def _resolve(v):\n"
        "    if isinstance(v, str) and v.startswith('__ref__:'):\n"
        "        return env.ref(_full(v[8:])).id\n"
        "    if isinstance(v, list) and v and all(isinstance(x, str) and x.startswith('__ref__:') for x in v):\n"
        "        return [(6, 0, [env.ref(_full(x[8:])).id for x in v])]\n"
        "    return v\n"
        "done, errors = 0, []\n"
        "users = {}\n"
        "for r in ROLES:\n"
        "    try:\n"
        "        with env.cr.savepoint():\n"
        "            gids = [env.ref(g).id for g in r.get('groups') or [] if env.ref(g, raise_if_not_found=False)]\n"
        "            u = env['res.users'].sudo().with_context(no_reset_password=True)._load_records([\n"
        "                {'xml_id': MODULE + '.user_' + r['code'], 'noupdate': False, 'values': {\n"
        "                    'name': r.get('name') or r['code'], 'login': 'doc_' + r['code'],\n"
        "                    'lang': _lang('zh_TW'), 'tz': 'Asia/Taipei', 'groups_id': [(6, 0, gids)]}}])\n"
        "            u.password = PASSWORD\n"
        "            users[r['code']] = u.login\n"
        "    except Exception as e:\n"
        "        errors.append({'xmlid': 'user_' + r['code'], 'model': 'res.users', 'error': str(e)[:500]})\n"
        "for rec in RECORDS:\n"
        "    try:\n"
        "        with env.cr.savepoint():\n"
        "            if rec.get('call'):\n"
        "                if not re.match(r'^(action|button)_[a-z0-9_]+$', rec['call']):\n"
        "                    raise ValueError('不允許的方法：%%s' %% rec['call'])\n"
        "                target = env.ref(_full(rec['ref'])).sudo().with_context(\n"
        "                    tracking_disable=True, mail_create_nolog=True, mail_notrack=True)\n"
        "                getattr(target, rec['call'])()\n"
        "            else:\n"
        "                vals = {k: _resolve(v) for k, v in (rec.get('values') or {}).items()}\n"
        "                env[rec['model']].sudo().with_context(tracking_disable=True,\n"
        "                    mail_create_nolog=True, no_reset_password=True)._load_records([\n"
        "                    {'xml_id': _full(rec['xmlid']), 'values': vals, 'noupdate': False}])\n"
        "        done += 1\n"
        "    except Exception as e:\n"
        "        errors.append({'xmlid': rec.get('xmlid'), 'model': rec.get('model'), 'error': str(e)[:500]})\n"
        "env.cr.commit()\n"
        "print(MARK + json.dumps({'done': done, 'errors': errors, 'users': users}))\n"
    ) % (module, json.dumps(records), json.dumps(roles), password)


def gate_script(pairs, since, refs=None, allow=CONFIG_MODELS):
    """D1 截圖前檢查。

    pairs: {model: [ids]}；refs: {"model|field": [ids]}（many2one／x2many 的值，
    comodel 在這裡查）；since: 清除完成時間（字串）——之後才建立的都是我們放的
    （示範資料與拍攝過程產生），允許。
    允許：模組 xmlid、__doc_scenario_* xmlid、清除之後才建立，或設定類模型（allow）。
    """
    return _HEAD + (
        "PAIRS = json.loads(%r)\n"
        "REFS = json.loads(%r)\n"
        "SINCE = %r\n"
        "ALLOW = set(json.loads(%r))\n"
        # 鍵的格式：model|field，或明細的 model|x2many欄位>明細欄位（可多層）
        "for key, ids in REFS.items():\n"
        "    model, _, path = key.partition('|')\n"
        "    comodel = model if model in env else None\n"
        "    for part in path.split('>'):\n"
        "        f = env[comodel]._fields.get(part) if comodel else None\n"
        "        comodel = f.comodel_name if f is not None and f.relational else None\n"
        "    if comodel:\n"
        "        PAIRS.setdefault(comodel, [])\n"
        "        PAIRS[comodel] = sorted(set(PAIRS[comodel]) | set(ids))\n"
        "mods = set(env['ir.module.module'].sudo().search([('state', '=', 'installed')]).mapped('name'))\n"
        "Imd = env['ir.model.data'].sudo()\n"
        "bad = []\n"
        "for model, ids in PAIRS.items():\n"
        "    if model not in env or not ids or model in ALLOW:\n"
        "        continue\n"
        "    ok = set(Imd.search([('model', '=', model), ('res_id', 'in', ids),\n"
        "        '|', ('module', 'in', list(mods)), ('module', '=like', '__doc_scenario_%%')]).mapped('res_id'))\n"
        "    rest = [i for i in ids if i not in ok]\n"
        "    if rest and 'create_date' in env[model]._fields:\n"
        "        recent = env[model].sudo().with_context(active_test=False).search(\n"
        "            [('id', 'in', rest), ('create_date', '>=', SINCE)]).ids\n"
        "        rest = [i for i in rest if i not in recent]\n"
        "    bad.extend([model, i] for i in rest)\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps({'bad': bad}))\n"
    ) % (json.dumps(pairs), json.dumps(refs or {}), since, json.dumps(list(allow or ())))


def fields_script(models):
    """示範資料起草用：各模型的欄位定義（唯讀）。只回必填、關聯、選項等 AI 需要的部分。"""
    return _HEAD + (
        "MODELS = json.loads(%r)\n"
        "out = {}\n"
        "for m in MODELS:\n"
        "    if m not in env:\n"
        "        continue\n"
        "    info = {}\n"
        "    for name, f in env[m]._fields.items():\n"
        "        if not f.store or f.compute or name in ('id', 'create_uid', 'write_uid',\n"
        "                                                  'create_date', 'write_date'):\n"
        "            continue\n"
        "        d = {'type': f.type, 'string': f.string}\n"
        "        if f.required:\n"
        "            d['required'] = True\n"
        "        if f.relational:\n"
        "            d['relation'] = f.comodel_name\n"
        "        if f.type == 'selection' and isinstance(f.selection, list):\n"
        "            d['selection'] = [k for k, _v in f.selection][:20]\n"
        "        info[name] = d\n"
        "    out[m] = info\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps(out))\n"
    ) % (json.dumps(sorted(set(models))),)


def groups_script():
    """AI 圈選提議角色用：黃金庫裡使用者看得到的應用權限群組（唯讀）。

    只取有 xmlid、分類可見（設定頁「使用者」表單上那些下拉）的群組。"""
    return _HEAD + (
        "out = []\n"
        "for g in env['res.groups'].sudo().search([('category_id.visible', '=', True)]):\n"
        "    x = _xid(g)\n"
        "    if x:\n"
        "        out.append({'xmlid': x, 'name': g.name, 'app': g.category_id.name})\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps(out))\n")


def screen_access_script(actions, roles):
    """權限缺口修補用：每個選單動作哪些角色進得去（唯讀）。

    actions: [動作 xmlid]；roles: {角色代碼: [群組 xmlid]}。
    判斷：角色（含隱含群組）要通過選單的群組限制，而且對動作的模型有讀取權限。
    回傳 {動作 xmlid: [進得去的角色代碼]}。"""
    return _HEAD + (
        "ACTIONS = json.loads(%r)\n"
        "ROLES = json.loads(%r)\n"
        "user_grp = env.ref('base.group_user')\n"
        "implied = {}\n"
        "for code, xids in ROLES.items():\n"
        "    gs = env['res.groups']\n"
        "    for x in xids:\n"
        "        g = env.ref(x, raise_if_not_found=False)\n"
        "        if g and g._name == 'res.groups':\n"
        "            gs |= g\n"
        "    gs |= user_grp\n"
        "    implied[code] = set((gs | gs.trans_implied_ids).ids)\n"
        "out = {}\n"
        "for xid in ACTIONS:\n"
        "    act = env.ref(xid, raise_if_not_found=False)\n"
        "    if not act or act._name != 'ir.actions.act_window' or act.res_model not in env:\n"
        "        continue\n"
        "    menus = env['ir.ui.menu'].sudo().with_context(active_test=False).search(\n"
        "        [('action', '=', '%%s,%%s' %% (act._name, act.id))])\n"
        "    need_menu = []\n"
        "    for m in menus:\n"
        "        chain, cur = set(), m\n"
        "        while cur:\n"
        "            if cur.groups_id:\n"
        "                chain.add(frozenset(cur.groups_id.ids))\n"
        "            cur = cur.parent_id\n"
        "        need_menu.append(chain)\n"
        "    acl = env['ir.model.access'].sudo().search([('model_id.model', '=', act.res_model),\n"
        "                                                ('perm_read', '=', True)])\n"
        "    acl_global = any(not a.group_id for a in acl)\n"
        "    acl_groups = set(acl.mapped('group_id').ids)\n"
        "    ok = []\n"
        "    for code, gids in implied.items():\n"
        "        if not (acl_global or gids & acl_groups):\n"
        "            continue\n"
        "        if need_menu and not any(all(gids & set(g) for g in chain) for chain in need_menu):\n"
        "            continue\n"
        "        ok.append(code)\n"
        "    out[xid] = ok\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps(out))\n"
    ) % (json.dumps(actions), json.dumps(roles))


def data_probe_script(items):
    """送審前重播檢查（A3）：各選單動作打開後有幾筆資料（唯讀）。

    items: [[功能鍵, 動作 xmlid]]。以管理者身分、套用動作本身的 domain 計數；
    畫面的預設篩選（search_default_*）不套用——它們多半依登入者，換角色就不同。
    回傳 {功能鍵: 筆數}；動作不存在或不是視窗動作的略過，算不出來的記 -1。
    """
    return _HEAD + (
        "from odoo.tools.safe_eval import safe_eval\n"
        "ITEMS = json.loads(%r)\n"
        "base = env['ir.actions.actions']._get_eval_context()\n"
        "cids = [env.company.id]\n"
        "base.update({'context': dict(env.context, allowed_company_ids=cids),\n"
        "             'allowed_company_ids': cids, 'active_id': False, 'active_ids': []})\n"
        "out = {}\n"
        "for key, xid in ITEMS:\n"
        "    act = env.ref(xid, raise_if_not_found=False)\n"
        "    if not act or act._name != 'ir.actions.act_window' or act.res_model not in env:\n"
        "        continue\n"
        "    try:\n"
        "        dom = safe_eval(act.domain or '[]', dict(base))\n"
        "        out[key] = env[act.res_model].sudo().with_context(active_test=True).search_count(dom)\n"
        "    except Exception:\n"
        "        out[key] = -1\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps(out))\n"
    ) % (json.dumps(items),)


def flow_script(models, lang='zh_TW'):
    """推導任務流程（唯讀，不執行任何按鈕）。

    每個有狀態列（widget="statusbar"）的模型：
      · 步驟：狀態欄位的選項（many2one 的階段用名稱，跨庫才比得起來）；
      · 按鈕在哪些狀態看得到：把 invisible 運算式逐一代入狀態值求值，運算式還牽涉其他
        欄位的標「條件可見」；
      · 按鈕會轉到哪個狀態：AST 讀按鈕方法的原始碼，找寫入狀態欄位的常數（追一層
        self 上的方法呼叫）；many2one 階段不推（引用的是 xmlid／記錄）；
      · 按鈕打開什麼：type=action 的動作模型，或方法原始碼裡的 'res_model' 常數；
      · 報表：綁在這個模型上的 ir.actions.report。
    """
    return _HEAD + (
        "MODELS = json.loads(%r)\n"
        "LANG = _lang(%r)\n"
    ) % (json.dumps(sorted(models)), lang) + _FLOW_BODY


_FLOW_BODY = r"""
import ast
import inspect
import textwrap
import xml.etree.ElementTree as ET
E = env(context=dict(env.context, lang=LANG))
SAFE_NAMES = {'True', 'False', 'None', 'context', 'uid', 'parent', 'id'}

def _expr_names(expr):
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return None
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}

class _Ctx(dict):
    def __missing__(self, key):
        return None

def _visible_states(expr, fname, values):
    # 回傳 (看得到的狀態, 是否條件可見)；None 表示每個狀態都看得到
    if not expr:
        return None, False
    names = _expr_names(expr)
    if names is None:
        return None, True
    others = names - {fname} - SAFE_NAMES
    vis = []
    for v in values:
        ctx = _Ctx({fname: v, 'True': True, 'False': False, 'None': None, 'context': {}})
        try:
            hidden = eval(compile(expr, '<invisible>', 'eval'), {'__builtins__': {}}, ctx)
        except Exception:
            return None, True
        if not hidden:
            vis.append(v)
    if fname not in names:
        return (None if vis else []), bool(others)
    return vis, bool(others)

def _method_asts(model_cls, name):
    # 整條 MRO 上每一個定義了這個方法的類別：覆寫多半只有 super()，真正寫狀態的在原始模組
    out = []
    for klass in model_cls.__mro__:
        meth = klass.__dict__.get(name)
        if meth is None or not callable(meth):
            continue
        try:
            out.append(ast.parse(textwrap.dedent(inspect.getsource(meth))))
        except (OSError, TypeError, SyntaxError, IndentationError):
            continue
    return out

def _targets(model_cls, name, fname, values, depth=1, seen=None):
    seen = seen if seen is not None else set()
    if name in seen:
        return set(), set()
    seen.add(name)
    found, opens = set(), set()
    nodes = [n for tree in _method_asts(model_cls, name) for n in ast.walk(tree)]
    for node in nodes:
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    if k.value == fname and v.value in values:
                        found.add(v.value)
                    if k.value == 'res_model' and isinstance(v.value, str):
                        opens.add(v.value)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == fname \
                        and isinstance(node.value, ast.Constant) and node.value.value in values:
                    found.add(node.value.value)
        elif isinstance(node, ast.Call) and depth > 0:
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                    and fn.value.id in ('self', 'rec', 'record', 'order', 'records') \
                    and isinstance(fn.attr, str):
                f2, o2 = _targets(model_cls, fn.attr, fname, values, depth - 1, seen)
                found |= f2
                opens |= o2
    return found, opens

out = {}
for model in MODELS:
    if model not in E:
        continue
    M = E[model].sudo()
    try:
        arch = M.get_views([(False, 'form')])['views']['form']['arch']
        root = ET.fromstring(arch)
    except Exception:
        continue
    sb = next((n for n in root.iter('field') if n.attrib.get('widget') == 'statusbar'), None)
    if sb is None:
        continue
    fname = sb.attrib.get('name')
    field = M._fields.get(fname)
    if field is None:
        continue
    if field.type == 'selection':
        sel = field._description_selection(E)
        steps = [{'value': k, 'label': lbl} for k, lbl in sel]
        values = [k for k, _l in sel]
        static = True
    elif field.type == 'many2one':
        Stage = E[field.comodel_name].sudo()
        recs = Stage.search([], limit=40)
        steps = [{'value': r.display_name, 'label': r.display_name} for r in recs]
        values = [s['value'] for s in steps]
        static = False
    else:
        continue
    visible_bar = [v.strip() for v in (sb.attrib.get('statusbar_visible') or '').split(',')
                   if v.strip()]
    buttons = []
    seen_btn = set()
    for b in root.iter('button'):
        name = b.attrib.get('name')
        btype = b.attrib.get('type') or ''
        if not name or name in seen_btn or btype not in ('object', 'action'):
            continue
        seen_btn.add(name)
        vis, cond = _visible_states(b.attrib.get('invisible'), fname, values) \
            if static else (None, bool(b.attrib.get('invisible')))
        if vis == []:
            continue  # 任何狀態都看不到
        targets, opens = set(), set()
        if btype == 'object':
            if static:
                targets, opens = _targets(type(M), name, fname, set(values))
            else:
                _t, opens = _targets(type(M), name, fname, set())
        elif name.isdigit():
            a = E['ir.actions.actions'].sudo().browse(int(name)).exists()
            if a and a.type == 'ir.actions.act_window':
                res_model = E['ir.actions.act_window'].sudo().browse(a.id).res_model
                if res_model:
                    opens.add(res_model)
        buttons.append({'name': name, 'type': btype,
                        'label': b.attrib.get('string') or b.attrib.get('title') or name,
                        'visible': vis, 'conditional': cond,
                        'targets': sorted(targets), 'opens': sorted(opens - {model})})
    reports = [_xid(r) for r in E['ir.actions.report'].sudo().search([('model', '=', model)])
               if _xid(r)]
    out[model] = {'field': fname, 'field_type': field.type, 'steps': steps,
                  'statusbar_visible': visible_bar, 'buttons': buttons, 'reports': reports,
                  'model_name': E['ir.model']._get(model).name}
env.cr.rollback()
print(MARK + json.dumps({'flows': out}))
"""


def toggle_script(scope, lang='zh_TW'):
    """盤點設定開關（唯讀）。只回「已開啟」的：module_ 已裝、group_ 已勾、參數不是預設值。

    scope: 方案範圍內的模組（BOM ∪ 範圍內官方模組）。開關的「提供者」不在範圍內的不收：
      安裝模組型看目標模組，其他看定義設定欄位的模組。
    另外回傳「沒勾的群組開關」的群組——受它控制的畫面不屬於方案預設範圍，盤點要排除。
    """
    return _HEAD + (
        "SCOPE = set(json.loads(%r))\n"
        "LANG = _lang(%r)\n"
    ) % (json.dumps(sorted(scope)), lang) + _TOGGLE_BODY


_TOGGLE_BODY = r"""
import ast
import os
import xml.etree.ElementTree as ET
from odoo.modules.module import get_module_path
E = env(context=dict(env.context, lang=LANG))
S = E['res.config.settings'].sudo()
Imd = E['ir.model.data'].sudo()
Mod = E['ir.module.module'].sudo()
cls = S._get_classified_fields()
values = S.default_get(list(S._fields))

# 設定頁結構：欄位 → (app, block, setting) 標題、說明、官方文件
meta = {}
try:
    arch = S.get_views([(False, 'form')])['views']['form']['arch']
    root = ET.fromstring(arch)
    parent = {c: p for p in root.iter() for c in p}
    for f in root.iter('field'):
        name = f.attrib.get('name')
        if not name or name in meta:
            continue
        app = block = setting = None
        cur = parent.get(f)
        while cur is not None:
            if cur.tag == 'setting' and setting is None:
                setting = cur
            elif cur.tag == 'block' and block is None:
                block = cur
            elif cur.tag == 'app' and app is None:
                app = cur
            cur = parent.get(cur)
        parts = [x for x in (
            app.attrib.get('string') if app is not None else None,
            block.attrib.get('title') if block is not None else None,
            (setting.attrib.get('string') if setting is not None else None)) if x]
        meta[name] = {
            'app': app.attrib.get('name') if app is not None else '',
            'path': parts,
            'label': setting.attrib.get('string') if setting is not None and setting.attrib.get('string') else '',
            'help': setting.attrib.get('help') if setting is not None else '',
            'doc': setting.attrib.get('documentation') if setting is not None else '',
        }
except Exception:
    pass

def _field_module(name):
    return getattr(S._fields[name], '_module', '') or ''

def _label(name):
    m = meta.get(name) or {}
    return m.get('label') or S._fields[name].string or name

def _base(name, kind, target, provider):
    m = meta.get(name) or {}
    path = list(m.get('path') or [])
    if not path or path[-1] != _label(name):
        path.append(_label(name))
    return {'name': name, 'kind': kind, 'target': target, 'module': provider,
            'defined_in': _field_module(name), 'label': _label(name),
            'help': m.get('help') or S._fields[name].help or '',
            'path': path, 'doc': m.get('doc') or '', 'app': m.get('app') or ''}

out, off_groups = [], []
installed = Mod.search([('state', '=', 'installed')])
graph = {m.name: m.dependencies_id.mapped('name') for m in installed}

# 安裝模組型
for mod in cls['module']:
    name = 'module_' + mod.name
    if mod.state != 'installed' or mod.name not in SCOPE:
        continue
    t = _base(name, 'module', mod.name, mod.name)
    t['downstream'] = sorted(mod.downstream_dependencies().filtered(
        lambda m: m.state == 'installed').mapped('name'))
    t['value'] = 'on'
    out.append(t)

# 開啟群組型
def _gated(xid):
    els, menus = [], []
    V = E['ir.ui.view'].sudo()
    for v in V.search([('arch_db', 'ilike', xid)]):
        try:
            r = ET.fromstring(v.arch_db or '<x/>')
        except ET.ParseError:
            continue
        base = v
        while base.inherit_id and base.mode != 'primary':
            base = base.inherit_id
        vmod = (Imd.search([('model', '=', 'ir.ui.view'), ('res_id', '=', v.id)], limit=1).module
                or '')
        for n in r.iter():
            g = [x.strip() for x in (n.attrib.get('groups') or '').split(',')]
            if xid in g and n.tag in ('field', 'button', 'page') and n.attrib.get('name'):
                els.append({'model': v.model or '', 'view': _xid(base),
                            'element': '%s:%s' % (n.tag, n.attrib['name']), 'module': vmod})
    return els

for name, groups, implied in cls['group']:
    xid = _xid(implied)
    if not xid:
        continue
    on = bool(values.get(name))
    if not on:
        off_groups.append(xid)
        continue
    provider = _field_module(name)
    if provider not in SCOPE:
        continue
    t = _base(name, 'group', xid, provider)
    t['value'] = 'on'
    t['elements'] = _gated(xid)
    out.append(t)

# 參數型：config_parameter、default_、與公司相關的可寫欄位；只收「不是預設值」的
def _default_of(field):
    d = field.default
    try:
        return d(S) if callable(d) else d
    except Exception:
        return None

def _is_set(field, val):
    if field.type == 'boolean':
        return bool(val)
    if val in (False, None, '', 0, 0.0):
        return False
    dv = _default_of(field)
    if field.type == 'many2one':
        dv = getattr(dv, 'id', dv)
        val = getattr(val, 'id', val)
    return val != dv

param_names = [(n, key) for n, key in cls['config']]
param_names += [(n, None) for n, _m, _f in cls['default']]
param_names += [(n, None) for n in cls['other']
                if S._fields[n].related and not S._fields[n].readonly
                and S._fields[n].type in ('boolean', 'selection', 'integer', 'float', 'char', 'many2one')]
by_key = {}
for name, key in param_names:
    field = S._fields[name]
    provider = _field_module(name)
    if provider not in SCOPE or not _is_set(field, values.get(name)):
        continue
    val = values.get(name)
    if field.type == 'selection':
        val = dict(field._description_selection(E)).get(val, val)
    elif field.type == 'many2one' and val:
        val = E[field.comodel_name].browse(getattr(val, 'id', val)).display_name
    t = _base(name, 'param', key or name, provider)
    t['value'] = str(val)[:80]
    t['models'] = []
    out.append(t)
    if key:
        by_key[key] = t

# 參數會影響哪些模型：在範圍內模組的原始碼裡找讀取這個 key 的類別（_name／_inherit）
if by_key:
    for mod in sorted(SCOPE):
        path = get_module_path(mod, display_warning=False)
        if not path:
            continue
        for dirpath, _dirs, files in os.walk(path):
            if '/tests' in dirpath or '/migrations' in dirpath:
                continue
            for fn in files:
                if not fn.endswith('.py'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    src = open(fp, encoding='utf-8').read()
                except Exception:
                    continue
                keys = [k for k in by_key if k in src]
                if not keys:
                    continue
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    hit = {c.value for c in ast.walk(node)
                           if isinstance(c, ast.Constant) and c.value in by_key}
                    if not hit:
                        continue
                    models = []
                    for st in node.body:
                        if isinstance(st, ast.Assign) and any(
                                isinstance(tg, ast.Name) and tg.id in ('_name', '_inherit')
                                for tg in st.targets):
                            v = st.value
                            vals = [v] if isinstance(v, ast.Constant) else getattr(v, 'elts', [])
                            models += [x.value for x in vals if isinstance(x, ast.Constant)
                                       and isinstance(x.value, str)]
                    for k in hit:
                        for m in models:
                            if m not in by_key[k]['models'] and m != 'res.config.settings':
                                by_key[k]['models'].append(m)

env.cr.rollback()
print(MARK + json.dumps({'toggles': out, 'off_groups': off_groups, 'graph': graph}))
"""


def analysis_script(modules, official=(), lang='zh_TW'):
    """一次 odoo shell 跑完「盤點＋設定開關＋流程」（唯讀）。

    ★ 每一次 odoo shell 都要重新載入整個 registry（幾百個模組，15–40 秒），而且是在母體
      容器裡多開一個 Odoo 程序。分開跑三支腳本＝三次載入；合併後只載入一次。
    三支腳本的內容不變，只把各自的 print(MARK + …) 收集起來、最後合併輸出一次：
      features（盤點）、toggles／off_groups／graph（開關）、flows（流程）。
    流程的模型取自這次盤點出來的畫面。
    """
    scope = sorted(set(modules) | set(official or ()))
    return _HEAD + (
        "MODS = set(json.loads(%r))\n"
        "OFFICIAL = set(json.loads(%r)) - MODS\n"
        "SCOPE = set(json.loads(%r))\n"
        "LANG = _lang(%r)\n"
        "__OUT = {}\n"
        "__print = print\n"
        "def print(s):\n"
        "    if isinstance(s, str) and s.startswith(MARK):\n"
        "        __OUT.update(json.loads(s[len(MARK):]))\n"
        "    else:\n"
        "        __print(s)\n"
    ) % (json.dumps(sorted(modules)), json.dumps(sorted(official or ())), json.dumps(scope),
         lang) + _INVENTORY_BODY + (
        "\nMODELS = sorted({d.get('model') for d in __OUT.get('features') or []\n"
        "                  if d.get('kind') == 'action' and d.get('model')})\n"
    ) + _TOGGLE_BODY + _FLOW_BODY + (
        "\n__print(MARK + json.dumps(__OUT))\n"
    )
