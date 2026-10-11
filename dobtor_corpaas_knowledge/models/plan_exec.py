# -*- coding: utf-8 -*-
"""核准、展開與流程編排（新架構規格第 10、11 節）。

核准（人工或依自動化等級）→ 展開（依計畫項目建立情境、能力、角色、範圍，不呼叫 AI 判斷）
→ 示範資料（依資料需求）→ 重播檢查通過即由系統核准 → 第一輪更新＝前哨批（T3）
→ 修正輪（每輪更新結束後評估）→ 達標完成／停止條件 → 驗收報告。
"""
import html as html_mod
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .catalog import glossary_text
from ..services import txn

_logger = logging.getLogger(__name__)

PLAN_ROUND_REASON = 'plan_round'


class KnowledgePlanExec(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    # ------------------------------------------------------------------
    # 核准
    # ------------------------------------------------------------------
    def _check_plan_approver(self):
        if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_approver'):
            raise AccessError(_('只有知識核准者可以核准說明書製作計畫。'))

    def action_approve(self):
        self.ensure_one()
        self._check_plan_approver()
        if self.state != 'review':
            raise UserError(_('只有「審閱」中的計畫可以核准。'))
        check = self.run_checks('t2')
        if check.state == 'block':
            raise UserError(_('核准前檢查未通過：%s') % check.blocking_text())
        return self._plan_approve('manual')

    def _plan_approve(self, mode):
        self.ensure_one()
        plan = self.sudo().with_context(knowledge_plan_system=True)
        others = plan.search([('package_id', '=', plan.package_id.id), ('source_type', '=', plan.source_type),
                              ('id', '!=', plan.id), ('state', 'in', ('approved', 'expanding', 'canary',
                                                                      'running', 'done', 'stopped'))])
        others.write({'state': 'superseded'})
        plan.write({'state': 'approved', 'approve_mode': mode, 'approved_at': fields.Datetime.now(),
                    'approved_by': self.env.uid if mode == 'manual' else False})
        plan.message_post(body=_('計畫已%s核准') % (_('人工') if mode == 'manual' else _('自動')))
        plan._plan_materialize()
        plan._plan_start()
        return True

    def _plan_try_auto_approve(self):
        """依方案的自動化等級自動核准（規格第 10 節）。回傳是否核准。"""
        self.ensure_one()
        level = self.package_id.knowledge_automation or 'standard'
        if level == 'conservative' or self.state != 'review':
            return False
        check = self.run_checks('t2')
        if check.state == 'block':
            return False
        results = {r['code']: r['state'] for r in check.results()}
        if self.parent_id:
            if not self._is_minor_change():
                return False
        else:
            if level != 'full' or self.source_type != 'product':
                return False
            if results.get('A6') != 'pass' or len(self.live_items('story')) != 1:
                return False
            if self.cost_estimate and self.budget and self.cost_estimate > self.budget:
                return False
        self._plan_approve('auto')
        return True

    def _is_minor_change(self):
        """輕微變更：只有差異；不動故事與章節結構；預算增加不超過門檻。"""
        self.ensure_one()
        structural = self.item_ids.filtered(lambda i: i.kind in ('story', 'chapter')
                                            and i.change in ('new', 'modify', 'remove'))
        if structural:
            return False
        ratio = float(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.plan_minor_budget_ratio') or 0.1)
        base = self.parent_id.cost_estimate or 0
        return not base or (self.cost_estimate or 0) <= base * (1 + ratio)

    # ------------------------------------------------------------------
    # 展開
    # ------------------------------------------------------------------
    def _plan_materialize(self):
        """依計畫項目建立正式紀錄。照內容建立，不呼叫 AI。"""
        self.ensure_one()
        self.write({'state': 'expanding'})
        roles = self._materialize_roles()
        scenario = self._materialize_story(roles)
        caps = self._materialize_chapters()
        self._materialize_flows(caps)
        self._materialize_removed()
        # 有計畫的方案不再用圈選提案：還在待審的一律排除（範圍由計畫決定）
        self.env['corpaas.knowledge.selection'].sudo().search([
            ('package_id', '=', self.package_id.id), ('state', '=', 'proposed')]).write({'state': 'excluded'})
        self.env['corpaas.knowledge.hooks']._knowledge_plan_materialized(self, scenario)
        return scenario

    def _set_record(self, item, rec):
        item.with_context(knowledge_plan_system=True).write({'res_model': rec._name, 'res_id': rec.id})

    def _materialize_roles(self):
        Role = self.env['corpaas.knowledge.role'].sudo()
        out = Role
        for seq, item in enumerate(self.live_items('role'), 1):
            data = item.content()
            groups = [g for g in data.get('groups') or [] if re.fullmatch(r'[a-z0-9_]+\.[a-z0-9_]+', g or '')]
            code = item.key
            role = Role.search([('code', '=', code)], limit=1)
            if not role:
                role = Role.create({'code': code, 'name': item.name, 'group_xmlids': '\n'.join(groups),
                                    'sequence': seq})
            out |= role
            self._set_record(item, role)
        return out

    def _materialize_story(self, roles):
        """故事 → 情境。同一方案沿用計畫先前建立的情境（改版只更新敘事與用語）。"""
        Sc = self.env['corpaas.knowledge.scenario'].sudo()
        pkg = self.package_id
        item = self.live_items('story')[:1]
        data = item.content() if item else {}
        prev = self.parent_id.live_items('story')[:1].record() if self.parent_id else None
        shared = pkg.knowledge_scenario_ids.filtered(lambda s: not s.knowledge_private_partner_id)
        sc = prev or (self._story_scenario_default(shared[:1]) if shared else Sc)
        vals = {'narrative': data.get('narrative') or False,
                'glossary': glossary_text(data.get('glossary') or {}) or False}
        vals.update(self._story_scenario_extra())
        if sc:
            sc.write(vals)
        else:
            code = self._story_scenario_code()
            sc = Sc.search([('code', '=', code)], limit=1) or Sc.create(dict(
                vals, code=code, name=data.get('model') and '%s（%s）' % (data.get('company') or pkg.display_name,
                                                                          data.get('model'))
                or data.get('company') or pkg.display_name))
        sc.role_ids = [(6, 0, roles.ids)]
        sc.package_ids = [(4, pkg.id)]
        if item:
            self._set_record(item, sc)
        return sc

    def _story_scenario_default(self, shared):
        """沒有前一版時沿用的情境（產品來源沿用方案既有的共用情境；建議書來源覆寫成另建）。"""
        return shared

    def _story_scenario_code(self):
        return 'plan_%s' % self.package_id.id

    def _story_scenario_extra(self):
        """寫進情境的額外欄位（建議書來源覆寫：客戶專屬、適用章節）。"""
        return {}

    def _materialize_chapters(self):
        """章節 → 能力（範本庫有的直接引用），掛到方案；入選的功能點加進能力。"""
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        pkg = self.package_id
        out = {}
        for seq, item in enumerate(self.live_items('chapter'), 1):
            data = item.content()
            prev = None
            if self.parent_id:
                old = self.parent_id.live_items('chapter').filtered(lambda i: i.key == item.key)[:1]
                prev = old.record() if old else None
            cap = prev or (Cap.search([('code', '=', data['library_code'])], limit=1)
                           if data.get('library_code') else Cap)
            cap = cap or Cap._knowledge_find_by_name(item.name)
            if not cap:
                cap = Cap.create({'name': item.name, 'pain': data.get('pain') or False,
                                  'outcome': data.get('outcome') or False})
            cap.package_ids = [(4, pkg.id)]
            feats = self.line_ids.filtered(lambda l: l.item_id == item and l.assignment == 'chapter').mapped(
                'feature_id')
            if feats:
                cap.feature_ids = [(4, f.id) for f in feats]
            if 'sequence' in cap._fields and not cap.sequence:
                cap.sequence = seq * 10
            self._set_record(item, cap)
            out[item.id] = cap
        return out

    def _materialize_flows(self, caps):
        """流程歸到功能點過半所在的章節。"""
        by_feature = {}
        for line in self.line_ids.filtered(lambda l: l.assignment == 'chapter' and l.item_id):
            by_feature[line.feature_id.id] = caps.get(line.item_id.id)
        for flow in self.env['corpaas.knowledge.flow'].sudo().search([('package_ids', 'in', self.package_id.id)]):
            votes = {}
            for f in flow.feature_ids:
                cap = by_feature.get(f.id)
                if cap:
                    votes[cap] = votes.get(cap, 0) + 1
            if votes:
                best = max(votes, key=lambda c: (votes[c], -c.id))
                if flow.capability_id != best:
                    flow.capability_id = best

    def _materialize_removed(self):
        """修訂移除的章節：能力不再掛這個方案（能力本身留著，其他方案可能在用）。"""
        for item in self.item_ids.filtered(lambda i: i.change == 'remove' and i.kind == 'chapter'):
            old = self.parent_id.live_items('chapter').filtered(lambda i: i.key == item.key)[:1] \
                if self.parent_id else None
            cap = old.record() if old else None
            if cap:
                cap.package_ids = [(3, self.package_id.id)]

    # ------------------------------------------------------------------
    # 執行
    # ------------------------------------------------------------------
    def _plan_start(self):
        """展開後啟動：情境還沒有核准的示範資料 → 依資料需求起草（重播檢查通過自動核准、接著更新）；
        已經有 → 直接排更新（前哨批）。"""
        self.ensure_one()
        sc = self.live_items('story')[:1].record() if self.live_items('story') else None
        pkg = self.package_id
        pkg.sudo().write({'knowledge_enabled': True})
        if sc and not sc.published_rev_no:
            self.write({'state': 'expanding'})
            if sc.seed_json:
                sc._enqueue_seed_check()
            else:
                sc._knowledge_auto_draft_seed()
            return True
        self.write({'state': 'canary'})
        self.env['corpaas.knowledge.hooks']._knowledge_plan_apply_instructions(self)
        pkg.knowledge_enqueue_refresh(full=not self.parent_id, reason=PLAN_ROUND_REASON)
        return True

    def _plan_after_seed_check(self, scenario, state):
        """重播檢查結束：通過 → 系統核准示範資料（會自動排更新）；最終失敗 → 停止。"""
        self.ensure_one()
        if self.state != 'expanding':
            return
        if state == 'ok':
            self.write({'state': 'canary'})
            self.env['corpaas.knowledge.hooks']._knowledge_plan_apply_instructions(self)
            if scenario.state == 'review':
                scenario._knowledge_system_approve()
            else:
                self.package_id.knowledge_enqueue_refresh(full=True, reason=PLAN_ROUND_REASON)
        elif state == 'issues' and not scenario._seed_can_retry():
            # 自動修正用完仍有空白畫面：照樣往下跑，空白的由修正輪補資料（前哨批會把關）
            self.message_post(body=_('示範資料仍有問題，自動修正已用完：照樣執行，空白畫面由修正輪補資料'))
            self._plan_after_seed_check(scenario, 'ok')
        elif state == 'failed':
            self._plan_stop(_('示範資料重播檢查失敗（檢查本身沒有做成）'))

    def _plan_after_run(self, run):
        """每輪更新結束後評估：前哨批、達標、停止條件、下一輪。"""
        self.ensure_one()
        if self.state not in ('canary', 'running'):
            return
        if not run.plan_id:
            run.sudo().plan_id = self.id
        metrics = self.env['corpaas.knowledge.hooks']._knowledge_plan_metrics(self)
        prev = json.loads(self.last_metrics_json or '{}') if self.last_metrics_json else {}
        vals = {'last_metrics_json': json.dumps(metrics, ensure_ascii=False), 'rounds': self.rounds + 1}
        self.write(vals)
        icp = self.env['ir.config_parameter'].sudo()
        if self.state == 'canary':
            need = float(icp.get_param('corpaas_knowledge.plan_canary_shot_rate') or 80)
            if metrics.get('shots_total') and metrics.get('shot_rate', 0) < need:
                self._plan_stop(_('前哨批未達標：截圖成功率 %(r).0f%%（門檻 %(n).0f%%）',
                                  r=metrics.get('shot_rate', 0), n=need), canary=True)
                return
            self.write({'state': 'running'})
        if self._targets_met(metrics):
            self._plan_finish()
            return
        if self.budget and self.cost_actual >= self.budget:
            self._plan_stop(_('預算用完（$%(a).2f／$%(b).2f）', a=self.cost_actual, b=self.budget))
            return
        if self.rounds >= (self.max_rounds or 3) + 1:   # 第一輪是前哨批（全量），之後才算修正輪
            self._plan_stop(_('修正輪數已達上限（%s 輪）') % (self.max_rounds or 3))
            return
        if prev and self._no_progress(prev, metrics):
            streak = int(prev.get('no_progress', 0)) + 1
            metrics['no_progress'] = streak
            self.last_metrics_json = json.dumps(metrics, ensure_ascii=False)
            if streak >= int(icp.get_param('corpaas_knowledge.plan_no_progress_rounds') or 2):
                self._plan_stop(_('連續 %s 輪沒有進步') % streak)
                return
        self.package_id.knowledge_enqueue_refresh(full=False, reason=PLAN_ROUND_REASON)

    def _targets_met(self, m):
        if not m.get('shots_total') or not m.get('articles_total'):
            return False
        return m.get('shot_rate', 0) >= self.target_shot_rate and \
            m.get('review_rate', 0) >= self.target_review_rate

    @staticmethod
    def _no_progress(prev, cur):
        return (cur.get('shots_ok', 0) <= prev.get('shots_ok', 0)
                and cur.get('articles_published', 0) <= prev.get('articles_published', 0))

    def _plan_finish(self):
        self.write({'state': 'done', 'stop_reason': False})
        self._plan_report()
        self.message_post(body=_('已達品質目標，計畫完成'))

    def _plan_stop(self, reason, canary=False):
        self.write({'state': 'stopped', 'stop_reason': reason[:250]})
        self._plan_report()
        self.message_post(body=_('計畫停止：%s') % reason)
        if canary:
            # 前哨批未達標：退回審閱＝開一個修訂版本，帶上原因當審閱意見
            nxt = self._plan_new_version('revision', notes=reason, rebuild_ledger=False)
            nxt.message_post(body=_('前哨批未達標，自動建立修訂版本，請依原因調整後再核准'))

    def action_stop(self):
        for rec in self:
            rec._check_plan_approver()
            if rec.state in ('expanding', 'canary', 'running'):
                rec.sudo().with_context(knowledge_plan_system=True)._plan_stop(_('人工停止'))
        return True

    # ------------------------------------------------------------------
    # 驗收報告
    # ------------------------------------------------------------------
    def _plan_report(self):
        self.ensure_one()
        esc = html_mod.escape
        m = self.env['corpaas.knowledge.hooks']._knowledge_plan_metrics(self)
        per = m.get('chapters') or {}
        rows = [
            (_('截圖成功率'), '%.0f%%' % m.get('shot_rate', 0), '≥ %.0f%%' % self.target_shot_rate,
             m.get('shot_rate', 0) >= self.target_shot_rate),
            (_('自審通過（上線）率'), '%.0f%%' % m.get('review_rate', 0), '≥ %.0f%%' % self.target_review_rate,
             m.get('review_rate', 0) >= self.target_review_rate),
            (_('AI 成本'), '$%.2f' % self.cost_actual, '≤ $%.2f（預估 $%.2f）' % (self.budget, self.cost_estimate or 0),
             not self.budget or self.cost_actual <= self.budget),
        ]
        head = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(a), esc(b), esc(c), '✔' if ok else '✘') for a, b, c, ok in rows)
        chap = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(item.name), per.get(str(item.id), {}).get('features', 0), per.get(str(item.id), {}).get('shots_ok', 0),
            per.get(str(item.id), {}).get('published', 0)) for item in self.live_items('chapter'))
        gaps = self.env['corpaas.knowledge.gap_item'].sudo().read_group(
            [('package_id', '=', self.package_id.id), ('state', '!=', 'resolved')], ['kind'], ['kind'])
        exc = '、'.join('%s %s' % (g['kind'], g['kind_count']) for g in gaps) or _('無')
        self.report_html = (
            '<p><b>%s</b>%s</p>'
            '<table class="table table-sm"><tr><th>%s</th><th>%s</th><th>%s</th><th></th></tr>%s</table>'
            '<p><b>%s</b></p><table class="table table-sm"><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>%s</table>'
            '<p><b>%s</b>%s</p>') % (
            esc(_('狀態：')), esc(dict(self._fields['state'].selection).get(self.state, '')
                                  + ('（%s）' % self.stop_reason if self.stop_reason else '')),
            esc(_('指標')), esc(_('達成')), esc(_('目標')), head,
            esc(_('各章覆蓋')), esc(_('章節')), esc(_('功能點')), esc(_('截圖成功')), esc(_('已上線')), chap,
            esc(_('例外清單：')), esc(exc))

    # ------------------------------------------------------------------
    # 下一個版本
    # ------------------------------------------------------------------
    def action_new_version(self):
        self.ensure_one()
        nxt = self._plan_new_version('revision', rebuild_ledger=True)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': nxt.id, 'view_mode': 'form'}

    def _plan_new_version(self, version_type, notes=None, rebuild_ledger=True, instructions=None):
        """建立下一個版本：沿用項目與底稿歸屬（標「沿用」），再依需要重建底稿或直接起草。"""
        self.ensure_one()
        src = self.sudo()
        nxt = src.with_context(knowledge_plan_system=True).create({
            'package_id': src.package_id.id, 'source_type': src.source_type, 'parent_id': src.id,
            'version': (max(src.search([('package_id', '=', src.package_id.id),
                                        ('source_type', '=', src.source_type)]).mapped('version') or [0]) + 1),
            'version_type': version_type, 'reader': src.reader, 'budget': src.budget,
            'target_shot_rate': src.target_shot_rate, 'target_review_rate': src.target_review_rate,
            'target_blank_max': src.target_blank_max, 'max_rounds': src.max_rounds,
            'review_notes': notes or False, 'state': 'ledger'})
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        for item in src.live_items().filtered(lambda i: i.kind not in ('question', 'instruction')):
            Item.create({'plan_id': nxt.id, 'kind': item.kind, 'key': item.key, 'name': item.name,
                         'content_json': item.content_json, 'summary': item.summary, 'evidence': item.evidence,
                         'confidence': item.confidence, 'confirmed': item.confirmed, 'locked': item.locked,
                         'change': 'same'})
        for ins in instructions or []:
            Item.create(dict(ins, plan_id=nxt.id, kind='instruction', change='new'))
        if rebuild_ledger:
            nxt.action_build_ledger()
        else:
            Line = self.env['corpaas.knowledge.scope_line'].sudo().with_context(knowledge_plan_system=True)
            chapters = {i.key: i for i in nxt.item_ids.filtered(lambda i: i.kind == 'chapter')}
            for line in src.line_ids:
                Line.create({'plan_id': nxt.id, 'feature_id': line.feature_id.id, 'module': line.module,
                             'module_category': line.module_category, 'kind': line.kind,
                             'flow_id': line.flow_id.id, 'usage': line.usage,
                             'classification': line.classification, 'has_pack': line.has_pack,
                             'assignment': line.assignment, 'reason': line.reason,
                             'item_id': chapters.get(line.item_id.key).id if line.item_id and
                             chapters.get(line.item_id.key) else False,
                             'confidence': line.confidence, 'by_rule': line.by_rule, 'locked': line.locked})
            for m in src.module_ids:
                m.copy({'plan_id': nxt.id})
            nxt._plan_after_ledger()
        return nxt


