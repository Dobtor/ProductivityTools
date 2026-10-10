# -*- coding: utf-8 -*-
"""操作說明的缺口：記錄、修補器、真實結果檢查（迭代式架構）。

修補器依缺口類型、由便宜到貴排：
  · 權限（access）：規則找出進得去的角色改用它拍；沒有就改用系統管理員。
  · 定位（locator）：AI 修過的腳本重拍（AI 修補沿用既有 needs_repair 流程）。
  · 示範資料（data）：AI 只針對空白畫面補示範資料（只新增 → 說明庫疊加，不重建）。
  · 文字（text）：規則修標題（去掉內部分類標籤、情境名）；修不掉的留給人。
  · 發佈（publish）：重新同步那張 slide。
每次嘗試記在缺口上，同一缺口到上限（MAX_GAP_ATTEMPTS）轉人工。
"""
import json
import logging

from odoo import _, api, models

from odoo.addons.dobtor_corpaas_knowledge.services import remote, scripts, shooter

from ..services import manual_lib, rule_scripts

_logger = logging.getLogger(__name__)

SHOT_GAP_KINDS = ('data', 'access', 'locator')
#: 截圖失敗分類 → 缺口類型
FAILURE_TO_GAP = {'empty': 'data', 'access': 'access', 'locator': 'locator'}


