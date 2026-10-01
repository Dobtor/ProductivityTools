# -*- coding: utf-8 -*-
import logging
import time
from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from ..models.placement import INDUSTRY_GROUP, slide_lang
from .common import ManualCase

_READBACK = ('odoo.addons.dobtor_corpaas_knowledge_manual.services.manual_lib.'
             'readback_lost')
_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestSlideSync(ManualCase):

    def _seq(self, slide):
        slide.invalidate_recordset()
        return slide.sequence

    def test_channel_created_as_documentation(self):
        Tag = self.env['product.tag'].sudo()
        tag = Tag.create({'name': 'KB 教育訓練'})
        if 'tag_ids' in self.env['product.product']._fields:
            self.tmpl.product_variant_ids.write({'tag_ids': [(4, tag.id)]})
        else:
            self.tmpl.product_tag_ids = [(4, tag.id)]
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        channel = self._channel()
        self.assertEqual(len(channel), 1)
        self.assertEqual(channel.channel_type, 'documentation')
        self.assertEqual(channel.visibility, 'public')
        self.assertEqual(channel.enroll, 'public')
        self.assertEqual(channel.promote_strategy, 'none')
        self.assertTrue(channel.is_published)
        self.assertTrue(channel.knowledge_managed)
        # 層級對應：產業／方案類型 → slide.channel.tag（群組）＋方案產品的 CorPaaS 標籤
        industry = channel.tag_ids.filtered(lambda t: t.group_id.name == INDUSTRY_GROUP)
        self.assertEqual(industry.mapped('name'), ['KB 教育訓練'])

    def test_renumber_sections_and_articles(self):
        a1 = self._article(self.f1, self.cap_a, name='A1')
        a2 = self._article(self.f2, self.cap_a, name='A2')
        b1 = self._article(self.f3, self.cap_b, name='B1')
        c1 = self._article(self.f4, None, name='C1')
        self._publish(c1, b1, a2, a1)
        channel = self._channel()
        sections = {s.capability_id: s.slide_id for s in channel.knowledge_section_ids}
        slide = {a: a.placement_ids.slide_id for a in (a1, a2, b1, c1)}
        self.assertEqual(self._seq(sections[self.cap_a]), 100)
        self.assertEqual(self._seq(slide[a1]), 101)
        self.assertEqual(self._seq(slide[a2]), 102)
        self.assertEqual(self._seq(sections[self.cap_b]), 200)
        self.assertEqual(self._seq(slide[b1]), 201)
        common = channel.knowledge_section_ids.filtered(lambda s: not s.capability_id).slide_id
        self.assertEqual(common.name, '共通操作')
        self.assertEqual(self._seq(common), 300, '共通操作排最後')
        self.assertEqual(self._seq(slide[c1]), 301)
        self.assertEqual(slide[a2].category_id, sections[self.cap_a])
        self.assertEqual(slide[b1].category_id, sections[self.cap_b])
        self.assertEqual(slide[c1].category_id, common)
        for s in slide.values():
            self.assertTrue(s.is_preview, '非成員只能開 is_preview 的 slide')
            self.assertTrue(s.is_published)
            self.assertEqual(s.slide_category, 'article')
            self.assertIn('情境：協會年會', s.tag_ids.mapped('name'))

        self.cap_b.sequence = 1
        channel._knowledge_renumber()
        self.assertEqual(self._seq(sections[self.cap_b]), 100)
        self.assertEqual(self._seq(slide[b1]), 101)
        self.assertEqual(self._seq(sections[self.cap_a]), 200)
        self.assertEqual(self._seq(slide[a1]), 201)

    def test_obsolete_section_removed_without_scrambling(self):
        a1 = self._article(self.f1, self.cap_a, name='A1')
        b1 = self._article(self.f3, self.cap_b, name='B1')
        self._publish(a1, b1)
        channel = self._channel()
        old_section = channel.knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_b).slide_id
        # f3 改成「沒有能力」的圈選 → 章節依方案的候選決定 → 共通操作
        self.cap_b.feature_ids = [(5,)]
        self.env['corpaas.knowledge.selection'].sudo().create({
            'package_id': self.pkg.id, 'kind': 'feature', 'feature_id': self.f3.id,
            'state': 'approved'})
        b1._manual_push()
        self.assertFalse(old_section.exists(), '空章節要刪掉')
        common = channel.knowledge_section_ids.filtered(lambda s: not s.capability_id).slide_id
        self.assertEqual(self._seq(a1.placement_ids.slide_id), 101)
        self.assertEqual(self._seq(common), 200)
        b_slide = b1.placement_ids.slide_id
        self.assertEqual(self._seq(b_slide), 201)
        self.assertEqual(b_slide.category_id, common)

    def test_html_content_and_anchor(self):
        art = self._article(self.f1, self.cap_a)
        asset = self._asset(self.f1, 'main', regions=[{'n': 1, 'x': 1, 'y': 1, 'w': 5, 'h': 5}])
        art.asset_ids = [(6, 0, asset.ids)]
        self._publish(art)
        pl = art.placement_ids
        html = pl.slide_id.html_content
        block = art.step_block_ids
        self.assertIn('id="%s"' % block.anchor, html)
        self.assertIn('id="%s-1"' % block.anchor, html)
        self.assertIn('img-fluid rounded border', html)
        self.assertIn('s_alert alert alert-info', html)
        self.assertNotIn('[[shot', html)
        self.assertFalse(pl.sync_error, pl.sync_error)
        self.assertEqual(pl.last_synced_rev, art.rev_no)
        self.assertEqual(art.manual_live_asset_ids, asset)

    def test_slide_written_in_zh_tw(self):
        """B10：slide 一律以 zh_TW 寫與讀回（沒啟用就 en_US）。"""
        self.assertEqual(slide_lang(self.env),
                         self.env['res.lang']._get_code('zh_TW') or 'en_US')
        self.env['res.lang']._activate_lang('zh_TW')
        self.assertEqual(slide_lang(self.env), 'zh_TW')
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        slide = art.placement_ids.slide_id
        self.assertIn('會員報名前要先建立年會', slide.with_context(lang='zh_TW').html_content)
        self.assertEqual(slide.with_context(lang='zh_TW').name, art.name)

    def test_readback_mismatch_rolls_back_channel(self):
        """讀回不一致 → 整個 channel 維持上版（savepoint 回滾），差異記在 sync_error。"""
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        slide = art.placement_ids.slide_id
        before = slide.html_content
        art.scenario_html = '<p>完全不同的情境說明。</p>'
        with patch(_READBACK, return_value=['圖片']):
            art._do_publish('text')
        slide.invalidate_recordset()
        self.assertEqual(slide.html_content, before, '讀回不一致不能留下半套內容')
        self.assertIn('圖片', art.placement_ids.sync_error)
        art.action_resync()
        self.assertIn('完全不同', slide.html_content)
        self.assertFalse(art.placement_ids.sync_error)

    def test_date_published_only_on_text_change(self):
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        slide = art.placement_ids.slide_id
        old = datetime(2020, 1, 1)
        slide.sudo().date_published = old
        art._do_publish('shot')
        self.assertEqual(slide.date_published, old, '純重拍不重設「新」標記')
        art.scenario_html = '<p>完全不同的情境說明。</p>'
        art._do_publish('text')
        self.assertGreater(slide.date_published, old)

    def test_unreviewed_block_never_rendered(self):
        """B3：從沒上線的步驟區塊不上前台；引用它的文章不能發佈，要一起核准。"""
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        fresh = self._block(self.f1, html='<h4>新步驟</h4><p>還沒審的文字</p>')
        fresh.knowledge_propose('new')
        art.step_block_ids = [(4, fresh.id)]
        self.assertNotIn('還沒審的文字', art.render_html())
        self.assertIn('還沒審的文字', art.render_html(preview=True))
        with self.assertRaises(UserError):
            art._do_publish('shot')
        art.knowledge_reshoot_done()
        self.assertEqual(art.state, 'review', '純重拍也不能把新區塊帶上線')
        # 已上線的區塊被改（待核）→ 前台用上線快照
        live = art.step_block_ids - fresh
        live.html = '<h4>開啟</h4><p>未審改寫</p>'
        live.knowledge_propose('text')
        self.assertNotIn('未審改寫', art.render_html())
        # 核准文章 → 一起送審的新區塊一起核准
        art.with_user(self.approver).action_approve()
        self.assertEqual(fresh.state, 'published')
        self.assertEqual(art.state, 'published')
        self.assertIn('還沒審的文字', art.placement_ids.slide_id.html_content)
        self.assertNotIn('未審改寫', art.placement_ids.slide_id.html_content)

    def test_review_counter_for_waiver(self):
        """B4：文章核准且核准者沒改文字 → 情境計數 +1；改過或退回 → 歸零。"""
        art = self._article(self.f1, self.cap_a)
        art.knowledge_propose('new')
        art.with_user(self.approver).action_approve()
        self.assertEqual(self.scenario.clean_approvals, 1)
        art.scenario_html = '<p>改一下</p>'
        art.knowledge_propose('text')
        art.with_user(self.approver).action_approve()
        self.assertEqual(self.scenario.clean_approvals, 2)
        art.scenario_html = '<p>再改</p>'
        art.knowledge_propose('text')
        art.scenario_html = '<p>核准者自己又改了</p>'
        art.with_user(self.approver).action_approve()
        self.assertEqual(self.scenario.clean_approvals, 0)
        art.scenario_html = '<p>第三版</p>'
        art.knowledge_propose('text')
        art.with_user(self.approver).action_approve()
        art.scenario_html = '<p>第四版</p>'
        art.knowledge_propose('text')
        art.with_user(self.approver).action_reject(reason='不對')
        self.assertEqual(self.scenario.clean_approvals, 0)

    def test_retire_unpublishes_not_deletes(self):
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        slide = art.placement_ids.slide_id
        self.f1.write({'package_ids': [(3, self.pkg.id)],
                       'missing_package_ids': [(4, self.pkg.id)]})
        self.hooks._knowledge_feature_gone(self.f1)
        self.assertEqual(art.state, 'retired')
        self.assertTrue(slide.exists())
        self.assertFalse(slide.is_published)
        art.placement_ids.unlink()
        self.assertTrue(slide.exists(), '位置刪了也不刪 slide')

    def test_empty_chapter_hidden_and_scenario_dropped(self):
        a1 = self._article(self.f1, self.cap_a, name='A1')
        b1 = self._article(self.f3, self.cap_b, name='B1')
        self._publish(a1, b1)
        channel = self._channel()
        sec_b = channel.knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_b).slide_id
        self.assertTrue(sec_b.is_published)
        # 方案不再圈選 f3 → 位置撤下（不刪），章節空了 → 章節不發佈
        self.cap_b.feature_ids = [(5,)]
        self.hooks._manual_retire_orphans(self.pkg)
        b_slide = b1.placement_ids.slide_id
        self.assertTrue(b1.placement_ids.manual_retired)
        self.assertTrue(b_slide.exists())
        self.assertFalse(b_slide.is_published)
        self.assertFalse(sec_b.is_published, '空章節不出現在前台')
        self.assertEqual(b1.state, 'published', '文章本身不下架（別的方案可能還在用）')
        # 方案拿掉情境 → 撤下
        self.scenario.package_ids = [(3, self.pkg.id)]
        self.hooks._manual_retire_orphans(self.pkg)
        self.assertTrue(a1.placement_ids.manual_retired)
        self.assertTrue(a1.placement_ids.slide_id.exists())
        self.assertFalse(a1.placement_ids.slide_id.is_published)

    def test_canonical_is_first_placement(self):
        pkg2 = self._new_package('KB Plan 2')
        art = self._article(self.f1, self.cap_a)
        self.scenario.package_ids = [(3, pkg2.id)]
        self._publish(art)
        first = art.placement_ids
        self.scenario.package_ids = [(4, pkg2.id)]
        art._manual_push()
        self.assertEqual(len(art.placement_ids), 2)
        second = art.placement_ids - first
        self.assertTrue(first.is_canonical)
        self.assertFalse(second.is_canonical)
        self.assertEqual(second.channel_id, self._channel(pkg2.product_tmpl_id))
        self.assertEqual(second.capability_id, self.cap_a)
        self.assertEqual(second.slide_id._knowledge_canonical_url(),
                         first.slide_id.website_url)
        self.assertEqual(first.slide_id._knowledge_canonical_url(),
                         first.slide_id.website_url)
        second.action_set_canonical()
        self.assertFalse(first.is_canonical)
        self.assertEqual(first.slide_id._knowledge_canonical_url(),
                         second.slide_id.website_url)
        other = self.env['slide.slide'].sudo().create(
            {'name': 'x', 'channel_id': first.channel_id.id, 'slide_category': 'article'})
        self.assertFalse(other._knowledge_canonical_url())
        second.unlink()
        self.assertTrue(first.is_canonical)
        # 全螢幕模板也輸出主要位置的 canonical
        view = self.env.ref(
            'dobtor_corpaas_knowledge_manual.slide_fullscreen_knowledge_canonical')
        self.assertIn('kb_canonical_url', view.arch_db)

    def test_fingerprint_mismatch_package_gets_no_new_placement(self):
        """B1：方案目前指紋≠文章指紋 → 不掛。"""
        pkg2 = self._new_package('KB Plan 3', scope_hash='h9')
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        self.assertEqual(art.placement_ids.mapped('package_id'), self.pkg)
        self.assertFalse(self._channel(pkg2.product_tmpl_id).knowledge_placement_ids)

    def _refresh(self):
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', return_value={}):
            self.hooks._knowledge_dispatch_events(
                self.pkg, self.env['corpaas.knowledge.event'], {'token': 'tok'})

    def test_readback_failure_retried_on_refresh(self):
        """核准時讀回不一致 → 位置留 sync_error、last_synced_rev 不動；下一次 refresh 重推。"""
        art = self._article(self.f1, self.cap_a)
        self._publish(art)
        pl = art.placement_ids
        slide = pl.slide_id
        synced = pl.last_synced_rev
        self.assertEqual(synced, art.published_rev_no)
        art.scenario_html = '<p>核准的新版</p>'
        art.knowledge_propose('text')
        with patch(_READBACK, return_value=['錨點 id：x']):
            art.with_user(self.approver).action_approve()
        self.assertEqual(art.state, 'published')
        self.assertIn('錨點', pl.sync_error)
        self.assertEqual(pl.last_synced_rev, synced, '失敗不能記成已同步')
        self.assertNotIn('核准的新版', slide.html_content)
        self._refresh()
        self.assertIn('核准的新版', slide.html_content)
        self.assertFalse(pl.sync_error)
        self.assertEqual(pl.last_synced_rev, art.published_rev_no)

    def test_retire_hides_emptied_chapter(self):
        a1 = self._article(self.f1, self.cap_a, name='A1')
        b1 = self._article(self.f3, self.cap_b, name='B1')
        self._publish(a1, b1)
        sec_b = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_b).slide_id
        self.assertTrue(sec_b.is_published)
        b1.with_user(self.approver).action_retire()
        self.assertFalse(b1.placement_ids.slide_id.is_published)
        self.assertFalse(sec_b.is_published, '章節底下全部下架 → 章節不出現在前台')
        self.assertTrue(a1.placement_ids.slide_id.is_published)

    def test_fork_review_diffs_against_source(self):
        """還沒上線過的分岔：審核頁比對分岔來源的上線版與母區塊，不是「全部是新的」。"""
        old_blk = self._block(self.f1, html='<h4>開啟</h4><p>第一段</p><p>OLDTOK</p>',
                              publish=True)
        old = self._article(self.f1, self.cap_a, block=old_blk)
        self._publish(old)
        new_blk = self._block(self.f1, fingerprint='h2', derived_from_id=old_blk.id,
                              html='<h4>開啟</h4><p>第一段</p><p>NEWTOK</p>')
        new_blk.knowledge_propose('new')
        fork = self._article(self.f1, self.cap_a, block=new_blk, fingerprint='h2',
                             manual_forked_from_id=old.id)
        fork.knowledge_propose('text')
        self.assertIn('文字沒有變動', fork.review_diff)
        html = fork.manual_review_html
        self.assertIn('分岔前', html)
        self.assertNotIn('（新區塊）', html)
        self.assertIn('OLD', html)
        self.assertNotIn('&amp;lt;', html, '本次那欄不能重複跳脫')

    def test_batch_approve_is_linear(self):
        """同一個 channel 一次核准多篇：每個 channel 只同步＋重新編號一次（查詢數 O(N)）。"""
        feats = self.Feature
        for i in range(60):
            feats |= self.Feature.create({
                'feature_key': 'kbtest.action:kbtest.n%s' % i, 'module': 'kbtest',
                'kind': 'action', 'anchor': 'kbtest.n%s' % i, 'name': '批次%s' % i,
                'model': 'res.partner', 'package_ids': [(6, 0, self.pkg.ids)]})
        for f in feats:
            self._fp(f, 'h1')
        self.cap_a.feature_ids = [(4, f.id) for f in feats]
        arts = self.Article
        for i, f in enumerate(feats):
            arts |= self._article(f, self.cap_a, name='批次%s' % (59 - i))
        arts.knowledge_propose('new')
        counts = []
        for batch in (arts[:10], arts[10:]):
            self.env.flush_all()
            q0, t0 = self.cr.sql_log_count, time.time()
            batch.with_user(self.approver).action_approve()
            self.env.flush_all()
            counts.append((len(batch), self.cr.sql_log_count - q0, time.time() - t0))
        for n, q, t in counts:
            _logger.info('批次核准 %s 篇：%s 次查詢、%.2f 秒（每篇 %.1f 次）', n, q, t, q / n)
        (n1, q1, _t1), (n2, q2, _t2) = counts
        self.assertEqual(set(arts.mapped('state')), {'published'})
        self.assertLess(q2 / n2, 2 * q1 / n1, '第二批（channel 已有 10 篇）每篇查詢數不能隨 channel 變大')
        self.assertLess(q2, 50 * 120, '查詢數要是 O(N)')
        slides = arts.mapped('placement_ids.slide_id')
        self.assertEqual(len(slides), 60)
        ordered = slides.sorted('sequence')
        self.assertEqual(ordered.mapped('sequence'), list(range(101, 161)))
        self.assertEqual(set(ordered.mapped('category_id.name')), {'線上報名'})
