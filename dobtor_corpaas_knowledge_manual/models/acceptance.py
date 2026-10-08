# -*- coding: utf-8 -*-
"""說明書驗收報告：每次全量更新後，依固定標準檢查發佈成果；全部通過就自動存成範本庫。

★ 不要求逐字相同（文章是 AI 寫的），要求的是結構與品質：清除重跑之後拿同一份報告比，
  通過的項目一樣、數字落在門檻內，就是「一樣好」。
★ 門檻可用系統參數 corpaas_knowledge.acceptance 覆寫（JSON），例如
  {"article_ratio": 0.9, "tutorials": 3}。
★ 只產生報告、不記缺口：驗收沒過的原因（截圖、示範資料、文字）各自已有缺口與修補器，
  這裡再記一次會讓迭代迴圈為了同一件事多跑。
"""
import html as html_mod
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_TARGETS = {'article_ratio': 0.9, 'tutorials': 3}


class SolutionPackage(models.Model):
    _inherit = 'infrastructure.solution.package'

    manual_acceptance_json = fields.Text(readonly=True, copy=False)
    manual_acceptance_ok = fields.Boolean(string='說明書驗收通過', readonly=True, copy=False)
    manual_acceptance_at = fields.Datetime(string='驗收時間', readonly=True, copy=False)
    manual_acceptance_html = fields.Html(string='說明書驗收報告', compute='_compute_manual_acceptance_html',
                                         sanitize=False)

    def _compute_manual_acceptance_html(self):
        esc = html_mod.escape
        for rec in self:
            try:
                checks = json.loads(rec.manual_acceptance_json or '[]')
            except ValueError:
                checks = []
            if not checks:
                rec.manual_acceptance_html = False
                continue
            rows = ''.join(
                '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                    '✅' if c['ok'] else '❌', esc(c['label']), esc(str(c.get('value', ''))),
                    esc(str(c.get('target', '')))) for c in checks)
            rec.manual_acceptance_html = (
                '<table class="table table-sm table-bordered"><thead><tr><th></th><th>%s</th>'
                '<th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
                esc(_('項目')), esc(_('結果')), esc(_('標準')), rows)


