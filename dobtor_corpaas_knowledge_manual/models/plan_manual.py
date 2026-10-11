# -*- coding: utf-8 -*-
"""說明書出口接上說明書製作計畫（新架構規格第 11、12 節）。

· 範圍：依計畫的範圍底稿（歸到章節的功能點）產生腳本、截圖、文章；不再看圈選提案。
· 指標：截圖成功率、上線率、各章覆蓋——計畫的前哨批、修正輪、驗收報告依它判斷。
· 內容指示：計畫版本帶的指示，在下一輪先依指示重寫那幾篇，並永久帶進之後的寫作與審稿。
"""
import json
import logging

from odoo import _, api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from ..services import manual_lib
from .hooks import ai_dict, ai_html_steps, ai_text

_logger = logging.getLogger(__name__)

#: 同一個共用步驟區塊最多分岔幾份專屬版本（規格 12.4）
MAX_FORKS = 3


class KnowledgeArticlePlan(models.Model):
    _inherit = 'corpaas.knowledge.article'

    manual_instructions = fields.Text(
        string='人工指示', readonly=True, copy=False,
        help='上線後意見採納的內容指示；之後每次重寫、分岔都帶進提示詞，自審也拿它檢查')
    manual_pending_instruction = fields.Boolean(string='待依指示重寫', readonly=True, copy=False)
    knowledge_plan_item_id = fields.Many2one('corpaas.knowledge.plan.item', string='計畫章節',
                                             compute='_compute_knowledge_plan_item')

    def _compute_knowledge_plan_item(self):
        Line = self.env['corpaas.knowledge.scope_line'].sudo()
        for rec in self:
            plan = rec.scenario_id.package_ids[:1].knowledge_plan_id if rec.scenario_id else False
            line = Line.search([('plan_id', '=', plan.id), ('feature_id', '=', rec.feature_id.id)],
                               limit=1) if plan else Line
            rec.knowledge_plan_item_id = line.item_id

    def _manual_review_prompt(self, package):
        prompt = super()._manual_review_prompt(package)
        extra = []
        plan = package.knowledge_plan_id if package else False
        rules = (plan.story().get('rules') if plan else None) or []
        if rules:
            extra.append('寫作規則（說明書製作計畫）：%s' % json.dumps(rules, ensure_ascii=False)[:800])
        if self.manual_instructions:
            extra.append('本篇必須遵守的人工指示（沒做到要列為問題）：%s' % self.manual_instructions[:1500])
        return prompt + ('\n\n' + '\n'.join(extra) if extra else '')


class KnowledgeStepBlockPlan(models.Model):
    _inherit = 'corpaas.knowledge.step_block'

    instruction_fork = fields.Boolean(string='依指示分岔', readonly=True, copy=False,
                                      help='依人工指示分岔的情境專屬版本：不參與指紋收斂合併')


