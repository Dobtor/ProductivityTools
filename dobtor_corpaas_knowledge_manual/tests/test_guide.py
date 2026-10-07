# -*- coding: utf-8 -*-
"""說明書改善：開始之前（本說明怎麼用、開始前必設定）、章末（狀態速查、訊息與狀況對照）、
步驟寫法（開始前要先有／完成後會看到）、情境說明舉示範資料的實際數字、流程位置。"""
import json
from unittest.mock import patch

from odoo.tests.common import tagged

from ..services import guide_lib, prompts
from .common import ManualCase
from .test_hooks import FakeSandbox


@tagged('post_install', '-at_install')
class TestGuide(ManualCase):

    def setUp(self):
        super().setUp()
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        self.Ai = self.env['corpaas.knowledge.ai']

    def _flow(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        flow = Flow.create({
            'model': 'res.partner', 'model_name': '報名', 'state_field': 'kbg_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, (self.f1 | self.f2).ids)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('done', '完成')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': True})
        self.env['corpaas.knowledge.flow.transition'].sudo().create({
            'flow_id': flow.id, 'from_value': 'draft', 'to_value': 'done',
            'button_name': 'action_confirm', 'button_label': '確認',
            'button_feature_id': self.f2.id})
        self.f2.kind = 'button'
        return flow

    def _publish_three(self):
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲 建立報名'), (self.f2, '乙 報名確認'), (self.f3, '丙 收款'))]
        self._publish(*arts)
        return arts

    def _section(self):
        return self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)

    def _guide(self, section, kind):
        return section.guide_slide_ids.filtered(lambda g: g.kind == kind).slide_id

    # ------------------------------------------------------------------
    def test_front_section_first_with_howto(self):
        self._publish_three()
        channel = self._channel()
        front = self.env['corpaas.knowledge.channel_section'].search(
            [('channel_id', '=', channel.id), ('kind', '=', 'front')])
        self.assertEqual(front.name, '開始之前')
        self.assertNotIn(front, channel.knowledge_section_ids, '章節清單不含開始之前')
        howto = self._guide(front, 'howto')
        self.assertTrue(howto.is_published)
        self.assertEqual(howto.category_id, front.slide_id)
        self.assertLess(front.slide_id.sequence, self._section().slide_id.sequence,
                        '開始之前排在所有章節前面')
        self.assertIn('線上報名', howto.html_content, '列出各章')
        self.assertFalse(self._guide(front, 'setup'), '沒有探測資料就不放開始前必設定')

    def test_setup_page_from_probe_data(self):
        self.pkg.manual_setup_json = json.dumps({
            'items': [dict(guide_lib.SETUP_ITEMS[0], count=1, names=['新苗貿易'], menu='設定 › 公司',
                           ok=True),
                      dict(guide_lib.SETUP_ITEMS[2], count=0, names=[], menu='庫存 › 倉庫', ok=False)],
            'roles': [{'name': '業務', 'groups': ['銷售 / 管理員']}],
            'toggles': [{'path': '銷售 › 設定 › 報價範本', 'features': ['報價範本']}]},
            ensure_ascii=False)
        self._publish_three()
        front = self.env['corpaas.knowledge.channel_section'].search(
            [('channel_id', '=', self._channel().id), ('kind', '=', 'front')])
        setup = self._guide(front, 'setup')
        html = setup.html_content
        self.assertTrue(setup.is_published)
        for text in ('新苗貿易', '尚未設定', '沒有倉庫就無法收貨', '庫存 › 倉庫', '銷售 / 管理員',
                     '報價範本'):
            self.assertIn(text, html)
        howto = self._guide(front, 'howto')
        self.assertIn(setup.website_url, howto.html_content, '導讀連到開始前必設定')

    def test_status_page_after_articles(self):
        self._flow()
        self._publish_three()
        section = self._section()
        status = self._guide(section, 'status')
        self.assertTrue(status.is_published)
        self.assertEqual(status.name, '線上報名：狀態速查')
        self.assertIn('按「確認」→ 完成', status.html_content)
        arts = self.env['corpaas.knowledge.placement'].search(
            [('channel_id', '=', self._channel().id)]).mapped('slide_id')
        self.assertGreater(status.sequence, max(arts.mapped('sequence')), '狀態速查排在章末')
        self.assertFalse(self._guide(section, 'messages'), '沒有訊息就不放對照表')

    def test_messages_page_and_unchanged_not_rewritten(self):
        flow = self._flow()
        self.pkg.manual_messages_json = json.dumps([{
            'flow': flow.id, 'button': 'action_confirm', 'label': '確認', 'from': 'draft',
            'variant': 'empty', 'message': '請先加入至少一筆明細<b>', 'when': '在「草稿」狀態按「確認」',
            'cause': '單據沒有明細', 'fix': '回到單據加入明細後再確認'}], ensure_ascii=False)
        self._publish_three()
        msgs = self._guide(self._section(), 'messages')
        self.assertIn('請先加入至少一筆明細&lt;b&gt;', msgs.html_content, '訊息原文照樣、跳脫')
        self.assertIn('回到單據加入明細後再確認', msgs.html_content)
        stamp = msgs.date_published
        self._channel()._knowledge_renumber()
        self.assertEqual(msgs.date_published, stamp, '內容沒變不重設「新」標記')

    def test_probe_stores_data_and_skips_same_sandbox(self):
        flow = self._flow()
        sb = FakeSandbox(self.scenario)
        sb.base_sig, sb.seed_applied = 'b1', 's1'
        calls = []

        def shell(s, script):
            calls.append(script)
            if 'GROUPS' in script:
                return {'items': {'company': {'count': 1, 'names': ['新苗'], 'menu': '設定/公司'}},
                        'groups': {}}
            return [{'flow': flow.id, 'button': 'action_confirm', 'label': '確認', 'from': 'draft',
                     'variant': 'as_is', 'message': '缺少客戶'}]
        with patch.object(type(sb), '_shell', shell, create=True):
            self.assertTrue(self.hooks._manual_guide_probe(self.pkg, sb))
            self.assertFalse(self.hooks._manual_guide_probe(self.pkg, sb), '說明庫沒變不重跑')
        self.assertEqual(len(calls), 2)
        setup = json.loads(self.pkg.manual_setup_json)
        self.assertEqual(setup['items'][0]['menu'], '設定 › 公司')
        msgs = json.loads(self.pkg.manual_messages_json)
        self.assertEqual(msgs[0]['when'], '在「草稿」狀態按「確認」')

    def test_ai_fills_meanings_and_message_help(self):
        flow = self._flow()
        self.pkg.manual_messages_json = json.dumps(
            [{'flow': flow.id, 'message': '缺少客戶', 'when': '按「確認」'}], ensure_ascii=False)

        def ask(purpose, prompt, **kw):
            if purpose == 'manual_flow_meaning':
                return {'flows': [{'model': 'res.partner', 'steps': [
                    {'value': 'draft', 'meaning': '還沒確認的報名'},
                    {'value': 'done', 'meaning': '这是简体'}]}]}
            return {'items': [{'id': 0, 'cause': '報名沒有填客戶', 'fix': '回到報名填上客戶再確認'}]}
        with patch.object(type(self.Ai), 'ask', side_effect=ask):
            self.hooks._manual_guide_ai(self.pkg, 'tok', {'ai': False})
        steps = {s.value: s.meaning for s in flow.step_ids}
        self.assertEqual(steps['draft'], '還沒確認的報名')
        self.assertFalse(steps['done'], '簡體字的短文不用')
        self.assertEqual(json.loads(self.pkg.manual_messages_json)[0]['fix'], '回到報名填上客戶再確認')

    # ------------------------------------------------------------------
    def test_step_prompt_has_flow_and_finish(self):
        self._flow()
        ctx = self.hooks._manual_flow_context(self.f2)
        self.assertEqual(ctx[0]['按之後的狀態'], '完成')
        text = prompts.step_block_prompt({'name': '報名確認', 'key': 'k'}, [], [], [], flow_ctx=ctx)
        self.assertIn('完成後會看到', text)
        self.assertIn('開始前要先有', text)
        self.assertIn('按之前的狀態', text)
        screen = self.hooks._manual_flow_context(self.f1)
        self.assertEqual(screen[0]['狀態順序'], '草稿 → 完成', '入口畫面帶出狀態順序')

    def test_scenario_prompt_has_demo_values(self):
        seed = [{'xmlid': 'x.so_1', 'model': 'sale.order', 'values': {
                    'partner_id': '__ref__:x.cust', 'state': 'draft'}},
                {'xmlid': 'x.cust', 'model': 'res.partner', 'values': {'name': '宏達文具'}},
                {'xmlid': 'x.l1', 'model': 'sale.order.line', 'values': {
                    'order_id': '__ref__:x.so_1', 'product_uom_qty': 20, 'price_unit': 480}}]
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'fingerprint': 'h1', 'login_role': 'admin',
            'steps_json': '[{"shot": "main"}]'})
        self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'ok',
            'bindings_json': json.dumps({'so': 'x.so_1'})})
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: seed):
            demo = self.hooks._manual_demo_examples(self.scenario, self.f1)
            text = self.hooks._manual_scenario_prompt(self.pkg, self.scenario, self.f1,
                                                      self.cap_a, self.Block)
        self.assertEqual(demo[0]['values']['partner_id'], '宏達文具', '參照換成名稱')
        self.assertEqual(demo[0]['lines'][0]['price_unit'], 480, '帶出明細數字')
        self.assertIn('宏達文具', text)

    def test_article_shows_flow_position(self):
        self._flow()
        art = self._article(self.f2, self.cap_a, name='報名確認')
        self.assertIn('流程位置｜', art.render_html(preview=True))
        self.assertIn('草稿 →（按「確認」）→ 完成', art.render_html(preview=True))

    def test_redraft_review_rewrites_drafts(self):
        tmpl = self.env['corpaas.knowledge.shot_template'].sudo().create({
            'feature_id': self.f1.id, 'fingerprint': 'h1', 'login_role': 'admin',
            'steps_json': '[{"shot": "main"}]'})
        binding = self.env['corpaas.knowledge.shot_binding'].sudo().create({
            'template_id': tmpl.id, 'scenario_id': self.scenario.id, 'state': 'ok'})
        block = self._block(self.f1)
        block.knowledge_propose('new')
        art = self._article(self.f1, self.cap_a, block=block, shot_binding_id=binding.id)
        art.knowledge_propose('new')
        self.assertEqual(art.state, 'review')

        def ask(purpose, prompt, **kw):
            if purpose == 'manual_step_block':
                return {'title': '建立報名', 'steps': [
                    {'title': '開啟', 'html': '<p>開始前要先有：年會。</p>'},
                    {'title': '完成後會看到', 'html': '<p>報名變成草稿。</p>'}]}
            return {'title': '建立年會報名', 'html': '<p>會員宏達報名 2 人。</p>'}
        with patch.object(type(self.Ai), 'ask', side_effect=ask):
            nb, na = self.hooks._manual_redraft_review(self.pkg)
        self.assertEqual((nb, na), (1, 1))
        self.assertIn('完成後會看到', block.html)
        self.assertIn('宏達', art.scenario_html)
        self.assertEqual(art.state, 'review')


