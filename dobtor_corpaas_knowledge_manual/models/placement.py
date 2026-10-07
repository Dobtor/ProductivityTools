# -*- coding: utf-8 -*-
"""發佈位置（文章 × channel）、章節、slide.channel／slide.slide 擴充。

一個方案產品（product.template）一個文件型 channel。

☠️ slide.slide.channel_id 是必填 M2O：一張 slide 只屬於一個 channel，所以每個
  placement 各自擁有一張 slide（同一篇文章在多個 channel → 多張 slide → canonical）。
☠️ 章節是 is_category=True 的 slide，category_id 由 sequence 計算（不能直接寫）→
  每次同步整個 channel 重新編號：章節 100、200…，文章 101、102…，共通操作最後。
☠️ 原生刪章節會呼叫 _move_category_slides 把整個 channel 重編 1..n → 先把廢章節
  排到最後（底下沒有文章）再刪，刪完再套一次編號。
☠️ slide 的 is_published 寫入要 can_publish：文件型 channel 只有負責人或
  slides 管理員才有 → 一律以 channel 負責人（我們建立時是 OdooBot）身分寫。
☠️ slide.write({'is_published': True}) 每次都會重設 date_published（前台「新」標記）
  → 已上線的 slide 不再寫 is_published，只在文字實質改寫時自己重設。
☠️ html_content／name 是可翻譯欄位：寫入與讀回一律帶 lang=zh_TW（沒啟用才退回 en_US），
  否則以觸發者的語言寫進別的翻譯，前台中文頁看不到（B10）。
★ 原子發佈（營運規格）：以 channel 為單位在 savepoint 裡寫 slide、讀回比對、重新編號；
  任一張讀回不一致 → 整個 channel 回滾、維持上版，差異記在 sync_error。
★ slide 一律不刪（連結 404 比「已下架」更傷）：方案不要了 → 取消發佈＋manual_retired。
"""
import html as html_mod
import json
import re
from contextlib import contextmanager

from odoo import SUPERUSER_ID, _, api, fields, models

from ..services import manual_lib

COMMON_SECTION = '共通操作'
INDUSTRY_GROUP = '產業／方案類型'
BATCH_KEY = 'manual_sync_batch'
#: 旅程篇（D1）：章節裡至少幾篇上線的參考篇才放（兩篇以下一眼就看完，不需要導覽）
JOURNEY_MIN = 3
#: 同一個流程裡功能的先後：先進畫面，再按按鈕、開精靈，最後看報表與設定
KIND_ORDER = {'menu': 0, 'action': 0, 'client': 0, 'button': 1, 'wizard': 2, 'report': 3,
              'setting': 4, 'route': 5}
#: 章內分組：日常操作 → 報表與分析 → 設定（參考說明書：設定是導入時做一次，不跟日常操作混排）
CONFIG_WORDS = {'配置', '設定', 'Configuration', 'Settings'}
REPORT_WORDS = {'報告', '報表', '分析', 'Reporting', 'Reports'}
GROUP_DAILY, GROUP_REPORT, GROUP_CONFIG = 0, 1, 2


def article_group(feature):
    """0 日常操作、1 報表與分析、2 設定：看功能種類與選單路徑。"""
    segs = {s.strip() for s in re.split(r'[/›]', feature.menu_path or '') if s.strip()}
    if feature.kind == 'setting' or segs & CONFIG_WORDS:
        return GROUP_CONFIG
    if feature.kind == 'report' or segs & REPORT_WORDS:
        return GROUP_REPORT
    return GROUP_DAILY


@contextmanager
def sync_batch(env):
    """★ 一批（批次核准、一次 refresh）裡每個 channel 只同步＋重新編號一次。

    批次中 `_manual_push`／下架只登記要同步的位置，離開時逐 channel 一個 savepoint
    做完。重新編號整個 channel 是 O(n)，逐篇做就變成 O(n²)。已在批次中 → 沿用外層。
    """
    if env.context.get(BATCH_KEY) is not None:
        yield env
        return
    batch = {'channels': {}, 'memo': {}}
    yield env(context=dict(env.context, **{BATCH_KEY: batch}))
    Channel = env['slide.channel'].sudo()
    Placement = env['corpaas.knowledge.placement'].sudo()
    for cid, pids in batch['channels'].items():
        channel = Channel.browse(cid).exists()
        if channel:
            channel._knowledge_sync(Placement.browse(sorted(pids)).exists())


