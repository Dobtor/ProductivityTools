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


def inventory_script(modules, lang='zh_TW'):
    """盤點功能點（唯讀）。modules: 方案 BOM 的技術名清單。"""
    return _HEAD + (
        "MODS = set(%r)\n"
        "LANG = _lang(%r)\n"
        "E = env(context=dict(env.context, lang=LANG, active_test=False))\n"
        "out = []\n"
        "def _mod(xid):\n"
        "    return xid.split('.', 1)[0] if xid else ''\n"
        "def _groups(recs):\n"
        "    return sorted(filter(None, (_xid(g) for g in recs)))\n"
        "Imd = E['ir.model.data'].sudo()\n"
        "def _ids(model):\n"
        "    return Imd.search([('model', '=', model), ('module', 'in', list(MODS))])\n"
        # 選單
        "for d in _ids('ir.ui.menu'):\n"
        "    m = E['ir.ui.menu'].browse(d.res_id).exists()\n"
        "    if not m or not m.action:\n"
        "        continue\n"
        "    act = m.action\n"
        "    xid = d.module + '.' + d.name\n"
        "    out.append({'kind': 'menu', 'module': d.module, 'anchor': xid,\n"
        "        'name': m.name, 'menu_path': m.complete_name or m.name,\n"
        "        'model': getattr(act, 'res_model', '') or '',\n"
        "        'view_mode': getattr(act, 'view_mode', '') or '',\n"
        "        'action_xmlid': _xid(act), 'groups': _groups(m.groups_id)})\n"
        # 視窗動作
        "for d in _ids('ir.actions.act_window'):\n"
        "    a = E['ir.actions.act_window'].browse(d.res_id).exists()\n"
        "    if not a:\n"
        "        continue\n"
        "    out.append({'kind': 'action', 'module': d.module,\n"
        "        'anchor': d.module + '.' + d.name, 'name': a.name,\n"
        "        'model': a.res_model or '', 'view_mode': a.view_mode or '',\n"
        "        'view_xmlid': _xid(a.view_id) if a.view_id else '',\n"
        "        'groups': _groups(a.groups_id)})\n"
        # 報表
        "for d in _ids('ir.actions.report'):\n"
        "    r = E['ir.actions.report'].browse(d.res_id).exists()\n"
        "    if r:\n"
        "        out.append({'kind': 'report', 'module': d.module,\n"
        "            'anchor': d.module + '.' + d.name, 'name': r.name,\n"
        "            'model': r.model or '', 'groups': _groups(r.groups_id)})\n"
        # 按鈕：每個模組自己的 form 視圖（含繼承）裡具名的 button
        "import xml.etree.ElementTree as ET\n"
        "for d in _ids('ir.ui.view'):\n"
        "    v = E['ir.ui.view'].browse(d.res_id).exists()\n"
        "    if not v or v.type != 'form':\n"
        "        continue\n"
        "    try:\n"
        "        root = ET.fromstring(v.arch_db or '<x/>')\n"
        "    except ET.ParseError:\n"
        "        continue\n"
        "    vx = d.module + '.' + d.name\n"
        "    base = v\n"
        "    while base.inherit_id and base.mode != 'primary':\n"
        "        base = base.inherit_id\n"
        "    for b in root.iter('button'):\n"
        "        name = b.attrib.get('name')\n"
        "        if not name:\n"
        "            continue\n"
        "        out.append({'kind': 'button', 'module': d.module,\n"
        "            'anchor': '%%s/button[%%s]' %% (vx, name),\n"
        "            'name': b.attrib.get('string') or name, 'model': v.model or '',\n"
        "            'view_xmlid': _xid(base), 'button_name': name,\n"
        "            'button_type': b.attrib.get('type') or '',\n"
        "            'groups': sorted(filter(None, (b.attrib.get('groups') or '').split(',')))})\n"
        # 精靈
        "for m in E['ir.model'].sudo().search([('transient', '=', True)]):\n"
        "    mods = set((m.modules or '').replace(' ', '').split(','))\n"
        "    hit = sorted(mods & MODS)\n"
        "    if hit:\n"
        "        out.append({'kind': 'wizard', 'module': hit[0], 'anchor': m.model,\n"
        "            'name': m.name, 'model': m.model, 'groups': []})\n"
        # 設定
        "for f in E['ir.model.fields'].sudo().search([('model', '=', 'res.config.settings')]):\n"
        "    mods = set((f.modules or '').replace(' ', '').split(','))\n"
        "    hit = sorted(mods & MODS)\n"
        "    if hit and not f.name.startswith('module_'):\n"
        "        out.append({'kind': 'setting', 'module': hit[0], 'anchor': f.name,\n"
        "            'name': f.field_description, 'model': 'res.config.settings',\n"
        "            'groups': []})\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps({'features': out}))\n"
    ) % (sorted(modules), lang)


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
        "            sh, found = scope_hash(archs, it.get('elements') or [],\n"
        "                                   it.get('menu_path') or '', it.get('view_mode') or '')\n"
        "            per[code] = {'form': form_hash(archs), 'scope': sh,\n"
        "                         'found': found, 'sig': signature(archs)}\n"
        "        except Exception as e:\n"
        "            per[code] = {'error': str(e)[:300]}\n"
        "    res[it['key']] = per\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps({'version': FINGERPRINT_VERSION, 'lang': LANG, 'items': res}))\n"
    ) % (json.dumps(items), json.dumps(roles), lang)