@tagged('post_install', '-at_install')
class TestTutorial(ManualCase):

    def setUp(self):
        super().setUp()
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        self.flow = Flow.create({
            'model': 'res.partner', 'model_name': '報名單', 'state_field': 'kbt_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, (self.f1 | self.f2).ids)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('sent', '已送出'), ('done', '完成'),
                                        ('cancel', '取消')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': self.flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': v != 'cancel'})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        for fr, to, name, label, opens in [('draft', 'sent', 'action_submit', '送出', False),
                                           ('draft', 'done', 'action_skip', '直接完成', False),
                                           ('sent', 'done', 'action_wizard', '精靈', 'x.wizard'),
                                           ('sent', 'done', 'action_done', '完成', False),
                                           ('done', 'draft', 'action_draft', '重設', False)]:
            T.create({'flow_id': self.flow.id, 'from_value': fr, 'to_value': to,
                      'button_name': name, 'button_label': label, 'opens_model': opens,
                      'button_feature_id': self.f2.id if name == 'action_done' else False})
        self.Tutorial = self.env['corpaas.knowledge.tutorial'].sudo()

    def test_path_follows_statusbar_without_wizards(self):
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(t.button_name, a, b) for t, a, b in path],
                         [('action_submit', 'draft', 'sent'), ('action_done', 'sent', 'done')],
                         '一步一格往下走；開精靈的、往回的不走')

    def test_path_assumes_next_state_and_skips_recorded_later(self):
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        self.flow.transition_ids.unlink()
        # 草稿沒記到按鈕；「確認」只記了從「已送出」起（實際上草稿也看得到）；「核實」終點不明
        T.create({'flow_id': self.flow.id, 'from_value': 'sent', 'to_value': 'done',
                  'button_name': 'action_confirm', 'button_label': '確認'})
        T.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': 'sent',
                  'button_name': 'print_quotation', 'button_label': '列印'})
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(t.button_name, a, b) for t, a, b in path],
                         [('action_confirm', 'draft', 'done')], '列印不走；下一格才記到的當成現在按得到')
        self.flow.transition_ids.unlink()
        T.create({'flow_id': self.flow.id, 'from_value': 'draft', 'to_value': False,
                  'button_name': 'button_validate', 'button_label': '核實'})
        path = self.Tutorial._path(self.flow)
        self.assertEqual([(a, b) for _t, a, b in path], [('draft', 'sent')], '終點不明先假設下一格')

    def test_pick_record_prefers_first_state_with_lines(self):
        seed = [{'xmlid': 'x.r1', 'model': 'res.partner', 'values': {'kbt_state': 'done'}},
                {'xmlid': 'x.r2', 'model': 'res.partner', 'values': {'name': '甲'}},
                {'xmlid': 'x.r3', 'model': 'res.partner', 'values': {'name': '乙', 'kbt_state': 'draft'}},
                {'xmlid': 'x.l', 'model': 'res.partner.line', 'values': {'p': '__ref__:x.r3'}}]
        self.assertEqual(self.Tutorial._pick_record(self.flow, seed, 'draft')['xmlid'], 'x.r3')

    def test_shoot_and_publish_tutorial(self):
        from odoo.addons.dobtor_corpaas_knowledge.services import shooter
        seed = [{'xmlid': 'x.r3', 'model': 'res.partner', 'values': {'name': '宏達報名', 'kbt_state': 'draft'}}]
        sb = FakeSandbox(self.scenario)
        sb.dirty = False
        jobs_seen = []

        def run(env, sandbox, jobs, settings):
            jobs_seen.extend(jobs)
            from .common import png
            shots = {j['id']: {'ok': True, 'images': [
                {'name': 'before', 'file': '%s/before.png' % j['id'], 'regions': []},
                {'name': 'after', 'file': '%s/after.png' % j['id']}]} for j in jobs}
            files = {}
            for j in jobs:
                files['%s/before.png' % j['id']] = png()
                files['%s/after.png' % j['id']] = png()
            return {'shots': shots}, files
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: seed), \
                patch.object(shooter, 'run_shots', run), \
                patch.object(type(self.env['res.config.settings']), 'knowledge_shot_settings',
                             lambda s: {}, create=True):
            n = self.hooks._manual_shoot_tutorials(self.pkg, sb)
            again = self.hooks._manual_shoot_tutorials(self.pkg, sb)
        self.assertEqual((n, again), (1, 0), '輸入沒變不重拍')
        self.assertEqual(len(jobs_seen), 2, '一步一個拍攝工作')
        self.assertEqual(jobs_seen[0]['steps'][4], {'click': {'button': 'action_submit'}})
        self.assertTrue(sb.dirty, '按過按鈕：說明庫要重建')
        tut = self.Tutorial.search([('flow_id', '=', self.flow.id)])
        self.assertEqual((tut.state, len(tut.steps()), tut.record_label), ('ok', 2, '宏達報名'))
        arts = [self._article(f, self.cap_a, name=nm) for f, nm in
                ((self.f1, '甲'), (self.f2, '乙 完成報名'), (self.f3, '丙'))]
        self._publish(*arts)
        section = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a)
        slide = section.guide_slide_ids.filtered(lambda g: g.kind == 'tutorial').slide_id
        self.assertTrue(slide.is_published)
        self.assertEqual(slide.name, '線上報名：情境教學')
        html = slide.html_content
        self.assertIn('第 2 步：已送出 → 完成', html)
        self.assertIn('狀態列變成「完成」', html)
        self.assertIn('乙 完成報名', html, '連到那一步的參考篇')
        self.assertIn('/web/image/%s' % tut.steps()[0]['after'], html)
        art_seqs = self.env['corpaas.knowledge.placement'].search(
            [('channel_id', '=', self._channel().id)]).mapped('slide_id.sequence')
        self.assertLess(slide.sequence, min(art_seqs), '教學排在參考篇之前')


