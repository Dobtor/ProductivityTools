# -*- coding: utf-8 -*-
"""操作說明出口參與核心 refresh 的掛勾。

    kb_fingerprint ── _knowledge_elements_for（範本決定腳本範圍）
                      _knowledge_fingerprint_rebaselined（定義改了：原地換指紋，不分岔）
    kb_sandbox     ── _knowledge_scenarios_needing_shots
    kb_shoot       ── _knowledge_shoot：範本（複製／AI 探索）→ 繫結 → 一批拍完 → D1 → dHash 換圖 → AI 修
    kb_outlets     ── _knowledge_dispatch_events：下架（逐方案）→ 修繫結 → 對帳（新文章／分岔／
                      失效回復／換圖上線）→ 合併提案

★ 鍵一律帶指紋（B1/B2）：範本、步驟區塊、文章、素材都以「功能 × 腳本範圍指紋」為鍵；
  方案 A 的畫面改版只會產生 A 那個指紋的新東西，方案 B 的文字與圖一個字都不會變。
★ 對帳（_manual_reconcile）每次 refresh 都掃這個方案的全部候選功能 × 情境，不只這次的
  事件（B5）：上次預算用完、AI 失敗、截圖還沒好而停在 stale 的，下一次會自己接著做。
★ 預算：BudgetExceeded 不是失敗。拍攝本身不花 AI 預算，所以 AI 工作停了照樣拍；
  剩下的 AI 工作留到下一次 refresh。
★ 修腳本不在同一次重試：避免一個壞畫面在同一次 refresh 裡反覆燒預算；修好的繫結回到
  pending，下一次 refresh 才重建說明庫重拍。失敗等修的繫結不會逼每次都重建說明庫。
"""
import io
import json
import logging
from urllib.parse import urlparse

from PIL import Image

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.services import (hub_client, phash, remote, scripts,
                                                           shooter)

from ..services import manual_lib, prompts
from .placement import sync_batch

_logger = logging.getLogger(__name__)

AI_ERRORS = (hub_client.HubError, remote.RemoteError, ValueError, KeyError, TypeError)
#: 同一個繫結連續 AI 修補的上限；超過就停在 failed 等人處理（action_reset）
MAX_REPAIRS = 3


def ai_dict(data, purpose):
    """AI 回覆必須是物件；沒回（None）當空物件。

    ☠️ 模型偶爾回 list／字串：直接 .get() 是 AttributeError，不在 AI_ERRORS 裡，
      整個分派會中斷。一律轉成 ValueError＝這一項 AI 失敗，下一次 refresh 再試。
    """
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError('AI（%s）回覆不是物件：%s' % (purpose, type(data).__name__))
    return data


def ai_text(value):
    return value.strip() if isinstance(value, str) else ''


def ai_str_map(value):
    """{佔位符: xmlid}：只留字串對字串；不是物件就當沒給。"""
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def ai_html_steps(steps, purpose):
    """[{'title','html'}]（steps_to_html 用）：格式不對就 ValueError。"""
    if not isinstance(steps, list) or not steps or not all(
            isinstance(x, dict) and isinstance(x.get('title', ''), str)
            and isinstance(x.get('html', ''), str) for x in steps):
        raise ValueError('AI（%s）的 steps 不是 [{title, html}]' % purpose)
    return steps


