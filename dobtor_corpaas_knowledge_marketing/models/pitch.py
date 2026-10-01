# -*- coding: utf-8 -*-
"""能力卡片（pitch）與宣稱錨定（claim）。

★ 宣稱一律核准：`_knowledge_requires_review` 永遠 True，連純重拍也不例外。
★ 上線內容另存一份 `live_json`（核准那一刻的快照），商品頁只讀它：
  編輯中、送審中、失效中的卡片，前台仍是上一次核准的版本——不會把還沒核准的宣稱推上線。
  ☠️ 不拿修訂表當上線來源：`_gc_keep_last` 只留最近 N 版，會把上線那版清掉。
★ 存在與否以「方案」為單位（feature.is_present_in(package)）：同一個功能在 A 方案被拿掉、
  B 方案還在，只有 A 方案商品頁的卡片要處理。
★ 宣稱的處理分兩種：
  - 功能從方案消失 → 宣稱待查、卡片失效、暫時撤圖；核准前必須改錨定或刪除那句宣稱
    （不能核准時自動把待查洗成正常）。
  - 畫面大改（scope_changed）→ 只換圖（同一張截圖的新版），宣稱與上線狀態都不動。
"""
import json
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.services import hub_client

from . import html_guard
from .guard import guard_ctx, is_guarded

_logger = logging.getLogger(__name__)

HTML_RULES = (
    "body_html 只能用這些標籤：p、ul、ol、li、strong、em、h4、h5、table、thead、tbody、tr、th、td、div、span；"
    "只能用這些 class：s_alert alert alert-info、table table-bordered table-striped align-middle"
    "（thead 用 table-light）、badge text-bg-primary、d-flex。"
    "不得有 style、id、data-* 屬性，不得有 <style>、<script>、<svg>、<img>、<a>。"
)

CLAIM_STATES = [('ok', '正常'), ('check', '待查')]


def present_features(features, package):
    """這些功能點裡，在這個方案還存在的；不知道方案時退回「還沒全部消失」。"""
    if package:
        return features.filtered(lambda f: f.is_present_in(package))
    return features.filtered(lambda f: not f.missing)


def package_domain(package, prefix=''):
    """屬於這個方案的行銷內容：有指定方案的比方案；舊資料沒指定的比方案商品。"""
    return ['|', (prefix + 'package_id', '=', package.id),
            '&', (prefix + 'package_id', '=', False),
            (prefix + 'product_tmpl_id', '=', package.product_tmpl_id.id)]


