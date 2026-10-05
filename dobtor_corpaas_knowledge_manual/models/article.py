# -*- coding: utf-8 -*-
"""文章：功能 × 情境 × 腳本範圍指紋。步驟區塊（共用）＋情境區塊（這個情境為什麼這樣做）＋素材。

★ 鍵＝(feature_id, scenario_id, fingerprint)（設計「共用規則」：同功能、同情境、指紋相同
  才是同一篇）。方案 A 的畫面改版只會產生／改動 A 那個指紋的文章；方案 B 還在舊指紋就繼續
  看舊的那篇，文字與圖都不受影響（B1）。
★ 一個方案拿到某篇文章的條件：方案目前（任一角色）的 scope_hash 等於文章指紋，而且功能是
  該方案圈選核准的候選。指紋不同但方案仍有這個功能×情境 → 舊版維持上線（stale 語意），
  等新指紋那篇核准後接手同一張 slide（網址不變）。
★ 文章本身不存完整 HTML：每次推到 slide 時由 render_html() 組裝。
☠️ 前台一律用「最後一次核准上線的快照」組裝（標題、情境區塊、步驟區塊清單；區塊本身也用
  它自己的上線快照），不看目前欄位：上線後被改、還沒審的文字，不能藉下一次推送（重拍、
  補掛 channel、重試）偷渡上線。
"""
import difflib
import hashlib
import html as html_mod
import json

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.services import phash

from ..services import manual_lib
from .placement import BATCH_KEY, sync_batch

_logger = logging.getLogger(__name__)


