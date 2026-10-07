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
    def _knowledge_scenarios_needing_shots(self, package, events):
        """還有截圖缺口待修的情境也要準備說明庫（迭代的下一輪只拍缺口）。"""
        res = super()._knowledge_scenarios_needing_shots(package, events)
        gaps = self.env['corpaas.knowledge.gap_item'].sudo().search([
            ('package_id', '=', package.id), ('state', '=', 'open'),
            ('kind', 'in', SHOT_GAP_KINDS)])
        # ★ 等 AI 修腳本的（needs_repair）不算：修好會變「待拍」，那時才需要說明庫
        actionable = gaps.filtered(lambda g: not (g.record() and g.record().needs_repair))
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
            try:
                added = scenario._ai_fill_gaps(package, mine.mapped('feature_id'),
                                               token=ctx.get('token'))
            except Exception as e:  # noqa: BLE001 — 補不了記一次嘗試，下一輪再試
                mine.attempted('ai_seed', str(e)[:300])
                continue
            mine.attempted('ai_seed', _('補了 %s 筆示範資料') % added)
            for g in mine:
                b = g.record()
                if b and b.state == 'failed':
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
        order = [r.code for r in scenario.all_roles().sorted('sequence') if r.code != 'admin']
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
            pick = next((c for c in order if c in ok and c != current), None) or (
                'admin' if 'admin' in roles and current != 'admin' else None)
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