def slide_lang(env):
    """寫 slide 用的語言：zh_TW 啟用就用它，否則 en_US。"""
    return env['res.lang']._get_code('zh_TW') or 'en_US'


class ReadbackMismatch(Exception):
    """channel 內有 slide 讀回與送出不一致：觸發 savepoint 回滾。"""


class KnowledgePlacement(models.Model):
    _name = 'corpaas.knowledge.placement'
    _description = '操作說明：發佈位置'
    _order = 'channel_id, sequence, id'

    article_id = fields.Many2one('corpaas.knowledge.article', required=True,
                                 ondelete='cascade', index=True)
    channel_id = fields.Many2one('slide.channel', required=True, ondelete='cascade',
                                 index=True)
    package_id = fields.Many2one('infrastructure.solution.package', ondelete='set null',
                                 index=True)
    capability_id = fields.Many2one('corpaas.knowledge.capability', ondelete='set null',
                                    string='章節能力', help='空白＝共通操作')
    slide_id = fields.Many2one('slide.slide', ondelete='set null', readonly=True)
    sequence = fields.Integer(default=10, help='章節內排序')
    last_synced_rev = fields.Integer(readonly=True)
    text_hash = fields.Char(readonly=True, help='上次推送的文字雜湊（判斷是否重設「新」標記）')
    is_canonical = fields.Boolean(string='主要位置', copy=False,
                                  help='多個 channel 都有這篇文章時，搜尋引擎以這個為準')
    sync_error = fields.Char(readonly=True, help='寫入 slide 後讀回比對的差異')
    manual_retired = fields.Boolean(string='已從方案撤下', readonly=True, copy=False,
                                    help='方案不再有這篇（情境拿掉、功能消失…）：slide 取消發佈、不刪')
    synced_at = fields.Datetime(readonly=True)
    slide_url = fields.Char(related='slide_id.website_url', string='網址')
    slide_published = fields.Boolean(related='slide_id.is_published', string='已上線')

    _sql_constraints = [
        ('article_channel_unique', 'unique(article_id, channel_id)',
         '同一篇文章在同一個 channel 只能有一個位置'),
    ]

    def unlink(self):
        # ★ 不刪 slide：取消發佈留著（外部連結、搜尋引擎、租戶書籤）
        self._manual_unpublish_slide()
        articles = self.mapped('article_id')
        res = super().unlink()
        articles.exists().mapped('placement_ids')._manual_fix_canonical()
        return res

    # ------------------------------------------------------------------
    def _manual_fix_canonical(self):
        """每篇文章恰好一個主要位置：沿用既有的，沒有就取最先建立的。"""
        for article in self.mapped('article_id'):
            pls = article.placement_ids.sorted('id')
            if not pls:
                continue
            live = pls.filtered(lambda p: not p.manual_retired) or pls
            canon = pls.filtered('is_canonical') & live
            keep = canon[:1] or live[:1]
            (pls - keep).filtered('is_canonical').write({'is_canonical': False})
            if not keep.is_canonical:
                keep.is_canonical = True

    def action_set_canonical(self):
        self.ensure_one()
        (self.article_id.placement_ids - self).write({'is_canonical': False})
        self.is_canonical = True
        return True

    def _manual_sync_slide(self):
        """把文章內容寫進 slide，讀回比對。回傳讀回遺失的描述 list（空＝一致）。

        不處理排序（交給 channel 重新編號），也不自己回滾（交給 channel 的 savepoint）。
        """
        self.ensure_one()
        rec = self.sudo()
        now = fields.Datetime.now()
        art = rec.article_id
        channel = rec.channel_id
        publisher = channel._knowledge_publisher()
        live = art._manual_live_text()
        html = art.render_html(live=live)
        text_hash = manual_lib.text_signature(html)
        vals = {
            'name': live['name'],
            'slide_category': 'article',
            'is_preview': True,
            'html_content': html,
            'tag_ids': [(6, 0, publisher.env['slide.tag']._manual_tag_for(
                art.scenario_id).ids)],
        }
        slide = rec.slide_id.exists().with_env(publisher.env)
        if not slide:
            vals.update(channel_id=channel.id, sequence=0, is_published=True)
            slide = publisher.env['slide.slide'].create(vals)
        else:
            if not slide.is_published:
                vals['is_published'] = True
            elif rec.text_hash and rec.text_hash != text_hash:
                vals['date_published'] = now
            slide.write(vals)
        # ★ 真的讀回：清快取、以同一語言從資料庫再讀一次
        slide.flush_recordset()
        slide.invalidate_recordset(['html_content'])
        lost = manual_lib.readback_lost(html, slide.html_content)
        rec.write({'slide_id': slide.id, 'text_hash': text_hash, 'synced_at': now,
                   'sync_error': '；'.join(lost) or False})
        return lost

    def _manual_unpublish_slide(self):
        """功能消失／下架：取消發佈，不刪除（連結 404 比「已下架」頁更傷）。"""
        for rec in self.sudo():
            slide = rec.slide_id.exists()
            if slide and slide.is_published:
                slide.with_env(rec.channel_id._knowledge_publisher().env).is_published = False

    def _manual_retire(self):
        """這個方案不再有這篇：slide 取消發佈、位置標記撤下（不刪）。"""
        self._manual_unpublish_slide()
        self.sudo().filtered(lambda p: not p.manual_retired).write({'manual_retired': True})

    def _manual_is_live(self):
        self.ensure_one()
        return bool(not self.manual_retired and self.slide_id and self.slide_id.is_published)