class KnowledgeHooksGaps(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    # ------------------------------------------------------------------
    # 記錄
    # ------------------------------------------------------------------
    @api.model
    def _manual_sync_shot_gaps(self, package, bindings):
        """截圖繫結 → 缺口：失敗的記（或更新證據），成功的把它的缺口關掉。"""
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        for b in bindings:
            feature = b.template_id.feature_id
            mine = Gap.search([('package_id', '=', package.id),
                               ('res_model', '=', b._name), ('res_id', '=', b.id),
                               ('kind', 'in', SHOT_GAP_KINDS), ('state', '!=', 'resolved')])
            if b.state == 'ok':
                mine.resolve(_('截圖已成功'))
                continue
            if b.state != 'failed':
                continue
            kind = FAILURE_TO_GAP[self._manual_failure_kind(b.last_error)]
            (mine.filtered(lambda g: g.kind != kind)).resolve(_('改判為其他缺口類型'))
            Gap.note(package, kind, b.last_error, scenario=b.scenario_id, feature=feature,
                     record=b)
        return True

    @api.model
    def _manual_sync_text_gaps(self, package):
        """待審文章的文字檢查 → 缺口（截圖沒對應的不算：那是截圖缺口）。"""
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        arts = self.env['corpaas.knowledge.article'].sudo().search([
            ('feature_id.package_ids', 'in', package.id), ('state', '=', 'review')])
        for art in arts:
            problems = [p for p in art._manual_text_problems()
                        if not p.startswith(_('截圖標記沒有對應的圖'))]
            gap = Gap.search([('package_id', '=', package.id), ('kind', '=', 'text'),
                              ('res_model', '=', art._name), ('res_id', '=', art.id),
                              ('state', '!=', 'resolved')], limit=1)
            if problems:
                Gap.note(package, 'text', '；'.join(problems), scenario=art.scenario_id,
                         feature=art.feature_id, record=art)
            elif gap:
                gap.resolve(_('文字檢查已通過'))
        return True

    @api.model
    def _manual_sync_path_gaps(self, package, sandbox):
        """流程路徑覆蓋：說明庫裡沒有單據走到的狀態列步驟 → 示範資料缺口（掛在流程上）。"""
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        flows = self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', package.id)])
        spec = {f.model: f.state_field for f in flows if f.field_type == 'selection'}
        if not spec:
            return 0
        try:
            counts = sandbox._shell(scripts.state_counts_script(spec))
        except remote.RemoteError as e:
            _logger.warning('[knowledge.manual] 流程路徑統計失敗：%s', e)
            return 0
        n = 0
        for f in flows.filtered(lambda f: f.model in counts):
            have = counts.get(f.model) or {}
            missing = [s.label or s.value for s in f.step_ids.sorted('sequence')
                       if s.on_statusbar and not have.get(s.value)]
            entry = f.feature_ids.filtered(lambda x: x.kind == 'action' and x.model == f.model)[:1]
            open_gap = Gap.search([('package_id', '=', package.id), ('kind', '=', 'data'),
                                   ('res_model', '=', f._name), ('res_id', '=', f.id),
                                   ('state', '!=', 'resolved')], limit=1)
            if missing:
                Gap.note(package, 'data', _('流程「%(f)s」沒有走到「%(s)s」的單據',
                                            f=f.name, s='」「'.join(missing)),
                         scenario=sandbox.scenario_id, feature=entry or None, record=f)
                n += 1
            elif open_gap:
                open_gap.resolve(_('流程每個狀態都有單據了'))
        return n

    @api.model
    def _knowledge_scenarios_needing_shots(self, package, events):
        """還有截圖缺口待修的情境也要準備說明庫（迭代的下一輪只拍缺口）。"""
        res = super()._knowledge_scenarios_needing_shots(package, events)
        gaps = self.env['corpaas.knowledge.gap_item'].sudo().search([
            ('package_id', '=', package.id), ('state', '=', 'open'),
            ('kind', 'in', SHOT_GAP_KINDS)])
        # ★ 等 AI 修腳本的（needs_repair）不算：修好會變「待拍」，那時才需要說明庫
        # ☠️ 流程路徑缺口掛的是流程（沒有 needs_repair）：實機整輪更新在準備階段當掉
        actionable = gaps.filtered(
            lambda g: not getattr(g.record(), 'needs_repair', False))
        return res | actionable.mapped('scenario_id')

    # ------------------------------------------------------------------
    # 修補器
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_fix_gaps_before_sandbox(self, package, ctx):
        """示範資料缺口：每個情境請 AI 一次補齊空白畫面要的資料（只新增，說明庫疊加即可）。"""
        res = super()._knowledge_fix_gaps_before_sandbox(package, ctx)
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        gaps = Gap.search([('package_id', '=', package.id), ('state', '=', 'open'),
                           ('kind', '=', 'data')])
        for scenario in gaps.mapped('scenario_id'):
            mine = gaps.filtered(lambda g: g.scenario_id == scenario)
            notes = [g.evidence for g in mine if g.res_model == 'corpaas.knowledge.flow']
            try:
                added = scenario._ai_fill_gaps(package, mine.mapped('feature_id'),
                                               token=ctx.get('token'), notes=notes)
            except Exception as e:  # noqa: BLE001 — 補不了記一次嘗試，下一輪再試
                mine.attempted('ai_seed', str(e)[:300])
                continue
            mine.attempted('ai_seed', _('補了 %s 筆示範資料') % added)
            for g in mine:
                b = g.record()
                if b and b._name == 'corpaas.knowledge.shot_binding' and b.state == 'failed':
                    b.write({'state': 'pending', 'needs_repair': False})
        return res

    @api.model
    def _manual_fix_shot_gaps(self, package, sandbox, ctx):
        """拍攝前：權限缺口改用進得去的角色；定位缺口重拍（AI 修過的腳本）。"""
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        scenario = sandbox.scenario_id
        gaps = Gap.search([('package_id', '=', package.id), ('state', '=', 'open'),
                           ('scenario_id', '=', scenario.id),
                           ('kind', 'in', ('access', 'locator'))])
        if not gaps:
            return 0
        roles = {r.code: [g.strip() for g in (r.group_xmlids or '').splitlines() if g.strip()]
                 for r in scenario.all_roles()}
        access = gaps.filtered(lambda g: g.kind == 'access')
        actions = sorted({g.feature_id.action_xmlid for g in access if g.feature_id.action_xmlid})
        can = {}
        if actions and roles:
            try:
                can = sandbox._shell(scripts.screen_access_script(actions, roles))
            except remote.RemoteError as e:
                _logger.warning('[knowledge.manual] 權限判斷失敗：%s', e)
        from odoo.addons.dobtor_corpaas_knowledge.models.feature import ROUTE_ROLE
        front = set(ROUTE_ROLE.values())
        order = [r.code for r in scenario.all_roles().sorted('sequence')
                 if r.code != 'admin' and r.code not in front]
        fixed = 0
        for g in gaps:
            b = g.record()
            if not b:
                g.resolve(_('截圖繫結已不存在'))
                continue
            if g.kind == 'locator':
                b.write({'state': 'pending'})
                g.attempted('reshoot', _('以目前（AI 修過）的腳本重拍'))
                fixed += 1
                continue
            ok = can.get(g.feature_id.action_xmlid) or []
            current = b.login_role()
            # ★ 已經換過角色仍是存取錯誤（錯在畫面裡的關聯資料，例如聯絡人表單讀付款交易）：
            #   再換一般角色只會一直失敗，直接用系統管理員
            #   ☠️ 實機：業務、採購、會計輪流換，3 張聯絡人截圖一直失敗
            switched = bool(b.roles_json and json.loads(b.roles_json or '{}').get('login_role'))
            pick = None if switched else next((c for c in order if c in ok and c != current), None)
            pick = pick or ('admin' if 'admin' in roles and current != 'admin' else None)
            if not pick:
                g.attempted('rule_role', _('沒有其他角色可用'))
                continue
            b.write({'roles_json': json.dumps({'login_role': pick}), 'state': 'pending'})
            g.attempted('rule_role', _('改用角色 %s 拍') % pick)
            fixed += 1
        return fixed

    @api.model
    def _manual_fix_text_gaps(self, package):
        """文字缺口：規則修標題；修好就關缺口，修不掉記一次嘗試。"""
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        for g in Gap.search([('package_id', '=', package.id), ('state', '=', 'open'),
                             ('kind', '=', 'text')]):
            art = g.record()
            if not art:
                g.resolve(_('文章已不存在'))
                continue
            clean = manual_lib.clean_title(art.name, art.scenario_id.name)
            if clean and clean != art.name:
                art.with_context(knowledge_system_write=True).name = clean
            problems = [p for p in art._manual_text_problems()
                        if not p.startswith(_('截圖標記沒有對應的圖'))]
            if problems:
                g.attempted('rule_title', '；'.join(problems))
            else:
                g.resolve(_('規則修正標題'))
        return True

    @api.model
    def _manual_fix_publish_gaps(self, package):
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        for g in Gap.search([('package_id', '=', package.id), ('state', '=', 'open'),
                             ('kind', '=', 'publish')]):
            pl = g.record()
            if not pl:
                g.resolve(_('發佈位置已不存在'))
                continue
            pl.channel_id._knowledge_request_sync(pl)
            g.attempted('resync', _('重新同步 slide'))
        return True

    # ------------------------------------------------------------------
    # 真實結果檢查：跟拍照同一套探測
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_check_screens(self, package, sandbox, items):
        """用跟拍照一樣的角色帳號、預設篩選打開每個畫面，判斷有沒有內容。

        ★ 實機：唯讀計數說「外包直運」有資料，實拍卻是空白（預設篩選、角色看不到）。
          回傳 {功能鍵: 1 有內容／0 空白／-1 打不開}；說明庫沒有角色帳號才退回唯讀計數。"""
        logins = json.loads(sandbox.role_logins or '{}')
        if not logins or not items:
            return super()._knowledge_check_screens(package, sandbox, items)
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        codes = list(logins)
        shots, keys = [], {}
        for i, (key, xid) in enumerate(items):
            f = Feature.search([('feature_key', '=', key)], limit=1)
            role = rule_scripts.pick_role(f.kind, f.module, codes) if f else codes[0]
            sid = 'c%s' % i
            keys[sid] = key
            shots.append({'id': sid, 'login': logins.get(role) or logins[codes[0]],
                          'password': sandbox.sudo().password,
                          'steps': [{'goto': {'action': xid}}, {'probe': 'entry'}]})
        out = {}
        settings = self.env['res.config.settings'].knowledge_shot_settings()
        for i in range(0, len(shots), 30):
            try:
                result, _files = shooter.run_shots(self.env, sandbox, shots[i:i + 30], settings)
            except (shooter.ShotError, remote.RemoteError) as e:
                _logger.warning('[knowledge.manual] 重播檢查探測失敗，退回唯讀計數：%s', e)
                return super()._knowledge_check_screens(package, sandbox, items)
            for sid, res in (result.get('shots') or {}).items():
                if not res.get('ok'):
                    out[keys[sid]] = -1
                    continue
                probe = next((img.get('probe') for img in res.get('images') or []
                              if img.get('is_probe')), None) or {}
                out[keys[sid]] = 0 if probe.get('empty') else 1
        return out

    @api.model
    def _manual_check_cancel(self, ctx):
        run = self.env['corpaas.knowledge.run'].sudo().browse(ctx.get('run_id') or 0).exists()
        if run:
            run.check_cancel()


class SolutionPackageManualGaps(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_collect_gaps(self):
        """從目前狀態補記缺口（失敗的截圖、待審文章的文字檢查）：缺口模型上線前留下的
        失敗也能進迴圈。"""
        hooks = self.env['corpaas.knowledge.hooks']
        for rec in self:
            bindings = hooks._manual_relevant_bindings(rec)
            hooks._manual_sync_shot_gaps(rec, bindings)
            hooks._manual_sync_text_gaps(rec)
        return True

    def action_knowledge_fix_gaps(self):
        self._knowledge_collect_gaps()
        return super().action_knowledge_fix_gaps()
