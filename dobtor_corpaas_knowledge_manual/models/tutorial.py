# -*- coding: utf-8 -*-
"""情境教學：同一張示範單據跨畫面、一路按到流程終點，每一步拍「按之前」「按之後」。

★ 參考說明書最有價值的部分：讀者看到的是同一張單據從草稿走到完成，每一步知道誰按、
  按哪顆、做完狀態列會變成什麼。逐畫面的參考篇做不到這件事（每個畫面各用各的示範單據）。
★ 路徑與腳本全部由流程結構規則產生（不叫 AI）：從狀態列第一個狀態起，每次挑一顆會把狀態
  推到下一個狀態列步驟、不開精靈的按鈕。每一步一個拍攝工作、用那顆按鈕的拍攝角色登入；
  拍攝工作依序執行，所以同一張單據的狀態接得上。
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
            cands = [t for t in flow.transition_ids.sorted('id') if t.id not in used and ok(t)]
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
        cands = [r for r in seed if r.get('model') == flow.model and not r.get('call')
                 and (r.get('values') or {}).get(flow.state_field) in (first_value, None)]
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
        """每個方案能力一個：能力名下使用量最大、狀態列最長的流程。"""
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        out = Flow
        for cap in package.knowledge_capability_ids:
            flows = Flow.search([('capability_id', '=', cap.id), ('package_ids', 'in', package.id),
                                 ('field_type', '=', 'selection')])
            flows = flows.sorted(lambda f: (-(f.usage_score or 0),
                                            -len(f.step_ids.filtered('on_statusbar')), f.id))
            for f in flows:
                if len(self.env['corpaas.knowledge.tutorial']._path(f)) >= MIN_STEPS:
                    out |= f
                    break
        return out

    @api.model
    def _manual_shoot_tutorials(self, package, sandbox, token=None):
        """拍情境教學。回傳這次拍了幾篇。"""
        Tutorial = self.env['corpaas.knowledge.tutorial'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        scenario = sandbox.scenario_id
        seed = [r for r in self._manual_seed(scenario) if not r.get('call')]
        logins = json.loads(sandbox.sudo().role_logins or '{}')
        if not seed or not logins:
            return 0
        from odoo.addons.dobtor_corpaas_knowledge.models.flow_diagram import MODEL_ROLE
        jobs, plans = [], []
        for flow in self._manual_tutorial_flows(package):
            # ☠️ 實機：按鈕多半沒有功能點繫結，退回第一個角色（業務）去按付款、採購申請 → 存取錯誤。
            #   退回時用單據的負責角色。
            default_role = MODEL_ROLE.get(flow.model) if MODEL_ROLE.get(flow.model) in logins \
                else next(iter(logins))
            path = Tutorial._path(flow)
            bar = [s.value for s in flow.step_ids.sorted('sequence') if s.on_statusbar]
            rec = Tutorial._pick_record(flow, seed, bar[0])
            if not rec:
                continue
            steps = []
            for t, fr, to in path:
                b = Binding.search([('feature_id', '=', t.button_feature_id.id),
                                    ('state', '=', 'ok')], limit=1) if t.button_feature_id else Binding
                role = (b.login_role() if b else None) or default_role
                if role not in logins:
                    role = default_role
                steps.append({'from': fr, 'to': to, 'button': t.button_name,
                              'label': t.display_label() or t.button_name, 'role': role})
            sig = hashlib.sha1(json.dumps(
                [flow.structure_hash, rec['xmlid'], steps, scenario.seed_revisions(),
                 shooter.runner_signature()], sort_keys=True, default=str).encode()).hexdigest()[:16]
            tut = Tutorial.search([('package_id', '=', package.id), ('flow_id', '=', flow.id)])
            if tut and tut.inputs_sig == sig and tut.state == 'ok':
                continue
            plans.append((flow, rec, steps, sig, tut))
        if not plans:
            return 0
        resolved = sandbox.resolve_xmlids(sorted({p[1]['xmlid'] for p in plans}))
        password = sandbox.sudo().password
        for k, (flow, rec, steps, sig, tut) in enumerate(plans):
            target = resolved.get(rec['xmlid'])
            if not target:
                continue
            for i, st in enumerate(steps):
                jobs.append({'id': 't%s_%s' % (k, i), 'login': logins[st['role']],
                             'password': password, 'steps': [
                                 {'open': {'model': flow.model, 'res_id': target[1]}},
                                 {'wait': {'ms': 600}},
                                 {'highlight': {'button': st['button'], 'n': 1}},
                                 {'shot': 'before'},
                                 {'click': {'button': st['button']}},
                                 {'wait': {'ms': 1200}},
                                 {'shot': 'after'}]})
        if not jobs:
            return 0
        package._knowledge_heartbeat('kb_shoot', _('情境教學 %s 篇') % len(plans))
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        try:
            result, files = shooter.run_shots(self.env, sandbox, jobs, settings)
        except (shooter.ShotError, remote.RemoteError) as e:
            _logger.warning('[knowledge.manual] 情境教學拍攝環境錯誤：%s', e)
            return 0
        sandbox.sudo().dirty = True   # 按過按鈕：示範資料已改動（R1）
        shots = result.get('shots') or {}
        done = 0
        for k, (flow, rec, steps, sig, tut) in enumerate(plans):
            out, error = [], ''
            for i, st in enumerate(steps):
                r = shots.get('t%s_%s' % (k, i)) or {}
                if not r.get('ok'):
                    error = (r.get('error') or _('沒有結果'))[:2000]
                    break
                images = {img.get('name'): img for img in r.get('images') or []}
                atts = {}
                for name in ('before', 'after'):
                    img = images.get(name)
                    data = files.get(img.get('file')) if img else None
                    if not data:
                        continue
                    png = annotate.draw_regions(data, img.get('regions') or []) \
                        if name == 'before' else data
                    atts[name] = self.env['ir.attachment'].sudo().create({
                        'name': 'tutorial-%s-%s-%s.png' % (flow.id, i, name),
                        'datas': base64.b64encode(png), 'mimetype': 'image/png',
                        'public': True, 'res_model': 'corpaas.knowledge.tutorial'}).id
                if 'after' not in atts:
                    error = _('第 %s 步沒有拍到按之後的畫面') % (i + 1)
                    break
                seen = [o for o in r.get('transitions') or [] if o.get('to')]
                if seen:
                    st = dict(st, to=str(seen[-1]['to']))   # 實際推到的狀態
                out.append(dict(st, before=atts.get('before'), after=atts['after']))
                if i + 1 < len(steps) and steps[i + 1]['from'] != st['to']:
                    break   # 跟預期不同：後面的步驟起點對不上，教到這裡為止
            vals = {'package_id': package.id, 'flow_id': flow.id, 'record_xmlid': rec['xmlid'],
                    'record_label': Tutorial._record_label(rec, seed),
                    'steps_json': json.dumps(out, ensure_ascii=False), 'inputs_sig': sig,
                    'state': 'ok' if len(out) >= MIN_STEPS else 'failed',
                    'last_error': error or False, 'shot_at': fields.Datetime.now()}
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
        flow = tutorial.flow_id
        steps = tutorial.steps()
        role_names = self._manual_role_names(tutorial.package_id)
        articles = {}
        for pl in placements.filtered(lambda p: p._manual_is_live()):
            articles.setdefault(pl.article_id.feature_id.id, pl)
        trans = {t.button_name: t for t in flow.transition_ids}
        first, last = flow.step_label(steps[0]['from']), flow.step_label(steps[-1]['to'])
        parts = ['<p>%s</p>' % esc(_(
            '以下用示範系統裡的同一張「%(m)s」%(r)s，從「%(a)s」一路做到「%(b)s」。'
            '每一步先看要按哪顆按鈕（紅框），按完對照狀態列確認。',
            m=flow.model_name or flow.name, r=('（%s）' % tutorial.record_label)
            if tutorial.record_label else '', a=first, b=last))]
        for n, st in enumerate(steps, start=1):
            fr, to = flow.step_label(st['from']), flow.step_label(st['to'])
            who = role_names.get(st.get('role')) or ''
            parts.append('<h3>%s</h3>' % esc(_('第 %(n)s 步：%(a)s → %(b)s', n=n, a=fr, b=to)))
            parts.append('<p>%s</p>' % esc(_('%(who)s在「%(a)s」的單據上按「%(btn)s」（圖中 1）。',
                                            who=('由%s' % who) if who else '', a=fr, btn=st['label'])))
            if st.get('before'):
                parts.append('<p><img src="/web/image/%s" class="img-fluid rounded border" alt="%s" '
                             'loading="lazy"/></p>' % (st['before'], esc(_('按「%s」之前，紅框是要按的按鈕')
                                                                       % st['label'])))
            parts.append('<p><strong>%s</strong>%s</p>' % (
                esc(_('做完確認：')), esc(_('狀態列變成「%s」。') % to)))
            parts.append('<p><img src="/web/image/%s" class="img-fluid rounded border" alt="%s" '
                         'loading="lazy"/></p>' % (st['after'], esc(_('按完之後，狀態是「%s」') % to)))
            t = trans.get(st['button'])
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