class KnowledgeHooksPlanManual(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    # ------------------------------------------------------------------
    # 範圍
    # ------------------------------------------------------------------
    @api.model
    def _manual_candidates(self, package):
        plan = package.knowledge_plan_id
        if not plan:
            return super()._manual_candidates(package)
        Cap = self.env['corpaas.knowledge.capability']
        renamed_to = self.env['corpaas.knowledge.rename'].sudo().search(
            [('state', '=', 'proposed')]).mapped('new_feature_id')
        out = {}
        for line in plan.line_ids.filtered(lambda l: l.assignment == 'chapter'):
            f = line.feature_id
            if not (f.model or f.kind == 'route') or f in renamed_to or not f.is_present_in(package):
                continue
            cap = line.item_id.record() if line.item_id else None
            out[f] = cap or Cap
        # 建議書來源的計畫（客戶專屬情境）：它們入選的功能點也要做（只配對客戶專屬情境，見下）
        for prop_plan in self.env['corpaas.knowledge.plan'].sudo().search([
                ('package_id', '=', package.id), ('source_type', '!=', 'product'),
                ('state', 'in', ('approved', 'expanding', 'canary', 'running', 'done', 'stopped'))]):
            for line in prop_plan.line_ids.filtered(lambda l: l.assignment == 'chapter'):
                f = line.feature_id
                if f in out or not (f.model or f.kind == 'route') or f in renamed_to \
                        or not f.is_present_in(package):
                    continue
                cap = line.item_id.record() if line.item_id else None
                out[f] = cap or Cap
        return out

    @api.model
    def _manual_scenarios_for(self, package, capability):
        """客戶專屬情境只說明它的適用章節；共用情境不寫只屬於客戶計畫的章節。"""
        scenarios = super()._manual_scenarios_for(package, capability)
        for sc in scenarios.filtered('knowledge_private_partner_id'):
            if not capability or capability not in sc.knowledge_scope_capability_ids:
                scenarios -= sc
        plan = package.knowledge_plan_id
        if plan and capability:
            product_caps = [i.record() for i in plan.live_items('chapter')]
            if capability not in product_caps:
                scenarios = scenarios.filtered('knowledge_private_partner_id')
        return scenarios

    @api.model
    def _manual_scenario_prompt(self, package, scenario, feature, capability, blocks):
        prompt = super()._manual_scenario_prompt(package, scenario, feature, capability, blocks)
        art = self.env['corpaas.knowledge.article'].sudo().search(
            [('feature_id', '=', feature.id), ('scenario_id', '=', scenario.id),
             ('state', '!=', 'retired'), ('manual_instructions', '!=', False)], limit=1)
        plan = package.knowledge_plan_id if package else False
        rules = (plan.story().get('rules') if plan else None) or []
        extra = ''
        if rules:
            extra += '\n\n★ 寫作規則（說明書製作計畫）：%s' % json.dumps(rules, ensure_ascii=False)[:800]
        if art:
            extra += '\n\n★ 這篇有人工指示，一定要遵守：%s' % art.manual_instructions[:1500]
        return prompt + extra

    # ------------------------------------------------------------------
    # 指標
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_plan_metrics(self, plan):
        res = super()._knowledge_plan_metrics(plan)
        lines = plan.line_ids.filtered(lambda l: l.assignment == 'chapter')
        feats = lines.mapped('feature_id')
        story = plan.live_items('story')[:1].record() if plan.live_items('story') else None
        scenarios = story or plan.package_id.knowledge_scenario_ids.filtered(
            lambda s: not s.knowledge_private_partner_id)
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        Article = self.env['corpaas.knowledge.article'].sudo()
        bindings = Binding.search([('scenario_id', 'in', scenarios.ids)]).filtered(
            lambda b: b.template_id.feature_id in feats)
        arts = Article.search([('scenario_id', 'in', scenarios.ids), ('feature_id', 'in', feats.ids),
                               ('state', '!=', 'retired')])
        ok = bindings.filtered(lambda b: b.state == 'ok')
        pub = arts.filtered(lambda a: a.state == 'published')
        chapters = {}
        for item in plan.live_items('chapter'):
            mine = lines.filtered(lambda l: l.item_id == item).mapped('feature_id')
            chapters[str(item.id)] = {
                'features': len(mine),
                'shots_ok': len(ok.filtered(lambda b: b.template_id.feature_id in mine)),
                'published': len(pub.filtered(lambda a: a.feature_id in mine)),
            }
        res.update({
            'shots_total': len(bindings), 'shots_ok': len(ok),
            'shot_rate': round(100.0 * len(ok) / len(bindings), 1) if bindings else 0.0,
            'articles_total': len(arts), 'articles_published': len(pub),
            'review_rate': round(100.0 * len(pub) / len(arts), 1) if arts else 0.0,
            'exceptions': len(arts.filtered(lambda a: a.state == 'review' and a.manual_review_state == 'fail')),
            'chapters': chapters,
        })
        return res

    # ------------------------------------------------------------------
    # 內容指示
    # ------------------------------------------------------------------
    @api.model
    def _knowledge_plan_apply_instructions(self, plan):
        """計畫的內容指示 → 掛到文章（永久）並標「待依指示重寫」；截圖指示 → 重拍。"""
        res = super()._knowledge_plan_apply_instructions(plan)
        Article = self.env['corpaas.knowledge.article'].sudo()
        Binding = self.env['corpaas.knowledge.shot_binding'].sudo()
        for item in plan.live_items('instruction').filtered(lambda i: i.change == 'new'):
            data = item.content()
            text = (data.get('text') or item.name or '').strip()
            art = Article.browse(data.get('article_id') or 0).exists()
            if data.get('type') == 'shot' and art and art.shot_binding_id:
                art.shot_binding_id.write({'state': 'pending'})
                continue
            if art and text:
                merged = '\n'.join(x for x in [(art.manual_instructions or '').strip(), '・' + text] if x)
                art.write({'manual_instructions': merged, 'manual_pending_instruction': True})
            elif data.get('binding_id'):
                Binding.browse(data['binding_id']).exists().write({'state': 'pending'})
        return res

    @api.model
    def _manual_propose_merges(self, features):
        """依計畫產出的方案：指紋相同的步驟區塊自動合併（規格 15.2），不再等人確認。"""
        merges = super()._manual_propose_merges(features)
        auto = merges.filtered(lambda m: m.state == 'proposed' and any(
            p.knowledge_plan_mode for p in m.feature_id.package_ids))
        for m in auto:
            try:
                with self.env.cr.savepoint():
                    m.action_merge()
            except Exception as e:  # noqa: BLE001 — 合併不了留給人看
                _logger.warning('[knowledge.manual] 自動合併步驟區塊失敗 %s：%s', m.id, e)
        return merges

    @api.model
    def _manual_auto_publish(self, package, token, stop):
        """自審前先處理「待依指示重寫」的文章（已上線的會重新送審）。"""
        try:
            self._manual_apply_pending_instructions(package, token, stop)
        except hub_client.BudgetExceeded:
            stop['ai'] = True
        return super()._manual_auto_publish(package, token, stop)

    @api.model
    def _manual_apply_pending_instructions(self, package, token, stop):
        Article = self.env['corpaas.knowledge.article'].sudo()
        arts = Article.search([('scenario_id', 'in', package.knowledge_scenario_ids.ids),
                               ('manual_pending_instruction', '=', True)])
        for art in arts:
            if stop.get('ai'):
                break
            try:
                self._manual_rewrite_with_instruction(package, art, token)
            except hub_client.BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 — 這篇留到下一輪
                _logger.warning('[knowledge.manual] 依指示重寫失敗 %s：%s', art.display_name, e)

    @api.model
    def _manual_rewrite_with_instruction(self, package, art, token):
        """依人工指示重寫：步驟區塊沒上線過就直接改；已上線且共用 → 分岔成這個情境專屬
        （同一區塊分岔滿 MAX_FORKS 份就改共用版本並送審）；情境說明一起重寫。"""
        feedback = "\n\n★ 這次依人工指示修改，一定要做到：%s" % (art.manual_instructions or '')[:1500]
        Ai = self.env['corpaas.knowledge.ai']
        Block = self.env['corpaas.knowledge.step_block'].sudo()
        tmpl = art.shot_binding_id.template_id
        blocks = art.step_block_ids.filtered(lambda b: b.feature_id == art.feature_id)
        new_blocks = art.step_block_ids - blocks
        for block in blocks:
            if not tmpl:
                new_blocks |= block
                continue
            data = ai_dict(Ai.ask('manual_step_block', self._manual_step_prompt(package, art.feature_id, tmpl)
                                  + feedback, package=package, refresh_token=token, record=tmpl),
                           'manual_step_block')
            steps = ai_html_steps(data.get('steps'), 'manual_step_block')
            target = block
            shared = self.env['corpaas.knowledge.article'].sudo().search_count(
                [('step_block_ids', 'in', block.id), ('id', '!=', art.id), ('state', '!=', 'retired')])
            if block.published_rev_no and shared:
                base = block.derived_from_id or block
                forks = Block.search_count([('derived_from_id', '=', base.id), ('state', '!=', 'retired')])
                if forks < MAX_FORKS:
                    target = Block.create({'name': block.name, 'feature_id': block.feature_id.id,
                                           'fingerprint': block.fingerprint, 'derived_from_id': base.id,
                                           'sequence': block.sequence, 'instruction_fork': True})
            target.write({'name': ai_text(data.get('title')) or target.name,
                          'html': manual_lib.steps_to_html(steps, target.anchor)})
            if target.published_rev_no:
                target.knowledge_propose('text', note=_('依人工指示修改'))
            elif target.state == 'draft':
                target.knowledge_propose('new', note=_('依人工指示分岔'))
            new_blocks |= target
        data = ai_dict(Ai.ask('manual_scenario',
                              self._manual_scenario_prompt(package, art.scenario_id, art.feature_id,
                                                           art.capability_id, new_blocks) + feedback,
                              package=package, refresh_token=token, record=art.scenario_id), 'manual_scenario')
        if isinstance(data.get('html'), str):
            art.with_context(knowledge_system_write=True).write({
                'scenario_html': manual_lib.clean_html(data['html']),
                'step_block_ids': [(6, 0, new_blocks.ids)]})
        art.write({'manual_pending_instruction': False, 'manual_review_input': False})
        if art.state == 'published':
            art.knowledge_propose('text', note=_('依人工指示修改'))
        art.message_post(body=_('依人工指示重寫：%s') % (art.manual_instructions or '')[:500])
        return True