class KnowledgeChannelSection(models.Model):
    _name = 'corpaas.knowledge.channel_section'
    _description = '操作說明：channel 章節'
    _order = 'channel_id, id'

    channel_id = fields.Many2one('slide.channel', required=True, ondelete='cascade',
                                 index=True)
    capability_id = fields.Many2one('corpaas.knowledge.capability', ondelete='cascade',
                                    help='空白＝共通操作')
    slide_id = fields.Many2one('slide.slide', ondelete='set null', readonly=True,
                               domain=[('is_category', '=', True)])
    name = fields.Char(compute='_compute_name')
    journey_slide_id = fields.Many2one('slide.slide', string='旅程篇', ondelete='set null',
                                       readonly=True,
                                       help='章節第一篇：照任務流程串起本章的參考篇（D1，規則產生）')
    journey_hash = fields.Char(readonly=True)

    @api.depends('capability_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.capability_id.name or COMMON_SECTION

    # ------------------------------------------------------------------
    # 旅程篇（D1）
    # ------------------------------------------------------------------
    @api.model
    def _manual_flow_rank(self, capability, placements):
        """{feature id: 名次}：依本章的任務流程排參考篇的先後。

        流程取能力名下的，加上含本章功能、還沒歸給別的能力的流程；使用量大的流程在前。"""
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        feats = placements.mapped('article_id.feature_id')
        flows = capability.flow_ids | Flow.search([('feature_ids', 'in', feats.ids)]).filtered(
            lambda f: not f.capability_id or f.capability_id == capability)
        rank = {}
        for flow in flows.sorted(lambda f: (-(f.usage_score or 0), f.id)):
            for f in flow.feature_ids.sorted(lambda x: (KIND_ORDER.get(x.kind, 9), x.id)):
                rank.setdefault(f.id, len(rank))
        return rank, flows

    def _manual_journey_html(self, capability, ordered, flows):
        esc = html_mod.escape
        snap = capability._last_published_snapshot() or {}
        parts = []
        for key in ('outcome', 'pain'):
            if snap.get(key):
                parts.append('<p>%s</p>' % esc(snap[key]))
                break
        feats = set(ordered.mapped('article_id.feature_id').ids)
        for flow in flows.sorted(lambda f: (-(f.usage_score or 0), f.id)):
            if not feats & set(flow.feature_ids.ids):
                continue
            steps = [s.label for s in flow.step_ids.sorted('sequence')
                     if s.on_statusbar and s.label]
            if len(steps) >= 2:
                parts.append('<p><strong>%s</strong>：%s</p>' % (
                    esc(flow.name or ''), ' → '.join(esc(x) for x in steps)))
        links = {GROUP_DAILY: [], GROUP_REPORT: [], GROUP_CONFIG: []}
        for pl in ordered:
            live = pl.article_id._manual_live_text()
            links[article_group(pl.article_id.feature_id)].append('<a href="%s">%s</a>' % (
                esc(pl.slide_id.website_url or '#'), esc(live.get('name') or '')))
        if links[GROUP_DAILY]:
            parts.append('<p>%s</p><ol>%s</ol>' % (
                esc(_('日常操作，依照做事的順序逐篇看下去：')),
                ''.join('<li>%s</li>' % x for x in links[GROUP_DAILY])))
        if links[GROUP_REPORT]:
            parts.append('<p>%s%s</p>' % (esc(_('報表與分析：')), '、'.join(links[GROUP_REPORT])))
        if links[GROUP_CONFIG]:
            parts.append('<p>%s%s</p>' % (esc(_('設定（通常只在導入時做一次）：')),
                                          '、'.join(links[GROUP_CONFIG])))
        return '<div class="o_kb_journey">%s</div>' % ''.join(parts)

    def _manual_sync_journey(self, placements, publisher, shown):
        """建立／更新本章的旅程篇 slide；不需要時取消發佈（不刪）。回傳 slide（可能空）。"""
        self.ensure_one()
        cap = self.capability_id
        slide = self.journey_slide_id.exists()
        live = placements.filtered(lambda p: p._manual_is_live())
        if not cap or not shown or len(live) < JOURNEY_MIN:
            if slide and slide.is_published:
                slide.with_env(publisher.env).is_published = False
            return slide
        _rank, flows = self._manual_flow_rank(cap, live)
        html = self._manual_journey_html(cap, live, flows)
        diagram = self._manual_journey_diagram(cap, live)
        if diagram:
            url = diagram._knowledge_public_image()
            if url:
                html = ('<p><img src="%s" alt="%s" style="max-width:100%%"/></p>' % (
                    url, html_mod.escape(_('%s 主線流程圖') % cap.name))) + html
        name = _('%s：整體流程') % ((cap._last_published_snapshot() or {}).get('name') or cap.name)
        text_hash = manual_lib.text_signature(name + html)
        vals = {'name': name, 'slide_category': 'article', 'is_preview': True,
                'html_content': html}
        if not slide:
            slide = publisher.env['slide.slide'].create(
                dict(vals, channel_id=self.channel_id.id, sequence=0, is_published=True))
        else:
            slide = slide.with_env(publisher.env)
            if not slide.is_published:
                vals['is_published'] = True
            elif self.journey_hash == text_hash:
                vals = {}
            else:
                vals['date_published'] = fields.Datetime.now()
            if vals:
                slide.write(vals)
        self.write({'journey_slide_id': slide.id, 'journey_hash': text_hash})
        if diagram:
            # dobtor_bpmn 的「嵌入於」：設計圖上看得到它用在哪篇文章
            Embed = self.env['bpmn.diagram.embed'].sudo()
            if not Embed.search_count([('diagram_id', '=', diagram.id),
                                       ('res_model', '=', 'slide.slide'),
                                       ('res_id', '=', slide.id)]):
                Embed.create({'diagram_id': diagram.id, 'res_model': 'slide.slide',
                              'res_id': slide.id})
        return slide

    def _manual_journey_diagram(self, capability, placements):
        """這個章節（能力×方案）最新版的主線設計圖。"""
        package = placements.mapped('package_id')[:1]
        if not package:
            return self.env['bpmn.diagram']
        return self.env['bpmn.diagram'].sudo().search([
            ('knowledge_capability_id', '=', capability.id),
            ('knowledge_package_id', '=', package.id),
            ('knowledge_scope', '=', 'capability')], order='version desc, id desc', limit=1)

    # ☠️ capability_id 可為 NULL，SQL UNIQUE 擋不住「兩個共通操作」→ 由
    #   _knowledge_section_for 先查再建，不靠約束。


class SlideTag(models.Model):
    _inherit = 'slide.tag'

    @api.model
    def _manual_tag_for(self, scenario):
        if not scenario:
            return self.browse()
        name = _('情境：%s') % scenario.name
        tag = self.sudo().search([('name', '=', name)], limit=1)
        return tag or self.sudo().create({'name': name})


class SlideChannel(models.Model):
    _inherit = 'slide.channel'

    knowledge_product_tmpl_id = fields.Many2one(
        'product.template', string='方案產品', index=True, ondelete='set null', copy=False,
        help='方案知識：一個方案產品一個說明 channel')
    knowledge_managed = fields.Boolean(string='由方案知識管理', copy=False,
                                       help='內容與排序由系統同步；手動改動會被覆蓋')
    knowledge_placement_ids = fields.One2many('corpaas.knowledge.placement', 'channel_id')
    knowledge_section_ids = fields.One2many('corpaas.knowledge.channel_section',
                                            'channel_id')

    _sql_constraints = [
        ('knowledge_tmpl_unique', 'unique(knowledge_product_tmpl_id)',
         '每個方案產品只能有一個說明 channel'),
    ]

    def _knowledge_publisher(self):
        """以 channel 負責人身分（sudo）、zh_TW 語言操作 slide：can_publish 才會成立。"""
        self.ensure_one()
        user = self.sudo().user_id or self.env['res.users'].browse(SUPERUSER_ID)
        return self.with_user(user).sudo().with_context(lang=slide_lang(self.env))

    def _knowledge_request_sync(self, placements=None):
        """同步這些 channel（placements 只取屬於各 channel 的；空＝只重新編號）。

        批次中只登記，離開批次時統一做；不在批次就立刻做。
        """
        placements = placements or self.env['corpaas.knowledge.placement']
        batch = self.env.context.get(BATCH_KEY)
        for channel in self.sudo():
            mine = placements.filtered(lambda p: p.channel_id == channel)
            if batch is not None:
                batch['channels'].setdefault(channel.id, set()).update(mine.ids)
            else:
                channel._knowledge_sync(mine)
        return True

    def _knowledge_sync(self, placements):
        """★ 原子發佈：一個 channel 一個 savepoint。讀回不一致 → 整個 channel 回滾。

        成功才把 last_synced_rev 設成文章的上線修訂；失敗的位置留著 sync_error、
        last_synced_rev 不動，下一次 refresh 會重推（_manual_refresh_article）。
        """
        self.ensure_one()
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        placements = placements.sudo()
        errors = {}
        try:
            with self.env.cr.savepoint():
                for pl in placements:
                    lost = pl._manual_sync_slide()
                    if lost:
                        errors[pl.id] = lost
                self._knowledge_renumber()
                if errors:
                    raise ReadbackMismatch()
                for pl in placements:
                    if pl.last_synced_rev != pl.article_id.published_rev_no:
                        pl.last_synced_rev = pl.article_id.published_rev_no
        except ReadbackMismatch:
            for pid, lost in errors.items():
                Placement.browse(pid).write({'sync_error': '；'.join(lost)})
            (placements - Placement.browse(list(errors))).write(
                {'sync_error': _('同 channel 另一篇讀回不一致，整批維持上版')})
            return False
        return True

    def _knowledge_industry_tag_names(self):
        """產業／方案類型標籤：方案產品的 CorPaaS 標籤。

        ☠️ dobtor_corpaas_product 的 tag_ids（CorPaaS 標籤）定義在 product.product（變體）上，
          不是 template；template 上只有原生的 product_tag_ids。
        """
        self.ensure_one()
        tmpl = self.sudo().knowledge_product_tmpl_id
        if not tmpl:
            return []
        names = []
        if 'tag_ids' in self.env['product.product']._fields:
            names = tmpl.with_context(active_test=False).product_variant_ids.mapped(
                'tag_ids.name')
        if not names and 'product_tag_ids' in tmpl._fields:
            names = tmpl.product_tag_ids.mapped('name')
        return sorted({n for n in names if n})

    def _knowledge_sync_industry_tags(self):
        """層級對應：slide.channel.tag.group「產業／方案類型」＋方案產品的標籤 → /slides/all 可篩選。"""
        Group = self.env['slide.channel.tag.group'].sudo()
        Tag = self.env['slide.channel.tag'].sudo()
        for channel in self.sudo():
            names = channel._knowledge_industry_tag_names()
            group = Group.search([('name', '=', INDUSTRY_GROUP)], limit=1)
            if not group:
                if not names:
                    continue
                group = Group.create({'name': INDUSTRY_GROUP})
            wanted = Tag
            for name in names:
                wanted |= Tag.search([('group_id', '=', group.id), ('name', '=', name)],
                                     limit=1) or Tag.create({'name': name, 'group_id': group.id})
            ours = channel.tag_ids.filtered(lambda t: t.group_id == group)
            if ours != wanted:
                channel.tag_ids = [(3, t.id) for t in ours - wanted] + \
                    [(4, t.id) for t in wanted - ours]

    @api.model
    def _knowledge_channel_for(self, product_tmpl):
        channel = self.sudo().with_context(active_test=False).search(
            [('knowledge_product_tmpl_id', '=', product_tmpl.id)], limit=1)
        if channel:
            channel._knowledge_sync_industry_tags()
            return channel
        # ★ 以 OdooBot 建立：負責人＝OdooBot，之後 slide 發佈權限不看觸發者是誰。
        channel = self.with_user(SUPERUSER_ID).create({
            'name': _('%s 操作說明') % product_tmpl.name,
            'channel_type': 'documentation',
            'visibility': 'public',
            'enroll': 'public',
            'promote_strategy': 'none',
            'allow_comment': False,
            'is_published': True,
            'knowledge_product_tmpl_id': product_tmpl.id,
            'knowledge_managed': True,
        })
        channel = self.sudo().browse(channel.id)
        channel._knowledge_sync_industry_tags()
        return channel

    def _knowledge_section_for(self, capability):
        self.ensure_one()
        Section = self.env['corpaas.knowledge.channel_section'].sudo()
        section = Section.search([('channel_id', '=', self.id), ('kind', '=', 'chapter'),
                                  ('capability_id', '=', capability.id or False)], limit=1)
        name = capability.name or COMMON_SECTION
        publisher = self._knowledge_publisher()
        slide = section.slide_id.exists()
        if not slide:
            slide = publisher.env['slide.slide'].create({
                'name': name, 'channel_id': self.id, 'is_category': True, 'sequence': 0})
        elif slide.name != name:
            slide.with_env(publisher.env).name = name
        if not section:
            section = Section.create({'channel_id': self.id, 'capability_id': capability.id,
                                      'slide_id': slide.id})
        elif section.slide_id != slide:
            section.slide_id = slide
        return section

    @api.model
    def _knowledge_layout(self, groups):
        """純計算：groups {capability: placements} → ([(capability, base)], step)。

        章節依能力 sequence；共通操作（空 capability）最後。章節間距至少 100，
        一個章節超過 99 篇就放大間距，文章編號才不會跨進下一章。
        """
        caps = sorted([c for c in groups if c], key=lambda c: (c.sequence, c.name or '', c.id))
        order = caps + [c for c in groups if not c]
        # ＋5：旅程篇、觀念、情境教學、狀態速查、訊息與狀況對照
        biggest = max([len(p) for p in groups.values()] or [0]) + 5
        step = 100 * (1 + biggest // 100)
        return [(cap, (i + 1) * step) for i, cap in enumerate(order)], step

    def _knowledge_renumber(self):
        Cap = self.env['corpaas.knowledge.capability']
        Flow = self.env['corpaas.knowledge.flow']
        for channel in self.sudo():
            publisher = channel._knowledge_publisher()
            package = channel._manual_package()
            chapters, any_shown = [], False
            Slide = publisher.env['slide.slide']
            groups = {}
            for pl in channel.knowledge_placement_ids:
                groups.setdefault(pl.capability_id or Cap, channel.env[pl._name])
                groups[pl.capability_id or Cap] |= pl
            layout, step = self._knowledge_layout(groups)
            wanted, live = {}, channel.env['corpaas.knowledge.channel_section']
            for cap, base in layout:
                section = channel._knowledge_section_for(cap)
                live |= section
                wanted[section.slide_id.id] = base
                # ★ 章節底下全部撤下／未發佈 → 章節也不發佈（空章節不出現在前台）
                shown = any(pl._manual_is_live() for pl in groups[cap])
                sec_slide = section.slide_id.with_env(publisher.env)
                if sec_slide.is_published != shown:
                    sec_slide.is_published = shown
                # ★ 章內依任務流程排（D1）：先進畫面、再按鈕與精靈、最後報表；不在流程上的照舊
                rank, flows = section._manual_flow_rank(cap, groups[cap]) if cap else ({}, Flow)
                ordered = groups[cap].sorted(lambda p: (
                    article_group(p.article_id.feature_id),
                    rank.get(p.article_id.feature_id.id, 10 ** 6), p.sequence,
                    p.article_id.name or '', p.id)).filtered('slide_id')
                journey = section._manual_sync_journey(ordered, publisher, shown)
                start = 1
                if journey:
                    wanted[journey.id] = base + 1
                    start = 2
                # 先懂這幾個觀念（能力上線快照，AI 起草送審）：整體流程之後
                concept = section._manual_sync_concept(publisher, shown) if cap else None
                if concept:
                    wanted[concept.id] = base + start
                    start += 1
                # 情境教學：整體流程之後、參考篇之前（同一張單據一路做完）
                tutorial = section._manual_sync_tutorial(flows, package, groups[cap], publisher,
                                                         shown) if cap else None
                if tutorial:
                    wanted[tutorial.id] = base + start
                    start += 1
                for j, pl in enumerate(ordered, start=start):
                    wanted[pl.slide_id.id] = base + j
                # 章末：狀態速查、訊息與狀況對照（規則產生）
                after = start + len(ordered)
                for k, gslide in enumerate(section._manual_sync_chapter_guides(
                        flows, package, publisher, shown)):
                    wanted[gslide.id] = base + after + k
                if shown:
                    any_shown = True
                    live_pls = groups[cap].filtered(lambda p: p._manual_is_live())
                    first = journey if journey and journey.is_published else \
                        ordered.filtered(lambda p: p._manual_is_live())[:1].slide_id
                    chapters.append((section, first, live_pls))
            # 開始之前：本說明怎麼用、開始前必設定（排在所有章節前面）
            if package:
                front = channel._manual_front_section()
                live |= front
                wanted[front.slide_id.id] = 1
                fslide = front.slide_id.with_env(publisher.env)
                if fslide.is_published != any_shown:
                    fslide.is_published = any_shown
                setup = front._manual_upsert_guide(
                    'setup', channel._manual_setup_html(package), publisher, any_shown)
                howto = front._manual_upsert_guide(
                    'howto', channel._manual_howto_html(package, chapters, setup), publisher,
                    any_shown)
                for k, gslide in enumerate(x for x in (howto, setup) if x):
                    wanted[gslide.id] = 2 + k
            obsolete = channel.knowledge_section_ids - live
            tail = (len(layout) + 1) * step * 1000
            spare = iter(range(tail + len(obsolete), tail + 10 ** 6))
            for k, section in enumerate(obsolete):
                if section.slide_id:
                    wanted[section.slide_id.id] = tail + k
                # 旅程篇與規則頁跟其他 slide 一樣不刪：取消發佈、排到最後
                for extra in (section.journey_slide_id | section.guide_slide_ids.mapped(
                        'slide_id')).exists():
                    if extra.is_published:
                        extra.with_env(publisher.env).is_published = False
                    wanted[extra.id] = next(spare)

            channel._knowledge_write_sequences(Slide, wanted)
            if obsolete:
                Slide.flush_model()
                doomed = obsolete.mapped('slide_id').with_env(publisher.env).exists()
                obsolete.unlink()
                doomed.unlink()
                for sid in doomed.ids:
                    wanted.pop(sid, None)
                channel._knowledge_write_sequences(Slide, wanted)

    @api.model
    def _knowledge_write_sequences(self, Slide, wanted):
        """一條 SQL 寫完整個 channel 的 sequence。

        ☠️ 逐張 slide.sequence = n 是一張一個 UPDATE，而且每次都讓整個 channel 的
          category_id 重算。SQL 寫完要清快取＋modified()，category_id 才會跟著重算。
        """
        slides = Slide.browse(list(wanted)).exists()
        changed = {s.id: wanted[s.id] for s in slides if s.sequence != wanted[s.id]}
        if not changed:
            return
        Slide.flush_model(['sequence'])
        self.env.cr.execute(
            "UPDATE slide_slide s SET sequence = (m.value)::int "
            "FROM jsonb_each_text(%s::jsonb) m WHERE s.id = (m.key)::int",
            (json.dumps({str(k): v for k, v in changed.items()}),))
        touched = Slide.browse(list(changed))
        touched.invalidate_recordset(['sequence'])
        touched.modified(['sequence'])

    def action_knowledge_renumber(self):
        self._knowledge_renumber()
        return True


class SlideSlide(models.Model):
    _inherit = 'slide.slide'

    def _knowledge_canonical_url(self):
        """slide 頁 <head> 的 canonical：同文章的主要位置那張 slide。

        不是方案知識的 slide 回 False（沿用 website 預設 canonical）。
        """
        self.ensure_one()
        placement = self.env['corpaas.knowledge.placement'].sudo().search(
            [('slide_id', '=', self.id)], limit=1)
        if not placement:
            return False
        canon = placement.article_id.placement_ids.filtered('is_canonical')[:1]
        slide = canon.slide_id.sudo() if canon else self.env['slide.slide']
        if not slide or not slide.is_published:
            slide = self.sudo()
        return slide.website_url
