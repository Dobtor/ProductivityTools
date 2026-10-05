# -*- coding: utf-8 -*-
"""知識更新執行紀錄（A5）：一次更新一筆，記各階段的狀態、耗時、成果與成本。

★ 也是階段作業（A1）的控制中心：盤點、拍攝、出口三張佇列單接力時，靠這筆紀錄傳遞
  token／是否全量／說明庫，失敗的階段可以單獨重跑。
"""
import json

from odoo import _, api, fields, models

RUN_STATES = [('running', '進行中'), ('done', '完成'), ('failed', '失敗')]
STAGES = [('prepare', '盤點與說明庫'), ('shoot', '拍攝'), ('outlets', '出口與收尾')]


class KnowledgeRun(models.Model):
    _name = 'corpaas.knowledge.run'
    _description = '知識更新執行紀錄'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name')
    package_id = fields.Many2one('infrastructure.solution.package', required=True,
                                 ondelete='cascade', index=True, readonly=True)
    token = fields.Char(required=True, index=True, readonly=True)
    reason = fields.Char(string='觸發原因', readonly=True)
    full = fields.Boolean(string='全量', readonly=True)
    state = fields.Selection(RUN_STATES, string='狀態', default='running', required=True,
                             readonly=True, index=True)
    stage = fields.Selection(STAGES, string='目前階段', readonly=True)
    started_at = fields.Datetime(string='開始', default=fields.Datetime.now, readonly=True)
    ended_at = fields.Datetime(string='結束', readonly=True)
    duration_min = fields.Float(string='耗時（分）', compute='_compute_duration')
    sandbox_ids = fields.Many2many('corpaas.knowledge.sandbox', string='說明庫', readonly=True)
    log_json = fields.Text(string='階段紀錄', readonly=True, default='[]',
                           help='[{stage, start, end, seconds, note}]')
    stats_json = fields.Text(string='成果', readonly=True, default='{}')
    error = fields.Text(string='錯誤', readonly=True)
    ai_cost = fields.Float(string='AI 成本（USD）', compute='_compute_ai', digits=(10, 4))
    ai_calls = fields.Integer(string='AI 呼叫次數', compute='_compute_ai')
    summary = fields.Text(string='摘要', compute='_compute_summary')

    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s' % (rec.package_id.display_name or '',
                                  fields.Datetime.to_string(rec.started_at) or '')

    def _compute_duration(self):
        now = fields.Datetime.now()
        for rec in self:
            end = rec.ended_at or now
            rec.duration_min = round((end - rec.started_at).total_seconds() / 60.0, 1) \
                if rec.started_at else 0

    def _compute_ai(self):
        Call = self.env['corpaas.knowledge.ai.call'].sudo()
        for rec in self:
            calls = Call.search([('refresh_token', '=', rec.token)]) if rec.token else Call
            rec.ai_calls = len(calls)
            rec.ai_cost = sum(calls.mapped('cost_usd'))

    def _compute_summary(self):
        labels = {'sandboxes_rebuilt': _('重建說明庫'), 'sandboxes_reused': _('沿用說明庫'),
                  'shots_planned': _('要拍'), 'shots_skipped': _('沿用截圖'),
                  'shots_ok': _('拍成功'), 'shots_failed': _('拍失敗'),
                  'templates_rule': _('規則腳本'), 'articles': _('文章對帳')}
        for rec in self:
            stats = rec.stats()
            rec.summary = '、'.join('%s %s' % (labels.get(k, k), v) for k, v in stats.items())

    def stats(self):
        self.ensure_one()
        try:
            return json.loads(self.stats_json or '{}')
        except ValueError:
            return {}

    def add_stats(self, **counts):
        """累加成果計數。"""
        for rec in self:
            stats = rec.stats()
            for k, v in counts.items():
                stats[k] = stats.get(k, 0) + (v or 0)
            rec.stats_json = json.dumps(stats, ensure_ascii=False)

    def begin_stage(self, stage, note=None):
        for rec in self:
            log = json.loads(rec.log_json or '[]')
            log.append({'stage': stage, 'start': fields.Datetime.to_string(fields.Datetime.now()),
                        'note': note or ''})
            rec.write({'stage': stage, 'log_json': json.dumps(log, ensure_ascii=False)})

    def end_stage(self, note=None):
        now = fields.Datetime.now()
        for rec in self:
            log = json.loads(rec.log_json or '[]')
            if log and not log[-1].get('end'):
                start = fields.Datetime.from_string(log[-1]['start'])
                log[-1].update(end=fields.Datetime.to_string(now),
                               seconds=int((now - start).total_seconds()))
                if note:
                    log[-1]['note'] = note
            rec.log_json = json.dumps(log, ensure_ascii=False)

    def mark_failed(self, error):
        self.end_stage(note=_('失敗'))
        self.write({'state': 'failed', 'error': str(error)[:4000],
                    'ended_at': fields.Datetime.now()})

    def mark_done(self):
        self.end_stage()
        self.write({'state': 'done', 'stage': False, 'ended_at': fields.Datetime.now()})

    def events(self):
        self.ensure_one()
        return self.env['corpaas.knowledge.event'].sudo().search(
            [('refresh_token', '=', self.token)])

    def ctx(self):
        self.ensure_one()
        return {'token': self.token, 'full': self.full, 'reason': self.reason}

    def action_resume(self):
        """失敗的更新從失敗的階段重跑（已完成的階段不重做）。"""
        for rec in self.filtered(lambda r: r.state == 'failed' and r.stage):
            rec.write({'state': 'running', 'error': False, 'ended_at': False})
            rec.package_id._knowledge_enqueue_stage(rec, rec.stage)
        return True


class SolutionPackageRuns(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_run_ids = fields.One2many('corpaas.knowledge.run', 'package_id',
                                        string='更新執行紀錄')