def archs_script(model, views, lang='zh_TW'):
    """在說明庫取功能畫面的 arch（唯讀，結尾 rollback）。"""
    return scripts._HEAD + (
        "VIEWS = json.loads(%r)\n"
        "MODEL = %r\n"
        "views = [(env.ref(vx).id if vx else False, vt) for vx, vt in VIEWS]\n"
        "data = env[MODEL].with_context(lang=%r).get_views(views)\n"
        "out = {vt: data['views'][vt]['arch'] for vt in data.get('views', {})}\n"
        "env.cr.rollback()\n"
        "print(MARK + json.dumps(out))\n"
    ) % (json.dumps(views), model, lang)


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    # ------------------------------------------------------------------
    # 共用
    # ------------------------------------------------------------------
    @api.model
    def _manual_feature_dict(self, feature, package=None):
        delta = []
        # 「改過」與改了什麼依方案的黃金庫而定（方案屬性層）
        custom = feature.attr_for(package, 'customized')
        elements = feature.attr_for(package, 'custom_elements')
        if feature.module_origin == 'odoo' and custom and elements:
            try:
                delta = json.loads(elements)
            except ValueError:
                delta = []
        return {'key': feature.feature_key, 'name': feature.name, 'kind': feature.kind,
                'model': feature.model, 'menu_path': feature.menu_path,
                'action_xmlid': feature.action_xmlid, 'button_name': feature.button_name,
                'delta': delta}

    @api.model
    def _manual_package_hashes(self, package, feature):
        """{role_code: scope_hash}：方案目前各角色的腳本範圍指紋（經重新基準對照換算）。

        ☠️ 指紋計算失敗（error、沒有 scope_hash）的角色不列入；全部失敗＝空 dict →
          呼叫端一律跳過，不拿 False 當指紋去寫新區塊／新文章（B7）。
        """
        FP = self.env['corpaas.knowledge.fingerprint'].sudo()
        Rebase = self.env['corpaas.knowledge.manual.rebase']
        out = {}
        for fp in FP.search([('feature_id', '=', feature.id), ('package_id', '=', package.id),
                             ('current', '=', True)], order='id'):
            if fp.scope_hash and not fp.error:
                out[fp.role_code] = Rebase.resolve(feature, fp.scope_hash)
        return out

    @api.model
    def _manual_candidates(self, package):
        """{feature: capability}：被圈選核准、屬於方案能力的功能。

        兩個來源：功能圈選提案已核准（能力在方案內；沒指定能力＝共通操作），或能力的功能點已人工列入。
        ☠️ 改名候選還沒確認時，新鍵不當候選（B9）：確認前舊文章維持上線，新鍵先寫一篇就會重複。
        """
        caps = package.knowledge_capability_ids
        Cap = self.env['corpaas.knowledge.capability']
        out = {}
        sels = self.env['corpaas.knowledge.selection'].sudo().search([
            ('package_id', '=', package.id), ('kind', '=', 'feature'),
            ('state', '=', 'approved'), ('feature_id', '!=', False)])
        for sel in sels:
            own = (sel.feature_id.capability_ids & caps)[:1]
            if sel.capability_id:
                cap = sel.capability_id if sel.capability_id in caps else own
                if not cap:
                    continue
            else:
                cap = own or Cap
            out.setdefault(sel.feature_id, cap)
        for cap in caps:
            for feature in cap.feature_ids:
                out.setdefault(feature, cap)
        renamed_to = self.env['corpaas.knowledge.rename'].sudo().search(
            [('state', '=', 'proposed')]).mapped('new_feature_id')
        # ★ 沒被改過的官方畫面不寫文章（K21）：說明連到 Odoo 官方文件，不重寫一份——
        #   除非方案勾了「原生畫面也製作操作說明」（帶客戶認識原生功能的方案）。
        return {f: c for f, c in out.items()
                if f.model and f not in renamed_to and f.is_present_in(package)
                and package._knowledge_documents_feature(f)}

    @api.model
    def _manual_sorted_candidates(self, package):
        return sorted(self._manual_candidates(package).items(),
                      key=lambda kv: (-(kv[0].attr_for(package, 'usage_score') or 0), kv[0].id))

    @api.model
    def _manual_scenarios_for(self, package, capability):
        """功能要在哪些情境說明：能力有指定適用情境就取交集，否則方案的全部情境。"""
        scenarios = package.knowledge_scenario_ids
        if capability and capability.scenario_ids:
            scenarios &= capability.scenario_ids
        return scenarios

    @api.model
    def _manual_article_status(self, article, package, memo=None):
        """(base, fits, capability)。

        base：方案仍要這個功能×情境（有產品、功能是候選、情境適用）。
        fits：base 而且方案目前任一角色的指紋＝文章指紋（B1）。
        """
        memo = {} if memo is None else memo
        key = ('cand', package.id)
        if key not in memo:
            memo[key] = self._manual_candidates(package)
        cands = memo[key]
        feature = article.feature_id
        if not package.product_tmpl_id or feature not in cands:
            return False, False, None
        cap = cands[feature]
        if article.scenario_id not in self._manual_scenarios_for(package, cap):
            return False, False, cap
        hkey = ('hash', package.id, feature.id)
        if hkey not in memo:
            memo[hkey] = self._manual_package_hashes(package, feature)
        fits = bool(article.fingerprint) and article.fingerprint in memo[hkey].values()
        return True, fits, cap

    @api.model
    def _manual_seed(self, scenario):
        """已核准版本的示範資料（說明庫只用這個重建）；沒有核准版就是空的。"""
        try:
            return scenario.live_seed()
        except UserError:
            return []

    # ------------------------------------------------------------------
    # 指紋範圍
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_elements_for(self, feature, package):
        res = list(super()._knowledge_elements_for(feature, package) or [])
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        tmpl = Template._for_hashes(feature, self._manual_package_hashes(package, feature)) \
            or Template._latest_for(feature)
        for element in (tmpl.elements_list() if tmpl else []):
            if element not in res:
                res.append(element)
        return res

    @api.model
    def _knowledge_fingerprint_rebaselined(self, feature, package, role_code, old, new):
        """腳本範圍的「定義」改了（範本步驟改過）：同一個畫面換了雜湊 → 原地換鍵（B6）。

        不分岔、不叫 AI、不重寫文字：範本／步驟區塊／文章／素材的指紋 old → new，並記一筆
        對照（其他還在 old 的方案經對照換算，兩次 refresh 之間不會掉文章）。
        """
        parent = getattr(super(), '_knowledge_fingerprint_rebaselined', None)
        res = parent(feature, package, role_code, old, new) if parent else True
        if not old or not new or old == new:
            return res
        Rebase = self.env['corpaas.knowledge.manual.rebase'].sudo()
        if Rebase.resolve(feature, old) == new:
            return res
        if Rebase.search_count([('feature_id', '=', feature.id), ('old_hash', '=', old)]):
            # 同一個 old 已被別的方案換到另一個指紋：這個方案在新定義下畫面真的不同，
            # 交給對帳分岔（不能把共用的東西再搬一次）。
            return res
        Template = self.env['corpaas.knowledge.shot_template'].sudo().with_context(
            active_test=False)
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        Article = self.env['corpaas.knowledge.article'].sudo()
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        moved = Template
        for tmpl in Template.search([('feature_id', '=', feature.id), ('fingerprint', '=', old)]):
            if not Template.search_count([('feature_id', '=', feature.id),
                                          ('fingerprint', '=', new),
                                          ('login_role', '=', tmpl.login_role)]):
                tmpl.fingerprint = new
                moved |= tmpl
        bindings = moved.mapped('binding_ids')
        bindings.filtered(lambda b: b.shot_scope_hash == old).write({'shot_scope_hash': new})
        if bindings:
            Asset.search([('owner_model', '=', 'corpaas.knowledge.shot_binding'),
                          ('owner_id', 'in', bindings.ids),
                          ('scope_hash', '=', old)]).write({'scope_hash': new})
        if not Block.search_count([('feature_id', '=', feature.id), ('fingerprint', '=', new)]):
            Block.search([('feature_id', '=', feature.id), ('fingerprint', '=', old)]).write(
                {'fingerprint': new})
        for art in Article.search([('feature_id', '=', feature.id), ('fingerprint', '=', old)]):
            if not Article.search_count([('feature_id', '=', feature.id),
                                         ('scenario_id', '=', art.scenario_id.id),
                                         ('fingerprint', '=', new), ('id', '!=', art.id)]):
                art.fingerprint = new
        Rebase.create({'feature_id': feature.id, 'old_hash': old, 'new_hash': new,
                       'package_id': package.id, 'role_code': role_code})
        return res

    # ------------------------------------------------------------------
    # 要拍哪些情境
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_scenarios_needing_shots(self, package, events):
        """要重建說明庫的情境：還沒有這個指紋的範本或繫結、待拍（pending）、成功卻沒素材、
        情境示範資料變了。

        ☠️ 失敗等修的繫結不算：修補在分派階段做、不需要說明庫；修好變回 pending 才重建，
          否則一個壞繫結會讓每次 refresh 都重建一座說明庫。
        """
        res = super()._knowledge_scenarios_needing_shots(package, events)
        scenarios = package.knowledge_scenario_ids
        res |= events.filtered(lambda e: e.type == 'scenario_changed').mapped(
            'scenario_id') & scenarios
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        for feature, cap in self._manual_candidates(package).items():
            hashes = self._manual_package_hashes(package, feature)
            if not hashes:
                continue
            tmpl = Template._for_hashes(feature, hashes)
            for sc in self._manual_scenarios_for(package, cap) - res:
                b = tmpl.binding_for(sc) if tmpl else None
                if not b or b.state == 'pending' or (
                        b.state == 'ok' and not b.current_assets()):
                    res |= sc
        return res

    # ------------------------------------------------------------------
    # 拍攝
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_shoot(self, package, sandbox, events, ctx):
        res = super()._knowledge_shoot(package, sandbox, events, ctx)
        token = ctx.get('token')
        stop = ctx.setdefault('manual_ai_stopped', {'ai': False})
        self._manual_prepare_templates(package, sandbox, token, stop)
        todo = self._manual_bindings_to_shoot(package, sandbox, events, ctx)
        if not todo:
            return res
        failed = self._manual_run_batch(package, sandbox, todo, token, ctx)
        self._manual_repair_bindings(package, failed, token, stop)
        return res

    @api.model
    def _manual_prepare_templates(self, package, sandbox, token, stop):
        """步驟 1：這個方案目前指紋還沒有範本 → 以同功能的舊範本複製（不叫 AI），
        一份都沒有才 AI 探索；這個情境還沒有繫結 → 沿用／AI 挑示範資料。"""
        scenario = sandbox.scenario_id
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        for feature, cap in self._manual_sorted_candidates(package):
            if scenario not in self._manual_scenarios_for(package, cap):
                continue
            hashes = self._manual_package_hashes(package, feature)
            if not hashes:
                continue
            try:
                tmpl = Template._for_hashes(feature, hashes)
                if not tmpl:
                    src = Template._latest_for(feature)
                    if src:
                        tmpl = self._manual_fork_template(src, hashes)
                    elif stop['ai']:
                        continue
                    else:
                        tmpl = self._manual_explore(package, sandbox, feature, hashes, token)
                if not tmpl.binding_for(scenario):
                    self._manual_bind(package, tmpl, scenario, token, stop)
            except hub_client.BudgetExceeded as e:
                _logger.info('[knowledge.manual] AI 探索停止：%s', e)
                stop['ai'] = True
            except AI_ERRORS as e:
                _logger.warning('[knowledge.manual] AI 探索失敗 %s：%s', feature.feature_key, e)

    @api.model
    def _manual_fork_template(self, src, hashes):
        """畫面指紋變了：以舊範本的步驟複製一份新指紋的範本（確定性，不叫 AI）。"""
        new_hash = hashes.get(src.login_role) or next(iter(hashes.values()))
        return src.copy({'fingerprint': new_hash, 'derived_from_id': src.id,
                         'repair_count': 0,
                         'note': _('指紋 %(o)s → %(n)s 複製', o=src.fingerprint, n=new_hash)})

    @api.model
    def _manual_demo(self, scenario):
        return [{'xmlid': r['xmlid'], 'model': r['model']}
                for r in self._manual_seed(scenario)][:300]

    @api.model
    def _manual_binding_fits(self, bindings, scenario):
        """繫結能否直接沿用到另一個情境：情境示範資料的 xmlid 都在，模組 xmlid 一律可用。"""
        seed = {r['xmlid'] for r in self._manual_seed(scenario)}
        return all(isinstance(x, str) and (not x.startswith('__doc_scenario_') or x in seed)
                   for x in bindings.values())

    @api.model
    def _manual_bind(self, package, tmpl, scenario, token, stop):
        """範本在這個情境的繫結：同範本（含複製來源）已有能用的就沿用，否則 AI 挑示範資料。"""
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        chain, cur = [], tmpl
        while cur and cur not in chain:
            chain.append(cur)
            cur = cur.derived_from_id
        others = Binding.browse()
        for t in chain:
            others |= t.binding_ids
        others = others.sorted(lambda b: (b.scenario_id != scenario, -b.id))
        for other in others:
            if other.scenario_id == scenario or self._manual_binding_fits(other.bindings(),
                                                                         scenario):
                return Binding.create({'template_id': tmpl.id, 'scenario_id': scenario.id,
                                       'bindings_json': other.bindings_json,
                                       'roles_json': other.roles_json})
        bindings = {}
        if tmpl.placeholder_list():
            if stop['ai']:
                return Binding
            data = ai_dict(self.env['corpaas.knowledge.ai'].ask(
                'manual_bind', prompts.bind_prompt(
                    self._manual_feature_dict(tmpl.feature_id, package), tmpl.steps(),
                    tmpl.placeholder_list(), self._manual_demo(scenario)),
                package=package, refresh_token=token, record=tmpl), 'manual_bind')
            bindings = ai_str_map(data.get('bindings'))
        return Binding.create({'template_id': tmpl.id, 'scenario_id': scenario.id,
                               'bindings_json': json.dumps(bindings)})

    @api.model
    def _manual_explore(self, package, sandbox, feature, hashes, token):
        """功能一份範本都沒有：AI 看畫面結構與示範資料寫範本＋第一個繫結。"""
        scenario = sandbox.scenario_id
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        views = feature.views_for_fingerprint() or [[False, 'form']]
        archs = remote.shell_json(self.env, sandbox.master_instance_id, sandbox.db_name,
                                  archs_script(feature.model, views))
        roles = [{'code': r.code, 'name': r.name} for r in scenario.all_roles()]
        screen = self._manual_probe(sandbox, feature)
        data = ai_dict(self.env['corpaas.knowledge.ai'].ask(
            'manual_explore', prompts.explore_prompt(
                self._manual_feature_dict(feature, package), archs, self._manual_demo(scenario), roles,
                screen=screen),
            package=package, refresh_token=token, record=feature), 'manual_explore')
        steps = data.get('steps')
        manual_lib.validate_steps(steps)
        codes = [r['code'] for r in roles]
        role = data.get('login_role') if ai_text(data.get('login_role')) in codes else \
            (codes[0] if codes else False)
        bindings = ai_str_map(data.get('bindings'))
        tmpl = Template.create({
            'feature_id': feature.id, 'steps_json': json.dumps(steps, ensure_ascii=False),
            'login_role': role, 'source': 'ai', 'note': ai_text(data.get('note'))[:200],
            'fingerprint': hashes.get(role) or next(iter(hashes.values()))})
        Binding.create({'template_id': tmpl.id, 'scenario_id': scenario.id,
                        'bindings_json': json.dumps(bindings)})
        return tmpl

    @api.model
    def _manual_probe(self, sandbox, feature):
        """在說明庫實際打開這個功能的畫面，抓下「真的看得到」的按鈕、欄位、分頁。

        ★ 設計要的是「AI 在說明庫實際看過畫面再寫腳本」。做法是由我們的無頭瀏覽器看、
          把看到的東西交給 AI，而不是讓 AI 自己操作瀏覽器：AI 碰不到任何網路位址，
          也不會在探索時亂按按鈕改資料。view arch 看不到的（群組／條件隱藏、繼承後的
          實際位置）這裡都看得到。
        ★ 探測失敗不擋探索：退回只用 arch。
        """
        logins = json.loads(sandbox.role_logins or '{}')
        if not logins or not feature.model:
            return {}
        seed = self._manual_seed(sandbox.scenario_id)
        record_xid = next((r['xmlid'] for r in seed if r['model'] == feature.model), None)
        steps = []
        if feature.kind in ('action', 'menu', 'client') and (
                feature.action_xmlid or feature.kind == 'action'):
            steps += [{'goto': {'action': feature.action_xmlid or feature.anchor}},
                      {'probe': 'entry'}]
        if record_xid:
            ids = sandbox.resolve_xmlids([record_xid]).get(record_xid)
            if ids:
                steps += [{'open': {'model': ids[0], 'res_id': ids[1]}}, {'probe': 'record'}]
        if not steps:
            return {}
        shot = {'id': 'probe', 'login': next(iter(logins.values())),
                'password': sandbox.sudo().password, 'steps': steps}
        try:
            result, _files = shooter.run_shots(
                self.env, sandbox, [shot],
                self.env['res.config.settings'].knowledge_shot_settings())
        except (shooter.ShotError, remote.RemoteError) as e:
            _logger.info('[knowledge.manual] 探測 %s 失敗，改只用 arch：%s', feature.feature_key, e)
            return {}
        res = (result.get('shots') or {}).get('probe') or {}
        return {img['name']: img.get('probe') for img in res.get('images') or []
                if img.get('is_probe')}

    @api.model
    def _manual_bindings_to_shoot(self, package, sandbox, events, ctx):
        """步驟 2 前半：這個情境、這個方案目前指紋的繫結裡要拍的（待拍、沒素材、全量）。"""
        sc = sandbox.scenario_id
        full = ctx.get('full') or sc in events.filtered(
            lambda e: e.type == 'scenario_changed').mapped('scenario_id')
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        out = self.env['corpaas.knowledge.shot_binding'].sudo()
        for feature, cap in self._manual_candidates(package).items():
            if sc not in self._manual_scenarios_for(package, cap):
                continue
            hashes = self._manual_package_hashes(package, feature)
            tmpl = Template._for_hashes(feature, hashes) if hashes else Template
            b = tmpl.binding_for(sc) if tmpl else None
            if not b:
                continue
            if full or b.state == 'pending' or (b.state == 'ok' and not b.current_assets()):
                out |= b
        return out

    @api.model
    def _manual_fail(self, binding, error, result=None, repair=True):
        vals = {'state': 'failed', 'last_error': (error or '')[:4000],
                'last_shot_at': fields.Datetime.now(), 'needs_repair': repair}
        if result is not None:
            vals['last_result'] = json.dumps(result, ensure_ascii=False)[:100000]
        binding.write(vals)

    @api.model
    def _manual_run_batch(self, package, sandbox, bindings, token, ctx):
        """步驟 2 後半～4：解析 → 一批拍完 → 採用圖片。回傳失敗、要 AI 修的繫結。"""
        Binding = self.env['corpaas.knowledge.shot_binding']
        xmlids = sorted({x for b in bindings for x in b.bindings().values()
                         if isinstance(x, str)})
        resolved_x = sandbox.resolve_xmlids(xmlids) if xmlids else {}
        sb = sandbox.sudo()
        logins = json.loads(sb.role_logins or '{}')
        password = sb.password
        shots, by_id, failed = [], {}, Binding
        for b in bindings:
            resolved = {name: resolved_x[x] for name, x in b.bindings().items()
                        if x in resolved_x}
            steps, missing = manual_lib.fill_placeholders(b.template_id.steps(), resolved)
            role = b.login_role()
            login = logins.get(role or '') or (
                next(iter(logins.values())) if len(logins) == 1 and not role else None)
            # ★ 佔位符對不到、角色沒帳號：AI 能修（改繫結／改角色），列入修補
            if missing:
                self._manual_fail(b, _('說明庫找不到示範資料：%s') % ', '.join(sorted(missing)))
                failed |= b
                continue
            if not login:
                self._manual_fail(b, _('說明庫沒有角色「%s」的帳號') % (role or '?'))
                failed |= b
                continue
            sid = 'b%s' % b.id
            shots.append({'id': sid, 'login': login, 'password': password, 'steps': steps})
            by_id[sid] = b
        if not shots:
            return failed
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        try:
            result, files = shooter.run_shots(self.env, sandbox, shots, settings)
        except (shooter.ShotError, remote.RemoteError) as e:
            # 執行環境的錯（不是腳本的錯）：不叫 AI，下一次 refresh 再拍
            for b in by_id.values():
                b.write({'state': 'pending', 'last_error': str(e)[:4000]})
            return failed
        threshold = int(settings.get('phash_threshold') or 10)
        for sid, b in by_id.items():
            r = (result.get('shots') or {}).get(sid) or {'ok': False, 'error': _('沒有結果')}
            if not r.get('ok'):
                self._manual_fail(b, r.get('error') or '', result=r)
                failed |= b
                continue
            if r.get('transitions') and b.template_id.feature_id.model:
                self.env['corpaas.knowledge.flow'].sudo()._knowledge_record_observations(
                    b.template_id.feature_id.model, r['transitions'])
            errors = self._manual_adopt_images(sandbox, b, r.get('images') or [], files,
                                               threshold)
            vals = {'last_result': json.dumps(r, ensure_ascii=False)[:100000],
                    'last_token': token, 'last_shot_at': fields.Datetime.now()}
            if errors:
                self._manual_fail(b, '\n'.join(errors))
                b.write(vals)
                failed |= b
                continue
            vals.update(state='ok', last_error=False, needs_repair=False, repair_attempts=0,
                        shot_scope_hash=b.template_id.fingerprint)
            b.write(vals)
        return failed

    @api.model
    def _manual_adopt_images(self, sandbox, binding, images, files, threshold):
        """步驟 4：D1 檢查 → dHash 比對 → 換圖。回傳錯誤 list。

        ★ 素材的 scope_hash＝範本指紋（不看是哪個方案拍的）：同指紋共用一份，不同指紋各自一份，
          兩個方案不會互相把對方的圖標成 superseded（B2）。
        """
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        feature, scenario = binding.feature_id, binding.scenario_id
        scope = binding.template_id.fingerprint
        current = {a.shot_name: a for a in binding.current_assets()}
        errors = []
        now = fields.Datetime.now()
        for img in images:
            name = img.get('name')
            bad = sandbox.gate_bad_records(img.get('records') or {}, img.get('refs'))
            if bad:
                errors.append(_('%(n)s：畫面出現非示範資料 %(b)s（D1，不採用）',
                                n=name, b=json.dumps(list(bad)[:10])))
                continue
            data = files.get(img.get('file'))
            if not data:
                errors.append(_('%s：截圖檔不見了') % name)
                continue
            digest = phash.dhash(data)
            regions = json.dumps(img.get('regions') or [])
            old = current.get(name)
            if old and phash.distance(old.phash, digest) < threshold:
                old.write({'scope_hash': scope, 'regions_json': regions})
                continue
            width, height = Image.open(io.BytesIO(data)).size
            asset = Asset.create({
                'name': '%s／%s' % (feature.name, name), 'shot_name': name,
                'feature_id': feature.id, 'scenario_id': scenario.id, 'scope_hash': scope,
                'owner_model': binding._name, 'owner_id': binding.id,
                'regions_json': regions, 'phash': digest, 'width': width, 'height': height})
            asset.attachment_id = Attachment.create({
                'name': '%s.png' % name, 'raw': data, 'mimetype': 'image/png',
                'res_model': asset._name, 'res_id': asset.id})
            if old:
                old.write({'state': 'superseded', 'superseded_at': now})
        return errors

    @api.model
    def _manual_repair_bindings(self, package, bindings, token, stop):
        for b in bindings.filtered(lambda x: x.state == 'failed' and x.needs_repair):
            if stop['ai']:
                return
            if b.repair_attempts >= MAX_REPAIRS:
                b.write({'needs_repair': False})
                b.template_id.message_post(body=_(
                    '情境「%(s)s」的截圖 AI 已連續修 %(n)s 次仍失敗，請人工處理後按「下次重拍」。',
                    s=b.scenario_id.name, n=b.repair_attempts))
                continue
            try:
                self._manual_repair(package, b, token)
            except hub_client.BudgetExceeded as e:
                _logger.info('[knowledge.manual] 修腳本停止：%s', e)
                stop['ai'] = True
            except AI_ERRORS as e:
                _logger.warning('[knowledge.manual] 修腳本失敗 %s：%s',
                                b.template_id.display_name, e)

    @api.model
    def _manual_repair(self, package, binding, token):
        """步驟 5：AI 依錯誤修範本／繫結／登入角色；下一次 refresh 才重拍。"""
        tmpl = binding.template_id
        last = json.loads(binding.last_result or '{}')
        roles = [{'code': r.code, 'name': r.name} for r in binding.scenario_id.all_roles()]
        data = ai_dict(self.env['corpaas.knowledge.ai'].ask(
            'manual_repair', prompts.repair_prompt(
                self._manual_feature_dict(tmpl.feature_id, package), tmpl.steps(), binding.bindings(),
                binding.last_error, last.get('dom_text'), last.get('url'), roles,
                self._manual_demo(binding.scenario_id)),
            package=package, refresh_token=token, record=tmpl), 'manual_repair')
        steps = data.get('steps') or tmpl.steps()
        manual_lib.validate_steps(steps)
        if steps != tmpl.steps():
            tmpl.write({'steps_json': json.dumps(steps, ensure_ascii=False),
                        'repair_count': tmpl.repair_count + 1, 'source': 'ai'})
        tmpl.message_post(body=_('AI 修補截圖腳本：%s') % ai_text(data.get('reason')))
        vals = {'state': 'pending', 'needs_repair': False,
                'repair_attempts': binding.repair_attempts + 1}
        if isinstance(data.get('bindings'), dict):
            vals['bindings_json'] = json.dumps(ai_str_map(data['bindings']))
        role = ai_text(data.get('login_role'))
        if role and role in [r['code'] for r in roles] and role != binding.login_role():
            vals['roles_json'] = json.dumps({'login_role': role})
        binding.write(vals)
        return tmpl

    # ------------------------------------------------------------------
    # 事件分派
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_dispatch_events(self, package, events, ctx):
        res = super()._knowledge_dispatch_events(package, events, ctx)
        token = ctx.get('token')
        stop = ctx.setdefault('manual_ai_stopped', {'ai': False})
        # ★ 整次 refresh 一個批次：每個 channel 最後只同步＋重新編號一次
        with sync_batch(self.env) as env:
            me = self.with_env(env)
            package = package.with_env(env)
            me._manual_retire_removed(package, events.with_env(env))
            me._manual_retire_orphans(package)
            me._manual_repair_bindings(package, me._manual_relevant_bindings(package),
                                       token, stop)
            me._manual_reconcile(package, token, stop)
        self._manual_propose_merges(self.env['corpaas.knowledge.feature'].union(
            *self._manual_candidates(package).keys()))
        return res

    @api.model
    def _manual_relevant_bindings(self, package):
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        out = self.env['corpaas.knowledge.shot_binding'].sudo()
        for feature, cap in self._manual_candidates(package).items():
            hashes = self._manual_package_hashes(package, feature)
            tmpl = Template._for_hashes(feature, hashes) if hashes else Template
            if tmpl:
                out |= tmpl.binding_ids.filtered(
                    lambda b: b.scenario_id in self._manual_scenarios_for(package, cap))
        return out

    @api.model
    def _manual_reconcile(self, package, token, stop):
        """B5：每次 refresh 對這個方案的每個候選功能 × 情境對帳一次。

        · 有指紋相符的文章 → 換圖、失效回復、掛到還沒掛的 channel。
        · 同鍵文章曾下架 → 送審復原（不重複建立）。
        · 只有別的指紋的文章 → 跟上新指紋（只有本方案在用就原地換鍵；共用就分岔一篇新的）。
        · 一篇都沒有 → 起草新文章。
        """
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        cache = {}
        for feature, cap in self._manual_sorted_candidates(package):
            hashes = self._manual_package_hashes(package, feature)
            if not hashes:
                continue
            tmpl = Template._for_hashes(feature, hashes)
            for scenario in self._manual_scenarios_for(package, cap):
                try:
                    self._manual_reconcile_one(package, feature, cap, scenario, hashes, tmpl,
                                               token, cache, stop)
                except hub_client.BudgetExceeded as e:
                    _logger.info('[knowledge.manual] 對帳停止 AI：%s', e)
                    stop['ai'] = True
                except AI_ERRORS as e:
                    _logger.warning('[knowledge.manual] 對帳失敗 %s／%s：%s',
                                    feature.feature_key, scenario.code, e)

    @api.model
    def _manual_reconcile_one(self, package, feature, cap, scenario, hashes, tmpl, token,
                              cache, stop):
        Article = self.env['corpaas.knowledge.article'].sudo()
        arts = Article.search([('feature_id', '=', feature.id),
                               ('scenario_id', '=', scenario.id)], order='id')
        values = set(hashes.values())
        fitting = arts.filtered(lambda a: a.fingerprint in values)
        alive = fitting.filtered(lambda a: a.state != 'retired')
        if alive:
            art = alive.sorted(lambda a: (a.state != 'published', -a.id))[:1]
            return self._manual_refresh_article(package, art)
        if fitting:
            # ★ B8：同鍵文章曾下架（功能消失後又回來）→ 送審復原，不另起一篇重複的
            fitting[:1].knowledge_propose('restore', note=_('功能重新出現，復原下架的文章'))
            return fitting[:1]
        if not tmpl or not tmpl.fingerprint:
            return None
        base = arts.filtered(lambda a: a.state != 'retired')
        if base:
            mine = base.filtered(lambda a: a.placement_ids.filtered(
                lambda p: p.package_id == package and not p.manual_retired))
            old = (mine or base).sorted(
                lambda a: (a.state not in ('published', 'stale'), -a.id))[:1]
            return self._manual_follow_scope(package, old, tmpl, token, cache, stop)
        if stop['ai']:
            return None
        return self._manual_draft_article(package, feature, scenario, cap, tmpl, token,
                                          cache, stop)

    @api.model
    def _manual_images_fresh(self, art):
        """(圖好了沒, 繫結)：文章指紋的繫結拍成功、且有同指紋的現行素材。

        這個功能完全沒有截圖範本（人工文章）→ 視為不需要圖。
        """
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        tmpl = Template._for_hashes(art.feature_id, {'_': art.fingerprint})
        if not tmpl:
            return not Template._latest_for(art.feature_id), None
        b = tmpl.binding_for(art.scenario_id)
        ok = bool(b) and b.state == 'ok' and bool(b.current_assets().filtered(
            lambda a: a.scope_hash == art.fingerprint))
        return ok, b or None

    @api.model
    def _manual_refresh_article(self, package, art):
        fresh, b = self._manual_images_fresh(art)
        changed = False
        if fresh and b:
            assets = b.current_assets().filtered(lambda a: a.scope_hash == art.fingerprint)
            if art.asset_ids != assets or art.shot_binding_id != b:
                art._manual_apply_assets(b)
                changed = True
        if art.state == 'stale':
            if fresh:
                art.knowledge_reshoot_done()
        elif art.state == 'draft' and art.manual_waiting_shots:
            if fresh:
                art.knowledge_propose('shot', note=_('新指紋的截圖拍好了'))
        elif art.state == 'published':
            if changed:
                art.knowledge_reshoot_done()
            else:
                pl = art.placement_ids.filtered(
                    lambda p: p.package_id == package or
                    p.channel_id.knowledge_product_tmpl_id == package.product_tmpl_id)[:1]
                if not pl or not pl._manual_is_live():
                    # ★ 方案新引用既有情境、或接手舊指紋那篇的位置：指紋相同直接掛上，不必拍
                    art._manual_push()
                    return art
        # ★ 上次同步失敗（讀回不一致整批回滾）或落後上線修訂 → 重推。前台只用上線快照組裝，
        #   送審中、草稿中的文章重推也只會推上線那一版。
        if art.published_rev_no and art.state != 'retired' and art.placement_ids.filtered(
                lambda p: not p.manual_retired and (
                    p.sync_error or p.last_synced_rev != art.published_rev_no)):
            art._manual_push()
        return art

    @api.model
    def _manual_follow_scope(self, package, old_art, tmpl, token, cache, stop):
        """方案的指紋變了（或還沒有這個指紋的文章）：以既有文章為底跟上新指紋。

        ★ 只有本方案在用 → 原地換指紋（不留一篇沒人用的舊文章）；別的方案還在舊指紋 →
          分岔一篇新的，舊那篇一個字都不動（B1）。
        """
        feature = old_art.feature_id
        new_hash = tmpl.fingerprint
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        blocks, changed = Block, False
        for blk in old_art.step_block_ids:
            if blk.feature_id != feature or blk.fingerprint == new_hash:
                blocks |= blk
                continue
            nb = self._manual_block_for_hash(package, blk, new_hash, tmpl, token, cache, stop)
            if nb is None:
                return None
            changed = changed or nb != blk
            blocks |= nb
        reason = _('畫面改版：%s') % feature.name
        binding = tmpl.binding_for(old_art.scenario_id)
        shared = old_art._manual_fitting_packages() - package
        if not shared:
            was_live = old_art.state in ('published', 'stale')
            old_art.write({'fingerprint': new_hash, 'step_block_ids': [(6, 0, blocks.ids)]})
            if changed:
                old_art.knowledge_propose('text', note=_('畫面改版，步驟區塊依新指紋分岔'))
            elif was_live:
                old_art.knowledge_mark_stale(reason)
                self._manual_refresh_article(package, old_art)
            return old_art
        art = self.env['corpaas.knowledge.article'].sudo().create({
            'name': old_art.name, 'feature_id': feature.id,
            'scenario_id': old_art.scenario_id.id, 'capability_id': old_art.capability_id.id,
            'sequence': old_art.sequence, 'fingerprint': new_hash,
            'step_block_ids': [(6, 0, blocks.ids)], 'scenario_html': old_art.scenario_html,
            'shot_binding_id': binding.id if binding else False,
            'asset_ids': [(6, 0, binding.current_assets().filtered(
                lambda a: a.scope_hash == new_hash).ids)] if binding else [],
            'manual_forked_from_id': old_art.id})
        art.message_post(body=_('%(r)s；舊指紋那篇仍供其他方案使用：%(o)s',
                                r=reason, o=old_art.display_name))
        if changed:
            art.knowledge_propose('text', note=_('畫面改版，步驟區塊依新指紋分岔'))
        else:
            # 文字與上線版相同：圖拍好就以「純重拍」自動上線、接手本方案的 slide
            art.manual_waiting_shots = True
            self._manual_refresh_article(package, art)
        return art

    @api.model
    def _manual_block_for_hash(self, package, old_blk, new_hash, tmpl, token, cache, stop):
        """既有步驟區塊在新指紋下的版本：同分岔線已有就沿用，否則請 AI 只改差異。

        ☠️ 同指紋下「別條分岔線」的區塊不默默拿來用：那是指紋收斂，要走合併提案、
          人工確認（_manual_propose_merges），不是對帳時自己決定。
        回傳區塊；AI 判定不必改字 → 回傳 old_blk；預算已停 → None。
        """
        key = (old_blk.id, new_hash)
        if key in cache:
            return cache[key]
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        feature = old_blk.feature_id
        lineage = old_blk._manual_ancestors()
        at_hash = Block.search([('feature_id', '=', feature.id),
                                ('fingerprint', '=', new_hash),
                                ('state', '!=', 'retired')], order='id')
        res = at_hash.filtered(lambda b: b.derived_from_id == old_blk or b in lineage)[:1]
        if not res and self.env['corpaas.knowledge.article'].sudo().search_count([
                ('feature_id', '=', feature.id), ('fingerprint', '=', new_hash),
                ('step_block_ids', 'in', old_blk.ids)]):
            res = old_blk
        if not res:
            if stop['ai']:
                return None
            res = self._manual_fork_block(package, old_blk, new_hash, tmpl, token) or old_blk
        cache[key] = res
        return res

    @api.model
    def _manual_fork_block(self, package, old, new_hash, tmpl, token):
        """以既有步驟區塊為底請 AI 只改差異；文字不需改回 False。"""
        FP = self.env['corpaas.knowledge.fingerprint'].sudo()
        feature = old.feature_id

        def found(scope_hash):
            fp = FP.search([('feature_id', '=', feature.id), ('scope_hash', '=', scope_hash)],
                           order='computed_at desc', limit=1) if scope_hash else FP
            return json.loads(fp.found_json or '[]') if fp else []
        data = self.env['corpaas.knowledge.ai'].ask(
            'manual_fork', prompts.fork_prompt(
                self._manual_feature_dict(feature, package), old.html, found(old.fingerprint),
                found(new_hash), tmpl.steps() if tmpl else []),
            package=package, refresh_token=token, record=old)
        data = ai_dict(data, 'manual_fork')
        if not data.get('changed'):
            return False
        html = manual_lib.steps_to_html(ai_html_steps(data.get('steps'), 'manual_fork'),
                                        old.anchor)
        fork = self.env['corpaas.knowledge.step_block'].sudo().create({
            'name': ai_text(data.get('title')) or old.name, 'feature_id': feature.id,
            'fingerprint': new_hash, 'html': html, 'derived_from_id': old.id,
            'sequence': old.sequence})
        fork.knowledge_propose('new', note=_('畫面改版分岔：%s') % ai_text(data.get('reason')))
        return fork

    @api.model
    def _manual_propose_merges(self, features):
        """指紋收斂（同功能、同指紋有兩份以上）→ 合併提案，人工確認。"""
        if not features:
            return self.env['corpaas.knowledge.step_block.merge']
        Merge = self.env['corpaas.knowledge.step_block.merge'].sudo()
        out = Merge
        for keep, others in self.env['corpaas.knowledge.step_block'].sudo()._find_converged(
                features):
            out |= Merge._propose(keep, others)
        return out

    @api.model
    def _manual_step_block_for(self, package, feature, tmpl, token, cache, stop):
        """新文章的步驟區塊：同功能×指紋已有就共用；只有別的指紋的 → 以它為底分岔（B7）；
        一份都沒有才請 AI 從頭寫。"""
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        scope = tmpl.fingerprint
        if not scope:
            return Block
        block = Block.search([('feature_id', '=', feature.id), ('fingerprint', '=', scope),
                              ('state', '!=', 'retired')],
                             order='published_rev_no desc, id', limit=1)
        if block:
            return block
        same = self.env['corpaas.knowledge.article'].sudo().search(
            [('feature_id', '=', feature.id), ('fingerprint', '=', scope),
             ('state', '!=', 'retired')], limit=1)
        blocks = same.step_block_ids.filtered(lambda b: b.feature_id == feature)
        if blocks:
            return blocks
        src = Block.search([('feature_id', '=', feature.id), ('state', '!=', 'retired')],
                           order='published_rev_no desc, id desc', limit=1)
        if src:
            return self._manual_block_for_hash(package, src, scope, tmpl, token, cache,
                                               stop) or Block
        data = self.env['corpaas.knowledge.ai'].ask(
            'manual_step_block', prompts.step_block_prompt(
                self._manual_feature_dict(feature, package), tmpl.steps(), tmpl.shot_names(),
                tmpl.elements_list()),
            package=package, refresh_token=token, record=tmpl)
        data = ai_dict(data, 'manual_step_block')
        steps = ai_html_steps(data.get('steps'), 'manual_step_block')
        block = Block.create({'name': ai_text(data.get('title')) or feature.name,
                              'feature_id': feature.id, 'fingerprint': scope})
        html = manual_lib.steps_to_html(steps, block.anchor)
        block.html = html
        block.knowledge_propose('new', note=_('AI 起草步驟區塊'))
        return block

    @api.model
    def _manual_write_scenario(self, package, scenario, feature, capability, blocks, token):
        """情境區塊：回傳 (標題, HTML)。★ 帶入既有步驟區塊，禁止重寫步驟。"""
        steps_html = ''.join(b.html or '' for b in blocks)
        fdict = self._manual_feature_dict(feature, package)
        cls = feature.class_for(package) if package else None
        if cls:
            # ★ 分類寫在情境說明（每個方案一篇），不寫進跨方案共用的步驟區塊：方案核心因方案而異
            fdict['class'] = cls.as_payload()
        data = self.env['corpaas.knowledge.ai'].ask(
            'manual_scenario', prompts.scenario_prompt(
                {'name': scenario.name, 'narrative': scenario.narrative},
                scenario.glossary_map(), fdict,
                {'name': capability.name, 'pain': capability.pain,
                 'outcome': capability.outcome} if capability else {},
                steps_html),
            package=package or None, refresh_token=token, record=scenario)
        data = ai_dict(data, 'manual_scenario')
        if not isinstance(data.get('html'), str):
            raise ValueError('AI（manual_scenario）沒有給 html 字串')
        return ai_text(data.get('title')), manual_lib.clean_html(data['html'])

    @api.model
    def _manual_draft_article(self, package, feature, scenario, cap, tmpl, token, cache, stop):
        block = self._manual_step_block_for(package, feature, tmpl, token, cache, stop)
        if not block:
            return None
        title, html = self._manual_write_scenario(package, scenario, feature, cap, block,
                                                  token)
        binding = tmpl.binding_for(scenario)
        assets = binding.current_assets().filtered(
            lambda a: a.scope_hash == tmpl.fingerprint) if binding else []
        art = self.env['corpaas.knowledge.article'].sudo().create({
            'name': title or feature.name, 'feature_id': feature.id,
            'scenario_id': scenario.id, 'capability_id': cap.id if cap else False,
            'fingerprint': tmpl.fingerprint, 'step_block_ids': [(6, 0, block.ids)],
            'scenario_html': html, 'shot_binding_id': binding.id if binding else False,
            'asset_ids': [(6, 0, assets.ids)] if binding else []})
        art.knowledge_propose('new', note=_('AI 起草新文章'))
        return art

    # ------------------------------------------------------------------
    # 下架（逐方案，B8）
    # ------------------------------------------------------------------
    @api.model
    def _manual_retire_removed(self, package, events):
        """這個方案的功能消失（且不是改名）→ 只撤下這個方案的發佈位置（取消發佈，不刪）。

        所有方案都沒有了（feature.missing）才整篇文章下架。
        """
        Rename = self.env['corpaas.knowledge.rename'].sudo()
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        renamed = events.filtered(lambda e: e.type == 'rename_candidate').mapped('feature_id')
        for ev in events.filtered(lambda e: e.type == 'feature_removed' and e.feature_id):
            feature = ev.feature_id
            if (ev.package_id and ev.package_id != package) or feature.is_present_in(package):
                continue
            if feature in renamed or Rename.search_count(
                    [('old_feature_id', '=', feature.id),
                     ('state', 'in', ('proposed', 'accepted'))]):
                continue
            pls = Placement.search([('article_id.feature_id', '=', feature.id),
                                    ('package_id', '=', package.id),
                                    ('manual_retired', '=', False)])
            pls._manual_retire()
            pls.mapped('channel_id')._knowledge_request_sync()
            if feature.missing:
                self._knowledge_feature_gone(feature)

    @api.model
    def _manual_retire_orphans(self, package):
        """方案拿掉情境、功能不再是候選 → 撤下這個方案的位置（slide 取消發佈，不刪）。

        ★ 功能從方案消失的情況不在這裡處理：要先看改名候選（_manual_retire_removed）。
        """
        if not package.product_tmpl_id:
            return
        channel = self.env['slide.channel'].sudo().with_context(active_test=False).search(
            [('knowledge_product_tmpl_id', '=', package.product_tmpl_id.id)], limit=1)
        if not channel:
            return
        memo, doomed = {}, self.env['corpaas.knowledge.placement'].sudo()
        for pl in channel.knowledge_placement_ids.filtered(lambda p: not p.manual_retired):
            if pl.package_id and pl.package_id != package:
                continue
            art = pl.article_id
            if not art.feature_id.is_present_in(package):
                continue
            if not self._manual_article_status(art, package, memo)[0]:
                doomed |= pl
        if doomed:
            doomed._manual_retire()
            channel._knowledge_request_sync()

    # ------------------------------------------------------------------
    # help API
    # ------------------------------------------------------------------
    @api.model
    def _manual_public_url(self, slide):
        base = (self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.public_base_url') or '').rstrip('/')
        url = slide.website_url or ''
        if not base:
            return url
        parsed = urlparse(url)
        return base + (parsed.path or '/') + ('?%s' % parsed.query if parsed.query else '')

    @api.model
    def _knowledge_help_links(self, package, matches, query, ctx):
        """★ 依「有沒有上線中的位置」挑文章，不看狀態：送審中、失效中的文章，
        舊版照樣在線上，連結也要照樣給。"""
        res = list(super()._knowledge_help_links(package, matches, query, ctx) or [])
        if not matches or not package.product_tmpl_id:
            return res
        Article = self.env['corpaas.knowledge.article'].sudo()
        channel = self.env['slide.channel'].sudo().search(
            [('knowledge_product_tmpl_id', '=', package.product_tmpl_id.id)], limit=1)
        if not channel:
            return res
        seen = {r.get('url') for r in res}
        for feature, _score in matches:
            arts = Article.search([('feature_id', '=', feature.id),
                                   ('scenario_id', 'in', package.knowledge_scenario_ids.ids),
                                   ('published_rev_no', '>', 0)])
            # ★ 核心提供的 D5 參數（所有角色的 scope_hash）；租戶端落在其中之一就不算分歧
            fingerprint = feature.sudo().help_fingerprint(package) or {}
            groups = ctx.get('groups')
            if groups is not None:
                # ★ 同一功能多個情境時，先給「情境角色與使用者群組重疊最多」的那篇：
                #   倉管問到出貨，應該先看到倉管角色拍的畫面。
                have = set(groups)

                def overlap(art):
                    want = set()
                    for role in art.scenario_id.all_roles():
                        want |= {g.strip() for g in (role.group_xmlids or '').splitlines()
                                 if g.strip()}
                    return len(have & want)
                arts = arts.sorted(key=lambda a: -overlap(a))
            for art in arts:
                pl = art.placement_ids.filtered(
                    lambda p: p.channel_id == channel and p._manual_is_live())[:1]
                if not pl:
                    continue
                live = art.step_block_ids.filtered('published_rev_no')
                block = live.filtered(lambda b: b.feature_id == feature)[:1] or live[:1]
                url = self._manual_public_url(pl.slide_id)
                if block:
                    url += '#%s' % block.anchor
                if url in seen:
                    continue
                seen.add(url)
                res.append({
                    'feature_key': feature.feature_key, 'title': pl.slide_id.name or art.name,
                    'url': url, 'kind': 'manual', 'scenario': art.scenario_id.name,
                    'anchor': block.anchor or '',
                    'fingerprint': fingerprint,
                })
        return res

    # ------------------------------------------------------------------
    # 功能點生命週期
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_covered_features(self, package, features):
        """有上線中位置（這個方案的 channel）的文章所說明的功能點。"""
        res = set(super()._knowledge_covered_features(package, features) or ())
        if not features or not package.product_tmpl_id:
            return res
        arts = self.env['corpaas.knowledge.article'].sudo().search([
            ('feature_id', 'in', features.ids), ('published_rev_no', '>', 0)])
        for art in arts:
            if any(p.package_id == package and p._manual_is_live() for p in art.placement_ids):
                res.add(art.feature_id.id)
        return res

    @api.model
    def _knowledge_rename_feature(self, old, new):
        res = super()._knowledge_rename_feature(old, new)
        for model in ('corpaas.knowledge.article', 'corpaas.knowledge.step_block',
                      'corpaas.knowledge.shot_template',
                      'corpaas.knowledge.step_block.merge',
                      'corpaas.knowledge.manual.rebase'):
            Model = self.env[model].sudo().with_context(active_test=False)
            Model.search([('feature_id', '=', old.id)]).write({'feature_id': new.id})
        return res

    @api.model
    def _knowledge_feature_gone(self, feature):
        """功能消失：所有方案都沒有了 → 文章下架；還有方案在用 → 只撤下沒有它的方案的位置。"""
        res = super()._knowledge_feature_gone(feature)
        arts = self.env['corpaas.knowledge.article'].sudo().search(
            [('feature_id', '=', feature.id), ('state', '!=', 'retired')])
        if feature.missing:
            # ☠️ 系統流程：以觸發 refresh 的人執行，他不一定是知識核准者 → 不走 action_retire
            arts._knowledge_retire()
            return res
        gone = arts.mapped('placement_ids').filtered(
            lambda p: p.package_id and not feature.is_present_in(p.package_id))
        gone._manual_retire()
        gone.mapped('channel_id')._knowledge_request_sync()
        return res

    @api.model
    def _knowledge_check_feature_ref(self, feature):
        if super()._knowledge_check_feature_ref(feature):
            return True
        return bool(self.env['corpaas.knowledge.article'].sudo().search_count(
            [('feature_id', '=', feature.id), ('state', '!=', 'retired')])
            or self.env['corpaas.knowledge.shot_template'].sudo().search_count(
                [('feature_id', '=', feature.id)]))
