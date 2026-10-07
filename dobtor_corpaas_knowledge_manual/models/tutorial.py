# -*- coding: utf-8 -*-
"""情境教學：同一張示範單據跨畫面、一路按到流程終點，每一步拍「按之前」「按之後」。

★ 參考說明書最有價值的部分：讀者看到的是同一張單據從草稿走到完成，每一步知道誰按、
  按哪顆、做完狀態列會變成什麼。逐畫面的參考篇做不到這件事（每個畫面各用各的示範單據）。
★ 路徑與腳本全部由流程結構規則產生（不叫 AI）：從狀態列第一個狀態起，每次挑一顆會把狀態
  推到下一個狀態列步驟的按鈕；走完再沿著「交接」打開下游單據（銷售訂單 → 出貨單 → 發票），
  在下游單據上照樣往下按。整條是一個拍攝工作（下游單據的 id 事先不知道，只能在同一個
  瀏覽器裡一路點過去）；每一步是一組選用步驟，按鈕沒出現就略過那一組、下游跟著略過，
  做到哪裡就教到哪裡。
★ 會改到說明庫的示範資料：放在所有拍攝之後跑，跑過就把說明庫標成「已被拍攝改動」
  （下一次更新重建）；輸入簽章沒變就不重拍。
"""
import base64
import hashlib
import html as html_mod
import json
import logging

from odoo import _, api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.services import remote, shooter

from ..services import annotate

_logger = logging.getLogger(__name__)

#: 一篇情境教學最多幾步（太長的流程只教前半段，其餘看參考篇）
MAX_STEPS = 6
#: 至少要成功幾步才發佈（只有一步就跟參考篇一樣，不需要教學）
MIN_STEPS = 2


