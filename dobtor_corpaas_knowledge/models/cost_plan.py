# -*- coding: utf-8 -*-
"""成本規劃器（D3）：更新前先估這次要花多少 AI、預算夠做到哪裡，做不完的留到隔天。

預算＝「單次更新預算」與「AI Hub 來源今日剩餘」取小者（Hub 剩餘由每次呼叫的回應記下，
今天還沒呼叫過就只看單次預算）。工作依能力順序做（起草順序見操作說明出口），
所以預算不夠時被留下的是排在後面的能力，不會全部擠在同一章。
"""
import html as html_mod
import math
from datetime import datetime, time, timedelta

from odoo import _, fields, models



class SolutionPackageCostPlan(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_cost_plan_html = fields.Html(string='成本估算', readonly=True, sanitize=False,
                                           copy=False)
    knowledge_cost_plan_at = fields.Datetime(string='估算時間', readonly=True, copy=False)

    # ------------------------------------------------------------------
    def _knowledge_cost_lines(self, full=False):
        """[{key, label, count, purposes, deferrable}]：這次更新預計的 AI 工作。

        出口模組各自追加（操作說明：探索、修補、起草）。purposes 的單價相加＝一件的成本。
        deferrable：預算不夠時可以留到隔天的（起草類）；不可延後的先扣。"""
        self.ensure_one()
        pending = self.env['corpaas.knowledge.feature'].sudo().search_count(
            [('package_ids', 'in', self.id), ('classify_pending', '=', True)])
        return [{'key': 'classify', 'label': _('AI 歸類新功能（每次最多 80 個一批）'),
                 'count': 1 if pending else 0, 'purposes': ['classify_features'],
                 'deferrable': False, 'note': _('%s 個待歸類') % pending}]

    def _knowledge_cost_plan(self, full=False):
        self.ensure_one()
        Ai = self.env['corpaas.knowledge.ai']
        conf = Ai._conf()
        lines, fixed = [], 0.0
        for line in self._knowledge_cost_lines(full):
            unit = round(sum(Ai.unit_cost(p) for p in line['purposes']), 4)
            line = dict(line, unit=unit, cost=round(unit * line['count'], 2))
            lines.append(line)
            if not line['deferrable']:
                fixed += line['cost']
        hub_left = Ai.hub_cost_left()
        allowed = conf['budget'] if hub_left is None else min(conf['budget'], hub_left)
        room = max(0.0, allowed - fixed)
        deferred = 0
        for line in lines:
            if not line['deferrable'] or not line['count']:
                line['fit'] = line['count']
                continue
            fit = min(line['count'], int(math.floor(room / line['unit']))) if line['unit'] else \
                line['count']
            line['fit'] = fit
            room -= fit * line['unit']
            deferred += line['count'] - fit
        total = round(sum(l['cost'] for l in lines), 2)
        return {'lines': lines, 'total': total, 'budget': conf['budget'],
                'hub_left': hub_left, 'allowed': round(allowed, 2), 'deferred': deferred}

    def _knowledge_cost_plan_render(self, plan):
        esc = html_mod.escape
        rows = ''.join(
            '<tr><td>%s</td><td class="text-end">%s</td><td class="text-end">%s</td>'
            '<td class="text-end">$%.2f</td><td class="text-end">%s</td><td>%s</td></tr>' % (
                esc(l['label']), l['count'], '$%.3f' % l['unit'], l['cost'],
                l.get('fit', l['count']), esc(l.get('note') or ''))
            for l in plan['lines'])
        hub = _('未知（今天還沒呼叫過 AI Hub）') if plan['hub_left'] is None \
            else '$%.2f' % plan['hub_left']
        head = _('預估 $%(t).2f；可用 $%(a).2f（單次預算 $%(b).2f、AI Hub 今日剩餘 %(h)s）',
                 t=plan['total'], a=plan['allowed'], b=plan['budget'], h=hub)
        tail = ''
        if plan['deferred']:
            tail = '<p class="text-warning">%s</p>' % esc(_(
                '預算不夠：%s 件會留到隔天的自動更新接著做（依能力順序，排在後面的先留）。')
                % plan['deferred'])
        return ('<p>%s</p><table class="table table-sm"><thead><tr><th>%s</th>'
                '<th class="text-end">%s</th><th class="text-end">%s</th>'
                '<th class="text-end">%s</th><th class="text-end">%s</th><th>%s</th></tr>'
                '</thead><tbody>%s</tbody></table>%s') % (
            esc(head), esc(_('工作')), esc(_('件數')), esc(_('單價')), esc(_('小計')),
            esc(_('預算內可做')), esc(_('備註')), rows, tail)

    def action_knowledge_cost_plan(self):
        """估算下一次全量更新的 AI 成本（不呼叫 AI、不改內容）。"""
        for rec in self:
            plan = rec._knowledge_cost_plan(full=True)
            rec.sudo().write({'knowledge_cost_plan_html': rec._knowledge_cost_plan_render(plan),
                              'knowledge_cost_plan_at': fields.Datetime.now()})
        return True

    # ------------------------------------------------------------------
    def _knowledge_budget_exhausted(self, token):
        Ai = self.env['corpaas.knowledge.ai']
        left = Ai.hub_cost_left()
        return (left is not None and left <= 0) or \
            Ai.spent(token) >= Ai._conf()['budget'] - 0.01

    @staticmethod
    def _knowledge_minutes_until_tomorrow(now=None, hour=2):
        """距離台北時間明天 hour 點還有幾分鐘（隔天接著做的排程時間）。"""
        now = now or fields.Datetime.now()
        local = now + timedelta(hours=8)
        target = datetime.combine(local.date() + timedelta(days=1), time(hour))
        return max(1, int((target - local).total_seconds() // 60))

    def _knowledge_carry_over(self, run):
        """預算用完、還有沒做完的 AI 工作 → 排一次隔天凌晨的增量更新接著做。"""
        self.ensure_one()
        if not self._knowledge_budget_exhausted(run.token):
            return False
        plan = self._knowledge_cost_plan(full=False)
        left = sum(l['count'] for l in plan['lines'] if l['deferrable'])
        if not left:
            return False
        minutes = self._knowledge_minutes_until_tomorrow()
        self.knowledge_enqueue_refresh(full=False, reason='budget_carryover',
                                       delay_minutes=minutes)
        run.add_stats(carried_over=left)
        try:
            self.message_post(body=_('AI 預算已用完，還有 %s 件待做，已排在明天凌晨接著更新。')
                              % left)
        except Exception:  # noqa: BLE001 — 沒有 chatter 不影響
            pass
        return True