class KnowledgePitch(models.Model):
    _name = 'corpaas.knowledge.pitch'
    _description = '能力卡片（產品行銷）'
    _inherit = ['corpaas.knowledge.marketing.guarded']
    _order = 'product_tmpl_id, sequence, id'
    _rec_name = 'headline'

    _marketing_guarded_fields = ('state', 'live_json', 'images_hidden')

    sequence = fields.Integer(default=10)
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='能力',
                                    required=True, ondelete='cascade', index=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', string='情境',
                                  ondelete='set null')
    product_tmpl_id = fields.Many2one('product.template', string='方案商品', required=True,
                                      ondelete='cascade', index=True)
    package_id = fields.Many2one('infrastructure.solution.package', string='方案',
                                 ondelete='set null', index=True,
                                 help='宣稱錨定依這個方案判斷功能是否存在；留空＝商品頁對應的方案')
    headline = fields.Char(string='標題', tracking=True)
    body_html = fields.Html(string='內文', help='痛點→成果、情境故事')
    asset_ids = fields.Many2many(
        'corpaas.knowledge.asset', 'corpaas_knowledge_pitch_asset_rel',
        'pitch_id', 'asset_id', string='截圖（乾淨版）',
        domain="[('state', '=', 'current'), ('feature_id', 'in', capability_feature_ids)]")
    capability_feature_ids = fields.Many2many(related='capability_id.feature_ids',
                                              string='能力的功能點')
    claim_ids = fields.One2many('corpaas.knowledge.claim', 'pitch_id', string='宣稱')
    claims_digest = fields.Text(compute='_compute_claims_digest', inverse='_inverse_claims_digest',
                                string='宣稱內容', help='一行一句；還原修訂時由此重建宣稱')
    claim_check_count = fields.Integer(compute='_compute_claims_digest', string='待查宣稱')
    images_hidden = fields.Boolean(string='圖片暫時撤下', copy=False, readonly=True,
                                   help='宣稱錨定的功能從方案消失：前台先不顯示這張卡片的圖，核准後恢復')
    live_json = fields.Text(string='上線快照', copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        Tmpl = self.env['product.template']
        for vals in vals_list:
            if not vals.get('package_id') and vals.get('product_tmpl_id'):
                pkg = Tmpl.browse(vals['product_tmpl_id'])._knowledge_package()
                if pkg:
                    vals['package_id'] = pkg.id
        return super().create(vals_list)

    @api.depends('claim_ids.text', 'claim_ids.state', 'claim_ids.sequence')
    def _compute_claims_digest(self):
        for rec in self:
            claims = rec.claim_ids.sorted('sequence')
            rec.claims_digest = '\n'.join(claims.mapped('text'))
            rec.claim_check_count = len(claims.filtered(lambda c: c.state == 'check'))

    def _inverse_claims_digest(self):
        """還原修訂寫回宣稱文字：同一句保留原錨定，新句錨定整個能力的功能點。"""
        for rec in self:
            lines = [t.strip() for t in (rec.claims_digest or '').splitlines() if t.strip()]
            keep = rec.claim_ids.filtered(lambda c: c.text in lines)
            (rec.claim_ids - keep).unlink()
            have = set(keep.mapped('text'))
            rec._replace_claims([t for t in lines if t not in have], keep=keep)
            for seq, text in enumerate(lines, start=1):
                rec.claim_ids.filtered(lambda c, t=text: c.text == t).write({'sequence': seq * 10})

    def _marketing_package(self):
        self.ensure_one()
        return self.package_id or self.product_tmpl_id._knowledge_package()

    # ------------------------------------------------------------------
    # 狀態機覆寫點
    # ------------------------------------------------------------------
    def _knowledge_revision_fields(self):
        return ['headline', 'body_html', 'claims_digest', 'asset_ids']

    def _knowledge_requires_review(self, change):
        return True

    def _marketing_check_claims(self):
        """核准前：沒有待查宣稱，且每一句都錨定到方案裡存在的功能點（至少一個）。"""
        self.ensure_one()
        pending = self.claim_ids.filtered(lambda c: c.state == 'check')
        if pending:
            raise UserError(_('還有待查的宣稱，請先改錨定到現有功能或刪除：%s')
                            % '、'.join(pending.mapped('text')))
        pkg = self._marketing_package()
        bad = self.claim_ids.filtered(
            lambda c: not c.feature_ids or present_features(c.feature_ids, pkg) != c.feature_ids)
        if bad:
            raise UserError(_('每一句宣稱都必須錨定到方案裡存在的功能點：%s')
                            % '、'.join(bad.mapped('text')))

    def _knowledge_publish(self):
        self.ensure_one()
        if not (self.headline or '').strip():
            raise UserError(_('能力卡片沒有標題。'))
        self._marketing_check_claims()
        assets = self.asset_ids.filtered(lambda a: a.state == 'current' and a.attachment_id)
        for att in assets.mapped('attachment_id').sudo():
            att.generate_access_token()
        self._marketing_sys().write({
            'images_hidden': False,
            'live_json': json.dumps({
                'headline': self.headline,
                'body_html': str(self.body_html or ''),
                'claims': [{'id': c.id, 'text': c.text, 'feature_ids': c.feature_ids.ids}
                           for c in self.claim_ids.sorted('sequence')],
                'asset_ids': assets.ids,
            }, ensure_ascii=False),
        })
        return True

    def _knowledge_unpublish(self):
        self._marketing_sys().write({'live_json': False})
        return True

    # ------------------------------------------------------------------
    # 宣稱錨定（D4 失效）
    # ------------------------------------------------------------------
    @api.model
    def _marketing_flag_features(self, features, reason, package=None):
        """功能從方案消失：引用它的宣稱 → 待查；所屬卡片 → 失效＋暫時撤圖。回傳受影響的卡片。

        package 為空＝所有方案都沒有了（例如改名被否決、功能全面消失）。
        """
        if not features:
            return self.browse()
        domain = [('feature_ids', 'in', features.ids)]
        if package:
            domain += package_domain(package, 'pitch_id.')
        claims = self.env['corpaas.knowledge.claim'].sudo().with_context(
            **guard_ctx()).search(domain)
        for claim in claims:
            hit = claim.feature_ids & features
            claim.write({'state': 'check',
                         'reason': '%s：%s' % (reason, '、'.join(hit.mapped('name')))})
        pitches = claims.mapped('pitch_id').filtered(lambda p: p.state != 'retired')
        if pitches:
            pitches._marketing_sys().write({'images_hidden': True})
            pitches.knowledge_mark_stale(reason)
        return pitches

    @api.model
    def _marketing_swap_images(self, features, package):
        """畫面大改：同一張截圖換成最新版（素材自動、不送審），宣稱與上線狀態不動。"""
        if not features:
            return self.browse()
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        pitches = self.sudo().search(package_domain(package) + [
            ('asset_ids.feature_id', 'in', features.ids), ('state', '!=', 'retired')])
        changed = self.browse()
        for pitch in pitches:
            live = pitch._live()
            ids = set(pitch.asset_ids.ids) | set(live.get('asset_ids') or [])
            mapping = {}
            for asset in Asset.browse(sorted(ids)).exists():
                if asset.feature_id not in features or asset.state == 'current':
                    continue
                new = pitch._marketing_current_asset(asset)
                if new and new != asset:
                    mapping[asset.id] = new.id
            if not mapping:
                continue
            vals = {'asset_ids': [(6, 0, [mapping.get(i, i) for i in pitch.asset_ids.ids])]}
            if live:
                live['asset_ids'] = [mapping.get(i, i) for i in live.get('asset_ids') or []]
                vals['live_json'] = json.dumps(live, ensure_ascii=False)
            pitch._marketing_sys().write(vals)
            changed |= pitch
        return changed

    # ------------------------------------------------------------------
    # 前台
    # ------------------------------------------------------------------
    def _live(self):
        self.ensure_one()
        return json.loads(self.live_json or '{}')

    def _marketing_current_asset(self, asset):
        """被重拍取代的圖跟到同一張的最新版（同功能、情境、shot_name）。"""
        if asset.state == 'current':
            return asset
        return self.env['corpaas.knowledge.asset'].sudo().search([
            ('feature_id', '=', asset.feature_id.id), ('scenario_id', '=', asset.scenario_id.id),
            ('shot_name', '=', asset.shot_name), ('state', '=', 'current')], limit=1)

    def _live_assets_map(self, lives=None):
        """{pitch.id: 上線快照裡的圖}（被取代的跟到最新版）。

        ★ 整批兩次查詢（快照裡的素材＋被取代者的最新版）：商品頁是公開頁，不能每張卡片各查。
        """
        lives = lives if lives is not None else {p.id: p._live() for p in self}
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        wanted = {p.id: [i for i in lives[p.id].get('asset_ids') or [] if isinstance(i, int)]
                  for p in self}
        found = Asset.browse(sorted({i for ids in wanted.values() for i in ids})).exists()
        replaced = found.filtered(lambda a: a.state != 'current')
        current = {}
        if replaced:
            fresh = Asset.search([('feature_id', 'in', replaced.feature_id.ids),
                                  ('shot_name', 'in', list(set(replaced.mapped('shot_name')))),
                                  ('state', '=', 'current')], order='id desc')
            for asset in replaced:
                current[asset.id] = fresh.filtered(
                    lambda a, o=asset: a.feature_id == o.feature_id
                    and a.scenario_id == o.scenario_id and a.shot_name == o.shot_name)[:1]
        by_id = {a.id: a for a in found}
        out = {}
        for pitch in self:
            assets = Asset
            for aid in wanted[pitch.id]:
                asset = by_id.get(aid)
                if asset and asset.state != 'current':
                    asset = current.get(aid)
                if asset and asset.attachment_id:
                    assets |= asset
            out[pitch.id] = assets
        return out

    def _live_assets(self):
        self.ensure_one()
        return self._live_assets_map()[self.id]

    def _live_claim_items(self, live):
        """[(快照宣稱, 錨定功能點 id)]：只留目前宣稱記錄還在、且狀態正常的那幾句。

        ☠️ 不能只排除「待查」：宣稱被刪掉（連同它的待查狀態）後，快照裡那句會重新冒出來。
        ★ 錨定以快照為準（核准的是那一刻的錨定）；舊快照沒存錨定才退回目前的錨定。
        """
        self.ensure_one()
        ok = {c.id: c for c in self.claim_ids if c.state == 'ok'}
        out = []
        for item in live.get('claims') or []:
            if not isinstance(item, dict) or item.get('id') not in ok or not item.get('text'):
                continue
            fids = item.get('feature_ids')
            if not isinstance(fids, list):
                fids = ok[item['id']].feature_ids.ids
            out.append((item, fids))
        return out

    def _live_claims(self, live=None, package=None, features=None):
        """上線快照的宣稱，且錨定的功能點都還在這個方案裡（features＝整批預先取好的功能點）。"""
        self.ensure_one()
        live = live if live is not None else self._live()
        package = package or self._marketing_package()
        items = self._live_claim_items(live)
        if features is None:
            features = self.env['corpaas.knowledge.feature'].sudo().browse(
                sorted({f for _item, fids in items for f in fids})).exists()
        present = set(present_features(features, package).ids)
        return [item['text'] for item, fids in items
                if fids and all(f in present for f in fids)]

    def _website_cards(self, package=None):
        """整批組商品頁卡片（package＝商品頁對應的方案；卡片自己有方案就用自己的）。

        ★ 素材與功能點各整批查一次：商品頁是公開頁，查詢數不能跟卡片數成正比。
        """
        lives = {p.id: p._live() for p in self}
        assets = self._live_assets_map(lives)
        fids = {f for p in self for _item, ids in p._live_claim_items(lives[p.id]) for f in ids}
        features = self.env['corpaas.knowledge.feature'].sudo().browse(sorted(fids)).exists()
        return [p._website_card(lives[p.id], assets[p.id], p.package_id or package, features)
                for p in self]

    def _website_card(self, live=None, assets=None, package=None, features=None):
        self.ensure_one()
        live = live if live is not None else self._live()
        images = []
        if not self.images_hidden:
            for asset in assets if assets is not None else self._live_assets():
                att = asset.attachment_id.sudo()
                token = att.access_token or att.generate_access_token()[0]
                images.append({'url': '/web/image/%s?access_token=%s' % (att.id, token),
                               'alt': asset.name})
        return {
            'anchor': 'kb-cap-%s' % (self.capability_id.code or self.capability_id.id),
            'headline': live.get('headline') or '',
            'body_html': Markup(live.get('body_html') or ''),
            'claims': self._live_claims(live, package, features),
            'images': images,
        }

    # ------------------------------------------------------------------
    # AI 起草（按鈕走佇列；refresh 期間的呼叫才同步）
    # ------------------------------------------------------------------
    def action_ai_draft(self):
        action = True
        for rec in self:
            pkg = rec._marketing_package()
            if not pkg:
                raise UserError(_('能力卡片「%s」找不到對應的方案，無法排入 AI 起草。')
                                % rec.display_name)
            action = self.env['corpaas.knowledge.ai'].enqueue(
                rec, '_ai_draft_run', pkg, note=_('AI 起草行銷文案'))
        return action

    def _ai_draft_run(self):
        """佇列作業的入口（corpaas.knowledge.ai.job 以原使用者身分呼叫）。"""
        self.ensure_one()
        return self._ai_draft(package=self._marketing_package() or None)

    def _ai_features(self):
        self.ensure_one()
        return present_features(self.capability_id.feature_ids, self._marketing_package())

    def _ai_prompt(self):
        self.ensure_one()
        cap, sc = self.capability_id, self.scenario_id
        features = [{'key': f.feature_key, 'name': f.name, 'menu_path': f.menu_path or ''}
                    for f in self._ai_features()]
        scenario = {'name': sc.name, 'narrative': sc.narrative or '',
                    'glossary': sc.glossary_map()} if sc else None
        return (
            "請為方案「%(product)s」的能力「%(cap)s」寫一張商品頁的能力卡片。\n"
            "結構：標題一句（20 字內，講成果不講功能名）；內文依「痛點 → 成果 → 情境故事」三段；"
            "再列出 2–5 句可被驗證的宣稱，每句宣稱必須對應到下方功能點（用 key），"
            "沒有功能點支撐的事不要宣稱。有情境時，內文一律改用情境用語對照（glossary）裡的用語。\n"
            "%(rules)s\n"
            "回覆格式：{\"headline\": str, \"body_html\": str, "
            "\"claims\": [{\"text\": str, \"features\": [key, …]}]}\n\n"
            "能力：%(cap_json)s\n\n功能點：%(features)s\n\n情境：%(scenario)s"
        ) % {
            'product': self.product_tmpl_id.name, 'cap': cap.name, 'rules': HTML_RULES,
            'cap_json': json.dumps({'name': cap.name, 'pain': cap.pain or '',
                                    'outcome': cap.outcome or '',
                                    'differentiator': cap.differentiator or ''},
                                   ensure_ascii=False),
            'features': json.dumps(features, ensure_ascii=False),
            'scenario': json.dumps(scenario, ensure_ascii=False),
        }

    def _ai_draft(self, refresh_token=None, package=None):
        """capability＋scenario＋glossary → headline/body_html/claims，然後送審。"""
        self.ensure_one()
        data = self.env['corpaas.knowledge.ai'].ask(
            'marketing_pitch', self._ai_prompt(), package=package,
            refresh_token=refresh_token, record=self) or {}
        headline = (data.get('headline') or '').strip()
        if not headline:
            raise hub_client.HubError(_('AI 沒有回傳標題'))
        self.write({'headline': headline[:200],
                    'body_html': html_guard.clean(data.get('body_html'))})
        self._replace_claims(data.get('claims') or [])
        if not self.asset_ids:
            self.asset_ids = [(6, 0, self._suggest_assets().ids)]
        self.knowledge_propose('claim', note=_('AI 起草行銷文案'))
        return True

    def _replace_claims(self, items, keep=None):
        """AI 宣稱 → claim；錨定只收能力內、方案裡還在的功能點，對不上就錨定整個能力的功能點（寧可多查）。"""
        self.ensure_one()
        cap_features = self._ai_features()
        by_key = {f.feature_key: f for f in cap_features}
        (self.claim_ids - (keep or self.claim_ids.browse())).unlink()
        vals = []
        for seq, item in enumerate(items, start=1):
            if isinstance(item, str):
                item = {'text': item}
            text = (item.get('text') or '').strip() if isinstance(item, dict) else ''
            if not text:
                continue
            anchored = [by_key[k].id for k in item.get('features') or [] if k in by_key]
            vals.append({'pitch_id': self.id, 'sequence': seq * 10, 'text': text,
                         'capability_id': self.capability_id.id,
                         'feature_ids': [(6, 0, anchored or cap_features.ids)]})
        return self.env['corpaas.knowledge.claim'].create(vals)

    def _suggest_assets(self, limit=3):
        """乾淨版截圖：只從核心素材挑（使用中、屬於能力的功能點）；同情境優先。"""
        self.ensure_one()
        Asset = self.env['corpaas.knowledge.asset'].sudo()
        domain = [('state', '=', 'current'), ('attachment_id', '!=', False),
                  ('feature_id', 'in', self._ai_features().ids)]
        found = Asset.browse()
        if self.scenario_id:
            found = Asset.search(domain + [('scenario_id', '=', self.scenario_id.id)],
                                 limit=limit)
        if len(found) < limit:
            found |= Asset.search(domain + [('id', 'not in', found.ids)],
                                  limit=limit - len(found))
        return found


class KnowledgeClaim(models.Model):
    _name = 'corpaas.knowledge.claim'
    _description = '行銷宣稱（錨定到功能點）'
    _order = 'pitch_id, sequence, id'
    _rec_name = 'text'

    sequence = fields.Integer(default=10)
    pitch_id = fields.Many2one('corpaas.knowledge.pitch', string='能力卡片', required=True,
                               ondelete='cascade', index=True)
    product_tmpl_id = fields.Many2one(related='pitch_id.product_tmpl_id', store=True)
    text = fields.Char(string='宣稱', required=True)
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='能力',
                                    compute='_compute_capability', store=True,
                                    readonly=False, ondelete='cascade')
    feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_claim_feature_rel',
        'claim_id', 'feature_id', string='錨定功能點')
    state = fields.Selection(CLAIM_STATES, default='ok', required=True, index=True,
                             readonly=True)
    reason = fields.Char(string='待查原因')

    @api.depends('pitch_id.capability_id')
    def _compute_capability(self):
        for rec in self:
            if not rec.capability_id:
                rec.capability_id = rec.pitch_id.capability_id

    def _anchors_present(self):
        self.ensure_one()
        pkg = self.pitch_id._marketing_package()
        return bool(self.feature_ids) and \
            present_features(self.feature_ids, pkg) == self.feature_ids

    def write(self, vals):
        # ★ 待查 → 正常只有兩條路：改錨定到方案裡存在的功能（這裡自動），或核准者確認。
        if 'state' in vals and not is_guarded(self.env):
            raise UserError(_('宣稱狀態不能直接修改：請改錨定到現有功能、刪除，或由核准者確認。'))
        res = super().write(vals)
        if 'feature_ids' in vals and 'state' not in vals:
            fixed = self.filtered(lambda c: c.state == 'check' and c._anchors_present())
            if fixed:
                fixed.with_context(**guard_ctx()).write({'state': 'ok', 'reason': False})
        return res

    def action_mark_ok(self):
        self.env['corpaas.knowledge.pitch']._check_approver()
        for claim in self:
            if not claim._anchors_present():
                raise UserError(_('宣稱「%s」錨定的功能已不在方案裡，請改錨定到現有功能或刪除。')
                                % claim.text)
        self.with_context(**guard_ctx()).write({'state': 'ok', 'reason': False})
        return True