@tagged('post_install', '-at_install')
class TestHandoff(ManualCase):

    def test_upstream_view_button_is_not_handoff(self):
        Flow = self.env['corpaas.knowledge.flow'].sudo()
        po = Flow.create({'model': 'purchase.order', 'model_name': '採購單', 'state_field': 'state',
                          'field_type': 'selection', 'package_ids': [(4, self.pkg.id)]})
        so = Flow.create({'model': 'sale.order', 'model_name': '銷售單', 'state_field': 'state',
                          'field_type': 'selection', 'package_ids': [(4, self.pkg.id)]})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        back = T.create({'flow_id': po.id, 'button_name': 'action_view_sale_orders',
                         'button_label': '銷售', 'opens_flow_id': so.id})
        fwd = T.create({'flow_id': so.id, 'button_name': 'action_view_purchase_orders',
                        'button_label': '494', 'opens_flow_id': po.id,
                        'button_feature_id': self.f3.id})
        self.assertFalse(back.is_handoff(), '採購單回頭看銷售單是查看關聯')
        self.assertTrue(fwd.is_handoff())
        self.assertEqual(fwd.display_label(), self.f3.name, '只有編號的按鈕名稱改用功能點名稱')
        self.f2.write({'model': 'purchase.order'})
        back.button_feature_id = self.f2.id
        self.assertFalse(self.hooks._manual_flow_context(self.f2), '查看上游的按鈕不寫成流程上的一步')
        self.f1.write({'model': 'purchase.order'})
        self.assertNotIn('後續單據', str(self.hooks._manual_flow_context(self.f1)))


