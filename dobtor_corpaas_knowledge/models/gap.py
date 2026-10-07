# -*- coding: utf-8 -*-
"""缺口（迭代式架構的骨幹）：每個沒達標的產出記一筆，下一輪只處理缺口。

★ 2026-10 從零驗證：一次更新「全部拍、全部寫」，拍不成的畫面照樣起草、靠人逐一發現。
  改成缺口驅動：拍照、文字檢查、前台抽查把未達標記成缺口；下一輪先跑修補器
  （規則 → AI），只重拍、重寫有缺口的；同一缺口修到上限仍未解才交人。
"""
from odoo import _, api, fields, models

GAP_KINDS = [('data', '示範資料缺口'), ('access', '權限不足'), ('locator', '腳本定位'),
             ('text', '文字檢查'), ('publish', '前台發佈')]
GAP_STATES = [('open', '待修'), ('resolved', '已解'), ('human', '轉人工')]
#: 同一個缺口自動修補的次數上限；超過轉人工
MAX_GAP_ATTEMPTS = 3


class KnowledgeGapItem(models.Model):
    _name = 'corpaas.knowledge.gap_item'
    _description = '知識產出缺口'
    _order = 'state, kind, id desc'

    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', ondelete='cascade', index=True)
    feature_id = fields.Many2one('corpaas.knowledge.feature', ondelete='cascade', index=True)
    kind = fields.Selection(GAP_KINDS, string='類型', required=True, index=True)
    state = fields.Selection(GAP_STATES, string='狀態', default='open', required=True,
                             index=True)
    res_model = fields.Char(string='對象模型', help='缺口所在的記錄（截圖繫結、文章、發佈位置）')
    res_id = fields.Integer(string='對象')
    evidence = fields.Text(string='證據')
    attempts = fields.Integer(string='已修次數', readonly=True)
    last_fixer = fields.Char(string='最近的修補', readonly=True)
    fix_note = fields.Text(string='修補紀錄', readonly=True)
    resolved_at = fields.Datetime(string='解決時間', readonly=True)

    @api.model
    def note(self, package, kind, evidence, scenario=None, feature=None, record=None):
        """記一筆缺口；同一對象同類型已有待修的就更新證據（不重複）。"""
        dom = [('package_id', '=', package.id), ('kind', '=', kind),
               ('state', 'in', ('open', 'human')),
               ('scenario_id', '=', scenario.id if scenario else False),
               ('feature_id', '=', feature.id if feature else False)]
        if record:
            dom += [('res_model', '=', record._name), ('res_id', '=', record.id)]
        gap = self.sudo().search(dom, limit=1)
        if gap:
            gap.evidence = (evidence or '')[:4000]
            return gap
        return self.sudo().create({
            'package_id': package.id, 'kind': kind, 'evidence': (evidence or '')[:4000],
            'scenario_id': scenario.id if scenario else False,
            'feature_id': feature.id if feature else False,
            'res_model': record._name if record else False,
            'res_id': record.id if record else 0})

    def resolve(self, note=None):
        for gap in self.filtered(lambda g: g.state != 'resolved'):
            gap.write({'state': 'resolved', 'resolved_at': fields.Datetime.now(),
                       'fix_note': '\n'.join(filter(None, [gap.fix_note, note]))[-4000:]})
        return True

    def attempted(self, fixer, note=None):
        """記一次修補嘗試；到上限轉人工。"""
        for gap in self:
            attempts = gap.attempts + 1
            gap.write({
                'attempts': attempts, 'last_fixer': fixer,
                'state': 'human' if attempts >= MAX_GAP_ATTEMPTS and gap.state == 'open'
                else gap.state,
                'fix_note': '\n'.join(filter(None, [gap.fix_note, '%s：%s' % (
                    fixer, note or '')]))[-4000:]})
        return True

    def record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return None
        return self.env[self.res_model].sudo().browse(self.res_id).exists() or None

    def action_reopen(self):
        """轉人工的缺口處理過（補檔案、改設定）後重新交給系統修。"""
        self.write({'state': 'open', 'attempts': 0})
        return True


class SolutionPackageGaps(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_gap_ids = fields.One2many('corpaas.knowledge.gap_item', 'package_id',
                                        string='缺口')
    knowledge_gap_open = fields.Integer(string='待修缺口', compute='_compute_knowledge_gaps')
    knowledge_gap_human = fields.Integer(string='轉人工缺口', compute='_compute_knowledge_gaps')
    knowledge_max_iterations = fields.Integer(
        string='每日迭代上限', default=3,
        help='一次更新後若還有待修缺口，自動接著跑「只修缺口」的更新；一天最多幾輪（含第一輪）')

    def _compute_knowledge_gaps(self):
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        for rec in self:
            rec.knowledge_gap_open = Gap.search_count([('package_id', '=', rec.id),
                                                       ('state', '=', 'open')])
            rec.knowledge_gap_human = Gap.search_count([('package_id', '=', rec.id),
                                                        ('state', '=', 'human')])

    def _knowledge_iterate(self, run):
        """收斂迴圈：還有待修缺口、今天輪數沒到上限 → 排下一輪「只修缺口」的更新。"""
        self.ensure_one()
        Gap = self.env['corpaas.knowledge.gap_item'].sudo()
        open_gaps = Gap.search_count([('package_id', '=', self.id), ('state', '=', 'open')])
        run.add_stats(gaps_open=open_gaps)
        if not open_gaps:
            return False
        since = fields.Datetime.subtract(fields.Datetime.now(), hours=24)
        today = self.env['corpaas.knowledge.run'].sudo().search_count([
            ('package_id', '=', self.id), ('create_date', '>=', since)])
        if today >= (self.knowledge_max_iterations or 3):
            run.add_stats(iterate_stopped=1)
            return False
        self.knowledge_enqueue_refresh(full=False, reason='gap_fix')
        return True

    def action_knowledge_fix_gaps(self):
        """手動排一輪「只修缺口」的更新。"""
        for rec in self:
            rec.knowledge_enqueue_refresh(full=False, reason='gap_fix')
        return True

    def action_open_knowledge_gaps(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('缺口'),
                'res_model': 'corpaas.knowledge.gap_item', 'view_mode': 'list,form',
                'domain': [('package_id', '=', self.id)],
                'context': {'search_default_open': 1}}
