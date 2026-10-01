# -*- coding: utf-8 -*-
"""本期新增（release note）：同一次 refresh 新增、且已歸入能力的功能點 → AI 起草 → 送審。

★ 一次 refresh 一篇（package × refresh_token 唯一）：事件重送不會重複起草。
★ 預算用完不算失敗：先建草稿、標 ai_pending，下一次 refresh 的 dispatch 再補寫。
★ 錨定到功能點：其中一個功能從方案消失 → 這篇失效，商品頁不再顯示（依上線快照的功能點判斷）。
★ 上線過的一篇改稿再送審時，商品頁照舊顯示上線快照，核准後才換；只有下架或從未上線的不顯示。
★ 發給既有訂戶：已發佈的一篇可開郵件精靈（收件人＝這個方案在用合約的客戶），一律人工按送出。
"""
import json
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from . import html_guard
from .pitch import HTML_RULES, present_features

_logger = logging.getLogger(__name__)


class KnowledgeReleaseNote(models.Model):
    _name = 'corpaas.knowledge.release_note'
    _description = '本期新增（產品行銷）'
    _inherit = ['corpaas.knowledge.marketing.guarded']
    _order = 'published_date desc, id desc'
    _rec_name = 'title'

    product_tmpl_id = fields.Many2one('product.template', string='方案商品', required=True,
                                      ondelete='cascade', index=True)
    package_id = fields.Many2one('infrastructure.solution.package', string='方案',
                                 ondelete='set null', index=True)
    refresh_token = fields.Char(index=True, readonly=True, copy=False)
    title = fields.Char(string='標題', tracking=True)
    body_html = fields.Html(string='內文')
    feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_release_note_feature_rel',
        'note_id', 'feature_id', string='新增功能點')
    published_date = fields.Date(string='發佈日期', copy=False)
    ai_pending = fields.Boolean(string='等待 AI 起草', copy=False, readonly=True)
    live_json = fields.Text(string='上線快照', copy=False, readonly=True)

    _sql_constraints = [
        ('refresh_unique', 'unique(package_id, refresh_token)', '同一次更新只會有一篇本期新增'),
    ]

    def _knowledge_revision_fields(self):
        return ['title', 'body_html', 'feature_ids']

    def _knowledge_requires_review(self, change):
        return True

    def _knowledge_publish(self):
        self.ensure_one()
        if not (self.title or '').strip():
            raise UserError(_('本期新增沒有標題。'))
        pkg = self.package_id
        gone = self.feature_ids - present_features(self.feature_ids, pkg) if pkg else \
            self.feature_ids.filtered('missing')
        if gone:
            raise UserError(_('本期新增提到的功能已從方案消失，請先移除：%s')
                            % '、'.join(gone.mapped('name')))
        self._marketing_sys().write({
            'published_date': self.published_date or fields.Date.context_today(self),
            'live_json': json.dumps({'title': self.title,
                                     'body_html': str(self.body_html or ''),
                                     'feature_ids': self.feature_ids.ids},
                                    ensure_ascii=False),
        })
        return True

    def _knowledge_unpublish(self):
        self._marketing_sys().write({'live_json': False})
        return True

    @api.model
    def _marketing_flag_removed(self, features, package):
        """功能從方案消失 → 引用它的本期新增失效（商品頁不再顯示）。"""
        if not features:
            return self.browse()
        notes = self.sudo().search([('package_id', '=', package.id),
                                    ('feature_ids', 'in', features.ids),
                                    ('state', '=', 'published')])
        for note in notes:
            note.knowledge_mark_stale(_('功能消失：%s') % '、'.join(
                (note.feature_ids & features).mapped('name')))
        return notes

    def _marketing_first_showable(self, package=None):
        """依序第一篇可以上商品頁的：快照提到的功能都還在方案裡（舊快照沒存就看目前的功能點）。"""
        Feature = self.env['corpaas.knowledge.feature'].sudo()
        for note in self:
            live = json.loads(note.live_json or '{}')
            fids = live.get('feature_ids')
            features = Feature.browse(fids).exists() if isinstance(fids, list) \
                else note.feature_ids
            if isinstance(fids, list) and len(features) != len(set(fids)):
                continue
            pkg = note.package_id or package
            if present_features(features, pkg) == features:
                return note
        return self.browse()

    def _website_note(self):
        self.ensure_one()
        live = json.loads(self.live_json or '{}')
        return {'title': live.get('title') or '',
                'body_html': Markup(live.get('body_html') or ''),
                'date': self.published_date}

    # ------------------------------------------------------------------
    # 事件 → 草稿
    # ------------------------------------------------------------------
    @api.model
    def _marketing_classified(self, package, features):
        """已歸入能力的功能點 → {feature: capability}。

        ★ 兩個來源：能力上已掛的功能點；以及同一次 refresh 的 AI 分類提議（selection，
          未排除）——分類剛跑完、還沒人核准，本期新增本來就要送審，先起草不會漏上線。
        """
        caps = package.knowledge_capability_ids
        out = {}
        for f in features:
            cap = f.capability_ids & caps
            if cap:
                out[f] = cap[:1]
        rest = features.filtered(lambda f: f not in out)
        if rest:
            sels = self.env['corpaas.knowledge.selection'].sudo().search([
                ('package_id', '=', package.id), ('kind', '=', 'feature'),
                ('feature_id', 'in', rest.ids), ('capability_id', '!=', False),
                ('state', '!=', 'excluded')])
            for sel in sels:
                out.setdefault(sel.feature_id, sel.capability_id)
        return out

    @api.model
    def _marketing_from_events(self, package, events, ctx):
        token = (ctx or {}).get('token')
        tmpl = package.product_tmpl_id
        if not tmpl:
            return self.browse()
        pending = self.search([('package_id', '=', package.id), ('ai_pending', '=', True),
                               ('state', '=', 'draft')])
        added = events.filtered(lambda e: e.type == 'feature_added'
                                and (not e.package_id or e.package_id == package)).feature_id
        classified = self._marketing_classified(package, added) if added else {}
        note = self.browse()
        if classified and token and not self.search_count(
                [('package_id', '=', package.id), ('refresh_token', '=', token)]):
            note = self.create({
                'product_tmpl_id': tmpl.id, 'package_id': package.id,
                'refresh_token': token, 'ai_pending': True,
                'title': _('本期新增（%s）') % fields.Date.context_today(self),
                'feature_ids': [(6, 0, [f.id for f in classified])],
            })
        for rec in (pending | note):
            try:
                rec._ai_draft(refresh_token=token)
            except hub_client.BudgetExceeded as e:
                _logger.info('[knowledge] 本期新增 %s 留到下一次：%s', rec.id, e)
                break
            except hub_client.HubError as e:
                _logger.warning('[knowledge] 本期新增 %s 起草失敗：%s', rec.id, e)
        return pending | note

    def _ai_prompt(self):
        self.ensure_one()
        classified = self._marketing_classified(self.package_id, self.feature_ids) \
            if self.package_id else {}
        items = [{'key': f.feature_key, 'name': f.name, 'menu_path': f.menu_path or '',
                  'capability': classified[f].name if f in classified else None,
                  'capability_outcome': classified[f].outcome or '' if f in classified else ''}
                 for f in self.feature_ids]
        return (
            "方案「%(product)s」這一版新增了下列功能。請寫一段商品頁的「本期新增」：\n"
            "標題一句（25 字內）；內文依能力分組，每組一句說明客戶多了什麼好處，再列功能名稱；"
            "只寫下列功能，不要推測其他改版內容。\n%(rules)s\n"
            "回覆格式：{\"title\": str, \"body_html\": str}\n\n功能：%(items)s"
        ) % {'product': self.product_tmpl_id.name, 'rules': HTML_RULES,
             'items': json.dumps(items, ensure_ascii=False)}

    def _ai_draft(self, refresh_token=None):
        self.ensure_one()
        data = self.env['corpaas.knowledge.ai'].ask(
            'marketing_release_note', self._ai_prompt(), package=self.package_id or None,
            refresh_token=refresh_token, record=self) or {}
        title = (data.get('title') or '').strip()
        if not title:
            raise hub_client.HubError(_('AI 沒有回傳標題'))
        self.write({'title': title[:200], 'body_html': html_guard.clean(data.get('body_html')),
                    'ai_pending': False})
        self.knowledge_propose('claim', note=_('AI 起草本期新增'))
        return True

    def action_ai_draft(self):
        action = True
        for rec in self:
            if not rec.package_id:
                raise UserError(_('本期新增「%s」沒有方案，無法排入 AI 起草。') % rec.display_name)
            action = self.env['corpaas.knowledge.ai'].enqueue(
                rec, '_ai_draft_run', rec.package_id, note=_('AI 起草本期新增'))
        return action

    def _ai_draft_run(self):
        self.ensure_one()
        return self._ai_draft()

    # ------------------------------------------------------------------
    # 發給既有訂戶（只開精靈，不自動寄）
    # ------------------------------------------------------------------
    def _marketing_package_variants(self):
        """這個方案在賣的變體：方案指定的那一個，或同分支的所有變體。"""
        self.ensure_one()
        pkg = self.package_id.sudo()
        if pkg.product_id:
            variants = pkg.product_id
            branch = pkg.product_id.branch_name
        else:
            variants = self.product_tmpl_id.sudo().product_variant_ids
            branch = False
        if branch:
            variants |= variants.product_tmpl_id.product_variant_ids.filtered(
                lambda v: v.branch_name == branch)
        return variants

    def _marketing_subscriber_partners(self):
        """既有訂戶：訂閱行是這個方案變體、還在用（new／inprogress、沒過期）的合約客戶。"""
        self.ensure_one()
        Partner = self.env['res.partner']
        if 'dobtor.contract.line' not in self.env or not self.package_id:
            return Partner
        Line = self.env['dobtor.contract.line'].sudo()
        now = fields.Datetime.now()
        lines = Line.search([
            ('product_id', 'in', self._marketing_package_variants().ids),
            ('state', 'in', ('new', 'inprogress')),
            ('subscription_product_line_id', '!=', False),
            '|', ('end_date', '=', False), ('end_date', '>=', now)])
        partners = lines.mapped('subscription_product_line_id.partner_id')
        return partners.filtered(lambda p: p.email and p.active)

    def action_notify_subscribers(self):
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_('只有已發佈的本期新增可以發給既有訂戶。'))
        partners = self._marketing_subscriber_partners()
        if not partners:
            raise UserError(_('這個方案目前沒有使用中的訂戶（或訂戶沒有 email）。'))
        live = self._website_note()
        return {
            'type': 'ir.actions.act_window', 'name': _('發給既有訂戶'),
            'res_model': 'mail.compose.message', 'view_mode': 'form', 'target': 'new',
            'context': {
                # ★ mass_mail：每位訂戶各收一封，不會看到彼此的地址
                'default_composition_mode': 'mass_mail',
                'default_model': 'res.partner',
                'default_res_ids': partners.ids,
                'default_subject': live['title'],
                'default_body': live['body_html'],
                'default_auto_delete': False,
            },
        }
