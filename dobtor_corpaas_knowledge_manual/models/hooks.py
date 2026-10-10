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

from odoo.addons.dobtor_corpaas_knowledge.models.feature import ROUTE_MEMBER, ROUTE_VISITOR
from odoo.addons.dobtor_corpaas_knowledge.services import (hub_client, phash, remote, scripts,
                                                           shooter)

from ..services import failure_policy, manual_lib, prompts, rule_scripts
from .placement import sync_batch

_logger = logging.getLogger(__name__)

AI_ERRORS = (hub_client.HubError, remote.RemoteError, ValueError, KeyError, TypeError)
#: 同一個繫結連續 AI 修補的上限；超過就停在 failed 等人處理（action_reset）
MAX_REPAIRS = 3
#: 截圖程式在定位失敗時附上的畫面資訊（有這行就多給一次修補）
SCREEN_HINT = '看得到的按鈕'
#: 截圖程式回報「說明庫後台沒有載入」的錯誤開頭（與 shot_runner/run.py 的 BACKEND_DOWN 相同）
BACKEND_DOWN = '後台沒有載入'


def login_mode(url, navigations=()):
    """訪客開 /web/login 最後停在哪：standard 標準登入頁／popup 首頁彈窗／redirect 被導到別頁。

    ☠️ 實機：彈窗網址 /?popup=login 只是中途經過，最後停在 /——要連經過的網址一起看。"""
    url = url or ''
    if 'popup=login' in url or any('popup=login' in (n or '') for n in navigations or ()):
        return 'popup'
    path = url.split('://', 1)[-1].split('/', 1)[-1].split('?')[0]
    return 'standard' if path.rstrip('/').endswith('web/login') else 'redirect'


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
        out = {'key': feature.feature_key, 'name': feature.name, 'kind': feature.kind,
               'model': feature.model, 'menu_path': feature.menu_path,
               'action_xmlid': feature.action_xmlid, 'button_name': feature.button_name,
               'delta': delta}
        if feature.kind == 'route':
            from odoo.addons.dobtor_corpaas_knowledge.models.feature import (
                route_audience, route_path)
            out.update(anchor=route_path(feature.anchor), audience=route_audience(feature.anchor),
                       front_menus=[m for m in (feature.front_menus or '').splitlines() if m])
        return out

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
            # ★ 同時屬於多個能力時看模組（銷售訂單畫面也被採購能力收了，不能取第一個）
            own = package._knowledge_best_capability(sel.feature_id, caps)
            if sel.capability_id:
                cap = sel.capability_id if sel.capability_id in caps else own
                if not cap:
                    continue
            else:
                cap = own or Cap
            out.setdefault(sel.feature_id, cap)
        for cap in caps:
            for feature in cap.feature_ids:
                if feature not in out:
                    out[feature] = package._knowledge_best_capability(feature, caps) or cap
        renamed_to = self.env['corpaas.knowledge.rename'].sudo().search(
            [('state', '=', 'proposed')]).mapped('new_feature_id')
        # ★ 沒被改過的官方畫面不寫文章（K21）：說明連到 Odoo 官方文件，不重寫一份——
        #   除非方案勾了「原生畫面也製作操作說明」（帶客戶認識原生功能的方案）。
        return {f: c for f, c in out.items()
                if (f.model or f.kind == 'route') and f not in renamed_to
                and f.is_present_in(package)
                and package._knowledge_documents_feature(f)}

    @api.model
    def _manual_sorted_candidates(self, package):
        """起草／拍攝順序：依能力順序（聯絡人 → 產品 → 銷售 → …），章內再看使用量（D1）。

        ★ 不再只依使用量：會計畫面的使用量最高，預算用完時上線的幾乎全是會計，
          初次接觸的人看不到「報價 → 訂單 → 出貨 → 發票 → 收款」這條主線。
          共通操作（沒有能力）排最後。"""
        return sorted(self._manual_candidates(package).items(),
                      key=lambda kv: ((kv[1].sequence, kv[1].id) if kv[1] else (10 ** 6, 0),
                                      -(kv[0].attr_for(package, 'usage_score') or 0), kv[0].id))

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
        """準備範本 → 只拍要拍的（R4）→ 每批（預設 20 個畫面）拍完就提交 → AI 修補失敗的。

        ★ 每批提交（A1）：中途失敗或被中斷，已拍好的不會跟著回滾；重跑時它們的輸入簽章
          沒變，自然被略過。
        """
        res = super()._knowledge_shoot(package, sandbox, events, ctx)
        token = ctx.get('token')
        stop = ctx.setdefault('manual_ai_stopped', {'ai': False})
        stop['run_id'] = ctx.get('run_id')
        stats = ctx.setdefault('stats', {})
        # ★ 所有說明庫共用同一個 ctx：上一個情境的健檢結果不能帶到這一個
        ctx.pop('manual_role_down', None)
        ctx.pop('manual_backend_down', None)
        if not self._manual_backend_preflight(sandbox, ctx):
            return res
        try:
            # 示範資料現況（名稱、狀態）＋精靈模型：寫／修腳本與挑示範資料要用
            sandbox.sudo().refresh_demo_state(self._manual_seed(sandbox.scenario_id))
            self._manual_commit()
        except Exception as e:  # noqa: BLE001 — 讀不到就照舊只給 xmlid
            _logger.warning('[knowledge.manual] 讀取示範資料現況失敗：%s', e)
        stats['templates_rule'] = stats.get('templates_rule', 0) + (
            self._manual_prepare_templates(package, sandbox, token, stop) or 0)
        self._manual_commit()
        # 迭代：權限缺口換角色、定位缺口重拍（把那些繫結設回待拍）
        stats['gaps_fixed_shot'] = stats.get('gaps_fixed_shot', 0) + (
            self._manual_fix_shot_gaps(package, sandbox, ctx) or 0)
        self._manual_commit()
        todo = self._manual_bindings_to_shoot(package, sandbox, events, ctx)
        relevant = self._manual_relevant_bindings(package).filtered(
            lambda b: b.scenario_id == sandbox.scenario_id)
        stats['shots_planned'] = stats.get('shots_planned', 0) + len(todo)
        stats['shots_skipped'] = stats.get('shots_skipped', 0) + max(
            0, len(relevant.filtered(lambda b: b.state == 'ok')) - len(todo & relevant))
        if not todo:
            return res
        size = max(1, int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.shot_batch_size', 20) or 20))
        failed = self.env['corpaas.knowledge.shot_binding']
        canary = max(1, int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.shot_canary_size', 5) or 5))
        batch_list = self._manual_canary_first(list(todo), canary)
        # ★ 先拍前哨批（不同角色各一張起跳），之後每批拍完就看：同一個非腳本錯誤累積到門檻就整批停
        chunks = [batch_list[:canary]] + [batch_list[i:i + size]
                                          for i in range(canary, len(batch_list), size)]
        shot = self.env['corpaas.knowledge.shot_binding']
        for ids in chunks:
            if not ids:
                continue
            chunk = self.env['corpaas.knowledge.shot_binding'].browse([b.id for b in ids])
            failed |= self._manual_run_batch(package, sandbox, chunk, token, ctx)
            shot |= chunk
            self._manual_commit()
            self._manual_check_cancel(ctx)
            if ctx.get('manual_backend_down'):
                break
            # 健檢跳過（還是待拍）的不算：只看真的拍了的
            taken = shot.filtered(lambda b: b.state in ('ok', 'failed'))
            errors = [b.last_error for b in taken if b.state == 'failed' and b.last_error]
            halt = failure_policy.halt_reason(errors, len(taken), canary)
            if halt:
                left = len(batch_list) - len(shot)
                stats['shots_halted'] = stats.get('shots_halted', 0) + left
                _logger.warning('[knowledge.manual] %s 整批提前終止：%s 出現 %s 次（已拍 %s，未拍 %s）',
                                package.display_name, halt[0], halt[1], len(shot), left)
                break
        stats['shots_ok'] = stats.get('shots_ok', 0) + len(todo.filtered(
            lambda b: b.state == 'ok'))
        stats['shots_failed'] = stats.get('shots_failed', 0) + len(todo.filtered(
            lambda b: b.state == 'failed'))
        self._manual_record_failures(sandbox.scenario_id, relevant, stats)
        self._manual_repair_bindings(package, failed, token, stop)
        for key in ('skipped_env', 'skipped_same'):
            n = stop.pop(key, 0)
            if n:
                stats['repair_' + key] = stats.get('repair_' + key, 0) + n
        try:
            stats['gaps_path'] = self._manual_sync_path_gaps(package, sandbox)
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge.manual] 流程路徑缺口失敗：%s', e)
        self._manual_commit()
        return res

    @api.model
    def _manual_access_diagnosis(self, sandbox, login, error, url, cache):
        """存取錯誤：到說明庫唯讀查原因（權限清單、記錄規則、公司），回一句話（計畫第 26 項）。"""
        import re
        if not login or '存取錯誤' not in (error or '') or not hasattr(sandbox, 'diagnose_access'):
            return ''
        m = re.search(r'\(([a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)+)\)', error)
        if not m:
            return ''
        model = m.group(1)
        rid = None
        u = re.search(r'/odoo/%s/(\d+)' % re.escape(model), url or '')
        if u:
            rid = int(u.group(1))
        key = (login, model, rid)
        if key not in cache:
            try:
                cache[key] = sandbox.diagnose_access(login, model, rid)[1]
            except Exception as e:  # noqa: BLE001 — 診斷失敗不影響拍攝
                _logger.info('[knowledge.manual] 存取診斷失敗 %s：%s', key, e)
                cache[key] = ''
        return cache[key]

    @api.model
    def _manual_canary_first(self, bindings, canary):
        """前哨批放最前面：每個登入角色先挑一張，再補到 canary 張（各角色的問題第一批就看得到）。"""
        first, seen = [], set()
        for b in bindings:
            role = b.login_role()
            if role not in seen and len(first) < canary:
                first.append(b)
                seen.add(role)
        for b in bindings:
            if len(first) >= canary:
                break
            if b not in first:
                first.append(b)
        return first + [b for b in bindings if b not in first]

    @api.model
    def _manual_backend_preflight(self, sandbox, ctx):
        """拍攝前先登入一次：說明庫的後台打不開就不寫腳本、不拍、不叫 AI（回傳 False）。

        ☠️ 實機：社群電商方案的說明庫後台動作區不渲染，87 張全部逾時，
          探索、寫情境、寫步驟、修腳本照樣跑完，一輪燒掉 $25 一張圖都沒有。"""
        from odoo.addons.dobtor_corpaas_knowledge.services import txn
        if txn.in_tests(self.env) and not self.env.context.get('kb_test_preflight'):
            return True   # 其他測試的 run_shots 假資料不含這次登入
        sb = sandbox.sudo()
        logins = json.loads(sb.role_logins or '{}')
        login = logins.get('admin') or next(iter(logins.values()), None)
        if not login:
            return True
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        shots = [{'id': 'preflight', 'login': login, 'password': sb.password, 'steps': []}]
        pkg = getattr(sandbox, 'package_id', None)
        pkg = pkg if pkg is not None and hasattr(pkg, 'knowledge_profile') else None
        if pkg and pkg.knowledge_profile().get('website'):
            # 方案檔案：訪客實際開一次登入頁，看登入方式（標準頁／首頁彈窗／被導走）
            shots.append({'id': 'login_probe', 'login': None, 'frontend': True, 'password': '',
                          'steps': [{'goto': {'url': '/web/login'}}, {'wait': {'ms': 800}}]})
        # ★ 健檢（計畫第 27 項）：每個角色先登入一次；登不進去的角色這輪不拍、不送修
        for code, user in logins.items():
            if user != login:
                shots.append({'id': 'role_%s' % code, 'login': user, 'password': sb.password,
                              'frontend': code == ROUTE_MEMBER, 'steps': []})
        try:
            result, _files = shooter.run_shots(self.env, sandbox, shots, settings)
        except (shooter.ShotError, remote.RemoteError):
            return True   # 執行環境的錯照舊由批次處理
        got = (result or {}).get('shots') or {}
        probe = got.get('login_probe') or {}
        down = {code: (got.get('role_%s' % code) or {}).get('error') or '' for code in logins
                if logins[code] != login and not (got.get('role_%s' % code) or {}).get('ok')
                and 'role_%s' % code in got}
        if down:
            ctx['manual_role_down'] = down
            st = ctx.setdefault('stats', {})
            st['roles_down'] = st.get('roles_down', 0) + len(down)
            _logger.warning('[knowledge.manual] 健檢：角色登不進去 %s', down)
        if pkg:
            health = {'roles_down': {k: v[:200] for k, v in down.items()},
                      'residual': (json.loads(sb.purge_report or '{}') or {}).get('residual') or {}
                      if hasattr(sb, 'purge_report') else {},
                      'checked': fields.Datetime.to_string(fields.Datetime.now())}
            vals = {'health': health}
            if probe.get('ok'):
                vals['login_mode'] = login_mode(probe.get('url'), probe.get('navigations'))
            pkg._knowledge_update_profile(vals)
        error = (got.get('preflight') or {}).get('error') or ''
        if not error.startswith(BACKEND_DOWN):
            return True
        ctx['manual_backend_down'] = True
        ctx.setdefault('stats', {})['shots_backend_down'] = 1
        _logger.warning('[knowledge.manual] 說明庫 %s 後台打不開，本輪不拍：%s',
                        getattr(sandbox, 'display_name', ''), error[:1500])
        return False

    @staticmethod
    def _manual_failure_kind(error):
        """截圖失敗 → 缺口種類，由 failure_policy.classify 對應（只有一套分類）：
        空白＝示範資料缺口、存取錯誤＝權限缺口、腳本／未知＝定位缺口；
        其他環境錯（登入失敗、非示範資料、系統錯誤）與暫時性錯誤不開缺口。"""
        error = error or ''
        if error.startswith(BACKEND_DOWN):
            return 'backend'
        kind = failure_policy.classify(error)
        if kind == failure_policy.DATA:
            return 'empty'
        if kind == failure_policy.ENVIRONMENT:
            return 'access' if failure_policy.is_access(error) else 'environment'
        if kind == failure_policy.TRANSIENT:
            return 'transient'
        return 'locator'

    @api.model
    def _manual_record_failures(self, scenario, bindings, stats):
        """失敗分類寫進執行紀錄；空白畫面寫回情境，下次 AI 組裝／修正示範資料時優先補。"""
        failed = bindings.filtered(lambda b: b.state == 'failed')
        kinds = {'empty': [], 'access': [], 'locator': [], 'backend': [], 'environment': [],
                 'transient': []}
        for b in failed:
            kinds[self._manual_failure_kind(b.last_error)].append(b.template_id.feature_id.name)
        for k, names in kinds.items():
            stats['shots_failed_%s' % k] = len(names)
        scenario.sudo().shot_gaps = json.dumps(sorted(set(kinds['empty'])), ensure_ascii=False)
        for pkg in scenario.package_ids:
            self._manual_sync_shot_gaps(pkg, bindings)
        return kinds

    @api.model
    def _manual_commit(self):
        """階段作業裡的中途提交（測試裡不提交）。"""
        from odoo.addons.dobtor_corpaas_knowledge.services import txn
        if not txn.in_tests(self.env):
            self.env.cr.commit()

    @api.model
    @api.model
    def _manual_script_mode(self):
        """截圖腳本怎麼產生：rule（預設，規則為主、AI 為輔）／ai（每個畫面請 AI 探索）。"""
        mode = self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.manual_script_mode', 'rule')
        return 'ai' if mode == 'ai' else 'rule'

    def _manual_prepare_templates(self, package, sandbox, token, stop):
        """步驟 1：這個方案目前指紋還沒有範本 → 以同功能的舊範本複製（不叫 AI），
        一份都沒有 → 規則產生（規則模式）或 AI 探索；這個情境還沒有繫結 → 沿用／AI 挑示範資料。

        ★ 規則模式下，AI 探索出來、在這個情境拍失敗的舊範本也改用規則重寫（A2）。
        """
        scenario = sandbox.scenario_id
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        rule_mode = self._manual_script_mode() == 'rule'
        need_rule = []
        for feature, cap in self._manual_sorted_candidates(package):
            package._knowledge_heartbeat('kb_shoot', feature.name)
            if scenario not in self._manual_scenarios_for(package, cap):
                continue
            hashes = self._manual_package_hashes(package, feature)
            if not hashes:
                continue
            try:
                tmpl = Template._for_hashes(feature, hashes)
                if tmpl and rule_mode and tmpl.source == 'ai':
                    b = tmpl.binding_for(scenario)
                    if b and b.state == 'failed':
                        need_rule.append((feature, hashes, tmpl))
                        continue
                if not tmpl:
                    src = Template._latest_for(feature)
                    if src and not (rule_mode and src.source == 'ai'
                                    and src.binding_for(scenario).state == 'failed'):
                        tmpl = self._manual_fork_template(src, hashes)
                    elif rule_mode:
                        need_rule.append((feature, hashes, src))
                        continue
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
        if need_rule:
            return self._manual_rule_templates(package, sandbox, need_rule, token, stop)
        return 0

    # ------------------------------------------------------------------
    # 規則產生截圖腳本（A2）
    # ------------------------------------------------------------------
    @api.model
    def _manual_seed_record(self, scenario, model):
        """情境裡這個模型的第一筆示範記錄 xmlid（動作步驟不算）。"""
        return next((r['xmlid'] for r in self._manual_seed(scenario)
                     if r['model'] == model and not r.get('call')), None)

    @api.model
    def _manual_probe_many(self, sandbox, items):
        """一次無頭瀏覽器跑完多個畫面的探測：{feature.id: {'entry': …, 'record': …}}。

        ★ 一個畫面開一次容器要 20–60 秒；94 個畫面分批（每批 30 個）一起探測。
        """
        logins = json.loads(sandbox.role_logins or '{}')
        if not logins:
            return {}
        scenario = sandbox.scenario_id
        codes = list(logins)
        xids = {f.id: self._manual_seed_record(scenario, f.model) for f, _role in items}
        resolved = sandbox.resolve_xmlids(sorted({x for x in xids.values() if x})) \
            if any(xids.values()) else {}
        shots = []
        for feature, role in items:
            if feature.kind == 'setting' or not feature.action_xmlid:
                continue
            steps = [{'goto': {'action': feature.action_xmlid}}, {'probe': 'entry'}]
            ids = resolved.get(xids.get(feature.id))
            if ids:
                steps += [{'open': {'model': ids[0], 'res_id': ids[1]}}, {'probe': 'record'}]
            shots.append({'id': 'f%s' % feature.id,
                          'login': logins.get(role) or logins.get(codes[0]),
                          'password': sandbox.sudo().password, 'steps': steps})
        out = {}
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        for i in range(0, len(shots), 30):
            batch = shots[i:i + 30]
            try:
                result, _files = shooter.run_shots(self.env, sandbox, batch, settings)
            except (shooter.ShotError, remote.RemoteError) as e:
                _logger.warning('[knowledge.manual] 批次探測失敗：%s', e)
                continue
            for sid, res in (result.get('shots') or {}).items():
                probes = {img['name']: img.get('probe') for img in res.get('images') or []
                          if img.get('is_probe')}
                out[int(sid[1:])] = probes
        return out

    @api.model
    def _manual_rule_templates(self, package, sandbox, items, token, stop):
        """規則產生範本：批次探測 → 依畫面型態組步驟 → 建範本＋繫結；取代的舊 AI 範本封存。
        寫不出來（沒有動作、設定沒有欄位名）才退回 AI 探索。"""
        scenario = sandbox.scenario_id
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        codes = [r.code for r in scenario.all_roles()]
        roled = [(f, rule_scripts.pick_role(f.kind, f.module, codes, anchor=f.anchor))
                 for f, _h, _o in items]
        probes = self._manual_probe_many(sandbox, roled)
        made = 0
        for (feature, hashes, old), (_f, role) in zip(items, roled):
            package._knowledge_heartbeat('kb_shoot', feature.name)
            probe = probes.get(feature.id) or {}
            rec_xid = self._manual_seed_record(scenario, feature.model)
            steps, placeholders = rule_scripts.build_steps(
                {'key': feature.feature_key, 'kind': feature.kind, 'anchor': feature.anchor,
                 'action_xmlid': feature.action_xmlid},
                entry=probe.get('entry'), record=probe.get('record'), has_record=bool(rec_xid))
            if not steps:
                if old or stop['ai']:
                    continue
                try:
                    self._manual_explore(package, sandbox, feature, hashes, token)
                except hub_client.BudgetExceeded:
                    stop['ai'] = True
                except AI_ERRORS as e:
                    _logger.warning('[knowledge.manual] AI 探索失敗 %s：%s', feature.feature_key, e)
                continue
            tmpl = Template.create({
                'feature_id': feature.id, 'steps_json': json.dumps(steps, ensure_ascii=False),
                'login_role': role, 'source': 'rule',
                'derived_from_id': old.id if old else False,
                'note': _('規則產生（畫面：%s）') % ((probe.get('entry') or {}).get('view_type')
                                                  or feature.kind),
                'fingerprint': hashes.get(role) or next(iter(hashes.values()))})
            Binding.create({'template_id': tmpl.id, 'scenario_id': scenario.id,
                            'bindings_json': json.dumps({'rec': rec_xid} if placeholders else {})})
            if old and old.active:
                old.active = False
            made += 1
        return made

    @api.model
    def _manual_fork_template(self, src, hashes):
        """畫面指紋變了：以舊範本的步驟複製一份新指紋的範本（確定性，不叫 AI）。"""
        new_hash = hashes.get(src.login_role) or next(iter(hashes.values()))
        return src.copy({'fingerprint': new_hash, 'derived_from_id': src.id,
                         'repair_count': 0,
                         'note': _('指紋 %(o)s → %(n)s 複製', o=src.fingerprint, n=new_hash)})

    @api.model
    def _manual_demo(self, scenario):
        """給 AI 的示範資料清單：xmlid、模型，加上說明庫裡讀到的名稱與目前狀態。

        ★ 沒有狀態時 AI 分不出草稿與已核准，常把「已核准才有」的按鈕綁到草稿上。"""
        state = self._manual_demo_state(scenario).get('records') or {}
        out = []
        for r in self._manual_seed(scenario):
            if r.get('call'):
                continue
            d = {'xmlid': r['xmlid'], 'model': r['model']}
            info = state.get(r['xmlid']) or {}
            if info.get('missing'):
                continue   # 說明庫裡沒有（重播失敗或被刪）：不給 AI 挑
            for k in ('name', 'state', 'archived'):
                if info.get(k):
                    d[k] = info[k]
            out.append(d)
        return out[:300]

    @api.model
    def _manual_demo_state(self, scenario):
        sb = self.env['corpaas.knowledge.sandbox'].sudo().search(
            [('scenario_id', '=', scenario.id), ('demo_state_json', '!=', False)],
            order='write_date desc', limit=1)
        return sb.demo_state() if sb else {}

    @api.model
    def _manual_flow_brief(self, model):
        """模型的狀態流程（系統量到的）：狀態順序、哪顆按鈕從哪裡推到哪裡、會開哪個精靈。"""
        out = []
        for flow in self.env['corpaas.knowledge.flow'].sudo().search([('model', '=', model)]):
            labels = {st.value: st.label or st.value for st in flow.step_ids}
            moves = []
            for t in flow.transition_ids[:30]:
                m = {'button': t.button_name, 'label': t.button_label}
                if t.from_value:
                    m['from'] = labels.get(t.from_value, t.from_value)
                if t.to_value:
                    m['to'] = labels.get(t.to_value, t.to_value)
                if t.opens_model:
                    m['opens'] = t.opens_model
                moves.append(m)
            out.append({'state_field': flow.state_field,
                        'states': [labels[k] for k in labels], 'buttons': moves})
        return out

    @api.model
    def _manual_binding_fits(self, bindings, scenario):
        """繫結能否直接沿用到另一個情境：情境示範資料的 xmlid 都在，模組 xmlid 一律可用。"""
        seed = {r['xmlid'] for r in self._manual_seed(scenario) if not r.get('call')}
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
                screen=screen, flows=self._manual_flow_brief(feature.model) if feature.model else None),
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
        record_xid = next((r['xmlid'] for r in seed
                           if r['model'] == feature.model and not r.get('call')), None)
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
            if b.state == 'pending' or (b.state == 'ok' and not b.current_assets()):
                out |= b
            elif b.state == 'ok' and b.shot_inputs \
                    and b.shot_inputs != self._manual_shot_inputs(b):
                # ★ 拍攝輸入變了（截圖程式、腳本、角色、示範資料）：增量更新也重拍
                #   ☠️ 實機：截圖程式改成隱藏 Cookie 列，增量更新照樣沿用舊截圖
                out |= b
            elif b.state == 'failed' and b.shot_inputs != self._manual_shot_inputs(b):
                # ★ 失敗的也一樣：截圖程式、腳本、角色、示範資料有變就再拍一次（輸入沒變就不重拍）
                #   ☠️ 實機（社群電商方案）：截圖程式修好按鈕定位，失敗的 12 張要等全量更新才會重拍
                out |= b
            elif full and not (b.state == 'ok' and b.shot_inputs
                               and b.shot_inputs == self._manual_shot_inputs(b)):
                # ★ R4：全量更新不等於全部重拍——輸入簽章沒變的畫面沿用現有截圖
                out |= b
        return out

    @api.model
    def _manual_shot_inputs(self, binding):
        """拍這張圖用到的一切：腳本、佔位符對應、畫面指紋、登入角色、示範資料上線版號、截圖程式。"""
        import hashlib
        tmpl = binding.template_id
        seed_rev = binding.scenario_id.seed_revisions()   # 含資料包的上線版號
        # 繫結用正規化後的（鍵不含大括號）：跟原文一樣的不會變，帶大括號的會變→重拍一次
        data = [tmpl.steps_json, json.dumps(binding.bindings()), binding.roles_json, tmpl.fingerprint,
                tmpl.login_role, seed_rev, shooter.runner_signature()]
        return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False)
                            .encode('utf-8')).hexdigest()[:16]

    @api.model
    def _manual_fail(self, binding, error, result=None, repair=True):
        vals = {'state': 'failed', 'last_error': (error or '')[:4000],
                'last_shot_at': fields.Datetime.now(), 'needs_repair': repair,
                'shot_inputs': self._manual_shot_inputs(binding)}
        if result is not None:
            vals['last_result'] = json.dumps(result, ensure_ascii=False)[:100000]
        binding.write(vals)

    @api.model
    def _manual_run_batch(self, package, sandbox, bindings, token, ctx):
        """步驟 2 後半～4：解析 → 一批拍完 → 採用圖片。回傳失敗、要 AI 修的繫結。"""
        package._knowledge_heartbeat('kb_shoot', _('拍攝 %s 個畫面') % len(bindings))
        Binding = self.env['corpaas.knowledge.shot_binding']
        xmlids = sorted({x for b in bindings for x in b.bindings().values()
                         if isinstance(x, str)})
        resolved_x = sandbox.resolve_xmlids(xmlids) if xmlids else {}
        sb = sandbox.sudo()
        logins = json.loads(sb.role_logins or '{}')
        password = sb.password
        shots, by_id, failed = [], {}, Binding
        transient = sb.demo_state().get('transient') or []
        for b in bindings:
            resolved = {name: resolved_x[x] for name, x in b.bindings().items()
                        if x in resolved_x}
            steps, missing = manual_lib.fill_placeholders(b.template_id.steps(), resolved)
            wizards = manual_lib.wizard_opens(steps, transient)
            if wizards:
                # ★ 精靈是暫存資料，用網址打不開（畫面空白、等元素逾時）：不必拍就知道會失敗
                #   ☠️ 實機（社群電商方案）：/odoo/wallet.charge.wizard/100 等元素逾時，AI 修了 3 次
                self._manual_fail(b, _('腳本用網址打開精靈 %s：精靈（暫存模型）只能按開啟它的按鈕打開，'
                                       '請改成先打開來源單據再按按鈕') % '、'.join(sorted(set(wizards))))
                failed |= b
                continue
            role = b.login_role()
            front = b.template_id.feature_id.kind == 'route'
            if not front and role in (ROUTE_VISITOR, ROUTE_MEMBER):
                # ☠️ 後台畫面不能用網站訪客／會員（入口網站帳號進不了後台，會被導到 /my）：
                #   實機 AI 修腳本把「產生推薦碼」改成會員登入。改用系統管理員拍。
                role = 'admin' if 'admin' in logins else next(
                    (c for c in logins if c not in (ROUTE_VISITOR, ROUTE_MEMBER)), role)
            down = (ctx or {}).get('manual_role_down') or {}
            if role in down:
                # 健檢時這個角色就登不進去：這輪不拍、不送修（留待下次）
                b.write({'state': 'pending', 'needs_repair': False,
                         'last_error': _('健檢：角色「%(r)s」登不進去：%(e)s', r=role, e=down[role][:300])})
                continue
            login = logins.get(role or '') or (
                next(iter(logins.values())) if len(logins) == 1 and not role else None)
            # ★ 佔位符對不到、角色沒帳號：AI 能修（改繫結／改角色），列入修補
            if missing:
                self._manual_fail(b, _('說明庫找不到示範資料：%s') % ', '.join(sorted(missing)))
                failed |= b
                continue
            if front and role == ROUTE_VISITOR:
                login = None   # 網站訪客：不登入
            elif not login:
                self._manual_fail(b, _('說明庫沒有角色「%s」的帳號') % (role or '?'))
                failed |= b
                continue
            sid = 'b%s' % b.id
            shots.append({'id': sid, 'login': login, 'password': password, 'steps': steps,
                          'frontend': front})
            by_id[sid] = b
        if not shots:
            return failed
        if any(rule_scripts.mutates(b.template_id.steps()) for b in by_id.values()):
            # 會按物件按鈕／填欄位的腳本會改到示範資料：下次更新要重建說明庫（R1）
            sandbox.sudo().dirty = True
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        try:
            result, files = shooter.run_shots(self.env, sandbox, shots, settings)
        except (shooter.ShotError, remote.RemoteError) as e:
            # 執行環境的錯（不是腳本的錯）：不叫 AI，下一次 refresh 再拍
            for b in by_id.values():
                b.write({'state': 'pending', 'last_error': str(e)[:4000]})
            return failed
        threshold = int(settings.get('phash_threshold') or 10)
        down = 0
        shots_by_id = {s['id']: s for s in shots}
        diag_cache = {}
        gate = self._manual_gate_prefetch(sandbox, result, by_id)
        for sid, b in by_id.items():
            # 逐張採用：送心跳，否則看門狗只看得到拍攝前的時間
            package._knowledge_heartbeat('kb_shoot', b.template_id.feature_id.name)
            r = (result.get('shots') or {}).get(sid) or {'ok': False, 'error': _('沒有結果')}
            if not r.get('ok') and (r.get('error') or '').startswith(BACKEND_DOWN):
                # 說明庫的後台打不開（執行環境的錯）：不叫 AI 修，留著下次重拍
                b.write({'state': 'pending', 'needs_repair': False,
                         'last_error': (r.get('error') or '')[:4000],
                         'last_shot_at': fields.Datetime.now()})
                down += 1
                continue
            if not r.get('ok'):
                if (r.get('error') or '').startswith('畫面出現錯誤對話框'):
                    self._manual_retire_assets(b)
                err = r.get('error') or ''
                diag = self._manual_access_diagnosis(sandbox, shots_by_id.get(sid, {}).get('login'),
                                                     err, r.get('url'), diag_cache)
                if diag:
                    err = '%s\n診斷：%s' % (err, diag)
                self._manual_fail(b, err, result=r)
                failed |= b
                continue
            empty = [i.get('name') for i in r.get('images') or []
                     if i.get('empty') and not i.get('is_probe')]
            if empty:
                # ★ 空白引導頁不採用：入門說明拍一張「目前沒有資料」沒有意義。
                #   原因幾乎都是示範資料不足（或篩選把資料濾掉），AI 改腳本修不好，不送 AI 修補。
                self._manual_retire_assets(b)
                self._manual_fail(b, _('畫面是空白引導頁（示範資料不足或被篩選濾掉）：%s')
                                  % ', '.join(empty), result=r, repair=False)
                failed |= b
                continue
            if r.get('transitions') and b.template_id.feature_id.model:
                self.env['corpaas.knowledge.flow'].sudo()._knowledge_record_observations(
                    b.template_id.feature_id.model, r['transitions'])
            errors = self._manual_adopt_images(sandbox, b, r.get('images') or [], files,
                                               threshold, gate=gate)
            vals = {'last_result': json.dumps(r, ensure_ascii=False)[:100000],
                    'last_token': token, 'last_shot_at': fields.Datetime.now()}
            if errors:
                self._manual_fail(b, '\n'.join(errors))
                b.write(vals)
                failed |= b
                continue
            # 標註找不到的步驟不算失敗（圖照用），但留在 last_error 讓審稿的人看得到
            warn = '\n'.join(r.get('warnings') or [])[:4000] or False
            vals.update(state='ok', last_error=warn, needs_repair=False, repair_attempts=0,
                        repair_fp=False,
                        shot_scope_hash=b.template_id.fingerprint,
                        shot_inputs=self._manual_shot_inputs(b))
            b.write(vals)
        if down and down == len(by_id):
            # 整批都打不開後台：後面的批次也一樣，停止這一輪拍攝（不再寫腳本、不叫 AI）
            ctx['manual_backend_down'] = True
            ctx.setdefault('stats', {})['shots_backend_down'] = down
        return failed

    @api.model
    def _manual_retire_assets(self, binding):
        """撤下這個繫結目前採用的截圖（重拍確認畫面是空白或錯誤對話框時）：
        不然文章仍配著先前拍到的壞圖。"""
        assets = binding.current_assets()
        if assets:
            assets.sudo().write({'state': 'superseded', 'superseded_at': fields.Datetime.now()})

    @api.model
    def _manual_gate_prefetch(self, sandbox, result, by_id):
        """整批成功的圖一次做 D1 檢查（原本每張圖各開一次 shell）。失敗就回 None，逐張查。"""
        items = {}
        for sid, r in (result.get('shots') or {}).items():
            if sid not in by_id or not r.get('ok'):
                continue
            for img in r.get('images') or []:
                if img.get('records') or img.get('refs'):
                    items['%s|%s' % (sid, img.get('name'))] = (img.get('records') or {}, img.get('refs'))
        if not items:
            return {}
        try:
            return sandbox.gate_bad_records_batch(items)
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge.manual] 整批 D1 檢查失敗，改逐張：%s', e)
            return None

    @api.model
    def _manual_adopt_images(self, sandbox, binding, images, files, threshold, gate=None):
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
            if gate is not None:
                bad = gate.get('b%s|%s' % (binding.id, name)) or []
            else:
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
    def _manual_repair_eligible(self, b):
        """這張會不會被送去 AI 修（與下面迴圈的判斷一致，不寫任何東西）。"""
        if b.state != 'failed' or not b.needs_repair:
            return False
        if failure_policy.classify(b.last_error) not in failure_policy.REPAIRABLE:
            return False
        if b.repair_fp and b.repair_fp == failure_policy.fingerprint(b.last_error):
            return False
        bonus = 1 if SCREEN_HINT in (b.last_error or '') and not b.repair_bonus_used else 0
        return b.repair_attempts < MAX_REPAIRS + bonus

    @api.model
    def _manual_prefetch_repairs(self, package, bindings, token):
        """要修的腳本先平行問 AI（一個範本只問一次），迴圈裡的 ask 直接拿結果。

        ★ 修一張約 30–60 秒；一輪 20 張一個接一個要 10–20 分鐘，是拍攝階段變慢的主因。"""
        todo, seen = [], set()
        for b in bindings.filtered(self._manual_repair_eligible):
            if b.template_id.id in seen:
                continue   # 同一個範本先修的會改到腳本，後面的提示就不一樣了
            seen.add(b.template_id.id)
            try:
                todo.append(('manual_repair', self._manual_repair_prompt(package, b)))
            except Exception as e:  # noqa: BLE001 — 組不出提示就留給迴圈照常處理
                _logger.info('[knowledge.manual] 預先修補略過 %s：%s', b.id, e)
        if len(todo) < 2:
            return 0
        workers = int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.repair_workers', 3) or 3)
        return self.env['corpaas.knowledge.ai'].prefetch(
            todo, package=package, refresh_token=token, workers=max(1, min(workers, 6)))

    @api.model
    def _manual_repair_bindings(self, package, bindings, token, stop):
        if not stop['ai']:
            self._manual_prefetch_repairs(package, bindings, token)
        for b in bindings.filtered(lambda x: x.state == 'failed' and x.needs_repair):
            package._knowledge_heartbeat('kb_shoot', _('修補截圖腳本'))
            if stop['ai']:
                return
            # ★ 每修一張檢查「要求停止」：修腳本一張 0.1 美元，按停止要立刻停
            #   ☠️ 實機：停止只在拍照批次之間檢查，87 張拍完後的修腳本照跑，停不下來多花 $9
            self._manual_check_cancel({'run_id': stop.get('run_id')})
            kind = failure_policy.classify(b.last_error)
            fp = failure_policy.fingerprint(b.last_error)
            if kind not in failure_policy.REPAIRABLE:
                # ★ 環境／資料／暫時性的錯改腳本修不好：不叫 AI（環境→缺口修補換角色或規則，
                #   資料→補示範資料，暫時性→下次原樣重拍）
                vals = {'needs_repair': False}
                if kind == failure_policy.TRANSIENT and b.transient_fp != fp:
                    # 暫時性錯誤原樣重拍一次（另記，不蓋掉「修過」的指紋）
                    vals.update(state='pending', transient_fp=fp)
                b.write(vals)
                stop['skipped_env'] = stop.get('skipped_env', 0) + 1
                continue
            if b.repair_fp and b.repair_fp == fp:
                # ★ 修過一次、再拍還是同一個錯：同一招不用第二次（交給人或規則）
                b.write({'needs_repair': False})
                b.template_id.message_post(body=_(
                    '情境「%(s)s」的截圖修過仍是同一個錯誤，不再請 AI 修：%(e)s',
                    s=b.scenario_id.name, e=(b.last_error or '').split('\n')[0][:200]))
                stop['skipped_same'] = stop.get('skipped_same', 0) + 1
                continue
            # ★ 錯誤附了「畫面看得到的按鈕」（之前的修補都沒有這個資訊）：額外再給一次，只此一次
            #   ☠️ 實機（社群電商方案）：6 張點不到按鈕都已修滿 3 次，畫面上其實是別的按鈕名
            bonus = 1 if SCREEN_HINT in (b.last_error or '') and not b.repair_bonus_used else 0
            if b.repair_attempts >= MAX_REPAIRS + bonus:
                b.write({'needs_repair': False})
                b.template_id.message_post(body=_(
                    '情境「%(s)s」的截圖 AI 已連續修 %(n)s 次仍失敗，請人工處理後按「下次重拍」。',
                    s=b.scenario_id.name, n=b.repair_attempts))
                continue
            try:
                self._manual_repair(package, b, token)
                # 真的修過才記（預算用完中斷不算修過）
                b.write({'repair_fp': fp, 'repair_bonus_used': b.repair_bonus_used
                         or b.repair_attempts > MAX_REPAIRS})
            except hub_client.BudgetExceeded as e:
                _logger.info('[knowledge.manual] 修腳本停止：%s', e)
                stop['ai'] = True
            except AI_ERRORS as e:
                # ★ AI 回覆壞掉也算修過一次：否則每次更新都再付費問同一個錯
                b.write({'repair_attempts': b.repair_attempts + 1, 'repair_fp': fp})
                _logger.warning('[knowledge.manual] 修腳本失敗 %s：%s',
                                b.template_id.display_name, e)

    @api.model
    def _manual_repair_roles(self, binding):
        tmpl = binding.template_id
        return [{'code': r.code, 'name': r.name} for r in binding.scenario_id.all_roles()
                # 後台畫面不讓 AI 改成會員（入口網站帳號進不了後台）
                if tmpl.feature_id.kind == 'route' or r.code not in (ROUTE_MEMBER, ROUTE_VISITOR)]

    @api.model
    def _manual_repair_prompt(self, package, binding):
        tmpl = binding.template_id
        last = json.loads(binding.last_result or '{}')
        return prompts.repair_prompt(
            self._manual_feature_dict(tmpl.feature_id, package), tmpl.steps(), binding.bindings(),
            binding.last_error, last.get('dom_text'), last.get('url'), self._manual_repair_roles(binding),
            self._manual_demo(binding.scenario_id),
            flows=self._manual_flow_brief(tmpl.feature_id.model) if tmpl.feature_id.model else None)

    @api.model
    def _manual_repair(self, package, binding, token):
        """步驟 5：AI 依錯誤修範本／繫結／登入角色；下一次 refresh 才重拍。"""
        tmpl = binding.template_id
        roles = self._manual_repair_roles(binding)
        data = ai_dict(self.env['corpaas.knowledge.ai'].ask(
            'manual_repair', self._manual_repair_prompt(package, binding),
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
        # ★ 已改用系統管理員的（權限缺口換來的）不讓 AI 換回一般角色
        #   ☠️ 實機（社群電商方案）：系統換成 admin 後，AI 修腳本又改回 sales／account，存取錯誤再現
        forced = (json.loads(binding.roles_json or '{}') or {}).get('login_role') == 'admin'
        if role and role in [r['code'] for r in roles] and role != binding.login_role() and not forced:
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
        stop['run_id'] = ctx.get('run_id')
        # ★ 整次 refresh 一個批次：每個 channel 最後只同步＋重新編號一次
        with sync_batch(self.env) as env:
            me = self.with_env(env)
            package = package.with_env(env)
            me._manual_retire_removed(package, events.with_env(env))
            me._manual_retire_orphans(package)
            me._manual_repair_bindings(package, me._manual_relevant_bindings(package),
                                       token, stop)
            me._manual_reconcile(package, token, stop)
            # 單一核准關卡（計畫第 22、23 項）：剛寫好、待審的文章先自審，通過就系統核准上線
            from odoo.addons.dobtor_corpaas_knowledge.services import txn
            pub = bad = 0
            if not txn.in_tests(self.env) or self.env.context.get('kb_test_autopublish'):
                pub, bad = me._manual_auto_publish(package, token, stop)
            if pub or bad:
                stats = ctx.setdefault('stats', {})
                stats['auto_published'] = stats.get('auto_published', 0) + pub
                stats['review_failed'] = stats.get('review_failed', 0) + bad
        self._manual_propose_merges(self.env['corpaas.knowledge.feature'].union(
            *self._manual_candidates(package).keys()))
        try:
            self._manual_public_check(package, ctx.setdefault('stats', {}))
        except Exception as e:  # noqa: BLE001 — 抽查失敗只記錄，不讓更新失敗
            _logger.warning('[knowledge.manual] 前台抽查失敗：%s', e)
        # 迭代：文字缺口先用規則修，修完再記一次現況；發佈缺口重新同步
        try:
            self._manual_sync_text_gaps(package)
            self._manual_fix_text_gaps(package)
            self._manual_fix_publish_gaps(package)
        except Exception as e:  # noqa: BLE001
            _logger.warning('[knowledge.manual] 文字／發佈缺口處理失敗：%s', e)
        return res

    @api.model
    def _manual_public_check(self, package, stats, sample=None):
        """發佈後以未登入身分抽查（通用化第三階段）：頁面 200、有截圖的文章頁面裡有圖。

        結果記在執行紀錄（public_ok／public_failed），失敗的位置寫進 sync_error。"""
        import requests
        from odoo.addons.dobtor_corpaas_knowledge.services import txn
        if txn.in_tests(self.env):
            return None
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        live = Placement.search([('package_id', '=', package.id),
                                 ('manual_retired', '=', False), ('slide_id', '!=', False)])
        live = live.filtered(lambda p: p.slide_id.is_published)
        if not live:
            return None
        sample = sample or int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.public_check_sample', 5) or 5)
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        picks = live.sorted(lambda p: p.synced_at or p.create_date, reverse=True)[:sample]
        # ☠️ 實機：只抽最近更新的幾篇，曾經失敗的那篇沒被抽到，缺口就永遠解不掉 →
        #   有待修（含轉人工）發佈缺口的位置一定重抽，通過了就解除
        gapped = self.env['corpaas.knowledge.gap_item'].sudo().search([
            ('package_id', '=', package.id), ('kind', '=', 'publish'), ('state', '!=', 'resolved'),
            ('res_model', '=', Placement._name)])
        for gap in gapped:
            pl = Placement.browse(gap.res_id).exists()
            if pl and pl in live:
                picks |= pl
            elif not pl or pl.manual_retired:
                gap.resolve(_('發佈位置已撤下或不存在'))
        ok = failed = 0
        for pl in picks:
            # ☠️ 實機：website_url 在有網站網域時是完整網址，再接 base 就變 https://xhttps://x
            url = pl.slide_id.website_url or ''
            if not url.startswith('http'):
                url = base + url
            problem = ''
            try:
                resp = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code != 200:
                    problem = 'HTTP %s' % resp.status_code
                elif pl.article_id.asset_ids and '<img' not in resp.text:
                    problem = _('頁面沒有截圖')
            except requests.RequestException as e:
                problem = str(e)[:200]
            Gap = self.env['corpaas.knowledge.gap_item'].sudo()
            if problem:
                failed += 1
                pl.sync_error = _('前台抽查：%s') % problem
                Gap.note(package, 'publish', problem, scenario=pl.article_id.scenario_id,
                         feature=pl.article_id.feature_id, record=pl)
            else:
                ok += 1
                Gap.search([('res_model', '=', pl._name), ('res_id', '=', pl.id),
                            ('kind', '=', 'publish'), ('state', '!=', 'resolved')]).resolve(
                    _('前台抽查通過'))
        stats['public_ok'] = stats.get('public_ok', 0) + ok
        stats['public_failed'] = stats.get('public_failed', 0) + failed
        return ok, failed

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
        try:
            self._manual_prefetch_drafts(package, token, stop)
        except Exception as e:  # noqa: BLE001 — 預取失敗就逐篇照常問
            _logger.warning('[knowledge.manual] 平行預取失敗：%s', e)
        for feature, cap in self._manual_sorted_candidates(package):
            package._knowledge_heartbeat('kb_outlets', feature.name)
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
            # ★ 起草一篇約一分鐘：逐功能提交，中途失敗已寫好的草稿不會跟著回滾（A1）
            self._manual_commit()
            if stop.get('run_id'):
                self._manual_check_cancel({'run_id': stop['run_id']})

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
        # ★ 截圖還沒成功不起草（迭代：截圖缺口修好的下一輪才寫）——實機 7 篇白起草又被擋下
        b = tmpl.binding_for(scenario)
        if b and b.state == 'failed':
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
            'manual_step_block', self._manual_step_prompt(package, feature, tmpl),
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
    def _manual_flow_context(self, feature):
        """這個畫面在任務流程中的位置（給 AI 寫「完成後會看到」、給文章頂端的流程位置）。

        按鈕：按之前／之後的狀態、會開出的單據；入口畫面：那張單據的狀態順序與後續單據。"""
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        Trans = self.env['corpaas.knowledge.flow.transition'].sudo()
        out = []
        for t in Trans.search([('button_feature_id', '=', feature.id)], order='id'):
            f = t.flow_id
            label = t.display_label()
            handoff = bool(t.opens_flow_id) and t.is_handoff()
            if not label or not (t.to_value or handoff):
                continue   # 查看上游關聯單據的智慧按鈕不是流程上的一步
            item = {'流程': f.name, '按鈕': label}
            if t.from_value:
                item['按之前的狀態'] = f.step_label(t.from_value)
            if t.to_value:
                item['按之後的狀態'] = f.step_label(t.to_value)
            if handoff:
                item['會開出'] = t.opens_flow_id.name
            if item not in out:
                out.append(item)
        if feature.model and feature.kind in ('action', 'menu', 'client'):
            for f in Flow.search([('model', '=', feature.model)], order='id'):
                steps = [s.label or s.value for s in f.step_ids.sorted('sequence') if s.on_statusbar]
                if len(steps) < 2:
                    continue
                item = {'流程': f.name, '狀態順序': ' → '.join(steps)}
                nxt = sorted({t.opens_flow_id.name for t in f.transition_ids
                              if t.opens_flow_id and t.is_handoff()})
                if nxt:
                    item['後續單據'] = nxt
                out.append(item)
        return out[:6]

    @api.model
    def _manual_demo_examples(self, scenario, feature, limit=8):
        """截圖用到的示範單據（含明細）：給情境說明舉實際的名稱與數字。

        參照（__ref__）換成被參照記錄的名稱；只留字串與數字。"""
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        bs = Binding.search([('feature_id', '=', feature.id), ('scenario_id', '=', scenario.id)],
                            order='id desc')
        b = bs.filtered(lambda x: x.state == 'ok')[:1] or bs[:1]
        xids = [x for x in (b.bindings().values() if b else []) if isinstance(x, str)]
        if not xids:
            return []
        try:
            seed = [r for r in self._manual_seed(scenario) if not r.get('call')]
        except Exception:  # noqa: BLE001 — 示範資料還沒核准：不舉例
            return []
        by = {r['xmlid']: r for r in seed}

        def name_of(ref):
            rec = by.get(ref)
            return ((rec.get('values') or {}).get('name') if rec else None) or ref.split('.')[-1]

        def plain(vals):
            out = {}
            for k, v in (vals or {}).items():
                if isinstance(v, str) and v.startswith('__ref__:'):
                    out[k] = name_of(v[len('__ref__:'):])
                elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    out[k] = v
            return out

        out = []
        for x in xids:
            rec = by.get(x) or next((r for k, r in by.items()
                                     if k.split('.')[-1] == x.split('.')[-1]), None)
            if not rec:
                continue
            ref = '__ref__:%s' % rec['xmlid']
            lines = [plain(r.get('values')) for r in seed
                     if ref in (r.get('values') or {}).values()][:limit]
            item = {'model': rec['model'], 'values': plain(rec.get('values'))}
            if lines:
                item['lines'] = lines
            out.append(item)
        return out[:4]

    @api.model
    def _manual_step_prompt(self, package, feature, tmpl):
        return prompts.step_block_prompt(
            self._manual_feature_dict(feature, package), tmpl.steps(), tmpl.shot_names(),
            tmpl.elements_list(), flow_ctx=self._manual_flow_context(feature))

    @api.model
    def _manual_scenario_prompt(self, package, scenario, feature, capability, blocks):
        steps_html = ''.join(b.html or '' for b in blocks)
        fdict = self._manual_feature_dict(feature, package)
        cls = feature.class_for(package) if package else None
        if cls:
            # ★ 分類寫在情境說明（每個方案一篇），不寫進跨方案共用的步驟區塊：方案核心因方案而異
            fdict['class'] = cls.as_payload()
        return prompts.scenario_prompt(
            {'name': scenario.name, 'narrative': scenario.narrative},
            scenario.glossary_map(), fdict,
            {'name': capability.name, 'pain': capability.pain,
             'outcome': capability.outcome} if capability else {},
            steps_html, demo=self._manual_demo_examples(scenario, feature))

    @api.model
    def _manual_prefetch_drafts(self, package, token, stop):
        """起草前平行預取（依賴感知：只對截圖已成功、還沒有文章的功能）。

        兩段：先平行問步驟區塊（建好區塊），再平行問情境說明；之後的對帳迴圈照常起草，
        AI 呼叫直接拿預取結果。回傳預取筆數。"""
        if stop.get('ai'):
            return 0
        Ai = self.env['corpaas.knowledge.ai']
        Template = self.env['corpaas.knowledge.shot_template'].sudo()
        Article = self.env['corpaas.knowledge.article'].sudo()
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        workers = int(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.draft_parallel', 3) or 3)
        need = []   # [(feature, cap, scenario, tmpl)]
        for feature, cap in self._manual_sorted_candidates(package):
            hashes = self._manual_package_hashes(package, feature)
            tmpl = Template._for_hashes(feature, hashes) if hashes else Template
            if not tmpl or not tmpl.fingerprint:
                continue
            for scenario in self._manual_scenarios_for(package, cap):
                b = tmpl.binding_for(scenario)
                if b and b.state == 'ok' and not Article.search_count(
                        [('feature_id', '=', feature.id), ('scenario_id', '=', scenario.id)]):
                    need.append((feature, cap, scenario, tmpl))
        if not need:
            return 0
        fresh = {}
        for feature, _cap, _sc, tmpl in need:
            if not Block.search_count([('feature_id', '=', feature.id),
                                       ('state', '!=', 'retired')]):
                fresh[feature.id] = (feature, tmpl)
        count = Ai.prefetch([('manual_step_block', self._manual_step_prompt(package, f, t))
                             for f, t in fresh.values()], package=package,
                            refresh_token=token, workers=workers)
        cache = {}
        items = []
        for feature, cap, scenario, tmpl in need:
            try:
                block = self._manual_step_block_for(package, feature, tmpl, token, cache, stop)
            except Exception as e:  # noqa: BLE001 — 這篇照常在迴圈裡再試
                _logger.info('[knowledge.manual] 預取步驟區塊失敗 %s：%s', feature.feature_key, e)
                continue
            if block:
                items.append(('manual_scenario',
                              self._manual_scenario_prompt(package, scenario, feature, cap, block)))
        self._manual_commit()
        count += Ai.prefetch(items, package=package, refresh_token=token, workers=workers)
        return count

    @api.model
    def _manual_write_scenario(self, package, scenario, feature, capability, blocks, token):
        """情境區塊：回傳 (標題, HTML)。★ 帶入既有步驟區塊，禁止重寫步驟。"""
        data = self.env['corpaas.knowledge.ai'].ask(
            'manual_scenario',
            self._manual_scenario_prompt(package, scenario, feature, capability, blocks),
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
            'name': manual_lib.clean_title(title or feature.name, scenario.name),
            'feature_id': feature.id,
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