class KnowledgeScenarioPlan(models.Model):
    _inherit = 'corpaas.knowledge.scenario'

    def _seed_can_retry(self):
        from .catalog import MAX_SEED_REPAIRS
        self.ensure_one()
        return self.seed_auto_repairs < MAX_SEED_REPAIRS

    def _plan_after_seed_check(self, state):
        plan = self._seed_plan()
        if plan:
            plan._plan_after_seed_check(self, state)


class SolutionPackagePlanExec(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_iterate(self, run):
        """依計畫產出時，輪次由計畫的流程編排決定；沒有計畫照舊（收斂迴圈）。"""
        self.ensure_one()
        plans = self.env['corpaas.knowledge.plan'].sudo().search(
            [('package_id', '=', self.id), ('state', 'in', ('canary', 'running'))])
        if plans:
            for plan in plans:
                plan.with_context(knowledge_plan_system=True)._plan_after_run(run)
            return True
        return super()._knowledge_iterate(run)

    def _knowledge_stage_prepare(self, run):
        plan = self.knowledge_plan_id
        if plan and not run.plan_id:
            run.sudo().plan_id = plan.id
        return super()._knowledge_stage_prepare(run)

    def _knowledge_ai_catalog(self, added, token):
        """依計畫產出時不再歸類能力（新功能點進下一版計畫的底稿）。"""
        if self.knowledge_plan_mode:
            return False
        return super()._knowledge_ai_catalog(added, token)

    def _knowledge_restore_library(self):
        if self.knowledge_plan_mode:
            return {}
        return super()._knowledge_restore_library()

    def _knowledge_tidy_capabilities(self):
        if self.knowledge_plan_mode:
            return {}
        return super()._knowledge_tidy_capabilities()


class KnowledgeHooksPlan(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _knowledge_plan_materialized(self, plan, scenario):
        """計畫展開後（出口模組覆寫，例如說明書模組依底稿決定範圍）。"""
        return True

    @api.model
    def _knowledge_plan_apply_instructions(self, plan):
        """把計畫的內容指示套到出口（說明書模組覆寫）。"""
        return True

    @api.model
    def _knowledge_plan_metrics(self, plan):
        """計畫的執行指標（說明書模組覆寫）：shots_total、shots_ok、shot_rate、articles_total、
        articles_published、review_rate、chapters={item id: {...}}。"""
        return {}


class SolutionPackagePlanRenames(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _knowledge_detect_renames(self, added, removed, token):
        """依計畫產出時，改名候選相似度夠高（同模組同種類）就自動接受，不等人確認。"""
        res = super()._knowledge_detect_renames(added, removed, token)
        if not self.knowledge_plan_mode or not removed:
            return res
        auto = float(self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.rename_auto_threshold') or 0.95)
        cands = self.env['corpaas.knowledge.rename'].sudo().search([
            ('state', '=', 'proposed'), ('old_feature_id', 'in', removed.ids), ('similarity', '>=', auto)])
        cands.filtered(lambda r: r.old_feature_id.model == r.new_feature_id.model)._knowledge_accept()
        return res


class SolutionPackagePlanBackfill(models.Model):
    _inherit = 'infrastructure.solution.package'

    def action_knowledge_plan_backfill(self):
        """依目前已核准的情境、能力、角色與範圍，反推出第一版計畫（移轉用，規格第 20 節）。"""
        for pkg in self:
            if not self.env.user.has_group('dobtor_corpaas_knowledge.group_knowledge_manager'):
                raise AccessError(_('只有知識管理者可以反推計畫。'))
            pkg.sudo()._knowledge_plan_backfill()
        return True

    def _knowledge_plan_backfill(self):
        self.ensure_one()
        Plan = self.env['corpaas.knowledge.plan'].sudo().with_context(knowledge_plan_system=True)
        if Plan.search_count([('package_id', '=', self.id), ('source_type', '=', 'product')]):
            raise UserError(_('方案「%s」已經有計畫，不需要反推。') % self.display_name)
        plan = Plan.create({'package_id': self.id, 'source_type': 'product', 'version': 1,
                            'version_type': 'initial', 'state': 'draft'})
        Item = self.env['corpaas.knowledge.plan.item'].sudo().with_context(knowledge_plan_system=True)
        sc = self.knowledge_scenario_ids.filtered(lambda s: not s.knowledge_private_partner_id)[:1]
        if sc:
            company = ''
            seed = []
            try:
                seed = sc.live_seed()
            except Exception:  # noqa: BLE001 — 沒有核准版就不帶公司名
                seed = []
            for row in seed:
                if row.get('xmlid') == 'base.main_company':
                    company = (row.get('values') or {}).get('name') or ''
            Item.create({'plan_id': plan.id, 'kind': 'story', 'key': 'story', 'name': company or sc.name,
                         'summary': sc.narrative, 'confidence': 'high', 'confirmed': True,
                         'res_model': sc._name, 'res_id': sc.id,
                         'content_json': json.dumps({'company': company or sc.name, 'narrative': sc.narrative,
                                                     'glossary': sc.glossary_map()}, ensure_ascii=False)})
            for seq, role in enumerate(sc.all_roles() if hasattr(sc, 'all_roles') else sc.role_ids, 1):
                Item.create({'plan_id': plan.id, 'kind': 'role', 'key': role.code, 'name': role.name,
                             'sequence': seq, 'confidence': 'high', 'confirmed': True,
                             'res_model': role._name, 'res_id': role.id,
                             'content_json': json.dumps({'groups': (role.group_xmlids or '').split()})})
        chapters = {}
        for seq, cap in enumerate(self.knowledge_capability_ids.sorted(lambda c: (c.sequence, c.id)), 1):
            key = re.sub(r'[^a-z0-9_]+', '_', (cap.code or 'cap_%s' % cap.id).lower()).strip('_')
            chapters[cap.id] = Item.create({
                'plan_id': plan.id, 'kind': 'chapter', 'key': key, 'name': cap.name, 'sequence': seq,
                'summary': '%s → %s' % (cap.pain or '', cap.outcome or ''), 'confidence': 'high',
                'confirmed': True, 'res_model': cap._name, 'res_id': cap.id,
                'content_json': json.dumps({'pain': cap.pain, 'outcome': cap.outcome, 'priority': 'must',
                                            'library_code': cap.code or None}, ensure_ascii=False)})
        plan._ledger_build()
        cands = self.env['corpaas.knowledge.hooks']._manual_candidates(self) \
            if hasattr(self.env['corpaas.knowledge.hooks'], '_manual_candidates') else {}
        Line = self.env['corpaas.knowledge.scope_line'].sudo().with_context(knowledge_plan_system=True)
        for line in plan.line_ids:
            cap = cands.get(line.feature_id)
            item = chapters.get(cap.id) if cap else None
            if item:
                line.write({'assignment': 'chapter', 'item_id': item.id, 'reason': _('現行版本已納入'),
                            'confidence': 'high'})
            elif line.assignment == 'unassigned':
                line.write({'assignment': 'exclude', 'reason': _('現行版本未納入'), 'confidence': 'medium'})
        plan._d4_exclusions()
        plan._d5_cost_quality()
        plan.write({'state': 'done', 'approve_mode': 'manual', 'approved_by': self.env.uid,
                    'approved_at': fields.Datetime.now()})
        plan.message_post(body=_('依現行已核准的情境、能力、角色與範圍反推出第一版計畫'))
        return plan