class KnowledgeTutorial(models.Model):
    _name = 'corpaas.knowledge.tutorial'
    _description = '操作說明：情境教學'
    _order = 'package_id, id'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    flow_id = fields.Many2one('corpaas.knowledge.flow', required=True, ondelete='cascade',
                              index=True)
    record_xmlid = fields.Char(string='示範單據', readonly=True)
    record_label = fields.Char(string='單據說明', readonly=True)
    steps_json = fields.Text(readonly=True, help='[{from, to, button, label, role, before, after}]：'
                                                 'before／after 是公開圖檔 id')
    inputs_sig = fields.Char(readonly=True, help='路徑、示範資料版號、角色、截圖程式的簽章：沒變不重拍')
    state = fields.Selection([('pending', '待拍'), ('ok', '成功'), ('failed', '失敗')],
                             default='pending', index=True)
    last_error = fields.Text(readonly=True)
    shot_at = fields.Datetime(readonly=True)

    _sql_constraints = [('package_flow_unique', 'unique(package_id, flow_id)',
                         '同一方案同一流程只有一篇情境教學')]

    def steps(self):
        self.ensure_one()
        try:
            return json.loads(self.steps_json or '[]') or []
        except ValueError:
            return []

    # ------------------------------------------------------------------
    @api.model
    def _path(self, flow):
        """狀態列上的主線：[(transition, from, 預期的 to)]，最多 MAX_STEPS 步。

        ☠️ 實機：靜態分析推不出很多按鈕的終點（調撥的「核實」終點空白），也常只記到其中一個
          起點（銷售單的「確認」只記了「報價已傳送」→ 銷售訂單，草稿其實也看得到）。所以：
          ① 起點相符、終點是後面的狀態 → 最優先；② 起點相符、終點不明 → 先假設推到下一格；
          ③ 下一格狀態才記到的按鈕 → 當成現在也按得到。實際推到哪裡以拍攝時觀察到的為準。
          列印、取消、鎖定、寄送、查看類按鈕不走；開精靈的只在它確實會改狀態時走。"""
        import re
        deny = re.compile(r'(?i)print|preview|report|export|download|cancel|lock|draft|send|'
                          r'^action_(view|see|show|open)_')
        bar = [s.value for s in flow.step_ids.sorted('sequence') if s.on_statusbar]
        if len(bar) < 2:
            return []

        def ok(t):
            return t.button_name and not t.button_name.isdigit() and t.display_label() \
                and not deny.search(t.button_name) and (not t.opens_model or t.to_value)

        cur, path, used = bar[0], [], set()
        while len(path) < MAX_STEPS and bar.index(cur) < len(bar) - 1:
            idx = bar.index(cur)
            cands = [t for t in flow.effective_transitions().sorted('id') if t.id not in used and ok(t)]
            later = [t for t in cands if (t.from_value or '') == cur and t.to_value in bar
                     and bar.index(t.to_value) > idx]
            unknown = [t for t in cands if (t.from_value or '') == cur and not t.to_value]
            skip = [t for t in cands if idx + 1 < len(bar) and t.from_value == bar[idx + 1]
                    and t.to_value in bar and bar.index(t.to_value) > idx + 1]
            if later:
                best = min(later, key=lambda t: (bar.index(t.to_value), bool(t.opens_model)))
                to = best.to_value
            elif unknown:
                best, to = unknown[0], bar[idx + 1]
            elif skip:
                best = min(skip, key=lambda t: (bar.index(t.to_value), bool(t.opens_model)))
                to = best.to_value
            else:
                break
            used.add(best.id)
            path.append((best, cur, to))
            cur = to
        return path

    @api.model
    def _pick_record(self, flow, seed, first_value):
        """示範資料裡停在第一個狀態的單據（沒寫狀態＝預設狀態，也算）；有明細的優先。"""
        # ☠️ 實機：沒寫狀態的單據多半另有動作記錄（so_01_confirm → ref so_01）把它推走了，
        #   拍的時候已經不在第一個狀態 → 按鈕找不到。被動作記錄推過的不挑。
        moved = {str(r.get('ref')) for r in seed if r.get('call') and r.get('ref')}
        moved |= {x.split('.', 1)[1] for x in moved if '.' in x}
        cands = [r for r in seed if r.get('model') == flow.model and not r.get('call')
                 and (r.get('values') or {}).get(flow.state_field) in (first_value, None)
                 and r['xmlid'] not in moved and r['xmlid'].split('.')[-1] not in moved]
        if not cands:
            return None

        def has_lines(r):
            ref = '__ref__:%s' % r['xmlid']
            return any(ref in (x.get('values') or {}).values() for x in seed)
        return sorted(cands, key=lambda r: (not has_lines(r), cands.index(r)))[0]

    @api.model
    def _record_label(self, rec, seed):
        by = {r['xmlid']: r for r in seed}
        vals = rec.get('values') or {}
        if isinstance(vals.get('name'), str) and vals['name']:
            return vals['name']
        for k, v in vals.items():
            if isinstance(v, str) and v.startswith('__ref__:') and k.startswith('partner'):
                ref = by.get(v[len('__ref__:'):])
                name = (ref.get('values') or {}).get('name') if ref else None
                if name:
                    return _('客戶／對象：%s') % name
        return ''


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _knowledge_shoot(self, package, sandbox, events, ctx):
        res = super()._knowledge_shoot(package, sandbox, events, ctx)
        if sandbox.scenario_id == package.knowledge_scenario_ids[:1]:
            try:
                n = self._manual_shoot_tutorials(package, sandbox, ctx.get('token'))
                if n:
                    ctx.setdefault('stats', {})['tutorials_shot'] = n
            except Exception as e:  # noqa: BLE001 — 教學拍不成不影響其他
                _logger.warning('[knowledge.manual] 情境教學拍攝失敗：%s', e)
            self._manual_commit()
        return res

    @api.model
    def _manual_tutorial_flows(self, package):
        """每個方案能力一個起點流程：能力名下使用量最大、狀態列最長、走得出路徑的。"""
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        Tutorial = self.env['corpaas.knowledge.tutorial']
        out = Flow
        for cap in package.knowledge_capability_ids:
            flows = Flow.search([('capability_id', '=', cap.id), ('package_ids', 'in', package.id),
                                 ('field_type', '=', 'selection')])
            flows = flows.sorted(lambda f: (-(f.usage_score or 0),
                                            -len(f.step_ids.filtered('on_statusbar')), f.id))
            for f in flows:
                if Tutorial._path(f):
                    out |= f
                    break
        return out

    @api.model
    def _manual_tutorial_downstream(self, flow, package):
        """[(轉換, 下游流程)]：這張單據交接給哪些下游單據（依上下游先後，最多 3 個）。"""
        from odoo.addons.dobtor_corpaas_knowledge.models.flow_diagram import DOWNSTREAM_ORDER
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        out, seen = [], set()
        for t, model in flow._kb_opens():
            if model in seen or model == flow.model:
                continue
            target = Flow.search([('model', '=', model), ('package_ids', 'in', package.id),
                                  ('field_type', '=', 'selection')], limit=1)
            if target:
                seen.add(model)
                out.append((t, target))
        out.sort(key=lambda x: DOWNSTREAM_ORDER.index(x[1].model)
                 if x[1].model in DOWNSTREAM_ORDER else 99)
        return out[:3]

    @api.model
    def _manual_tutorial_plan(self, flow, package):
        """整條教學的步驟計畫：起點流程的路徑，接著每個下游單據（打開 → 它的路徑）。

        回傳 [{kind: press|open, flow, button, label, from, to, req}]；req 是要先成功的步驟序號。"""
        Tutorial = self.env['corpaas.knowledge.tutorial']
        plan = []
        for t, fr, to in Tutorial._path(flow):
            plan.append({'kind': 'press', 'flow': flow.id, 'button': t.button_name,
                         'label': t.display_label(), 'from': fr, 'to': to,
                         'wizard': t.opens_model or ''})
        root_steps = list(range(len(plan)))
        for t, target in self._manual_tutorial_downstream(flow, package):
            label = t.display_label() or target.name
            if not label:
                continue
            idx = len(plan)
            plan.append({'kind': 'open', 'flow': target.id, 'button': t.button_name,
                         'label': label, 'from': '', 'to': '', 'parent': flow.id,
                         'wizard': t.opens_model if t.opens_model and t.opens_model != target.model
                         else '', 'req': []})
            for t2, fr2, to2 in Tutorial._path(target)[:3]:
                plan.append({'kind': 'press', 'flow': target.id, 'button': t2.button_name,
                             'label': t2.display_label(), 'from': fr2, 'to': to2,
                             'wizard': t2.opens_model or '', 'req': [idx]})
            if len(plan) >= 10:
                break
        del root_steps
        return plan[:10]

    @api.model
    def _manual_tutorial_steps(self, plan, model, res_id, confirm, auth=None):
        """計畫 → 拍攝步驟（每一步一組選用步驟）。

        confirm：{精靈模型: 確認按鈕}；auth：{流程 id: (帳號, 密碼)}——每一組先用那張單據的
        負責角色登入（沒有就沿用目前登入的帳號）。下游單據打開後記下網址，換角色再回到它。
        ☠️ 實機：用系統管理員一個帳號拍整條，管理員沒有銷售／會計權限 → 每一步都是存取錯誤。"""
        auth = auth or {}
        steps = []
        opened = {}   # 計畫序號 → 記下的網址名稱
        for i, st in enumerate(plan):
            grp = 's%s' % i
            req = ['s%s' % r for r in st.get('req') or []]
            base = {'optional': True, 'grp': grp, 'req': req}
            who_flow = st.get('parent') if st['kind'] == 'open' else st['flow']
            if who_flow in auth:
                user, password = auth[who_flow]
                steps.append(dict({'login': {'user': user, 'password': password}}, **base))
            if st.get('req'):
                steps.append(dict({'recall': opened.get(st['req'][0], 'g%s' % st['req'][0])}, **base))
            else:
                steps.append(dict({'open': {'model': model, 'res_id': res_id}}, **base))
            steps.append(dict({'wait': {'ms': 800}}, **base))
            steps.append(dict({'highlight': {'button': st['button'], 'n': 1}}, **base))
            steps.append(dict({'shot': '%s_before' % grp}, **base))
            steps.append(dict({'click': {'button': st['button']}}, **base))
            steps.append(dict({'wait': {'ms': 1200}}, **base))
            if st.get('wizard') and confirm.get(st['wizard']):
                steps.append(dict({'click': {'button': confirm[st['wizard']]}}, **base))
                steps.append(dict({'wait': {'ms': 1500}}, **base))
            steps.append(dict({'shot': '%s_after' % grp}, **base))
            if st['kind'] == 'open':
                opened[i] = 'g%s' % i
                steps.append(dict({'remember': opened[i]}, **base))
        return steps

    @api.model
    def _manual_tutorial_copies(self, sandbox, resolved):
        """{xmlid: [model, 複本 id]}：在說明庫複製教學要用的示範單據（會 commit；說明庫之後
        本來就會標成已改動、下次重建）。"""
        from odoo.addons.dobtor_corpaas_knowledge.services import scripts
        if not resolved:
            return {}
        script = scripts._HEAD + (
            "SRC = json.loads(%r)\n"
            "out = {}\n"
            "for x, (model, rid) in SRC.items():\n"
            "    try:\n"
            "        with env.cr.savepoint():\n"
            "            new = env[model].browse(rid).copy()\n"
            "            out[x] = [model, new.id]\n"
            "    except Exception:\n"
            "        pass\n"
            "env.cr.commit()\n"
            "print(MARK + json.dumps(out))\n"
        ) % json.dumps(resolved)
        try:
            return sandbox._shell(script) or {}
        except remote.RemoteError as e:
            _logger.warning('[knowledge.manual] 複製教學單據失敗：%s', e)
            return {}

    @api.model
    def _manual_wizard_confirms(self, sandbox, models_):
        """精靈的確認按鈕：表單裡第一顆主要按鈕（btn-primary）的名稱。"""
        from odoo.addons.dobtor_corpaas_knowledge.services import scripts
        if not models_:
            return {}
        script = scripts._HEAD + (
            "import re\n"
            "MODELS = json.loads(%r)\n"
            "out = {}\n"
            "for m in MODELS:\n"
            "    if m not in env:\n"
            "        continue\n"
            "    try:\n"
            "        arch = env[m].get_views([(False, 'form')])['views']['form']['arch']\n"
            "    except Exception:\n"
            "        continue\n"
            "    for b in re.finditer(r'<button[^>]*>', arch):\n"
            "        tag = b.group(0)\n"
            "        if 'btn-primary' in tag and re.search(r'type=\"(object|action)\"', tag):\n"
            "            n = re.search(r'name=\"([^\"]+)\"', tag)\n"
            "            if n:\n"
            "                out[m] = n.group(1)\n"
            "                break\n"
            "env.cr.rollback()\n"
            "print(MARK + json.dumps(out))\n"
        ) % json.dumps(sorted(models_))
        try:
            return sandbox._shell(script) or {}
        except remote.RemoteError as e:
            _logger.warning('[knowledge.manual] 精靈確認按鈕探測失敗：%s', e)
            return {}

    @api.model
    def _manual_shoot_tutorials(self, package, sandbox, token=None):
        """拍情境教學（每個能力一條，跨單據）。回傳這次拍了幾篇。"""
        from odoo.addons.dobtor_corpaas_knowledge.models.flow_diagram import MODEL_ROLE
        Tutorial = self.env['corpaas.knowledge.tutorial'].sudo()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        scenario = sandbox.scenario_id
        seed = [r for r in self._manual_seed(scenario) if not r.get('call')]
        all_seed = self._manual_seed(scenario)
        logins = json.loads(sandbox.sudo().role_logins or '{}')
        if not seed or not logins:
            return 0
        # 一開始先用起點單據的負責角色登入；之後每一步再換成那張單據的負責角色
        login_role = next(iter(logins))
        plans = []
        for flow in self._manual_tutorial_flows(package):
            bar = [s.value for s in flow.step_ids.sorted('sequence') if s.on_statusbar]
            rec = Tutorial._pick_record(flow, all_seed, bar[0])
            plan = self._manual_tutorial_plan(flow, package)
            if not rec or not plan:
                continue
            sig = hashlib.sha1(json.dumps(
                [flow.structure_hash, rec['xmlid'], plan, scenario.seed_revisions(),
                 shooter.runner_signature(), login_role], sort_keys=True, default=str)
                .encode()).hexdigest()[:16]
            tut = Tutorial.search([('package_id', '=', package.id), ('flow_id', '=', flow.id)])
            if tut and tut.inputs_sig == sig and tut.state == 'ok':
                continue
            plans.append((flow, rec, plan, sig, tut))
        if not plans:
            return 0
        resolved = sandbox.resolve_xmlids(sorted({p[1]['xmlid'] for p in plans}))
        # ☠️ 實機：一般截圖先跑、有些會按「確認」，輪到教學時示範單據早就鎖定了 →
        #   在說明庫複製一張全新的（copy 回到草稿），教學用複本；複製不了才用原本那張
        resolved.update(self._manual_tutorial_copies(sandbox, resolved))
        confirm = self._manual_wizard_confirms(
            sandbox, {st['wizard'] for p in plans for st in p[2] if st.get('wizard')})
        jobs = []
        password = sandbox.sudo().password
        for k, (flow, rec, plan, sig, tut) in enumerate(plans):
            target = resolved.get(rec['xmlid'])
            if not target:
                continue
            auth = {}
            for st in plan:
                for fid in (st['flow'], st.get('parent')):
                    f = Flow.browse(fid) if fid else Flow
                    code = MODEL_ROLE.get(f.model) if f else None
                    if f and code in logins:
                        auth[f.id] = (logins[code], password)
            jobs.append({'id': 't%s' % k, 'login': logins[login_role], 'password': password,
                         'steps': self._manual_tutorial_steps(plan, flow.model, target[1],
                                                              confirm, auth)})
        if not jobs:
            return 0
        package._knowledge_heartbeat('kb_shoot', _('情境教學 %s 篇') % len(jobs))
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        try:
            result, files = shooter.run_shots(self.env, sandbox, jobs, settings)
        except (shooter.ShotError, remote.RemoteError) as e:
            _logger.warning('[knowledge.manual] 情境教學拍攝環境錯誤：%s', e)
            return 0
        sandbox.sudo().dirty = True   # 按過按鈕：示範資料已改動（R1）
        shots = result.get('shots') or {}
        done = 0
        for k, (flow, rec, plan, sig, tut) in enumerate(plans):
            r = shots.get('t%s' % k) or {}
            images = {img.get('name'): img for img in r.get('images') or []}
            observed = {o.get('button'): o for o in r.get('transitions') or []}
            out = []
            for i, st in enumerate(plan):
                after = images.get('s%s_after' % i)
                data = files.get(after.get('file')) if after else None
                if not data:
                    continue
                atts = {}
                before = images.get('s%s_before' % i)
                bdata = files.get(before.get('file')) if before else None
                if bdata:
                    atts['before'] = self.env['ir.attachment'].sudo().create({
                        'name': 'tutorial-%s-%s-before.png' % (flow.id, i),
                        'datas': base64.b64encode(annotate.draw_regions(
                            bdata, before.get('regions') or [])),
                        'mimetype': 'image/png', 'public': True,
                        'res_model': 'corpaas.knowledge.tutorial'}).id
                atts['after'] = self.env['ir.attachment'].sudo().create({
                    'name': 'tutorial-%s-%s-after.png' % (flow.id, i),
                    'datas': base64.b64encode(data), 'mimetype': 'image/png', 'public': True,
                    'res_model': 'corpaas.knowledge.tutorial'}).id
                step = dict(st, **atts)
                ob = observed.get(st['button'])
                if st['kind'] == 'press' and ob and ob.get('to'):
                    step['from'], step['to'] = str(ob.get('from') or st['from']), str(ob['to'])
                f = Flow.browse(st['flow'])
                step['role'] = MODEL_ROLE.get(f.model) or ''
                out.append(step)
            presses = [s for s in out if s['kind'] == 'press']
            vals = {'package_id': package.id, 'flow_id': flow.id, 'record_xmlid': rec['xmlid'],
                    'record_label': Tutorial._record_label(rec, seed),
                    'steps_json': json.dumps(out, ensure_ascii=False), 'inputs_sig': sig,
                    'state': 'ok' if len(out) >= MIN_STEPS and presses else 'failed',
                    'last_error': (r.get('error') or '')[:2000] or
                    ('\n'.join(r.get('warnings') or [])[:2000] or False),
                    'shot_at': fields.Datetime.now()}
            old = tut.steps() if tut else []
            if tut:
                tut.write(vals)
            else:
                tut = Tutorial.create(vals)
            self.env['ir.attachment'].sudo().browse(
                [a for s in old for a in (s.get('before'), s.get('after')) if a]).unlink()
            self.env['ir.attachment'].sudo().browse(
                [a for s in out for a in (s.get('before'), s.get('after')) if a]).write(
                {'res_id': tut.id})
            done += 1
        return done