class KnowledgeArticle(models.Model):
    _name = 'corpaas.knowledge.article'
    _description = '操作說明：文章'
    _inherit = ['corpaas.knowledge.content.mixin']
    _order = 'capability_id, sequence, name'

    name = fields.Char(string='標題', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    feature_id = fields.Many2one('corpaas.knowledge.feature', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    scenario_id = fields.Many2one('corpaas.knowledge.scenario', required=True,
                                  ondelete='cascade', index=True)
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='能力（章節）',
                                    ondelete='set null', index=True,
                                    help='預設章節；實際章節依各方案的圈選能力（發佈位置上）')
    fingerprint = fields.Char(string='腳本範圍指紋', index=True,
                              help='文章鍵的一部分：這篇對應的 scope_hash（租戶端 D5 比對也用它）')
    step_block_ids = fields.Many2many(
        'corpaas.knowledge.step_block', 'corpaas_knowledge_article_step_block_rel',
        'article_id', 'step_block_id', string='步驟區塊')
    scenario_html = fields.Html(string='情境區塊')
    shot_binding_id = fields.Many2one('corpaas.knowledge.shot_binding', string='情境繫結',
                                      ondelete='set null')
    asset_ids = fields.Many2many('corpaas.knowledge.asset',
                                 'corpaas_knowledge_article_asset_rel',
                                 'article_id', 'asset_id', string='素材')
    placement_ids = fields.One2many('corpaas.knowledge.placement', 'article_id',
                                    string='發佈位置')
    placement_count = fields.Integer(compute='_compute_placement_count')
    preview_html = fields.Html(compute='_compute_preview_html', sanitize=False,
                               string='預覽')
    manual_forked_from_id = fields.Many2one(
        'corpaas.knowledge.article', string='分岔自', ondelete='set null', index=True,
        copy=False, help='別的方案還在舊指紋、這篇是新指紋的分岔')
    manual_waiting_shots = fields.Boolean(
        string='等新畫面截圖', copy=False,
        help='文字與上線版相同、只差新指紋的截圖：圖拍好就自動上線（純重拍不必審）')
    manual_review_sig = fields.Char(copy=False, readonly=True,
                                    help='送審當下的文字雜湊（核准時比對：核准者有沒有改過）')
    manual_live_asset_ids = fields.Many2many(
        'corpaas.knowledge.asset', 'corpaas_knowledge_article_live_asset_rel',
        'article_id', 'asset_id', string='上線版素材', copy=False, readonly=True)
    manual_review_html = fields.Html(compute='_compute_manual_review_html', sanitize=False,
                                     string='審核')

    # ------------------------------------------------------------------
    # D4 覆寫點
    # ------------------------------------------------------------------
    def _knowledge_revision_fields(self):
        return ['name', 'scenario_html', 'step_block_ids', 'capability_id']

    def _manual_unpublished_blocks(self):
        return self.step_block_ids.filtered(lambda b: not b.published_rev_no)

    def _knowledge_requires_review(self, change):
        self.ensure_one()
        # ★ B3：引用還沒上線過的步驟區塊 → 一律送審（區塊跟文章一起給核准者看），
        #   不能被「純重拍」或「情境免審」帶著自動上線。
        if self._manual_unpublished_blocks():
            return True
        if change == 'shot':
            # ★ 純重拍只換圖：文字跟核准版不同（伺服端流程改過、分岔後被人改過）就要審，
            #   否則重拍會把沒審過的文字記成上線版。
            return not self._manual_text_approved()
        if change == 'text' and self.scenario_id.text_review_waived():
            return False
        return True

    def _knowledge_publish(self):
        # ★ 真正的推送在 _do_publish 記下上線快照之後（前台只用上線快照組裝）
        return True

    def _knowledge_unpublish(self):
        pls = self.mapped('placement_ids')
        pls._manual_retire()
        # ★ 章節可能因此變空：重新編號才會把空章節取消發佈
        pls.mapped('channel_id')._knowledge_request_sync()
        return True

    def _manual_text_approved(self):
        """目前的文字＝核准過的文字？比對自己的上線版；還沒上線過的分岔比對分岔來源的上線版。"""
        self.ensure_one()
        names = self._knowledge_revision_fields()
        base = self._last_published_snapshot()
        if not base and self.manual_forked_from_id:
            # 分岔的步驟區塊是新指紋的另一份，各自有審核閘門；這裡只比文章本身的文字
            base = self.manual_forked_from_id._last_published_snapshot()
            names = ['name', 'scenario_html']
        if not base:
            return False
        now = json.loads(json.dumps(self._snapshot(), default=str))
        return all(now.get(n) == base.get(n) for n in names)

    def _manual_live_text(self):
        """前台用的文字：{'name', 'scenario_html', 'blocks'}，取最後一次上線的快照。"""
        self.ensure_one()
        snap = self._last_published_snapshot()
        Block = self.env['corpaas.knowledge.step_block']
        if not snap:
            if self.state != 'published':
                return {'name': self.name, 'scenario_html': '', 'blocks': Block}
            snap = self._snapshot()  # 舊資料沒有上線快照
        return {'name': snap.get('name') or self.name,
                'scenario_html': snap.get('scenario_html') or '',
                'blocks': Block.browse(snap.get('step_block_ids') or []).exists()}

    def _manual_swap_live_block(self, old, new):
        """人工確認的步驟區塊合併：上線快照裡的 old 換成 new（兩份都是核准過的內容）。"""
        Rev = self.env['corpaas.knowledge.revision'].sudo()
        for art in self:
            rev = Rev.search([('res_model', '=', art._name), ('res_id', '=', art.id),
                              ('was_published', '=', True)], limit=1)
            data = rev._data() if rev else {}
            if old.id not in (data.get('step_block_ids') or []):
                continue
            ids = [new.id if i == old.id else i for i in data['step_block_ids']]
            data['step_block_ids'] = list(dict.fromkeys(ids))
            rev.snapshot = json.dumps(data, ensure_ascii=False, default=str)

    def _do_publish(self, change, note=None):
        self.ensure_one()
        fresh = self._manual_unpublished_blocks()
        if fresh:
            raise UserError(_('「%(a)s」引用還沒上線的步驟區塊（%(b)s），要跟文章一起核准才能發佈。',
                              a=self.display_name, b='、'.join(fresh.mapped('name'))))
        res = super()._do_publish(change, note=note)
        self.write({'manual_waiting_shots': False,
                    'manual_live_asset_ids': [(6, 0, self._display_assets().ids)]})
        self._manual_push()
        return res

    def knowledge_propose(self, change, note=None):
        res = super().knowledge_propose(change, note=note)
        for rec in self.filtered(lambda r: r.state == 'review'):
            rec.manual_review_sig = rec._manual_text_sig()
        return res

    def _manual_text_sig(self):
        """文章＋引用區塊的文字雜湊（判斷核准者有沒有改過）。"""
        self.ensure_one()
        parts = [self.name or '', self.scenario_html or '']
        parts += ['%s:%s:%s' % (b.id, b.name or '', b.html or '')
                  for b in self.step_block_ids.sorted('id')]
        return hashlib.sha1('\x1f'.join(parts).encode('utf-8')).hexdigest()

    manual_shots_ready = fields.Boolean(string='截圖就緒', compute='_compute_manual_shots_ready')
    manual_shots_problem = fields.Char(string='截圖問題', compute='_compute_manual_shots_ready')

    def action_approve(self):
        self._check_approver()
        with sync_batch(self.env) as env:
            res = self.with_env(env)._manual_approve()
        self._manual_refresh_coverage()
        return res

    def _manual_refresh_coverage(self):
        """核准／下架後立即重算相關方案的說明覆蓋率（否則要等下一次知識更新才反映）。"""
        pkgs = self.mapped('feature_id.package_ids').filtered('knowledge_enabled')
        try:
            with self.env.cr.savepoint():
                pkgs.sudo()._knowledge_rebuild_coverage()
        except Exception as e:  # noqa: BLE001 — 報表重算失敗不影響核准
            _logger.warning('[knowledge.manual] 覆蓋率重算失敗：%s', e)

    def _manual_shots_problem(self):
        """這篇的截圖有什麼問題（空字串＝就緒）。"""
        self.ensure_one()
        b = self.shot_binding_id
        if not b:
            return ''
        if b.state != 'ok':
            from .sandbox_overview import reason_label
            return _('截圖沒有拍成功（%s）') % (reason_label(b.last_error) or b.state)
        if not self.asset_ids.filtered(lambda a: a.state == 'current'):
            return _('沒有使用中的截圖')
        return ''

    def _compute_manual_shots_ready(self):
        for rec in self:
            rec.manual_shots_problem = rec._manual_shots_problem()
            rec.manual_shots_ready = not rec.manual_shots_problem

    def _manual_approve(self):
        # ★ 截圖沒拍好的文章不讓核准：發佈出去就是一篇配著空白頁或錯誤畫面的說明。
        #   確定要先上線純文字時，可帶 context knowledge_force_approve。
        if not self.env.context.get('knowledge_force_approve'):
            bad = [(r, r._manual_shots_problem()) for r in self]
            bad = [(r, p) for r, p in bad if p]
            if bad:
                raise UserError(_('以下文章的截圖尚未就緒，先重拍或修補後再核准：\n%s')
                                % '\n'.join('・%s：%s' % (r.name, p) for r, p in bad))
        clean = {rec.id: bool(rec.manual_review_sig)
                 and rec.manual_review_sig == rec._manual_text_sig() for rec in self}
        # ★ B3：一起送審、從沒上線過的新區塊跟文章一起核准（核准者在審核頁看得到它的全文）
        fresh = self.mapped('step_block_ids').filtered(
            lambda b: not b.published_rev_no and b.state == 'review')
        if fresh:
            fresh.action_approve()
        res = super().action_approve()
        # ★ B4：情境「連續 N 次核准無修改」計數——核准者沒改文字才 +1
        for rec in self:
            rec.scenario_id.note_article_review(clean[rec.id])
        return res

    def action_reject(self, reason=None):
        res = super().action_reject(reason=reason)
        self.mapped('scenario_id').note_article_review(False)
        return res

    def action_approve_by_scenario(self):
        """依情境批次核准：同情境（這幾篇的情境）所有待核文章一起核准。"""
        self._check_approver()
        todo = self.search([('state', '=', 'review'),
                            ('scenario_id', 'in', self.mapped('scenario_id').ids)])
        todo.action_approve()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'sticky': False,
                       'message': _('已依情境核准 %s 篇文章') % len(todo),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }

    # ------------------------------------------------------------------
    def _compute_placement_count(self):
        for rec in self:
            rec.placement_count = len(rec.placement_ids)

    @api.depends('name', 'scenario_html', 'step_block_ids', 'asset_ids')
    def _compute_preview_html(self):
        # ★ 預覽不產生標註版附件（讀取時不寫資料庫）；還沒畫過就先顯示原圖
        for rec in self:
            rec.preview_html = rec.render_html(preview=True) if rec.id else False

    def _image_html(self, asset, preview=False):
        if preview:
            att = asset.sudo().manual_attachment_id or asset.sudo().attachment_id
        else:
            att = asset._manual_image_attachment()
        if not att:
            return ''
        return ('<p><img src="/web/image/%s" class="img-fluid rounded border" alt="%s" '
                'loading="lazy"/></p>' % (att.id, html_mod.escape(asset.name or '')))

    def _display_assets(self):
        """要顯示的圖：指紋相符的現行素材（B2）。

        還沒有新指紋的圖（剛換指紋、等重拍）→ 暫時沿用原本掛著的現行素材，前台不會突然沒圖。
        """
        self.ensure_one()
        current = self.asset_ids.filtered(lambda a: a.state == 'current')
        mine = current.filtered(lambda a: a.scope_hash == self.fingerprint)
        return (mine or current).sorted('id')

    def render_html(self, preview=False, live=None):
        """組裝 slide 內容：情境區塊 → 各步驟區塊（標題帶 id="<anchor>"）→ 未放置的圖。

        圖片位置由步驟區塊裡的 [[shot:<名稱>]] 決定；沒放到的補在最後。
        ☠️ B3：前台只用上線快照（文章與各步驟區塊的）；preview=True（後台審核）才看目前文字。
        """
        self.ensure_one()
        if preview:
            live = {'scenario_html': self.scenario_html, 'blocks': self.step_block_ids}
        elif live is None:
            live = self._manual_live_text()
        parts = []
        intro = manual_lib.clean_html(live['scenario_html'] or '').strip()
        if intro:
            parts.append('<div class="s_alert alert alert-info">%s</div>' % intro)
        images = {}
        for asset in self._display_assets():
            images.setdefault(asset.shot_name, self._image_html(asset, preview=preview))
        used = set()
        for block in live['blocks'].sorted(lambda b: (b.sequence, b.id)):
            name, source = (block.name, block.html) if preview else block._manual_live_source()
            html = manual_lib.stamp_heading_ids(source or '', block.anchor)
            if not html:
                continue
            body, hit = manual_lib.replace_shot_markers(html, images)
            used |= hit
            parts.append('<h3 id="%s">%s</h3>%s' % (block.anchor, html_mod.escape(name or ''),
                                                    body))
        parts.extend(v for k, v in images.items() if k not in used and v)
        return ''.join(parts)

    # ------------------------------------------------------------------
    # 審核畫面（D4：核准者不能盲簽）
    # ------------------------------------------------------------------
    @staticmethod
    def _manual_diff_table(a, b, left, right):
        # ☠️ Html 欄位值是 Markup：difflib 對它 replace('&', '&amp;') 會再跳脫一次
        return difflib.HtmlDiff(wrapcolumn=70).make_table(
            str(a or '').splitlines(), str(b or '').splitlines(), left, right,
            context=True, numlines=2)

    def _manual_review_base(self):
        """審核的比對基準：自己的上線版；還沒上線過的分岔 → 分岔來源的上線版。"""
        self.ensure_one()
        me = self.with_context(manual_review_base=False)
        snap = me._last_published_snapshot()
        if not snap and self.manual_forked_from_id:
            snap = me.manual_forked_from_id._last_published_snapshot()
        return snap

    def _last_published_snapshot(self):
        if not self.env.context.get('manual_review_base'):
            return super()._last_published_snapshot()
        # 審核差異：分岔基準；區塊清單把「分岔自 X」的區塊視為同一格（文字差異在區塊那節）
        snap = dict(self._manual_review_base())
        if snap.get('step_block_ids'):
            swap = {b.derived_from_id.id: b.id for b in self.step_block_ids
                    if b.derived_from_id}
            snap['step_block_ids'] = [swap.get(i, i) for i in snap['step_block_ids']]
        return snap

    def _compute_review_diff(self):
        super(KnowledgeArticle, self.with_context(manual_review_base=True))._compute_review_diff()

    def _manual_review_blocks_html(self):
        self.ensure_one()
        Block = self.env['corpaas.knowledge.step_block']
        old_ids = self._manual_review_base().get('step_block_ids') or []
        old_blocks = Block.browse(old_ids).exists()
        rows = []
        for blk in self.step_block_ids.sorted(lambda b: (b.sequence, b.id)):
            parent = blk.derived_from_id
            base = parent if parent.published_rev_no and (
                parent in old_blocks or not blk.published_rev_no) else Block
            if blk in old_blocks and blk.state == 'published':
                continue
            if base:
                before, label = base._manual_live_source()[1], _('分岔前（%s）') % base.name
            elif blk.published_rev_no:
                before, label = blk._manual_live_source()[1], _('上線版')
            else:
                before, label = '', _('（新區塊）')
            if before == (blk.html or ''):
                continue
            rows.append('<h6>%s</h6>%s' % (html_mod.escape(blk.name or ''), self._manual_diff_table(
                before, blk.html, label, _('本次'))))
        for gone in old_blocks - self.step_block_ids:
            if gone in self.step_block_ids.mapped('derived_from_id'):
                continue
            rows.append('<h6>%s</h6><p class="text-muted">%s</p>' % (
                html_mod.escape(gone.name or ''), _('這個步驟區塊會從文章移除')))
        return ''.join(rows)

    @staticmethod
    def _manual_review_img(asset):
        att = asset.sudo().attachment_id if asset else None
        if not att:
            return '—'
        return '<img src="/web/image/%s" class="img-fluid rounded border"/>' % att.id

    def _manual_review_shots_html(self):
        self.ensure_one()
        live = self.manual_live_asset_ids
        if not self.published_rev_no:
            live = live or self.manual_forked_from_id.manual_live_asset_ids
        before = {a.shot_name: a for a in live}
        after = {a.shot_name: a for a in self._display_assets()}
        rows = []
        for name in sorted(set(before) | set(after)):
            a, b = before.get(name), after.get(name)
            if a and b and a == b:
                continue
            dist = phash.distance(a.phash, b.phash) if a and b and a.phash and b.phash else None
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                html_mod.escape(name), self._manual_review_img(a), self._manual_review_img(b),
                '' if dist is None else dist))
        if not rows:
            return ''
        return ('<table class="table table-bordered table-striped align-middle">'
                '<thead class="table-light"><tr><th>%s</th><th>%s</th><th>%s</th>'
                '<th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
            _('截圖'), _('上線版'), _('本次'), _('dHash 差距'), ''.join(rows))

    def _manual_review_impact_html(self):
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks']
        memo, channels = {}, []
        for pkg in self.scenario_id.package_ids.filtered('product_tmpl_id'):
            _base, fits, _cap = hooks._manual_article_status(self, pkg, memo)
            if fits:
                channels.append('%s（%s）' % (pkg.product_tmpl_id.display_name,
                                             pkg.display_name))
        changed = self.step_block_ids.filtered(lambda b: b.state != 'published')
        others = (changed.mapped('article_ids') - self)
        items = ['<li>%s</li>' % (_('同步到 %(n)s 個 channel：%(c)s', n=len(channels),
                                    c='、'.join(channels) or _('（無）')))]
        if changed:
            items.append('<li>%s</li>' % (_('共用的步驟區塊另外影響 %s 篇文章') % len(others)))
        return '<ul>%s</ul>' % ''.join(items)

    @api.depends('state', 'scenario_html', 'name', 'step_block_ids', 'asset_ids')
    def _compute_manual_review_html(self):
        for rec in self:
            if not rec.id or rec.state != 'review':
                rec.manual_review_html = False
                continue
            parts = ['<h5>%s</h5>%s' % (_('文章文字差異'), rec.review_diff or '')]
            blocks = rec._manual_review_blocks_html()
            if blocks:
                parts.append('<h5>%s</h5>%s' % (_('步驟區塊差異'), blocks))
            shots = rec._manual_review_shots_html()
            if shots:
                parts.append('<h5>%s</h5>%s' % (_('截圖對照'), shots))
            parts.append('<h5>%s</h5>%s' % (_('影響範圍'), rec._manual_review_impact_html()))
            rec.manual_review_html = ''.join(parts)

    # ------------------------------------------------------------------
    # 發佈位置
    # ------------------------------------------------------------------
    def _manual_fitting_packages(self, memo=None):
        """指紋相符、可以掛這篇的方案（B1）。"""
        self.ensure_one()
        hooks = self.env['corpaas.knowledge.hooks']
        memo = {} if memo is None else memo
        out = self.env['infrastructure.solution.package']
        for pkg in self.scenario_id.package_ids:
            if hooks._manual_article_status(self, pkg, memo)[1]:
                out |= pkg
        return out

    def _manual_ensure_placements(self):
        """建立／轉交／下架發佈位置，回傳這次要寫 slide 的位置。

        · 指紋相符 → 建立（或從同功能×情境、舊指紋那篇接手同一張 slide）並同步。
        · 方案仍有這個功能×情境、只是指紋不同 → 不動（舊版照樣在線上，等新指紋那篇接手）。
        · 方案已經不要了（情境拿掉、功能從方案消失、不再是候選）→ 取消發佈，不刪。
        """
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        Channel = self.env['slide.channel'].sudo()
        Cap = self.env['corpaas.knowledge.capability']
        hooks = self.env['corpaas.knowledge.hooks']
        batch = self.env.context.get(BATCH_KEY)
        memo, to_sync = (batch['memo'] if batch is not None else {}), Placement
        for art in self.sudo():
            handled = Placement
            packages = art.scenario_id.package_ids | art.placement_ids.mapped('package_id')
            for pkg in packages.filtered('product_tmpl_id'):
                base, fits, cap = hooks._manual_article_status(art, pkg, memo)
                cap = cap if cap and cap in pkg.knowledge_capability_ids else Cap
                if not base and not art.placement_ids.filtered(
                        lambda p: p.package_id == pkg):
                    continue
                channel = Channel._knowledge_channel_for(pkg.product_tmpl_id) if fits else \
                    Channel.with_context(active_test=False).search(
                        [('knowledge_product_tmpl_id', '=', pkg.product_tmpl_id.id)], limit=1)
                pl = art.placement_ids.filtered(lambda p: p.channel_id == channel)[:1] \
                    if channel else Placement
                if pl and pl in handled:
                    continue
                if fits:
                    if not pl:
                        pl = Placement.search([
                            ('channel_id', '=', channel.id),
                            ('article_id.feature_id', '=', art.feature_id.id),
                            ('article_id.scenario_id', '=', art.scenario_id.id),
                            ('article_id', '!=', art.id)], limit=1)
                        if pl:
                            # ★ 同一張 slide 由新指紋這篇接手：網址與錨點不變
                            pl.write({'article_id': art.id, 'package_id': pkg.id})
                        else:
                            pl = Placement.create({
                                'article_id': art.id, 'channel_id': channel.id,
                                'package_id': pkg.id, 'capability_id': cap.id,
                                'sequence': art.sequence})
                    vals = {}
                    if pl.capability_id != cap:
                        vals['capability_id'] = cap.id
                    if pl.manual_retired:
                        vals['manual_retired'] = False
                    if vals:
                        pl.write(vals)
                    to_sync |= pl
                elif pl and not base:
                    pl._manual_retire()
                handled |= pl
            (art.placement_ids - handled).filtered(
                lambda p: not p.manual_retired)._manual_retire()
        self.sudo().mapped('placement_ids')._manual_fix_canonical()
        return to_sync

    def _manual_push(self):
        """把文章推到指紋相符的方案 slide；每個 channel 一個原子單位。"""
        to_sync = self._manual_ensure_placements()
        channels = to_sync.mapped('channel_id') | self.sudo().mapped('placement_ids.channel_id')
        channels._knowledge_request_sync(to_sync)
        return True

    def _manual_apply_assets(self, binding):
        """重拍後改用繫結目前的素材——只取指紋與文章相同的（B2）。"""
        for art in self.sudo():
            assets = binding.current_assets().filtered(
                lambda a: a.scope_hash == art.fingerprint)
            art.write({'asset_ids': [(6, 0, assets.ids)], 'shot_binding_id': binding.id})

    # ------------------------------------------------------------------
    # 動作
    # ------------------------------------------------------------------
    def action_open_placements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('發佈位置'),
            'res_model': 'corpaas.knowledge.placement', 'view_mode': 'list,form',
            'domain': [('article_id', '=', self.id)],
        }

    def _manual_package(self):
        self.ensure_one()
        return (self._manual_fitting_packages() or self.placement_ids.mapped('package_id')
                or self.scenario_id.package_ids)[:1]

    def action_ai_rewrite_scenario(self):
        """重寫情境區塊：排進 AI 佇列（不在 HTTP 請求裡同步等 AI）。"""
        Ai = self.env['corpaas.knowledge.ai']
        res = True
        for art in self:
            package = art._manual_package()
            if not package:
                raise UserError(_('「%s」沒有對應的方案，無法排入 AI 作業。') % art.display_name)
            res = Ai.enqueue(art, '_manual_ai_rewrite_scenario_run', package,
                             note=_('AI 重寫情境區塊'))
        return res

    def _manual_ai_rewrite_scenario_run(self):
        """佇列作業本體：重寫情境區塊（帶入既有步驟區塊，不重寫步驟）→ 送審。"""
        hooks = self.env['corpaas.knowledge.hooks']
        for art in self:
            title, html = hooks._manual_write_scenario(
                art._manual_package(), art.scenario_id, art.feature_id, art.capability_id,
                art.step_block_ids, None)
            art.write({'scenario_html': html, 'name': title or art.name})
            art.knowledge_propose('text', note=_('AI 重寫情境區塊'))
        return True

    def action_resync(self):
        """手動重推（例如 slide 被人改壞）：只推上線中的文章。"""
        self.filtered(lambda a: a.state in ('published', 'stale'))._manual_push()
        return True