class KnowledgeHooks(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _manual_acceptance_targets(self):
        raw = self.env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.acceptance')
        targets = dict(DEFAULT_TARGETS)
        try:
            targets.update(json.loads(raw or '{}') or {})
        except ValueError:
            pass
        return targets

    @api.model
    def _manual_acceptance(self, package):
        """回傳 [{key, label, ok, value, target}]，同時寫回方案；全部通過就存範本庫。"""
        targets = self._manual_acceptance_targets()
        Channel = self.env['slide.channel'].sudo()
        Section = self.env['corpaas.knowledge.channel_section'].sudo()
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        channel = Channel.search([('knowledge_product_tmpl_id', '=', package.product_tmpl_id.id)],
                                 limit=1) if package.product_tmpl_id else Channel
        checks = []

        def add(key, label, ok, value, target):
            checks.append({'key': key, 'label': label, 'ok': bool(ok), 'value': value,
                           'target': target})

        def live(section, kind):
            g = section.guide_slide_ids.filtered(lambda x: x.kind == kind)[:1]
            return bool(g.slide_id and g.slide_id.is_published)

        front = Section.search([('channel_id', '=', channel.id), ('kind', '=', 'front')],
                               limit=1) if channel else Section
        add('front', _('開始之前：本說明怎麼用＋開始前必設定'),
            front and live(front, 'howto') and live(front, 'setup'),
            '、'.join(label for label, kind in (('本說明怎麼用', 'howto'), ('開始前必設定', 'setup'))
                     if front and live(front, kind)) or _('（無）'), _('兩頁都上線'))

        setup = package._manual_guide_data('manual_setup_json') or {}
        missing = [i['label'] for i in setup.get('items') or [] if i.get('required') and not i.get('ok')]
        nomenu = [i['label'] for i in setup.get('items') or []
                  if not i.get('count_only') and not i.get('menu')]
        add('setup_items', _('開始前必設定：必要項目都已設定、每項都有去哪裡設定'),
            setup.get('items') and not missing and not nomenu,
            '；'.join(filter(None, [missing and _('未設定：%s') % '、'.join(missing),
                                    nomenu and _('缺路徑：%s') % '、'.join(nomenu)])) or _('全部符合'),
            _('全部符合'))

        caps = package.knowledge_capability_ids.sorted(lambda c: (c.sequence, c.id))
        ranks = [c._knowledge_rank() for c in caps]
        add('chapter_order', _('章節依做事的上下游排序'), ranks == sorted(ranks),
            ' → '.join(caps.mapped('name')), _('聯絡人、產品 → 銷售 → 採購 → 庫存 → 應收付'))

        sections = channel.knowledge_section_ids.filtered('capability_id') if channel else Section
        lacking = []
        for sec in sections:
            flows = Flow.search([('capability_id', '=', sec.capability_id.id),
                                 ('package_ids', 'in', package.id)]).filtered(
                lambda f: len(f.step_ids.filtered('on_statusbar')) >= 2)
            if not flows or not sec.slide_id.is_published:
                continue
            need = [n for k, n in (('status', _('狀態速查')), ('concept', _('觀念頁')))
                    if not live(sec, k)]
            if not (sec.journey_slide_id and sec.journey_slide_id.is_published):
                need.insert(0, _('整體流程'))
            if need:
                lacking.append('%s（%s）' % (sec.name, '、'.join(need)))
        add('chapter_pages', _('有流程的章節：整體流程、觀念頁、狀態速查都上線'), not lacking,
            '；'.join(lacking) or _('全部符合'), _('全部符合'))

        cands = self._manual_candidates(package)
        expected = sum(len(self._manual_scenarios_for(package, cap)) for cap in cands.values())
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        pls = Placement.search([('package_id', '=', package.id), ('manual_retired', '=', False)])
        live_n = len(pls.filtered(lambda p: p._manual_is_live()))
        ratio = (live_n / expected) if expected else 0
        add('articles', _('上線文章／應有文章'), ratio >= targets['article_ratio'],
            '%s／%s（%.0f%%）' % (live_n, expected, ratio * 100),
            '≥ %.0f%%' % (targets['article_ratio'] * 100))

        bad = [p.article_id.name for p in pls if p._manual_is_live()
               and p.article_id._manual_text_problems()]
        add('text_lint', _('上線文章的文字檢查'), not bad,
            _('%s 篇有問題') % len(bad) if bad else _('0 篇有問題'), _('0 篇'))

        tutorials = sum(1 for sec in sections if live(sec, 'tutorial'))
        want = min(targets['tutorials'], len(sections)) if sections else targets['tutorials']
        add('tutorials', _('情境教學（同一張單據做到底）'), tutorials >= want,
            _('%s 篇') % tutorials, _('≥ %s 篇') % want)

        public = self.env['corpaas.knowledge.gap_item'].sudo().search_count([
            ('package_id', '=', package.id), ('kind', '=', 'publish'), ('state', '!=', 'resolved')])
        add('public', _('前台抽查'), not public, _('%s 個待修') % public, _('0 個待修'))

        ok = all(c['ok'] for c in checks)
        package.write({'manual_acceptance_json': json.dumps(checks, ensure_ascii=False),
                       'manual_acceptance_ok': ok, 'manual_acceptance_at': fields.Datetime.now()})
        self._manual_commit()   # 同上：別讓方案記錄的鎖擋住之後的心跳
        if ok:
            try:
                package._knowledge_save_library(note=_('驗收全部通過，自動存檔'))
            except Exception as e:  # noqa: BLE001
                _logger.warning('[knowledge.manual] 存範本庫失敗：%s', e)
            self._manual_commit()
        return checks

    @api.model
    def _knowledge_dispatch_events(self, package, events, ctx):
        res = super()._knowledge_dispatch_events(package, events, ctx)
        try:
            checks = self._manual_acceptance(package)
            stats = ctx.setdefault('stats', {})
            stats['acceptance_ok'] = sum(1 for c in checks if c['ok'])
            stats['acceptance_failed'] = sum(1 for c in checks if not c['ok'])
        except Exception as e:  # noqa: BLE001 — 驗收失敗只記錄
            _logger.warning('[knowledge.manual] 說明書驗收失敗：%s', e)
        return res