class KnowledgeChannelSection(models.Model):
    _inherit = 'corpaas.knowledge.channel_section'

    def _manual_tutorial_html(self, tutorial, placements):
        esc = html_mod.escape
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        root = tutorial.flow_id
        steps = tutorial.steps()
        role_names = self._manual_role_names(tutorial.package_id)
        articles = {}
        for pl in placements.filtered(lambda p: p._manual_is_live()):
            articles.setdefault(pl.article_id.feature_id.id, pl)
        docs = []
        for st in steps:
            st.setdefault('flow', root.id)       # 舊格式（單一單據）的步驟
            st.setdefault('kind', 'press')
            name = Flow.browse(st['flow']).model_name or Flow.browse(st['flow']).name
            if name and name not in docs:
                docs.append(name)
        parts = ['<p>%s</p>' % esc(_(
            '以下用示範系統裡的同一張「%(m)s」%(r)s，一路做下去%(chain)s。每一步先看要按哪顆按鈕'
            '（紅框），按完對照畫面確認。',
            m=root.model_name or root.name,
            r=('（%s）' % tutorial.record_label) if tutorial.record_label else '',
            chain=('，經過%s' % '、'.join('「%s」' % d for d in docs[1:])) if len(docs) > 1 else ''))]
        for n, st in enumerate(steps, start=1):
            flow = Flow.browse(st['flow'])
            who = role_names.get(st.get('role')) or ''
            doc = flow.model_name or flow.name
            if st['kind'] == 'open':
                parent = Flow.browse(st.get('parent'))
                parts.append('<h3>%s</h3>' % esc(_('第 %(n)s 步：打開%(d)s', n=n, d=doc)))
                parts.append('<p>%s</p>' % esc(_(
                    '回到這張「%(p)s」，按「%(b)s」（圖中 1）打開它的%(d)s。',
                    p=parent.model_name or parent.name, b=st['label'], d=doc)))
                done_text = _('畫面換成這張單據的%s。') % doc
            else:
                fr, to = flow.step_label(st['from']), flow.step_label(st['to'])
                parts.append('<h3>%s</h3>' % esc(_('第 %(n)s 步：%(d)s %(a)s → %(b)s',
                                                   n=n, d=doc, a=fr, b=to)))
                parts.append('<p>%s</p>' % esc(_(
                    '%(who)s在「%(a)s」的%(d)s上按「%(btn)s」（圖中 1）%(wiz)s。',
                    who=('由%s' % who) if who else '', a=fr, d=doc, btn=st['label'],
                    wiz='，在跳出的視窗按確認' if st.get('wizard') else '')))
                done_text = _('狀態列變成「%s」。') % to
            if st.get('before'):
                parts.append('<p><img src="/web/image/%s" class="img-fluid rounded border" alt="%s" '
                             'loading="lazy"/></p>' % (st['before'], esc(_('按「%s」之前，紅框是要按的按鈕')
                                                                       % st['label'])))
            parts.append('<p><strong>%s</strong>%s</p>' % (esc(_('做完確認：')), esc(done_text)))
            parts.append('<p><img src="/web/image/%s" class="img-fluid rounded border" alt="%s" '
                         'loading="lazy"/></p>' % (st['after'], esc(done_text)))
            t = flow.transition_ids.filtered(lambda x: x.button_name == st['button'])[:1]
            pl = articles.get(t.button_feature_id.id) if t and t.button_feature_id else None
            if pl and pl.slide_id:
                parts.append('<p>%s<a href="%s">%s</a></p>' % (
                    esc(_('這一步的詳細說明：')), esc(pl.slide_id.website_url or '#'),
                    esc(pl.article_id._manual_live_text().get('name') or '')))
        return '<div class="o_kb_guide o_kb_tutorial">%s</div>' % ''.join(parts)

    def _manual_sync_tutorial(self, flows, package, placements, publisher, shown):
        """本章的情境教學（排在整體流程之後、參考篇之前）。回傳 slide（可能空）。"""
        self.ensure_one()
        tut = self.env['corpaas.knowledge.tutorial'].sudo().search(
            [('package_id', '=', package.id), ('flow_id', 'in', flows.ids), ('state', '=', 'ok')],
            limit=1) if package and flows else None
        html = self._manual_tutorial_html(tut, placements) if tut and len(tut.steps()) >= MIN_STEPS \
            else ''
        return self._manual_upsert_guide('tutorial', html, publisher, shown)