#: D1：清除時不動的模型前綴（系統、設定、身分）。
PURGE_SKIP_PREFIXES = (
    'ir.', 'base', 'bus.', 'res.users', 'res.groups', 'res.company', 'res.lang',
    'res.currency', 'res.country', 'res.partner.title', 'res.partner.industry',
    'res.config', 'res.bank', 'decimal.precision', 'uom.', 'mail.template',
    'mail.alias', 'mail.message.subtype', 'mail.activity.type', 'web_editor.',
    'website', 'theme.', 'report.', 'digest.', 'iap.', 'auth_', 'spreadsheet',
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
    roles: [{'code', 'name', 'groups': [...]}] → 建 res.users（xmlid user_<code>）。
    """
    return _HEAD + (
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
        "for rec in RECORDS:\n"
        "    try:\n"
        "        with env.cr.savepoint():\n"
        "            vals = {k: _resolve(v) for k, v in (rec.get('values') or {}).items()}\n"
        "            env[rec['model']].sudo().with_context(tracking_disable=True,\n"
        "                mail_create_nolog=True, no_reset_password=True)._load_records([\n"
        "                {'xml_id': _full(rec['xmlid']), 'values': vals, 'noupdate': False}])\n"
        "        done += 1\n"
        "    except Exception as e:\n"
        "        errors.append({'xmlid': rec.get('xmlid'), 'model': rec.get('model'), 'error': str(e)[:500]})\n"
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
        "env.cr.commit()\n"
        "print(MARK + json.dumps({'done': done, 'errors': errors, 'users': users}))\n"
    ) % (module, json.dumps(records), json.dumps(roles), password)


def gate_script(pairs, since, refs=None):
    """D1 截圖前檢查。

    pairs: {model: [ids]}；refs: {"model|field": [ids]}（many2one／x2many 的值，
    comodel 在這裡查）；since: 清除完成時間（字串）——之後才建立的都是我們放的
    （示範資料與拍攝過程產生），允許。
    允許：模組 xmlid、__doc_scenario_* xmlid、或清除之後才建立。
    """
    return _HEAD + (
        "PAIRS = json.loads(%r)\n"
        "REFS = json.loads(%r)\n"
        "SINCE = %r\n"
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
        "    if model not in env or not ids:\n"
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
    ) % (json.dumps(pairs), json.dumps(refs or {}), since)


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
