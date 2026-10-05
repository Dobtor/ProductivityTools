# -*- coding: utf-8 -*-
"""說明庫的截圖總覽（D2）：每個畫面一格縮圖與狀態，一眼看出空白頁、錯誤、定位失敗。

★ 實機 2026-10-05：要判斷 96 張截圖能不能用，只能把圖一張張下載下來做縮圖拼版才看得出
  35 張是空白引導頁——審核的人在控制台裡看不到這些。
"""
from html import escape

from odoo import _, fields, models

#: 失敗原因 → 簡短標籤（給總覽用；完整訊息在繫結上）
REASONS = (
    ('空白引導頁', '空白頁'), ('錯誤對話框', '錯誤對話框'), ('找不到示範資料', '缺示範資料'),
    ('非示範資料', '非示範資料'), ('button[name', '按鈕找不到'), ('o_notebook', '分頁找不到'),
    ('Timeout', '元素逾時'),
)


def reason_label(error):
    for needle, label in REASONS:
        if needle in (error or ''):
            return label
    return (error or '').strip().splitlines()[0][:40] if error else ''


class KnowledgeSandboxOverview(models.Model):
    _inherit = 'corpaas.knowledge.sandbox'

    shots_overview_html = fields.Html(string='截圖總覽', compute='_compute_shots_overview',
                                      sanitize=False)
    shots_ok = fields.Integer(string='截圖成功', compute='_compute_shots_overview')
    shots_failed = fields.Integer(string='截圖失敗', compute='_compute_shots_overview')

    def _overview_bindings(self):
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks']
        return hooks._manual_relevant_bindings(self.package_id).filtered(
            lambda b: b.scenario_id == self.scenario_id) if self.package_id else \
            self.env['corpaas.knowledge.shot_binding']

    def _compute_shots_overview(self):
        for rec in self:
            try:
                bindings = rec._overview_bindings()
            except Exception:  # noqa: BLE001 — 總覽失敗不擋表單
                bindings = self.env['corpaas.knowledge.shot_binding']
            ok = bindings.filtered(lambda b: b.state == 'ok')
            rec.shots_ok = len(ok)
            rec.shots_failed = len(bindings) - len(ok)
            rec.shots_overview_html = rec._render_overview(bindings)

    def _render_overview(self, bindings):
        cells = []
        order = {'failed': 0, 'pending': 1, 'ok': 2}
        for b in bindings.sorted(lambda x: (order.get(x.state, 3), x.feature_id.name or '')):
            assets = b.current_assets()
            badge = {'ok': ('text-bg-success', _('成功')), 'failed': ('text-bg-danger', _('失敗')),
                     'pending': ('text-bg-secondary', _('待拍'))}.get(b.state, ('', b.state))
            note = reason_label(b.last_error) if b.state != 'ok' else (
                _('有標註找不到') if b.last_error else '')
            imgs = ''.join(
                '<a href="/web/image/%d" target="_blank"><img src="/web/image/%d/320x200" '
                'style="width:160px;height:100px;object-fit:cover;object-position:top;'
                'border:1px solid #ddd;border-radius:4px;margin:2px"/></a>'
                % (a.attachment_id.id, a.attachment_id.id) for a in assets[:3] if a.attachment_id)
            cells.append(
                '<div style="display:inline-block;vertical-align:top;width:340px;margin:6px;'
                'padding:6px;border:1px solid #eee;border-radius:6px">'
                '<div><span class="badge %s">%s</span> <b>%s</b></div>'
                '<div class="text-muted small">%s</div><div>%s</div></div>'
                % (badge[0], escape(badge[1]), escape(b.feature_id.name or ''), escape(note),
                   imgs or '<span class="text-muted small">%s</span>' % escape(_('沒有截圖'))))
        if not cells:
            return '<p class="text-muted">%s</p>' % escape(_('還沒有截圖。'))
        return '<div>%s</div>' % ''.join(cells)