@tagged('post_install', '-at_install')
class TestRound2(ManualCase):
    """第二輪比較的修正：歸屬看模組、章節排序、狀態速查、章內分組、角色對章節、文字檢查、觀念頁。"""

    def test_shared_feature_goes_to_module_capability(self):
        # f1 同時在 A、B；B 的功能點多數跟 f1 同模組 → 歸 B
        self.cap_b.feature_ids = [(4, self.f1.id)]
        self.f3.module = 'kbtest'
        self.f2.module = 'other'
        cands = self.hooks._manual_candidates(self.pkg)
        self.assertEqual(cands[self.f1], self.cap_b)

    def test_tidy_orders_capabilities_and_moves_flows(self):
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        self.cap_a.sequence = self.cap_b.sequence = 10
        sale = self.Feature.create({'feature_key': 'kbtest.action:so', 'module': 'sale', 'kind': 'action',
                                    'anchor': 'kbtest.so', 'name': '訂單', 'model': 'sale.order',
                                    'package_ids': [(6, 0, self.pkg.ids)]})
        stock = self.Feature.create({'feature_key': 'kbtest.action:pk', 'module': 'stock',
                                     'kind': 'action', 'anchor': 'kbtest.pk', 'name': '調撥',
                                     'model': 'stock.picking', 'package_ids': [(6, 0, self.pkg.ids)]})
        self.cap_a.feature_ids = [(6, 0, stock.ids)]
        self.cap_b.feature_ids = [(6, 0, (sale | stock).ids)]
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'sale.order', 'state_field': 'state', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)], 'feature_ids': [(6, 0, sale.ids)]})
        stats = self.pkg._knowledge_tidy_capabilities()
        self.assertEqual(flow.capability_id, self.cap_b, '銷售訂單流程歸到有 sale 模組的能力')
        self.assertEqual(stats['caps_ordered'], 2)
        self.assertLess(self.cap_b.sequence, self.cap_a.sequence, '主要模組 sale 排在 stock 前面')
        self.cap_a.sequence = 99
        self.assertFalse(self.pkg._knowledge_tidy_capabilities()['caps_ordered'], '有人排過就不動')

    def test_status_excludes_print_and_splits_cancel(self):
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'model_name': '調撥', 'state_field': 'kbr_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)]})
        for i, (v, label) in enumerate([('draft', '草稿'), ('ready', '準備好'), ('done', '完成'),
                                        ('cancel', '已取消')]):
            self.env['corpaas.knowledge.flow.step'].sudo().create({
                'flow_id': flow.id, 'sequence': i, 'value': v, 'label': label,
                'on_statusbar': v != 'cancel'})
        T = self.env['corpaas.knowledge.flow.transition'].sudo()
        for fr, to, name, label in [('ready', 'done', 'button_validate', '驗證'),
                                    ('ready', 'cancel', 'do_print_picking', '列印'),
                                    ('ready', 'cancel', 'action_cancel', '取消'),
                                    ('draft', 'ready', 'action_confirm', 'action_confirm')]:
            T.create({'flow_id': flow.id, 'from_value': fr, 'to_value': to, 'button_name': name,
                      'button_label': label})
        data = self.env['corpaas.knowledge.channel_section']._manual_status_data(flow, self.pkg)
        rows = {r['label']: r for r in data[0]['steps']}
        self.assertEqual(rows['準備好']['next'], ['按「驗證」→ 完成'])
        self.assertEqual(rows['準備好']['back'], ['按「取消」→ 已取消'], '列印不列；取消另一欄')
        self.assertFalse(rows['草稿']['next'], '方法名稱不是給人看的按鈕名稱')
        html = guide_lib.render_status(data)
        self.assertIn('取消或退回', html)

    def test_config_articles_after_daily(self):
        from ..models.placement import article_group
        self.f1.menu_path = '報名/配置/年會類型'
        self.f2.menu_path = '報名/報告/分析'
        self.assertEqual([article_group(f) for f in (self.f1, self.f2, self.f3)], [2, 1, 0])
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲 設定'), (self.f2, '乙 報表'), (self.f3, '丙 日常'))]
        self._publish(*arts)
        seq = {a.name: a.placement_ids.slide_id.sequence for a in arts}
        self.assertLess(seq['丙 日常'], seq['乙 報表'])
        self.assertLess(seq['乙 報表'], seq['甲 設定'])
        journey = self._channel().knowledge_section_ids.filtered(
            lambda s: s.capability_id == self.cap_a).journey_slide_id
        self.assertIn('設定（通常只在導入時做一次）', journey.html_content)

    def test_lint_flags_demo_name_and_prerequisite(self):
        art = self._article(self.f1, self.cap_a, name='核對宏達文具發票')
        art.step_block_ids.html = '<p>開始前要先有：至少一筆範本，才能在列表中看到範例。</p>'
        with patch.object(type(self.hooks), '_manual_seed', lambda s, sc: [
                {'xmlid': 'x.p', 'model': 'res.partner', 'values': {'name': '宏達文具'}}]):
            problems = art._manual_text_problems()
        self.assertTrue(any('示範資料名稱' in p for p in problems))
        self.assertTrue(any('開始前要先有' in p for p in problems))

    def test_concept_drafted_reviewed_then_shown(self):
        self.f3.capability_ids = [(5,)]
        self.cap_b.feature_ids = [(5,)]
        self.cap_a.feature_ids = [(6, 0, (self.f1 | self.f2 | self.f3).ids)]
        flow = self.env['corpaas.knowledge.flow'].sudo().create({
            'model': 'res.partner', 'model_name': '報名', 'state_field': 'kbc_state',
            'field_type': 'selection', 'capability_id': self.cap_a.id,
            'package_ids': [(4, self.pkg.id)]})
        for i, v in enumerate(['draft', 'done']):
            self.env['corpaas.knowledge.flow.step'].sudo().create(
                {'flow_id': flow.id, 'sequence': i, 'value': v, 'label': v, 'on_statusbar': True})
        self.cap_a._do_publish('new')
        html = '<p>報名從草稿到完成，' + '說明' * 60 + '</p>'
        with patch.object(type(self.env['corpaas.knowledge.ai']), 'ask', return_value={'html': html}):
            self.assertEqual(self.hooks._manual_draft_concepts(self.pkg, 'tok', {'ai': False}), 1)
        self.assertEqual(self.cap_a.state, 'review')
        arts = [self._article(f, self.cap_a, name=n) for f, n in
                ((self.f1, '甲'), (self.f2, '乙'), (self.f3, '丙'))]
        self._publish(*arts)
        section = self._channel().knowledge_section_ids.filtered(lambda s: s.capability_id == self.cap_a)
        self.assertFalse(section.guide_slide_ids.filtered(lambda g: g.kind == 'concept').slide_id,
                         '沒核准不出現')
        self.cap_a._do_publish('text')
        self._channel()._knowledge_renumber()
        slide = section.guide_slide_ids.filtered(lambda g: g.kind == 'concept').slide_id
        self.assertTrue(slide.is_published)
        self.assertEqual(slide.name, '線上報名：先懂這幾個觀念')
        self.assertLess(slide.sequence, min(a.placement_ids.slide_id.sequence for a in arts))
